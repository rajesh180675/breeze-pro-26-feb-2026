"""
Breeze Options Trader PRO v10.0
Production-grade terminal for ICICI Breeze Options Trading.

Enhanced features:
- 12 pages: Dashboard, Option Chain, Sell, Square Off, Orders, Positions,
            Strategy Builder, Analytics, Historical Data, Risk Monitor, Watchlist, Settings
- Auto-refresh with live countdown
- IV Smile + Term Structure charts
- Stress Testing / Scenario Analysis
- Portfolio Greeks heatmap
- Bulk square-off
- CSV/Excel export
- Persistent watchlist
- P&L history charts
- Enhanced notifications
- Dark mode via Streamlit config
"""

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
from functools import wraps
import time
import logging
import io
from typing import Any, Dict, List, Optional

import app_config as C
from helpers import (
    APIResponse, safe_background_gradient, safe_int, safe_float, safe_str, parse_funds,
    detect_position_type, get_closing_action, calculate_pnl, enrich_positions,
    get_market_status, format_currency,
    format_expiry, format_expiry_short, calculate_days_to_expiry,
    format_number, pnl_badge
)
from analytics import (
    calculate_greeks, estimate_implied_volatility,
    calculate_portfolio_greeks, stress_test_portfolio,
    calculate_iv_smile, calculate_max_drawdown, calculate_var,
    monte_carlo_var, rolling_realized_vol, iv_vs_rv_spread, portfolio_correlation_matrix,
    detect_market_regime
)
from session_manager import (
    Credentials, SessionState, CacheManager, Notifications,
    generate_totp, auto_connect_with_totp, AppWarmupManager,
    MultiAccountManager, AccountProfile
)
from breeze_api import BreezeAPIClient
from validators import validate_date_range
from strategies import (
    StrategyLeg, PREDEFINED_STRATEGIES, STRATEGY_CATEGORIES,
    generate_strategy_legs, calculate_strategy_metrics,
    generate_payoff_data, get_strategies_by_category, AIStrategySuggester
)
from persistence import TradeDB, AccountProfileDB, export_trades_for_tax
from risk_monitor import RiskMonitor, Alert, ExpiryDayAutopilot
from alerting import (
    AlertConfig, AlertDispatcher, TelegramDispatcher, EmailDispatcher
)
from paper_trading import PaperTradingEngine
import live_feed as lf
import holiday_calendar as _hc   # dynamic NSE holiday calendar
from option_chain_controller import (
    apply_option_chain_live_overlay,
    invalidate_option_chain_cache,
    load_cached_option_chain,
    load_compare_option_frames,
    load_option_chain_spot,
    render_option_chain_controls,
    resolve_replay_chain_selection,
    sync_option_chain_live_feed,
    sync_option_chain_watchlist,
)
from option_chain_metrics import calculate_max_pain, calculate_pcr
from option_chain_page import (
    build_option_chain_chart,
    render_option_chain_analysis,
    render_option_chain_chart,
    render_option_chain_display,
)
from option_chain_summary import render_option_chain_summary
from option_chain_view_model import build_option_chain_page_view_model
from option_chain_service import (
    compose_option_chain_workspace,
    estimate_atm_strike,
    filter_option_chain,
)
from option_chain_state import ensure_option_chain_state, update_option_chain_state
from option_chain_utils import process_option_chain
from option_chain_workspace import (
    resolve_selected_strike,
)

# ─── Logging ──────────────────────────────────────────────────
# Ensure logs directory exists before FileHandler is created.
# logging.basicConfig with FileHandler("logs/app.log") will crash with
# FileNotFoundError if the directory does not exist yet — and main() creates
# it too late because this code runs at import / module level.
import os as _os
_os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/app.log", mode='a')
    ]
)
log = logging.getLogger(__name__)

# ─── Singleton DB ─────────────────────────────────────────────
_db = TradeDB()

# ═══════════════════════════════════════════════════════════════
# PAGE CONFIG & CSS
# ═══════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Breeze PRO Trader",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

THEME_CSS = """
<style>
/* ── Layout ── */
#MainMenu {visibility:hidden}
footer {visibility:hidden}
header {visibility:hidden}
.block-container {padding-top:1rem;padding-bottom:1rem}

/* ── Typography ── */
.page-header {
    font-size:1.9rem;font-weight:800;
    background:linear-gradient(135deg,#1f77b4,#17a2b8);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;
    border-bottom:3px solid #1f77b4;padding-bottom:.5rem;margin-bottom:1.5rem
}
.section-header {
    font-size:1.3rem;font-weight:700;color:#2c3e50;
    margin:1.2rem 0 .8rem;border-left:4px solid #1f77b4;padding-left:.7rem
}
.subsection {font-size:1.1rem;font-weight:600;color:#495057;margin:.8rem 0 .4rem}

/* ── Status badges ── */
.badge-connected {
    background:#d4edda;color:#155724;padding:5px 14px;
    border-radius:20px;font-weight:700;font-size:.85rem;display:inline-block
}
.badge-warning {
    background:#fff3cd;color:#856404;padding:5px 14px;
    border-radius:20px;font-weight:700;font-size:.85rem;display:inline-block
}
.badge-danger {
    background:#f8d7da;color:#721c24;padding:5px 14px;
    border-radius:20px;font-weight:700;font-size:.85rem;display:inline-block
}

/* ── P&L Colors ── */
.profit {color:#28a745!important;font-weight:700}
.loss {color:#dc3545!important;font-weight:700}
.neutral {color:#6c757d!important}

/* ── Cards ── */
.metric-card {
    background:#f8f9fa;padding:1.2rem;border-radius:10px;
    border:1px solid #dee2e6;margin:.4rem 0;
    box-shadow:0 1px 3px rgba(0,0,0,.06)
}
.metric-card-green {
    background:linear-gradient(135deg,#d4edda,#c3e6cb);
    border-color:#28a745;padding:1.2rem;border-radius:10px;margin:.4rem 0
}
.metric-card-red {
    background:linear-gradient(135deg,#f8d7da,#f5c6cb);
    border-color:#dc3545;padding:1.2rem;border-radius:10px;margin:.4rem 0
}

/* ── Alerts ── */
.info-box {
    background:#e7f3ff;border-left:5px solid #2196F3;
    padding:1rem;margin:.8rem 0;border-radius:0 8px 8px 0
}
.danger-box {
    background:#fdecea;border-left:5px solid #dc3545;
    padding:1rem;margin:.8rem 0;border-radius:0 8px 8px 0
}
.warn-box {
    background:#fff8e1;border-left:5px solid #ff9800;
    padding:1rem;margin:.8rem 0;border-radius:0 8px 8px 0
}
.success-box {
    background:#e8f5e9;border-left:5px solid #4caf50;
    padding:1rem;margin:.8rem 0;border-radius:0 8px 8px 0
}

/* ── Empty state ── */
.empty-state {text-align:center;padding:2.5rem 1rem;color:#6c757d}
.empty-state-icon {font-size:3rem;margin-bottom:.8rem;opacity:.5}

/* ── Market status pill ── */
.mkt-open {
    background:#e8f5e9;color:#2e7d32;padding:4px 12px;
    border-radius:20px;font-weight:700;font-size:.8rem
}
.mkt-closed {
    background:#ffebee;color:#c62828;padding:4px 12px;
    border-radius:20px;font-weight:700;font-size:.8rem
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {background:#0f1117}
[data-testid="stSidebar"] * {color:#fafafa}

/* ── Data table ── */
.stDataFrame {border-radius:8px;overflow:hidden}

/* ── Button variants ── */
.stButton button[kind="primary"] {
    background:linear-gradient(135deg,#1f77b4,#17a2b8);
    border:none;font-weight:700
}
</style>
"""

BREEZE_PRO_CSS = """
<style>
:root {
  --bg-primary:#0d1117; --bg-secondary:#161b22; --bg-card:#1c2128;
  --border:#30363d; --text-primary:#e6edf3; --text-muted:#8b949e;
  --accent:#388bfd; --success:#3fb950; --warning:#d29922; --danger:#f85149;
}
.stApp { background-color: var(--bg-primary); color: var(--text-primary); }
.stSidebar { background-color: var(--bg-secondary) !important; }
.page-header { color: var(--text-primary); border-bottom: 2px solid var(--accent); }
.metric-card { background: var(--bg-card); border:1px solid var(--border); border-radius:8px; }
.metric-label { color: var(--text-muted); }
.metric-value { color: var(--text-primary); font-weight:700; }
.stDataFrame thead { background: var(--bg-secondary) !important; }
.stDataFrame tbody tr:hover { background: var(--bg-card) !important; }
.stButton > button[kind="primary"] { background-color: var(--accent); border:none; font-weight:600; }
.stButton > button[kind="primary"]:hover { background-color:#58a6ff; box-shadow:0 0 8px rgba(56,139,253,.4); }
.badge-success { color: var(--success); font-weight:600; }
.badge-danger { color: var(--danger); font-weight:600; }
.badge-warning { color: var(--warning); font-weight:600; }
.badge-muted { color: var(--text-muted); }
.scroll-table { max-height:400px; overflow-y:auto; border:1px solid var(--border); border-radius:6px; }
</style>
"""

KEYBOARD_SHORTCUTS_JS = """
<script>
document.addEventListener('keydown', function(e) {
  if (e.altKey && e.key >= '1' && e.key <= '9') {
    e.preventDefault();
    const pages = document.querySelectorAll('[data-testid="stRadio"] label');
    const idx = parseInt(e.key) - 1;
    if (pages[idx]) pages[idx].click();
  }
  if (e.altKey && (e.key === 'r' || e.key === 'R')) {
    e.preventDefault();
    const refreshBtns = document.querySelectorAll('button');
    for (const btn of refreshBtns) {
      if (btn.textContent.includes('Refresh') || btn.textContent.includes('🔄')) { btn.click(); break; }
    }
  }
});
</script>
"""

RESPONSIVE_CSS = """
<style>
@media (max-width: 768px) {
  section[data-testid="stSidebar"] { width: 0 !important; }
  .page-header { font-size: 1.2rem; }
  .stColumns { flex-direction: column !important; }
}
</style>
"""

st.markdown(THEME_CSS, unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════

# PAGES is populated after all page functions are defined (see bottom of file).
# Using None placeholders here keeps sidebar navigation key order stable at import time.
PAGES = {
    "🏠 Dashboard": None,
    "⛓️ Option Chain": None,
    "💸 Sell Options": None,
    "❌ Square Off": None,
    "📋 Orders & Trades": None,
    "💼 Positions": None,
    "📊 Historical Data": None,
    "📈 Futures Trading": None,
    "⏰ GTT Orders": None,
    "🧠 Strategy Builder": None,
    "🔬 Analytics": None,
    "🚨 Risk Monitor": None,
    "👁️ Watchlist": None,
    "📄 Paper Trading": None,
    "⚙️ Settings": None,
}

AUTH_PAGES = set([k for k in PAGES.keys() if k != "🏠 Dashboard"])


# ═══════════════════════════════════════════════════════════════
# DECORATORS
# ═══════════════════════════════════════════════════════════════

def error_handler(f):
    @wraps(f)
    def w(*a, **k):
        try:
            return f(*a, **k)
        except Exception as e:
            log.error(f"{f.__name__}: {e}", exc_info=True)
            st.error(f"❌ Error: {e}")
            if st.session_state.get("debug_mode"):
                st.exception(e)
    return w


def require_auth(f):
    @wraps(f)
    def w(*a, **k):
        if not SessionState.is_authenticated():
            st.warning("🔒 Please connect your account first")
            if st.button("Go to Login →"):
                SessionState.navigate_to("🏠 Dashboard")
                st.rerun()
            return
        return f(*a, **k)
    return w


# ═══════════════════════════════════════════════════════════════
# COMMON UI HELPERS
# ═══════════════════════════════════════════════════════════════

def empty_state(icon, msg, sub=""):
    st.markdown(
        f'<div class="empty-state">'
        f'<div class="empty-state-icon">{icon}</div>'
        f'<h3>{msg}</h3><p style="opacity:.7">{sub}</p></div>',
        unsafe_allow_html=True
    )


def page_header(title: str):
    st.markdown(f'<h1 class="page-header">{title}</h1>', unsafe_allow_html=True)


def section(title: str):
    st.markdown(f'<h2 class="section-header">{title}</h2>', unsafe_allow_html=True)


def info_box(text: str):
    st.markdown(f'<div class="info-box">{text}</div>', unsafe_allow_html=True)


def warn_box(text: str):
    st.markdown(f'<div class="warn-box">{text}</div>', unsafe_allow_html=True)


def danger_box(text: str):
    st.markdown(f'<div class="danger-box">{text}</div>', unsafe_allow_html=True)


def pnl_metric(label: str, value: float, col=None):
    color = "#28a745" if value >= 0 else "#dc3545"
    icon = "▲" if value >= 0 else "▼"
    html = (f'<div class="metric-card">'
            f'<small style="color:#6c757d">{label}</small><br>'
            f'<span style="font-size:1.6rem;font-weight:800;color:{color}">'
            f'{icon} {format_currency(value)}</span></div>')
    target = col if col else st
    target.markdown(html, unsafe_allow_html=True)


def render_live_feed_status(client: BreezeAPIClient) -> None:
    """Render a compact live feed status indicator in the sidebar."""
    mgr = lf.get_live_feed_manager()
    if mgr is None:
        st.sidebar.caption("📡 WS: Not initialized")
        return

    stats = mgr.get_health_stats()
    state = stats["state"]

    if state == lf.FeedState.CONNECTED:
        color = "🟢"
        label = "Connected"
    elif state == lf.FeedState.RECONNECTING:
        color = "🟡"
        label = "Reconnecting..."
    elif state == lf.FeedState.CONNECTING:
        color = "🔵"
        label = "Connecting..."
    else:
        color = "🔴"
        label = "Disconnected"

    subs = stats["total_subscriptions"]
    ticks = stats["total_ticks"]
    last = stats["last_tick_secs_ago"]
    last_str = f"{last:.1f}s ago" if last is not None else "—"

    st.sidebar.markdown(
        f"**{color} WS {label}** | Subs: {subs} | Ticks: {ticks:,} | Last: {last_str}"
    )

    if stats["is_stale"] and C.is_market_open():
        st.sidebar.warning("⚠️ Feed may be stale. Consider reconnecting.")

    col1, col2 = st.sidebar.columns(2)
    with col1:
        if state in (lf.FeedState.DISCONNECTED, lf.FeedState.STOPPED):
            if st.button("▶ Connect", key="ws_connect_btn"):
                mgr.connect()
                st.rerun()
    with col2:
        if state == lf.FeedState.CONNECTED:
            if st.button("⏹ Disconnect", key="ws_disconnect_btn"):
                mgr.disconnect()
                st.rerun()


def render_live_price_badge(stock_token: str, fallback_price: float = 0.0, col=None) -> None:
    """Display a live LTP badge that reads from TickStore."""
    tick_store = lf.get_tick_store()
    tick = tick_store.get_latest(stock_token)

    if tick:
        ltp = tick.ltp
        chg = tick.change_pct
        color = "#28a745" if chg >= 0 else "#dc3545"
        sign = "+" if chg >= 0 else ""
        age = time.time() - tick.received_at
        freshness = "🟢" if age < 5 else ("🟡" if age < 30 else "🔴")
        html = (
            f'<span style="color:{color};font-weight:700;font-size:1.1rem">'
            f'₹{ltp:,.2f}</span> '
            f'<span style="color:{color};font-size:.85rem">'
            f'{sign}{chg:.2f}%</span> '
            f'<span title="{age:.1f}s ago">{freshness}</span>'
        )
    else:
        html = (
            f'<span style="color:#6c757d;font-size:1.1rem">'
            f'₹{fallback_price:,.2f}</span> '
            f'<span title="No live tick">⚫</span>'
        )

    target = col if col is not None else st
    target.markdown(html, unsafe_allow_html=True)


def auto_subscribe_option_chain(
    instrument: str,
    expiry: str,
    strikes: List[int],
    client: BreezeAPIClient,
) -> Dict[str, str]:
    """Subscribe WebSocket feeds for all visible strikes in the option chain."""
    mgr = lf.get_live_feed_manager()
    if mgr is None or not mgr.is_connected():
        return {}

    resolver = lf.get_token_resolver(client.breeze)
    cfg = C.INSTRUMENTS.get(instrument)
    if not cfg:
        return {}

    instruments_to_resolve = []
    for strike in strikes:
        for right in ["call", "put"]:
            instruments_to_resolve.append({
                "exchange": cfg.exchange,
                "stock_code": cfg.api_code,
                "product_type": "options",
                "expiry": expiry,
                "strike": float(strike),
                "right": right,
            })

    token_map = resolver.resolve_batch(instruments_to_resolve, max_workers=8)
    for token in token_map.values():
        if token:
            mgr.subscribe_quote(token, get_market_depth=False)
    st.session_state[f"oc_tokens_{cfg.api_code}_{expiry}"] = token_map
    return token_map


def cleanup_option_chain_ws_subscriptions() -> None:
    mgr = lf.get_live_feed_manager()
    tick_store = lf.get_tick_store()
    ws_keys = [k for k in st.session_state.keys() if str(k).startswith("oc_ws_tokens_")]
    for key in ws_keys:
        tokens = st.session_state.get(key, []) or []
        if mgr:
            for tok in tokens:
                mgr.unsubscribe_quote(tok)
        lf.unregister_option_chain_tracking(tokens)
        tick_store.clear_tokens(tokens)
        st.session_state.pop(key, None)


def get_client():
    c = SessionState.get_client()
    if not c or not c.is_connected():
        st.error("❌ Not connected to Breeze API")
        return None

    # Session health guard — check every 5 minutes (Task 1.2)
    import time as _time
    from session_manager import check_session_health, _SESSION_HEALTH_CHECK_INTERVAL
    last_check = st.session_state.get("_session_health_ts", 0)
    if (_time.time() - last_check) >= _SESSION_HEALTH_CHECK_INTERVAL:
        st.session_state["_session_health_ts"] = _time.time()
        if not check_session_health(c):
            SessionState.set_authentication(False, None)
            SessionState.navigate_to("⚙️ Settings")
            st.error("🔴 Session expired or revoked. Please re-login from Settings.")
            return None
    return c


def get_cached_funds(client):
    cached = CacheManager.get("funds", "funds")
    if cached:
        return cached
    resp = client.get_funds()
    if resp["success"]:
        funds = parse_funds(resp)
        CacheManager.set("funds", funds, "funds", C.FUNDS_CACHE_TTL_SECONDS)
        return funds
    return None


def get_cached_positions(client):
    cached = CacheManager.get("positions", "positions")
    if cached is not None:
        return cached
    resp = client.get_positions()
    if resp["success"]:
        items = APIResponse(resp).items
        CacheManager.set("positions", items, "positions", C.POSITION_CACHE_TTL_SECONDS)
        return items
    return None


def get_dashboard_metrics(client, cache=CacheManager) -> Dict[str, Dict[str, str]]:
    """
    Build top dashboard metrics with cache-aware data collection.

    PCR / Max Pain are computed from cached NIFTY option chain only.
    This intentionally avoids extra option-chain API calls during dashboard refreshes.
    """
    metrics: Dict[str, Dict[str, str]] = {}

    def _metric(label: str, value: str, delta: Optional[str] = None) -> None:
        metrics[label] = {"value": value, "delta": delta or ""}

    def _spot_for(symbol_key: str) -> float:
        cfg = C.get_instrument(symbol_key)
        cache_key = f"spot_{cfg.api_code}"
        cached = cache.get(cache_key, "spot")
        if cached:
            return safe_float(cached, 0.0)
        resp = client.get_spot_price(cfg.api_code, cfg.exchange)
        if resp.get("success"):
            items = APIResponse(resp).items
            if items:
                ltp = safe_float(items[0].get("ltp", 0))
                if ltp > 0:
                    cache.set(cache_key, ltp, "spot", C.SPOT_CACHE_TTL_SECONDS)
                    return ltp
        return 0.0

    nifty_spot = _spot_for("NIFTY")
    banknifty_spot = _spot_for("BANKNIFTY")
    _metric("NIFTY SPOT", f"{nifty_spot:,.2f}" if nifty_spot > 0 else "—")
    _metric("BANKNIFTY SPOT", f"{banknifty_spot:,.2f}" if banknifty_spot > 0 else "—")

    vix_val = 0.0
    cached_vix = cache.get("india_vix", "dashboard")
    if cached_vix:
        vix_val = safe_float(cached_vix, 0.0)
    else:
        try:
            vix_resp = client.get_india_vix()
            if vix_resp.get("success"):
                vix_val = safe_float((vix_resp.get("data") or {}).get("vix", 0), 0.0)
                if vix_val > 0:
                    cache.set("india_vix", vix_val, "dashboard", 60)
        except Exception as exc:
            log.debug(f"India VIX fetch failed: {exc}")
    _metric("VIX", f"{vix_val:.2f}" if vix_val > 0 else "—")

    nifty_cfg = C.get_instrument("NIFTY")
    pcr_value = 0.0
    max_pain_value = 0.0
    try:
        expiries = C.get_next_expiries("NIFTY", 1)
        if expiries:
            chain_key = f"oc_{nifty_cfg.api_code}_{expiries[0]}"
            chain_df = cache.get(chain_key, "option_chain")
            if chain_df is not None and not chain_df.empty:
                pcr_value = calculate_pcr(chain_df)
                max_pain_value = calculate_max_pain(chain_df)
    except Exception as exc:
        log.debug(f"Dashboard PCR/MaxPain computation failed: {exc}")
    _metric("NIFTY PCR", f"{pcr_value:.2f}" if pcr_value > 0 else "—")
    _metric("NIFTY MAX PAIN", f"{max_pain_value:,.0f}" if max_pain_value > 0 else "—")

    _metric("MARKET STATUS", get_market_status())
    _metric("SESSION TIME", SessionState.get_login_duration() or "0h 0m")

    prev = st.session_state.get("_dashboard_metrics_prev", {})
    for key, item in metrics.items():
        old_val = prev.get(key, "")
        new_val = item["value"]
        if old_val and old_val != "—" and new_val != "—":
            item["delta"] = f"{old_val} → {new_val}"
    st.session_state["_dashboard_metrics_prev"] = {k: v["value"] for k, v in metrics.items()}
    return metrics


def get_market_regime_snapshot(vix: float, pcr: float, spot: float) -> Dict[str, str]:
    """Compute and cache a lightweight market regime snapshot for UI badges."""
    if spot <= 0:
        return {"regime": "RANGE_BOUND", "confidence": 0.5, "risk_level": "MEDIUM"}
    closes = np.linspace(spot * 0.98, spot * 1.02, 220)
    hist_df = pd.DataFrame({"close": closes})
    regime = detect_market_regime(hist_df, vix=vix, pcr=pcr if pcr > 0 else 1.0, spot=spot)
    st.session_state["market_regime_snapshot"] = regime
    return regime


def build_iv_surface_data(client, instrument: str, expiries: List[str], spot: float) -> Dict[str, Any]:
    """Build strike-expiry IV grid with 5-minute cache."""
    cache_key = f"iv_surface_{instrument}_{int(spot)}_{','.join(expiries[:6])}"
    cached = CacheManager.get(cache_key, "analytics")
    if cached:
        return cached

    cfg = C.get_instrument(instrument)
    records: List[Dict[str, float]] = []
    for expiry in expiries[:6]:
        try:
            chain_resp = client.get_option_chain(cfg.api_code, cfg.exchange, expiry)
            if not chain_resp.get("success"):
                continue
            chain_df = process_option_chain(chain_resp.get("data", {}))
            if chain_df.empty:
                continue
            dte = max(calculate_days_to_expiry(expiry), 1)
            tte = max(dte / C.DAYS_PER_YEAR, 0.001)
            for _, row in chain_df.iterrows():
                strike = safe_float(row.get("strike_price", 0))
                ltp = safe_float(row.get("ltp", 0))
                right = C.normalize_option_type(row.get("right", ""))
                if strike <= 0 or ltp <= 0 or right not in ("CE", "PE"):
                    continue
                iv = estimate_implied_volatility(ltp, spot, strike, tte, right)
                if pd.isna(iv) or iv <= 0:
                    continue
                greeks = calculate_greeks(spot, strike, tte, iv, right)
                records.append(
                    {
                        "strike": strike,
                        "moneyness": strike / spot if spot > 0 else 0,
                        "dte": dte,
                        "iv": iv * 100.0,
                        "delta": greeks.get("delta", 0.0),
                    }
                )
        except Exception as exc:
            log.debug(f"IV surface fetch failed for {expiry}: {exc}")
    out = {"records": records}
    CacheManager.set(cache_key, out, "analytics", ttl=300)
    return out


def render_iv_surface(df_chain_dict: Dict[str, Any], spot: float) -> None:
    """Render 3D IV surface and 2D smile slice."""
    recs = df_chain_dict.get("records", [])
    if not recs:
        st.info("Not enough option-chain data to render IV surface")
        return

    import plotly.graph_objects as go
    data_df = pd.DataFrame(recs)
    x_vals = np.array(sorted(data_df["moneyness"].dropna().unique()))
    y_vals = np.array(sorted(data_df["dte"].dropna().unique()))
    if len(x_vals) < 2 or len(y_vals) < 2:
        st.info("Need at least 2 strikes and 2 expiries for IV surface")
        return

    grid_x, grid_y = np.meshgrid(x_vals, y_vals)
    try:
        from scipy.interpolate import griddata
        grid_z = griddata(
            points=data_df[["moneyness", "dte"]].to_numpy(),
            values=data_df["iv"].to_numpy(),
            xi=(grid_x, grid_y),
            method="linear",
        )
    except Exception:
        grid_z = np.full_like(grid_x, np.nan, dtype=float)

    if np.isnan(grid_z).all():
        # fallback nearest fill
        for i, dte in enumerate(y_vals):
            row = data_df[data_df["dte"] == dte].sort_values("moneyness")
            if row.empty:
                continue
            iv_interp = np.interp(x_vals, row["moneyness"], row["iv"])
            grid_z[i, :] = iv_interp

    fig = go.Figure(
        data=[
            go.Surface(
                x=grid_x,
                y=grid_y,
                z=grid_z,
                colorscale="Viridis",
                contours={"z": {"show": True, "usecolormap": True}},
                hovertemplate="Moneyness=%{x:.3f}<br>DTE=%{y}<br>IV=%{z:.2f}%<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        title="IV Surface",
        scene=dict(
            xaxis_title="Strike / Spot",
            yaxis_title="Days To Expiry",
            zaxis_title="Implied Vol (%)",
        ),
        height=500,
    )
    st.plotly_chart(fig, width="stretch")

    selected_dte = st.selectbox("IV Smile Slice DTE", y_vals.tolist(), key="iv_surface_slice_dte")
    slice_df = data_df[data_df["dte"] == selected_dte].sort_values("strike")
    if not slice_df.empty:
        smile_fig = go.Figure()
        smile_fig.add_trace(
            go.Scatter(
                x=slice_df["strike"],
                y=slice_df["iv"],
                mode="lines+markers",
                name=f"DTE {selected_dte}",
            )
        )
        smile_fig.update_layout(
            title=f"IV Smile (DTE {selected_dte})",
            xaxis_title="Strike",
            yaxis_title="IV (%)",
            height=320,
        )
        st.plotly_chart(smile_fig, width="stretch")


def render_portfolio_greeks_heatmap(rows_df: pd.DataFrame) -> None:
    """Render position-level Greeks heatmap with portfolio totals row."""
    if rows_df.empty:
        return
    import plotly.graph_objects as go

    numeric_cols = ["Delta", "Gamma", "Theta ₹", "Vega ₹", "P&L ₹"]
    heat_df = rows_df.copy()
    for col in numeric_cols:
        heat_df[col] = pd.to_numeric(heat_df[col].astype(str).str.replace(",", "", regex=False), errors="coerce").fillna(0.0)
    heat_df["Notional"] = (heat_df["Spot ₹"].astype(str).str.replace(",", "", regex=False).astype(float) * heat_df["Qty"].astype(float))

    z_cols = ["Delta", "Gamma", "Theta ₹", "Vega ₹", "Notional", "P&L ₹"]
    matrix = heat_df[z_cols].to_numpy()
    y_labels = (
        heat_df["Position"].astype(str)
        + " "
        + heat_df["Strike"].astype(str)
        + " "
        + heat_df["Type"].astype(str)
    ).tolist()

    totals = heat_df[z_cols].sum(axis=0).to_numpy().reshape(1, -1)
    matrix_with_total = np.vstack([matrix, totals])
    y_with_total = y_labels + ["PORTFOLIO TOTAL"]

    fig = go.Figure(
        data=go.Heatmap(
            z=matrix_with_total,
            x=z_cols,
            y=y_with_total,
            colorscale="RdYlGn",
            zmid=0,
            hovertemplate="Row=%{y}<br>Metric=%{x}<br>Value=%{z:.2f}<extra></extra>",
        )
    )
    fig.update_layout(height=380, title="Portfolio Greeks Heatmap")
    st.plotly_chart(fig, width="stretch")


def build_iv_rv_spread_monitor(client, instruments: List[str]) -> pd.DataFrame:
    from historical import HistoricalDataFetcher
    fetcher = HistoricalDataFetcher(client)
    rows = []
    today = datetime.now().date()
    from_date = (today - timedelta(days=45)).isoformat()
    to_date = today.isoformat()

    for inst in instruments:
        try:
            cfg = C.get_instrument(inst)
            expiries = C.get_next_expiries(inst, 1)
            if not expiries:
                continue
            expiry = expiries[0]
            chain_resp = client.get_option_chain(cfg.api_code, cfg.exchange, expiry)
            if not chain_resp.get("success"):
                continue
            chain_df = process_option_chain(chain_resp.get("data", {}))
            if chain_df.empty:
                continue
            spot_resp = client.get_spot_price(cfg.api_code, cfg.exchange)
            spot = 0.0
            if spot_resp.get("success"):
                items = APIResponse(spot_resp).items
                if items:
                    spot = safe_float(items[0].get("ltp", 0))
            if spot <= 0:
                continue
            atm = estimate_atm_strike(chain_df, spot=spot)
            dte = max(calculate_days_to_expiry(expiry), 1)
            tte = max(dte / C.DAYS_PER_YEAR, 1 / C.DAYS_PER_YEAR)
            ce = chain_df[(chain_df["right"] == "Call") & (chain_df["strike_price"] == atm)]
            pe = chain_df[(chain_df["right"] == "Put") & (chain_df["strike_price"] == atm)]
            iv_values = []
            if not ce.empty:
                ltp = safe_float(ce.iloc[0].get("ltp", 0))
                if ltp > 0:
                    iv = estimate_implied_volatility(ltp, spot, atm, tte, "CE")
                    if not pd.isna(iv) and iv > 0:
                        iv_values.append(iv * 100)
            if not pe.empty:
                ltp = safe_float(pe.iloc[0].get("ltp", 0))
                if ltp > 0:
                    iv = estimate_implied_volatility(ltp, spot, atm, tte, "PE")
                    if not pd.isna(iv) and iv > 0:
                        iv_values.append(iv * 100)
            if not iv_values:
                continue
            atm_iv = float(np.mean(iv_values))

            hist_df = fetcher.fetch(
                stock_code=cfg.spot_code or cfg.api_code,
                exchange_code=cfg.spot_exchange or "NSE",
                product_type="cash",
                from_date=from_date,
                to_date=to_date,
                interval="1day",
            )
            if hist_df.empty or "close" not in hist_df.columns:
                continue
            rv_series = rolling_realized_vol(pd.to_numeric(hist_df["close"], errors="coerce"), window=5).dropna()
            if rv_series.empty:
                continue
            rv5 = float(rv_series.iloc[-1])
            vrp_pct = ((atm_iv - rv5) / max(rv5, 0.01)) * 100.0
            if vrp_pct > 30:
                signal = "🟢 SELL VOLATILITY"
            elif vrp_pct < -15:
                signal = "🔴 BUY VOLATILITY"
            else:
                signal = "⚪ NEUTRAL"
            rows.append(
                {
                    "Instrument": inst,
                    "ATM IV%": round(atm_iv, 2),
                    "RV-5d%": round(rv5, 2),
                    "VRP%": round(vrp_pct, 2),
                    "Signal": signal,
                }
            )
        except Exception as exc:
            log.debug(f"IV/RV monitor failed for {inst}: {exc}")
            continue
    return pd.DataFrame(rows)


def split_positions(all_pos):
    options, equities = [], []
    for p in (all_pos or []):
        qty = safe_int(p.get("quantity", 0))
        if qty == 0:
            continue
        if C.is_option_position(p):
            options.append(p)
        elif C.is_equity_position(p):
            equities.append(p)
    return options, equities


def invalidate_trading_caches():
    CacheManager.invalidate("positions", "positions")
    CacheManager.invalidate("funds", "funds")


def fetch_spot_prices(client, positions):
    stock_codes = set(p.get("stock_code", "") for p in positions if C.is_option_position(p))
    spot_prices = {}
    for code in stock_codes:
        if not code:
            continue
        ck = f"spot_{code}"
        cached = CacheManager.get(ck, "spot")
        if cached:
            spot_prices[code] = cached
            continue
        cfg = next((c for c in C.INSTRUMENTS.values() if c.api_code == code), None)
        if not cfg:
            continue
        try:
            resp = client.get_spot_price(code, cfg.exchange)
            if resp["success"]:
                items = APIResponse(resp).items
                if items:
                    ltp = safe_float(items[0].get("ltp", 0))
                    if ltp > 0:
                        spot_prices[code] = ltp
                        CacheManager.set(ck, ltp, "spot", C.SPOT_CACHE_TTL_SECONDS)
        except Exception:
            pass
    return spot_prices


def render_alert_banners():
    monitor = st.session_state.get("risk_monitor")
    if not monitor or not monitor.is_running():
        return
    alerts = monitor.get_alerts()
    for alert in alerts:
        _db.log_alert(alert.level, alert.category, alert.message, alert.position_id)
        if alert.level == "CRITICAL":
            st.error(f"🚨 **{alert.message}**")
        elif alert.level == "WARNING":
            st.warning(f"⚠️ {alert.message}")
        else:
            st.info(f"ℹ️ {alert.message}")


def export_to_csv(df: pd.DataFrame, filename: str, label: str = "📥 Export CSV"):
    """Return download button for CSV export."""
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    st.download_button(
        label=label,
        data=buf.getvalue(),
        file_name=filename,
        mime="text/csv"
    )


def export_to_excel(dfs: dict, filename: str):
    """Export multiple sheets to Excel."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        for sheet, df in dfs.items():
            if not df.empty:
                excel_safe_dataframe(df).to_excel(writer, sheet_name=sheet[:31], index=False)
    st.download_button(
        label="📥 Export Excel",
        data=buf.getvalue(),
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def excel_safe_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with timezone-aware datetimes converted to timezone-naive values for Excel."""
    safe_df = df.copy()
    for col in safe_df.columns:
        series = safe_df[col]
        if getattr(series.dtype, "tz", None) is not None:
            safe_df[col] = series.dt.tz_localize(None)
    return safe_df


# ═══════════════════════════════════════════════════════════════
# AUTO-REFRESH
# ═══════════════════════════════════════════════════════════════

def render_auto_refresh(page_key: str):
    """Show auto-refresh toggle + countdown in a small expander."""
    with st.sidebar.expander("🔄 Auto Refresh"):
        enabled = st.checkbox(
            "Enable", key=f"ar_en_{page_key}",
            value=st.session_state.get(f"ar_en_{page_key}", False)
        )
        interval = st.select_slider(
            "Interval (s)", options=[10, 15, 30, 60, 120],
            value=st.session_state.get(f"ar_iv_{page_key}", 30),
            key=f"ar_iv_{page_key}"
        )
        if enabled:
            last_refresh = st.session_state.get(f"ar_ts_{page_key}", 0)
            elapsed = time.time() - last_refresh
            remaining = max(0, interval - elapsed)
            st.caption(f"⏱️ Refresh in {remaining:.0f}s")
            if elapsed >= interval:
                st.session_state[f"ar_ts_{page_key}"] = time.time()
                st.rerun()


# ═══════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════

def render_sidebar():
    with st.sidebar:
        st.markdown("""
        <div style="text-align:center;padding:.5rem 0 1rem">
            <span style="font-size:2rem">📈</span><br>
            <span style="font-size:1.3rem;font-weight:800;color:#fff">Breeze PRO</span><br>
            <span style="font-size:.7rem;color:#aaa">v10.0 — Production Terminal</span>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("---")

        if st.session_state.get("paper_trading_enabled"):
            st.markdown("""
            <div style="background:#fd7e14;color:black;padding:.5rem;
                        border-radius:6px;text-align:center;font-weight:700">
            📄 PAPER TRADING MODE
            </div>
            """, unsafe_allow_html=True)

        has_secrets = Credentials.has_stored_credentials()
        avail = list(PAGES.keys()) if SessionState.is_authenticated() else ["🏠 Dashboard"]
        cur = SessionState.get_current_page()
        if cur not in avail:
            cur = "🏠 Dashboard"
            SessionState.navigate_to(cur)
        try:
            idx = avail.index(cur)
        except ValueError:
            idx = 0

        sel = st.radio(
            "Nav", avail, index=idx,
            format_func=lambda p: p,
            label_visibility="collapsed", key="nav"
        )
        if sel != cur:
            if cur == "⛓️ Option Chain" and sel != "⛓️ Option Chain":
                cleanup_option_chain_ws_subscriptions()
            SessionState.navigate_to(sel)
            st.rerun()

        st.markdown("---")

        if SessionState.is_authenticated():
            profile_db = AccountProfileDB(_db)
            profiles = profile_db.get_profiles()
            active_profile = profile_db.get_active_profile()
            if profiles and st.session_state.get("master_password"):
                opts = [p["profile_name"] for p in profiles]
                def _fmt_profile(name: str) -> str:
                    rec = next((p for p in profiles if p["profile_name"] == name), {})
                    last_used = rec.get("last_used") or "never"
                    return f"{name} ({last_used[:16]})"
                current_profile_name = (active_profile or {}).get("profile_name", opts[0])
                selected_profile = st.selectbox("Switch Account", opts, index=opts.index(current_profile_name) if current_profile_name in opts else 0, format_func=_fmt_profile, key="sidebar_profile_switch")
                if selected_profile != current_profile_name:
                    profile_db.set_active(selected_profile)
                    _cleanup_session()
                    st.success(f"Switched to {selected_profile}. Please login again.")
                    st.rerun()
            elif profiles:
                st.caption("Set master password in Settings to enable account switching.")

            # Status
            ms = C.get_market_status()
            mkt_class = "mkt-open" if ms["status"] == "open" else "mkt-closed"
            st.markdown(
                f'<span class="badge-connected">✅ Connected</span>&nbsp;&nbsp;'
                f'<span class="{mkt_class}">{ms["label"]}</span>',
                unsafe_allow_html=True
            )
            # Public holiday banner
            if ms.get("is_holiday"):
                st.warning(
                    "🏖️ **NSE Holiday** — Market closed today.  \n"
                    "Option expiries for this week have been moved to the "
                    "previous trading day automatically."
                )
            # Countdown
            if "countdown" in ms:
                mins = ms["countdown"] // 60
                secs = ms["countdown"] % 60
                st.caption(f"⏱ {ms['next']} in {mins}m {secs:02d}s")

            client = get_client()
            if client:
                try:
                    render_live_feed_status(client)
                except Exception as _lf_err:
                    log.warning("render_live_feed_status failed: %s", _lf_err)
                    st.sidebar.caption("📡 WS: status unavailable")

            name = st.session_state.get("user_name", "Trader")
            dur = SessionState.get_login_duration()
            st.markdown(f"**👤 {name}**" + (f"  ·  ⏱ {dur}" if dur else ""))

            if SessionState.is_session_expired():
                st.error("🔴 Session expired!")
            elif SessionState.is_session_stale():
                st.warning("⚠️ Session aging — consider reconnecting")

            # Funds summary
            if client:
                funds = get_cached_funds(client)
                if funds:
                    util = (funds["allocated_fno"] / funds["total_balance"] * 100
                            if funds["total_balance"] > 0 else 0)
                    c1, c2 = st.columns(2)
                    c1.metric("Free", format_currency(funds["unallocated"]))
                    c2.metric("Util", f"{util:.0f}%",
                              delta="⚠️" if util > 75 else None,
                              delta_color="inverse")

            # Monitor status
            monitor = st.session_state.get("risk_monitor")
            if monitor:
                status = "🟢 Monitor ON" if monitor.is_running() else "🔴 Monitor OFF"
                st.caption(status)

            st.markdown("---")
            if st.button("🔓 Disconnect", width="stretch"):
                _cleanup_session()
                st.rerun()

        else:
            _render_login_form(has_secrets)

        st.markdown("---")
        with st.expander("⚙️ Quick Settings"):
            st.selectbox("Default Instrument", list(C.INSTRUMENTS.keys()),
                         key="selected_instrument")
            st.session_state.debug_mode = st.checkbox(
                "Debug Mode", value=st.session_state.get("debug_mode", False))
            if has_secrets:
                k, _, _ = Credentials.get_all_credentials()
                if k:
                    st.caption(f"API: {k[:4]}...{k[-4:]}")



def _render_login_form(has_secrets: bool):
    profile_db = AccountProfileDB(_db)
    active_profile = profile_db.get_active_profile()
    decrypted_active = None
    if active_profile and st.session_state.get("master_password"):
        try:
            mgr = MultiAccountManager(st.session_state.get("master_password"))
            for p in mgr.list_profiles():
                if p.display_name == active_profile.get("profile_name"):
                    decrypted_active = p
                    break
        except Exception:
            decrypted_active = None
    if active_profile:
        st.caption(f"Active Profile: {active_profile.get('profile_name')}")

    if has_secrets:
        st.markdown("### 🔑 Daily Login")
        st.success("✅ API Keys loaded from secrets")
        with st.form("quick_login"):
            tok = st.text_input("Session Token", type="password",
                                placeholder="8-digit token from ICICI")
            if st.form_submit_button("🔑 Connect", type="primary", width="stretch"):
                if tok and len(tok.strip()) >= 4:
                    k, s, _ = Credentials.get_all_credentials()
                    do_login(k, s, tok.strip(), st.session_state.get("totp_secret", ""))
                else:
                    st.warning("Enter a valid session token")
    else:
        st.markdown("### 🔐 Login")
        st.warning("No secrets found. Enter credentials.")
        with st.form("full_login"):
            k, s, _ = Credentials.get_all_credentials()
            if active_profile and not k:
                if decrypted_active:
                    k = decrypted_active.api_key
                    s = decrypted_active.api_secret or s
                    st.session_state["totp_secret"] = decrypted_active.totp_secret or st.session_state.get("totp_secret", "")
                else:
                    st.warning("Active profile is encrypted. Enter master password in Settings to decrypt.")
            nk = st.text_input("API Key", value=k, type="password")
            ns = st.text_input("API Secret", value=s, type="password")
            tok = st.text_input("Session Token (optional if TOTP secret set)", type="password")
            if st.form_submit_button("🔑 Connect", type="primary", width="stretch"):
                if nk and ns and (tok or st.session_state.get("totp_secret")):
                    do_login(nk.strip(), ns.strip(), tok.strip(), st.session_state.get("totp_secret", ""))
                else:
                    st.warning("Provide API credentials and token or TOTP secret")


def _cleanup_session():
    cleanup_option_chain_ws_subscriptions()
    mgr = lf.get_live_feed_manager()
    if mgr is not None:
        mgr.disconnect()
    monitor = st.session_state.get("risk_monitor")
    if monitor:
        monitor.stop()
    SessionState.set_authentication(False, None)
    Credentials.clear_runtime_credentials()
    CacheManager.clear_all()
    SessionState.navigate_to("🏠 Dashboard")
    _db.log_activity("LOGOUT", "Session ended")


def do_login(api_key, api_secret, token, totp_secret=""):
    if not api_key or not api_secret:
        st.error("❌ Missing API credentials")
        return
    with st.spinner("Connecting to Breeze API… (up to 20 s)"):
        try:
            client = BreezeAPIClient(api_key, api_secret)
            resp = auto_connect_with_totp(client, api_key, token, totp_secret=totp_secret)
            if resp["success"]:
                Credentials.save_runtime_credentials(api_key, api_secret, token)
                SessionState.set_authentication(True, client)
                if "paper_engine" not in st.session_state:
                    st.session_state.paper_engine = PaperTradingEngine(client)
                st.session_state.user_name = "Trader"
                SessionState.log_activity("Login", "Connected successfully")
                _db.log_activity("LOGIN", "Session started")

                # Start risk monitor
                settings = _db.get_all_settings()
                max_loss = settings.get("max_portfolio_loss", C.DEFAULT_MAX_PORTFOLIO_LOSS)
                monitor = RiskMonitor(api_client=client, poll_interval=15.0, max_portfolio_loss=max_loss)
                monitor.start()
                st.session_state.risk_monitor = monitor

                Notifications.success("Connected!")
                time.sleep(0.4)
                st.rerun()
            else:
                msg = resp.get("message", "Unknown error")
                st.error(f"❌ Connection failed: {msg}")
                if any(k in msg.lower() for k in ("session", "token", "unauthorized", "invalid")):
                    st.info("💡 Session tokens expire daily. Generate a fresh token from ICICI Breeze → API Login.")
                elif any(k in msg.lower() for k in ("timeout", "timed out")):
                    st.warning("⏱️ Connection timed out — ICICI servers may be slow or unreachable. Try again in a moment.")
        except TimeoutError as e:
            st.error(f"⏱️ {e}")
            st.info("💡 This usually means your session token is invalid/expired or ICICI servers are unreachable. "
                    "Get a fresh token from the ICICI Breeze app and try again.")
        except Exception as e:
            st.error(f"❌ Error: {e}")
            if st.session_state.get("debug_mode"):
                st.exception(e)


# ═══════════════════════════════════════════════════════════════
# PAGE: DASHBOARD
# ═══════════════════════════════════════════════════════════════

@error_handler
def page_dashboard():
    page_header("🏠 Dashboard")

    if not SessionState.is_authenticated():
        # Welcome screen
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("""
            <div class="metric-card">
            <h3>📊 Market Data</h3>
            <ul>
            <li>Live option chains</li>
            <li>Greeks & IV smile</li>
            <li>PCR, Max Pain, OI charts</li>
            <li>IV term structure</li>
            </ul>
            </div>""", unsafe_allow_html=True)
        with c2:
            st.markdown("""
            <div class="metric-card">
            <h3>💰 Trading</h3>
            <ul>
            <li>Sell/Buy options</li>
            <li>15+ strategy templates</li>
            <li>Payoff diagrams</li>
            <li>Bulk square-off</li>
            </ul>
            </div>""", unsafe_allow_html=True)
        with c3:
            st.markdown("""
            <div class="metric-card">
            <h3>🛡️ Risk Management</h3>
            <ul>
            <li>Fixed & trailing stops</li>
            <li>Portfolio-level limits</li>
            <li>Stress testing</li>
            <li>Real-time alerts</li>
            </ul>
            </div>""", unsafe_allow_html=True)

        st.markdown("---")
        section("📋 Supported Instruments")
        rows = [{"Name": n, "Exchange": c.exchange, "Lot": c.lot_size,
                 "Strike Gap": c.strike_gap, "Expiry": c.expiry_day,
                 "Description": c.description}
                for n, c in C.INSTRUMENTS.items()]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        info_box("👈 <b>Login from the sidebar</b> to start trading.")
        return

    client = get_client()
    if not client:
        return

    render_auto_refresh("dashboard")

    st.markdown(
        """
        <style>
        .dashboard-metric-wrap div[data-testid="stMetric"] {
            background: linear-gradient(135deg, rgba(17, 138, 178, 0.10), rgba(0, 60, 100, 0.06));
            border: 1px solid rgba(17, 138, 178, 0.30);
            border-radius: 10px;
            padding: 8px 10px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    dashboard_metrics = get_dashboard_metrics(client)
    metric_labels = [
        "NIFTY SPOT",
        "BANKNIFTY SPOT",
        "VIX",
        "NIFTY PCR",
        "NIFTY MAX PAIN",
        "MARKET STATUS",
        "SESSION TIME",
    ]
    metric_cols = st.columns(7)
    for col, label in zip(metric_cols, metric_labels):
        value = dashboard_metrics.get(label, {}).get("value", "—")
        delta = dashboard_metrics.get(label, {}).get("delta", "")
        with col:
            st.markdown('<div class="dashboard-metric-wrap">', unsafe_allow_html=True)
            st.metric(label, value, delta if delta else None)
            st.markdown("</div>", unsafe_allow_html=True)
    try:
        regime_info = get_market_regime_snapshot(
            vix=safe_float(dashboard_metrics.get("VIX", {}).get("value", 0), 0.0),
            pcr=safe_float(dashboard_metrics.get("NIFTY PCR", {}).get("value", 0), 0.0),
            spot=safe_float(dashboard_metrics.get("NIFTY SPOT", {}).get("value", 0), 0.0),
        )
        st.info(
            f"🧭 Market Regime: **{regime_info.get('regime', 'RANGE_BOUND')}** | "
            f"Confidence: **{safe_float(regime_info.get('confidence', 0), 0.0):.2f}** | "
            f"Risk: **{regime_info.get('risk_level', 'MEDIUM')}**"
        )
    except Exception as exc:
        log.debug(f"Regime badge render failed: {exc}")

    with st.expander("🏦 Market Circuit Breakers"):
        def _cb_line(label: str, spot_val: float) -> Dict[str, str]:
            if spot_val <= 0:
                return {"name": label, "status": "N/A", "distance": "—", "limit": "±10%"}
            upper = spot_val * 1.10
            lower = spot_val * 0.90
            dist = min(upper - spot_val, spot_val - lower)
            pct = (dist / spot_val) * 100 if spot_val > 0 else 0
            status = "⚠️ CAUTION" if pct < 15 else "● NORMAL"
            return {
                "name": label,
                "status": status,
                "distance": f"{dist:,.0f} ({pct:.1f}%)",
                "limit": f"±10% ({lower:,.0f} - {upper:,.0f})",
            }

        cb_rows = [
            _cb_line("NIFTY", safe_float(dashboard_metrics.get("NIFTY SPOT", {}).get("value", 0), 0.0)),
            _cb_line("BANKNIFTY", safe_float(dashboard_metrics.get("BANKNIFTY SPOT", {}).get("value", 0), 0.0)),
        ]
        st.dataframe(pd.DataFrame(cb_rows), hide_index=True, width="stretch")
        st.caption("Market-wide circuit breakers: 10% / 15% / 20%")

    st.markdown("---")

    # ── Account Overview ──────────────────────────────────────
    section("💰 Account Overview")
    funds = get_cached_funds(client)
    all_pos = get_cached_positions(client)

    if funds:
        util = (funds["allocated_fno"] / funds["total_balance"] * 100
                if funds["total_balance"] > 0 else 0)
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total Balance", format_currency(funds["total_balance"]))
        c2.metric("F&O Allocated", format_currency(funds["allocated_fno"]))
        c3.metric("Available", format_currency(funds["unallocated"]))
        c4.metric("Margin Used", f"{util:.1f}%",
                  delta="⚠️ High" if util > 75 else None, delta_color="inverse")
        # Live P&L from positions
        if all_pos is not None:
            opt_pos, _ = split_positions(all_pos)
            ep = enrich_positions(opt_pos)
            total_pnl = sum(e["_pnl"] for e in ep)
            c5.metric("Options P&L", format_currency(total_pnl),
                      delta=f"{'▲' if total_pnl >= 0 else '▼'}")

    st.markdown("---")

    # ── Positions ─────────────────────────────────────────────
    if all_pos is None:
        st.error("❌ Could not load positions")
        return
    opt_pos, eq_pos = split_positions(all_pos)

    tab1, tab2 = st.tabs([f"📍 Options ({len(opt_pos)})", f"📦 Equity ({len(eq_pos)})"])

    with tab1:
        if not opt_pos:
            empty_state("📭", "No option positions", "Use Sell Options to open positions")
            if st.button("💰 Go to Sell Options"):
                SessionState.navigate_to("💸 Sell Options")
                st.rerun()
        else:
            ep = enrich_positions(opt_pos)
            total_pnl = sum(e["_pnl"] for e in ep)
            rows = []
            for e in ep:
                rows.append({
                    "Instrument": C.api_code_to_display(e.get("stock_code", "")),
                    "Strike": e.get("strike_price"),
                    "Type": C.normalize_option_type(e.get("right", "")),
                    "Position": e["_pt"].upper(),
                    "Qty": e["_qty"],
                    "Avg ₹": f"{e['_avg']:.2f}",
                    "LTP ₹": f"{e['_ltp']:.2f}",
                    "P&L ₹": f"{e['_pnl']:+,.2f}",
                    "P&L%": f"{e['_pnl_pct']:+.1f}%",
                    "Expiry": format_expiry_short(e.get("expiry_date", ""))
                })
            c1, c2 = st.columns([4, 1])
            with c1:
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            with c2:
                pnl_metric("Total Options P&L", total_pnl)
                monitor = st.session_state.get("risk_monitor")
                if monitor:
                    port_stats = monitor.get_stats()
                    st.metric("Monitor", "🟢 ON" if port_stats["running"] else "🔴 OFF")

    with tab2:
        if not eq_pos:
            empty_state("📦", "No equity positions")
        else:
            eq_rows = [{"Stock": p.get("stock_code"), "Qty": safe_int(p.get("quantity")),
                        "Avg ₹": f"{safe_float(p.get('average_price')):.2f}",
                        "LTP ₹": f"{safe_float(p.get('ltp')):.2f}",
                        "P&L ₹": f"{safe_float(p.get('pnl')):+,.2f}",
                        "Type": p.get("product_type")} for p in eq_pos]
            total_eq = sum(safe_float(p.get("pnl", 0)) for p in eq_pos)
            st.metric("Equity P&L", format_currency(total_eq))
            st.dataframe(pd.DataFrame(eq_rows), hide_index=True, width="stretch")

    # ── Quick Actions ─────────────────────────────────────────
    st.markdown("---")
    section("⚡ Quick Actions")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    actions = [("📊 Chain", "⛓️ Option Chain"), ("💰 Sell", "💸 Sell Options"),
               ("🔄 Square Off", "❌ Square Off"), ("🎯 Strategies", "🧠 Strategy Builder"),
               ("🛡️ Risk", "🚨 Risk Monitor"), ("👁️ Watchlist", "👁️ Watchlist")]
    for col, (label, page) in zip([c1, c2, c3, c4, c5, c6], actions):
        with col:
            if st.button(label, width="stretch"):
                SessionState.navigate_to(page)
                st.rerun()

    # ── Session Stats ─────────────────────────────────────────
    summary = _db.get_trade_summary()
    pnl_hist = _db.get_pnl_history(30)
    if pnl_hist:
        st.markdown("---")
        section("📊 P&L History (30 Days)")
        hist_df = pd.DataFrame(pnl_hist).sort_values("date")
        if "realized_pnl" in hist_df.columns and not hist_df.empty:
            hist_df["Cumulative P&L"] = hist_df["realized_pnl"].cumsum()
            st.line_chart(hist_df.set_index("date")[["Cumulative P&L"]])

    if summary and summary.get("total", 0) > 0:
        section("📈 All-Time Stats")
        sc1, sc2, sc3, sc4 = st.columns(4)
        sc1.metric("Total Trades", summary.get("total", 0))
        sc2.metric("Premium Sold", format_currency(summary.get("sold", 0)))
        sc3.metric("Premium Bought", format_currency(summary.get("bought", 0)))
        net = (summary.get("sold") or 0) - (summary.get("bought") or 0)
        sc4.metric("Net Premium", format_currency(net),
                   delta=f"{'▲' if net >= 0 else '▼'}")


# ═══════════════════════════════════════════════════════════════
# PAGE: OPTION CHAIN
# ═══════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_option_chain():
    page_header("📊 Option Chain")
    client = get_client()
    if not client:
        return

    render_auto_refresh("option_chain")
    state = ensure_option_chain_state(st.session_state)
    controls = render_option_chain_controls(state, format_expiry, format_expiry_short)
    if controls is None:
        return
    inst = controls.inst
    cfg = controls.cfg
    expiry = controls.expiry
    compare_expiries = controls.compare_expiries

    state = update_option_chain_state(
        st.session_state,
        compare_expiries=compare_expiries,
        selected_chart=controls.chart_tab,
        normalization_mode=controls.normalization_mode,
        show_only_liquid=controls.show_only_liquid,
        show_only_unusual=controls.show_only_unusual,
        change_window=controls.change_window,
        replay_mode=controls.quote_mode == "⏪ Replay",
        sticky_atm=controls.sticky_atm,
    )

    if controls.refresh:
        invalidate_option_chain_cache(CacheManager, cfg.api_code, expiry, compare_expiries)
        st.rerun()

    try:
        base_df = load_cached_option_chain(CacheManager, client, _db, inst, cfg, expiry, st.spinner)
    except Exception as exc:
        st.error(f"❌ Option-chain fetch failed: {exc}")
        return
    if base_df is None or base_df.empty:
        st.warning("⚠️ No option chain data returned from Breeze.")
        return
    SessionState.log_activity("Chain", f"{inst} {format_expiry_short(expiry)}")

    compare_frames = load_compare_option_frames(
        lambda expiry_value: base_df if expiry_value == expiry else load_cached_option_chain(CacheManager, client, _db, inst, cfg, expiry_value, st.spinner),
        expiry,
        compare_expiries,
    )
    _spot = load_option_chain_spot(CacheManager, client, cfg, st.session_state)
    replay_timestamps, replay_ts, replay_df = resolve_replay_chain_selection(
        _db,
        st.session_state,
        inst,
        expiry,
        controls.quote_mode,
        update_option_chain_state,
        st.caption,
        st.info,
    )
    if not replay_df.empty:
        base_df = replay_df
        compare_frames[expiry] = base_df

    dte = calculate_days_to_expiry(expiry)
    provisional_atm = estimate_atm_strike(base_df, spot=_spot)
    ddf = filter_option_chain(base_df, atm=provisional_atm, strikes_per_side=controls.n_strikes, show_all=controls.show_all)
    all_strikes = sorted(ddf["strike_price"].dropna().astype(int).unique().tolist()) if "strike_price" in ddf.columns else []
    monitor_strikes = sync_option_chain_watchlist(_db, st.session_state, state, inst, expiry, all_strikes)
    state = update_option_chain_state(st.session_state, monitored_strikes=monitor_strikes)

    visible_strikes = []
    if "strike_price" in ddf.columns:
        visible_strikes = sorted({int(x) for x in ddf["strike_price"].dropna().tolist()})
    token_map = sync_option_chain_live_feed(lf, auto_subscribe_option_chain, st.session_state, inst, expiry, cfg.api_code, visible_strikes, client) if visible_strikes else {}
    try:
        ddf = apply_option_chain_live_overlay(controls.quote_mode, ddf, token_map, inst, expiry)
    except Exception as exc:
        log.debug(f"Live WS quote overlay failed: {exc}")

    baseline_map = _db.get_volume_baseline_map(inst, lookback_days=5) if controls.chain_opt_volume_spike else {}
    selected_strike = resolve_selected_strike(state.get("selected_strike"), all_strikes, provisional_atm)
    workspace = compose_option_chain_workspace(
        _db,
        instrument=inst,
        expiry=expiry,
        days_to_expiry=dte,
        base_df=base_df,
        display_df=ddf,
        compare_frames=compare_frames,
        replay_timestamps=replay_timestamps,
        replay_ts=replay_ts or "",
        change_window=controls.change_window,
        spot=_spot,
        baseline_map=baseline_map,
        history_provider=_db.get_iv_history,
        monitored_strikes=monitor_strikes,
        selected_strike=selected_strike,
        sticky_atm=controls.sticky_atm,
        show_only_liquid=controls.show_only_liquid,
        show_only_unusual=controls.show_only_unusual,
        include_greeks=controls.show_greeks,
        include_oi_change_pct=controls.chain_opt_oi_heatmap,
        include_iv_percentile=controls.chain_opt_iv_percentile,
        include_max_pain_marker=controls.chain_opt_max_pain_marker,
        dte_provider=calculate_days_to_expiry,
    )
    view_model = build_option_chain_page_view_model(
        controls,
        workspace,
        compare_frames,
        base_df,
        selected_strike,
        _spot,
        format_expiry_short(expiry),
        dte,
    )
    atm = view_model.metrics.atm
    state = update_option_chain_state(st.session_state, selected_strike=view_model.display.selected_strike)
    render_option_chain_summary(
        view_model.metrics.summary_payload,
        controls.chain_opt_pcr_gauge,
        format_number,
        format_expiry_short,
        warn_box,
    )

    st.markdown("---")

    display_col, analysis_col = st.columns([3, 2])
    with display_col:
        section("⛓️ Chain Ladder")
        selected_strike = render_option_chain_display(
            controls.view,
            view_model.display.display_df,
            view_model.display.ladder,
            view_model.display.selected_strike,
            view_model.display.pinned_strikes,
            view_model.metrics.atm,
            view_model.metrics.max_pain,
            all_strikes,
        )
        state = update_option_chain_state(st.session_state, selected_strike=selected_strike)

    with analysis_col:
        render_option_chain_analysis(
            view_model.analysis_payload["panel_payload"],
            view_model.analysis_payload["change_df"],
            view_model.analysis_payload["top_movers"],
            view_model.analysis_payload["session_iv_extremes"],
            view_model.analysis_payload["change_window"],
            section,
        )

    st.markdown("---")
    section(f"📈 {controls.chart_tab}")

    fig = build_option_chain_chart(**view_model.chart_payload)
    selected_strike = render_option_chain_chart(fig, controls.chart_tab, selected_strike, all_strikes, atm)
    state = update_option_chain_state(st.session_state, selected_strike=selected_strike)

    if view_model.compare_caption:
        st.caption(view_model.compare_caption)

    # ── Export ────────────────────────────────────────────────
    if view_model.display.export_payload["enabled"]:
        export_to_csv(
            view_model.display.display_df,
            view_model.display.export_payload["filename"],
            label="📥 Export Chain CSV",
        )


# ═══════════════════════════════════════════════════════════════
# PAGE: SELL OPTIONS
# ═══════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_sell_options():
    page_header("💰 Sell Options")
    client = get_client()
    if not client:
        return

    c1, c2 = st.columns([1, 1])

    with c1:
        section("📝 Order Details")
        inst = st.selectbox("Instrument", list(C.INSTRUMENTS.keys()), key="s_i")
        cfg = C.get_instrument(inst)
        expiries = C.get_next_expiries(inst, 6)
        if not expiries:
            st.error("No expiries")
            return
        expiry = st.selectbox("Expiry", expiries, format_func=format_expiry, key="s_e")
        dte = calculate_days_to_expiry(expiry)
        if dte <= 0:
            warn_box("⚠️ Expiry day! Consider next week's expiry.")
        # Holiday advisory
        _s_natural = C.get_natural_expiry_for(inst, expiry)
        if _s_natural and _s_natural != expiry:
            st.info(
                f"📅 **Holiday-adjusted expiry** — natural {inst} expiry "
                f"({format_expiry_short(_s_natural)}) is a market holiday. "
                f"NSE moved it to **{format_expiry_short(expiry)}**."
            )

        ot = st.radio("Option Type", ["CE (Call)", "PE (Put)"], horizontal=True, key="s_t")
        oc = "CE" if "CE" in ot else "PE"

        # Compute a reasonable default ATM
        ck = f"oc_{cfg.api_code}_{expiry}"
        df = CacheManager.get(ck, "option_chain")
        default_atm = estimate_atm_strike(df) if df is not None and not df.empty else 0
        if default_atm == 0:
            default_atm = int((cfg.min_strike + cfg.max_strike) / 2)
            default_atm = round(default_atm / cfg.strike_gap) * cfg.strike_gap

        strike = st.number_input(
            "Strike Price", min_value=cfg.min_strike, max_value=cfg.max_strike,
            value=int(default_atm), step=cfg.strike_gap, key="s_s"
        )
        valid = C.validate_strike(inst, strike)
        if not valid:
            st.warning(f"Strike must be a multiple of {cfg.strike_gap}")

        lots = st.number_input("Lots", min_value=1, max_value=C.MAX_LOTS_PER_ORDER,
                               value=1, key="s_l")
        qty = lots * cfg.lot_size
        st.info(f"**Quantity:** {qty:,} ({lots} lot{'s' if lots > 1 else ''} × {cfg.lot_size})")

        otp = st.radio("Order Type", ["Market", "Limit"], horizontal=True, key="s_o")
        lp = 0.0
        if otp == "Limit":
            lp = st.number_input("Limit Price ₹", min_value=0.01, step=0.05, key="s_p")

        # Stop loss config
        with st.expander("🛡️ Auto Stop-Loss (Optional)"):
            set_sl = st.checkbox("Set stop-loss after order", key="s_sl_en")
            if set_sl:
                sl_mult = st.slider("Stop at premium × multiplier", 1.5, 5.0, 2.0, 0.5)
                st.caption(f"Stop triggers if premium rises to {sl_mult}× your sell price")

    with c2:
        section("📊 Market Info")
        quote_ltp = 0.0
        if st.button("📊 Get Quote", disabled=not valid, width="stretch"):
            with st.spinner("Fetching quote..."):
                r = client.get_option_quote(cfg.api_code, cfg.exchange, expiry, int(strike), oc)
                if r["success"]:
                    items = APIResponse(r).items
                    if items:
                        quote_ltp = safe_float(items[0].get("ltp", 0))
                        st.session_state["s_quote_ltp"] = quote_ltp
                        st.success(f"**LTP: ₹{quote_ltp:.2f}**")
                        st.metric("Premium Receivable", format_currency(quote_ltp * qty))
                        st.metric("DTE", f"{dte} days")
                    else:
                        st.warning("No quote data available")
                else:
                    st.error(f"❌ {r.get('message')}")

        if st.button("💰 Check Margin", disabled=not valid, width="stretch"):
            with st.spinner("Calculating margin..."):
                r = client.get_margin(cfg.api_code, cfg.exchange, expiry,
                                      int(strike), oc, "sell", qty)
                if r["success"]:
                    m = safe_float(APIResponse(r).get("required_margin", 0))
                    st.success(f"**Required Margin: {format_currency(m)}**")
                    funds = get_cached_funds(client)
                    if funds and m > 0:
                        pct = m / funds["total_balance"] * 100 if funds["total_balance"] > 0 else 0
                        st.metric("Margin % of Account", f"{pct:.1f}%",
                                  delta="⚠️ High" if pct > 30 else None, delta_color="inverse")
                else:
                    st.error(f"❌ {r.get('message')}")

        # Show theoretical Greeks
        quote_ltp = st.session_state.get("s_quote_ltp", 0)
        if quote_ltp > 0 and valid:
            tte = max(dte / C.DAYS_PER_YEAR, 0.001)
            # Approximate spot as strike (ATM assumption)
            iv = estimate_implied_volatility(quote_ltp, strike, strike, tte, oc)
            greeks = calculate_greeks(strike, strike, tte, iv, oc)
            with st.expander("📐 Theoretical Greeks"):
                gc1, gc2 = st.columns(2)
                gc1.metric("Delta", f"{-greeks['delta']:+.3f}" if oc == "CE" else f"{greeks['delta']:+.3f}")
                gc2.metric("Theta/day", f"₹{abs(greeks['theta'] * qty):.0f}")
                gc1.metric("Vega/1%", f"₹{abs(greeks['vega'] * qty):.0f}")
                gc2.metric("IV", f"{iv*100:.1f}%")

    # ── Pre-trade cost preview ───────────────────────────────
    render_order_cost_preview(
        client=client,
        stock_code=cfg.api_code,
        exchange_code=cfg.exchange,
        product="options",
        order_type=otp.lower(),
        price=lp,
        action="sell",
        quantity=qty,
        expiry_date=expiry,
        right="call" if oc == "CE" else "put",
        strike_price=str(int(strike)),
        key_prefix="sell_preview",
    )

    # ── Order placement ───────────────────────────────────────
    st.markdown("---")
    danger_box("⚠️ <b>RISK WARNING:</b> Option selling carries <b>unlimited risk</b>. "
               "Never sell without understanding your max loss. Use stop-losses.")

    ack = st.checkbox("✅ I understand and accept the risks of option selling", key="s_ack")
    order_busy = st.session_state.get("_order_busy", False)
    can_place = ack and valid and strike > 0 and (otp == "Market" or lp > 0) and not order_busy

    if order_busy:
        st.warning("⏳ Order in progress...")

    if _db.get_setting("voice_confirmations", False):
        if st.button("🔊 Read Order Back", key="sell_voice_read"):
            safe_price = lp if lp > 0 else st.session_state.get("s_quote_ltp", 0)
            components.html(
                f"""
                <script>
                  const msg = new SpeechSynthesisUtterance(
                    "Confirm order: Sell {lots} lots of {inst} {int(strike)} {oc} at {safe_price:.2f} rupees per share."
                  );
                  msg.rate = 0.9;
                  msg.lang = "en-IN";
                  window.speechSynthesis.speak(msg);
                </script>
                """,
                height=0,
            )

    col1, col2 = st.columns([2, 1])
    with col1:
        if st.button(f"🔴 SELL {qty:,} {inst} {int(strike)} {oc}",
                     type="primary", disabled=not can_place, width="stretch"):
            st.session_state._order_busy = True
            try:
                with st.spinner("Placing order..."):
                    if oc == "CE":
                        r = client.sell_call(cfg.api_code, cfg.exchange, expiry,
                                             int(strike), qty, otp.lower(), lp)
                    else:
                        r = client.sell_put(cfg.api_code, cfg.exchange, expiry,
                                            int(strike), qty, otp.lower(), lp)

                    if r["success"]:
                        order_id = APIResponse(r).get("order_id", "N/A")
                        st.success(f"✅ Order placed! ID: {order_id}")
                        st.balloons()

                        _db.log_trade(
                            stock_code=cfg.api_code, exchange=cfg.exchange,
                            strike=int(strike), option_type=oc, expiry=expiry,
                            action="sell", quantity=qty,
                            # For market orders lp==0; log quote_ltp as best-estimate price.
                            # This makes trade history meaningful instead of all zeros.
                            price=lp if lp > 0 else st.session_state.get("s_quote_ltp", 0),
                            order_type=otp.lower(), trade_id=str(order_id),
                            notes=f"Sold {inst}"
                        )
                        _db.log_activity("SELL_ORDER", f"SELL {inst} {int(strike)} {oc} x{qty}")
                        SessionState.log_activity("Sell", f"{inst} {int(strike)} {oc}")

                        # Auto add to risk monitor
                        monitor = st.session_state.get("risk_monitor")
                        if monitor:
                            pid = f"{cfg.api_code}_{int(strike)}_{oc}"
                            monitor.add_position(
                                position_id=pid, stock_code=cfg.api_code,
                                exchange=cfg.exchange, expiry=expiry,
                                strike=int(strike), option_type=oc,
                                position_type="short", quantity=qty,
                                avg_price=lp if lp > 0 else quote_ltp
                            )
                            # Set auto stop loss if configured
                            if set_sl and (lp > 0 or quote_ltp > 0):
                                ref_price = lp if lp > 0 else quote_ltp
                                monitor.set_stop_loss(pid, ref_price * sl_mult)

                        invalidate_trading_caches()
                        time.sleep(1.5)
                    elif r.get("error_code") == "DUPLICATE_ORDER":
                        st.warning(f"⚠️ {r['message']}")
                    else:
                        st.error(f"❌ {r.get('message')}")
            finally:
                st.session_state._order_busy = False


# ═══════════════════════════════════════════════════════════════
# PAGE: SQUARE OFF
# ═══════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_square_off():
    page_header("🔄 Square Off")
    client = get_client()
    if not client:
        return

    col_r, col_bulk = st.columns([1, 1])
    with col_r:
        if st.button("🔄 Refresh Positions", width="stretch"):
            invalidate_trading_caches()
            st.rerun()
    with col_bulk:
        if st.button("⚠️ Square Off ALL", type="secondary", width="stretch",
                     help="Square off all open option positions at market price"):
            st.session_state["confirm_bulk_sqoff"] = True

    # Bulk confirm
    if st.session_state.get("confirm_bulk_sqoff"):
        st.error("🚨 **CONFIRM: Square off ALL option positions at MARKET price?**")
        # Preview positions before confirming
        _prev_pos = get_cached_positions(client)
        _prev_opt, _ = split_positions(_prev_pos or [])
        _prev_ep = enrich_positions(_prev_opt)
        if _prev_ep:
            preview_rows = []
            for _pe in _prev_ep:
                _sc = _pe.get("stock_code", "")
                _ic = next((c for c in C.INSTRUMENTS.values() if c.api_code == _sc), None)
                _ls = _ic.lot_size if _ic else 1
                _lots = _pe["_qty"] // _ls
                preview_rows.append({
                    "Instrument": C.api_code_to_display(_sc),
                    "Strike": _pe.get("strike_price"),
                    "Type": C.normalize_option_type(_pe.get("right", "")),
                    "Lots": _lots,
                    "Qty": _pe["_qty"],
                    "Lot Size": _ls,
                    "P&L ₹": f"{_pe['_pnl']:+,.2f}"
                })
            st.dataframe(pd.DataFrame(preview_rows), hide_index=True, width="stretch")
        cc1, cc2 = st.columns(2)
        if cc1.button("✅ Yes, Square Off All", type="primary"):
            all_pos = get_cached_positions(client)
            opt_pos, _ = split_positions(all_pos or [])
            ep = enrich_positions(opt_pos)
            success_count = 0
            for e in ep:
                sc = e.get("stock_code", "")
                ic = next((c for c in C.INSTRUMENTS.values() if c.api_code == sc), None)
                lot_size = ic.lot_size if ic else 1
                qty_to_close = e["_qty"]
                # Ensure qty is a valid multiple of lot size
                lots_to_close = qty_to_close // lot_size
                if lots_to_close < 1:
                    st.warning(f"⚠️ Skipping {C.api_code_to_display(sc)}: qty {qty_to_close} < 1 lot ({lot_size})")
                    continue
                # Clamp to exact multiple of lot size
                qty_to_close = lots_to_close * lot_size
                r = client.square_off_option_position(
                    e,
                    quantity=qty_to_close,
                    order_type="market",
                    limit_price=0.0,
                )
                if r["success"]:
                    success_count += 1
                    _db.log_trade(
                        stock_code=sc,
                        exchange=e.get("exchange_code", ""),
                        strike=safe_int(e.get("strike_price", 0)),
                        option_type=C.normalize_option_type(e.get("right", "")),
                        expiry=e.get("expiry_date", ""),
                        action=e["_close"], quantity=qty_to_close, price=0,
                        order_type="market",
                        notes=f"Bulk square off ({lots_to_close} lots × {lot_size})"
                    )
                else:
                    st.warning(f"⚠️ Failed: {C.api_code_to_display(sc)} {e.get('strike_price')} — {r.get('message', 'error')}")
            st.success(f"✅ Squared off {success_count}/{len(ep)} positions!")
            _db.log_activity("BULK_SQOFF", f"Squared off {success_count} positions")
            st.session_state["confirm_bulk_sqoff"] = False
            invalidate_trading_caches()
            time.sleep(1)
            st.rerun()
        if cc2.button("❌ Cancel"):
            st.session_state["confirm_bulk_sqoff"] = False
            st.rerun()

    all_pos = get_cached_positions(client)
    if all_pos is None:
        st.error("❌ Failed to load positions")
        return
    opt_pos, _ = split_positions(all_pos)

    ep = enrich_positions(opt_pos)
    if not ep:
        empty_state("📭", "No positions to square off",
                    "Open positions via Sell Options")
        return

    total_pnl = sum(e["_pnl"] for e in ep)
    st.metric("Total Options P&L", format_currency(total_pnl),
              delta=f"{'▲' if total_pnl >= 0 else '▼'}")

    # Position table
    # Build rows with lot information
    def _lot_info(e):
        sc = e.get("stock_code", "")
        ic = next((c for c in C.INSTRUMENTS.values() if c.api_code == sc), None)
        ls = ic.lot_size if ic else 1
        return ls, e["_qty"] // ls

    rows = []
    for i, e in enumerate(ep):
        ls, lots = _lot_info(e)
        rows.append({
            "#": i+1,
            "Instrument": C.api_code_to_display(e.get("stock_code", "")),
            "Strike": e.get("strike_price"),
            "Type": C.normalize_option_type(e.get("right", "")),
            "Position": e["_pt"].upper(),
            "Lots": lots,
            "Lot Size": ls,
            "Total Qty": e["_qty"],
            "Avg ₹": f"{e['_avg']:.2f}",
            "LTP ₹": f"{e['_ltp']:.2f}",
            "P&L ₹": f"{e['_pnl']:+,.2f}",
            "Action": e["_close"].upper(),
            "Expiry": format_expiry_short(e.get("expiry_date", ""))
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    st.markdown("---")
    section("🎯 Select Position to Square Off")
    labels = [
        f"{C.api_code_to_display(e.get('stock_code', ''))} "
        f"{e.get('strike_price')} {C.normalize_option_type(e.get('right', ''))} "
        f"({e['_pt'].upper()}) — Qty: {e['_qty']} — P&L: {format_currency(e['_pnl'])}"
        for e in ep
    ]
    si = st.selectbox("Position", range(len(labels)), format_func=lambda i: labels[i], key="sq_s")
    sel = ep[si]

    # ── Lot-size lookup for selected position ────────────────
    sel_stock_code = sel.get("stock_code", "")
    sel_inst_cfg = next((c for c in C.INSTRUMENTS.values() if c.api_code == sel_stock_code), None)
    sel_lot_size = sel_inst_cfg.lot_size if sel_inst_cfg else 1
    sel_max_lots = max(1, sel["_qty"] // sel_lot_size)

    info_box(
        f"ℹ️ <b>{C.api_code_to_display(sel_stock_code)}</b>: "        f"1 lot = <b>{sel_lot_size} qty</b> | "        f"Total position = <b>{sel['_qty']} qty ({sel_max_lots} lots)</b>"
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        ot = st.radio("Order Type", ["Market", "Limit"], horizontal=True, key="sq_o")
    with c2:
        sq_lots = st.number_input(
            f"Lots to Square Off",
            min_value=1,
            max_value=sel_max_lots,
            value=sel_max_lots,
            step=1,
            key="sq_lots",
            help=(
                f"Enter number of lots to close. "
                f"1 lot = {sel_lot_size} qty for {C.api_code_to_display(sel_stock_code)}. "
                f"Max = {sel_max_lots} lots."
            )
        )
        sq = sq_lots * sel_lot_size
        # Safety clamp — never exceed actual held quantity
        sq = min(sq, sel["_qty"])
        st.caption(f"📦 **{sq_lots} lot{'s' if sq_lots > 1 else ''} × {sel_lot_size} = {sq} units**")
    with c3:
        pr = 0.0
        if ot == "Limit":
            pr = st.number_input("Price ₹", value=float(sel["_ltp"]), min_value=0.01, step=0.05)

    # Validate quantity is exact multiple of lot size
    if sq % sel_lot_size != 0 or sq < sel_lot_size or sq > sel["_qty"]:
        st.error(
            f"❌ Quantity {sq} is invalid. Must be a multiple of lot size {sel_lot_size}. "
            f"Max = {sel['_qty']} ({sel_max_lots} lots)."
        )

    order_busy = st.session_state.get("_order_busy", False)
    render_order_cost_preview(
        client=client,
        stock_code=sel.get("stock_code", ""),
        exchange_code=sel.get("exchange_code", ""),
        product="options",
        order_type=ot.lower(),
        price=pr,
        action=sel["_close"],
        quantity=sq,
        expiry_date=sel.get("expiry_date", ""),
        right="call" if C.normalize_option_type(sel.get("right", "")) == "CE" else "put",
        strike_price=str(safe_int(sel.get("strike_price", 0))),
        key_prefix="sq_preview",
    )

    btn_label = (
        f"🔄 {sel['_close'].upper()} {sq_lots} lot{'s' if sq_lots > 1 else ''} "        f"({sq} qty) — {C.api_code_to_display(sel.get('stock_code', ''))} "        f"{sel.get('strike_price')} {C.normalize_option_type(sel.get('right', ''))}"
    )
    can_square = (not order_busy) and (sq % sel_lot_size == 0) and (sq <= sel["_qty"]) and (sq >= sel_lot_size)
    if st.button(btn_label, type="primary", disabled=not can_square, width="stretch"):
        st.session_state._order_busy = True
        try:
            with st.spinner("Squaring off..."):
                r = client.square_off_option_position(
                    sel,
                    quantity=sq,
                    order_type=ot.lower(),
                    limit_price=pr,
                )
                if r["success"]:
                    oid = APIResponse(r).get("order_id", "?")
                    st.success(f"✅ Squared off! Order ID: {oid}")
                    _db.log_trade(
                        stock_code=sel.get("stock_code", ""),
                        exchange=sel.get("exchange_code", ""),
                        strike=safe_int(sel.get("strike_price", 0)),
                        option_type=C.normalize_option_type(sel.get("right", "")),
                        expiry=sel.get("expiry_date", ""),
                        action=sel["_close"], quantity=sq, price=pr,
                        order_type=ot.lower(), trade_id=str(oid), notes="Square off"
                    )
                    _db.log_activity("SQUARE_OFF", f"{sel.get('stock_code')} {sel.get('strike_price')}")
                    SessionState.log_activity("SqOff", str(sel.get("strike_price")))
                    monitor = st.session_state.get("risk_monitor")
                    if monitor:
                        pid = (f"{sel.get('stock_code')}_{safe_int(sel.get('strike_price'))}_"
                               f"{C.normalize_option_type(sel.get('right', ''))}")
                        monitor.remove_position(pid)
                    invalidate_trading_caches()
                    time.sleep(1)
                    st.session_state._order_busy = False
                    st.rerun()
                elif r.get("error_code") == "DUPLICATE_ORDER":
                    st.warning(f"⚠️ {r['message']}")
                else:
                    st.error(f"❌ {r.get('message')}")
        finally:
            st.session_state._order_busy = False


# ═══════════════════════════════════════════════════════════════
# PAGE: ORDERS & TRADES
# ═══════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_orders_trades():
    page_header("📋 Orders & Trades")
    client = get_client()
    if not client:
        return

    c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
    with c1:
        exch = st.selectbox("Exchange", ["All", "NFO", "BFO"], key="o_e")
    with c2:
        fd = st.date_input("From", value=date.today() - timedelta(days=7), key="o_f")
    with c3:
        td = st.date_input("To", value=date.today(), key="o_t")
    with c4:
        st.markdown("<br>", unsafe_allow_html=True)
        refresh_ord = st.button("🔄 Fetch", width="stretch")

    try:
        validate_date_range(fd, td)
    except ValueError as e:
        st.error(str(e))
        return

    t1, t2, t3, t4, t5 = st.tabs(
        ["📋 Orders", "📊 Trades", "💾 History", "📝 Activity", "📊 Stats"])

    with t1:
        if refresh_ord:
            with st.spinner("Loading orders..."):
                r = client.get_order_list(
                    "" if exch == "All" else exch,
                    fd.strftime("%Y-%m-%d"), td.strftime("%Y-%m-%d")
                )
            if r["success"]:
                items = APIResponse(r).items
                if items:
                    df = pd.DataFrame(items)
                    st.dataframe(df, height=400, hide_index=True, width="stretch")
                    export_to_csv(df, f"orders_{fd}_{td}.csv")
                else:
                    empty_state("📭", "No orders found", f"{fd} to {td}")
            else:
                st.error(f"❌ {r.get('message')}")
        else:
            st.info("Click 🔄 Fetch to load orders")

    with t2:
        if refresh_ord:
            with st.spinner("Loading trades..."):
                r = client.get_trade_list(from_date=fd.strftime("%Y-%m-%d"),
                                          to_date=td.strftime("%Y-%m-%d"))
            if r["success"]:
                items = APIResponse(r).items
                if items:
                    df = pd.DataFrame(items)
                    st.dataframe(df, height=400, hide_index=True, width="stretch")
                    export_to_csv(df, f"trades_{fd}_{td}.csv")
                else:
                    empty_state("📭", "No trades found")
            else:
                st.error(f"❌ {r.get('message')}")
        else:
            st.info("Click 🔄 Fetch to load trades")

    with t3:
        section("💾 Persistent Trade History")
        filter_sym = st.text_input("Filter by symbol", key="o_sym")
        local_trades = _db.get_trades(limit=200, stock_code=filter_sym,
                                      date_from=fd.strftime("%Y-%m-%d"),
                                      date_to=td.strftime("%Y-%m-%d"))
        if local_trades:
            df = pd.DataFrame(local_trades)
            st.dataframe(df, height=400, hide_index=True, width="stretch")
            export_to_excel({"Trades": df}, f"trade_history_{fd}_{td}.xlsx")
        else:
            empty_state("💾", "No trades recorded", "Trades auto-save when orders are placed")

    with t4:
        db_log = _db.get_activities(limit=100)
        if db_log:
            st.dataframe(pd.DataFrame(db_log), hide_index=True, width="stretch")
            export_to_csv(pd.DataFrame(db_log), "activity_log.csv")
        else:
            empty_state("📝", "No activity yet")

    with t5:
        summary = _db.get_trade_summary()
        if summary and summary.get("total", 0) > 0:
            sc1, sc2, sc3, sc4, sc5 = st.columns(5)
            sc1.metric("Total Trades", summary.get("total", 0))
            sc2.metric("Trading Days", summary.get("trading_days", 0))
            sc3.metric("Premium Sold", format_currency(summary.get("sold") or 0))
            sc4.metric("Premium Bought", format_currency(summary.get("bought") or 0))
            net = (summary.get("sold") or 0) - (summary.get("bought") or 0)
            sc5.metric("Net Premium", format_currency(net))

            # P&L chart
            hist = _db.get_pnl_history(60)
            if hist:
                hist_df = pd.DataFrame(hist).sort_values("date")
                if "realized_pnl" in hist_df.columns:
                    hist_df["Cumulative"] = hist_df["realized_pnl"].cumsum()
                    st.line_chart(hist_df.set_index("date")[["Cumulative"]])
        else:
            empty_state("📊", "No stats yet", "Place some trades first")


# ═══════════════════════════════════════════════════════════════
# PAGE: POSITIONS
# ═══════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_positions():
    page_header("📍 Positions")
    client = get_client()
    if not client:
        return

    render_auto_refresh("positions")

    if st.button("🔄 Refresh", width="content"):
        invalidate_trading_caches()
        st.rerun()

    all_pos = get_cached_positions(client)
    if all_pos is None:
        st.error("❌ Failed to load positions")
        return
    opt_pos, eq_pos = split_positions(all_pos)

    t1, t2 = st.tabs([f"📍 Options ({len(opt_pos)})", f"📦 Equity ({len(eq_pos)})"])

    with t1:
        if not opt_pos:
            empty_state("📭", "No option positions")
        else:
            ep = enrich_positions(opt_pos)
            total_pnl = sum(e["_pnl"] for e in ep)

            # Summary metrics
            winners = [e for e in ep if e["_pnl"] > 0]
            losers = [e for e in ep if e["_pnl"] < 0]
            mc = st.columns(5)
            mc[0].metric("Total P&L", format_currency(total_pnl))
            mc[1].metric("💼 Positions", len(ep))
            mc[2].metric("Winners", len(winners))
            mc[3].metric("Losers", len(losers))
            mc[4].metric("Win Rate", f"{len(winners)/len(ep)*100:.0f}%" if ep else "N/A")

            rows = [{
                "Instrument": C.api_code_to_display(e.get("stock_code", "")),
                "Strike": e.get("strike_price"),
                "Type": C.normalize_option_type(e.get("right", "")),
                "Direction": e["_pt"].upper(),
                "Qty": e["_qty"],
                "Avg ₹": f"{e['_avg']:.2f}",
                "LTP ₹": f"{e['_ltp']:.2f}",
                "P&L ₹": f"{e['_pnl']:+,.2f}",
                "P&L%": f"{e['_pnl_pct']:+.1f}%",
                "Close": e["_close"].upper(),
                "Expiry": format_expiry_short(e.get("expiry_date", "")),
                "DTE": calculate_days_to_expiry(e.get("expiry_date", ""))
            } for e in ep]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

            export_to_csv(pd.DataFrame(rows), "positions.csv")

    with t2:
        if not eq_pos:
            empty_state("📦", "No equity positions")
        else:
            eq_rows = [{"Stock": p.get("stock_code"),
                        "Qty": safe_int(p.get("quantity")),
                        "Avg ₹": f"{safe_float(p.get('average_price')):.2f}",
                        "LTP ₹": f"{safe_float(p.get('ltp')):.2f}",
                        "P&L ₹": f"{safe_float(p.get('pnl')):+,.2f}",
                        "Type": p.get("product_type")} for p in eq_pos]
            total_eq = sum(safe_float(p.get("pnl", 0)) for p in eq_pos)
            st.metric("Equity P&L", format_currency(total_eq))
            st.dataframe(pd.DataFrame(eq_rows), hide_index=True, width="stretch")


# ═══════════════════════════════════════════════════════════════
# PAGE: STRATEGY BUILDER
# ═══════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_strategy_builder():
    page_header("🎯 Strategy Builder")
    client = get_client()
    if not client:
        return

    t_select, t_custom, t_execute = st.tabs(["📋 Select Strategy", "✏️ Custom Builder", "⚡ Execute"])

    with t_select:
        c1, c2 = st.columns([1, 2])
        with c1:
            section("Configuration")
            # Filter by category
            cat = st.selectbox("Category", ["All"] + STRATEGY_CATEGORIES, key="sb_cat")
            strats = get_strategies_by_category(cat)
            regime_snapshot = st.session_state.get("market_regime_snapshot", {})
            if regime_snapshot:
                st.caption(f"Regime: {regime_snapshot.get('regime', 'RANGE_BOUND')} ({regime_snapshot.get('confidence', 0):.2f})")
                if st.checkbox("Filter by regime suggestions", value=False, key="sb_regime_filter"):
                    suggested = set(regime_snapshot.get("recommended_strategies", []))
                    filtered = {k: v for k, v in strats.items() if k in suggested}
                    if filtered:
                        strats = filtered
            sname = st.selectbox("Strategy", list(strats.keys()), key="sb_s")
            inst = st.selectbox("Instrument", list(C.INSTRUMENTS.keys()), key="sb_i")
            cfg = C.get_instrument(inst)
            expiry = st.selectbox("Expiry", C.get_next_expiries(inst, 6),
                                  format_func=format_expiry, key="sb_e")
            multi_expiry = st.toggle("Multi-Expiry", value=False, key="sb_multi_expiry")
            far_expiry = ""
            if multi_expiry:
                _exp_list = C.get_next_expiries(inst, 6)
                _far_choices = [e for e in _exp_list if e != expiry]
                if _far_choices:
                    far_expiry = st.selectbox("Far Expiry", _far_choices, format_func=format_expiry, key="sb_far_e")

            # Try to get live ATM and available strikes from cached chain
            ck = f"oc_{cfg.api_code}_{expiry}"
            df = CacheManager.get(ck, "option_chain")
            default_atm = estimate_atm_strike(df) if df is not None and not df.empty else 0
            # Task 1.5: Extract available strikes for snap logic
            _avail_strikes = None
            if df is not None and not df.empty and "strike_price" in df.columns:
                _avail_strikes = set(int(s) for s in df["strike_price"].dropna().unique() if s > 0)
            if default_atm == 0:
                default_atm = int((cfg.min_strike + cfg.max_strike) / 2)
                default_atm = round(default_atm / cfg.strike_gap) * cfg.strike_gap

            atm = st.number_input("ATM Strike", min_value=cfg.min_strike,
                                  max_value=cfg.max_strike, value=int(default_atm),
                                  step=cfg.strike_gap, key="sb_a")
            lots = st.number_input("Lots per Leg", min_value=1, max_value=50, value=1, key="sb_l")
            templates = _db.list_basket_templates(inst)
            template_names = [t["name"] for t in templates]
            selected_template = st.selectbox("📂 Load Template", ["—"] + template_names, key="sb_template_load")
            if selected_template != "—" and st.button("Load Template", key="sb_load_template_btn"):
                tpl = next((t for t in templates if t["name"] == selected_template), None)
                if tpl:
                    loaded_legs = []
                    for l in tpl.get("legs", []):
                        offset = safe_int(l.get("offset", 0))
                        loaded_legs.append(
                            StrategyLeg(
                                strike=int(atm) + (offset * cfg.strike_gap),
                                option_type=str(l.get("type", "CE")),
                                action=str(l.get("action", "buy")),
                                quantity=lots * cfg.lot_size * max(1, safe_int(l.get("qty_multiplier", 1))),
                                label=str(l.get("label", "")),
                                expiry=expiry,
                            )
                        )
                    if loaded_legs:
                        st.session_state.strat_legs = loaded_legs
                        st.session_state.strat_cfg = cfg
                        st.session_state.strat_expiry = expiry
                        st.session_state.strat_name = tpl.get("strategy_type", "Template")
                        _db.mark_basket_template_used(selected_template)
                        st.success(f"Loaded template: {selected_template}")
                        st.rerun()

            if st.button("🔧 Build Strategy", type="primary", width="stretch"):
                try:
                    legs = generate_strategy_legs(
                        sname, int(atm), cfg.strike_gap, cfg.lot_size, lots,
                        available_strikes=_avail_strikes,
                        default_expiry=expiry,
                        expiry_by_action=(
                            {"buy": expiry, "sell": far_expiry or expiry}
                            if multi_expiry and sname in {"Calendar Spread", "Diagonal Spread"}
                            else None
                        ),
                    )
                    st.session_state.strat_legs = legs
                    st.session_state.strat_cfg = cfg
                    st.session_state.strat_expiry = expiry
                    st.session_state.strat_multi_expiry = multi_expiry
                    st.session_state.strat_name = sname
                    st.success(f"✅ Built {len(legs)} leg(s)")
                except Exception as e:
                    st.error(f"❌ {e}")
            save_tpl_name = st.text_input("💾 Save as Template", key="sb_template_name")
            if save_tpl_name and st.button("Save Template", key="sb_template_save_btn"):
                src_legs = st.session_state.get("strat_legs", [])
                if not src_legs:
                    st.warning("Build a strategy before saving as template.")
                else:
                    legs_payload = []
                    for l in src_legs:
                        legs_payload.append(
                            {
                                "offset": int(round((l.strike - int(atm)) / cfg.strike_gap)),
                                "type": l.option_type,
                                "action": l.action,
                                "qty_multiplier": max(1, int(l.quantity / max(lots * cfg.lot_size, 1))),
                                "label": l.label,
                            }
                        )
                    ok = _db.save_basket_template(save_tpl_name, inst, sname, legs_payload)
                    st.success("Template saved.") if ok else st.error("Could not save template.")

        with c2:
            info = PREDEFINED_STRATEGIES.get(sname, {})
            with st.expander("🤖 AI Suggests for Today"):
                regime_snapshot = st.session_state.get("market_regime_snapshot", {"regime": "RANGE_BOUND"})
                trader_win_rates: Dict[str, float] = {}
                trade_rows = _db.get_trades(limit=2000)
                if trade_rows:
                    tdf = pd.DataFrame(trade_rows)
                    if "notes" in tdf.columns and "pnl" in tdf.columns:
                        tdf["strategy"] = tdf["notes"].astype(str).str.extract(r"Strategy:\s*(.*)")[0]
                        for strat_name, g in tdf.dropna(subset=["strategy"]).groupby("strategy"):
                            wins = (pd.to_numeric(g["pnl"], errors="coerce").fillna(0.0) > 0).mean() * 100.0
                            trader_win_rates[str(strat_name)] = float(wins)
                suggester = AIStrategySuggester()
                dte_for_suggest = calculate_days_to_expiry(expiry)
                suggestions = suggester.suggest(
                    regime=regime_snapshot,
                    vix=safe_float(st.session_state.get("_dashboard_metrics_prev", {}).get("VIX", 15), 15),
                    pcr=safe_float(st.session_state.get("_dashboard_metrics_prev", {}).get("NIFTY PCR", 1.0), 1.0),
                    trader_win_rates=trader_win_rates,
                    available_capital=float(_db.get_setting("capital_base", 100000)),
                    days_to_expiry=max(dte_for_suggest, 1),
                )
                if suggestions:
                    for sug in suggestions:
                        st.markdown(f"**{sug.strategy}** — Score {sug.score:.1f}")
                        st.caption(sug.reason)

            st.markdown(f"### {sname}")
            st.markdown(info.get("description", ""))
            mc = st.columns(4)
            mc[0].metric("Market View", info.get("view", ""))
            mc[1].metric("Risk", info.get("risk", ""))
            mc[2].metric("Reward", info.get("reward", ""))
            mc[3].metric("Complexity", info.get("complexity", ""))

            if st.session_state.get("strat_legs"):
                legs = st.session_state.strat_legs
                sexpiry = st.session_state.get("strat_expiry", expiry)
                scfg = st.session_state.get("strat_cfg", cfg)

                st.markdown("---")
                section("📐 Strategy Legs")
                leg_rows = [{"Leg": i+1,
                             "Action": f"{'🟢 BUY' if l.action == 'buy' else '🔴 SELL'}",
                             "Strike": l.strike, "Type": l.option_type,
                             "Expiry": format_expiry_short(l.expiry or sexpiry),
                             "Qty": l.quantity, "Label": l.label,
                             "Premium ₹": f"{l.premium:.2f}" if l.premium > 0 else "—"}
                            for i, l in enumerate(legs)]
                st.dataframe(pd.DataFrame(leg_rows), hide_index=True, width="stretch")
                if st.session_state.get("strat_multi_expiry"):
                    section("🗓️ Per-Leg Expiry")
                    expiry_choices = C.get_next_expiries(inst, 6)
                    for i, leg in enumerate(legs):
                        leg.expiry = st.selectbox(
                            f"Leg {i+1} Expiry",
                            expiry_choices,
                            index=(expiry_choices.index(leg.expiry) if leg.expiry in expiry_choices else 0),
                            format_func=format_expiry_short,
                            key=f"sb_leg_exp_{i}",
                        )
                    st.session_state.strat_legs = legs

                col_fetch, col_analyze = st.columns(2)
                if col_fetch.button("📊 Fetch Quotes", width="stretch"):
                    with st.spinner("Fetching quotes for all legs..."):
                        for leg in legs:
                            try:
                                r = client.get_option_quote(scfg.api_code, scfg.exchange,
                                                      (leg.expiry or sexpiry), leg.strike, leg.option_type)
                                if r["success"]:
                                    items = APIResponse(r).items
                                    if items:
                                        leg.premium = safe_float(items[0].get("ltp", 0))
                            except Exception:
                                pass
                        st.session_state.strat_legs = legs
                    st.success("✅ Quotes loaded")

                if col_analyze.button("📈 Analyze", width="stretch"):
                    metrics = calculate_strategy_metrics(legs)
                    mc = st.columns(4)
                    mc[0].metric("Net Premium", format_currency(metrics["net_premium"]))
                    mc[1].metric("Max Profit", format_currency(metrics["max_profit"]))
                    mc[2].metric("Max Loss", format_currency(metrics["max_loss"]))
                    if metrics["max_loss"] != 0:
                        mc[3].metric("R:R Ratio", f"1:{abs(metrics['max_profit']/metrics['max_loss']):.2f}")
                    rr_value = f"1:{abs(metrics['max_profit']/metrics['max_loss']):.2f}" if metrics["max_loss"] else "∞"
                    st.caption(f"R/R: {rr_value}")
                    if metrics["breakevens"]:
                        info_box(f"🎯 <b>Breakevens:</b> {', '.join(str(int(b)) for b in metrics['breakevens'])}")

                    payoff_df = generate_payoff_data(legs, int(atm), scfg.strike_gap)
                    if payoff_df is not None:
                        section("📊 Payoff Diagram")
                        import plotly.graph_objects as go
                        fig = go.Figure()
                        # Split payoff into profit/loss traces for visual zones.
                        profit_series = payoff_df["P&L"].where(payoff_df["P&L"] >= 0, 0)
                        loss_series = payoff_df["P&L"].where(payoff_df["P&L"] <= 0, 0)
                        fig.add_trace(go.Scatter(
                            x=payoff_df["Underlying"], y=profit_series,
                            mode='lines', name='Profit Zone',
                            line=dict(color='#2ca02c', width=2),
                            fill='tozeroy', fillcolor='rgba(44,160,44,0.20)'
                        ))
                        fig.add_trace(go.Scatter(
                            x=payoff_df["Underlying"], y=loss_series,
                            mode='lines', name='Loss Zone',
                            line=dict(color='#d62728', width=2),
                            fill='tozeroy', fillcolor='rgba(214,39,40,0.20)'
                        ))
                        fig.add_trace(go.Scatter(
                            x=payoff_df["Underlying"], y=payoff_df["P&L"],
                            mode='lines', name='P&L',
                            line=dict(color='#1f77b4', width=2),
                            fill='none'
                        ))
                        fig.add_hline(y=0, line_dash="dot", line_color="gray")
                        # Current spot marker (solid blue)
                        current_spot = st.session_state.get("last_spot", 0) or int(atm)
                        fig.add_vline(x=float(current_spot), line_dash="solid", line_color="blue",
                                      annotation_text="Current Spot")
                        # Break-even markers (dashed red)
                        for be in metrics.get("breakevens", []):
                            fig.add_vline(x=float(be), line_dash="dash", line_color="red",
                                          annotation_text=f"BE {int(be)}")
                        fig.update_layout(
                            title=f"{sname} Payoff",
                            xaxis_title="Underlying Price",
                            yaxis_title="P&L (₹)",
                            hovermode='x unified',
                            height=400
                        )
                        st.plotly_chart(fig, width="stretch")
                        scenario_spots = [
                            int(atm * 0.90),
                            int(atm * 0.95),
                            int(atm - 2 * scfg.strike_gap),
                            int(atm),
                            int(atm + 2 * scfg.strike_gap),
                            int(atm * 1.05),
                            int(atm * 1.10),
                        ]
                        scenario_pnl = []
                        for sp in scenario_spots:
                            pnl_value = 0.0
                            for leg in legs:
                                if leg.option_type == "CE":
                                    intrinsic = max(sp - leg.strike, 0)
                                else:
                                    intrinsic = max(leg.strike - sp, 0)
                                leg_pnl = (intrinsic - leg.premium) * leg.quantity
                                if leg.action == "sell":
                                    leg_pnl = -leg_pnl
                                pnl_value += leg_pnl
                            scenario_pnl.append({"Spot At Expiry": sp, "P&L (₹)": round(pnl_value, 2)})
                        section("📋 P&L At Expiry Table")
                        st.dataframe(pd.DataFrame(scenario_pnl), hide_index=True, width="stretch")

    with t_custom:
        section("✏️ Build Custom Strategy")
        st.caption("Add legs one by one to create a custom multi-leg strategy")
        if "custom_legs" not in st.session_state:
            st.session_state.custom_legs = []

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        with c1:
            cl_inst = st.selectbox("Instrument", list(C.INSTRUMENTS.keys()), key="cl_inst")
        cfg2 = C.get_instrument(cl_inst)
        with c2:
            cl_action = st.radio("Action", ["buy", "sell"], key="cl_act")
        with c3:
            cl_type = st.radio("Type", ["CE", "PE"], key="cl_type")
        with c4:
            cl_strike = st.number_input("Strike", min_value=cfg2.min_strike, max_value=cfg2.max_strike,
                                        value=int((cfg2.min_strike+cfg2.max_strike)//2),
                                        step=cfg2.strike_gap, key="cl_strike")
        with c5:
            cl_lots = st.number_input("Lots", min_value=1, value=1, key="cl_lots")
        with c6:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("➕ Add Leg", width="stretch"):
                st.session_state.custom_legs.append(StrategyLeg(
                    strike=int(cl_strike), option_type=cl_type,
                    action=cl_action, quantity=cl_lots * cfg2.lot_size
                ))

        if st.session_state.custom_legs:
            cleg_rows = [{"#": i+1, "Action": l.action.upper(), "Strike": l.strike,
                          "Type": l.option_type, "Qty": l.quantity,
                          "Premium": l.premium if l.premium > 0 else "—"}
                         for i, l in enumerate(st.session_state.custom_legs)]
            st.dataframe(pd.DataFrame(cleg_rows), hide_index=True, width="stretch")
            if st.button("🗑️ Clear All Legs"):
                st.session_state.custom_legs = []
                st.rerun()
            if st.button("📊 Analyze Custom Strategy", type="primary"):
                metrics = calculate_strategy_metrics(st.session_state.custom_legs)
                mc = st.columns(3)
                mc[0].metric("Net Premium", format_currency(metrics["net_premium"]))
                mc[1].metric("Max Profit", format_currency(metrics["max_profit"]))
                mc[2].metric("Max Loss", format_currency(metrics["max_loss"]))

    with t_execute:
        section("⚡ Execute Strategy")
        if not st.session_state.get("strat_legs"):
            info_box("Build a strategy in the <b>Select Strategy</b> tab first, then come here to execute it.")
            return
        legs = st.session_state.strat_legs
        sname_exec = st.session_state.get("strat_name", "Custom")
        scfg = st.session_state.get("strat_cfg", cfg)
        sexpiry = st.session_state.get("strat_expiry", expiry)
        is_multi_expiry = bool(st.session_state.get("strat_multi_expiry", False))

        st.write(f"**Strategy:** {sname_exec}")
        if is_multi_expiry:
            st.write(f"**Instrument:** {scfg.display_name} | **Expiry:** Multi-leg")
        else:
            st.write(f"**Instrument:** {scfg.display_name} | **Expiry:** {format_expiry_short(sexpiry)}")
        danger_box("⚠️ This will place <b>real orders</b> for all legs simultaneously.")

        st.markdown("**Estimated Charges (per leg):**")
        total_preview_charges = 0.0
        for i, leg in enumerate(legs):
            st.caption(f"Leg {i+1}: {leg.action.upper()} {leg.strike} {leg.option_type} × {leg.quantity}")
            leg_expiry = leg.expiry or sexpiry
            prev = render_order_cost_preview(
                client=client,
                stock_code=scfg.api_code,
                exchange_code=scfg.exchange,
                product="options",
                order_type="market",
                price=0.0,
                action=leg.action,
                quantity=leg.quantity,
                expiry_date=leg_expiry,
                right="call" if leg.option_type == "CE" else "put",
                strike_price=str(leg.strike),
                key_prefix=f"strat_preview_{i}",
            )
            if isinstance(prev, dict):
                total_preview_charges += float(prev.get("total_brokerage", 0) or 0)
        st.info(f"Approx total previewed charges: ₹{total_preview_charges:,.2f}")
        total_premium = 0.0
        for leg in legs:
            leg_value = (leg.premium or 0.0) * leg.quantity
            total_premium += -leg_value if leg.action == "buy" else leg_value
        premium_type = "Credit" if total_premium >= 0 else "Debit"
        st.info(f"Estimated total premium {premium_type}: ₹{abs(total_premium):,.2f}")

        ack = st.checkbox("I confirm all legs and want to execute", key="se_ack")
        if ack and st.button("⚡ PLACE ALL LEGS", type="primary", width="stretch"):
            ok, fail = 0, 0
            for leg in legs:
                with st.spinner(f"Placing {leg.action.upper()} {leg.strike} {leg.option_type}..."):
                    leg_expiry = leg.expiry or sexpiry
                    r = scfg and client.place_order(
                        scfg.api_code, scfg.exchange, leg_expiry,
                        leg.strike, leg.option_type, leg.action, leg.quantity, "market", 0.0
                    )
                    if r and r.get("success"):
                        ok += 1
                        _db.log_trade(
                            stock_code=scfg.api_code, exchange=scfg.exchange,
                            strike=leg.strike, option_type=leg.option_type,
                            expiry=leg_expiry, action=leg.action, quantity=leg.quantity,
                            price=0, order_type="market",
                            notes=f"Strategy: {sname_exec}"
                        )
                    else:
                        fail += 1
                        st.error(f"❌ Leg {leg.strike} {leg.option_type}: {r.get('message') if r else 'Failed'}")
            if ok:
                st.success(f"✅ {ok}/{ok+fail} legs executed successfully!")
                invalidate_trading_caches()


# ═══════════════════════════════════════════════════════════════
# PAGE: ANALYTICS
# ═══════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_analytics():
    page_header("📈 Analytics")
    client = get_client()
    if not client:
        return

    t1, t2, t3, t4, t5, t6 = st.tabs([
        "📊 Portfolio Greeks",
        "💰 Margin",
        "📈 Performance",
        "🧪 Stress Test",
        "🎲 Monte Carlo VaR",
        "🌐 IV Surface",
    ])

    with t1:
        all_pos = get_cached_positions(client)
        if all_pos is None:
            st.error("❌ Failed to load positions")
            return
        opt_pos, _ = split_positions(all_pos)
        if not opt_pos:
            empty_state("📊", "No options to analyze")
        else:
            spot_prices = fetch_spot_prices(client, opt_pos)
            if spot_prices:
                st.caption("Spot: " + ", ".join(f"{C.api_code_to_display(k)}: ₹{v:,.0f}" for k, v in spot_prices.items()))
            else:
                st.warning("⚠️ Could not fetch spot prices. Using strike as approximation.")

            rows = []
            for p in opt_pos:
                pt = detect_position_type(p)
                qty = abs(safe_int(p.get("quantity", 0)))
                strike = safe_float(p.get("strike_price", 0))
                ltp = safe_float(p.get("ltp", 0))
                ot = C.normalize_option_type(p.get("right", ""))
                exp = p.get("expiry_date", "")
                stock = p.get("stock_code", "")
                mult = -1 if pt == "short" else 1
                spot = spot_prices.get(stock, strike)
                dte_ = calculate_days_to_expiry(exp) if exp else 30
                tte = max(dte_ / C.DAYS_PER_YEAR, 0.001)
                try:
                    iv = estimate_implied_volatility(ltp, spot, strike, tte, ot) if ltp > 0 and spot > 0 else 0.20
                    g = calculate_greeks(spot, strike, tte, iv, ot)
                    for k in g:
                        g[k] = g[k] * mult * qty
                except Exception:
                    g = {'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'rho': 0}
                    iv = 0.0
                pnl = calculate_pnl(pt, safe_float(p.get("average_price", 0)), ltp, qty)
                rows.append({
                    "Position": C.api_code_to_display(stock),
                    "Strike": int(strike), "Type": ot, "Dir": pt.upper(), "Qty": qty,
                    "Spot ₹": f"{spot:,.0f}",
                    "IV%": f"{iv*100:.1f}", "DTE": dte_,
                    "Delta": f"{g['delta']:+.2f}",
                    "Gamma": f"{g['gamma']:+.4f}",
                    "Theta ₹": f"{g['theta']:+.0f}",
                    "Vega ₹": f"{g['vega']:+.0f}",
                    "P&L ₹": f"{pnl:+,.0f}"
                })

            if rows:
                rows_df = pd.DataFrame(rows)
                st.dataframe(rows_df, hide_index=True, width="stretch")
                # Portfolio aggregate
                port_g = calculate_portfolio_greeks(opt_pos, spot_prices)
                st.markdown("---")
                section("Portfolio Net Greeks")
                gc = st.columns(5)
                gc[0].metric("Net Delta", f"{port_g['delta']:+.2f}")
                gc[1].metric("Net Gamma", f"{port_g['gamma']:+.4f}")
                gc[2].metric("Net Theta/day", f"₹{port_g['theta']:+.0f}")
                gc[3].metric("Net Vega/1%", f"₹{port_g['vega']:+.0f}")
                gc[4].metric("Net Rho/1%", f"₹{port_g['rho']:+.0f}")
                render_portfolio_greeks_heatmap(rows_df)

                st.markdown("**Quick Action: Navigate to Square Off**")
                pos_labels = (
                    rows_df["Position"].astype(str)
                    + " "
                    + rows_df["Strike"].astype(str)
                    + " "
                    + rows_df["Type"].astype(str)
                ).tolist()
                selected_pos = st.selectbox("Select Position", pos_labels, key="analytics_sqoff_select")
                if st.button("Go to Square Off", key="analytics_sqoff_btn"):
                    st.session_state["square_off_prefill"] = selected_pos
                    SessionState.navigate_to("❌ Square Off")
                    st.rerun()

                # Delta visualization
                if any(r["Delta"] != "+0.00" for r in rows):
                    delta_df = rows_df[["Position", "Strike", "Type", "Delta"]].copy()
                    delta_df["Delta_val"] = delta_df["Delta"].astype(float)
                    st.bar_chart(delta_df.set_index("Position")["Delta_val"])

    with t2:
        section("Margin Analysis")
        funds = get_cached_funds(client)
        if funds:
            util = funds["allocated_fno"] / funds["total_balance"] * 100 if funds["total_balance"] > 0 else 0
            c1, c2 = st.columns(2)
            with c1:
                st.metric("Total Balance", format_currency(funds["total_balance"]))
                st.metric("F&O Allocated", format_currency(funds["allocated_fno"]))
                st.metric("Equity Allocated", format_currency(funds["allocated_equity"]))
            with c2:
                st.metric("Available (Free)", format_currency(funds["unallocated"]))
                st.metric("F&O Blocked", format_currency(funds["block_fno"]))
                st.metric("Utilization %", f"{util:.1f}%",
                          delta="⚠️ High" if util > 75 else "✅ OK",
                          delta_color="inverse" if util > 75 else "normal")
            if util > 90:
                danger_box("🚨 <b>Critical:</b> Margin utilization > 90%. Risk of forced liquidation!")
            elif util > 75:
                warn_box("⚠️ <b>Warning:</b> Margin utilization > 75%. Consider reducing exposure.")

            chart_df = pd.DataFrame({
                "Category": ["F&O", "Equity", "Unallocated", "Blocked F&O"],
                "Amount": [funds["allocated_fno"], funds["allocated_equity"],
                           funds["unallocated"], funds["block_fno"]]
            }).query("Amount > 0")
            if not chart_df.empty:
                st.bar_chart(chart_df.set_index("Category"), width="stretch")

    with t3:
        section("Performance Analytics")
        hist = _db.get_pnl_history(90)
        if hist:
            hist_df = pd.DataFrame(hist).sort_values("date")
            c1, c2 = st.columns(2)
            with c1:
                if "realized_pnl" in hist_df.columns:
                    hist_df["Cumulative P&L"] = hist_df["realized_pnl"].cumsum()
                    st.line_chart(hist_df.set_index("date")[["Cumulative P&L"]], width="stretch")
            with c2:
                if "num_trades" in hist_df.columns:
                    st.bar_chart(hist_df.set_index("date")[["num_trades"]], width="stretch")

            daily_pnl = hist_df.get("realized_pnl", pd.Series(dtype=float)).tolist()
            if daily_pnl:
                mc = st.columns(4)
                mc[0].metric("Total Days", len(daily_pnl))
                mc[1].metric("Best Day", format_currency(max(daily_pnl)))
                mc[2].metric("Worst Day", format_currency(min(daily_pnl)))
                mc[3].metric("Max Drawdown", format_currency(calculate_max_drawdown(
                    list(hist_df.get("realized_pnl", pd.Series()).cumsum()))))

            close_series = pd.to_numeric(hist_df.get("close", pd.Series(dtype=float)), errors="coerce")
            if close_series.notna().sum() >= 21:
                rv20 = rolling_realized_vol(close_series, window=20)
                rv30 = rolling_realized_vol(close_series, window=30)
                rv_df = pd.DataFrame({"rv_20": rv20, "rv_30": rv30}).dropna()
                if not rv_df.empty:
                    st.line_chart(rv_df, width="stretch")
                    spread = iv_vs_rv_spread(current_iv=15.0, hist_close=close_series, window=20)
                    st.caption(f"IV-RV Spread: IV {spread['iv']:.2f}% | RV {spread['rv']:.2f}% | Spread {spread['spread']:+.2f}% ({spread['spread_interpretation']})")

            symbol_groups = hist_df.groupby("symbol") if "symbol" in hist_df.columns else []
            corr_input = {}
            for sym, gdf in symbol_groups:
                s_close = pd.to_numeric(gdf.get("close", pd.Series(dtype=float)), errors="coerce").dropna()
                if len(s_close) >= 15:
                    corr_input[str(sym)] = s_close.reset_index(drop=True)
            corr = portfolio_correlation_matrix(corr_input)
            if not corr.empty:
                st.markdown("**Symbol Correlation Matrix**")
                st.dataframe(safe_background_gradient(corr, cmap='RdYlGn', axis=None), width="stretch")
        else:
            empty_state("📈", "No P&L history yet", "Trade to build history")

        st.markdown("---")
        section("📓 Trade Journal")
        trades = _db.get_trades(limit=5000)
        pnl_hist_full = _db.get_pnl_history(365)
        if trades:
            trades_df = pd.DataFrame(trades)
            pnl_series = pd.to_numeric(trades_df.get("pnl", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
            wins = pnl_series[pnl_series > 0]
            losses = pnl_series[pnl_series < 0]
            win_rate = (len(wins) / len(pnl_series) * 100.0) if len(pnl_series) else 0.0
            gross_profit = float(wins.sum()) if not wins.empty else 0.0
            gross_loss = float(abs(losses.sum())) if not losses.empty else 0.0
            profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
            avg_win = float(wins.mean()) if not wins.empty else 0.0
            avg_loss = float(losses.mean()) if not losses.empty else 0.0
            avg_win_loss = (abs(avg_win / avg_loss) if avg_loss != 0 else float("inf"))

            streak_win = streak_loss = max_win = max_loss = 0
            for p in pnl_series.tolist():
                if p > 0:
                    streak_win += 1
                    streak_loss = 0
                    max_win = max(max_win, streak_win)
                elif p < 0:
                    streak_loss += 1
                    streak_win = 0
                    max_loss = max(max_loss, streak_loss)

            daily_df = pd.DataFrame(pnl_hist_full) if pnl_hist_full else pd.DataFrame()
            daily_returns = []
            if not daily_df.empty and "realized_pnl" in daily_df.columns:
                daily_vals = pd.to_numeric(daily_df["realized_pnl"], errors="coerce").fillna(0.0)
                daily_returns = daily_vals.tolist()
            sharpe = 0.0
            calmar = 0.0
            if daily_returns:
                arr = np.array(daily_returns, dtype=float)
                if arr.std() > 0:
                    sharpe = float((arr.mean() * 252 - 0.065) / (arr.std() * np.sqrt(252)))
                cum = np.cumsum(arr)
                max_dd = abs(calculate_max_drawdown(cum.tolist()))
                annual_ret = float(arr.mean() * 252)
                calmar = (annual_ret / max_dd) if max_dd > 0 else 0.0

            m1, m2, m3, m4, m5, m6 = st.columns(6)
            m1.metric("Win Rate %", f"{win_rate:.1f}%")
            m2.metric("Profit Factor", "∞" if np.isinf(profit_factor) else f"{profit_factor:.2f}")
            m3.metric("Avg Win / Loss", "∞" if np.isinf(avg_win_loss) else f"{avg_win_loss:.2f}")
            m4.metric("Max Win Streak", str(max_win))
            m5.metric("Sharpe Ratio", f"{sharpe:.2f}")
            m6.metric("Calmar Ratio", f"{calmar:.2f}")
            st.caption(f"Max Loss Streak: {max_loss}")

            if not daily_df.empty and "date" in daily_df.columns and "realized_pnl" in daily_df.columns:
                daily_df["date"] = pd.to_datetime(daily_df["date"], errors="coerce")
                daily_plot = daily_df.dropna(subset=["date"]).sort_values("date").tail(30).copy()
                if not daily_plot.empty:
                    st.bar_chart(daily_plot.set_index("date")["realized_pnl"], width="stretch")

                daily_plot["month"] = daily_plot["date"].dt.to_period("M").astype(str)
                daily_plot["day"] = daily_plot["date"].dt.day
                month_heat = daily_plot.pivot_table(index="month", columns="day", values="realized_pnl", aggfunc="sum").fillna(0)
                if not month_heat.empty:
                    st.markdown("**Monthly P&L Heatmap**")
                    st.dataframe(safe_background_gradient(month_heat, cmap="RdYlGn", axis=None), width="stretch")

            inst_col = "stock_code" if "stock_code" in trades_df.columns else ("symbol" if "symbol" in trades_df.columns else None)
            if inst_col:
                inst_breakdown = trades_df.groupby(inst_col).size().reset_index(name="Trades")
                st.markdown("**Instrument Breakdown**")
                st.dataframe(inst_breakdown, hide_index=True, width="stretch")

            if "notes" in trades_df.columns:
                strat_series = trades_df["notes"].astype(str).str.extract(r"Strategy:\s*(.*)")[0].fillna("Manual")
                strat_df = pd.DataFrame({"strategy": strat_series, "pnl": pnl_series})
                strat_breakdown = strat_df.groupby("strategy")["pnl"].sum().reset_index().sort_values("pnl", ascending=False)
                st.markdown("**Strategy Breakdown (P&L)**")
                st.dataframe(strat_breakdown, hide_index=True, width="stretch")
            else:
                strat_breakdown = pd.DataFrame()

            summary_export = pd.DataFrame(
                [
                    {"metric": "win_rate_pct", "value": win_rate},
                    {"metric": "profit_factor", "value": profit_factor},
                    {"metric": "avg_win_loss", "value": avg_win_loss},
                    {"metric": "max_consecutive_wins", "value": max_win},
                    {"metric": "max_consecutive_losses", "value": max_loss},
                    {"metric": "sharpe_ratio", "value": sharpe},
                    {"metric": "calmar_ratio", "value": calmar},
                ]
            )
            if st.button("📥 Download Performance Report (Excel)", key="trade_journal_export"):
                export_to_excel(
                    {
                        "Summary": summary_export,
                        "DailyPnL": pd.DataFrame(pnl_hist_full),
                        "Trades": trades_df,
                        "StrategyBreakdown": strat_breakdown,
                    },
                    "performance_report.xlsx",
                )
        else:
            st.info("No trade data available for journal analytics yet.")

        st.markdown("---")
        section("IV vs RV Spread Monitor")
        ivrv_df = build_iv_rv_spread_monitor(client, ["NIFTY", "BANKNIFTY", "FINNIFTY"])
        if ivrv_df.empty:
            st.info("IV/RV monitor data unavailable right now.")
        else:
            st.dataframe(ivrv_df, hide_index=True, width="stretch")
            st.caption("Thresholds: VRP > 30% → strong sell volatility, VRP < -15% → strong buy volatility")

    with t4:
        section("🧪 Stress Test")
        all_pos = get_cached_positions(client)
        opt_pos, _ = split_positions(all_pos or [])
        if not opt_pos:
            empty_state("🧪", "No positions to stress test")
        else:
            spot_prices = fetch_spot_prices(client, opt_pos)
            st.caption("Simulates P&L under different spot and IV scenarios")
            results = stress_test_portfolio(opt_pos, spot_prices)
            if results:
                import plotly.graph_objects as go
                iv_scenario = st.selectbox("Select IV Scenario", list(results.keys()))
                scenario_data = results[iv_scenario]
                fig = go.Figure(go.Bar(
                    x=list(scenario_data.keys()),
                    y=list(scenario_data.values()),
                    marker_color=["#dc3545" if v < 0 else "#28a745" for v in scenario_data.values()]
                ))
                fig.update_layout(title=f"P&L under {iv_scenario}", xaxis_title="Spot Move",
                                  yaxis_title="P&L (₹)", height=350)
                st.plotly_chart(fig, width="stretch")
                # Show table of all scenarios
                stress_df = pd.DataFrame(results)
                st.dataframe(safe_background_gradient(stress_df, cmap='RdYlGn', axis=None),
                             width="stretch")


    with t5:
        st.markdown("**Monte Carlo Value-at-Risk (1-day, 95% confidence)**")
        positions = client.get_positions().get("data", {}).get("Success", []) or []
        if not positions:
            st.info("No open positions found.")
        else:
            col1, col2, col3 = st.columns(3)
            with col1:
                mc_days = st.selectbox("Horizon", [1, 3, 5], key="mc_days")
            with col2:
                mc_sims = st.selectbox("Simulations", [5_000, 10_000, 50_000], index=1, key="mc_sims")
            with col3:
                mc_vol = st.number_input("Portfolio IV %", value=15.0, step=0.5, key="mc_vol")

            spot = st.session_state.get("last_spot", 22000)
            if st.button("▶ Run Monte Carlo", key="mc_run_btn"):
                with st.spinner(f"Running {mc_sims:,} simulations..."):
                    var_result = monte_carlo_var(
                        positions=positions,
                        spot_price=float(spot),
                        volatility_annual=float(mc_vol) / 100,
                        days=int(mc_days),
                        simulations=int(mc_sims),
                    )

                col_a, col_b, col_c, col_d = st.columns(4)
                col_a.metric("VaR 95%", f"₹{var_result['var_95']:,.0f}", help="Loss not exceeded 95% of the time")
                col_b.metric("VaR 99%", f"₹{var_result['var_99']:,.0f}", help="Loss not exceeded 99% of the time")
                col_c.metric("CVaR 95%", f"₹{var_result['cvar_95']:,.0f}", help="Expected loss when VaR is breached")
                col_d.metric("Expected P&L", f"₹{var_result['expected_pnl']:,.0f}")

                col_e, col_f = st.columns(2)
                col_e.metric("Worst Case", f"₹{var_result['worst_case']:,.0f}")
                col_f.metric("Best Case", f"₹{var_result['best_case']:,.0f}")

    with t6:
        section("🌐 IV Surface Visualization")
        inst = st.selectbox("Instrument", list(C.INSTRUMENTS.keys()), index=0, key="ivsurf_inst")
        expiries = C.get_next_expiries(inst, 6)
        spot = st.session_state.get("last_spot", 0)
        if not expiries:
            st.info("No expiries available for IV surface")
        elif spot <= 0:
            st.info("Spot unavailable. Open Option Chain/Dashboard first to warm spot cache.")
        else:
            with st.spinner("Building IV surface (cached for 5 minutes)..."):
                surface_data = build_iv_surface_data(client, inst, expiries, float(spot))
            render_iv_surface(surface_data, float(spot))


@error_handler
@require_auth
def page_futures_trading():
    """Futures Trading page."""
    st.markdown('<div class="page-header">📈 Futures Trading</div>', unsafe_allow_html=True)
    from futures import (
        get_futures_expiries, calculate_basis, estimate_fair_value_futures,
        FuturesOrderRequest, validate_futures_order,
        build_futures_place_order_kwargs, build_roll_plan, execute_roll,
        render_basis_chart,
    )

    client = get_client()
    if not client:
        return

    tab1, tab2, tab3, tab4 = st.tabs(["📊 Quotes", "🛒 Buy / Sell", "🔄 Roll Position", "📉 Basis Chart"])

    col_inst, col_exch = st.columns([2, 1])
    with col_inst:
        instrument = st.selectbox("Instrument", list(C.INSTRUMENTS.keys()), key="fut_instrument")
        cfg = C.INSTRUMENTS[instrument]
    with col_exch:
        exchange = st.text_input("Exchange", value="NFO", key="fut_exchange")

    expiries = get_futures_expiries(instrument, count=3, exchange=exchange)

    with tab1:
        if st.button("🔄 Refresh Quotes", key="fut_refresh_quotes"):
            with st.spinner("Fetching futures quotes..."):
                quotes = {}
                for exp in expiries:
                    resp = client.get_futures_quote(cfg.api_code, exchange, exp)
                    if resp.get("success"):
                        data = (resp.get("data", {}) or {}).get("Success") or []
                        if isinstance(data, list) and data:
                            quotes[exp] = data[0]

                spot_resp = client.get_quotes(
                    stock_code=cfg.spot_code or cfg.api_code,
                    exchange_code=cfg.spot_exchange or "NSE",
                    product_type="cash",
                )
                spot = 0.0
                if spot_resp.get("success"):
                    sd = (spot_resp.get("data", {}) or {}).get("Success") or [{}]
                    try:
                        spot = float((sd[0] if sd else {}).get("ltp", 0) or 0)
                    except Exception:
                        pass
                st.session_state["fut_quotes"] = quotes
                st.session_state["fut_spot"] = spot

        quotes = st.session_state.get("fut_quotes", {})
        spot = st.session_state.get("fut_spot", 0.0)
        if not quotes:
            st.info("Click **Refresh Quotes** to load live futures prices.")
        else:
            st.metric("Spot Price", f"₹{spot:,.2f}" if spot else "—")
            st.divider()
            for exp, q in quotes.items():
                ltp = float(q.get("ltp", 0) or 0)
                chg = float(q.get("change_in_price", 0) or 0)
                oi = int(float(q.get("open_interest", 0) or 0))
                basis = calculate_basis(ltp, spot) if spot else 0
                dte = (datetime.strptime(exp[:10], "%Y-%m-%d") - datetime.now()).days
                fair = estimate_fair_value_futures(spot, dte) if spot else 0
                c1, c2, c3, c4, c5 = st.columns(5)
                label = datetime.strptime(exp[:10], "%Y-%m-%d").strftime("%b %Y")
                c1.metric(f"{label}", f"₹{ltp:,.2f}", delta=f"{chg:+.2f}")
                c2.metric("Basis", f"₹{basis:+.2f}")
                c3.metric("Fair Value", f"₹{fair:,.2f}" if fair else "—")
                c4.metric("OI", f"{oi:,}")
                c5.metric("DTE", f"{dte}d")

    with tab2:
        c1, c2 = st.columns(2)
        with c1:
            expiry = st.selectbox("Expiry", expiries, key="fut_expiry_trade")
            action = st.radio("Action", ["BUY", "SELL"], horizontal=True, key="fut_action")
        with c2:
            lots = st.number_input("Lots", min_value=1, value=1, step=1, key="fut_lots")
            quantity = lots * cfg.lot_size
            st.caption(f"Qty: {quantity} contracts")

        order_type = st.selectbox("Order Type", ["Market", "Limit", "Stop-Market", "Stop-Limit"], key="fut_order_type")
        order_type_map = {"Market": "market", "Limit": "limit", "Stop-Market": "stop_market", "Stop-Limit": "stop_limit"}
        ot = order_type_map[order_type]
        limit_price = 0.0
        stop_price = 0.0
        if ot in ("limit", "stop_limit"):
            limit_price = st.number_input("Limit Price ₹", min_value=0.01, value=22000.0, step=10.0, key="fut_limit")
        if ot in ("stop_market", "stop_limit"):
            stop_price = st.number_input("Stop Trigger ₹", min_value=0.01, value=21800.0, step=10.0, key="fut_stop")

        funds_resp = client.get_funds()
        available_margin = 0.0
        if funds_resp.get("success"):
            d = (funds_resp.get("data", {}) or {}).get("Success") or {}
            if isinstance(d, list) and d:
                d = d[0]
            if isinstance(d, dict):
                available_margin = float(d.get("total_bank_balance", 0) or 0)

        req = FuturesOrderRequest(cfg.api_code, exchange, expiry, action.lower(), lots, cfg.lot_size, ot, limit_price, stop_price)
        is_valid, err = validate_futures_order(req, available_margin)
        if not is_valid:
            st.error(f"❌ {err}")

        price_proxy = limit_price or stop_price or 22000
        est_margin = quantity * price_proxy * 0.15
        st.caption(f"Est. margin required: ₹{est_margin:,.0f} | Available: ₹{available_margin:,.0f}")

        if st.button(f"{'🟢 BUY' if action == 'BUY' else '🔴 SELL'} Futures", type="primary", disabled=not is_valid, key="fut_place_btn"):
            kwargs = build_futures_place_order_kwargs(req)
            with st.spinner("Placing futures order..."):
                resp = client.place_order(**kwargs)
            if resp.get("success"):
                st.success("✅ Futures order placed!")
            else:
                st.error(f"❌ {resp.get('message', 'Order failed')}")

    with tab3:
        st.markdown("**Roll a futures position from near-month to far-month expiry.**")
        c1, c2 = st.columns(2)
        with c1:
            near_exp = st.selectbox("Close (Near Month)", expiries, index=0, key="roll_near")
        with c2:
            far_opts = [e for e in expiries if e != near_exp]
            far_exp = st.selectbox("Open (Far Month)", far_opts, key="roll_far")

        roll_lots = st.number_input("Lots to Roll", min_value=1, value=1, key="roll_lots")
        position_side = st.radio("Current Position", ["Long (Buy)", "Short (Sell)"], horizontal=True, key="roll_side")
        current_action = "buy" if "Long" in position_side else "sell"
        roll_order_type = st.selectbox("Roll Order Type", ["market", "limit"], key="roll_ot")

        if st.button("📊 Preview Roll", key="roll_preview_btn"):
            with st.spinner("Fetching quotes for roll preview..."):
                st.session_state["roll_plan"] = build_roll_plan(client, cfg.api_code, exchange, near_exp, far_exp, roll_lots, cfg.lot_size)

        roll_plan = st.session_state.get("roll_plan")
        if roll_plan:
            sign = "+" if roll_plan.roll_cost >= 0 else ""
            cost_total = abs(roll_plan.roll_cost) * roll_lots * cfg.lot_size
            st.info(
                f"Roll/contract: ₹{sign}{roll_plan.roll_cost:.2f} ({sign}{roll_plan.roll_cost_pct:.2f}%) | "
                f"Near: ₹{roll_plan.near_ltp:,.2f} | Far: ₹{roll_plan.far_ltp:,.2f} | "
                f"Total {'Cost' if roll_plan.roll_cost > 0 else 'Credit'}: ₹{cost_total:,.2f}"
            )
            if st.button("✅ Execute Roll", type="primary", key="roll_exec_btn"):
                close_resp, open_resp = execute_roll(client, roll_plan, current_action, roll_order_type)
                if close_resp.get("success") and open_resp.get("success"):
                    st.success("✅ Roll executed successfully!")
                else:
                    if not close_resp.get("success"):
                        st.error(f"❌ Close order failed: {close_resp.get('message')}")
                    if not open_resp.get("success"):
                        st.error(f"❌ Open order failed: {open_resp.get('message')}")

    with tab4:
        if st.button("🔄 Load Basis Chart", key="fut_basis_btn"):
            with st.spinner("Fetching futures quotes..."):
                futures_data: Dict[str, float] = {}
                for exp in expiries:
                    resp = client.get_futures_quote(cfg.api_code, exchange, exp)
                    if resp.get("success"):
                        sd = (resp.get("data", {}) or {}).get("Success") or []
                        if isinstance(sd, list) and sd:
                            try:
                                futures_data[exp] = float(sd[0].get("ltp", 0) or 0)
                            except Exception:
                                pass
                spot_ltp = st.session_state.get("fut_spot", 0.0)
                st.session_state["basis_data"] = (futures_data, spot_ltp)

        basis_data = st.session_state.get("basis_data")
        if basis_data:
            futures_data, spot_ltp = basis_data
            fig = render_basis_chart(futures_data, spot_ltp, instrument)
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("Click **Load Basis Chart** above.")

# ═══════════════════════════════════════════════════════════════
# PAGE: HISTORICAL DATA
# ═══════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_historical_data():
    """Historical Data & Technical Analysis page."""
    st.markdown('<div class="page-header">📊 Historical Data & Charts</div>', unsafe_allow_html=True)

    from historical import HistoricalDataFetcher, get_historical_cache
    from charts import render_candlestick, render_technical_subplot
    import ta_indicators as ta
    import plotly.graph_objects as go

    client = get_client()
    if not client:
        return

    fetcher = HistoricalDataFetcher(client)

    tab1, tab2, tab3, tab4 = st.tabs(["📊 Price Chart", "📈 Options History", "🔢 Technical Analysis", "📥 Data Export"])

    with st.expander("⚙️ Instrument Settings", expanded=True):
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            instrument = st.selectbox("Instrument", list(C.INSTRUMENTS.keys()), key="hist_instrument")
            cfg = C.INSTRUMENTS[instrument]
        with col2:
            product_type = st.selectbox("Product", ["cash", "futures", "options"], key="hist_product")
        with col3:
            exchange = st.text_input("Exchange", value=cfg.exchange, key="hist_exchange")

        if product_type == "options":
            col4, col5, col6 = st.columns(3)
            with col4:
                expiry_options = C.get_next_expiries(instrument, count=6)
                expiry = st.selectbox("Expiry", expiry_options, key="hist_expiry")
            with col5:
                right = st.selectbox("Right", ["call", "put"], key="hist_right")
            with col6:
                atm = st.number_input(
                    "Strike",
                    value=int(st.session_state.get("last_spot", 22000) // cfg.strike_gap * cfg.strike_gap),
                    step=cfg.strike_gap,
                    key="hist_strike",
                )
            expiry_date = expiry
            right_param = right
            strike_param = str(int(atm))
        else:
            expiry_date = right_param = strike_param = ""

        col7, col8, col9 = st.columns(3)
        with col7:
            from_date = st.date_input("From Date", value=date.today() - timedelta(days=365), key="hist_from")
        with col8:
            to_date = st.date_input("To Date", value=date.today(), key="hist_to")
        with col9:
            interval = st.selectbox("Interval", ["1day", "30minute", "5minute", "1minute"], key="hist_interval")

        fetch_btn = st.button("📥 Fetch Data", type="primary", key="hist_fetch")

    if "hist_df" not in st.session_state:
        st.session_state["hist_df"] = None

    if fetch_btn:
        with st.spinner("Fetching historical data..."):
            try:
                df = fetcher.fetch(
                    stock_code=cfg.api_code,
                    exchange_code=exchange,
                    product_type=product_type,
                    from_date=str(from_date),
                    to_date=str(to_date),
                    interval=interval,
                    expiry_date=expiry_date,
                    right=right_param,
                    strike_price=strike_param,
                )
                st.session_state["hist_df"] = df
                if df.empty:
                    st.warning("No data returned for the selected parameters.")
                else:
                    st.success(f"✅ Fetched {len(df):,} candles ({from_date} → {to_date})")
                    st.caption(f"API calls used: {fetcher.last_api_calls}")
            except Exception as e:
                st.error(f"Fetch failed: {e}")
                log.error(f"Historical fetch error: {e}", exc_info=True)

    df = st.session_state.get("hist_df")

    with tab1:
        if df is None:
            st.info("Configure instrument settings above and click **Fetch Data**.")
        elif df.empty:
            st.warning("No data available for the selected parameters.")
        else:
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.radio("Chart Type", ["Candlestick", "Line", "OHLC"], horizontal=True, key="chart_type")
            with col_b:
                emas = st.multiselect("EMA Overlays", [9, 20, 50, 100, 200], default=[20, 50], key="chart_emas")
            with col_c:
                show_bb = st.checkbox("Bollinger Bands", key="chart_bb")
                show_vwap = st.checkbox("VWAP", key="chart_vwap")
                show_sr = st.checkbox("Support/Resistance", key="chart_sr")

            title = (
                f"{instrument} {'CALL' if right_param == 'call' else 'PUT' if right_param == 'put' else ''}"
                f"{' ' + strike_param if strike_param else ''} | {interval} | {str(from_date)} → {str(to_date)}"
            ).strip()

            fig = render_candlestick(
                df,
                title=title,
                show_volume=True,
                show_ema=emas if emas else None,
                show_bb=show_bb,
                show_vwap=show_vwap,
                support_resistance=show_sr,
                height=550,
            )
            st.plotly_chart(fig, width="stretch")

            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("Period High", f"₹{df['high'].max():,.2f}")
            col2.metric("Period Low", f"₹{df['low'].min():,.2f}")
            col3.metric("Period Change", f"{(df['close'].iloc[-1] / df['close'].iloc[0] - 1) * 100:.2f}%")
            col4.metric("Avg Volume", f"{df['volume'].mean():,.0f}")
            col5.metric("Candles", f"{len(df):,}")

    with tab2:
        st.markdown("**Compare historical option price vs underlying index spot.**")
        if df is None or df.empty:
            st.info("Fetch data in the Price Chart tab first.")
        elif product_type == "options":
            try:
                with st.spinner("Fetching spot data for comparison..."):
                    spot_df = fetcher.fetch(
                        stock_code=cfg.spot_code or cfg.api_code,
                        exchange_code=cfg.spot_exchange or "NSE",
                        product_type="cash",
                        from_date=str(from_date),
                        to_date=str(to_date),
                        interval=interval,
                    )
                if not spot_df.empty:
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=df["datetime"], y=df["close"], name=f"{instrument} {strike_param} {'CE' if right_param == 'call' else 'PE'}", line=dict(color="#388bfd", width=2), yaxis="y"))
                    fig.add_trace(go.Scatter(x=spot_df["datetime"], y=spot_df["close"], name=f"{instrument} Spot", line=dict(color="#f78166", width=1.5, dash="dot"), yaxis="y2"))
                    fig.update_layout(
                        title="Option Price vs Underlying Spot",
                        yaxis=dict(title="Option Price ₹", side="left"),
                        yaxis2=dict(title="Spot Price ₹", side="right", overlaying="y"),
                        height=450,
                        plot_bgcolor="#0d1117",
                        paper_bgcolor="#161b22",
                        font=dict(color="#e6edf3"),
                    )
                    st.plotly_chart(fig, width="stretch")
            except Exception as e:
                st.warning(f"Could not fetch spot data: {e}")
        else:
            st.info("Switch to 'options' product type for options history comparison.")

    with tab3:
        if df is None or df.empty:
            st.info("Fetch data in the Price Chart tab first.")
        else:
            indicators = st.multiselect("Indicators to Display", ["RSI", "MACD", "Stochastic", "ATR"], default=["RSI", "MACD"], key="ta_indicators")
            fig_main = render_candlestick(df, show_volume=False, height=350)
            st.plotly_chart(fig_main, width="stretch")

            for ind in indicators:
                if ind == "RSI":
                    rsi_period = st.slider("RSI Period", 5, 30, 14, key="rsi_period")
                    fig_ind = render_technical_subplot(df, "rsi", {"period": rsi_period}, height=180)
                elif ind == "MACD":
                    fig_ind = render_technical_subplot(df, "macd", height=200)
                elif ind == "Stochastic":
                    fig_ind = render_technical_subplot(df, "stochastic", height=180)
                elif ind == "ATR":
                    atr_vals = ta.atr(df["high"], df["low"], df["close"])
                    fig_ind = go.Figure()
                    fig_ind.add_trace(go.Scatter(x=df["datetime"], y=atr_vals, name="ATR(14)", line=dict(color="#FF6F00", width=1.5)))
                    fig_ind.update_layout(height=180, plot_bgcolor="#0d1117", paper_bgcolor="#161b22", font=dict(color="#e6edf3"), margin=dict(l=10, r=10, t=25, b=10), title=dict(text="ATR(14)", font=dict(size=12)))
                else:
                    continue
                st.plotly_chart(fig_ind, width="stretch")

            with st.expander("📍 Pivot Points (based on last bar)"):
                last = df.iloc[-1]
                pivots = ta.pivot_points(last["high"], last["low"], last["close"])
                pcols = st.columns(7)
                labels = ["S3", "S2", "S1", "P", "R1", "R2", "R3"]
                colors = ["#dc3545", "#e06c75", "#e5ac00", "#28a745", "#61afef", "#56b6c2", "#98c379"]
                for col, label, color in zip(pcols, labels, colors):
                    col.markdown(
                        f'<div style="text-align:center;color:{color};font-weight:700">{label}<br>₹{pivots[label]:,.2f}</div>',
                        unsafe_allow_html=True,
                    )

    with tab4:
        if df is None or df.empty:
            st.info("Fetch data in the Price Chart tab first.")
        else:
            st.markdown(f"**{len(df):,} rows** available for export.")
            csv_buf = io.StringIO()
            df.to_csv(csv_buf, index=False)
            st.download_button("📥 Download CSV", data=csv_buf.getvalue(), file_name=f"{instrument}_{interval}_{from_date}_{to_date}.csv", mime="text/csv")

            excel_buf = io.BytesIO()
            with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
                excel_safe_dataframe(df).to_excel(writer, sheet_name="OHLCV", index=False)
                ta_df = df.copy()
                ta_df["ema_20"] = ta.ema(df["close"], 20)
                ta_df["ema_50"] = ta.ema(df["close"], 50)
                ta_df["rsi_14"] = ta.rsi(df["close"])
                macd_l, sig_l, _ = ta.macd(df["close"])
                ta_df["macd"] = macd_l
                ta_df["macd_signal"] = sig_l
                ta_df["atr_14"] = ta.atr(df["high"], df["low"], df["close"])
                excel_safe_dataframe(ta_df).to_excel(writer, sheet_name="Technical Indicators", index=False)

            st.download_button(
                "📥 Download Excel (with indicators)",
                data=excel_buf.getvalue(),
                file_name=f"{instrument}_{interval}_{from_date}_{to_date}_with_ta.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            with st.expander("🗄️ Cache Statistics"):
                cache_stats = get_historical_cache().stats()
                st.json(cache_stats)
                if st.button("🗑️ Purge Expired Cache"):
                    n = get_historical_cache().purge_expired()
                    st.success(f"Purged {n} expired entries.")


def render_order_cost_preview(
    client: BreezeAPIClient,
    stock_code: str,
    exchange_code: str,
    product: str,
    order_type: str,
    price: float,
    action: str,
    quantity: int,
    expiry_date: str = "",
    right: str = "",
    strike_price: str = "",
    auto_fetch: bool = False,
    key_prefix: str = "preview",
) -> Optional[Dict]:
    """Render a pre-trade brokerage breakdown widget."""
    price_str = str(price) if order_type == "limit" and price > 0 else ""
    if exchange_code.strip().upper() == "NFO" and product.strip().lower() == "options" and not expiry_date:
        st.info("Select an expiry date to fetch the order cost estimate.")
        return None

    _, col_btn = st.columns([3, 1])
    with col_btn:
        fetch_preview = st.button("💰 Get Cost Estimate", key=f"{key_prefix}_btn") or auto_fetch

    if not fetch_preview:
        return None

    with st.spinner("Fetching cost estimate..."):
        resp = client.preview_order(
            stock_code=stock_code,
            exchange_code=exchange_code,
            product=product,
            order_type=order_type,
            price=price_str,
            action=action,
            quantity=str(quantity),
            expiry_date=expiry_date,
            right=right.lower() if right else "",
            strike_price=str(strike_price) if strike_price else "",
        )

    if not resp.get("success"):
        st.warning(f"Could not fetch cost estimate: {resp.get('message', 'Unknown')}")
        return None

    success = resp.get("data", {})
    if isinstance(success, dict) and "Success" in success:
        success = success["Success"]
    if not isinstance(success, dict):
        return None

    brokerage = float(success.get("brokerage", 0) or 0)
    stt = float(success.get("stt", 0) or 0)
    exchange_charges = float(success.get("exchange_turnover_charges", 0) or 0)
    stamp_duty = float(success.get("stamp_duty", 0) or 0)
    sebi = float(success.get("sebi_charges", 0) or 0)
    gst = float(success.get("gst", 0) or 0)
    total = float(success.get("total_brokerage", 0) or 0)

    order_value = price * quantity if price > 0 else 0
    net_value = order_value - total if action == "sell" else order_value + total

    st.markdown("""
    <style>
    .cost-preview { background:#1a1f2e; border:1px solid #30363d;
                    border-radius:8px; padding:1rem; margin:.5rem 0; }
    .cost-row { display:flex; justify-content:space-between;
                padding:3px 0; border-bottom:1px solid #30363d22; }
    .cost-total { font-weight:700; color:#388bfd; font-size:1.1rem;
                  border-top:2px solid #388bfd; padding-top:6px; margin-top:4px; }
    </style>
    """, unsafe_allow_html=True)

    order_value_pct = f" ({total/order_value*100:.2f}%)" if order_value > 0 else ""
    net_label = "Net Premium Received" if action == "sell" else "Net Cost (incl. charges)"

    st.markdown(f"""
    <div class="cost-preview">
      <div style="font-weight:700;margin-bottom:.5rem">💰 Order Cost Preview</div>
      <div class="cost-row"><span>Order Value</span><span>₹{order_value:,.2f}</span></div>
      <div class="cost-row"><span>Brokerage</span><span>₹{brokerage:,.2f}</span></div>
      <div class="cost-row"><span>STT</span><span>₹{stt:,.2f}</span></div>
      <div class="cost-row"><span>Exchange Charges</span><span>₹{exchange_charges:,.2f}</span></div>
      <div class="cost-row"><span>Stamp Duty</span><span>₹{stamp_duty:,.2f}</span></div>
      <div class="cost-row"><span>SEBI Charges</span><span>₹{sebi:,.2f}</span></div>
      <div class="cost-row"><span>GST (18%)</span><span>₹{gst:,.2f}</span></div>
      <div class="cost-row cost-total">
        <span>Total Charges</span>
        <span>₹{total:,.2f}{order_value_pct}</span>
      </div>
      <div class="cost-row" style="color:#28a745;font-weight:600">
        <span>{net_label}</span>
        <span>₹{net_value:,.2f}</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    return success


def render_gtt_order_cost_preview(
    entry_price: float,
    target_price: float,
    stoploss_price: float,
    quantity: int,
    lot_size: int,
) -> None:
    """Render P&L preview for a GTT trade before placement."""
    lots = quantity // lot_size if lot_size > 0 else 0
    entry_value = entry_price * quantity
    target_pnl = (entry_price - target_price) * quantity
    stop_pnl = (entry_price - stoploss_price) * quantity
    rr_ratio = abs(target_pnl / stop_pnl) if stop_pnl != 0 else 0

    st.markdown(
        """
        <style>
        .gtt-preview { background:#1a1f2e; border:1px solid #30363d;
                       border-radius:8px; padding:1rem; margin:.5rem 0; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.container():
        st.markdown('<div class="gtt-preview">', unsafe_allow_html=True)
        st.markdown("**📊 Trade P&L Preview**")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric(
            "Premium Collected",
            f"₹{entry_value:,.0f}",
            help=f"{lots} lot × ₹{entry_price:.2f} × {lot_size}",
        )
        color_target = "#28a745" if target_pnl > 0 else "#dc3545"
        pct_target = (abs(target_pnl) / entry_value * 100) if entry_value else 0
        pct_stop = (abs(stop_pnl) / entry_value * 100) if entry_value else 0
        col2.markdown(
            f'<div style="text-align:center"><small>Target Profit</small><br>'
            f'<span style="color:{color_target};font-size:1.3rem;font-weight:700">'
            f'₹{abs(target_pnl):,.0f}</span><br>'
            f'<small>{pct_target:.1f}% of premium</small></div>',
            unsafe_allow_html=True,
        )
        col3.markdown(
            f'<div style="text-align:center"><small>Max Loss (if stop hit)</small><br>'
            f'<span style="color:#dc3545;font-size:1.3rem;font-weight:700">'
            f'₹{abs(stop_pnl):,.0f}</span><br>'
            f'<small>{pct_stop:.1f}% of premium</small></div>',
            unsafe_allow_html=True,
        )
        col4.metric(
            "Risk:Reward",
            f"1:{rr_ratio:.2f}",
            delta="Good" if rr_ratio >= 0.4 else "Low",
            delta_color="normal" if rr_ratio >= 0.4 else "inverse",
        )
        st.markdown('</div>', unsafe_allow_html=True)


@error_handler
@require_auth
def page_gtt_orders():
    """GTT Orders management page."""
    st.markdown('<div class="page-header">⏰ GTT Orders (Good Till Triggered)</div>', unsafe_allow_html=True)

    from gtt_manager import GTTManager, GTTOrderRequest, GTTType, GTTLeg, GTTLegType, GTTStatus, validate_gtt_request

    client = get_client()
    if not client:
        return

    db = TradeDB()
    gtt_mgr = GTTManager(client, db)

    tab1, tab2, tab3 = st.tabs(["➕ Place GTT", "📋 Active GTTs", "📜 GTT History"])

    with tab1:
        st.markdown("**Create a new GTT order for automatic profit booking and stop-loss.**")
        gtt_type = st.radio("GTT Type", ["🎯 OCO (Entry + Target + Stop-Loss)", "📌 Single Leg (Standalone Trigger)"], horizontal=True, key="gtt_type_select")
        is_three_leg = "OCO" in gtt_type

        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            instrument = st.selectbox("Instrument", list(C.INSTRUMENTS.keys()), key="gtt_instrument")
            cfg = C.INSTRUMENTS[instrument]
        with col2:
            exchange = cfg.exchange
            expiry = st.selectbox("Expiry", C.get_next_expiries(instrument, count=6), key="gtt_expiry")
        with col3:
            right = st.selectbox("Right", ["call", "put"], key="gtt_right")

        col4, col5, col6 = st.columns(3)
        with col4:
            last_spot = st.session_state.get("last_spot", 22000)
            atm_guess = int(last_spot // cfg.strike_gap * cfg.strike_gap)
            strike = st.number_input("Strike Price", value=atm_guess, step=cfg.strike_gap, key="gtt_strike")
        with col5:
            lots = st.number_input("Lots", min_value=1, value=1, step=1, key="gtt_lots")
            quantity = lots * cfg.lot_size
            st.caption(f"Qty: {quantity} contracts")
        with col6:
            trade_date = st.date_input("Valid Till (trade_date)", value=date.today() + timedelta(days=7), key="gtt_trade_date")

        st.divider()

        if is_three_leg:
            st.markdown("**Entry Order:**")
            col7, col8, col9 = st.columns(3)
            with col7:
                entry_action = st.selectbox("Entry Action", ["sell", "buy"], key="gtt_entry_action")
            with col8:
                entry_price = st.number_input("Entry Price ₹", min_value=0.01, value=185.0, step=0.5, key="gtt_entry_price")
            with col9:
                entry_order_type = st.selectbox("Entry Order Type", ["limit", "market"], key="gtt_entry_type")

            st.markdown("**Target Leg (Profit Booking):**")
            col10, col11, col12 = st.columns(3)
            with col10:
                target_trigger = st.number_input("Target Trigger ₹", value=round(entry_price * 0.5, 1) if entry_action == "sell" else round(entry_price * 1.5, 1), step=0.5, key="gtt_target_trigger")
            with col11:
                target_limit = st.number_input("Target Limit ₹", value=target_trigger - 2.0, step=0.5, key="gtt_target_limit")
            with col12:
                target_action = "buy" if entry_action == "sell" else "sell"
                st.text_input("Target Action", value=target_action.upper(), disabled=True, key="gtt_target_action_disp")

            st.markdown("**Stop-Loss Leg:**")
            col13, col14, col15 = st.columns(3)
            with col13:
                sl_trigger = st.number_input("Stop-Loss Trigger ₹", value=round(entry_price * 2.0, 1) if entry_action == "sell" else round(entry_price * 0.5, 1), step=0.5, key="gtt_sl_trigger")
            with col14:
                sl_limit = st.number_input("Stop-Loss Limit ₹", value=sl_trigger + 5.0 if entry_action == "sell" else sl_trigger - 5.0, step=0.5, key="gtt_sl_limit")
            with col15:
                sl_action = "buy" if entry_action == "sell" else "sell"
                st.text_input("Stop-Loss Action", value=sl_action.upper(), disabled=True, key="gtt_sl_action_disp")

            with st.expander("🧮 Auto-Calculate Stops"):
                calc_method = st.radio("Calculation Method", ["% of Entry", "Fixed ₹", "Multiple of Premium"], horizontal=True, key="gtt_calc_method")
                if calc_method == "% of Entry":
                    target_pct = st.slider("Target %", 10, 80, 50, key="gtt_target_pct")
                    sl_pct = st.slider("Stop-Loss %", 50, 300, 100, key="gtt_sl_pct")
                    if st.button("Apply", key="gtt_apply_calc") and entry_action == "sell":
                        st.session_state["gtt_target_trigger"] = round(entry_price * (1 - target_pct / 100), 1)
                        st.session_state["gtt_sl_trigger"] = round(entry_price * (1 + sl_pct / 100), 1)
                        st.rerun()

            render_gtt_order_cost_preview(entry_price, target_trigger, sl_trigger, quantity, cfg.lot_size)

            order_details_legs = [
                GTTLeg(GTTLegType.TARGET, target_action, str(target_trigger), str(target_limit), "limit"),
                GTTLeg(GTTLegType.STOPLOSS, sl_action, str(sl_trigger), str(sl_limit), "limit"),
            ]

            req = GTTOrderRequest(
                exchange_code=exchange,
                stock_code=cfg.api_code,
                product="options",
                quantity=str(quantity),
                expiry_date=expiry,
                right=right,
                strike_price=str(int(strike)),
                gtt_type=GTTType.THREE_LEG,
                index_or_stock="index",
                trade_date=str(trade_date),
                fresh_order_action=entry_action,
                fresh_order_price=str(entry_price),
                fresh_order_type=entry_order_type,
                order_details=order_details_legs,
            )
        else:
            col16, col17, col18 = st.columns(3)
            with col16:
                sl_action_single = st.selectbox("Action", ["buy", "sell"], key="gtt_sl_action_single")
            with col17:
                sl_trigger_single = st.number_input("Trigger Price ₹", value=185.0, step=0.5, key="gtt_sl_trigger_single")
            with col18:
                sl_limit_single = st.number_input("Limit Price ₹", value=183.0, step=0.5, key="gtt_sl_limit_single")

            leg_type_str = st.selectbox("Leg Type", ["STOPLOSS", "PROFIT"], key="gtt_leg_type")
            leg_type = GTTLegType.STOPLOSS if leg_type_str == "STOPLOSS" else GTTLegType.TARGET

            req = GTTOrderRequest(
                exchange_code=exchange,
                stock_code=cfg.api_code,
                product="options",
                quantity=str(quantity),
                expiry_date=expiry,
                right=right,
                strike_price=str(int(strike)),
                gtt_type=GTTType.SINGLE,
                index_or_stock="index",
                trade_date=str(trade_date),
                order_details=[GTTLeg(leg_type, sl_action_single, str(sl_trigger_single), str(sl_limit_single))],
            )

        is_valid, err_msg = validate_gtt_request(req)
        if not is_valid:
            st.error(f"❌ Validation: {err_msg}")

        place_btn = st.button("✅ Place GTT Order", type="primary", disabled=not is_valid, key="gtt_place_btn")
        if place_btn and is_valid:
            with st.spinner("Placing GTT order..."):
                result = gtt_mgr.place_three_leg(req) if is_three_leg else gtt_mgr.place_single_leg(req)
            if result.get("success"):
                st.success("✅ GTT order placed successfully!")
                st.json(result.get("data", {}))
            else:
                st.error(f"❌ Failed: {result.get('message', 'Unknown error')}")

    with tab2:
        if st.button("🔄 Sync with Breeze", key="gtt_sync_btn"):
            with st.spinner("Syncing..."):
                n = gtt_mgr.sync_with_api("NFO")
            st.info(f"Sync complete: {n} status change(s)")

        active_gtts = gtt_mgr.get_active_gtts()
        if not active_gtts:
            st.info("No active GTT orders. Create one in the **Place GTT** tab.")
        else:
            for gtt in active_gtts:
                with st.expander(
                    f"{'OCO' if gtt.gtt_type == GTTType.THREE_LEG else 'Single'} | "
                    f"{gtt.stock_code} {gtt.strike} {gtt.right.upper()} | "
                    f"Entry: ₹{gtt.entry_price:.1f} | Target: ₹{gtt.target_trigger_price:.1f} | "
                    f"Stop: ₹{gtt.stoploss_trigger_price:.1f} | ID: {gtt.gtt_order_id[:8]}...",
                    expanded=False,
                ):
                    col_a, col_b, col_c, col_d = st.columns(4)
                    col_a.metric("Entry Price", f"₹{gtt.entry_price:.2f}")
                    col_b.metric("Target Trigger", f"₹{gtt.target_trigger_price:.2f}")
                    col_c.metric("Stop Trigger", f"₹{gtt.stoploss_trigger_price:.2f}")
                    col_d.metric("Qty", f"{gtt.quantity} ({gtt.quantity // max(cfg.lot_size,1)} lots)")
                    st.caption(f"Created: {gtt.created_at[:19]} | Valid till: {gtt.trade_date}")

                    if st.button("🗑️ Cancel", key=f"gtt_cancel_{gtt.gtt_order_id}"):
                        if st.session_state.get(f"confirm_cancel_{gtt.gtt_order_id}"):
                            result = gtt_mgr.cancel(gtt.gtt_order_id)
                            if result.get("success"):
                                st.success("GTT cancelled")
                                st.rerun()
                            else:
                                st.error(f"Cancel failed: {result.get('message')}")
                        else:
                            st.session_state[f"confirm_cancel_{gtt.gtt_order_id}"] = True
                            st.warning("Click Cancel again to confirm.")

    with tab3:
        all_gtts = gtt_mgr.get_all_gtts(limit=200)
        history_gtts = [g for g in all_gtts if g.status != GTTStatus.ACTIVE]
        if not history_gtts:
            st.info("No GTT history yet.")
        else:
            history_data = []
            for g in history_gtts:
                trigger_leg = g.trigger_leg or "—"
                if g.status == GTTStatus.TRIGGERED:
                    triggered_price = g.target_trigger_price if trigger_leg == "target" else g.stoploss_trigger_price
                    pnl_sign = 1 if trigger_leg == "target" else -1
                    pnl = pnl_sign * abs(g.entry_price - triggered_price) * g.quantity
                else:
                    pnl = None

                history_data.append({
                    "Status": g.status.value.upper(),
                    "Type": g.gtt_type.value,
                    "Instrument": f"{g.stock_code} {g.strike} {g.right.upper()}",
                    "Entry": f"₹{g.entry_price:.1f}",
                    "Target": f"₹{g.target_trigger_price:.1f}",
                    "Stop": f"₹{g.stoploss_trigger_price:.1f}",
                    "Triggered": trigger_leg.upper() if trigger_leg != "—" else "—",
                    "P&L": f"₹{pnl:,.0f}" if pnl is not None else "—",
                    "Created": g.created_at[:10],
                    "GTT ID": g.gtt_order_id[:12] + "...",
                })
            st.dataframe(pd.DataFrame(history_data), width="stretch", hide_index=True)

# ═══════════════════════════════════════════════════════════════
# PAGE: RISK MONITOR
# ═══════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_risk_monitor():
    page_header("🛡️ Risk Monitor")
    client = get_client()
    if not client:
        return

    if "risk_monitor" not in st.session_state:
        max_loss = _db.get_setting("max_portfolio_loss", C.DEFAULT_MAX_PORTFOLIO_LOSS)
        st.session_state.risk_monitor = RiskMonitor(
            api_client=client, poll_interval=15.0, max_portfolio_loss=max_loss)

    monitor: RiskMonitor = st.session_state.risk_monitor

    # ── Control row ───────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        if monitor.is_running():
            st.success("🟢 Monitor Running")
            if st.button("⏹️ Stop", width="stretch"):
                monitor.stop()
                st.rerun()
        else:
            st.warning("🔴 Monitor Stopped")
            if st.button("▶️ Start", type="primary", width="stretch"):
                monitor.start()
                st.rerun()
    stats = monitor.get_stats()
    c2.metric("Monitored", stats["positions"])
    c3.metric("Alerts", stats["alerts"])
    c4.metric("Poll Count", stats["poll_count"])
    c5.metric("Portfolio P&L", format_currency(stats["portfolio_pnl"]))

    if stats["portfolio_stop"]:
        danger_box("🚨 <b>PORTFOLIO STOP TRIGGERED!</b> Total loss has exceeded the portfolio limit.")

    # ── Portfolio limits config ───────────────────────────────
    with st.expander("⚙️ Portfolio Risk Limits"):
        cc1, cc2 = st.columns(2)
        max_loss = cc1.number_input("Max Portfolio Loss (₹)", value=float(
            _db.get_setting("max_portfolio_loss", C.DEFAULT_MAX_PORTFOLIO_LOSS)), step=5000.0)
        max_delta = cc2.number_input("Max Net Delta", value=float(
            _db.get_setting("max_delta", C.DEFAULT_MAX_DELTA)), step=10.0)
        if st.button("💾 Save Limits"):
            _db.set_setting("max_portfolio_loss", max_loss)
            _db.set_setting("max_delta", max_delta)
            monitor.set_portfolio_limits(max_loss, max_delta)
            st.success("✅ Limits updated")

    st.markdown("---")
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📍 Positions", "⚙️ Stop-Losses", "🧠 Smart Stops", "🚨 Alerts", "⏳ Expiry Autopilot"])

    with tab1:
        all_pos = get_cached_positions(client)
        opt_pos, _ = split_positions(all_pos or [])
        if not opt_pos:
            empty_state("📭", "No options to monitor")
        else:
            already = {m["id"] for m in monitor.get_monitored_summary()}
            for p in opt_pos:
                stock = p.get("stock_code", "")
                strike_val = safe_int(p.get("strike_price", 0))
                ot = C.normalize_option_type(p.get("right", ""))
                pt = detect_position_type(p)
                qty = abs(safe_int(p.get("quantity", 0)))
                avg = safe_float(p.get("average_price", 0))
                pid = f"{stock}_{strike_val}_{ot}"
                label = (f"{C.api_code_to_display(stock)} {strike_val} {ot} "
                         f"({pt.upper()} ×{qty}) — Avg ₹{avg:.2f}")
                c1, c2 = st.columns([4, 1])
                with c1:
                    st.markdown(f"{'✅' if pid in already else '⭕'} {label}")
                with c2:
                    if pid not in already:
                        if st.button("➕ Monitor", key=f"add_{pid}", width="stretch"):
                            monitor.add_position(pid, stock, p.get("exchange_code", ""),
                                                 p.get("expiry_date", ""), strike_val,
                                                 ot, pt, qty, avg)
                            _db.log_activity("MONITOR_ADD", f"Added {pid}")
                            st.success(f"✅ Monitoring {label}")
                            st.rerun()
                    else:
                        if st.button("🗑️ Remove", key=f"rm_{pid}", width="stretch"):
                            monitor.remove_position(pid)
                            st.rerun()

    with tab2:
        monitored = monitor.get_monitored_summary()
        if not monitored:
            empty_state("⚙️", "No positions being monitored",
                        "Add positions in the Positions tab")
        else:
            for m in monitored:
                status_icon = "🔴" if m["triggered"] else "🟢"
                lbl = (f"{status_icon} {C.api_code_to_display(m['stock'])} {m['strike']} "
                       f"{m['type']} ({m['pos'].upper()}) | Current ₹{m['current']:.2f} "
                       f"| P&L {format_currency(m['pnl'])}")
                with st.expander(lbl):
                    if m.get("triggered"):
                        danger_box("🚨 STOP HAS BEEN TRIGGERED!")
                    sc1, sc2, sc3 = st.columns(3)
                    with sc1:
                        st.markdown("**Fixed Stop-Loss**")
                        default_stop = m.get("stop") or m["avg"] * 1.5
                        stop_px = st.number_input("Stop Price ₹", value=float(default_stop),
                                                  min_value=0.01, step=0.5, key=f"sp_{m['id']}")
                        if st.button("Set Fixed Stop", key=f"ss_{m['id']}", width="stretch"):
                            monitor.set_stop_loss(m["id"], stop_px)
                            _db.log_activity("STOP_SET", f"₹{stop_px:.2f} on {m['id']}")
                            st.success(f"✅ Stop set at ₹{stop_px:.2f}")
                    with sc2:
                        st.markdown("**Trailing Stop**")
                        trail_pct = st.slider("Trail %", 10, 200, 50, 5, key=f"tr_{m['id']}")
                        if st.button("Set Trailing", key=f"trs_{m['id']}", width="stretch"):
                            monitor.set_trailing_stop(m["id"], trail_pct / 100.0)
                            _db.log_activity("TRAIL_SET", f"{trail_pct}% on {m['id']}")
                            st.success(f"✅ Trailing {trail_pct}% set")
                    with sc3:
                        st.markdown("**Current Config**")
                        if m.get("stop"):
                            st.caption(f"Fixed stop: ₹{m['stop']:.2f}")
                        if m.get("trail_pct"):
                            st.caption(f"Trailing: {m['trail_pct']*100:.0f}%")
                        st.caption(f"Avg: ₹{m['avg']:.2f} | DTE: {calculate_days_to_expiry(m.get('expiry',''))}")
                        if st.button("🗑️ Remove", key=f"rmm_{m['id']}", width="stretch"):
                            monitor.remove_position(m["id"])
                            st.rerun()

    with tab3:
        smart_rows = monitor.get_smart_stop_summary()
        if smart_rows:
            section("🧠 Smart Stops Status")
            out = []
            for row in smart_rows:
                out.append({
                    "Instrument": f"{C.api_code_to_display(row['stock'])} {row['strike']} {row['type']}",
                    "Position": row["pos"].upper(),
                    "Current ₹": f"{safe_float(row['current']):.2f}",
                    "Recommended Stop ₹": "—" if row["recommended_stop"] is None else f"{safe_float(row['recommended_stop']):.2f}",
                    "Auto Close": "YES" if row["auto_close"] else "NO",
                    "Reason": row["reason"] or "—",
                })
            st.dataframe(pd.DataFrame(out), hide_index=True, width="stretch")
        else:
            empty_state("🧠", "No smart-stop data yet", "Add and monitor positions first")

    with tab4:
        history = monitor.get_alert_history()
        db_alerts = _db.get_alerts(limit=50)
        if history or db_alerts:
            all_alerts = [{"Time": a.timestamp, "Level": a.level, "Category": a.category,
                           "Message": a.message, "Position": a.position_id}
                          for a in history]
            if all_alerts:
                df = pd.DataFrame(all_alerts)
                st.dataframe(df, hide_index=True, width="stretch")
                if st.button("✅ Acknowledge All"):
                    _db.acknowledge_alerts()
            if db_alerts:
                st.markdown("---")
                st.caption("Persistent Alert History")
                st.dataframe(pd.DataFrame(db_alerts), hide_index=True, width="stretch")
        else:
            empty_state("🔔", "No alerts", "Alerts appear when stops are triggered")

    with tab5:
        section("⏳ Expiry Day Autopilot")
        summary = monitor.get_monitored_summary()
        if not summary:
            st.info("No monitored positions for expiry autopilot.")
        else:
            autopilot = ExpiryDayAutopilot()
            enabled = st.toggle("Enable Expiry Autopilot", value=bool(_db.get_setting("expiry_autopilot_enabled", False)), key="expiry_autopilot_enabled")
            _db.set_setting("expiry_autopilot_enabled", bool(enabled))
            # Convert summary rows into lightweight position objects for evaluator.
            fake_positions = []
            for row in summary:
                fake_positions.append(
                    type("P", (), {"position_id": row["id"], "expiry": row.get("expiry", "")})()
                )
            eval_result = autopilot.evaluate(fake_positions, enabled=enabled)
            st.write(f"**Stage:** {eval_result['stage']}")
            if eval_result["message"]:
                st.info(eval_result["message"])
            exp_ids = eval_result.get("expiring_positions", [])
            st.write(f"Expiring positions today: **{len(exp_ids)}**")
            if exp_ids:
                st.dataframe(pd.DataFrame({"Position ID": exp_ids}), hide_index=True, width="stretch")

            if eval_result.get("should_auto_close") and exp_ids:
                confirm = st.checkbox("Final confirm: execute expiry auto-close now", key="expiry_autopilot_confirm")
                if confirm and st.button("Execute Expiry Auto-Close", key="expiry_autopilot_execute", type="primary"):
                    ok_count, fail_count = 0, 0
                    for row in summary:
                        if row["id"] not in exp_ids:
                            continue
                        close_action = "buy" if row["pos"] == "short" else "sell"
                        resp = client.place_order(
                            row["stock"],
                            row.get("exchange", "NFO"),
                            row.get("expiry", ""),
                            int(row["strike"]),
                            row["type"],
                            close_action,
                            int(row["qty"]),
                            "market",
                            0.0,
                        )
                        if resp.get("success"):
                            ok_count += 1
                        else:
                            fail_count += 1
                    if ok_count:
                        st.success(f"Auto-close completed for {ok_count} position(s).")
                    if fail_count:
                        st.error(f"Auto-close failed for {fail_count} position(s).")


# ═══════════════════════════════════════════════════════════════
# PAGE: WATCHLIST
# ═══════════════════════════════════════════════════════════════

@error_handler
@require_auth
def page_watchlist():
    page_header("👁️ Watchlist")
    client = get_client()
    if not client:
        return

    render_auto_refresh("watchlist")

    # ── Add to watchlist ──────────────────────────────────────
    with st.expander("➕ Add to Watchlist"):
        c1, c2, c3, c4, c5 = st.columns(5)
        wl_inst = c1.selectbox("Instrument", list(C.INSTRUMENTS.keys()), key="wl_inst")
        wl_cfg = C.get_instrument(wl_inst)
        wl_exp = c2.selectbox("Expiry", C.get_next_expiries(wl_inst, 6),
                              format_func=format_expiry_short, key="wl_exp")
        wl_ot = c3.radio("Type", ["CE", "PE"], horizontal=True, key="wl_ot")
        wl_strike = c4.number_input("Strike", min_value=wl_cfg.min_strike,
                                    max_value=wl_cfg.max_strike,
                                    value=int((wl_cfg.min_strike + wl_cfg.max_strike) // 2),
                                    step=wl_cfg.strike_gap, key="wl_strike")
        with c5:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("➕ Add", width="stretch"):
                sym = f"{wl_inst} {int(wl_strike)} {wl_ot} {format_expiry_short(wl_exp)}"
                ok = _db.add_watchlist_item(sym, wl_inst, int(wl_strike), wl_ot, wl_exp)
                if ok:
                    st.success(f"✅ Added: {sym}")
                    st.rerun()
                else:
                    st.error("Failed to add (may already exist)")

    # ── Display watchlist with live quotes ────────────────────
    items = _db.get_watchlist()
    if not items:
        empty_state("👁️", "Watchlist is empty", "Add options above to track them")
        return

    section("📊 Live Quotes")
    rows = []
    for item in items:
        row = {"ID": item["id"], "Symbol": item["symbol"],
               "Instrument": item["instrument"], "Strike": item["strike"],
               "Type": item["option_type"], "Expiry": format_expiry_short(item["expiry"]),
               "DTE": calculate_days_to_expiry(item["expiry"]),
               "LTP ₹": "—", "Bid ₹": "—", "Ask ₹": "—", "IV%": "—", "OI": "—"}
        try:
            cfg = C.get_instrument(item["instrument"])
            r = client.get_option_quote(cfg.api_code, cfg.exchange, item["expiry"],
                                  item["strike"], item["option_type"])
            if r["success"]:
                items_resp = APIResponse(r).items
                if items_resp:
                    d = items_resp[0]
                    ltp = safe_float(d.get("ltp", 0))
                    dte = calculate_days_to_expiry(item["expiry"])
                    tte = max(dte / C.DAYS_PER_YEAR, 0.001)
                    iv = estimate_implied_volatility(ltp, item["strike"], item["strike"],
                                                    tte, item["option_type"]) * 100 if ltp > 0 else 0
                    row.update({
                        "LTP ₹": f"{ltp:.2f}",
                        "Bid ₹": f"{safe_float(d.get('best_bid_price',0)):.2f}",
                        "Ask ₹": f"{safe_float(d.get('best_offer_price',0)):.2f}",
                        "IV%": f"{iv:.1f}",
                        "OI": format_number(safe_float(d.get("open_interest", 0)))
                    })
        except Exception:
            pass
        rows.append(row)

    df = pd.DataFrame(rows)
    display_cols = [c for c in df.columns if c != "ID"]
    st.dataframe(df[display_cols], hide_index=True, width="stretch")

    # Remove button
    rm_id = st.selectbox("Remove item:", [f"{r['ID']}: {r['Symbol']}" for r in rows], key="wl_rm")
    if st.button("🗑️ Remove from Watchlist"):
        item_id = int(rm_id.split(":")[0])
        _db.remove_watchlist_item(item_id)
        st.success("Removed")
        st.rerun()

    export_to_csv(df[display_cols], "watchlist.csv")


def _load_alert_config_from_db() -> AlertConfig:
    data = _db.get_setting("alert_config", {}) or {}
    if isinstance(data, dict):
        try:
            return AlertConfig(**data)
        except Exception:
            pass
    return AlertConfig()


def _get_alert_dispatcher() -> AlertDispatcher:
    if "alert_dispatcher" not in st.session_state:
        st.session_state.alert_dispatcher = AlertDispatcher(_load_alert_config_from_db())
    return st.session_state.alert_dispatcher


def render_alerts_settings_tab(
    alert_dispatcher: AlertDispatcher,
    alert_config: AlertConfig,
) -> AlertConfig:
    """Render alerts configuration and return updated config."""
    st.markdown("#### 🔔 Alert Notifications")

    with st.expander("📱 Telegram Alerts", expanded=alert_config.telegram_enabled):
        tg_enabled = st.toggle("Enable Telegram", value=alert_config.telegram_enabled, key="tg_enabled")
        if tg_enabled:
            tg_token = st.text_input("Bot Token", value=alert_config.telegram_bot_token, type="password", key="tg_token")
            tg_chat = st.text_input("Chat ID", value=alert_config.telegram_chat_id, key="tg_chat")
            if st.button("🧪 Test Telegram", key="tg_test"):
                test_dispatcher = TelegramDispatcher(tg_token, tg_chat)
                ok = test_dispatcher.send("✅ Breeze PRO: Telegram connected!")
                st.success("Telegram working!") if ok else st.error("Telegram test failed.")
        else:
            tg_token = alert_config.telegram_bot_token
            tg_chat = alert_config.telegram_chat_id

    with st.expander("📧 Email Alerts", expanded=alert_config.email_enabled):
        em_enabled = st.toggle("Enable Email", value=alert_config.email_enabled, key="em_enabled")
        if em_enabled:
            em_host = st.text_input("SMTP Host", value=alert_config.email_smtp_host, key="em_host")
            em_port = st.number_input("SMTP Port", value=alert_config.email_smtp_port, min_value=1, max_value=65535, key="em_port")
            em_user = st.text_input("Email (from)", value=alert_config.email_username, key="em_user")
            em_pass = st.text_input("App Password", value=alert_config.email_password, type="password", key="em_pass")
            em_to = st.text_input("Email (to)", value=alert_config.email_to, key="em_to")
            if st.button("🧪 Test Email", key="em_test"):
                test_email = EmailDispatcher(em_host, int(em_port), em_user, em_pass, em_to)
                ok = test_email.send("[Breeze PRO] Alert Test", "<p>✅ Email alerts are configured correctly.</p>")
                st.success("Email working!") if ok else st.error("Email test failed.")
        else:
            em_host = alert_config.email_smtp_host
            em_port = alert_config.email_smtp_port
            em_user = alert_config.email_username
            em_pass = alert_config.email_password
            em_to = alert_config.email_to

    with st.expander("🔗 Webhook Alerts"):
        wh_enabled = st.toggle("Enable Webhook", value=alert_config.webhook_enabled, key="wh_enabled")
        wh_url = st.text_input("Webhook URL", value=alert_config.webhook_url, key="wh_url")
        wh_secret = st.text_input("Webhook Secret (HMAC)", value=alert_config.webhook_secret, type="password", key="wh_secret")

    with st.expander("💬 Discord Alerts", expanded=alert_config.discord_enabled):
        dc_enabled = st.toggle("Enable Discord", value=alert_config.discord_enabled, key="dc_enabled")
        dc_url = st.text_input("Discord Webhook URL", value=alert_config.discord_webhook_url, key="dc_url")

    with st.expander("🟢 WhatsApp Alerts", expanded=alert_config.whatsapp_enabled):
        wa_enabled = st.toggle("Enable WhatsApp", value=alert_config.whatsapp_enabled, key="wa_enabled")
        wa_to = st.text_input("WhatsApp To", value=alert_config.whatsapp_to, key="wa_to")
        wa_from = st.text_input("Twilio WhatsApp From", value=alert_config.whatsapp_from, key="wa_from")
        tw_sid = st.text_input("Twilio Account SID", value=alert_config.twilio_account_sid, key="wa_sid")
        tw_token = st.text_input("Twilio Auth Token", value=alert_config.twilio_auth_token, type="password", key="wa_token")

    st.markdown("**Alert Template**")
    tpl = st.text_area(
        "Template",
        value=alert_config.alert_template,
        help="Use tokens like {level} {title} {body} {symbol} {strike} {pnl}",
        key="alert_template_text",
    )
    alert_sound = st.checkbox("Enable Browser Alert Sound", value=_db.get_setting("alert_sound_enabled", False), key="alert_sound_enabled")
    if alert_sound:
        components.html(
            """
            <audio id="breeze-alert-tone" preload="auto">
              <source src="https://actions.google.com/sounds/v1/alarms/beep_short.ogg" type="audio/ogg">
            </audio>
            <script>
              const a = document.getElementById('breeze-alert-tone');
              if (a) { a.play().catch(()=>{}); }
            </script>
            """,
            height=0,
        )

    st.divider()
    st.markdown("**What to alert on:**")
    al_fill = st.checkbox("Order fills", value=alert_config.alert_on_fill, key="al_fill")
    al_sl = st.checkbox("Stop-loss breaches", value=alert_config.alert_on_stop_loss, key="al_sl")
    al_gtt = st.checkbox("GTT triggers", value=alert_config.alert_on_gtt_trigger, key="al_gtt")
    al_margin = st.checkbox("Low margin warnings", value=alert_config.alert_on_margin_warning, key="al_margin")
    al_err = st.checkbox("API connection errors", value=alert_config.alert_on_errors, key="al_err")

    new_cfg = AlertConfig(
        telegram_enabled=tg_enabled,
        telegram_bot_token=tg_token if tg_enabled else alert_config.telegram_bot_token,
        telegram_chat_id=tg_chat if tg_enabled else alert_config.telegram_chat_id,
        email_enabled=em_enabled,
        email_smtp_host=em_host,
        email_smtp_port=int(em_port),
        email_username=em_user,
        email_password=em_pass,
        email_to=em_to,
        webhook_enabled=wh_enabled,
        webhook_url=wh_url if wh_enabled else alert_config.webhook_url,
        webhook_secret=wh_secret,
        discord_enabled=dc_enabled,
        discord_webhook_url=dc_url if dc_enabled else alert_config.discord_webhook_url,
        whatsapp_enabled=wa_enabled,
        whatsapp_to=wa_to,
        whatsapp_from=wa_from,
        twilio_account_sid=tw_sid,
        twilio_auth_token=tw_token,
        alert_template=tpl,
        alert_on_fill=al_fill,
        alert_on_stop_loss=al_sl,
        alert_on_gtt_trigger=al_gtt,
        alert_on_margin_warning=al_margin,
        alert_on_errors=al_err,
    )

    if st.button("💾 Save Alert Settings", type="primary", key="save_alert_cfg"):
        _db.set_setting("alert_config", new_cfg.__dict__)
        _db.set_setting("alert_sound_enabled", bool(alert_sound))
        alert_dispatcher.update_config(new_cfg)
        st.success("✅ Alert settings saved")

    return new_cfg


def render_totp_section() -> None:
    """Display TOTP generator tool and auto-login helper in Settings."""
    st.markdown("#### 🔐 TOTP Auto-Login")
    st.info("Enter your ICICI Direct TOTP base32 secret to auto-generate OTPs.")
    totp_secret = st.text_input(
        "TOTP Secret (base32)",
        type="password",
        value=st.session_state.get("totp_secret", ""),
        key="totp_secret_input",
    )
    if totp_secret:
        st.session_state["totp_secret"] = totp_secret
        try:
            current_otp = generate_totp(totp_secret)
            remaining = 30 - (int(time.time()) % 30)
            st.success(f"Current OTP: **{current_otp}** (valid for {remaining}s)")
            st.caption("This OTP refreshes every 30 seconds.")
        except ValueError as e:
            st.error(f"Invalid TOTP secret: {e}")


def render_account_switcher(db: TradeDB) -> None:
    """Account profile manager in Settings."""
    profile_db = AccountProfileDB(db)
    master_password = st.text_input(
        "Master Password (for encrypted profiles)",
        type="password",
        value=st.session_state.get("master_password", ""),
        key="master_password_input",
    )
    if master_password:
        st.session_state["master_password"] = master_password
    mgr = None
    if master_password:
        try:
            mgr = MultiAccountManager(master_password)
            migrated = mgr.ensure_profiles_encrypted()
            if migrated:
                st.success(f"Migrated {migrated} legacy plaintext profile(s) to encrypted storage.")
        except Exception as exc:
            st.warning(f"Encrypted profile manager unavailable: {exc}")
    else:
        st.info("Master password is required for encrypted account profile access.")

    st.markdown("#### 👤 Account Profiles")
    profiles = profile_db.get_profiles()
    active = profile_db.get_active_profile()

    if profiles:
        for p in profiles:
            name = p["profile_name"]
            is_active = name == (active or {}).get("profile_name")
            col1, col2, col3 = st.columns([3, 1, 1])
            col1.markdown(f"{'🟢 **' if is_active else ''}{name}{' (active)**' if is_active else ''}")
            with col2:
                if (not is_active) and st.button("Switch", key=f"switch_{name}"):
                    profile_db.set_active(name)
                    _cleanup_session()
                    st.success(f"Switched to {name}. Re-login required.")
                    st.rerun()
            with col3:
                if st.button("🗑️ Delete", key=f"del_{name}"):
                    deleting_active = is_active
                    profile_db.delete_profile(name)
                    if deleting_active:
                        _cleanup_session()
                    st.rerun()

    st.divider()
    with st.expander("➕ Add New Account Profile"):
        new_name = st.text_input("Profile Name", key="new_profile_name")
        new_key = st.text_input("API Key", type="password", key="new_api_key")
        new_secret = st.text_input("API Secret", type="password", key="new_api_secret")
        new_totp = st.text_input("TOTP Secret (optional)", type="password", key="new_totp")
        if st.button("Save Profile", key="save_profile_btn"):
            if new_name and new_key:
                if not mgr:
                    st.error("Master password required. Profile not saved.")
                    return
                mgr.add_profile(
                    AccountProfile(
                        profile_id="",
                        display_name=new_name,
                        api_key=new_key,
                        api_secret=new_secret,
                        totp_secret=new_totp,
                    )
                )
                if not active:
                    profile_db.set_active(new_name)
                st.success(f"Profile '{new_name}' saved.")
                st.rerun()
            else:
                st.error("Profile name and API key are required.")


def render_paper_trading_section(client: Optional[BreezeAPIClient]) -> None:
    st.markdown("#### 📄 Paper Trading Mode")
    if "paper_engine" not in st.session_state and client:
        st.session_state.paper_engine = PaperTradingEngine(client)
    engine: Optional[PaperTradingEngine] = st.session_state.get("paper_engine")
    enabled = bool(st.session_state.get("paper_trading_enabled", False))

    new_enabled = st.toggle("Enable Paper Trading", value=enabled, key="paper_mode_toggle")
    if new_enabled != enabled:
        if new_enabled:
            if engine and client:
                if "live_place_order_fn" not in st.session_state:
                    st.session_state.live_place_order_fn = client.place_order
                client.place_order = engine.place_order  # intercept live place_order calls
                engine.enable()
                st.session_state.paper_trading_enabled = True
                st.success("Paper mode enabled. Live orders will be intercepted.")
        else:
            confirm = st.checkbox("Confirm switch back to LIVE trading", key="paper_to_live_confirm")
            if confirm:
                if engine:
                    engine.disable()
                if client and st.session_state.get("live_place_order_fn"):
                    client.place_order = st.session_state.live_place_order_fn
                st.session_state.paper_trading_enabled = False
                st.success("Live mode restored.")
            else:
                st.warning("Please confirm before switching to live mode.")

    if engine:
        summary = engine.get_paper_summary()
        c1, c2, c3 = st.columns(3)
        c1.metric("Open Positions", summary.get("open_positions", 0))
        c2.metric("Filled Orders", summary.get("filled_orders", 0))
        c3.metric("Realized P&L", f"₹{summary.get('realized_pnl', 0):,.2f}")
        if st.button("Reset Paper Data", key="paper_reset_btn"):
            engine.reset()
            st.success("Paper trading data reset")


def render_funds_management_tab(client: BreezeAPIClient) -> None:
    """Render the Funds Management sub-tab within Settings."""
    st.markdown("#### 💰 Fund Transfer Between Segments")
    st.warning(
        "⚠️ Fund transfers are real operations and cannot be undone. "
        "Double-check all values before confirming."
    )

    with st.form("fund_transfer_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            txn_type = st.selectbox("Type", ["Deposit", "Withdrawal"], key="ft_type")
        with col2:
            amount = st.number_input(
                "Amount ₹",
                min_value=1.0,
                value=10000.0,
                step=1000.0,
                key="ft_amount",
            )
        with col3:
            segment = st.selectbox("Segment", ["Equity", "FNO", "Commodity"], key="ft_segment")

        st.caption("Deposit: moves funds INTO segment. Withdrawal: moves funds OUT.")
        confirm = st.checkbox(f"I confirm: {txn_type} ₹{amount:,.0f} to/from {segment}")
        submitted = st.form_submit_button("Transfer Funds", type="primary")

        if submitted and confirm:
            resp = client.set_funds(txn_type, str(amount), segment)
            if resp.get("success"):
                st.success(f"✅ Fund transfer successful: {txn_type} ₹{amount:,.0f}")
            else:
                st.error(f"❌ Failed: {resp.get('message')}")
        elif submitted and not confirm:
            st.warning("Please check the confirmation checkbox.")


def render_tax_export_tab(db: TradeDB) -> None:
    """Render tax export actions in Settings."""
    st.markdown("#### 🧾 Tax Export")
    fy = st.selectbox("Financial Year", ["2025-26", "2024-25", "2023-24"], key="tax_fy")
    fmt = st.radio("Format", ["csv", "excel"], horizontal=True, key="tax_fmt")

    if st.button("📥 Generate Tax Export", key="tax_export_btn"):
        data = export_trades_for_tax(db, fy, fmt)
        if not data:
            st.warning("No trades found for this financial year.")
            return
        ext = "csv" if fmt == "csv" else "xlsx"
        mime = "text/csv" if fmt == "csv" else (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        st.download_button(
            f"⬇️ Download {fy} Trade Report",
            data=data,
            file_name=f"breeze_trades_{fy}.{ext}",
            mime=mime,
        )




@error_handler
def page_paper_trading():
    page_header("📄 Paper Trading")
    render_paper_trading_section(get_client())


# ═══════════════════════════════════════════════════════════════
# PAGE: SETTINGS
# ═══════════════════════════════════════════════════════════════

@error_handler
def page_settings():
    page_header("⚙️ Settings")

    t1, t2, t3, t4, t5, t6 = st.tabs(["🎛️ Trading", "🛡️ Risk Limits", "🔔 Alerts", "🗄️ Database", "📅 Holiday Calendar", "ℹ️ System Info"])

    with t1:
        section("Trading Preferences")
        settings_tab1, settings_tab2, settings_tab3, settings_tab4, settings_tab5 = st.tabs([
            "⚙️ Trading", "💰 Funds", "🧾 Tax Export", "🔐 TOTP", "👤 Accounts"
        ])

        with settings_tab1:
            c1, c2 = st.columns(2)
            with c1:
                default_order = st.selectbox(
                    "Default Order Type",
                    ["Market", "Limit"],
                    index=0 if _db.get_setting("default_order_type", "Market") == "Market" else 1,
                )
                default_lots = st.number_input(
                    "Default Lots", min_value=1, value=int(_db.get_setting("default_lots", 1))
                )
                require_ack = st.checkbox(
                    "Require confirmation for orders", value=_db.get_setting("require_ack", True)
                )
            with c2:
                auto_sl = st.checkbox("Auto stop-loss after sell", value=_db.get_setting("auto_sl", False))
                voice_confirm = st.checkbox("🔊 Voice Confirmations", value=_db.get_setting("voice_confirmations", False))
                sl_mult = st.slider(
                    "Default SL multiplier", 1.5, 5.0, float(_db.get_setting("sl_multiplier", 2.0)), 0.5
                )
                max_lots_per_order = st.number_input(
                    "Max Lots Per Order", min_value=1, max_value=1000, value=int(_db.get_setting("max_lots", 100))
                )

            if st.button("💾 Save Trading Settings", type="primary"):
                _db.set_setting("default_order_type", default_order)
                _db.set_setting("default_lots", default_lots)
                _db.set_setting("require_ack", require_ack)
                _db.set_setting("auto_sl", auto_sl)
                _db.set_setting("voice_confirmations", voice_confirm)
                _db.set_setting("sl_multiplier", sl_mult)
                _db.set_setting("max_lots", max_lots_per_order)
                st.success("✅ Settings saved")

        with settings_tab2:
            client = get_client()
            if client and client.is_connected():
                render_funds_management_tab(client)
            else:
                st.info("Connect to Breeze API to use fund transfer operations.")

        with settings_tab3:
            render_tax_export_tab(_db)

        with settings_tab4:
            render_totp_section()

        with settings_tab5:
            render_account_switcher(_db)
            render_paper_trading_section(get_client())

    with t2:
        section("Risk Limits")
        c1, c2 = st.columns(2)
        with c1:
            max_portfolio_loss = c1.number_input(
                "Max Portfolio Loss (₹)", min_value=1000.0,
                value=float(_db.get_setting("max_portfolio_loss", C.DEFAULT_MAX_PORTFOLIO_LOSS)),
                step=5000.0)
            margin_warn = c1.slider("Margin Warning %", 50, 90,
                                    int(_db.get_setting("margin_warn_pct", C.DEFAULT_MARGIN_WARNING_PCT)))
        with c2:
            max_delta = c2.number_input("Max Net Delta", min_value=0.0,
                                         value=float(_db.get_setting("max_delta", C.DEFAULT_MAX_DELTA)),
                                         step=10.0)
            margin_crit = c2.slider("Margin Critical %", 75, 100,
                                     int(_db.get_setting("margin_crit_pct", C.DEFAULT_MARGIN_CRITICAL_PCT)))

        if st.button("💾 Save Risk Settings", type="primary"):
            _db.set_setting("max_portfolio_loss", max_portfolio_loss)
            _db.set_setting("max_delta", max_delta)
            _db.set_setting("margin_warn_pct", margin_warn)
            _db.set_setting("margin_crit_pct", margin_crit)
            monitor = st.session_state.get("risk_monitor")
            if monitor:
                monitor.set_portfolio_limits(max_portfolio_loss, max_delta)
            st.success("✅ Risk limits updated")

    with t3:
        section("Alerting")
        dispatcher = _get_alert_dispatcher()
        cfg = _load_alert_config_from_db()
        render_alerts_settings_tab(dispatcher, cfg)

        st.markdown("---")
        st.markdown("**Recent alert dispatch history**")
        hist_page_size = st.selectbox("History Size", [20, 50, 100], index=2, key="alert_hist_size")
        hist = dispatcher.get_history(limit=int(hist_page_size))
        if hist:
            st.dataframe(pd.DataFrame(hist), hide_index=True, width="stretch")
        else:
            st.caption("No dispatched alerts yet.")

    with t4:
        section("Database")
        stats = _db.get_db_stats()
        c1, c2, c3 = st.columns(3)
        for i, (tbl, cnt) in enumerate(stats.items()):
            [c1, c2, c3][i % 3].metric(tbl.replace("_", " ").title(), cnt)

        st.markdown("---")
        col1, col2 = st.columns(2)
        if col1.button("🗜️ Vacuum (Optimize DB)"):
            _db.vacuum()
            st.success("✅ Database optimized")

        if col2.button("🗑️ Clear Activity Log (> 90 days)", type="secondary"):
            st.warning("This will delete old activity logs")

        # Export full database
        all_trades = _db.get_trades(limit=10000)
        all_activity = _db.get_activities(limit=10000)
        all_alerts = _db.get_alerts(limit=10000)
        if st.button("📥 Export Full Database to Excel"):
            export_to_excel({
                "Trades": pd.DataFrame(all_trades),
                "Activity": pd.DataFrame(all_activity),
                "Alerts": pd.DataFrame(all_alerts),
                "PnL History": pd.DataFrame(_db.get_pnl_history(365)),
            }, "breeze_trader_export.xlsx")

    with t5:
        section("📅 NSE Holiday Calendar")

        status = _hc.get_status()

        # ── Status row ─────────────────────────────────────────────────────
        st.markdown("##### ⚡ Live Calendar Status")
        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("Holidays in Cache", status["total_holidays_in_memory"])
        col_b.metric(
            "Last NSE Fetch",
            f"{status['last_fetch_age_hours']}h ago"
            if status["last_fetch_age_hours"] is not None else "Never",
            delta="✅ OK" if status["last_fetch_ok"] else "⚠️ Fallback",
            delta_color="normal" if status["last_fetch_ok"] else "inverse",
        )
        col_c.metric("Cached Years", str(status["loaded_years"] or "None"))
        col_d.metric("API Refreshes", status["fetch_count"])

        if not status["last_fetch_ok"]:
            st.warning(
                "⚠️ Last NSE API fetch **failed** — the app is using the hardcoded fallback "
                "holiday set.  Click **Refresh Now** to retry, or check network connectivity."
            )
        else:
            st.success(
                f"✅ Holiday calendar is live (fetched from NSE API, "
                f"refreshes every {status['cache_max_age_hours']}h automatically)."
            )

        st.caption(f"Source: `{status['nse_api_url']}`   •   Cache DB: `{status['db_path']}`")

        # ── Manual refresh button ──────────────────────────────────────────
        st.markdown("---")
        c_btn, c_msg = st.columns([1, 3])
        with c_btn:
            if st.button("🔄 Refresh Now (from NSE)", type="primary", width="stretch"):
                with st.spinner("Fetching holidays from NSE API…"):
                    count, ok = _hc.force_refresh()
                if ok:
                    st.success(f"✅ Fetched & cached {count} holidays from NSE API.")
                else:
                    st.error(
                        "❌ NSE API fetch failed.  Hardcoded fallback is active.  "
                        "Check internet connectivity or try again later."
                    )
                st.rerun()
        with c_msg:
            st.info(
                "The calendar refreshes **automatically** every 24 hours.  "
                "Use this button only if you want to pull today's NSE bulletin immediately "
                "(e.g. after NSE announces a new ad-hoc holiday)."
            )

        # ── Year browser ──────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("##### 📆 Browse Holiday Calendar")

        from datetime import date as _dt_date
        current_year = _dt_date.today().year
        year_options = list(range(current_year - 1, current_year + 4))
        selected_year = st.selectbox(
            "Select Year", year_options,
            index=year_options.index(current_year),
            key="hc_year_select"
        )

        holidays_dict = _hc.get_holidays_for_year(selected_year)

        if holidays_dict:
            rows = []
            for iso_date in sorted(holidays_dict.keys()):
                try:
                    d_obj = _dt_date.fromisoformat(iso_date)
                    weekday = d_obj.strftime("%A")
                except Exception:
                    weekday = ""
                desc = holidays_dict[iso_date] or "—"
                source_tag = "📡 NSE API" if "(fallback)" not in desc else "📋 Fallback"
                rows.append({
                    "Date": iso_date,
                    "Day": weekday,
                    "Holiday": desc.replace("(fallback) ", "").strip(),
                    "Source": source_tag,
                })
            st.dataframe(
                pd.DataFrame(rows),
                hide_index=True,
                width="stretch",
                column_config={
                    "Date":    st.column_config.DateColumn("Date", format="DD MMM YYYY"),
                    "Day":     st.column_config.TextColumn("Day of Week"),
                    "Holiday": st.column_config.TextColumn("Holiday Name"),
                    "Source":  st.column_config.TextColumn("Source"),
                }
            )
            st.caption(f"Total: **{len(rows)} trading holidays** for {selected_year}")
        else:
            st.info(
                f"No holidays loaded for {selected_year} yet.  "
                "Click **Refresh Now** above to fetch from NSE, or wait for the next "
                "automatic refresh."
            )

        # ── How it works ──────────────────────────────────────────────────
        with st.expander("ℹ️ How the Holiday Calendar Works"):
            st.markdown("""
**Dynamic fetching (no manual updates needed)**

The holiday calendar is fetched automatically from the NSE official API:
```
https://www.nseindia.com/api/holiday-master?type=trading
```

**Refresh policy:**
- On app startup: calendar is loaded from SQLite cache (fast, no network call)
- When a year is missing from cache: NSE API is called immediately
- Every 24 hours: cache is considered stale and refreshed in the background
- Manual refresh: click the **Refresh Now** button above

**Fallback behaviour:**
If the NSE API is unreachable (network error, Streamlit Cloud egress block, NSE maintenance):
- The app silently falls back to the **hardcoded** `NSE_HOLIDAYS_2025_2026` set in `app_config.py`
- All expiry calculations, market status, and holiday advisories continue working
- The fallback is updated whenever a new version of the code is deployed

**Coverage:**
- FO (Futures & Options) holidays are used for expiry adjustments
- CM (Cash Market) holidays are also merged in, so no holiday is ever missed
- Both NSE and BSE instruments use this calendar

**Expiry adjustment rule (NSE circular):**
If a natural expiry date falls on a holiday → expiry is moved to the **previous trading day**.
""")

    with t6:
        section("System Information")
        info_items = {
            "App Version": "v10.0 PRO",
            "Python": "3.x",
            "Database": str(_db._db_path),
            "Session Timeout": f"{C.SESSION_TIMEOUT_SECONDS // 3600} hours",
            "Max Lots": str(C.MAX_LOTS_PER_ORDER),
            "Cache TTL (OC)": f"{C.OC_CACHE_TTL_SECONDS}s",
            "Risk Free Rate": f"{C.RISK_FREE_RATE * 100:.1f}%",
        }
        for k, v in info_items.items():
            st.markdown(f"**{k}:** `{v}`")

        if SessionState.is_authenticated():
            dur = SessionState.get_login_duration()
            st.markdown(f"**Session Duration:** `{dur or 'N/A'}`")
            is_stale = SessionState.is_session_stale()
            is_exp = SessionState.is_session_expired()
            st.markdown(f"**Session Status:** {'🔴 Expired' if is_exp else '⚠️ Aging' if is_stale else '✅ Active'}")


# ═══════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════

# ── Populate PAGES with actual functions now that all are defined ─────────
PAGES["🏠 Dashboard"] = page_dashboard
PAGES["⛓️ Option Chain"] = page_option_chain
PAGES["💸 Sell Options"] = page_sell_options
PAGES["❌ Square Off"] = page_square_off
PAGES["📋 Orders & Trades"] = page_orders_trades
PAGES["💼 Positions"] = page_positions
PAGES["📊 Historical Data"] = page_historical_data
PAGES["📈 Futures Trading"] = page_futures_trading
PAGES["⏰ GTT Orders"] = page_gtt_orders
PAGES["🧠 Strategy Builder"] = page_strategy_builder
PAGES["🔬 Analytics"] = page_analytics
PAGES["🚨 Risk Monitor"] = page_risk_monitor
PAGES["👁️ Watchlist"] = page_watchlist
PAGES["📄 Paper Trading"] = page_paper_trading
PAGES["⚙️ Settings"] = page_settings

PAGE_FN = {
    "🏠 Dashboard": page_dashboard,
    "⛓️ Option Chain": page_option_chain,
    "💸 Sell Options": page_sell_options,
    "❌ Square Off": page_square_off,
    "📋 Orders & Trades": page_orders_trades,
    "💼 Positions": page_positions,
    "📊 Historical Data": page_historical_data,
    "📈 Futures Trading": page_futures_trading,
    "⏰ GTT Orders": page_gtt_orders,
    "🧠 Strategy Builder": page_strategy_builder,
    "🔬 Analytics": page_analytics,
    "🚨 Risk Monitor": page_risk_monitor,
    "👁️ Watchlist": page_watchlist,
    "📄 Paper Trading": page_paper_trading,
    "⚙️ Settings": page_settings,
}


def main():
    try:
        SessionState.initialize()
        st.markdown(BREEZE_PRO_CSS, unsafe_allow_html=True)
        st.markdown(RESPONSIVE_CSS, unsafe_allow_html=True)
        components.html(KEYBOARD_SHORTCUTS_JS, height=0)

        if not SessionState.is_authenticated():
            render_sidebar()
            render_alert_banners()
            st.markdown("---")
            page_dashboard()
            return

        client = get_client()
        if client and "live_feed_initialized" not in st.session_state:
            mgr = lf.initialize_live_feed(client.breeze)
            st.session_state["live_feed_initialized"] = True
            st.session_state["live_feed_manager"] = mgr

        if client and "app_warmup" not in st.session_state:
            warmup = AppWarmupManager(client)
            warmup.start()
            st.session_state["app_warmup"] = warmup

        if "paper_engine" not in st.session_state and client:
            tick_store = lf.get_tick_store() if st.session_state.get("live_feed_initialized") else None
            st.session_state["paper_engine"] = PaperTradingEngine(client, tick_store)

        if "gtt_manager" not in st.session_state and client:
            from gtt_manager import GTTManager
            gtt_mgr = GTTManager(client, TradeDB())
            gtt_mgr.start_sync()
            st.session_state["gtt_manager"] = gtt_mgr

        render_sidebar()
        render_alert_banners()
        st.markdown("---")

        page = SessionState.get_current_page()
        if page in AUTH_PAGES and not SessionState.is_authenticated():
            st.warning("🔒 Please login from the sidebar to access this page.")
            return

        if SessionState.is_session_expired():
            st.error("🔴 Session expired (8 hours). Please reconnect.")
            if st.button("🔄 Reconnect", type="primary"):
                _cleanup_session()
                st.rerun()
            return

        PAGE_FN.get(page, page_dashboard)()

    except Exception as e:
        log.critical(f"Fatal: {e}", exc_info=True)
        st.error("❌ Critical error. Please refresh the page.")
        if st.session_state.get("debug_mode"):
            st.exception(e)


if __name__ == "__main__":
    main()
