from persistence import TradeDB, DBMigrator


def test_db_migrator_runs_idempotently():
    db = TradeDB()
    conn = db._get_conn()
    migrator = DBMigrator()
    migrator.run(conn)
    migrator.run(conn)
    row = conn.execute("SELECT MAX(version) AS version FROM schema_version").fetchone()
    assert row is not None
    assert int(row["version"]) >= 1


def test_basket_template_crud_roundtrip():
    db = TradeDB()
    ok = db.save_basket_template(
        name="pytest-template",
        instrument="NIFTY",
        strategy_type="Iron Condor",
        legs=[{"offset": -1, "type": "PE", "action": "buy", "qty_multiplier": 1}],
    )
    assert ok is True
    rows = db.list_basket_templates("NIFTY")
    assert any(r["name"] == "pytest-template" for r in rows)
