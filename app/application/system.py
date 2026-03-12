"""Application-facing system health and version services."""

from __future__ import annotations

import sqlite3

from app.core.settings import Settings, get_settings


def version_payload(settings: Settings | None = None) -> dict:
    current = settings or get_settings()
    return {
        "service": current.service_name,
        "version": current.app_version,
        "build": current.app_build,
        "commit": current.app_commit,
        "env": current.app_env,
    }


def db_connectivity_status(settings: Settings | None = None) -> tuple[bool, dict]:
    current = settings or get_settings()
    db_path = current.sqlite_db_path
    try:
        with sqlite3.connect(db_path, timeout=2.0) as conn:
            conn.execute("SELECT 1").fetchone()
        return True, {"db_ready": True, "db_path": db_path}
    except sqlite3.Error as exc:
        return False, {"db_ready": False, "db_path": db_path, "db_error": str(exc)}


def readiness_status(settings: Settings | None = None) -> tuple[bool, dict]:
    """Check minimum runtime dependencies required for serving traffic."""

    current = settings or get_settings()
    missing = []
    if not current.breeze_client_id:
        missing.append("BREEZE_CLIENT_ID")
    if not current.breeze_client_secret:
        missing.append("BREEZE_CLIENT_SECRET")
    if not current.breeze_session_token:
        missing.append("BREEZE_SESSION_TOKEN")
    if missing:
        return False, {"ready": False, "missing_env": missing, "db_ready": False, "reason": "missing_env"}

    db_ok, db_payload = db_connectivity_status(current)
    if not db_ok:
        payload = {"ready": False, "reason": "db_unavailable"}
        payload.update(db_payload)
        return False, payload

    return True, {"ready": True, **db_payload}
