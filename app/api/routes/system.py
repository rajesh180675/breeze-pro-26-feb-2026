"""System routes for health, readiness, version, and metrics."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from app.application.system import readiness_status, version_payload
from app.infrastructure.observability.metrics import CONTENT_TYPE_LATEST, render_metrics

router = APIRouter(tags=["system"])


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@router.get("/version")
def version() -> dict:
    return version_payload()


@router.get("/ready")
def ready() -> dict:
    ok, payload = readiness_status()
    if not ok:
        raise HTTPException(status_code=503, detail=payload)
    return payload


@router.get("/metrics")
def metrics() -> PlainTextResponse:
    return PlainTextResponse(render_metrics(), media_type=CONTENT_TYPE_LATEST)
