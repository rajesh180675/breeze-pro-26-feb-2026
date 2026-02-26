from persistence import AccountProfileDB, TradeDB


def test_account_profiles_save_switch_delete():
    db = TradeDB()
    adb = AccountProfileDB(db)

    adb.save_profile("A", "keyA", "totpA")
    adb.save_profile("B", "keyB", "totpB")
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
