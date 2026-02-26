"""
Breeze Options Trader PRO v10.0
Production-grade terminal for ICICI Breeze Options Trading.

Enhanced features:
- 11 pages: Dashboard, Option Chain, Sell, Square Off, Orders, Positions,
            Strategy Builder, Analytics, Risk Monitor, Watchlist, Settings
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
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
from functools import wraps
import time
import logging
import io
from typing import Dict, List, Optional

import app_config as C
from helpers import (
    APIResponse, safe_int, safe_float, safe_str, parse_funds,
    detect_position_type, get_closing_action, calculate_pnl, enrich_positions,
    process_option_chain, create_pivot_table,
    calculate_pcr, calculate_max_pain, estimate_atm_strike,
    add_greeks_to_chain, get_market_status, format_currency,
    format_expiry, format_expiry_short, calculate_days_to_expiry,
    format_number, pnl_badge
)
from analytics import (
    calculate_greeks, estimate_implied_volatility,
    calculate_portfolio_greeks, stress_test_portfolio,
    calculate_iv_smile, calculate_max_drawdown, calculate_var
)
from session_manager import (
    Credentials, SessionState, CacheManager, Notifications
)
from breeze_api import BreezeAPIClient
from validators import validate_date_range
from strategies import (
    StrategyLeg, PREDEFINED_STRATEGIES, STRATEGY_CATEGORIES,
    generate_strategy_legs, calculate_strategy_metrics,
    generate_payoff_data, get_strategies_by_category
)
from persistence import TradeDB
from risk_monitor import RiskMonitor, Alert

# ─── Logging ──────────────────────────────────────────────────
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
st.markdown(THEME_CSS, unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════

PAGES = [
    "Dashboard", "Option Chain", "Sell Options", "Square Off",
    "Orders & Trades", "Positions", "Strategy Builder",
    "Analytics", "Risk Monitor", "Watchlist", "Settings"
]

ICONS = {
    "Dashboard": "🏠", "Option Chain": "📊",
    "Sell Options": "💰", "Square Off": "🔄",
    "Orders & Trades": "📋", "Positions": "📍",
    "Strategy Builder": "🎯", "Analytics": "📈",
    "Risk Monitor": "🛡️", "Watchlist": "👁️", "Settings": "⚙️"
}

AUTH_PAGES = set(PAGES[1:])


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
                SessionState.navigate_to("Dashboard")
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


def get_client():
    c = SessionState.get_client()
    if not c or not c.is_connected():
        st.error("❌ Not connected to Breeze API")
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


def export_to_csv(df: pd.DataFrame, filename: str):
    """Return download button for CSV export."""
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    st.download_button(
        label="📥 Export CSV",
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
                df.to_excel(writer, sheet_name=sheet[:31], index=False)
    st.download_button(
        label="📥 Export Excel",
        data=buf.getvalue(),
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


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

        has_secrets = Credentials.has_stored_credentials()
        avail = PAGES if SessionState.is_authenticated() else ["Dashboard"]
        cur = SessionState.get_current_page()
        if cur not in avail:
            cur = "Dashboard"
            SessionState.navigate_to(cur)
        try:
            idx = avail.index(cur)
        except ValueError:
            idx = 0

        sel = st.radio(
            "Nav", avail, index=idx,
            format_func=lambda p: f"{ICONS.get(p, '')} {p}",
            label_visibility="collapsed", key="nav"
        )
        if sel != cur:
            SessionState.navigate_to(sel)
            st.rerun()

        st.markdown("---")

        if SessionState.is_authenticated():
            # Status
            ms = C.get_market_status()
            mkt_class = "mkt-open" if ms["status"] == "open" else "mkt-closed"
            st.markdown(
                f'<span class="badge-connected">✅ Connected</span>&nbsp;&nbsp;'
                f'<span class="{mkt_class}">{ms["label"]}</span>',
                unsafe_allow_html=True
            )
            # Countdown
            if "countdown" in ms:
                mins = ms["countdown"] // 60
                secs = ms["countdown"] % 60
                st.caption(f"⏱ {ms['next']} in {mins}m {secs:02d}s")

            name = st.session_state.get("user_name", "Trader")
            dur = SessionState.get_login_duration()
            st.markdown(f"**👤 {name}**" + (f"  ·  ⏱ {dur}" if dur else ""))

            if SessionState.is_session_expired():
                st.error("🔴 Session expired!")
            elif SessionState.is_session_stale():
                st.warning("⚠️ Session aging — consider reconnecting")

            # Funds summary
            client = get_client()
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
            if st.button("🔓 Disconnect", use_container_width=True):
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
    if has_secrets:
        st.markdown("### 🔑 Daily Login")
        st.success("✅ API Keys loaded from secrets")
        with st.form("quick_login"):
            tok = st.text_input("Session Token", type="password",
                                placeholder="8-digit token from ICICI")
            if st.form_submit_button("🔑 Connect", type="primary", use_container_width=True):
                if tok and len(tok.strip()) >= 4:
                    k, s, _ = Credentials.get_all_credentials()
                    do_login(k, s, tok.strip())
                else:
                    st.warning("Enter a valid session token")
    else:
        st.markdown("### 🔐 Login")
        st.warning("No secrets found. Enter credentials.")
        with st.form("full_login"):
            k, s, _ = Credentials.get_all_credentials()
            nk = st.text_input("API Key", value=k, type="password")
            ns = st.text_input("API Secret", value=s, type="password")
            tok = st.text_input("Session Token", type="password")
            if st.form_submit_button("🔑 Connect", type="primary", use_container_width=True):
                if all([nk, ns, tok]):
                    do_login(nk.strip(), ns.strip(), tok.strip())
                else:
                    st.warning("Fill all fields")


def _cleanup_session():
    monitor = st.session_state.get("risk_monitor")
    if monitor:
        monitor.stop()
    SessionState.set_authentication(False, None)
    Credentials.clear_runtime_credentials()
    CacheManager.clear_all()
    SessionState.navigate_to("Dashboard")
    _db.log_activity("LOGOUT", "Session ended")


def do_login(api_key, api_secret, token):
    if not api_key or not api_secret:
        st.error("❌ Missing API credentials")
        return
    with st.spinner("Connecting to Breeze API..."):
        try:
            client = BreezeAPIClient(api_key, api_secret)
            resp = client.connect(token)
            if resp["success"]:
                Credentials.save_runtime_credentials(api_key, api_secret, token)
                SessionState.set_authentication(True, client)
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
                st.error(f"❌ Connection failed: {resp.get('message', 'Unknown error')}")
                if 'session' in resp.get('message', '').lower():
                    st.info("💡 Session tokens expire daily. Get a fresh token from ICICI Breeze.")
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
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        info_box("👈 <b>Login from the sidebar</b> to start trading.")
        return

    client = get_client()
    if not client:
        return

    render_auto_refresh("dashboard")

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
                SessionState.navigate_to("Sell Options")
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
                st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
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
            st.dataframe(pd.DataFrame(eq_rows), hide_index=True, use_container_width=True)

    # ── Quick Actions ─────────────────────────────────────────
    st.markdown("---")
    section("⚡ Quick Actions")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    actions = [("📊 Chain", "Option Chain"), ("💰 Sell", "Sell Options"),
               ("🔄 Square Off", "Square Off"), ("🎯 Strategies", "Strategy Builder"),
               ("🛡️ Risk", "Risk Monitor"), ("👁️ Watchlist", "Watchlist")]
    for col, (label, page) in zip([c1, c2, c3, c4, c5, c6], actions):
        with col:
            if st.button(label, use_container_width=True):
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

    c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
    with c1:
        inst = st.selectbox("Instrument", list(C.INSTRUMENTS.keys()), key="oc_inst")
    cfg = C.get_instrument(inst)
    with c2:
        expiries = C.get_next_expiries(inst, 6)
        if not expiries:
            st.error("No expiries available")
            return
        expiry = st.selectbox("Expiry", expiries, format_func=format_expiry, key="oc_exp")
    with c3:
        n_strikes = st.slider("Strikes ±", 5, 40, 15, key="oc_n")
    with c4:
        st.markdown("<br>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        refresh = col1.button("🔄", key="oc_ref", help="Refresh chain")
        show_greeks = col2.checkbox("Greeks", True, key="oc_g")

    view = st.radio("View", ["Traditional", "Flat", "Calls Only", "Puts Only", "IV Smile"],
                    horizontal=True, key="oc_v")

    ck = f"oc_{cfg.api_code}_{expiry}"
    if refresh:
        CacheManager.invalidate(ck, "option_chain")
        st.rerun()

    df = CacheManager.get(ck, "option_chain")
    if df is not None:
        st.caption("📦 From cache — press 🔄 to refresh")
    else:
        with st.spinner(f"Loading {inst} option chain..."):
            resp = client.get_option_chain(cfg.api_code, cfg.exchange, expiry)
        if not resp["success"]:
            st.error(f"❌ Breeze API error: {resp.get('message')}")
            raw = resp.get("data", {})
            if isinstance(raw, dict) and raw.get("Error"):
                st.error(f"Breeze error detail: {raw['Error']} (Status {raw.get('Status')})")
            st.info(f"📋 Debug: stock_code={cfg.api_code}, exchange={cfg.exchange}, expiry={expiry}")
            return
        raw_data = resp.get("data", {})
        # Surface Breeze-level errors even when success=True (in case _ok wrapping is bypassed)
        if isinstance(raw_data, dict) and raw_data.get("Error"):
            st.error(f"❌ Breeze API returned error: {raw_data['Error']}")
            st.info(f"📋 Debug: stock_code={cfg.api_code}, exchange={cfg.exchange}, expiry={expiry}")
            return
        df = process_option_chain(raw_data)
        if df.empty:
            from breeze_api import convert_to_breeze_datetime
            st.warning("⚠️ No option chain data returned from Breeze.")
            st.info(
                f"📋 Debug info — stock_code: {cfg.api_code} | "
                f"exchange: {cfg.exchange} | "
                f"expiry: {expiry} → ISO: {convert_to_breeze_datetime(expiry)} | "
                f"product_type: options | "
                f"Raw response: {raw_data}"
            )
            return
        CacheManager.set(ck, df, "option_chain", C.OC_CACHE_TTL_SECONDS)
        SessionState.log_activity("Chain", f"{inst} {format_expiry_short(expiry)}")

    # ── Metrics bar ───────────────────────────────────────────
    atm = estimate_atm_strike(df)
    pcr = calculate_pcr(df)
    mp = calculate_max_pain(df)
    dte = calculate_days_to_expiry(expiry)
    total_call_oi = df[df["right"] == "Call"]["open_interest"].sum() if "right" in df.columns else 0
    total_put_oi = df[df["right"] == "Put"]["open_interest"].sum() if "right" in df.columns else 0

    mc = st.columns(6)
    mc[0].metric("ATM ≈", f"{atm:,.0f}")
    mc[1].metric("PCR", f"{pcr:.2f}", "Bullish" if pcr > 1 else "Bearish")
    mc[2].metric("Max Pain", f"{mp:,.0f}")
    mc[3].metric("DTE", str(dte), "⚠️ Expiry Soon!" if dte <= 2 else None,
                 delta_color="inverse" if dte <= 2 else "normal")
    mc[4].metric("Call OI", format_number(total_call_oi))
    mc[5].metric("Put OI", format_number(total_put_oi))

    if dte <= 0:
        warn_box("⚠️ <b>Expiry Day!</b> Options expire today. Consider squaring off short positions.")

    st.markdown("---")

    # Filter around ATM
    if "strike_price" in df.columns and atm > 0:
        strikes = sorted(df["strike_price"].unique())
        if strikes:
            ai = min(range(len(strikes)), key=lambda i: abs(strikes[i] - atm))
            filt = strikes[max(0, ai - n_strikes): min(len(strikes), ai + n_strikes + 1)]
            ddf = df[df["strike_price"].isin(filt)].copy()
        else:
            ddf = df.copy()
    else:
        ddf = df.copy()

    spot_for_greeks = atm if atm > 0 else (ddf["strike_price"].median() if "strike_price" in ddf.columns else 0)

    if show_greeks and not ddf.empty and spot_for_greeks > 0:
        try:
            ddf = add_greeks_to_chain(ddf, spot_for_greeks, expiry)
        except Exception as e:
            log.debug(f"Greeks calc failed: {e}")

    # ── Display ───────────────────────────────────────────────
    if view == "Traditional":
        pv = create_pivot_table(ddf)
        tgt = pv if not pv.empty else ddf
        st.dataframe(tgt, height=600, hide_index=True, use_container_width=True)
    elif view == "Calls Only":
        cd = ddf[ddf["right"] == "Call"] if "right" in ddf.columns else ddf
        st.dataframe(cd, height=600, hide_index=True, use_container_width=True)
    elif view == "Puts Only":
        pd_ = ddf[ddf["right"] == "Put"] if "right" in ddf.columns else ddf
        st.dataframe(pd_, height=600, hide_index=True, use_container_width=True)
    elif view == "IV Smile":
        # Compute and plot IV smile
        if spot_for_greeks > 0:
            smile = calculate_iv_smile(ddf, spot_for_greeks, expiry)
            all_strikes = sorted(set(list(smile["calls"].keys()) + list(smile["puts"].keys())))
            if all_strikes:
                smile_df = pd.DataFrame({
                    "Strike": all_strikes,
                    "Call IV%": [smile["calls"].get(s, np.nan) for s in all_strikes],
                    "Put IV%": [smile["puts"].get(s, np.nan) for s in all_strikes],
                }).set_index("Strike")
                st.line_chart(smile_df)
                st.caption("IV Smile: higher IV for OTM options indicates demand for protection (skew)")
            else:
                st.info("Not enough data for IV smile")
        else:
            st.info("Cannot compute IV smile without spot price")
    else:  # Flat
        st.dataframe(ddf, height=600, hide_index=True, use_container_width=True)

    # ── OI Chart ──────────────────────────────────────────────
    if "right" in ddf.columns and "open_interest" in ddf.columns and view != "IV Smile":
        st.markdown("---")
        section("📊 Open Interest Distribution")
        try:
            co = ddf[ddf["right"] == "Call"][["strike_price", "open_interest"]].rename(
                columns={"open_interest": "Call OI"})
            po = ddf[ddf["right"] == "Put"][["strike_price", "open_interest"]].rename(
                columns={"open_interest": "Put OI"})
            oi = (pd.merge(co, po, on="strike_price", how="outer")
                  .fillna(0).sort_values("strike_price").set_index("strike_price"))
            st.bar_chart(oi, use_container_width=True)

            # OI change if available
            if "oi_change" in ddf.columns:
                coc = ddf[ddf["right"] == "Call"][["strike_price", "oi_change"]].rename(
                    columns={"oi_change": "Call ΔOI"})
                poc = ddf[ddf["right"] == "Put"][["strike_price", "oi_change"]].rename(
                    columns={"oi_change": "Put ΔOI"})
                oic = (pd.merge(coc, poc, on="strike_price", how="outer")
                       .fillna(0).sort_values("strike_price").set_index("strike_price"))
                st.caption("OI Change (today)")
                st.bar_chart(oic, use_container_width=True)
        except Exception as e:
            log.debug(f"OI chart error: {e}")

    # ── Export ────────────────────────────────────────────────
    if not ddf.empty:
        export_to_csv(ddf, f"option_chain_{inst}_{expiry}.csv")


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
        if st.button("📊 Get Quote", disabled=not valid, use_container_width=True):
            with st.spinner("Fetching quote..."):
                r = client.get_quotes(cfg.api_code, cfg.exchange, expiry, int(strike), oc)
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

        if st.button("💰 Check Margin", disabled=not valid, use_container_width=True):
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

    # ── Order placement ───────────────────────────────────────
    st.markdown("---")
    danger_box("⚠️ <b>RISK WARNING:</b> Option selling carries <b>unlimited risk</b>. "
               "Never sell without understanding your max loss. Use stop-losses.")

    ack = st.checkbox("✅ I understand and accept the risks of option selling", key="s_ack")
    order_busy = st.session_state.get("_order_busy", False)
    can_place = ack and valid and strike > 0 and (otp == "Market" or lp > 0) and not order_busy

    if order_busy:
        st.warning("⏳ Order in progress...")

    col1, col2 = st.columns([2, 1])
    with col1:
        if st.button(f"🔴 SELL {qty:,} {inst} {int(strike)} {oc}",
                     type="primary", disabled=not can_place, use_container_width=True):
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
                            action="sell", quantity=qty, price=lp,
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
        if st.button("🔄 Refresh Positions", use_container_width=True):
            invalidate_trading_caches()
            st.rerun()
    with col_bulk:
        if st.button("⚠️ Square Off ALL", type="secondary", use_container_width=True,
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
            st.dataframe(pd.DataFrame(preview_rows), hide_index=True, use_container_width=True)
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
                r = client.square_off(
                    sc, e.get("exchange_code"),
                    e.get("expiry_date"), safe_int(e.get("strike_price")),
                    C.normalize_option_type(e.get("right", "")),
                    qty_to_close, e["_pt"], "market", 0.0
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
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

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
    btn_label = (
        f"🔄 {sel['_close'].upper()} {sq_lots} lot{'s' if sq_lots > 1 else ''} "        f"({sq} qty) — {C.api_code_to_display(sel.get('stock_code', ''))} "        f"{sel.get('strike_price')} {C.normalize_option_type(sel.get('right', ''))}"
    )
    can_square = (not order_busy) and (sq % sel_lot_size == 0) and (sq <= sel["_qty"]) and (sq >= sel_lot_size)
    if st.button(btn_label, type="primary", disabled=not can_square, use_container_width=True):
        st.session_state._order_busy = True
        try:
            with st.spinner("Squaring off..."):
                r = client.square_off(
                    sel.get("stock_code"), sel.get("exchange_code"),
                    sel.get("expiry_date"), safe_int(sel.get("strike_price")),
                    C.normalize_option_type(sel.get("right", "")),
                    sq, sel["_pt"], ot.lower(), pr
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
        refresh_ord = st.button("🔄 Fetch", use_container_width=True)

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
                    st.dataframe(df, height=400, hide_index=True, use_container_width=True)
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
                    st.dataframe(df, height=400, hide_index=True, use_container_width=True)
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
            st.dataframe(df, height=400, hide_index=True, use_container_width=True)
            export_to_excel({"Trades": df}, f"trade_history_{fd}_{td}.xlsx")
        else:
            empty_state("💾", "No trades recorded", "Trades auto-save when orders are placed")

    with t4:
        db_log = _db.get_activities(limit=100)
        if db_log:
            st.dataframe(pd.DataFrame(db_log), hide_index=True, use_container_width=True)
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

    if st.button("🔄 Refresh", use_container_width=False):
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
            mc[1].metric("Positions", len(ep))
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
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

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
            st.dataframe(pd.DataFrame(eq_rows), hide_index=True, use_container_width=True)


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
            sname = st.selectbox("Strategy", list(strats.keys()), key="sb_s")
            inst = st.selectbox("Instrument", list(C.INSTRUMENTS.keys()), key="sb_i")
            cfg = C.get_instrument(inst)
            expiry = st.selectbox("Expiry", C.get_next_expiries(inst, 6),
                                  format_func=format_expiry, key="sb_e")

            # Try to get live ATM
            ck = f"oc_{cfg.api_code}_{expiry}"
            df = CacheManager.get(ck, "option_chain")
            default_atm = estimate_atm_strike(df) if df is not None and not df.empty else 0
            if default_atm == 0:
                default_atm = int((cfg.min_strike + cfg.max_strike) / 2)
                default_atm = round(default_atm / cfg.strike_gap) * cfg.strike_gap

            atm = st.number_input("ATM Strike", min_value=cfg.min_strike,
                                  max_value=cfg.max_strike, value=int(default_atm),
                                  step=cfg.strike_gap, key="sb_a")
            lots = st.number_input("Lots per Leg", min_value=1, max_value=50, value=1, key="sb_l")

            if st.button("🔧 Build Strategy", type="primary", use_container_width=True):
                try:
                    legs = generate_strategy_legs(sname, int(atm), cfg.strike_gap, cfg.lot_size, lots)
                    st.session_state.strat_legs = legs
                    st.session_state.strat_cfg = cfg
                    st.session_state.strat_expiry = expiry
                    st.session_state.strat_name = sname
                    st.success(f"✅ Built {len(legs)} leg(s)")
                except Exception as e:
                    st.error(f"❌ {e}")

        with c2:
            info = PREDEFINED_STRATEGIES.get(sname, {})
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
                             "Qty": l.quantity, "Label": l.label,
                             "Premium ₹": f"{l.premium:.2f}" if l.premium > 0 else "—"}
                            for i, l in enumerate(legs)]
                st.dataframe(pd.DataFrame(leg_rows), hide_index=True, use_container_width=True)

                col_fetch, col_analyze = st.columns(2)
                if col_fetch.button("📊 Fetch Quotes", use_container_width=True):
                    with st.spinner("Fetching quotes for all legs..."):
                        for leg in legs:
                            try:
                                r = client.get_quotes(scfg.api_code, scfg.exchange,
                                                      sexpiry, leg.strike, leg.option_type)
                                if r["success"]:
                                    items = APIResponse(r).items
                                    if items:
                                        leg.premium = safe_float(items[0].get("ltp", 0))
                            except Exception:
                                pass
                        st.session_state.strat_legs = legs
                    st.success("✅ Quotes loaded")

                if col_analyze.button("📈 Analyze", use_container_width=True):
                    metrics = calculate_strategy_metrics(legs)
                    mc = st.columns(4)
                    mc[0].metric("Net Premium", format_currency(metrics["net_premium"]))
                    mc[1].metric("Max Profit", format_currency(metrics["max_profit"]))
                    mc[2].metric("Max Loss", format_currency(metrics["max_loss"]))
                    if metrics["max_loss"] != 0:
                        mc[3].metric("R:R Ratio", f"1:{abs(metrics['max_profit']/metrics['max_loss']):.2f}")
                    if metrics["breakevens"]:
                        info_box(f"🎯 <b>Breakevens:</b> {', '.join(str(int(b)) for b in metrics['breakevens'])}")

                    payoff_df = generate_payoff_data(legs, int(atm), scfg.strike_gap)
                    if payoff_df is not None:
                        section("📊 Payoff Diagram")
                        import plotly.graph_objects as go
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(
                            x=payoff_df["Underlying"], y=payoff_df["P&L"],
                            mode='lines', name='P&L',
                            line=dict(color='#1f77b4', width=2),
                            fill='tozeroy',
                            fillcolor='rgba(31,119,180,0.15)'
                        ))
                        fig.add_hline(y=0, line_dash="dot", line_color="gray")
                        fig.add_vline(x=int(atm), line_dash="dash", line_color="orange",
                                      annotation_text="ATM")
                        fig.update_layout(
                            title=f"{sname} Payoff",
                            xaxis_title="Underlying Price",
                            yaxis_title="P&L (₹)",
                            hovermode='x unified',
                            height=400
                        )
                        st.plotly_chart(fig, use_container_width=True)

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
            if st.button("➕ Add Leg", use_container_width=True):
                st.session_state.custom_legs.append(StrategyLeg(
                    strike=int(cl_strike), option_type=cl_type,
                    action=cl_action, quantity=cl_lots * cfg2.lot_size
                ))

        if st.session_state.custom_legs:
            cleg_rows = [{"#": i+1, "Action": l.action.upper(), "Strike": l.strike,
                          "Type": l.option_type, "Qty": l.quantity,
                          "Premium": l.premium if l.premium > 0 else "—"}
                         for i, l in enumerate(st.session_state.custom_legs)]
            st.dataframe(pd.DataFrame(cleg_rows), hide_index=True, use_container_width=True)
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

        st.write(f"**Strategy:** {sname_exec}")
        st.write(f"**Instrument:** {scfg.display_name} | **Expiry:** {format_expiry_short(sexpiry)}")
        danger_box("⚠️ This will place <b>real orders</b> for all legs simultaneously.")
        ack = st.checkbox("I confirm all legs and want to execute", key="se_ack")
        if ack and st.button("⚡ Execute All Legs", type="primary", use_container_width=True):
            ok, fail = 0, 0
            for leg in legs:
                with st.spinner(f"Placing {leg.action.upper()} {leg.strike} {leg.option_type}..."):
                    r = scfg and client.place_order(
                        scfg.api_code, scfg.exchange, sexpiry,
                        leg.strike, leg.option_type, leg.action, leg.quantity, "market", 0.0
                    )
                    if r and r.get("success"):
                        ok += 1
                        _db.log_trade(
                            stock_code=scfg.api_code, exchange=scfg.exchange,
                            strike=leg.strike, option_type=leg.option_type,
                            expiry=sexpiry, action=leg.action, quantity=leg.quantity,
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

    t1, t2, t3, t4 = st.tabs(["📊 Portfolio Greeks", "💰 Margin", "📈 Performance", "🧪 Stress Test"])

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
                st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
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

                # Delta visualization
                if any(r["Delta"] != "+0.00" for r in rows):
                    delta_df = pd.DataFrame(rows)[["Position", "Strike", "Type", "Delta"]]
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
                st.bar_chart(chart_df.set_index("Category"), use_container_width=True)

    with t3:
        section("Performance Analytics")
        hist = _db.get_pnl_history(90)
        if hist:
            hist_df = pd.DataFrame(hist).sort_values("date")
            c1, c2 = st.columns(2)
            with c1:
                if "realized_pnl" in hist_df.columns:
                    hist_df["Cumulative P&L"] = hist_df["realized_pnl"].cumsum()
                    st.line_chart(hist_df.set_index("date")[["Cumulative P&L"]], use_container_width=True)
            with c2:
                if "num_trades" in hist_df.columns:
                    st.bar_chart(hist_df.set_index("date")[["num_trades"]], use_container_width=True)

            daily_pnl = hist_df.get("realized_pnl", pd.Series(dtype=float)).tolist()
            if daily_pnl:
                mc = st.columns(4)
                mc[0].metric("Total Days", len(daily_pnl))
                mc[1].metric("Best Day", format_currency(max(daily_pnl)))
                mc[2].metric("Worst Day", format_currency(min(daily_pnl)))
                mc[3].metric("Max Drawdown", format_currency(calculate_max_drawdown(
                    list(hist_df.get("realized_pnl", pd.Series()).cumsum()))))
        else:
            empty_state("📈", "No P&L history yet", "Trade to build history")

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
                st.plotly_chart(fig, use_container_width=True)
                # Show table of all scenarios
                stress_df = pd.DataFrame(results)
                st.dataframe(stress_df.style.background_gradient(cmap='RdYlGn', axis=None),
                             use_container_width=True)


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
            if st.button("⏹️ Stop", use_container_width=True):
                monitor.stop()
                st.rerun()
        else:
            st.warning("🔴 Monitor Stopped")
            if st.button("▶️ Start", type="primary", use_container_width=True):
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
    tab1, tab2, tab3 = st.tabs(["📍 Positions", "⚙️ Stop-Losses", "🚨 Alerts"])

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
                        if st.button("➕ Monitor", key=f"add_{pid}", use_container_width=True):
                            monitor.add_position(pid, stock, p.get("exchange_code", ""),
                                                 p.get("expiry_date", ""), strike_val,
                                                 ot, pt, qty, avg)
                            _db.log_activity("MONITOR_ADD", f"Added {pid}")
                            st.success(f"✅ Monitoring {label}")
                            st.rerun()
                    else:
                        if st.button("🗑️ Remove", key=f"rm_{pid}", use_container_width=True):
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
                        if st.button("Set Fixed Stop", key=f"ss_{m['id']}", use_container_width=True):
                            monitor.set_stop_loss(m["id"], stop_px)
                            _db.log_activity("STOP_SET", f"₹{stop_px:.2f} on {m['id']}")
                            st.success(f"✅ Stop set at ₹{stop_px:.2f}")
                    with sc2:
                        st.markdown("**Trailing Stop**")
                        trail_pct = st.slider("Trail %", 10, 200, 50, 5, key=f"tr_{m['id']}")
                        if st.button("Set Trailing", key=f"trs_{m['id']}", use_container_width=True):
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
                        if st.button("🗑️ Remove", key=f"rmm_{m['id']}", use_container_width=True):
                            monitor.remove_position(m["id"])
                            st.rerun()

    with tab3:
        history = monitor.get_alert_history()
        db_alerts = _db.get_alerts(limit=50)
        if history or db_alerts:
            all_alerts = [{"Time": a.timestamp, "Level": a.level, "Category": a.category,
                           "Message": a.message, "Position": a.position_id}
                          for a in history]
            if all_alerts:
                df = pd.DataFrame(all_alerts)
                st.dataframe(df, hide_index=True, use_container_width=True)
                if st.button("✅ Acknowledge All"):
                    _db.acknowledge_alerts()
            if db_alerts:
                st.markdown("---")
                st.caption("Persistent Alert History")
                st.dataframe(pd.DataFrame(db_alerts), hide_index=True, use_container_width=True)
        else:
            empty_state("🔔", "No alerts", "Alerts appear when stops are triggered")


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
            if st.button("➕ Add", use_container_width=True):
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
            r = client.get_quotes(cfg.api_code, cfg.exchange, item["expiry"],
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
    st.dataframe(df[display_cols], hide_index=True, use_container_width=True)

    # Remove button
    rm_id = st.selectbox("Remove item:", [f"{r['ID']}: {r['Symbol']}" for r in rows], key="wl_rm")
    if st.button("🗑️ Remove from Watchlist"):
        item_id = int(rm_id.split(":")[0])
        _db.remove_watchlist_item(item_id)
        st.success("Removed")
        st.rerun()

    export_to_csv(df[display_cols], "watchlist.csv")


# ═══════════════════════════════════════════════════════════════
# PAGE: SETTINGS
# ═══════════════════════════════════════════════════════════════

@error_handler
def page_settings():
    page_header("⚙️ Settings")

    t1, t2, t3, t4 = st.tabs(["🎛️ Trading", "🛡️ Risk Limits", "🗄️ Database", "ℹ️ System Info"])

    with t1:
        section("Trading Preferences")
        c1, c2 = st.columns(2)
        with c1:
            default_order = st.selectbox("Default Order Type",
                                         ["Market", "Limit"],
                                         index=0 if _db.get_setting("default_order_type", "Market") == "Market" else 1)
            default_lots = st.number_input("Default Lots", min_value=1, value=int(_db.get_setting("default_lots", 1)))
            require_ack = st.checkbox("Require confirmation for orders",
                                      value=_db.get_setting("require_ack", True))
        with c2:
            auto_sl = st.checkbox("Auto stop-loss after sell",
                                  value=_db.get_setting("auto_sl", False))
            sl_mult = st.slider("Default SL multiplier", 1.5, 5.0,
                                float(_db.get_setting("sl_multiplier", 2.0)), 0.5)
            max_lots_per_order = st.number_input("Max Lots Per Order",
                                                  min_value=1, max_value=1000,
                                                  value=int(_db.get_setting("max_lots", 100)))

        if st.button("💾 Save Trading Settings", type="primary"):
            _db.set_setting("default_order_type", default_order)
            _db.set_setting("default_lots", default_lots)
            _db.set_setting("require_ack", require_ack)
            _db.set_setting("auto_sl", auto_sl)
            _db.set_setting("sl_multiplier", sl_mult)
            _db.set_setting("max_lots", max_lots_per_order)
            st.success("✅ Settings saved")

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

    with t4:
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

PAGE_FN = {
    "Dashboard": page_dashboard,
    "Option Chain": page_option_chain,
    "Sell Options": page_sell_options,
    "Square Off": page_square_off,
    "Orders & Trades": page_orders_trades,
    "Positions": page_positions,
    "Strategy Builder": page_strategy_builder,
    "Analytics": page_analytics,
    "Risk Monitor": page_risk_monitor,
    "Watchlist": page_watchlist,
    "Settings": page_settings,
}


def main():
    try:
        # Ensure logs dir
        import os
        os.makedirs("logs", exist_ok=True)

        SessionState.initialize()
        render_sidebar()
        render_alert_banners()
        st.markdown("---")

        page = SessionState.get_current_page()

        if page in AUTH_PAGES and not SessionState.is_authenticated():
            st.warning("🔒 Please login from the sidebar to access this page.")
            return

        if (SessionState.is_authenticated() and SessionState.is_session_expired()):
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
