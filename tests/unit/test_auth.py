from datetime import datetime, timedelta, timezone

from lib.auth import AuthManager, InMemoryTokenStore, TokenRecord


def test_authenticate_persists_token():
    manager = AuthManager(InMemoryTokenStore())
    record = manager.authenticate(session_token="abc")
    assert record.access_token == "abc"
    assert manager.current() is not None


def test_ensure_fresh_token_refreshes_when_expired():
    store = InMemoryTokenStore()
    store.save(TokenRecord(access_token="old", expires_at=datetime.now(tz=timezone.utc) - timedelta(seconds=1)))
    manager = AuthManager(store)

    def refresher():
        return TokenRecord(access_token="new", expires_at=datetime.now(tz=timezone.utc) + timedelta(hours=1))

    record = manager.ensure_fresh_token(refresher)
    assert record.access_token == "new"
