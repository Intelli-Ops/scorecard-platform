"""The application.

Run it with:

    cd backend
    ../.venv/Scripts/uvicorn app.main:app --reload

Then http://127.0.0.1:8000/docs for the API, which FastAPI generates from the
routes themselves.
"""
from __future__ import annotations
import shutil
import tempfile
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .api.admin_routes import router as admin_router
from .api.auth_routes import me_router, router as auth_router
from .api.run_routes import router as run_router
from .api.week_routes import router as week_router
from .config import settings
from .db import migrate
from .db.session import create_all, engine, session
from .jobs import worker
from .service import audit, auth, ratelimit


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure()
    create_all()
    worker.recover()           # builds whose process died - see worker.py
    ratelimit.purge()
    with session() as s:
        auth.purge_expired_sessions(s)
        auth.retire_unhashed_sessions(s)
    worker.start()
    yield
    worker.stop()


# The least free space, in MB, at which the data folder still counts as
# healthy: one build reads about 385 MB of uploads and writes its results.
MIN_FREE_MB = 1024


app = FastAPI(
    title="Scorecard Platform",
    description="Weekly GFS and All Providers scorecards, as a dashboard.",
    lifespan=lifespan,
    # Off on the server - see config.py.
    docs_url="/docs" if settings.api_docs else None,
    redoc_url="/redoc" if settings.api_docs else None,
    openapi_url="/openapi.json" if settings.api_docs else None,
)

# Only for a browser app served from another origin. The sign-in travels in
# an Authorization header, never a cookie, so credentials are not allowed.
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["Content-Disposition", "X-Row-Count"],
    )

# What every response tells the browser. API answers carry client figures and
# account details, so no browser or proxy may keep a copy (no-store); none of
# them is a page to be framed or a file to be sniffed into something else.
_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for k, v in _HEADERS.items():
        response.headers.setdefault(k, v)
    return response

app.include_router(auth_router)   # open - how you get a token
app.include_router(me_router)     # your own account
app.include_router(week_router)   # everything else needs one
app.include_router(run_router)
app.include_router(admin_router)  # and these need an admin


@app.get("/")
def root() -> dict:
    return {"name": "Scorecard Platform", "api": "/api"}


@app.exception_handler(audit.AuditUnavailable)
async def audit_unavailable(request: Request, exc: audit.AuditUnavailable):
    """No record, no action - see service/audit.py. 503, not 500: nothing is
    wrong with what was asked, and asking again later is the right response."""
    return JSONResponse({"detail": str(exc)}, status_code=503)


def _database_ok() -> bool:
    """Reachable, and on the schema this code expects."""
    try:
        with engine().connect() as c:
            c.execute(text("SELECT 1"))
        return migrate.revision(engine()) == migrate.head()
    except Exception:
        return False


def _storage_ok() -> bool:
    """Every folder the app writes to can actually be written to."""
    try:
        for folder in (settings.data_dir, settings.object_dir, settings.results_dir):
            with tempfile.TemporaryFile(dir=folder) as f:
                f.write(b"ok")
        return True
    except OSError:
        return False


def _disk_ok() -> bool:
    try:
        return shutil.disk_usage(settings.data_dir).free >= MIN_FREE_MB * 1024 * 1024
    except OSError:
        return False


@app.get("/api/health")
def health(response: Response) -> dict:
    """Is the app able to do its job - not merely answering.

    It answered `ok` as long as the process was up, which is the one thing a
    reply already proves. What can actually stop it working is checked: the
    database (reachable, and migrated to this code's schema), the data folders
    (writable), the disk (room for a build) and the build worker (alive).
    Anything failing makes it a 503, so `curl -f`, systemd or a load balancer
    sees the fault without reading the body.

    Public on purpose. A health check that needs credentials is not a health
    check - whatever is watching the service has to be able to ask without an
    account. It says which part is failing and nothing about the data.
    """
    checks = {"database": _database_ok(), "storage": _storage_ok(),
              "disk_space": _disk_ok(), "worker": worker.alive()}
    out: dict = {"ok": all(checks.values()), "checks": checks}
    if checks["database"]:
        out["queued_builds"] = worker.depth()
    if not out["ok"]:
        response.status_code = 503
    return out
