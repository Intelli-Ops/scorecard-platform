"""The FastAPI application: routers, security headers and the health check."""
from __future__ import annotations
import ipaddress
import re
import shutil
import tempfile
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .api.admin_routes import router as admin_router
from .api.auth_routes import me_router, router as auth_router
from .api.deps import refuse_upload
from .api.run_routes import router as run_router
from .api.week_routes import router as week_router
from .config import settings
from .db import migrate
from .db.session import check_schema, create_all, engine, session
from .jobs import worker
from .service import audit, auth, mail, ratelimit


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure()
    if settings.auto_migrate:
        create_all()
    else:
        check_schema()
    _health.clear()
    worker.recover()           # builds whose process died - see worker.py
    ratelimit.purge()
    with session() as s:
        auth.purge_expired_sessions(s)
        auth.retire_unhashed_sessions(s)
    worker.start()
    yield
    worker.stop()


MIN_FREE_MB = 1024


app = FastAPI(
    title="Scorecard Platform",
    description="Weekly GFS and All Providers scorecards, as a dashboard.",
    lifespan=lifespan,
    docs_url="/docs" if settings.api_docs else None,
    redoc_url="/redoc" if settings.api_docs else None,
    openapi_url="/openapi.json" if settings.api_docs else None,
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["Content-Disposition", "X-Row-Count"],
    )

_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


UPLOADS = re.compile(r"^/api/weeks/[^/]+/uploads/?$")
MAX_BODY = 1024 * 1024


def _too_big(request: Request) -> bool:
    try:
        return int(request.headers.get("content-length", "0")) > MAX_BODY
    except ValueError:
        return True


def _local(request: Request) -> bool:
    """Asked from the server itself - the installer's check, a monitor, an
    admin at the console - rather than from across the network."""
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except (AttributeError, ValueError):
        return False


@app.middleware("http")
async def security_headers(request: Request, call_next):
    https = request.url.scheme == "https"
    if settings.require_https and not https and not _local(request):
        response = JSONResponse(
            {"detail": "This server only accepts HTTPS. Open the https:// "
                       "address; if there is none yet, the certificate has "
                       "not been set up (see DEPLOY.md, 'HTTPS')."},
            status_code=400)
    elif request.method == "POST" and UPLOADS.match(request.url.path):
        refused = await run_in_threadpool(refuse_upload, request)
        if refused:
            response = JSONResponse({"detail": refused[1]}, status_code=refused[0])
        else:
            response = await call_next(request)
    elif _too_big(request):
        response = JSONResponse(
            {"detail": "That request is larger than anything this address "
                       "accepts."}, status_code=413)
    else:
        response = await call_next(request)
    for k, v in _HEADERS.items():
        response.headers.setdefault(k, v)
    if https:
        response.headers.setdefault("Strict-Transport-Security",
                                    "max-age=31536000")
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
    """503 when the activity log cannot be written, so the action is refused."""
    return JSONResponse({"detail": str(exc)}, status_code=503)


@app.exception_handler(mail.MailUnavailable)
async def mail_unavailable(request: Request, exc: mail.MailUnavailable):
    """A link that could not be mailed."""
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


HEALTH_TTL = 5.0
_health: dict = {}
_health_lock = threading.Lock()


def _checks() -> dict:
    with _health_lock:
        if not _health or time.monotonic() - _health["at"] >= HEALTH_TTL:
            checks = {"database": _database_ok(), "storage": _storage_ok(),
                      "disk_space": _disk_ok(), "worker": worker.alive()}
            _health.update(at=time.monotonic(), checks=checks,
                           queued=worker.depth() if checks["database"] else None)
        return dict(_health)


@app.get("/api/health")
def health(request: Request, response: Response) -> dict:
    """Is the app able to do its job - not merely answering."""
    state = _checks()
    ok = all(state["checks"].values())
    if not ok:
        response.status_code = 503
    if not _local(request):
        return {"ok": ok}
    out: dict = {"ok": ok, "checks": state["checks"]}
    if state["queued"] is not None:
        out["queued_builds"] = state["queued"]
    return out
