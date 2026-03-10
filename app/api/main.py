"""FastAPI app exposing health and metrics endpoints."""

from __future__ import annotations

from contextlib import asynccontextmanager
import sqlite3

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


def _version_payload() -> dict:
    settings = get_settings()
    return {
        "service": settings.service_name,
        "version": settings.app_version,
        "build": settings.app_build,
        "commit": settings.app_commit,
        "env": settings.app_env,
    }


def _db_connectivity_status() -> tuple[bool, dict]:
    settings = get_settings()
    db_path = settings.sqlite_db_path
    try:
        with sqlite3.connect(db_path, timeout=2.0) as conn:
            conn.execute("SELECT 1").fetchone()
        return True, {"db_ready": True, "db_path": db_path}
    except sqlite3.Error as exc:
        return False, {"db_ready": False, "db_path": db_path, "db_error": str(exc)}


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
        return False, {"ready": False, "missing_env": missing, "db_ready": False, "reason": "missing_env"}

    db_ok, db_payload = _db_connectivity_status()
    if not db_ok:
        payload = {"ready": False, "reason": "db_unavailable"}
        payload.update(db_payload)
        return False, payload

    return True, {"ready": True, **db_payload}


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    yield


app = FastAPI(title="breeze-service", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/version")
def version() -> dict:
    return _version_payload()


@app.get("/ready")
def ready() -> dict:
    ok, payload = _readiness_status()
    if not ok:
        raise HTTPException(status_code=503, detail=payload)
    return payload


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest().decode("utf-8"), media_type=CONTENT_TYPE_LATEST)
