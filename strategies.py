"""
Strategy Builder — 15+ predefined strategies, payoff diagrams, metrics.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd


@dataclass
class StrategyLeg:
    strike: int
    option_type: str   # CE / PE
    action: str        # buy / sell
    quantity: int
    premium: float = 0.0
    expiry: str = ""
    label: str = ""


@dataclass
class SuggestionResult:
    strategy: str
    score: float
    reason: str


PREDEFINED_STRATEGIES: Dict[str, Dict[str, Any]] = {
    # ── Neutral ──────────────────────────────────────────────────
    "Short Straddle": {
        "description": "Sell ATM Call + Put. Max profit when underlying stays at ATM. Suitable for low-vol environments.",
        "legs": [{"offset": 0, "type": "CE", "action": "sell", "label": "ATM CE"},
                 {"offset": 0, "type": "PE", "action": "sell", "label": "ATM PE"}],
        "view": "Neutral", "risk": "Unlimited", "reward": "Limited (premium)",
        "category": "Neutral Sell", "complexity": "Beginner",
    },
    "Short Strangle": {
        "description": "Sell OTM Call + OTM Put. Wider break-even range than straddle. Better risk/reward.",
        "legs": [{"offset": 2, "type": "CE", "action": "sell", "label": "OTM CE"},
                 {"offset": -2, "type": "PE", "action": "sell", "label": "OTM PE"}],
        "view": "Neutral/Range", "risk": "Unlimited", "reward": "Limited (premium)",
        "category": "Neutral Sell", "complexity": "Beginner",
    },
    "Iron Condor": {
        "description": "Sell OTM call & put spreads. Limited risk, defined profit zone. Classic premium harvesting.",
        "legs": [{"offset": -3, "type": "PE", "action": "buy", "label": "Far OTM PE"},
                 {"offset": -1, "type": "PE", "action": "sell", "label": "OTM PE"},
                 {"offset": 1, "type": "CE", "action": "sell", "label": "OTM CE"},
                 {"offset": 3, "type": "CE", "action": "buy", "label": "Far OTM CE"}],
        "view": "Neutral", "risk": "Limited", "reward": "Limited (premium)",
        "category": "Neutral Sell", "complexity": "Intermediate",
    },
    "Iron Butterfly": {
        "description": "ATM straddle sell + OTM strangle buy. Higher premium than Iron Condor, narrower range.",
        "legs": [{"offset": -2, "type": "PE", "action": "buy", "label": "OTM PE"},
                 {"offset": 0, "type": "PE", "action": "sell", "label": "ATM PE"},
                 {"offset": 0, "type": "CE", "action": "sell", "label": "ATM CE"},
                 {"offset": 2, "type": "CE", "action": "buy", "label": "OTM CE"}],
        "view": "Neutral", "risk": "Limited", "reward": "Limited (premium)",
        "category": "Neutral Sell", "complexity": "Intermediate",
    },
    "Wide Iron Condor": {
        "description": "Iron Condor with wider wings. Better win rate, lower premium per trade.",
        "legs": [{"offset": -5, "type": "PE", "action": "buy", "label": "Far OTM PE"},
                 {"offset": -2, "type": "PE", "action": "sell", "label": "OTM PE"},
                 {"offset": 2, "type": "CE", "action": "sell", "label": "OTM CE"},
                 {"offset": 5, "type": "CE", "action": "buy", "label": "Far OTM CE"}],
        "view": "Neutral", "risk": "Limited", "reward": "Limited (premium)",
        "category": "Neutral Sell", "complexity": "Intermediate",
    },
    # ── Bullish ──────────────────────────────────────────────────
    "Bull Call Spread": {
        "description": "Buy lower strike call + sell higher strike call. Defined risk bullish bet.",
        "legs": [{"offset": -1, "type": "CE", "action": "buy", "label": "ATM-1 CE"},
                 {"offset": 1, "type": "CE", "action": "sell", "label": "ATM+1 CE"}],
        "view": "Bullish", "risk": "Limited", "reward": "Limited",
        "category": "Directional Buy", "complexity": "Beginner",
    },
    "Bull Put Spread": {
        "description": "Sell higher put + buy lower put. Net credit bullish strategy.",
        "legs": [{"offset": -1, "type": "PE", "action": "buy", "label": "OTM PE"},
                 {"offset": 0, "type": "PE", "action": "sell", "label": "ATM PE"}],
        "view": "Bullish", "risk": "Limited", "reward": "Limited (credit)",
        "category": "Neutral Sell", "complexity": "Intermediate",
    },
    "Long Call": {
        "description": "Buy ATM call. Simple bullish bet with defined risk.",
        "legs": [{"offset": 0, "type": "CE", "action": "buy", "label": "ATM CE"}],
        "view": "Bullish", "risk": "Limited (premium)", "reward": "Unlimited",
        "category": "Directional Buy", "complexity": "Beginner",
    },
    # ── Bearish ──────────────────────────────────────────────────
    "Bear Put Spread": {
        "description": "Buy higher put + sell lower put. Defined risk bearish strategy.",
        "legs": [{"offset": 1, "type": "PE", "action": "buy", "label": "ATM+1 PE"},
                 {"offset": -1, "type": "PE", "action": "sell", "label": "OTM PE"}],
        "view": "Bearish", "risk": "Limited", "reward": "Limited",
        "category": "Directional Buy", "complexity": "Beginner",
    },
    "Bear Call Spread": {
        "description": "Sell lower call + buy higher call. Net credit bearish strategy.",
        "legs": [{"offset": 0, "type": "CE", "action": "sell", "label": "ATM CE"},
                 {"offset": 2, "type": "CE", "action": "buy", "label": "OTM CE"}],
        "view": "Bearish", "risk": "Limited", "reward": "Limited (credit)",
        "category": "Neutral Sell", "complexity": "Intermediate",
    },
    "Long Put": {
        "description": "Buy ATM put. Simple bearish bet with defined risk.",
        "legs": [{"offset": 0, "type": "PE", "action": "buy", "label": "ATM PE"}],
        "view": "Bearish", "risk": "Limited (premium)", "reward": "Substantial",
        "category": "Directional Buy", "complexity": "Beginner",
    },
    # ── Volatile ─────────────────────────────────────────────────
    "Long Straddle": {
        "description": "Buy ATM Call + Put. Profit from big moves in either direction.",
        "legs": [{"offset": 0, "type": "CE", "action": "buy", "label": "ATM CE"},
                 {"offset": 0, "type": "PE", "action": "buy", "label": "ATM PE"}],
        "view": "Volatile", "risk": "Limited (premium)", "reward": "Unlimited",
        "category": "Directional Buy", "complexity": "Beginner",
    },
    "Long Strangle": {
        "description": "Buy OTM Call + Put. Cheaper than straddle, needs bigger move to profit.",
        "legs": [{"offset": 2, "type": "CE", "action": "buy", "label": "OTM CE"},
                 {"offset": -2, "type": "PE", "action": "buy", "label": "OTM PE"}],
        "view": "Volatile", "risk": "Limited (premium)", "reward": "Unlimited",
        "category": "Directional Buy", "complexity": "Beginner",
    },
    # ── Advanced ─────────────────────────────────────────────────
    "Jade Lizard": {
        "description": "Sell OTM put + sell OTM call spread. No upside risk, defined downside.",
        "legs": [{"offset": -2, "type": "PE", "action": "sell", "label": "OTM PE"},
                 {"offset": 1, "type": "CE", "action": "sell", "label": "OTM CE"},
                 {"offset": 3, "type": "CE", "action": "buy", "label": "Far OTM CE"}],
        "view": "Bullish/Neutral", "risk": "Limited (downside)", "reward": "Limited (premium)",
        "category": "Advanced", "complexity": "Advanced",
    },
    "Broken Wing Butterfly CE": {
        "description": "Asymmetric butterfly: sell 2x ATM calls, buy ITM + far OTM. Net credit if done right.",
        "legs": [{"offset": -1, "type": "CE", "action": "buy", "label": "ITM CE"},
                 {"offset": 0, "type": "CE", "action": "sell", "label": "ATM CE (2x)", "multiplier": 2},
                 {"offset": 2, "type": "CE", "action": "buy", "label": "OTM CE"}],
        "view": "Neutral/Bearish", "risk": "Limited", "reward": "Limited",
        "category": "Advanced", "complexity": "Advanced",
    },
    "Ratio Put Spread": {
        "description": "Buy 1 ATM put, sell 2 OTM puts. Net credit, profits if market stays range-bound.",
        "legs": [{"offset": 0, "type": "PE", "action": "buy", "label": "ATM PE"},
                 {"offset": -2, "type": "PE", "action": "sell", "label": "OTM PE (2x)", "multiplier": 2}],
        "view": "Neutral/Mildly Bearish", "risk": "Unlimited (below)", "reward": "Limited",
        "category": "Advanced", "complexity": "Advanced",
    },
    "Calendar Spread": {
        "description": "Buy near-month option and sell far-month option at same strike (expiry differential play).",
        "legs": [{"offset": 0, "type": "CE", "action": "buy", "label": "Near CE"},
                 {"offset": 0, "type": "CE", "action": "sell", "label": "Far CE"}],
        "view": "Volatility/Theta", "risk": "Limited", "reward": "Limited",
        "category": "Advanced", "complexity": "Advanced",
    },
    "Diagonal Spread": {
        "description": "Buy near-month ITM and sell far-month OTM (different strikes + expiries).",
        "legs": [{"offset": -1, "type": "CE", "action": "buy", "label": "Near ITM CE"},
                 {"offset": 1, "type": "CE", "action": "sell", "label": "Far OTM CE"}],
        "view": "Directional/Theta", "risk": "Limited", "reward": "Limited",
        "category": "Advanced", "complexity": "Advanced",
    },
}

STRATEGY_CATEGORIES = sorted(set(v["category"] for v in PREDEFINED_STRATEGIES.values()))
STRATEGY_COMPLEXITIES = ["Beginner", "Intermediate", "Advanced"]


def _snap_to_nearest_strike(target: int, available_strikes: Optional[set]) -> int:
    """Snap a computed strike to the nearest available strike in the chain.

    If *available_strikes* is None or empty the target is returned unchanged.
    This prevents strategy legs from referencing strikes that don't actually
    exist in the fetched option chain (Task 1.5).
    """
    if not available_strikes:
        return target
    return min(available_strikes, key=lambda s: abs(s - target))


def generate_strategy_legs(strategy_name: str, atm_strike: int,
                           strike_gap: int, lot_size: int,
                           lots: int = 1,
                           available_strikes: Optional[set] = None,
                           default_expiry: str = "",
                           expiry_by_action: Optional[Dict[str, str]] = None) -> List[StrategyLeg]:
    """Generate legs for a predefined strategy.

    If *available_strikes* is provided, each computed strike is snapped to
    the nearest real strike in the set (Task 1.5).
    """
    strat = PREDEFINED_STRATEGIES.get(strategy_name)
    if not strat:
        raise ValueError(f"Unknown strategy: {strategy_name}")
    qty = lots * lot_size
    legs = []
    for leg in strat["legs"]:
        multiplier = leg.get("multiplier", 1)
        raw_strike = atm_strike + leg["offset"] * strike_gap
        strike = _snap_to_nearest_strike(raw_strike, available_strikes)
        legs.append(StrategyLeg(
            strike=strike,
            option_type=leg["type"],
            action=leg["action"],
            quantity=qty * multiplier,
            expiry=(expiry_by_action or {}).get(leg["action"], default_expiry),
            label=leg.get("label", "")
        ))
    return legs


def calculate_strategy_metrics(legs: List[StrategyLeg]) -> Dict[str, Any]:
    net_premium = sum(
        (leg.premium * leg.quantity if leg.action == "sell" else -leg.premium * leg.quantity)
        for leg in legs
    )
    all_strikes = [l.strike for l in legs]
    if not all_strikes:
        return {"net_premium": 0, "max_profit": 0, "max_loss": 0, "breakevens": []}

    spread = max(max(all_strikes) - min(all_strikes), 100)
    low = min(all_strikes) - 10 * spread
    high = max(all_strikes) + 10 * spread
    spots = np.linspace(low, high, 1000)
    payoffs = _calc_payoffs(legs, spots)

    breakevens = []
    for i in range(len(payoffs) - 1):
        if payoffs[i] * payoffs[i + 1] < 0:
            be = spots[i] - payoffs[i] * (spots[i + 1] - spots[i]) / (payoffs[i + 1] - payoffs[i])
            breakevens.append(round(float(be), 0))

    theta_differential = 0.0
    for leg in legs:
        if leg.expiry:
            try:
                dte = max((datetime.strptime(str(leg.expiry)[:10], "%Y-%m-%d") - datetime.now()).days, 1)
            except ValueError:
                dte = 1
            theta_weight = (leg.quantity / np.sqrt(dte))
            theta_differential += theta_weight if leg.action == "sell" else -theta_weight

    return {
        "net_premium": round(net_premium, 2),
        "max_profit": round(float(max(payoffs)), 2),
        "max_loss": round(float(min(payoffs)), 2),
        "breakevens": breakevens,
        "reward_risk": abs(round(float(max(payoffs)) / float(min(payoffs)), 2)) if min(payoffs) != 0 else float('inf'),
        "theta_differential": round(float(theta_differential), 2),
    }


def generate_payoff_data(legs: List[StrategyLeg], center: float,
                         gap: int, points: int = 300) -> Optional[pd.DataFrame]:
    if not legs:
        return None
    all_strikes = [l.strike for l in legs]
    low = min(all_strikes) - 8 * gap
    high = max(all_strikes) + 8 * gap
    spots = np.linspace(low, high, points)
    payoffs = _calc_payoffs(legs, spots)
    return pd.DataFrame({"Underlying": spots, "P&L": payoffs})


def _calc_payoffs(legs: List[StrategyLeg], spots: np.ndarray) -> np.ndarray:
    payoffs = np.zeros(len(spots))
    for leg in legs:
        if leg.option_type == "CE":
            intrinsic = np.maximum(spots - leg.strike, 0)
        else:
            intrinsic = np.maximum(leg.strike - spots, 0)
        if leg.action == "sell":
            payoffs += (leg.premium - intrinsic) * leg.quantity
        else:
            payoffs += (intrinsic - leg.premium) * leg.quantity
    return payoffs


def get_strategies_by_category(category: str = None) -> Dict:
    if not category or category == "All":
        return PREDEFINED_STRATEGIES
    return {k: v for k, v in PREDEFINED_STRATEGIES.items() if v["category"] == category}


def get_strategies_by_view(view: str) -> Dict:
    view_lower = view.lower()
    return {k: v for k, v in PREDEFINED_STRATEGIES.items()
            if view_lower in v["view"].lower()}


class AIStrategySuggester:
    """Rule-based strategy ranker with trader-specific win-rate weighting."""

    def suggest(
        self,
        regime: Dict[str, Any],
        vix: float,
        pcr: float,
        trader_win_rates: Dict[str, float],
        available_capital: float,
        days_to_expiry: int,
    ) -> List[SuggestionResult]:
        regime_name = str(regime.get("regime", "RANGE_BOUND"))
        preferred = set(regime.get("recommended_strategies", []))
        results: List[SuggestionResult] = []
        for name, meta in PREDEFINED_STRATEGIES.items():
            score = 0.0
            # 1) Regime fit 0-30
            if name in preferred:
                score += 30.0
            elif regime_name.lower() in str(meta.get("view", "")).lower():
                score += 20.0
            else:
                score += 8.0
            # 2) Trader history 0-25
            score += min(max(trader_win_rates.get(name, 50.0), 0.0), 100.0) * 0.25
            # 3) Risk/reward proxy 0-20 (favor defined-risk in high VIX)
            risk = str(meta.get("risk", "")).lower()
            if vix >= 20 and "limited" in risk:
                score += 16.0
            elif vix < 15 and "unlimited" in risk:
                score += 8.0
            else:
                score += 12.0
            # 4) Capital efficiency 0-15 (penalize complex advanced)
            complexity = str(meta.get("complexity", "Intermediate")).lower()
            if complexity == "beginner":
                score += 14.0
            elif complexity == "intermediate":
                score += 10.0
            else:
                score += 7.0 if available_capital > 100000 else 4.0
            # 5) DTE suitability 0-10
            if 3 <= days_to_expiry <= 15:
                score += 10.0
            elif 16 <= days_to_expiry <= 35:
                score += 7.0
            else:
                score += 4.0
            reason = f"Regime={regime_name}, VIX={vix:.1f}, PCR={pcr:.2f}, DTE={days_to_expiry}"
            results.append(SuggestionResult(strategy=name, score=round(score, 2), reason=reason))
        return sorted(results, key=lambda x: x.score, reverse=True)[:3]
