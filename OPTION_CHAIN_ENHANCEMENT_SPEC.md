# Option Chain Enhancement Spec

## Purpose

Design the next-generation option-chain workspace for Breeze PRO so it moves from a useful table view to a best-in-class analysis surface for discretionary traders, premium sellers, strategy builders, and intraday options flow analysis.

This spec is grounded in the current implementation:

- `app.py` `page_option_chain()`
- `helpers.py` option-chain transforms and analytics
- `breeze_api.py` chain fetch wrappers
- `live_feed.py` token resolution and tick ingestion
- `persistence.py` option-chain history persistence

## Current State Assessment

### What already works well

- Snapshot chain fetch is correct and explicit for both calls and puts.
- Spot-based ATM estimation is present and better than a naive midpoint.
- The page supports:
  - ATM strike filtering
  - live WebSocket LTP overlay
  - Greeks enrichment
  - PCR and Max Pain summary metrics
  - OI heatmap
  - volume spike badge
  - IV percentile toggle
  - IV smile
  - OI / change-in-OI bar charts
  - CSV export
- Daily option-chain snapshots are already persisted for:
  - IV history
  - volume baseline history

### Structural limitations in the current code

1. The page is monolithic.
   `page_option_chain()` in `app.py` owns fetch, cache, transform, enrichment, live overlay, metrics, and rendering. That blocks deeper feature growth and makes testing expensive.

2. Live mode is only partially live.
   WebSocket overlay currently updates LTP for visible strikes, but not the full market microstructure. OI, OI change, bid/ask, spread, volume acceleration, and liquidity state are not streamed into the working table.

3. Historical option-chain persistence is too coarse for top-end analytics.
   `option_chain_history` stores one row per day per strike/side. That is enough for crude IV percentile and average volume, but not for:
   - intraday skew shifts
   - OI build-up trajectories
   - gamma wall movement
   - session replay
   - time-sliced liquidity analytics

4. Charting is still basic.
   Current charts are mostly `st.bar_chart()` and `st.line_chart()`. They are useful, but not enough for:
   - linked crosshair analysis
   - multi-axis chain studies
   - expiry comparison
   - surface/heatmap analysis
   - dealer positioning charts

5. The page is table-first, not workflow-first.
   The user can inspect the chain, but the UI does not yet optimize for common trading questions:
   - Where are the call and put walls?
   - Which strikes are building fresh OI vs short covering?
   - How is skew changing intraday?
   - Is premium rich or cheap vs realized and vs nearby expiries?
   - Which strikes are liquid enough to trade now?

6. Current analytics are mostly per-expiry.
   Serious options analysis needs multi-expiry context, especially:
   - front vs next expiry skew
   - term structure
   - event premium
   - expected move by expiry

### Root constraints discovered from the codebase

- Chain fetch is driven by Breeze snapshot API plus a separate WebSocket subsystem.
- Existing persistence is SQLite-backed and suitable for extension.
- Existing tests cover helpers and persistence, but not a deep option-chain UI/service layer.
- Existing daily snapshot schema uses a uniqueness key of:
  - `trade_date`
  - `instrument`
  - `expiry`
  - `strike`
  - `option_type`

That daily granularity must remain for lightweight baselines, but a new intraday snapshot layer is required for advanced analytics.

## Product Goal

Create an option-chain workspace that answers, in one screen:

- Where is the market positioned now?
- How is positioning changing during the session?
- Which strikes/expiries are attractive for premium selling or buying?
- Where is liquidity usable or dangerous?
- What does volatility structure imply across strikes and expiries?

## Non-Goals

- Full execution-terminal replacement for all pages.
- Tick-by-tick institutional order-flow reconstruction from exchange-level trade prints.
- Level-2 depth charting beyond what Breeze feed fields can reliably support.

## Target User Workflows

### 1. Premium seller

Needs:

- ATM and OTM liquidity
- IV percentile / IV rank
- skew shape
- OI build-up and unwinding
- nearest support/resistance walls
- expected move band

### 2. Directional options trader

Needs:

- call/put momentum by strike cluster
- volume bursts
- OI confirmation vs price action
- skew steepening/flattening
- expiry comparison

### 3. Strategy builder

Needs:

- strike selection recommendations
- payoff context tied to live IV and liquidity
- spread quality and slippage risk
- nearby expiry comparison

### 4. Intraday analyst

Needs:

- replay of chain changes
- change-since-open
- time-window heatmaps
- fast anomaly detection

## UX Vision

### Desktop layout

Three-zone workspace:

1. Top Market Structure Rail
   - spot
   - futures basis if available
   - ATM strike
   - PCR
   - Max Pain
   - IV rank
   - expected move
   - DTE
   - regime tag

2. Center Chain Ladder
   - calls on left
   - strike in center
   - puts on right
   - sortable, color-coded, sticky ATM row
   - row pinning for user-marked strikes

3. Right Analysis Panel
   - chart tabs
   - regime summary
   - alerts
   - tradeability / liquidity diagnostics

### Mobile / narrow layout

- collapsible control drawer
- chain table first
- chart tabs below
- reduced chart count
- only core metrics visible above fold

## Feature Pillars

## 1. Chain Ladder Redesign

Replace the current table presentation with a proper ladder model.

### Requirements

- Single centered strike column.
- Calls and puts aligned on the same strike row.
- Sticky ATM row and optional sticky spot marker.
- Pinned rows for:
  - ATM
  - Max Pain
  - highest call OI
  - highest put OI
  - user favorites
- Column groups:
  - price
  - OI
  - change in OI
  - volume
  - IV
  - Greeks
  - liquidity
  - flow state

### Derived columns

- spread
- spread %
- mid price
- bid/ask imbalance
- OI build-up classification:
  - long build-up
  - short build-up
  - short covering
  - long unwinding
- distance from spot
- notional OI
- IV z-score
- IV percentile
- liquidity score

## 2. Charting Suite

All serious visuals should move to Plotly figures with linked cursor behavior, unified hover, export support, and synchronized strike/expiry selection.

### Core chart modules

| Chart | Purpose | Minimum interaction |
| --- | --- | --- |
| OI Profile | Call/put OI by strike | hover, ATM marker, max-pain marker |
| Delta OI Profile | fresh positioning by strike | hover, time-window toggle |
| Volume Burst Profile | unusual participation | threshold slider |
| IV Smile | strike-wise skew for selected expiry | call/put overlay, ATM marker |
| IV Term Structure | ATM IV across expiries | expiry hover, event markers |
| IV Surface | strike × expiry structure | rotate, slice by expiry or strike |
| Expected Move Cone | implied move by expiry | compare vs realized move |
| Gamma Exposure Profile | estimated dealer gamma by strike | wall markers, spot marker |
| Vanna / Charm Profile | second-order positioning pressure | expiry filter |
| Liquidity Scatter | spread vs volume vs OI | bubble size by notional |
| OI Heatmap | strike × time heatmap | replay slider, session anchor |
| Skew Shift Replay | intraday smile changes | play/pause and snapshot compare |

### Best-in-class chart behavior

- linked hover across all strike-based charts
- synced vertical strike marker
- synced spot/ATM marker
- click chart point to jump to table row
- click table row to highlight chart traces
- export current chart as PNG and CSV
- theme-consistent annotations and wall markers

## 3. Multi-Expiry Analysis

Current page is single-expiry centric. The enhanced workspace must add controlled multi-expiry analysis without overwhelming the main ladder.

### Required capabilities

- expiry strip with side-by-side metrics:
  - DTE
  - ATM IV
  - IV rank
  - total call OI
  - total put OI
  - PCR
  - expected move
- compare up to 3 expiries in charts
- expiry overlay in:
  - IV smile
  - OI profile
  - ATM IV term structure
- event premium detector:
  - flag front expiry vs next expiry distortion

## 4. Intraday Change Analytics

This is the biggest missing capability today.

### New analysis views

- change since open
- change over last 5 / 15 / 30 / 60 minutes
- replay slider for stored intraday snapshots
- session high / low IV by strike
- moving gamma walls
- top 10 strikes by:
  - OI addition
  - OI reduction
  - volume burst
  - spread widening

### Required alerts

- call wall shift
- put wall shift
- skew steepening beyond threshold
- ATM IV jump
- spread blowout at monitored strikes
- unusual volume at pinned strikes

## 5. Decision Support Layer

Add a small opinionated analysis summary generated deterministically from chain state.

### Examples

- "Put writing strongest at 22,300 and 22,400; support zone strengthening."
- "Call OI concentrated at 22,700 but change-in-OI is fading."
- "Front expiry IV elevated vs next expiry by 3.8 vol points."
- "Liquidity poor beyond 2.5% OTM; avoid wide-leg execution there."

This should be rule-based first, not LLM-based.

## Data and Storage Spec

## Existing table to retain

Keep `option_chain_history` as the lightweight daily aggregate store for:

- IV percentile
- average volume baselines
- historical strike activity summaries

## New table required

Add `option_chain_intraday_snapshots`.

### Proposed schema

```sql
CREATE TABLE option_chain_intraday_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_ts TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    instrument TEXT NOT NULL,
    expiry TEXT NOT NULL,
    strike INTEGER NOT NULL,
    option_type TEXT NOT NULL,
    ltp REAL DEFAULT 0,
    bid REAL DEFAULT 0,
    ask REAL DEFAULT 0,
    bid_qty REAL DEFAULT 0,
    ask_qty REAL DEFAULT 0,
    volume REAL DEFAULT 0,
    open_interest REAL DEFAULT 0,
    oi_change REAL DEFAULT 0,
    iv REAL DEFAULT 0,
    delta REAL DEFAULT 0,
    gamma REAL DEFAULT 0,
    theta REAL DEFAULT 0,
    vega REAL DEFAULT 0,
    spot REAL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'snapshot',
    UNIQUE(snapshot_ts, instrument, expiry, strike, option_type)
);
```

### Indexes

- `(instrument, expiry, snapshot_ts)`
- `(instrument, trade_date, snapshot_ts)`
- `(instrument, expiry, strike, option_type, snapshot_ts)`

### Snapshot policy

- snapshot mode:
  - persist every manual refresh
  - optional scheduled snapshot every 5 minutes while page active
- live mode:
  - aggregate WebSocket updates into 1-minute bars per strike/side
  - persist only finalized intervals

## Service / Module Refactor

The page should be split before major enhancements continue.

### New modules

- `option_chain_service.py`
  - fetch snapshot chain
  - merge live overlay
  - cache orchestration
  - view-model assembly

- `option_chain_metrics.py`
  - PCR
  - Max Pain
  - expected move
  - liquidity score
  - OI build-up classification
  - IV rank / percentile / z-score
  - gamma / vanna / charm profiles

- `option_chain_charts.py`
  - all Plotly builders for the chain workspace

- `option_chain_state.py`
  - UI state serialization
  - pinned strikes
  - selected expiry set
  - selected chart
  - replay timestamp

- `option_chain_alerts.py`
  - deterministic alert rules on chain movement

### Existing files to slim down

- `app.py`
  - keep layout composition only
- `helpers.py`
  - keep generic transforms only

## Analytics Definitions

### OI build-up classification

By strike and side, classify with price and OI direction:

- price up + OI up = long build-up
- price down + OI up = short build-up
- price up + OI down = short covering
- price down + OI down = long unwinding

### Liquidity score

Weighted score using:

- bid/ask spread %
- bid + ask quantity
- traded volume
- OI
- quote freshness

### Expected move

For each expiry:

- use ATM straddle
- or ATM IV-derived move as fallback
- show both when possible

### Gamma / Vanna / Charm

Use existing Greek machinery where possible, but aggregate by strike and expiry:

- net gamma by strike
- gamma wall candidates
- vanna pressure zones
- charm decay zones near expiry

### IV rank and percentile

For each expiry and for selected strike groups:

- ATM IV rank over 30/60/90 sessions
- strike-level IV percentile using historical snapshots

## UI Controls Spec

### Primary controls

- instrument
- expiry
- compare expiries
- quote mode
- replay mode
- strike range / show all
- strike distance bucket
- chart tab

### Advanced controls

- Greeks on/off
- normalize by notional / lots / absolute values
- smooth curves on/off
- pin ATM / max pain / walls
- show only liquid strikes
- show only unusual activity
- show only monitored strikes

## Performance Requirements

### Snapshot performance

- manual refresh to render complete in under 2.5 seconds for NIFTY-class chains on warm cache
- chart rebuild under 400 ms for filtered views

### Live performance

- visible chain updates under 500 ms from tick ingestion
- no full-table rerender on every tick
- debounce chart redraws to 750 ms

### Memory / storage

- intraday snapshot retention:
  - full resolution for 7 trading days
  - downsampled retention for 30 trading days
- daily aggregate retention:
  - 180 trading days minimum

## Testing Spec

### Unit tests

- `option_chain_metrics.py`
  - PCR
  - Max Pain
  - expected move
  - liquidity score
  - OI build-up state
  - gamma wall detection

- `option_chain_service.py`
  - cache hit path
  - cache invalidation path
  - snapshot + live merge
  - strike filtering and pinning

- `option_chain_charts.py`
  - figure construction
  - annotations
  - wall markers
  - multi-expiry traces

### Persistence tests

- schema migration for intraday snapshots
- 1-minute aggregation correctness
- retention cleanup correctness

### Integration tests

- page renders with:
  - snapshot only
  - live overlay
  - no spot available
  - missing one side of chain
  - illiquid strikes

### Deterministic golden-data tests

Add fixture-driven option-chain datasets for:

- balanced market
- put-heavy defensive market
- call-wall heavy trending-up market
- expiry-day distorted market
- illiquid far OTM market

These fixtures should drive both metrics tests and chart snapshot tests.

## Phased Delivery Plan

## Phase 1: Foundation and Refactor

- split service, metrics, and charts out of `app.py`
- add intraday snapshot table and migration
- persist intraday snapshots
- create deterministic fixtures and service tests

### Acceptance

- no behavior regression in current option-chain page
- existing helper tests still pass
- new service tests cover cache/fetch paths

## Phase 2: Chain Ladder and Core Charts

- build proper ladder view
- replace basic OI and IV smile charts with Plotly modules
- add linked hover and strike selection
- add liquidity columns and spread analytics

### Acceptance

- user can move between ladder row and chart highlights
- ATM, max pain, highest OI walls render clearly

## Phase 3: Multi-Expiry and Intraday Replay

- expiry comparison strip
- term structure and IV surface
- intraday replay slider
- OI heatmap over time

### Acceptance

- replay works off stored intraday snapshots
- compare-expiry charts stay responsive

## Phase 4: Dealer Positioning and Alerts

- gamma, vanna, charm views
- wall shift alerts
- rule-based chain commentary
- strike monitor watchlist

### Acceptance

- alerts are deterministic
- summary commentary matches fixture expectations

## Design Principles

- keep raw numbers inspectable; never hide the table under charts
- every advanced chart must map back to a strike and expiry the user can trade
- default view should stay usable for retail traders, with advanced views opt-in
- all premium/flow interpretations must be deterministic and explainable
- avoid adding charts that cannot be trusted from available data quality

## Immediate Recommendations

If implementation starts now, the highest-value first slice is:

1. refactor `page_option_chain()` into service + charts modules
2. add intraday snapshot persistence
3. replace current OI and IV smile visuals with proper Plotly charts
4. add liquidity score and build-up classification
5. add multi-expiry term structure and expected move analysis

This sequence delivers meaningful improvement quickly without overcommitting to speculative analytics before the data foundation exists.
