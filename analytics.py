"""
Analytics — Black-Scholes pricing, Greeks, IV solver, portfolio analytics.
Pure math. Only depends on app_config.
"""

import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging

import app_config as C

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# BLACK-SCHOLES CORE
# ═══════════════════════════════════════════════════════════════

def _d1_d2(spot: float, strike: float, tte: float, vol: float,
           r: float) -> Tuple[float, float]:
    if tte < 1e-10 or vol < 1e-10 or spot <= 0 or strike <= 0:
        return (10.0, 10.0) if spot > strike else (-10.0, -10.0)
    sqrt_t = np.sqrt(tte)
    d1 = (np.log(spot / strike) + (r + 0.5 * vol ** 2) * tte) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    return np.clip(d1, -10.0, 10.0), np.clip(d2, -10.0, 10.0)


def bs_price(spot: float, strike: float, tte: float, vol: float,
             option_type: str, r: float = C.RISK_FREE_RATE) -> float:
    d1, d2 = _d1_d2(spot, strike, tte, vol, r)
    disc = np.exp(-r * tte)
    if option_type == "CE":
        return max(0.0, spot * norm.cdf(d1) - strike * disc * norm.cdf(d2))
    return max(0.0, strike * disc * norm.cdf(-d2) - spot * norm.cdf(-d1))


def bs_vega_raw(spot: float, strike: float, tte: float, vol: float,
                r: float = C.RISK_FREE_RATE) -> float:
    if tte < 1e-10:
        return 0.0
    d1, _ = _d1_d2(spot, strike, tte, vol, r)
    return spot * norm.pdf(d1) * np.sqrt(tte)


def calculate_greeks(spot: float, strike: float, tte: float, vol: float,
                     option_type: str, r: float = C.RISK_FREE_RATE) -> Dict[str, float]:
    """All Greeks for a single option. Theta: daily. Vega: per 1% vol."""
    if tte < 1e-10:
        d = (1.0 if spot > strike else 0.0) if option_type == "CE" else \
            (-1.0 if spot < strike else 0.0)
        return {'delta': d, 'gamma': 0.0, 'theta': 0.0, 'vega': 0.0, 'rho': 0.0}

    d1, d2 = _d1_d2(spot, strike, tte, vol, r)
    sqrt_t = np.sqrt(tte)
    n_d1 = norm.pdf(d1)
    disc = np.exp(-r * tte)

    gamma = n_d1 / (spot * vol * sqrt_t) if (spot * vol * sqrt_t) > 0 else 0.0
    vega = spot * n_d1 * sqrt_t / 100.0

    if option_type == "CE":
        delta = norm.cdf(d1)
        theta = (-spot * n_d1 * vol / (2 * sqrt_t) - r * strike * disc * norm.cdf(d2)) / C.DAYS_PER_YEAR
        rho = strike * tte * disc * norm.cdf(d2) / 100.0
    else:
        delta = norm.cdf(d1) - 1
        theta = (-spot * n_d1 * vol / (2 * sqrt_t) + r * strike * disc * norm.cdf(-d2)) / C.DAYS_PER_YEAR
        rho = -strike * tte * disc * norm.cdf(-d2) / 100.0

    return {
        'delta': round(delta, 4), 'gamma': round(gamma, 6),
        'theta': round(theta, 4), 'vega': round(vega, 4),
        'rho': round(rho, 6)
    }


# ═══════════════════════════════════════════════════════════════
# IMPLIED VOLATILITY SOLVER
# ═══════════════════════════════════════════════════════════════

@dataclass
class IVResult:
    iv: float
    converged: bool
    iterations: int
    method: str
    price_error: float


def solve_iv(option_price: float, spot: float, strike: float,
             tte: float, option_type: str, r: float = C.RISK_FREE_RATE) -> IVResult:
    if option_price <= 0 or spot <= 0 or strike <= 0 or tte <= 0:
        return IVResult(0.20, False, 0, "default", float('inf'))

    intrinsic = max(0, spot - strike * np.exp(-r * tte)) if option_type == "CE" \
        else max(0, strike * np.exp(-r * tte) - spot)
    if option_price < intrinsic * 0.99:
        return IVResult(0.01, False, 0, "sub_intrinsic", abs(option_price - intrinsic))

    nr = _newton_raphson_iv(option_price, spot, strike, tte, option_type, r)
    if nr.converged:
        return nr
    return _brent_iv(option_price, spot, strike, tte, option_type, r)


def estimate_implied_volatility(option_price: float, spot: float, strike: float,
                                tte: float, option_type: str,
                                r: float = C.RISK_FREE_RATE) -> float:
    return solve_iv(option_price, spot, strike, tte, option_type, r).iv


def _newton_raphson_iv(target: float, spot: float, strike: float, tte: float,
                       ot: str, r: float, max_iter: int = 50, tol: float = 1e-8) -> IVResult:
    vol = np.clip(np.sqrt(2 * np.pi / tte) * (target / spot), 0.01, 3.0)
    diff = 0.0
    for i in range(max_iter):
        price = bs_price(spot, strike, tte, vol, ot, r)
        diff = price - target
        if abs(diff) < tol:
            return IVResult(vol, True, i + 1, "newton", abs(diff))
        vega = bs_vega_raw(spot, strike, tte, vol, r)
        if vega < 1e-12:
            return IVResult(vol, False, i + 1, "nr_vega_collapse", abs(diff))
        step = np.sign(diff / vega) * min(abs(diff / vega), vol * 0.5)
        vol = np.clip(vol - step, 0.001, 5.0)
    return IVResult(vol, False, max_iter, "nr_max_iter", abs(diff))


def _brent_iv(target: float, spot: float, strike: float, tte: float,
              ot: str, r: float) -> IVResult:
    def obj(vol):
        return bs_price(spot, strike, tte, vol, ot, r) - target
    try:
        lo, hi = 0.001, 5.0
        if obj(lo) * obj(hi) > 0:
            for test_hi in [1.0, 2.0, 5.0, 10.0]:
                if obj(lo) * obj(test_hi) < 0:
                    hi = test_hi
                    break
            else:
                best = lo if abs(obj(lo)) < abs(obj(hi)) else hi
                return IVResult(best, False, 0, "brent_no_bracket", min(abs(obj(lo)), abs(obj(hi))))
        iv, info = brentq(obj, lo, hi, xtol=1e-8, maxiter=100, full_output=True)
        return IVResult(iv, info.converged, info.iterations, "brent", abs(obj(iv)))
    except (ValueError, RuntimeError) as e:
        log.debug(f"Brent failed: {e}")
        return IVResult(0.20, False, 0, "brent_failed", float('inf'))


# ═══════════════════════════════════════════════════════════════
# IV TERM STRUCTURE & SMILE
# ═══════════════════════════════════════════════════════════════

def calculate_iv_smile(chain_df, spot: float, expiry: str) -> dict:
    """Return IV smile data: {strike: iv} for calls and puts."""
    import pandas as pd
    if chain_df is None or chain_df.empty:
        return {"calls": {}, "puts": {}}
    try:
        from helpers import calculate_days_to_expiry
        dte = calculate_days_to_expiry(expiry)
        tte = max(dte / C.DAYS_PER_YEAR, 0.001)
    except Exception:
        tte = 0.05

    calls, puts = {}, {}
    if "right" not in chain_df.columns:
        return {"calls": calls, "puts": puts}
    for _, row in chain_df.iterrows():
        strike = float(row.get("strike_price", 0))
        ltp = float(row.get("ltp", 0))
        if strike <= 0 or ltp <= 0:
            continue
        ot = "CE" if str(row.get("right", "")).strip().lower() in ("call", "ce") else "PE"
        iv = estimate_implied_volatility(ltp, spot, strike, tte, ot)
        if 0.01 < iv < 5.0:
            if ot == "CE":
                calls[int(strike)] = round(iv * 100, 2)
            else:
                puts[int(strike)] = round(iv * 100, 2)
    return {"calls": calls, "puts": puts}


def calculate_iv_term_structure(client, instrument: str, expiries: list, spot: float) -> dict:
    """ATM IV across multiple expiries (for term structure)."""
    import app_config as C
    cfg = C.get_instrument(instrument)
    result = {}
    for exp in expiries[:4]:
        try:
            resp = client.get_option_chain(cfg.api_code, cfg.exchange, exp)
            if not resp.get("success"):
                continue
            from helpers import process_option_chain, estimate_atm_strike, calculate_days_to_expiry
            df = process_option_chain(resp.get("data", {}))
            if df.empty:
                continue
            atm = estimate_atm_strike(df)
            dte = calculate_days_to_expiry(exp)
            tte = max(dte / C.DAYS_PER_YEAR, 0.001)

            # Get CE and PE ATM IV
            ce_rows = df[(df["right"] == "Call") & (df["strike_price"] == atm)]
            pe_rows = df[(df["right"] == "Put") & (df["strike_price"] == atm)]
            ce_iv = pe_iv = 0.0
            if not ce_rows.empty:
                ltp = float(ce_rows.iloc[0].get("ltp", 0))
                if ltp > 0:
                    ce_iv = estimate_implied_volatility(ltp, spot, atm, tte, "CE") * 100
            if not pe_rows.empty:
                ltp = float(pe_rows.iloc[0].get("ltp", 0))
                if ltp > 0:
                    pe_iv = estimate_implied_volatility(ltp, spot, atm, tte, "PE") * 100
            avg_iv = (ce_iv + pe_iv) / 2 if (ce_iv > 0 and pe_iv > 0) else max(ce_iv, pe_iv)
            result[exp] = {"dte": dte, "iv": round(avg_iv, 2), "atm": atm}
        except Exception as e:
            log.debug(f"IV term structure error {exp}: {e}")
    return result


# ═══════════════════════════════════════════════════════════════
# PORTFOLIO ANALYTICS
# ═══════════════════════════════════════════════════════════════

def calculate_portfolio_greeks(positions: list, spot_prices: dict) -> dict:
    """Aggregate Greeks across all positions."""
    agg = {'delta': 0.0, 'gamma': 0.0, 'theta': 0.0, 'vega': 0.0, 'rho': 0.0}
    for p in positions:
        from helpers import safe_float, safe_int, detect_position_type, calculate_days_to_expiry
        from app_config import normalize_option_type
        stock = p.get("stock_code", "")
        strike = safe_float(p.get("strike_price", 0))
        ltp = safe_float(p.get("ltp", 0))
        ot = normalize_option_type(p.get("right", ""))
        exp = p.get("expiry_date", "")
        qty = abs(safe_int(p.get("quantity", 0)))
        pt = detect_position_type(p)
        multiplier = -1 if pt == "short" else 1

        spot = spot_prices.get(stock, strike)
        if spot <= 0:
            spot = strike
        try:
            dte = calculate_days_to_expiry(exp) if exp else 30
            tte = max(dte / C.DAYS_PER_YEAR, 0.001)
            iv = estimate_implied_volatility(ltp, spot, strike, tte, ot) if ltp > 0 else 0.20
            greeks = calculate_greeks(spot, strike, tte, iv, ot)
            for k in agg:
                agg[k] += greeks[k] * multiplier * qty
        except Exception:
            pass
    return {k: round(v, 4) for k, v in agg.items()}


def calculate_var(pnl_series: list, confidence: float = 0.95) -> float:
    if not pnl_series:
        return 0.0
    return float(np.percentile(pnl_series, (1 - confidence) * 100))


def calculate_sharpe(returns: list, risk_free: float = C.RISK_FREE_RATE) -> float:
    if not returns or len(returns) < 2:
        return 0.0
    r = np.array(returns)
    if np.std(r) == 0:
        return 0.0
    return float((np.mean(r) * 252 - risk_free) / (np.std(r) * np.sqrt(252)))


def calculate_max_drawdown(cumulative_pnl: list) -> float:
    if not cumulative_pnl:
        return 0.0
    arr = np.array(cumulative_pnl)
    peak = np.maximum.accumulate(arr)
    drawdown = arr - peak
    return float(np.min(drawdown))


def calculate_win_rate(trades: list) -> float:
    """Compute win rate from trade list (profit > 0 = win)."""
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
    return wins / len(trades) * 100


# ═══════════════════════════════════════════════════════════════
# SCENARIO / STRESS TEST
# ═══════════════════════════════════════════════════════════════

def stress_test_portfolio(positions: list, spot_prices: dict,
                          spot_moves: list = None, iv_moves: list = None) -> dict:
    """P&L under various spot/IV scenarios."""
    if spot_moves is None:
        spot_moves = [-10, -5, -3, -1, 0, 1, 3, 5, 10]
    if iv_moves is None:
        iv_moves = [-20, -10, 0, 10, 20]  # pct change in IV

    from helpers import safe_float, safe_int, detect_position_type, calculate_days_to_expiry
    from app_config import normalize_option_type

    results = {}
    for iv_move in iv_moves:
        row = {}
        for spot_move in spot_moves:
            total_pnl = 0.0
            for p in positions:
                stock = p.get("stock_code", "")
                strike = safe_float(p.get("strike_price", 0))
                ltp = safe_float(p.get("ltp", 0))
                avg = safe_float(p.get("average_price", ltp))
                ot = normalize_option_type(p.get("right", ""))
                exp = p.get("expiry_date", "")
                qty = abs(safe_int(p.get("quantity", 0)))
                pt = detect_position_type(p)

                spot = spot_prices.get(stock, strike)
                if spot <= 0:
                    spot = strike
                new_spot = spot * (1 + spot_move / 100)
                dte = calculate_days_to_expiry(exp) if exp else 30
                tte = max(dte / C.DAYS_PER_YEAR, 0.001)

                try:
                    base_iv = estimate_implied_volatility(ltp, spot, strike, tte, ot) if ltp > 0 else 0.20
                    new_iv = max(0.01, base_iv * (1 + iv_move / 100))
                    new_price = bs_price(new_spot, strike, tte, new_iv, ot)
                    if pt == "short":
                        pnl = (avg - new_price) * qty
                    else:
                        pnl = (new_price - avg) * qty
                    total_pnl += pnl
                except Exception:
                    pass
            row[f"{spot_move:+d}%"] = round(total_pnl, 2)
        results[f"IV {iv_move:+d}%"] = row
    return results
