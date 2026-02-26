"""Futures trading module for Breeze PRO."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import app_config as C
from breeze_api import BreezeAPIClient, convert_to_breeze_datetime

log = logging.getLogger(__name__)

NSE_HOLIDAYS_2025_2026 = {
    "2025-01-14", "2025-01-26", "2025-02-26", "2025-03-14", "2025-03-31",
    "2025-04-10", "2025-04-14", "2025-04-18", "2025-05-01", "2025-08-15",
    "2025-08-27", "2025-10-02", "2025-10-20", "2025-10-21", "2025-10-24",
    "2025-11-05", "2025-12-25", "2026-01-14", "2026-01-26", "2026-03-13",
    "2026-03-20", "2026-03-30", "2026-04-02", "2026-04-14", "2026-04-17",
    "2026-05-01", "2026-06-08", "2026-08-15", "2026-10-02", "2026-11-12",
    "2026-12-25",
}


def get_futures_expiries(instrument_name: str, count: int = 3, exchange: str = "NFO") -> List[str]:
    """Return next `count` monthly futures expiries (last Thursday adjusted for holidays)."""
    _ = exchange  # for future exchange-specific calendars
    THURSDAY = 3
    now = datetime.now(C.IST)

    result: List[str] = []
    for month_offset in range(count + 6):
        month = (now.month + month_offset - 1) % 12 + 1
        year = now.year + (now.month + month_offset - 1) // 12

        last_day = date(year + 1, 1, 1) - timedelta(days=1) if month == 12 else date(year, month + 1, 1) - timedelta(days=1)
        expiry = last_day - timedelta(days=(last_day.weekday() - THURSDAY) % 7)

        attempts = 0
        while (expiry.isoformat() in NSE_HOLIDAYS_2025_2026 or expiry.weekday() >= 5) and attempts < 7:
            expiry -= timedelta(days=1)
            attempts += 1

        if expiry >= now.date():
            result.append(expiry.isoformat())
            if len(result) >= count:
                break

    return result[:count]


def calculate_basis(futures_price: float, spot_price: float) -> float:
    return round(futures_price - spot_price, 2)


def estimate_fair_value_futures(spot: float, days_to_expiry: int, risk_free_rate: float = C.RISK_FREE_RATE, dividend_yield: float = 0.01) -> float:
    import math

    T = max(days_to_expiry, 0) / C.DAYS_PER_YEAR
    return round(spot * math.exp((risk_free_rate - dividend_yield) * T), 2)


@dataclass
class FuturesOrderRequest:
    stock_code: str
    exchange_code: str
    expiry_date: str
    action: str
    lots: int
    lot_size: int
    order_type: str
    limit_price: float = 0.0
    stop_price: float = 0.0
    product_type: str = "futures"


def validate_futures_order(req: FuturesOrderRequest, available_margin: float) -> Tuple[bool, str]:
    if req.lots <= 0:
        return False, f"Lots must be positive, got {req.lots}"
    if req.lots > C.MAX_LOTS_PER_ORDER:
        return False, f"Lots ({req.lots}) exceeds maximum ({C.MAX_LOTS_PER_ORDER})"
    if req.order_type in ("limit", "stop_limit") and req.limit_price <= 0:
        return False, "Limit price must be positive for limit orders"
    if req.order_type in ("stop_market", "stop_limit") and req.stop_price <= 0:
        return False, "Stop price must be positive for stop orders"

    if req.order_type == "stop_limit":
        if req.action == "buy" and req.stop_price > req.limit_price:
            return False, f"For stop-limit buy: stop ({req.stop_price}) must be ≤ limit ({req.limit_price})."
        if req.action == "sell" and req.stop_price < req.limit_price:
            return False, f"For stop-limit sell: stop ({req.stop_price}) must be ≥ limit ({req.limit_price})."

    quantity = req.lots * req.lot_size
    price_proxy = req.limit_price or req.stop_price or 22000
    estimated_margin = quantity * price_proxy * 0.15
    if available_margin > 0 and estimated_margin > available_margin * 1.1:
        return False, (
            f"Estimated margin required (₹{estimated_margin:,.0f}) may exceed available margin "
            f"(₹{available_margin:,.0f})."
        )
    return True, ""


def build_futures_place_order_kwargs(req: FuturesOrderRequest) -> Dict:
    expiry_iso = convert_to_breeze_datetime(req.expiry_date)
    quantity = req.lots * req.lot_size

    if req.order_type == "market":
        breeze_order_type, price_str, stoploss_str = "market", "", "0"
    elif req.order_type == "limit":
        breeze_order_type, price_str, stoploss_str = "limit", str(req.limit_price), "0"
    elif req.order_type == "stop_market":
        breeze_order_type, price_str, stoploss_str = "stoploss", "", str(req.stop_price)
    elif req.order_type == "stop_limit":
        breeze_order_type, price_str, stoploss_str = "stoploss", str(req.limit_price), str(req.stop_price)
    else:
        raise ValueError(f"Unsupported order_type: {req.order_type!r}")

    return dict(
        stock_code=req.stock_code,
        exchange_code=req.exchange_code,
        product=req.product_type,
        action=req.action.lower(),
        order_type=breeze_order_type,
        quantity=str(quantity),
        price=price_str,
        stoploss=stoploss_str,
        validity="day",
        expiry_date=expiry_iso,
        right="",
        strike_price="",
        disclosed_quantity="0",
        user_remark="Futures",
    )


@dataclass
class RollPlan:
    stock_code: str
    exchange_code: str
    near_expiry: str
    far_expiry: str
    lots: int
    lot_size: int
    near_ltp: float
    far_ltp: float
    roll_cost: float
    roll_cost_pct: float


def build_roll_plan(client: BreezeAPIClient, stock_code: str, exchange_code: str, near_expiry: str, far_expiry: str, lots: int, lot_size: int) -> Optional[RollPlan]:
    near_resp = client.get_futures_quote(stock_code, exchange_code, near_expiry)
    far_resp = client.get_futures_quote(stock_code, exchange_code, far_expiry)
    if not (near_resp.get("success") and far_resp.get("success")):
        return None

    def _ltp(resp: Dict) -> float:
        success = (resp.get("data", {}) or {}).get("Success")
        if isinstance(success, list) and success:
            success = success[0]
        if isinstance(success, dict):
            try:
                return float(success.get("ltp", 0) or 0)
            except Exception:
                return 0.0
        return 0.0

    near_ltp, far_ltp = _ltp(near_resp), _ltp(far_resp)
    if near_ltp <= 0:
        return None
    roll_cost = far_ltp - near_ltp
    return RollPlan(stock_code, exchange_code, near_expiry, far_expiry, lots, lot_size, near_ltp, far_ltp, roll_cost, roll_cost / near_ltp * 100)


def execute_roll(client: BreezeAPIClient, roll_plan: RollPlan, current_position_action: str, order_type: str = "market") -> Tuple[Dict, Dict]:
    close_action = "sell" if current_position_action == "buy" else "buy"
    close_req = FuturesOrderRequest(roll_plan.stock_code, roll_plan.exchange_code, roll_plan.near_expiry, close_action, roll_plan.lots, roll_plan.lot_size, order_type)
    open_req = FuturesOrderRequest(roll_plan.stock_code, roll_plan.exchange_code, roll_plan.far_expiry, current_position_action, roll_plan.lots, roll_plan.lot_size, order_type)
    close_resp = client.place_order(**build_futures_place_order_kwargs(close_req))
    open_resp = client.place_order(**build_futures_place_order_kwargs(open_req))
    return close_resp, open_resp


def render_basis_chart(futures_data: Dict[str, float], spot_price: float, instrument: str, height: int = 350):
    import plotly.graph_objects as go

    if not futures_data or spot_price <= 0:
        fig = go.Figure()
        fig.add_annotation(text="No futures data", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        return fig

    expiries = sorted(futures_data.keys())
    basis_values = [round(futures_data[e] - spot_price, 2) for e in expiries]
    colors = ["#26a69a" if b >= 0 else "#ef5350" for b in basis_values]
    labels = []
    for e in expiries:
        try:
            labels.append(datetime.strptime(e[:10], "%Y-%m-%d").strftime("%b-%y"))
        except Exception:
            labels.append(e[:7])

    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=basis_values, marker_color=colors, text=[f"₹{b:+.1f}" for b in basis_values], textposition="outside", name="Basis"))
    fig.add_hline(y=0, line_color="rgba(230,237,243,0.4)", line_width=1)
    fig.update_layout(
        title=f"{instrument} Futures Basis (vs Spot ₹{spot_price:,.0f})",
        yaxis_title="Basis ₹ (Futures − Spot)",
        height=height,
        plot_bgcolor="#0d1117",
        paper_bgcolor="#161b22",
        font=dict(color="#e6edf3"),
        margin=dict(l=10, r=10, t=50, b=10),
        showlegend=False,
    )
    return fig
