from datetime import date, timedelta

import persistence as persistence_mod
from persistence import DBMigrator, TradeDB



def _fresh_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_trades.db"
    monkeypatch.setattr(persistence_mod, "DB_PATH", db_file)
    TradeDB._instance = None
    return TradeDB()


def test_db_migrator_runs_idempotently(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    conn = db._get_conn()
    migrator = DBMigrator()
    migrator.run(conn)
    migrator.run(conn)
    row = conn.execute("SELECT MAX(version) AS version FROM schema_version").fetchone()
    assert row is not None
    assert int(row["version"]) == 6


def test_log_trade_returns_true_on_success(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    ok = db.log_trade("NIFTY", "NFO", 22000, "CE", "2026-03-26", "sell", 75, 100.0)
    assert ok is True


def test_get_trades_empty_when_no_trades(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    assert db.get_trades() == []


def test_get_trades_filters_by_date(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    today = date.today()
    for i in range(3):
        d = (today - timedelta(days=i)).isoformat()
        with db._tx() as conn:
            conn.execute(
                """
                INSERT INTO trades (trade_id, timestamp, date, stock_code, exchange, strike, option_type, expiry, action, quantity, price, order_type, notes, pnl)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (f"t{i}", f"{d}T10:00:00", d, "NIFTY", "NFO", 22000, "CE", "2026-03-26", "sell", 75, 100.0, "limit", "", 0.0),
            )

    rows = db.get_trades(date_from=today.isoformat(), date_to=today.isoformat())
    assert len(rows) == 1
    assert rows[0]["date"] == today.isoformat()


def test_record_pnl_and_get_pnl_history(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    db.log_trade("NIFTY", "NFO", 22000, "CE", "2026-03-26", "sell", 75, 100.0, pnl=150.0)
    hist = db.get_pnl_history(days=5)
    assert hist
    assert "realized_pnl" in hist[0]


def test_record_option_chain_snapshot_and_retrieve(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    db.record_option_chain_snapshot(
        instrument="NIFTY",
        expiry="2026-03-26",
        rows=[{"strike_price": 22000, "right": "call", "iv": 0.22, "volume": 1500}],
    )
    iv = db.get_iv_history("NIFTY", 22000, "CE")
    assert iv and iv[-1] > 0


def test_save_and_get_iv_history(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    db.record_option_chain_snapshot(
        instrument="NIFTY",
        expiry="2026-03-26",
        rows=[{"strike_price": 22000, "right": "call", "iv": 22, "volume": 1000}],
    )
    out = db.get_iv_history("NIFTY", 22000, "CE")
    assert out
    assert 0 < out[0] < 1


def test_idempotency_guard_prevents_duplicate_orders(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    assert db.check_idempotency("o1") is None
    db.save_idempotency("o1", "broker-order-1")
    assert db.check_idempotency("o1") == "broker-order-1"


def test_save_and_load_settings(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    db.set_setting("k", "v")
    assert db.get_setting("k") == "v"


def test_get_volume_baseline_map_returns_dict(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    db.record_option_chain_snapshot(
        instrument="NIFTY",
        expiry="2026-03-26",
        rows=[{"strike_price": 22000, "right": "call", "iv": 0.2, "volume": 2000}],
    )
    out = db.get_volume_baseline_map("NIFTY", lookback_days=10)
    assert isinstance(out, dict)
    assert (22000, "CE") in out


def test_option_chain_intraday_snapshot_roundtrip(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    db.record_option_chain_intraday_snapshot(
        instrument="NIFTY",
        expiry="2026-03-26",
        snapshot_ts="2026-03-11T09:15:00",
        rows=[
            {
                "strike_price": 22000,
                "right": "Call",
                "ltp": 120,
                "best_bid_price": 119,
                "best_offer_price": 121,
                "bid_qty": 10,
                "offer_qty": 12,
                "volume": 1000,
                "open_interest": 20000,
                "oi_change": 500,
                "iv": 0.2,
            }
        ],
    )
    rows = db.get_option_chain_intraday_snapshots("NIFTY", expiry="2026-03-26")
    assert len(rows) == 1
    replay_rows = db.get_option_chain_snapshot_at_or_before("NIFTY", "2026-03-26", "2026-03-11T09:16:00")
    assert len(replay_rows) == 1
    assert replay_rows[0]["right"] == "Call"


def test_option_chain_intraday_cleanup_downsamples_old_rows(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    stale_trade_date = (date.today() - timedelta(days=10)).isoformat()
    keep_trade_date = (date.today() - timedelta(days=10)).isoformat()
    db.record_option_chain_intraday_snapshot(
        instrument="NIFTY",
        expiry="2026-03-26",
        trade_date=stale_trade_date,
        snapshot_ts=f"{stale_trade_date}T09:16:00",
        rows=[{"strike_price": 22000, "right": "Call", "ltp": 120}],
    )
    db.record_option_chain_intraday_snapshot(
        instrument="NIFTY",
        expiry="2026-03-26",
        trade_date=keep_trade_date,
        snapshot_ts=f"{keep_trade_date}T09:15:00",
        rows=[{"strike_price": 22000, "right": "Put", "ltp": 122}],
    )
    deleted = db.cleanup_option_chain_intraday_snapshots(retain_full_days=7, retain_downsampled_days=30)
    assert deleted == 1
    rows = db.get_option_chain_intraday_snapshots("NIFTY", expiry="2026-03-26")
    assert len(rows) == 1


def test_option_chain_window_comparison_and_recent_history(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    for snapshot_ts, ltp, oi in (
        ("2026-03-11T09:15:00", 100, 1000),
        ("2026-03-11T09:20:00", 108, 1250),
    ):
        db.record_option_chain_intraday_snapshot(
            instrument="NIFTY",
            expiry="2026-03-26",
            trade_date="2026-03-11",
            snapshot_ts=snapshot_ts,
            rows=[
                {
                    "strike_price": 22000,
                    "right": "Call",
                    "ltp": ltp,
                    "volume": oi // 2,
                    "open_interest": oi,
                    "oi_change": oi - 900,
                    "iv": 0.2,
                }
            ],
        )
    history = db.get_option_chain_recent_strike_history("NIFTY", "2026-03-26", 22000, "CE")
    assert len(history) == 2
    comparison = db.get_option_chain_window_comparison(
        "NIFTY",
        "2026-03-26",
        as_of_ts="2026-03-11T09:20:00",
        window_minutes=5,
    )
    assert len(comparison) == 1
    assert comparison[0]["current_open_interest"] == 1250
    assert comparison[0]["baseline_open_interest"] == 1000


def test_basket_template_crud_roundtrip(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    ok = db.save_basket_template(
        name="pytest-template",
        instrument="NIFTY",
        strategy_type="Iron Condor",
        legs=[{"offset": -1, "type": "PE", "action": "buy", "qty_multiplier": 1}],
    )
    assert ok is True
    rows = db.list_basket_templates("NIFTY")
    assert any(r["name"] == "pytest-template" for r in rows)
