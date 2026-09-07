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

from .api.routes import router
from .config import settings
from .db.session import create_all
from .jobs import worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure()
    create_all()
    worker.start()
    yield


app = FastAPI(
    title="Scorecard Platform",
    description="Weekly GFS and All Providers scorecards, as a dashboard.",
    lifespan=lifespan,
)

# The browser app is served from a different port in development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root() -> dict:
    return {"name": "Scorecard Platform", "docs": "/docs", "api": "/api"}
