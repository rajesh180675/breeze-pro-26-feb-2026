"""Authentication lifecycle and token storage primitives."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from json import JSONDecodeError
from pathlib import Path
from typing import Callable, Protocol

from app.domain.errors import AuthenticationError

LOGGER = logging.getLogger(__name__)


def _coerce_utc(value: datetime) -> datetime:
    """Normalize legacy naive timestamps to UTC-aware datetimes."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass
class TokenRecord:
    """Token value and expiry metadata."""

    access_token: str
    issued_at: datetime
    expires_at: datetime

    @property
    def refresh_at(self) -> datetime:
        lifetime = self.expires_at - self.issued_at
        return self.issued_at + lifetime * 0.9

    def is_expired(self) -> bool:
        return datetime.now(tz=timezone.utc) >= self.expires_at

    def should_refresh(self) -> bool:
        return datetime.now(tz=timezone.utc) >= self.refresh_at


class TokenStore(Protocol):
    """Store/restore token records."""

    def load(self) -> TokenRecord | None: ...

    def save(self, token: TokenRecord) -> None: ...


class InMemoryTokenStore:
    """Simple in-process token store."""

    def __init__(self) -> None:
        self._token: TokenRecord | None = None

    def load(self) -> TokenRecord | None:
        return self._token

    def save(self, token: TokenRecord) -> None:
        self._token = token


class FileTokenStore:
    """Optional local token cache for non-ephemeral services."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def load(self) -> TokenRecord | None:
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            expires_at = _coerce_utc(datetime.fromisoformat(raw["expires_at"]))
            issued_at_raw = raw.get("issued_at")
            issued_at = (
                _coerce_utc(datetime.fromisoformat(issued_at_raw))
                if issued_at_raw
                else (expires_at - timedelta(hours=24))
            )
            return TokenRecord(
                access_token=raw["access_token"],
                issued_at=issued_at,
                expires_at=expires_at,
            )
        except (JSONDecodeError, KeyError, OSError, TypeError, ValueError) as exc:
            LOGGER.warning("token_cache_invalid", extra={"path": str(self.path), "error": str(exc)})
            return None

    def save(self, token: TokenRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "access_token": token.access_token,
                    "issued_at": token.issued_at.isoformat(),
                    "expires_at": token.expires_at.isoformat(),
                }
            ),
            encoding="utf-8",
        )
        self.path.chmod(0o600)


class AuthManager:
    """Owns token creation and refresh serialization."""

    def __init__(self, token_store: TokenStore | None = None) -> None:
        self.token_store = token_store or InMemoryTokenStore()
        self._refresh_lock = threading.Lock()

    def current(self) -> TokenRecord | None:
        return self.token_store.load()

    def authenticate(self, *, session_token: str | None) -> TokenRecord:
        """Persist a provided session token from Breeze auth flow."""

        if not session_token:
            raise AuthenticationError("Session token missing", operation="authenticate")
        now = datetime.now(tz=timezone.utc)
        record = TokenRecord(
            access_token=session_token,
            issued_at=now,
            expires_at=now + timedelta(hours=24),
        )
        self.token_store.save(record)
        return record

    def ensure_fresh_token(self, authenticator: Callable[[], TokenRecord]) -> TokenRecord:
        """Refresh token when near expiry using lock for concurrent callers."""

        record = self.token_store.load()
        if record and not record.should_refresh() and not record.is_expired():
            return record

        with self._refresh_lock:
            second = self.token_store.load()
            if second and not second.should_refresh() and not second.is_expired():
                return second
            new_record = authenticator()
            self.token_store.save(new_record)
            return new_record
