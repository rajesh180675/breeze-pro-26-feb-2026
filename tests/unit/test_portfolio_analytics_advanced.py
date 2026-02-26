import math
import sys
import types

# analytics.py depends on scipy; provide lightweight stubs for unit testing envs.
scipy_mod = types.ModuleType("scipy")
stats_mod = types.ModuleType("scipy.stats")
opt_mod = types.ModuleType("scipy.optimize")


class _Norm:
    @staticmethod
    def cdf(x):
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    @staticmethod
    def pdf(x):
        return (1 / math.sqrt(2 * math.pi)) * math.exp(-(x ** 2) / 2)


stats_mod.norm = _Norm()

def _brentq(func, a, b, *args, **kwargs):
    return (a + b) / 2

opt_mod.brentq = _brentq
scipy_mod.stats = stats_mod
scipy_mod.optimize = opt_mod
sys.modules.setdefault("scipy", scipy_mod)
sys.modules.setdefault("scipy.stats", stats_mod)
sys.modules.setdefault("scipy.optimize", opt_mod)

import time

import numpy as np
import pandas as pd

from analytics import (
    monte_carlo_var,
    portfolio_correlation_matrix,
    rolling_realized_vol,
)


def _sample_positions(n=5):
    out = []
    for i in range(n):
        out.append(
            {
                "quantity": 50,
                "ltp": 120 + i,
                "strike_price": 22000 + i * 100,
                "iv": 18,
                "right": "call" if i % 2 == 0 else "put",
                "expiry_date": "2026-12-31",
            }
        )
    return out


def test_monte_carlo_var_runtime_and_monotonicity():
    positions = _sample_positions(5)
    t0 = time.perf_counter()
    result = monte_carlo_var(
        positions=positions,
        spot_price=22300,
        volatility_annual=0.18,
        simulations=10_000,
        days=1,
    )
    elapsed = time.perf_counter() - t0

    assert elapsed < 5.0
    assert result["var_95"] <= result["var_99"]
    assert result["simulations"] == 10_000


def test_rolling_realized_vol_matches_manual_formula():
    close = pd.Series(np.linspace(100, 120, 60))
    rv = rolling_realized_vol(close, window=20)

    log_returns = np.log(close / close.shift(1))
    manual = log_returns.rolling(window=20).std() * np.sqrt(252) * 100

    valid = (~rv.isna()) & (~manual.isna())
    diff = (rv[valid] - manual[valid]).abs().max()
    assert float(diff) <= 0.1


def test_portfolio_correlation_matrix_is_symmetric_with_unit_diagonal():
    s1 = pd.Series(np.linspace(100, 120, 80))
    s2 = pd.Series(np.linspace(200, 250, 80))
    s3 = pd.Series(np.linspace(300, 270, 80))

    corr = portfolio_correlation_matrix({"A": s1, "B": s2, "C": s3})
    assert not corr.empty
    assert corr.equals(corr.T)
    assert all(abs(float(corr.loc[k, k]) - 1.0) < 1e-9 for k in corr.index)
