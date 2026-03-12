"""FastAPI lifecycle hooks."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.logging import configure_logging
from app.core.settings import validate_settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    validate_settings()
    yield
