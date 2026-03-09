"""
Analytics — Black-Scholes pricing, Greeks, IV solver, portfolio analytics.
Pure math. Only depends on app_config.
"""

import numpy as np
import pandas as pd
from scipy.stats import norm
from scipy.optimize import brentq
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging
from datetime import datetime

import app_config as C

log = logging.getLogger(__name__)
TRADING_DAYS_PER_YEAR = getattr(C, "TRADING_DAYS_PER_YEAR", 252)


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
    # Task 1.4: Return NaN for same-day / near-expiry options (< 2 days)
    # to avoid polluting the option chain with a misleading default 20% IV.
    if tte < 2 / C.DAYS_PER_YEAR:
        return float('nan')
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


# ═══════════════════════════════════════════════════════════════
# ADVANCED PORTFOLIO ANALYTICS
# ═══════════════════════════════════════════════════════════════

def monte_carlo_var(
    positions: List[Dict],
    spot_price: float,
    volatility_annual: float,
    days: int = 1,
    simulations: int = 10_000,
    confidence_level: float = 0.95,
    risk_free_rate: float = C.RISK_FREE_RATE,
) -> Dict:
    """Monte Carlo Value-at-Risk for an options portfolio."""
    if not positions or simulations <= 0 or spot_price <= 0:
        return {
            "var_95": 0.0, "var_99": 0.0, "cvar_95": 0.0,
            "expected_pnl": 0.0, "worst_case": 0.0, "best_case": 0.0,
            "simulations": int(max(simulations, 0)), "confidence_level": confidence_level, "days": days,
        }

    vol_daily = max(0.0, volatility_annual) / np.sqrt(C.DAYS_PER_YEAR)
    rng = np.random.default_rng(seed=42)
    spot_returns = rng.normal(0, vol_daily * np.sqrt(max(days, 1)), int(simulations))

    pnl_distribution = np.zeros(int(simulations), dtype=float)

    for pos in positions:
        qty = int(float(pos.get("quantity", 0) or 0))
        if qty == 0:
            continue

        ltp = float(pos.get("ltp", pos.get("average_price", 0)) or 0)
        strike = float(pos.get("strike_price", 0) or 0)
        if strike <= 0:
            continue

        iv_raw = float(pos.get("iv", volatility_annual * 100) or (volatility_annual * 100))
        iv = iv_raw / 100 if iv_raw > 1 else iv_raw
        iv = max(0.01, iv)

        right = str(pos.get("right", pos.get("option_type", "call"))).lower()
        option_type = "CE" if "c" in right else "PE"

        expiry_str = str(pos.get("expiry_date", ""))
        try:
            exp_dt = datetime.strptime(expiry_str[:10], "%Y-%m-%d")
            dte = max(1, (exp_dt - datetime.now()).days)
        except Exception:
            dte = 30
        tte = dte / C.DAYS_PER_YEAR

        tte_new = max(1e-6, tte - max(days, 1) / C.DAYS_PER_YEAR)
        for i, ret in enumerate(spot_returns):
            new_spot = float(spot_price * np.exp(ret))
            new_price = bs_price(new_spot, strike, tte_new, iv, option_type, risk_free_rate)
            pnl_distribution[i] += (new_price - ltp) * qty

    pnl_sorted = np.sort(pnl_distribution)
    tail_count = max(1, int((1 - confidence_level) * simulations))

    q95 = float(np.percentile(pnl_distribution, 5))
    q99 = float(np.percentile(pnl_distribution, 1))

    # Report VaR as loss magnitudes (positive numbers), which preserves monotonicity:
    # VaR99 (more conservative) >= VaR95.
    var_95 = max(0.0, -q95)
    var_99 = max(var_95, max(0.0, -q99))

    tail = pnl_distribution[pnl_distribution <= q95]
    cvar_95 = max(0.0, -float(tail.mean())) if len(tail) > 0 else var_95

    return {
        "var_95": round(var_95, 2),
        "var_99": round(var_99, 2),
        "cvar_95": round(cvar_95, 2),
        "expected_pnl": round(float(pnl_distribution.mean()), 2),
        "worst_case": round(float(pnl_sorted[0]), 2),
        "best_case": round(float(pnl_sorted[-1]), 2),
        "simulations": int(simulations),
        "confidence_level": confidence_level,
        "days": int(days),
    }


def rolling_realized_vol(
    close_prices: pd.Series,
    window: int = 20,
    trading_days_per_year: int = TRADING_DAYS_PER_YEAR,
) -> pd.Series:
    """Rolling realized volatility annualized in percentage terms."""
    log_returns = np.log(close_prices / close_prices.shift(1))
    return (
        log_returns.rolling(window=window).std() * np.sqrt(trading_days_per_year) * 100
    ).rename(f"rv_{window}")


def iv_vs_rv_spread(current_iv: float, hist_close: pd.Series, window: int = 20) -> Dict:
    """Compute IV vs realized-vol spread and interpretation."""
    rv_series = rolling_realized_vol(hist_close, window)
    rv_valid = rv_series.dropna()
    rv = float(rv_valid.iloc[-1]) if len(rv_valid) > 0 else float(current_iv)
    spread = float(current_iv) - rv
    interp = (
        "Expensive (sell premium)" if spread > 3
        else "Cheap (buy premium)" if spread < -3
        else "Fair Value"
    )
    return {
        "iv": round(float(current_iv), 2),
        "rv": round(rv, 2),
        "spread": round(spread, 2),
        "spread_interpretation": interp,
    }


def portfolio_correlation_matrix(historical_data: Dict[str, pd.Series]) -> pd.DataFrame:
    """Pairwise log-return correlation matrix for portfolio symbols."""
    if not historical_data:
        return pd.DataFrame()
    returns = pd.DataFrame({
        sym: np.log(prices / prices.shift(1))
        for sym, prices in historical_data.items()
    }).dropna()
    if returns.empty:
        return pd.DataFrame()
    return returns.corr()


# ═══════════════════════════════════════════════════════════════
# TASK 3.4 — MARKET REGIME DETECTOR
# ═══════════════════════════════════════════════════════════════

class MarketRegime:
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGE_BOUND = "RANGE_BOUND"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    PRE_EXPIRY = "PRE_EXPIRY"


def _ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=span, adjust=False).mean()


def _adx_approx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    """Approximate ADX (Average Directional Index) from OHLC data.

    Returns a single ADX value for the most recent bar.  This is a simplified
    implementation suited for regime classification — not full Wilder smoothing.
    """
    if len(close) < period + 1:
        return 0.0
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10) * 100
    adx = dx.rolling(period).mean()
    val = adx.dropna()
    return float(val.iloc[-1]) if len(val) > 0 else 0.0


def detect_market_regime(
    close_prices: pd.Series,
    high_prices: Optional[pd.Series] = None,
    low_prices: Optional[pd.Series] = None,
    vix: float = 0.0,
    pcr: float = 1.0,
    days_to_expiry: int = 30,
) -> Dict:
    """Detect current market regime from price data and market indicators.

    Classifications: TRENDING_UP, TRENDING_DOWN, RANGE_BOUND, HIGH_VOLATILITY, PRE_EXPIRY.

    Returns dict with regime, confidence, recommended_strategies, risk_level, signals.
    """
    result = {
        "regime": MarketRegime.RANGE_BOUND,
        "confidence": 0.0,
        "recommended_strategies": [],
        "risk_level": "MEDIUM",
        "signals": {},
    }

    if close_prices is None or len(close_prices) < 10:
        return result

    close = close_prices.astype(float).dropna()
    if len(close) < 10:
        return result

    signals: Dict[str, Any] = {}

    # 1. EMA signals
    ema_short = _ema(close, 9)
    ema_long = _ema(close, 21)
    ema_diff_pct = (ema_short.iloc[-1] - ema_long.iloc[-1]) / ema_long.iloc[-1] * 100
    signals["ema_9_21_diff_pct"] = round(float(ema_diff_pct), 3)

    # 2. ADX for trend strength
    adx = 0.0
    if high_prices is not None and low_prices is not None:
        adx = _adx_approx(high_prices.astype(float), low_prices.astype(float), close, 14)
    signals["adx"] = round(adx, 2)

    # 3. Realized volatility
    log_ret = np.log(close / close.shift(1)).dropna()
    rv_5d = float(log_ret.tail(5).std() * np.sqrt(252) * 100) if len(log_ret) >= 5 else 0.0
    rv_20d = float(log_ret.tail(20).std() * np.sqrt(252) * 100) if len(log_ret) >= 20 else rv_5d
    signals["rv_5d"] = round(rv_5d, 2)
    signals["rv_20d"] = round(rv_20d, 2)
    signals["vix"] = round(vix, 2)
    signals["pcr"] = round(pcr, 2)
    signals["dte"] = days_to_expiry

    # ── Classification logic ──────────────────────────────────
    confidence = 0.5

    # Pre-expiry override
    if days_to_expiry <= 2:
        result["regime"] = MarketRegime.PRE_EXPIRY
        confidence = 0.85
        result["recommended_strategies"] = [
            "Short Straddle (tight)", "Iron Butterfly", "Calendar Spread"
        ]
        result["risk_level"] = "HIGH"
        result["confidence"] = confidence
        result["signals"] = signals
        return result

    # High volatility regime
    if vix > 22 or rv_5d > 25:
        result["regime"] = MarketRegime.HIGH_VOLATILITY
        confidence = min(0.9, 0.5 + (vix - 15) / 30)
        result["recommended_strategies"] = [
            "Iron Condor (wide wings)", "Short Strangle (far OTM)", "Long Straddle"
        ]
        result["risk_level"] = "HIGH"
    # Strong trending up
    elif ema_diff_pct > 0.3 and adx > 25:
        result["regime"] = MarketRegime.TRENDING_UP
        confidence = min(0.9, 0.4 + adx / 100 + ema_diff_pct / 5)
        result["recommended_strategies"] = [
            "Bull Call Spread", "Bull Put Spread", "Jade Lizard"
        ]
        result["risk_level"] = "MEDIUM"
    # Strong trending down
    elif ema_diff_pct < -0.3 and adx > 25:
        result["regime"] = MarketRegime.TRENDING_DOWN
        confidence = min(0.9, 0.4 + adx / 100 + abs(ema_diff_pct) / 5)
        result["recommended_strategies"] = [
            "Bear Put Spread", "Bear Call Spread", "Long Put"
        ]
        result["risk_level"] = "MEDIUM"
    # Range-bound
    else:
        result["regime"] = MarketRegime.RANGE_BOUND
        confidence = max(0.4, 0.7 - adx / 100)
        result["recommended_strategies"] = [
            "Short Straddle", "Short Strangle", "Iron Condor"
        ]
        result["risk_level"] = "LOW"

    result["confidence"] = round(min(confidence, 0.95), 2)
    result["signals"] = signals
    return result


# ═══════════════════════════════════════════════════════════════
# INNOVATION 1 — AI STRATEGY SUGGESTER
# ═══════════════════════════════════════════════════════════════

def score_strategy_for_regime(strategy_name: str, regime_info: Dict) -> Dict:
    """Score a strategy based on current market regime (Innovation 1).

    Scoring:
    - Regime fit (0-30)
    - R/R ratio proxy (0-20)
    - Capital efficiency (0-15)
    - Time decay benefit (0-10)
    - Historical performance proxy (0-25)
    """
    from strategies import PREDEFINED_STRATEGIES
    strat = PREDEFINED_STRATEGIES.get(strategy_name)
    if not strat:
        return {"score": 0, "breakdown": {}}

    regime = regime_info.get("regime", MarketRegime.RANGE_BOUND)
    confidence = regime_info.get("confidence", 0.5)

    # Regime fit (0-30)
    regime_fit_map = {
        MarketRegime.TRENDING_UP: {"Bull Call Spread": 30, "Bull Put Spread": 28, "Long Call": 25,
                                    "Jade Lizard": 22, "Short Strangle": 10, "Iron Condor": 12},
        MarketRegime.TRENDING_DOWN: {"Bear Put Spread": 30, "Bear Call Spread": 28, "Long Put": 25,
                                      "Short Strangle": 10, "Iron Condor": 12},
        MarketRegime.RANGE_BOUND: {"Short Straddle": 30, "Short Strangle": 28, "Iron Condor": 27,
                                    "Iron Butterfly": 25, "Wide Iron Condor": 24},
        MarketRegime.HIGH_VOLATILITY: {"Iron Condor": 25, "Wide Iron Condor": 28, "Long Straddle": 24,
                                        "Long Strangle": 22, "Short Strangle": 15},
        MarketRegime.PRE_EXPIRY: {"Short Straddle": 28, "Iron Butterfly": 27, "Iron Condor": 25,
                                   "Short Strangle": 20},
    }
    regime_scores = regime_fit_map.get(regime, {})
    regime_fit = regime_scores.get(strategy_name, 8)

    # R/R ratio proxy (0-20)
    risk_label = strat.get("risk", "Limited")
    rr_score = 15 if "Limited" in risk_label else 8

    # Capital efficiency (0-15)
    num_legs = len(strat.get("legs", []))
    capital_eff = max(5, 15 - num_legs * 2)

    # Time decay benefit (0-10)
    has_sell = any(l.get("action") == "sell" for l in strat.get("legs", []))
    theta_score = 10 if has_sell else 3

    # Historical performance proxy (0-25) — based on view match
    view = strat.get("view", "").lower()
    regime_lower = regime.lower().replace("_", " ")
    hist_score = 20 if regime_lower.replace("trending ", "") in view else 12

    total = regime_fit + rr_score + capital_eff + theta_score + hist_score
    total = min(total, 100)

    return {
        "score": total,
        "breakdown": {
            "regime_fit": regime_fit,
            "risk_reward": rr_score,
            "capital_efficiency": capital_eff,
            "time_decay": theta_score,
            "historical": hist_score,
        },
        "explanation": _generate_suggestion_explanation(strategy_name, regime, confidence, total),
    }


def _generate_suggestion_explanation(strategy_name: str, regime: str, confidence: float, score: int) -> str:
    """Generate a human-readable explanation for AI strategy suggestion."""
    regime_desc = {
        MarketRegime.TRENDING_UP: "upward trending market",
        MarketRegime.TRENDING_DOWN: "downward trending market",
        MarketRegime.RANGE_BOUND: "range-bound market",
        MarketRegime.HIGH_VOLATILITY: "high volatility environment",
        MarketRegime.PRE_EXPIRY: "pre-expiry period",
    }
    desc = regime_desc.get(regime, "current market conditions")
    strength = "strongly" if confidence > 0.7 else "moderately"
    return (
        f"{strategy_name} scores {score}/100 for the current {desc}. "
        f"The regime is {strength} detected (confidence: {confidence:.0%}). "
        f"This strategy is well-suited for these conditions."
    )


def get_ai_strategy_suggestions(regime_info: Dict, top_n: int = 3) -> List[Dict]:
    """Return top N strategy suggestions with scores and explanations (Innovation 1)."""
    from strategies import PREDEFINED_STRATEGIES
    scored = []
    for name in PREDEFINED_STRATEGIES:
        result = score_strategy_for_regime(name, regime_info)
        result["strategy_name"] = name
        scored.append(result)
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]


# ═══════════════════════════════════════════════════════════════
# INNOVATION 6 — REALIZED VS IMPLIED VOLATILITY DASHBOARD
# ═══════════════════════════════════════════════════════════════

def iv_rv_spread_analysis(atm_iv: float, historical_close: pd.Series, window: int = 5) -> Dict:
    """IV vs RV spread monitor showing volatility risk premium (Innovation 6).

    Thresholds:
    - spread > 30%: Strong sell signal (IV overpriced)
    - spread < -15%: Strong buy signal (IV underpriced)
    """
    rv_series = rolling_realized_vol(historical_close, window)
    rv_valid = rv_series.dropna()
    rv_current = float(rv_valid.iloc[-1]) if len(rv_valid) > 0 else 0.0

    spread = atm_iv - rv_current
    spread_pct = (spread / rv_current * 100) if rv_current > 0 else 0.0

    if spread_pct > 30:
        signal = "STRONG_SELL"
        signal_desc = "IV significantly overpriced vs RV — sell premium"
    elif spread_pct > 15:
        signal = "MILD_SELL"
        signal_desc = "IV moderately overpriced — consider selling premium"
    elif spread_pct < -15:
        signal = "STRONG_BUY"
        signal_desc = "IV significantly underpriced vs RV — buy premium"
    elif spread_pct < -5:
        signal = "MILD_BUY"
        signal_desc = "IV moderately underpriced — consider buying premium"
    else:
        signal = "NEUTRAL"
        signal_desc = "IV fairly priced relative to RV"

    return {
        "atm_iv": round(atm_iv, 2),
        "rv_current": round(rv_current, 2),
        "spread": round(spread, 2),
        "spread_pct": round(spread_pct, 2),
        "signal": signal,
        "signal_desc": signal_desc,
        "rv_series": rv_valid.tolist() if len(rv_valid) <= 100 else rv_valid.tail(100).tolist(),
    }


# ═══════════════════════════════════════════════════════════════
# TASK 3.3 — TRADE JOURNAL METRICS
# ═══════════════════════════════════════════════════════════════

def compute_trade_journal_metrics(trades: List[Dict], pnl_history: List[Dict]) -> Dict:
    """Compute comprehensive trade journal metrics (Task 3.3).

    Returns 10 metrics: Win Rate %, Profit Factor, Avg Win/Loss, Max Consecutive
    Wins/Losses, Sharpe Ratio, Calmar Ratio, and data for charts.
    """
    if not trades:
        return {
            "win_rate": 0.0, "profit_factor": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "max_consec_wins": 0, "max_consec_losses": 0, "sharpe": 0.0, "calmar": 0.0,
            "total_trades": 0, "total_pnl": 0.0,
        }

    pnl_values = [float(t.get("pnl", 0)) for t in trades]
    wins = [p for p in pnl_values if p > 0]
    losses = [p for p in pnl_values if p < 0]

    win_rate = len(wins) / len(pnl_values) * 100 if pnl_values else 0.0
    profit_factor = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else float('inf')
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = np.mean(losses) if losses else 0.0

    # Max consecutive wins/losses
    max_cw, max_cl, cw, cl = 0, 0, 0, 0
    for p in pnl_values:
        if p > 0:
            cw += 1
            cl = 0
        elif p < 0:
            cl += 1
            cw = 0
        else:
            cw = cl = 0
        max_cw = max(max_cw, cw)
        max_cl = max(max_cl, cl)

    # Sharpe from daily P&L
    daily_pnl = [float(h.get("realized_pnl", 0)) for h in pnl_history] if pnl_history else []
    sharpe = calculate_sharpe(daily_pnl) if daily_pnl else 0.0

    # Calmar ratio
    cumulative = list(np.cumsum(daily_pnl)) if daily_pnl else []
    max_dd = calculate_max_drawdown(cumulative) if cumulative else 0.0
    annual_return = sum(daily_pnl) / max(len(daily_pnl), 1) * 252
    calmar = (annual_return / abs(max_dd)) if max_dd != 0 else 0.0

    return {
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else 999.99,
        "avg_win": round(float(avg_win), 2),
        "avg_loss": round(float(avg_loss), 2),
        "max_consec_wins": max_cw,
        "max_consec_losses": max_cl,
        "sharpe": round(sharpe, 2),
        "calmar": round(calmar, 2),
        "total_trades": len(trades),
        "total_pnl": round(sum(pnl_values), 2),
    }
