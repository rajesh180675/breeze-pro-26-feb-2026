"""Tests for app/lib/auth.py - full coverage of token stores, records, AuthManager."""
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.lib.auth import AuthManager, FileTokenStore, InMemoryTokenStore, TokenRecord
from app.lib.errors import AuthenticationError


def test_authenticate_persists_token():
    manager = AuthManager(InMemoryTokenStore())
    record = manager.authenticate(session_token="abc")
    assert record.access_token == "abc"
    assert manager.current() is not None


def test_ensure_fresh_token_refreshes_when_expired():
    store = InMemoryTokenStore()
    manager = AuthManager(store)
    past = datetime.now(tz=timezone.utc) - timedelta(hours=1)
    expired = TokenRecord(access_token="old", issued_at=past - timedelta(hours=1), expires_at=past)
    store.save(expired)
    now = datetime.now(tz=timezone.utc)
    refreshed = TokenRecord(access_token="new", issued_at=now, expires_at=now + timedelta(hours=24))
    result = manager.ensure_fresh_token(lambda: refreshed)
    assert result.access_token == "new"


def test_token_refresh_threshold_lifecycle():
    store = InMemoryTokenStore()
    manager = AuthManager(store)
    now = datetime.now(tz=timezone.utc)
    old = TokenRecord(
        access_token="aging",
        issued_at=now - timedelta(hours=22),
        expires_at=now + timedelta(hours=2),
    )
    store.save(old)
    fresh = TokenRecord(access_token="fresh", issued_at=now, expires_at=now + timedelta(hours=24))
    result = manager.ensure_fresh_token(lambda: fresh)
    assert result.access_token == "fresh"


def test_token_record_is_expired():
    past = datetime.now(tz=timezone.utc) - timedelta(seconds=1)
    rec = TokenRecord(access_token="x", issued_at=past - timedelta(hours=1), expires_at=past)
    assert rec.is_expired()


def test_token_record_not_expired():
    now = datetime.now(tz=timezone.utc)
    rec = TokenRecord(access_token="x", issued_at=now, expires_at=now + timedelta(hours=23))
    assert not rec.is_expired()


def test_token_record_refresh_at_before_expires_at():
    now = datetime.now(tz=timezone.utc)
    rec = TokenRecord(access_token="x", issued_at=now, expires_at=now + timedelta(hours=10))
    assert rec.refresh_at < rec.expires_at


def test_in_memory_store_initially_empty():
    assert InMemoryTokenStore().load() is None


def test_in_memory_store_round_trip():
    store = InMemoryTokenStore()
    now = datetime.now(tz=timezone.utc)
    rec = TokenRecord(access_token="tok", issued_at=now, expires_at=now + timedelta(hours=1))
    store.save(rec)
    assert store.load().access_token == "tok"


def test_file_token_store_missing_returns_none():
    with tempfile.TemporaryDirectory() as d:
        assert FileTokenStore(str(Path(d) / "missing.json")).load() is None


def test_file_token_store_round_trip():
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "tok.json")
        store = FileTokenStore(path)
        now = datetime.now(tz=timezone.utc)
        rec = TokenRecord(access_token="ft", issued_at=now, expires_at=now + timedelta(hours=8))
        store.save(rec)
        loaded = store.load()
        assert loaded is not None
        assert loaded.access_token == "ft"


def test_file_token_store_handles_missing_issued_at():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "tok.json"
        expires = (datetime.now(tz=timezone.utc) + timedelta(hours=1)).isoformat()
        p.write_text(json.dumps({"access_token": "legacy", "expires_at": expires}))
        loaded = FileTokenStore(str(p)).load()
        assert loaded.access_token == "legacy"


def test_file_token_store_creates_parent_dirs():
    with tempfile.TemporaryDirectory() as d:
        nested = str(Path(d) / "a" / "b" / "tok.json")
        store = FileTokenStore(nested)
        now = datetime.now(tz=timezone.utc)
        store.save(TokenRecord(access_token="n", issued_at=now, expires_at=now + timedelta(hours=1)))
        assert Path(nested).exists()


def test_auth_manager_raises_on_empty_token():
    with pytest.raises(AuthenticationError):
        AuthManager().authenticate(session_token=None)


def test_auth_manager_raises_on_blank_string():
    with pytest.raises(AuthenticationError):
        AuthManager().authenticate(session_token="")


def test_auth_manager_authenticate_saves():
    store = InMemoryTokenStore()
    AuthManager(token_store=store).authenticate(session_token="t")
    assert store.load().access_token == "t"


def test_ensure_fresh_skips_refresh_when_valid():
    now = datetime.now(tz=timezone.utc)
    valid = TokenRecord(access_token="v", issued_at=now, expires_at=now + timedelta(hours=23))
    mgr = AuthManager()
    mgr.token_store.save(valid)
    calls = []
    result = mgr.ensure_fresh_token(lambda: calls.append(1) or valid)
    assert result.access_token == "v"
    assert calls == []


def test_auth_manager_current_none_before_auth():
    assert AuthManager().current() is None
