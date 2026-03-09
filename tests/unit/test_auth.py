from datetime import datetime, timedelta, timezone

from app.lib.auth import AuthManager, InMemoryTokenStore, TokenRecord


def test_authenticate_persists_token():
    manager = AuthManager(InMemoryTokenStore())
    record = manager.authenticate(session_token="abc")
    assert record.access_token == "abc"
    assert manager.current() is not None


def test_ensure_fresh_token_refreshes_when_expired():
    store = InMemoryTokenStore()
    now = datetime.now(tz=timezone.utc)
    store.save(
        TokenRecord(
            access_token="old",
            issued_at=now - timedelta(hours=24),
            expires_at=now - timedelta(seconds=1),
        )
    )
    manager = AuthManager(store)

    def refresher():
        now = datetime.now(tz=timezone.utc)
        return TokenRecord(
            access_token="new",
            issued_at=now,
            expires_at=now + timedelta(hours=1),
        )

    record = manager.ensure_fresh_token(refresher)
    assert record.access_token == "new"


def test_token_refresh_threshold_lifecycle():
    now = datetime.now(tz=timezone.utc)
    token_50 = TokenRecord(
        access_token="t",
        issued_at=now - timedelta(hours=5),
        expires_at=now + timedelta(hours=5),
    )
    assert token_50.should_refresh() is False

    token_90 = TokenRecord(
        access_token="t",
        issued_at=now - timedelta(hours=9),
        expires_at=now + timedelta(hours=1),
    )
    assert token_90.should_refresh() is True

    token_95 = TokenRecord(
        access_token="t",
        issued_at=now - timedelta(hours=9, minutes=30),
        expires_at=now + timedelta(minutes=30),
    )
    assert token_95.should_refresh() is True
