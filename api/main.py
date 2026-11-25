"""FastAPI application entry point: `uvicorn api.main:app`."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from api.config import get_settings
from api.db import get_sessionmaker
from api.routers import admin, submissions, verify
from engine.version import ENGINE_VERSION

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# One line per source request would flood the log (hundreds per check).
logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    if s.job_runner == "inline" and not s.inline_sync:
        from api.jobs import recover_inline_jobs, start_inline_maintenance

        recover_inline_jobs()
        start_inline_maintenance()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.app_name} API",
        version=ENGINE_VERSION,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.include_router(submissions.router)
    app.include_router(verify.router)
    app.include_router(admin.router)

    @app.get("/api/health", tags=["health"])
    def health() -> dict[str, str]:
        with get_sessionmaker()() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ok", "engine_version": ENGINE_VERSION}

    return app


app = create_app()
