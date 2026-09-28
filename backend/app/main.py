"""The application.

Run it with:

    cd backend
    ../.venv/Scripts/uvicorn app.main:app --reload

Then http://127.0.0.1:8000/docs for the API, which FastAPI generates from the
routes themselves.
"""
from __future__ import annotations
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.admin_routes import router as admin_router
from .api.auth_routes import me_router, router as auth_router
from .api.routes import router
from .config import settings
from .db.session import create_all, session
from .jobs import worker
from .service import auth


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure()
    create_all()
    worker.recover()           # before the worker takes anything new
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

# The browser app is served from a different port in development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
