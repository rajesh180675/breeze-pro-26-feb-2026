from persistence import AccountProfileDB, TradeDB
from session_manager import AccountProfile, MultiAccountManager


def test_account_profiles_save_switch_delete():
    db = TradeDB()
    adb = AccountProfileDB(db)
    mgr = MultiAccountManager("test-master-password")

    mgr.add_profile(AccountProfile(profile_id="", display_name="A", api_key="keyA", api_secret="", totp_secret="totpA"))
    mgr.add_profile(AccountProfile(profile_id="", display_name="B", api_key="keyB", api_secret="", totp_secret="totpB"))
    profiles = adb.get_profiles()
    names = {p["profile_name"] for p in profiles}
    assert {"A", "B"}.issubset(names)

    adb.set_active("A")
    assert adb.get_active_profile()["profile_name"] == "A"

    adb.set_active("B")
    assert adb.get_active_profile()["profile_name"] == "B"

    adb.delete_profile("B")
    active = adb.get_active_profile()
    assert active is None or active["profile_name"] != "B"
