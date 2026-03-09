from session_manager import MultiAccountManager, AccountProfile
from persistence import TradeDB


def test_multi_account_encrypt_and_list(monkeypatch):
    mgr = MultiAccountManager("test-master-password")
    mgr.add_profile(
        AccountProfile(
            profile_id="",
            display_name="unit-profile",
            api_key="k",
            api_secret="s",
            totp_secret="t",
        )
    )
    profiles = mgr.list_profiles()
    assert any(p.display_name == "unit-profile" for p in profiles)


def test_ensure_profiles_encrypted_migrates_plaintext():
    db = TradeDB()
    with db._tx() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO account_profiles
            (profile_name, api_key, api_secret, totp_secret, broker, is_active, created_at, last_used)
            VALUES (?, ?, ?, ?, ?, 0, datetime('now'), NULL)
            """,
            ("legacy-plain", "plain-key", "plain-secret", "plain-totp", "ICICI"),
        )
    mgr = MultiAccountManager("test-master-password")
    migrated = mgr.ensure_profiles_encrypted()
    assert migrated >= 1
