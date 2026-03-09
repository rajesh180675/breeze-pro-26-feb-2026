"""FastAPI app exposing health and metrics endpoints."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import PlainTextResponse

try:
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
except ImportError:  # pragma: no cover
    CONTENT_TYPE_LATEST = "text/plain"

    def generate_latest():
        return b""

from app.lib.config import get_settings
from app.lib.logging_config import configure_logging


def _readiness_status() -> tuple[bool, dict]:
    """Check minimum runtime dependencies required for serving traffic."""
    settings = get_settings()
    missing = []
    if not settings.breeze_client_id:
        missing.append("BREEZE_CLIENT_ID")
    if not settings.breeze_client_secret:
        missing.append("BREEZE_CLIENT_SECRET")
    if not settings.breeze_session_token:
        missing.append("BREEZE_SESSION_TOKEN")
    if missing:
        return False, {"ready": False, "missing_env": missing}
    return True, {"ready": True}


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    yield


app = FastAPI(title="breeze-service", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict:
    ok, payload = _readiness_status()
    if not ok:
        raise HTTPException(status_code=503, detail=payload)
    return payload


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest().decode("utf-8"), media_type=CONTENT_TYPE_LATEST)
