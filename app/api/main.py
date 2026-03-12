"""FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI

from app.api.routes.system import healthz, ready, router as system_router, version
from app.application.system import db_connectivity_status as _db_connectivity_status
from app.application.system import readiness_status as _readiness_status
from app.application.system import version_payload as _version_payload
from app.core.lifecycle import lifespan
from app.core.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.service_name, lifespan=lifespan)
    application.include_router(system_router)
    return application


app = create_app()
