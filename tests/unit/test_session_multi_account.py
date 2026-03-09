from session_manager import MultiAccountManager, AccountProfile
from persistence import TradeDB, AccountProfileDB


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
    pdb = AccountProfileDB(db)
    pdb.save_profile("legacy-plain", "plain-key", "plain-totp", api_secret="plain-secret")
    mgr = MultiAccountManager("test-master-password")
    migrated = mgr.ensure_profiles_encrypted()
    assert migrated >= 1
