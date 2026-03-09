# BREEZE PRO — CODEX RALPH MODE PRODUCTION SPEC
## Complete Architecture Study, Design Blueprint & Innovation Prompt
### Version: PRODUCTION GRADE v12.0 | Target: Indian NSE/BSE Options Terminal

---

> **RALPH MODE ACTIVATED.**
> This document is a full-spectrum engineering brief. Every section is actionable.
> ALL CAPS denotes MANDATORY / NON-NEGOTIABLE requirements.
> Every plan block is a Codex task unit. Execute sequentially.

---

## SECTION 0 — MISSION STATEMENT

Build the **definitive Indian retail options trading terminal** using ICICI Breeze Connect API.
Target user: active NSE/BSE/NFO derivatives trader (Nifty, BankNifty, FinNifty, MidcpNifty, Sensex, Bankex).
Platform: Streamlit (primary), FastAPI microservice (metrics/health), Docker/Kubernetes (prod deploy).

THE TERMINAL MUST:
- Execute real money trades with ZERO silent failures
- Show live Greeks, IV, PCR, Max Pain in real-time
- Manage risk autonomously via background daemon
- Support 15+ multi-leg strategies with payoff diagrams
- Persist all trades to SQLite for tax and audit trail
- Alert traders via Telegram + Email + Webhook on critical events
- Pass full CI (lint, unit tests, security scan, Docker build)

---

## SECTION 1 — DEEP CODEBASE ANALYSIS

### 1.1 Repository Structure (Authoritative)

```
breeze-pro/
├── app.py                    # MAIN ENTRY — 4,015 lines, 15-page Streamlit terminal
├── app_config.py             # Pure config — instruments, market hours, risk defaults
├── breeze_api.py             # API client v11 — retry, rate-limit, thread-lock, 1,341 lines
├── analytics.py              # Black-Scholes, Greeks, IV solver, Monte Carlo, VaR
├── strategies.py             # 15+ predefined strategies — payoff, metrics, legs
├── persistence.py            # SQLite — trades, watchlist, P&L history, snapshots
├── risk_monitor.py           # Background daemon — fixed/trailing stops, portfolio limits
├── alerting.py               # Telegram + Email + Webhook dispatchers
├── live_feed.py              # WebSocket feed — 825 lines, tick store, bar builder
├── gtt_manager.py            # GTT order management (Good-Till-Triggered)
├── paper_trading.py          # Simulated order fill engine
├── session_manager.py        # TOTP auth, credential store, cache manager
├── helpers.py                # Safe converters, option chain processing, formatting
├── charts.py                 # Plotly chart generators — candlestick, IV smile, Greeks
├── futures.py                # Futures expiry calendar, basis calc
├── historical.py             # Historical candle fetch + in-memory TTL cache
├── holiday_calendar.py       # Dynamic NSE holiday fetch from NSE API + SQLite cache
├── validators.py             # Date range, input validators
├── app/
│   ├── api/main.py           # FastAPI — /healthz /ready /metrics
│   └── lib/
│       ├── breeze_client.py  # Production REST wrapper — circuit breaker, Prometheus
│       ├── auth.py           # Token lifecycle — FileTokenStore, InMemoryTokenStore
│       ├── config.py         # Pydantic Settings (env vars)
│       ├── errors.py         # Typed exceptions hierarchy
│       ├── breeze_ws.py      # WebSocket reconnect + subscription cap manager
│       └── logging_config.py # Structured logging setup
├── data/
│   └── breeze_trader.db      # SQLite database (runtime)
├── tests/
│   ├── unit/                 # 15 unit test modules
│   └── integration/          # Live API integration tests
├── k8s/deployment.yaml       # Kubernetes deployment + HPA
├── docker-compose.prod.yml   # Production docker-compose
└── .github/workflows/ci.yml  # CI: lint → test → bandit → docker build
```

### 1.2 The 15 Pages — Full Map

| # | Page Key | Function | Auth Required | Core Dependencies |
|---|----------|----------|---------------|-------------------|
| 1 | 🏠 Dashboard | `page_dashboard()` | No (landing) | BreezeAPIClient, helpers, analytics |
| 2 | ⛓️ Option Chain | `page_option_chain()` | YES | get_option_chain, process_option_chain, add_greeks_to_chain |
| 3 | 💸 Sell Options | `page_sell_options()` | YES | place_order, render_order_cost_preview |
| 4 | ❌ Square Off | `page_square_off()` | YES | get_positions, place_order (bulk) |
| 5 | 📋 Orders & Trades | `page_orders_trades()` | YES | get_order_list, get_trade_list |
| 6 | 💼 Positions | `page_positions()` | YES | enrich_positions, calculate_pnl |
| 7 | 📊 Historical Data | `page_historical_data()` | YES | HistoricalCache, charts.render_candlestick |
| 8 | 📈 Futures Trading | `page_futures_trading()` | YES | futures.py, get_futures_expiries |
| 9 | ⏰ GTT Orders | `page_gtt_orders()` | YES | GTTManager, render_gtt_order_cost_preview |
| 10 | 🧠 Strategy Builder | `page_strategy_builder()` | YES | PREDEFINED_STRATEGIES, generate_payoff_data |
| 11 | 🔬 Analytics | `page_analytics()` | YES | stress_test_portfolio, monte_carlo_var, iv_smile |
| 12 | 🚨 Risk Monitor | `page_risk_monitor()` | YES | RiskMonitor daemon, Alert queue |
| 13 | 👁️ Watchlist | `page_watchlist()` | YES | TradeDB.watchlist, live quotes |
| 14 | 📄 Paper Trading | `page_paper_trading()` | YES | PaperTradingEngine |
| 15 | ⚙️ Settings | `page_settings()` | YES | AlertConfig, account profiles, TOTP |

### 1.3 Data Flow Architecture

```
BROWSER (Streamlit Frontend)
        │
        ▼
 render_sidebar() ──► SessionState.is_authenticated()
        │                        │
        │                   TOTP + API Key + Secret
        │                        │
        ▼                        ▼
 page_{name}()          BreezeAPIClient (breeze_api.py)
        │                   │           │
        │           RateLimiter    RetryDecorator
        │                   │           │
        │               breeze_connect SDK
        │                        │
        │              ┌─────────┴──────────┐
        │              │                    │
        │         REST Calls          WebSocket (live_feed.py)
        │              │                    │
        │         ICICI Breeze API    TickStore / BarBuilder
        │              │
        ▼              ▼
  CacheManager ◄── APIResponse (helpers.py)
        │
        ▼
  TradeDB (SQLite) ◄── persistence.py
        │
        ▼
  RiskMonitor (background thread) ──► AlertDispatcher
                                           │
                                    ┌──────┴──────┐
                               Telegram       Email/Webhook
```

### 1.4 Critical Subsystem Details

#### BreezeAPIClient (breeze_api.py)
- Thread-safe via `threading.RLock()`
- `RateLimiter` at 5 calls/second
- `@retry_api_call` — 3 attempts, exponential backoff (0.5s → 1s → 2s)
- CRITICAL: Order placement functions DO NOT use retry (idempotency)
- Datetime format: ISO-8601 `2026-03-04T06:00:00.000Z` (NOT `04-Mar-2026`)
- Permanent failure classification: `invalid session`, `unauthorized`, `forbidden`
- Transient failure classification: `503`, `502`, `429`, `connection reset`

#### Analytics Engine (analytics.py)
- Black-Scholes pricing: `bs_price()` with numerical stability clipping at ±10
- Greeks: Delta, Gamma, Theta (daily), Vega (per 1% vol), Rho
- IV solver: Newton-Raphson primary → Brent's method fallback
- Portfolio Greeks: aggregated weighted delta/gamma/theta/vega across all positions
- Stress Testing: scenario matrix (vol shock × spot shock) → P&L matrix
- Monte Carlo VaR: 10,000 simulations, configurable confidence level
- Rolling Realized Vol: annualized, configurable window
- IV vs RV Spread: volatility risk premium indicator

#### RiskMonitor (risk_monitor.py)
- Runs in a `threading.Thread(daemon=True)`
- Poll interval: 15 seconds (configurable)
- Per-position: fixed stop-loss, trailing stop (%, with high-water-mark)
- Portfolio-level: max loss (INR), max net delta
- Alert categories: STOP_LOSS, PORTFOLIO, MARGIN, EXPIRY, PRICE_MOVE
- Alert levels: INFO / WARNING / CRITICAL
- Thread-safe: `threading.RLock()` + `queue.Queue()`

#### LiveFeed (live_feed.py)
- WebSocket to Breeze feed server
- Token resolution via NSE/BSE Security Master CSV (24hr TTL cache)
- Max 500 concurrent subscriptions
- Tick store: up to 10,000 ticks per symbol (deque)
- Bar builder: OHLCV aggregation from ticks
- Worker queue: 50,000 event capacity
- Health check: stale detection at 60 seconds

#### Persistence (persistence.py)
- SQLite at `data/breeze_trader.db`
- Tables: trades, activity_log, watchlist, pnl_history, alerts_log, state_snapshots
- Thread-safe via connection-per-thread pattern
- CSV/Excel export for tax filing
- Account profile support (multi-session)

---

## SECTION 2 — CURRENT GAPS & BUG INVENTORY

### P0 — PRODUCTION BLOCKING

1. **PAPER TRADING PAGE IS NULL** — `page_paper_trading` is set to `None` in PAGES dict (app.py:277).
   `page_paper_trading()` function exists at line 3635 but is NOT wired up.
   FIX: Change `"📄 Paper Trading": None` → `"📄 Paper Trading": page_paper_trading`

2. **SESSION TOKEN VALIDATION** — `session_manager.py` uses HMAC-TOTP but does not verify
   token expiry server-side before API calls. Silent stale sessions cause all API calls to fail
   without a clear re-auth prompt.
   FIX: Add `_check_session_validity()` call in `get_client()`, redirect to Settings on `PERMANENT` error.

3. **MISSING INSTRUMENT COVERAGE** — `app_config.py` defines lot sizes for Sensex/Bankex (BSE Derivatives)
   but option chain page only queries NFO. BFO (BSE F&O) path is incomplete in `live_feed.py`.
   FIX: Complete BFO exchange path in `LiveFeedManager.subscribe()`.

### P1 — HIGH SEVERITY

4. **GTT ORDER COST PREVIEW** — `render_gtt_order_cost_preview()` calls `client.get_margin_required()`
   which may return stale data due to 60s funds cache TTL. Preview can show incorrect margin.
   FIX: Add force-refresh button; bypass cache on GTT preview.

5. **HISTORICAL DATA TIMEZONE SHIFT** — `historical.py` returns candles in UTC from Breeze API
   but chart labels show UTC times, misleading IST traders.
   FIX: Apply IST conversion in `fetch_historical_data()` before returning DataFrame.

6. **GREEK CALCULATION WITH ZERO TTE** — When expiry is same-day and `tte < 1e-10`, Greeks return
   hardcoded delta (0 or 1) but vega/theta return 0, which is correct — however the IV solver
   returns `IVResult(0.20, False, ...)` as default, polluting the option chain IV column with 20%.
   FIX: Return `None` or `np.nan` for same-day expiry IV, display as "—" in chain.

### P2 — MEDIUM SEVERITY

7. **STRATEGY BUILDER BASKET** — `generate_strategy_legs()` uses integer strike offsets × cfg.strike_gap
   but does not validate that calculated strikes actually exist in the fetched option chain.
   FIX: Snap to nearest available strike after generation.

8. **AUTOCOMPLETE ON WATCHLIST** — Watchlist add requires full instrument + strike + expiry.
   No search/autocomplete. High friction for new items.
   FIX: Add fuzzy text search against security master.

9. **MISSING TESTS** — No test for `page_dashboard()`, `page_sell_options()`, `page_square_off()`.
   Integration test suite has only 1 file.

---

## SECTION 3 — FULL PRODUCTION SPEC (CODEX TASK PLAN)

### PLAN PHASE 1 — FOUNDATION & CORRECTNESS (Sprint 1, Days 1–7)

**TASK 1.1 — WIRE UP PAPER TRADING PAGE**
```
FILE: app.py line 277
CHANGE: "📄 Paper Trading": None  →  "📄 Paper Trading": page_paper_trading
VERIFY: PaperTradingEngine.__init__ requires live_client — pass get_client() safely
TEST: test_paper_trading.py must pass; add test for page render with mock client
```

**TASK 1.2 — SESSION HEALTH GUARD**
```
FILE: session_manager.py
ADD: def check_session_health(client: BreezeAPIClient) -> bool:
     - Make a cheap call: client.get_funds()
     - If result contains PERMANENT error → clear credentials, return False
     - If result contains success → return True
FILE: app.py — get_client()
ADD: After returning client, call check_session_health() every 5 minutes
     (store last_check_ts in session_state, skip if < 300s since last check)
```

**TASK 1.3 — IST TIMEZONE IN HISTORICAL CHARTS**
```
FILE: historical.py
ADD: import pytz; IST = pytz.timezone("Asia/Kolkata")
MODIFY: fetch_historical_data() — after building DataFrame from API response,
        convert 'datetime' column from UTC to IST:
        df['datetime'] = pd.to_datetime(df['datetime'], utc=True).dt.tz_convert(IST)
FILE: charts.py render_candlestick()
ADD: tickformat="%d %b %H:%M" for xaxis (IST-aware display)
```

**TASK 1.4 — SAME-DAY EXPIRY IV FIX**
```
FILE: analytics.py — estimate_implied_volatility()
MODIFY: If tte < 2/365 (< 2 days), return np.nan instead of default 0.20
FILE: helpers.py — add_greeks_to_chain()
MODIFY: Replace NaN IV with "—" display string AFTER numeric calculations
```

**TASK 1.5 — STRIKE SNAP IN STRATEGY BUILDER**
```
FILE: strategies.py — generate_strategy_legs()
MODIFY: After computing strike = atm + offset * strike_gap,
        snap to nearest key in available_strikes set (pass as optional param)
FILE: app.py — page_strategy_builder()
ADD: Pass available_strikes from fetched option chain to generate_strategy_legs()
```

---

### PLAN PHASE 2 — NEW FEATURES (Sprint 2, Days 8–21)

**TASK 2.1 — LIVE DASHBOARD METRICS GRID**

IMPLEMENT a real-time top-of-page metrics bar on Dashboard (post-login) showing:
```
[ NIFTY SPOT | BANKNIFTY SPOT | VIX | NIFTY PCR | NIFTY MAX PAIN | MARKET STATUS | SESSION TIME ]
```
- EACH METRIC IS A `st.metric()` with delta from previous refresh
- VIX pulled from NSE API (add `get_india_vix()` to breeze_api.py)
- PCR calculated from cached option chain (read from CacheManager)
- Max Pain calculated from cached option chain
- Market Status from `get_market_status()` in helpers.py
- ALL METRICS auto-update on page refresh (no extra API call if chain cached)
- IMPLEMENTATION: New helper `get_dashboard_metrics(client, cache)` returning dict
- LAYOUT: `st.columns(7)` with gradient metric cards via injected CSS

**TASK 2.2 — OPTION CHAIN ENHANCEMENTS**

IMPLEMENT the following in `page_option_chain()`:
```
A. HEATMAP COLUMN — Add 'OI Change %' column, color-coded green/red via background_gradient
B. VOLUME SPIKE ALERT — If volume > 3x avg 5-day volume for that strike, add ⚡ badge
C. PCR GAUGE — Show Put/Call Ratio as an st.progress() visual + color-coded label
D. MAX PAIN MARKER — Highlight the max-pain strike row with a 🎯 emoji in the Strike column
E. IV PERCENTILE — For each row show IV as a percentile vs 30-day history (requires historical IV store)
F. EXPORT BUTTON — "📥 Export Chain CSV" downloads the full displayed DataFrame
```
ALL of these MUST BE toggleable (checkboxes in a sidebar expander named "⛓️ Chain Options")
to avoid UI clutter.

**TASK 2.3 — STRATEGY BUILDER PAYOFF DIAGRAM UPGRADE**

Current: Basic Plotly line chart.
REQUIRED UPGRADE:
```python
# In page_strategy_builder():
1. Add BREAK-EVEN LINES as vertical dashed red lines on payoff chart
2. Add CURRENT SPOT vertical line (solid blue)
3. Add SHADED PROFIT ZONE (green fill above break-even)
4. Add SHADED LOSS ZONE (red fill below break-even)
5. Show RISK/REWARD RATIO badge: "R/R: 1:2.3" next to strategy name
6. Add P&L AT EXPIRY TABLE: spot_levels × [-10%, -5%, ATM-2, ATM, ATM+2, +5%, +10%]
7. Add "PLACE ALL LEGS" button that iterates over legs and calls place_order() for each
   with a confirmation dialog showing total premium debit/credit
```

**TASK 2.4 — INTELLIGENT AUTO-STOP SYSTEM**

IMPLEMENT `SmartStopManager` in `risk_monitor.py`:
```python
class SmartStopManager:
    """
    Per-position intelligent stop placement engine.
    ALGORITHM:
    1. For SHORT positions: initial stop at avg_price × (1 + stop_multiplier)
       - Default stop_multiplier = 2.0 (100% loss = stop)
       - Trail: if position moves in favor, raise stop to lock in premium × trail_lock_pct
    2. For LONG positions: initial stop at avg_price × (1 - stop_multiplier)
       - Default stop_multiplier = 0.5 (50% loss = stop)
    3. TIME-BASED STOP: For short options on expiry day, auto-close if:
       - Time > 15:15 IST AND position still open
    4. PORTFOLIO STOP: If total portfolio loss > max_portfolio_loss, trigger ALL stops
    """
```
WIRE TO: `RiskMonitor._check_positions()` — call `SmartStopManager.evaluate()` each poll cycle
UI: New "Smart Stops" tab in Risk Monitor page showing status per position

**TASK 2.5 — MULTI-EXPIRY STRATEGY SUPPORT**

Current: Strategy Builder assumes single expiry.
REQUIRED:
```
- Add "Calendar Spread" strategy: Buy near-month expiry, Sell far-month expiry
- Add "Diagonal Spread": Different strikes AND different expiries
- In StrategyLeg dataclass: expiry field is already present — ENFORCE it in UI
- In page_strategy_builder(): Add per-leg expiry selector when "Multi-Expiry" toggle is ON
- In generate_payoff_data(): Support legs with different expiries (different TTEs)
- In calculate_strategy_metrics(): Account for theta differential between expiries
```

---

### PLAN PHASE 3 — ADVANCED INTELLIGENCE (Sprint 3, Days 22–42)

**TASK 3.1 — IV SURFACE VISUALIZATION**

IMPLEMENT in `page_analytics()`:
```python
def render_iv_surface(df_chain_dict: Dict[str, pd.DataFrame], spot: float):
    """
    3D IV Surface using Plotly go.Surface.
    X-axis: Strikes (moneyness = strike/spot)
    Y-axis: Expiries (days to expiry)
    Z-axis: Implied Volatility (%)

    DATA REQUIREMENTS:
    - Fetch option chains for ALL available expiries (up to 6)
    - Calculate IV for each strike × expiry combination
    - Build meshgrid and interpolate missing values (scipy.interpolate.griddata)

    DISPLAY:
    - go.Surface with viridis colorscale
    - Contour lines enabled
    - Hover: strike, expiry, IV, delta
    - Side-by-side with IV Smile (2D slice at selected expiry)
    """
```
PERFORMANCE: Cache IV surface data at 5-minute TTL (expensive to compute — 6 expiries × 80 strikes)

**TASK 3.2 — POSITION HEATMAP DASHBOARD**

IMPLEMENT `render_portfolio_greeks_heatmap()` in `page_analytics()`:
```python
# Input: list of positions with computed Greeks
# Output: Plotly heatmap go.Heatmap
# Rows: each open position (symbol + strike + expiry)
# Columns: Delta, Gamma, Theta, Vega, Notional, P&L
# Color encoding: green=positive, red=negative, intensity=magnitude
# Footer row: PORTFOLIO TOTALS in bold
# Action: Click on row → navigate to Square Off page with that position pre-selected
```

**TASK 3.3 — TRADE JOURNAL & PERFORMANCE ANALYTICS**

IMPLEMENT new sub-page within Analytics named "📓 Trade Journal":
```
METRICS TO DISPLAY:
1. Win Rate % (by trade count)
2. Profit Factor (gross profit / gross loss)
3. Average Win / Average Loss
4. Max Consecutive Wins / Losses
5. Sharpe Ratio (daily P&L stream, risk-free = 6.5%)
6. Calmar Ratio (annualized return / max drawdown)
7. Daily P&L bar chart (last 30 trading days)
8. Monthly P&L heatmap calendar (GitHub contribution style)
9. Instrument breakdown: pie chart by instrument traded
10. Strategy breakdown: which strategies are most profitable

DATA SOURCE: TradeDB.get_trades() + TradeDB.get_pnl_history()
EXPORT: "📥 Download Performance Report (Excel)" — multi-sheet XLSX
  - Sheet 1: Summary metrics
  - Sheet 2: Daily P&L
  - Sheet 3: All trades
  - Sheet 4: Strategy breakdown
```

**TASK 3.4 — MARKET REGIME DETECTOR**

IMPLEMENT `detect_market_regime()` in `analytics.py`:
```python
def detect_market_regime(
    historical_df: pd.DataFrame,  # OHLCV daily data
    vix: float,
    pcr: float,
    spot: float,
) -> Dict[str, Any]:
    """
    REGIME CLASSIFICATION:
    1. TRENDING_UP: EMA20 > EMA50 > EMA200, ADX > 25, PCR < 0.8
    2. TRENDING_DOWN: EMA20 < EMA50 < EMA200, ADX > 25, PCR > 1.2
    3. RANGE_BOUND: ADX < 20, VIX < 15, abs(PCR - 1.0) < 0.2
    4. HIGH_VOLATILITY: VIX > 20 OR realized_vol_5d > implied_vol × 1.5
    5. PRE_EXPIRY: Days to expiry <= 5

    RETURNS:
    {
        "regime": "RANGE_BOUND",
        "confidence": 0.78,
        "recommended_strategies": ["Iron Condor", "Short Straddle"],
        "risk_level": "MEDIUM",
        "signals": {
            "trend": "sideways",
            "volatility": "low",
            "momentum": "neutral",
        }
    }
    """
```
UI: Show regime badge on Dashboard and Strategy Builder.
IN STRATEGY BUILDER: Filter strategy suggestions based on current regime.

**TASK 3.5 — REAL-TIME ALERT SYSTEM OVERHAUL**

UPGRADE `alerting.py`:
```
ADD: WhatsApp via Twilio API (AlertConfig.whatsapp_enabled + whatsapp_to)
ADD: Discord webhook (AlertConfig.discord_enabled + discord_webhook_url)
ADD: Custom alert templates (Jinja2-style with {symbol}, {strike}, {pnl} tokens)
ADD: Alert deduplication window (suppress same alert within 5 minutes)
ADD: Alert history pagination in Settings page (show last 100 alerts)
ADD: Alert sound in browser via HTML5 Audio API (st.components.v1.html injection)
```
TELEGRAM FORMAT UPGRADE:
```
🚨 STOP LOSS HIT — NIFTY 24000 CE
━━━━━━━━━━━━━━━━━━━━━
📍 Position: SELL 1 lot @ ₹45.00
⚡ Current: ₹95.00
💥 Loss: ₹3,750 (2.1% of capital)
⏰ Time: 11:42:37 IST
🎯 Action: AUTO-SQUARE OFF triggered
━━━━━━━━━━━━━━━━━━━━━
[View Position] [Dismiss]
```

---

### PLAN PHASE 4 — SCALABILITY & PRODUCTION HARDENING (Sprint 4, Days 43–60)

**TASK 4.1 — MULTI-ACCOUNT SUPPORT**

CURRENT: Single ICICI Breeze account per session.
REQUIRED:
```python
# In session_manager.py
class AccountProfile:
    profile_id: str
    display_name: str
    api_key: str          # ENCRYPTED at rest via cryptography.fernet
    api_secret: str       # ENCRYPTED
    totp_secret: str      # ENCRYPTED (optional — for auto-login)
    last_used: datetime
    is_active: bool

class MultiAccountManager:
    def list_profiles(self) -> List[AccountProfile]: ...
    def add_profile(self, profile: AccountProfile) -> None: ...
    def switch_to(self, profile_id: str) -> BreezeAPIClient: ...
    def delete_profile(self, profile_id: str) -> None: ...
```
UI: "Switch Account" dropdown in sidebar (show display_name, last_used)
SECURITY: ALL stored credentials MUST BE encrypted using Fernet symmetric encryption.
Keys derived from a master password entered at startup (NOT stored anywhere).

**TASK 4.2 — WEBSOCKET-FIRST QUOTE ENGINE**

CURRENT: Option chain data via REST polling (30s default).
REQUIRED UPGRADE:
```
1. Subscribe all displayed option chain strikes to WebSocket on page load
2. Update prices in-memory via TickStore.get_latest(token)
3. "Live" mode: show prices updating in place WITHOUT full page re-render
   (use st.empty() containers + streaming updates)
4. "Snapshot" mode: current REST polling behavior (keep as fallback)
5. Mode toggle: "🔴 Live WS" / "📦 Snapshot" in option chain header
6. Subscription management: unsubscribe all on page navigation
7. Memory management: clear TickStore for unsubscribed tokens
```
THIS IS THE MOST IMPACTFUL LATENCY IMPROVEMENT POSSIBLE.

**TASK 4.3 — DATABASE MIGRATION FRAMEWORK**

CURRENT: Schema created with `CREATE TABLE IF NOT EXISTS` — no versioning.
REQUIRED:
```python
# In persistence.py
SCHEMA_VERSION = 5  # Increment on every schema change

class DBMigrator:
    MIGRATIONS = {
        1: "ALTER TABLE trades ADD COLUMN notes TEXT",
        2: "CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date)",
        3: "CREATE TABLE IF NOT EXISTS market_regime_log ...",
        4: "ALTER TABLE alerts_log ADD COLUMN dispatched_channels TEXT",
        5: "CREATE INDEX IF NOT EXISTS idx_watchlist_symbol ON watchlist(symbol)",
    }

    def run(self, conn: sqlite3.Connection) -> None:
        current = self._get_version(conn)
        for v, sql in self.MIGRATIONS.items():
            if v > current:
                conn.execute(sql)
                self._set_version(conn, v)
        conn.commit()
```
RUN: On every `TradeDB.__init__()` call.

**TASK 4.4 — PROMETHEUS METRICS EXPANSION**

FILE: `app/lib/breeze_client.py`
ADD the following metrics:
```python
# Already present (keep):
REQUEST_COUNTER     # breeze_requests_total
REQUEST_LATENCY     # breeze_request_duration_seconds
INFLIGHT            # breeze_client_inflight_requests
CIRCUIT_STATE       # breeze_circuit_state
CIRCUIT_FAILURES    # breeze_circuit_failures

# ADD NEW:
ORDER_COUNTER = Counter("breeze_orders_total", "Orders placed", ["action", "instrument", "status"])
POSITION_GAUGE = Gauge("breeze_open_positions", "Open positions count")
PNL_GAUGE = Gauge("breeze_unrealized_pnl_inr", "Unrealized P&L in INR")
WEBSOCKET_SUBS = Gauge("breeze_ws_subscriptions", "Active WS subscriptions")
ALERT_COUNTER = Counter("breeze_alerts_dispatched_total", "Alerts sent", ["channel", "level"])
CACHE_HIT_RATE = Gauge("breeze_cache_hit_rate", "Cache hit rate by namespace", ["namespace"])
```
DASHBOARD: Add Grafana dashboard JSON to `k8s/grafana-dashboard.json`

**TASK 4.5 — KUBERNETES PRODUCTION HARDENING**

FILE: `k8s/deployment.yaml`
REQUIRED ADDITIONS:
```yaml
# Resource limits (MANDATORY for prod):
resources:
  requests:
    memory: "512Mi"
    cpu: "250m"
  limits:
    memory: "1Gi"
    cpu: "1000m"

# Liveness probe (MANDATORY):
livenessProbe:
  httpGet:
    path: /healthz
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10
  failureThreshold: 3

# Readiness probe (MANDATORY):
readinessProbe:
  httpGet:
    path: /ready
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 5

# Pod Disruption Budget (for zero-downtime deploys):
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: breeze-pdb
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: breeze-service

# Horizontal Pod Autoscaler:
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
spec:
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

---

## SECTION 4 — INNOVATION IDEAS (DIFFERENTIATORS)

### INNOVATION 1 — AI-POWERED STRATEGY SUGGESTER

**Concept**: Analyze current market conditions + trader's historical P&L to suggest the single best strategy.

```python
# In strategies.py
class AIStrategySuggester:
    def suggest(
        self,
        regime: Dict,           # From detect_market_regime()
        vix: float,
        pcr: float,
        trader_win_rates: Dict[str, float],  # strategy_name → historical win rate
        available_capital: float,
        days_to_expiry: int,
    ) -> List[SuggestionResult]:
        """
        SCORING ALGORITHM (0-100 per strategy):
        1. Regime fit score (0-30): Does strategy match current regime?
        2. Historical performance score (0-25): Trader's own win rate for this strategy
        3. Risk/Reward score (0-20): R/R ratio vs current VIX premium
        4. Capital efficiency score (0-15): Margin required vs available capital
        5. Time decay score (0-10): Is DTE in optimal range for this strategy?

        RANK strategies by total score. Return top 3 with explanations.
        """
```

UI: Show in Strategy Builder as "🤖 AI Suggests for Today" collapsible card.

### INNOVATION 2 — EXPIRY DAY AUTOPILOT

**Concept**: On expiry day, run automated pre-close position management.

```python
class ExpiryDayAutopilot:
    """
    TRIGGERS WHEN: date.today() == any open position's expiry date

    ACTIONS (all require explicit user activation — NO autonomous trading by default):
    1. 14:00 IST — Show "Expiry Day Warning" banner with OTM/ITM status of all positions
    2. 14:30 IST — Show countdown timer to close
    3. 15:00 IST — AUTO-CLOSE alert: "15 minutes to close. {N} positions expiring today."
    4. 15:15 IST — If user enabled "Expiry Autopilot", place market square-off orders
                   for ALL positions expiring today (with final confirm dialog)
    5. 15:25 IST — Emergency close for any remaining expiry positions (CRITICAL alert)
    """
```

### INNOVATION 3 — BASKET ORDER TEMPLATES

**Concept**: Save any multi-leg strategy as a named "basket template" and replay it next week.

```python
# In persistence.py — ADD TABLE:
CREATE TABLE IF NOT EXISTS basket_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    instrument TEXT NOT NULL,
    strategy_type TEXT NOT NULL,
    legs_json TEXT NOT NULL,        -- JSON: [{offset, type, action, qty_multiplier}]
    created_at TEXT NOT NULL,
    last_used TEXT,
    use_count INTEGER DEFAULT 0
);

# In page_strategy_builder():
# ADD: "💾 Save as Template" button after strategy leg configuration
# ADD: "📂 Load Template" dropdown showing saved baskets
# LOGIC: On load, regenerate legs with current ATM strike but same offsets/types/actions
```

### INNOVATION 4 — CIRCUIT BREAKER DASHBOARD

**Concept**: Visual circuit breaker state for all monitored instruments.

```
NSE CIRCUIT BREAKER MONITOR
━━━━━━━━━━━━━━━━━━━━━━━━━━━
NIFTY     ────── ●NORMAL ────── | Limit: ±10% (2,250pts) | Distance: 847pts (37.6%)
BANKNIFTY ────── ●NORMAL ────── | Limit: ±10% (5,150pts) | Distance: 2,100pts (40.8%)
FINNIFTY  ────── ⚠️CAUTION ──── | Limit: ±10% | Distance: 210pts (9.3%) [< 15% away]

Market-wide circuit breakers: 10% / 15% / 20%
Current market move: +0.8%
```

SHOW: On Dashboard as a collapsible "Market Circuit Breakers" card.

### INNOVATION 5 — VOICE TRADE CONFIRMATION

**Concept**: Browser-based text-to-speech readback of order details before placement.

```javascript
// Injected via st.components.v1.html()
function readOrderBack(instrument, strike, action, qty, price) {
    const msg = new SpeechSynthesisUtterance(
        `Confirm order: ${action} ${qty} lots of ${instrument} ${strike} at ${price} rupees per share.`
    );
    msg.rate = 0.9;
    msg.lang = 'en-IN';
    window.speechSynthesis.speak(msg);
}
```

ACTIVATE: As an optional setting ("🔊 Voice Confirmations") in Settings page.
SECURITY: ONLY speaks on user-initiated order placement, NEVER on automated actions.

### INNOVATION 6 — REALIZED VS IMPLIED VOLATILITY DASHBOARD

**Concept**: Show IV vs RV premium as a tradeable signal.

```
IV vs RV SPREAD MONITOR (VRP — Volatility Risk Premium)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Instrument    ATM IV%    RV-5d%    VRP    Signal
NIFTY 50      14.2%      9.8%     +4.4%   🟢 SELL VOLATILITY (IV > RV by 45%)
BANKNIFTY     18.7%      22.1%    -3.4%   🔴 BUY VOLATILITY  (RV > IV by 18%)
FINNIFTY      12.5%      11.2%    +1.3%   ⚪ NEUTRAL

VRP Threshold: > 30% → strong sell signal; < -15% → strong buy signal
```

DATA: ATM IV from current option chain; RV-5d from historical OHLCV (already in historical.py)

---

## SECTION 5 — TESTING STRATEGY (COMPLETE)

### 5.1 Unit Test Coverage Requirements

ALL OF THE FOLLOWING MUST HAVE 100% BRANCH COVERAGE:
```
tests/unit/
├── test_analytics.py          # bs_price, calculate_greeks, solve_iv, stress_test
├── test_strategies.py         # generate_strategy_legs, calculate_strategy_metrics
├── test_risk_monitor.py       # stop triggers, portfolio limits, trailing stop
├── test_alerting.py           # TelegramDispatcher, EmailDispatcher (with mocks)
├── test_persistence.py        # TradeDB CRUD, migration runner
├── test_live_feed.py          # TickStore, BarBuilder, token resolution
├── test_breeze_api.py         # Retry logic, rate limiter, error classification
├── test_helpers.py            # safe_int, safe_float, process_option_chain
├── test_session_manager.py    # TOTP, credential store, cache TTL
├── test_paper_trading.py      # Order placement, fill simulation, P&L calc
├── test_gtt_manager.py        # GTT creation, trigger, cancellation
├── test_futures.py            # Expiry calculation, holiday adjustment
└── test_holiday_calendar.py   # NSE API fetch, fallback, cache
```

### 5.2 Integration Test Plan

```
tests/integration/
├── test_auth_flow.py          # Real TOTP → session token → API call
├── test_option_chain.py       # Fetch live NIFTY chain, validate structure
├── test_order_lifecycle.py    # Place → confirm → cancel (paper only in CI)
├── test_live_feed.py          # WS connect → subscribe → receive tick → unsubscribe
└── test_persistence.py        # Write trades → read back → export CSV
```

INTEGRATION TESTS: MUST auto-skip when `BREEZE_API_KEY` env var is absent.
MARK: `@pytest.mark.integration` on ALL integration tests.

### 5.3 Performance Benchmarks

```python
# pytest-benchmark targets:
benchmark_analytics:
    bs_price() < 0.1ms per call
    calculate_greeks() < 0.5ms per call
    solve_iv() < 2ms per call (including Newton-Raphson + Brent fallback)

benchmark_option_chain:
    process_option_chain(80 strikes) < 50ms
    add_greeks_to_chain(80 strikes) < 500ms

benchmark_database:
    TradeDB.add_trade() < 5ms
    TradeDB.get_trades(last_30_days) < 20ms
```

---

## SECTION 6 — CI/CD PIPELINE SPEC

### 6.1 GitHub Actions — Complete Workflow

```yaml
# .github/workflows/ci.yml — FULL SPECIFICATION

name: Breeze PRO CI
on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - name: Install deps
        run: pip install -r requirements.txt
      - name: Lint (ruff)
        run: ruff check . --select E,F,W,I,N
      - name: Format check (ruff format)
        run: ruff format --check .
      - name: Security scan (bandit)
        run: bandit -q -r . -x tests/,./data/
      - name: Type check (mypy)
        run: mypy app/lib/ --ignore-missing-imports

  test:
    runs-on: ubuntu-latest
    needs: quality
    steps:
      - name: Unit tests + coverage
        run: pytest tests/unit/ --cov=. --cov-report=xml --cov-fail-under=80
      - name: Upload coverage to Codecov
        uses: codecov/codecov-action@v4

  docker:
    runs-on: ubuntu-latest
    needs: test
    steps:
      - name: Build Docker image
        run: docker build -t breeze-pro:${{ github.sha }} .
      - name: Run container healthcheck
        run: |
          docker run -d --name test-container -p 8000:8000 breeze-pro:${{ github.sha }}
          sleep 15
          curl -f http://localhost:8000/healthz
          docker stop test-container
```

### 6.2 Dockerfile Optimization

```dockerfile
# REQUIRED DOCKERFILE IMPROVEMENTS:

# Stage 1: Builder
FROM python:3.11-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Runtime (minimal image)
FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY . .

# SECURITY: Non-root user (MANDATORY for production)
RUN useradd -m -u 1000 breeze && chown -R breeze:breeze /app
USER breeze

# Create required directories
RUN mkdir -p logs data

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/healthz || exit 1

# Streamlit runs on 8501, FastAPI on 8000
EXPOSE 8501 8000
```

---

## SECTION 7 — CONFIGURATION MANAGEMENT SPEC

### 7.1 Environment Variables (Complete List)

```bash
# REQUIRED (app will refuse to start without these):
BREEZE_API_KEY=your_icici_api_key
BREEZE_API_SECRET=your_icici_api_secret
BREEZE_SESSION_TOKEN=your_session_token  # OR use TOTP flow

# OPTIONAL — API behavior:
BREEZE_USE_PRODUCTION_CLIENT=true         # Use app/lib/breeze_client.py
MAX_REQUESTS_PER_MINUTE=100               # Rate limit
MAX_REQUESTS_PER_DAY=5000                 # Daily quota
BREEZE_BASE_URL=https://api.icicidirect.com  # Override for testing

# OPTIONAL — Risk defaults:
DEFAULT_MAX_PORTFOLIO_LOSS=50000          # INR
DEFAULT_MAX_DELTA=500
DEFAULT_MARGIN_WARNING_PCT=75
DEFAULT_MARGIN_CRITICAL_PCT=90

# OPTIONAL — Alerting:
TELEGRAM_BOT_TOKEN=bot1234567890:ABC...
TELEGRAM_CHAT_ID=-1001234567890
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=alerts@yourdomain.com
SMTP_PASS=app_password_here
ALERT_TO_EMAIL=trader@yourdomain.com

# OPTIONAL — Monitoring:
PROMETHEUS_ENABLED=true
PROMETHEUS_PORT=9090

# OPTIONAL — Master password for credential encryption:
BREEZE_MASTER_PASSWORD=your_secure_master_password
```

### 7.2 Streamlit Secrets (`.streamlit/secrets.toml`)

```toml
# NEVER COMMIT THIS FILE
BREEZE_API_KEY = "your_api_key"
BREEZE_API_SECRET = "your_api_secret"
# SESSION_TOKEN is obtained at runtime via TOTP — do not store here
```

---

## SECTION 8 — SECURITY HARDENING CHECKLIST

ALL MUST PASS BEFORE PRODUCTION DEPLOYMENT:

```
[ ] API keys NEVER logged (verify in breeze_api.py and session_manager.py)
[ ] Session tokens NEVER appear in Streamlit URL params
[ ] SQLite DB has file permissions 0600 (set in persistence.py __init__)
[ ] Fernet encryption applied to stored API credentials in account profiles
[ ] TOTP secret NEVER stored in plaintext — only in encrypted SQLite
[ ] Bandit security scan passes with zero HIGH findings
[ ] No `verify=False` in any requests.Session() call
[ ] Webhook signature verification (HMAC-SHA256) implemented and tested
[ ] Rate limiter tested against burst scenarios (verify no bypass possible)
[ ] All user inputs sanitized before SQL (use parameterized queries everywhere)
[ ] No eval() or exec() anywhere in codebase
[ ] Docker container runs as non-root user (UID 1000)
[ ] Kubernetes NetworkPolicy restricts ingress to port 8501/8000 only
[ ] Secrets injected via K8s Secrets (not ConfigMap) and mounted as env vars
```

---

## SECTION 9 — OPERATOR RUNBOOK

### Incident Response Playbook

```
INCIDENT: API calls all returning "invalid session"
  1. Check session token age: Settings → Session Info → Login Time
  2. If > 8 hours: Settings → Re-authenticate → Generate new TOTP → Reconnect
  3. If < 8 hours: Check ICICI Breeze server status
  4. If Breeze API down: app will degrade gracefully to cached data
  RECOVERY TIME TARGET: < 5 minutes

INCIDENT: Risk monitor not firing alerts
  1. Settings → Risk Monitor → Check daemon status (Running/Stopped badge)
  2. If stopped: click "Start Monitor" button
  3. Check logs: Settings → View Logs → filter for "RiskMonitor"
  4. Check alerting: Settings → Alerts → Test Telegram/Email
  RECOVERY TIME TARGET: < 2 minutes

INCIDENT: WebSocket feed showing stale data (>60s)
  1. Dashboard → WS Status badge should show "⚠️ Stale"
  2. Click "🔄 Reconnect WS" button in sidebar
  3. If reconnect fails: switch to REST polling mode (toggle in chain options)
  4. Check live_feed.py logs for token resolution errors
  RECOVERY TIME TARGET: < 1 minute

INCIDENT: Database corruption / lock timeout
  1. Stop the app (k8s: kubectl rollout restart deployment/breeze-pro)
  2. Run: python -c "from persistence import TradeDB; TradeDB()._verify_integrity()"
  3. If corrupt: restore from data/backups/ (nightly backup required)
  4. Apply pending migrations: python -c "from persistence import DBMigrator; ..."
  RECOVERY TIME TARGET: < 15 minutes
```

---

## SECTION 10 — CODEX RALPH MODE EXECUTION INSTRUCTIONS

### HOW TO FEED THIS SPEC TO CODEX

1. PROVIDE THE ENTIRE CODEBASE AS CONTEXT (all .py files)
2. START WITH: "You are an expert Python engineer working on Breeze PRO, a production options trading terminal. Read the attached codebase thoroughly. Then execute the following tasks in order."
3. FOR EACH PLAN TASK, PROVIDE AS A SEPARATE PROMPT:
   ```
   TASK: [TASK ID FROM SECTION 3]
   CONTEXT: [paste the relevant existing code]
   REQUIREMENT: [paste the task specification from Section 3]
   CONSTRAINTS:
   - ALL existing tests must continue to pass
   - Follow PEP 8 + ruff formatting rules
   - Add docstrings to all new functions
   - Add type hints to all new function signatures
   - Handle errors with specific exception types, never bare except
   - Log significant actions with log.info() / log.warning() / log.error()
   OUTPUT: Provide complete replacement file(s), not diffs
   ```
4. AFTER EACH TASK: Run `pytest tests/unit/ -x` before moving to next task
5. AFTER PHASE 2: Run `bandit -r . -x tests/` and fix all HIGH findings
6. AFTER PHASE 3: Run full integration test suite with live credentials
7. AFTER PHASE 4: Run Docker build + k8s dry-run apply

### RALPH MODE CONTRACT

```
RALPH MODE = RELENTLESS AUTONOMOUS LARGE-SCALE PRODUCTION HARDENING

Rules:
1. NEVER SKIP A TEST — if it's red, fix it before proceeding
2. NEVER SILENCE AN EXCEPTION — log it, handle it, or re-raise it
3. NEVER HARDCODE CREDENTIALS — use env vars or st.secrets
4. NEVER USE BARE EXCEPT — always catch specific exception types
5. NEVER MODIFY ORDER PLACEMENT WITHOUT EXPLICIT APPROVAL
6. ALWAYS ADD TYPE HINTS TO NEW FUNCTIONS
7. ALWAYS WRITE THE TEST BEFORE THE IMPLEMENTATION
8. ALWAYS RUN BANDIT AFTER ADDING USER INPUT HANDLING
9. ALWAYS BENCHMARK PERFORMANCE-CRITICAL PATHS
10. ALWAYS UPDATE THE RUNBOOK WHEN ADDING NEW FAILURE MODES
```

---

## APPENDIX A — INSTRUMENT REFERENCE TABLE

| Instrument | Exchange | Lot Size | Strike Gap | Expiry Day | Weekly? |
|------------|----------|----------|------------|------------|---------|
| NIFTY | NFO | 75 | 50 | Thursday | YES |
| BANKNIFTY | NFO | 30 | 100 | Wednesday | YES |
| FINNIFTY | NFO | 40 | 50 | Tuesday | YES |
| MIDCPNIFTY | NFO | 75 | 25 | Monday | YES |
| SENSEX | BFO | 10 | 100 | Friday | YES |
| BANKEX | BFO | 15 | 100 | Monday | YES |

ALL INSTRUMENTS: Monthly expiry = last Thursday of month (adjusted for holidays)
NSE CIRCUIT BREAKERS: 10% / 15% / 20% (market-wide); individual stocks: 5% / 10% / 20%
IST = UTC+5:30 — ALL timestamps MUST use IST for display

---

## APPENDIX B — API ERROR CODE REFERENCE

| Error Pattern | Classification | Action |
|---------------|----------------|--------|
| `invalid session` | PERMANENT | Clear credentials, force re-login |
| `session expired` | PERMANENT | Clear credentials, force re-login |
| `unauthorized` / `forbidden` | PERMANENT | Alert user, do not retry |
| `service unavailable` / `503` | TRANSIENT | Retry with backoff |
| `too many requests` / `429` | TRANSIENT | Retry after 2s × attempt |
| `connection reset` / `504` | TRANSIENT | Retry with backoff |
| `bad gateway` / `502` | TRANSIENT | Retry with backoff |
| Any order placement error | NON-RETRYABLE | Log + alert, return error to UI |

---

## APPENDIX C — DATABASE SCHEMA (COMPLETE v5)

```sql
-- VERSION TABLE
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

-- TRADES
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT UNIQUE,
    timestamp TEXT NOT NULL,
    date TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    exchange TEXT NOT NULL,
    strike INTEGER,
    option_type TEXT,
    expiry TEXT,
    action TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    order_type TEXT,
    status TEXT DEFAULT 'executed',
    pnl REAL DEFAULT 0,
    notes TEXT,
    strategy_name TEXT,       -- NEW v4
    session_id TEXT           -- NEW v4 (for multi-account)
);

-- P&L HISTORY
CREATE TABLE IF NOT EXISTS pnl_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    realized_pnl REAL DEFAULT 0,
    unrealized_pnl REAL DEFAULT 0,
    premium_sold REAL DEFAULT 0,
    premium_bought REAL DEFAULT 0,
    num_trades INTEGER DEFAULT 0,
    regime TEXT,              -- NEW v5 (market regime at close)
    UNIQUE(date)
);

-- BASKET TEMPLATES (NEW v5)
CREATE TABLE IF NOT EXISTS basket_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    instrument TEXT NOT NULL,
    strategy_type TEXT NOT NULL,
    legs_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used TEXT,
    use_count INTEGER DEFAULT 0
);

-- INDICES
CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date);
CREATE INDEX IF NOT EXISTS idx_trades_stock ON trades(stock_code, expiry);
CREATE INDEX IF NOT EXISTS idx_watchlist_symbol ON watchlist(symbol);
CREATE INDEX IF NOT EXISTS idx_pnl_date ON pnl_history(date);
```

---

*END OF SPEC — BREEZE PRO CODEX RALPH MODE v12.0*
*Generated: March 2026 | Total Pages: 15 | Total Modules: 22 | Test Files: 17*
*Lines of Production Code: 8,154 | Target Post-Sprint: 12,000+*
