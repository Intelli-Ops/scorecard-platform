"""The application.

Run it with:

    cd backend
    ../.venv/Scripts/uvicorn app.main:app --reload

Then http://127.0.0.1:8000/docs for the API, which FastAPI generates from the
routes themselves.
"""
from __future__ import annotations
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .api.admin_routes import router as admin_router
from .api.auth_routes import me_router, router as auth_router
from .api.routes import router
from .config import settings
from .db.session import create_all, session
from .jobs import worker
from .service import auth, ratelimit


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure()
    create_all()
    worker.recover()           # before the worker takes anything new
    ratelimit.reset()
    with session() as s:
        auth.purge_expired_sessions(s)
        auth.retire_unhashed_sessions(s)
    worker.start()
    yield


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
app.include_router(router)        # everything else needs one
app.include_router(admin_router)  # and these need an admin


@app.get("/")
def root() -> dict:
    return {"name": "Scorecard Platform", "api": "/api"}


@app.get("/api/health")
def health() -> dict:
    """Public on purpose. A health check that needs credentials is not a health
    check - whatever is watching the service has to be able to ask without an
    account. It says nothing about the data."""
    return {"ok": True, "queued_builds": worker.depth()}
