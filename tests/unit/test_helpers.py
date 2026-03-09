from datetime import datetime

import pandas as pd

import helpers


def test_add_greeks_to_chain_displays_dash_for_nan_iv(monkeypatch):
    monkeypatch.setattr(helpers, "estimate_implied_volatility", lambda *args, **kwargs: float("nan"))
    df = pd.DataFrame(
        [
            {
                "strike_price": 22000,
                "right": "Call",
                "ltp": 120.0,
                "iv": 0,
            }
        ]
    )

    out = helpers.add_greeks_to_chain(df, spot_price=22100.0, expiry_date=datetime.now().strftime("%Y-%m-%d"))

    assert out.loc[0, "iv"] == "—"
    assert out.loc[0, "delta"] == 0
    assert out.loc[0, "vega"] == 0


def test_add_greeks_to_chain_keeps_numeric_iv_when_computable(monkeypatch):
    monkeypatch.setattr(helpers, "estimate_implied_volatility", lambda *args, **kwargs: 0.25)
    df = pd.DataFrame(
        [
            {
                "strike_price": 22000,
                "right": "Put",
                "ltp": 130.0,
                "iv": 0,
            }
        ]
    )

    out = helpers.add_greeks_to_chain(df, spot_price=21900.0, expiry_date="2099-01-01")

    assert out.loc[0, "iv"] != "—"
    assert isinstance(out.loc[0, "iv"], float)
