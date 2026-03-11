import json
from pathlib import Path

import pandas as pd

from option_chain_alerts import build_commentary, evaluate_alerts
from option_chain_service import enrich_option_chain


def _fixture(name: str) -> pd.DataFrame:
    path = Path(__file__).resolve().parents[1] / "fixtures" / name
    return pd.DataFrame(json.loads(path.read_text()))


def test_alerts_detect_wall_shift_and_iv_jump():
    previous_df = enrich_option_chain(_fixture("option_chain_balanced.json"), "NIFTY", "2026-03-26", 22020, include_greeks=False)
    current_df = enrich_option_chain(_fixture("option_chain_expiry_day.json"), "NIFTY", "2026-03-26", 22020, include_greeks=False)
    alerts = evaluate_alerts(current_df, previous_df=previous_df, spot=22020, expiry="2026-03-26")
    codes = {alert["code"] for alert in alerts}
    assert "atm_iv_jump" in codes


def test_commentary_mentions_real_levels():
    df = enrich_option_chain(_fixture("option_chain_put_heavy.json"), "NIFTY", "2026-03-26", 22010, include_greeks=False)
    commentary = build_commentary(df, alerts=[], spot=22010, expiry="2026-03-26")
    joined = " ".join(commentary)
    assert "support" in joined.lower()
    assert "22000" in joined or "22100" in joined
