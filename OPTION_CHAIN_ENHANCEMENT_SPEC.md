# Option Chain Enhancement Build Plan

## Goal

Convert the current option-chain page into a modular workspace that supports:

- a proper call/strike/put ladder
- richer Plotly-based analytics
- multi-expiry comparison
- intraday snapshot replay
- deterministic alerts and commentary

This plan is intentionally implementation-first. It is organized by delivery phase, with exact file-level tasks and phase acceptance tests.

## Current Baseline

The current option-chain feature already provides:

- snapshot chain fetch for calls and puts
- ATM strike filtering
- live LTP overlay
- Greeks enrichment
- PCR and Max Pain
- OI heatmap
- IV smile
- OI/change-in-OI charts
- CSV export
- daily persistence for IV history and volume baseline history

The main constraints are:

- `app.py` owns too much of the option-chain flow
- live updates do not fully model liquidity and positioning state
- persistence is daily, not intraday
- charting is still basic
- testing is thin around a dedicated option-chain service layer

## Delivery Rules

- Keep the current option-chain page functional throughout the refactor.
- Preserve `option_chain_history` for lightweight daily baselines.
- Add new modules instead of expanding `page_option_chain()` further.
- Prefer deterministic analytics over heuristic or LLM-style interpretation.
- Each phase must end with runnable acceptance tests before starting the next phase.

## Target Files

### Existing files expected to change

- `app.py`
- `helpers.py`
- `persistence.py`
- `live_feed.py`
- `charts.py`
- `tests/integration/test_option_chain.py`
- `tests/integration/test_persistence.py`
- `tests/unit/test_helpers.py`
- `tests/unit/test_persistence_unit.py`
- `tests/unit/test_charts.py`

### New files expected to be added

- `option_chain_service.py`
- `option_chain_metrics.py`
- `option_chain_charts.py`
- `option_chain_state.py`
- `option_chain_alerts.py`
- `tests/unit/test_option_chain_metrics.py`
- `tests/unit/test_option_chain_service.py`
- `tests/unit/test_option_chain_charts.py`
- `tests/unit/test_option_chain_alerts.py`
- `tests/fixtures/option_chain_balanced.json`
- `tests/fixtures/option_chain_put_heavy.json`
- `tests/fixtures/option_chain_call_wall_trend.json`
- `tests/fixtures/option_chain_expiry_day.json`
- `tests/fixtures/option_chain_illiquid_otm.json`

## Phase 0: Baseline Capture

### Objective

Freeze current behavior and create a safe starting point for refactor work.

### File-level tasks

- `app.py`
  - identify and isolate the full `page_option_chain()` flow into documented sections using minimal comments only where flow boundaries are unclear
  - note current inputs, outputs, and session-state dependencies
- `tests/integration/test_option_chain.py`
  - add or tighten baseline tests for snapshot-only rendering and current summary metrics
- `tests/unit/test_helpers.py`
  - add coverage for currently used option-chain helper transforms that will later move into dedicated modules
- `tests/fixtures/option_chain_balanced.json`
  - add a representative chain fixture that mirrors current expected data shape

### Deliverables

- stable fixture for current option-chain behavior
- baseline tests that fail on regressions during refactor

### Acceptance tests

- `pytest tests/integration/test_option_chain.py -q`
- `pytest tests/unit/test_helpers.py -q`
- existing option-chain page still renders snapshot mode without feature loss

## Phase 1: Service and Persistence Foundation

### Objective

Extract option-chain orchestration out of `app.py` and add intraday persistence support without changing the visible UX.

### File-level tasks

- `option_chain_service.py`
  - create snapshot fetch orchestration
  - create chain normalization entrypoint
  - create snapshot-plus-live merge entrypoint
  - create filtered ladder view-model builder
  - centralize cache read/write behavior currently embedded in `app.py`
- `option_chain_metrics.py`
  - move PCR, Max Pain, expected move, IV percentile, IV z-score, liquidity score, and OI build-up classification into pure functions
- `persistence.py`
  - add `option_chain_intraday_snapshots` schema creation
  - add indexes for instrument/expiry/timestamp queries
  - add insert-or-ignore upsert path for intraday snapshots
  - add read APIs for replay windows and recent strike history
  - add retention cleanup for high-resolution intraday rows
- `app.py`
  - replace direct fetch/transform logic in `page_option_chain()` with calls into `option_chain_service.py`
  - keep the existing layout and visible controls unchanged in this phase
- `helpers.py`
  - remove moved option-chain-specific business logic
  - keep only generic transforms that are reused outside the option-chain feature
- `tests/unit/test_option_chain_metrics.py`
  - add pure function tests for PCR, Max Pain, expected move, liquidity score, IV percentile, IV z-score, and OI build-up state
- `tests/unit/test_option_chain_service.py`
  - add tests for cache-hit path, cache-miss path, snapshot normalization, live overlay merge, and strike filtering
- `tests/unit/test_persistence_unit.py`
  - add schema migration and insert/read tests for intraday snapshots
- `tests/integration/test_persistence.py`
  - add end-to-end persistence checks for intraday snapshot writes and replay reads

### Deliverables

- dedicated service and metrics modules
- intraday snapshot schema and persistence APIs
- no visible regression in current page behavior

### Acceptance tests

- `pytest tests/unit/test_option_chain_metrics.py -q`
- `pytest tests/unit/test_option_chain_service.py -q`
- `pytest tests/unit/test_persistence_unit.py -q`
- `pytest tests/integration/test_persistence.py -q`
- `pytest tests/integration/test_option_chain.py -q`
- current option-chain page still supports:
  - snapshot-only render
  - live LTP overlay
  - PCR and Max Pain display
  - CSV export

## Phase 2: Ladder Redesign and Core Plotly Charts

### Objective

Replace the current table-first rendering with a proper ladder model and move core analytics charts to dedicated Plotly builders.

### File-level tasks

- `option_chain_charts.py`
  - add Plotly OI profile builder
  - add Plotly delta-OI profile builder
  - add Plotly IV smile builder
  - add chart annotations for ATM, Max Pain, highest call OI, and highest put OI
  - add consistent hover and export config
- `option_chain_state.py`
  - store selected strike, pinned strikes, selected chart tab, chart filters, and visible strike window
- `option_chain_service.py`
  - produce ladder rows with centered strike and aligned call/put cells
  - add derived columns for spread, spread percent, mid price, bid/ask imbalance, distance from spot, notional OI, IV percentile, IV z-score, and liquidity score
  - support row pinning for ATM, Max Pain, OI walls, and user favorites
- `app.py`
  - replace current option-chain table rendering with ladder rendering driven by service output
  - wire table-row selection into chart highlight state
  - wire chart click selection back into ladder state if the existing UI stack permits it cleanly
- `charts.py`
  - remove or deprecate option-chain-specific chart code that is replaced by `option_chain_charts.py`
- `tests/unit/test_option_chain_charts.py`
  - add tests for figure construction, trace counts, annotations, and strike markers
- `tests/unit/test_charts.py`
  - trim or update overlapping legacy chart tests if ownership moves fully to `option_chain_charts.py`
- `tests/integration/test_option_chain.py`
  - add ladder render tests and selected-strike highlight tests

### Deliverables

- centered ladder UI
- Plotly core charts for OI and IV
- stateful strike selection and pinning

### Acceptance tests

- `pytest tests/unit/test_option_chain_charts.py -q`
- `pytest tests/integration/test_option_chain.py -q`
- user can verify in the page that:
  - calls and puts align on the same strike row
  - ATM row remains visible and clearly marked
  - Max Pain and top OI walls render as markers in both ladder and charts
  - liquidity and spread columns render for visible strikes

## Phase 3: Multi-Expiry Comparison

### Objective

Add controlled multi-expiry analysis without making the main ladder unusable.

### File-level tasks

- `option_chain_service.py`
  - add expiry-strip summary model for up to three expiries
  - add compare-expiry datasets for ATM IV, OI profile, expected move, and PCR
- `option_chain_metrics.py`
  - add expiry-level ATM IV rank and term-structure calculations
  - add front-vs-next event premium distortion detection
- `option_chain_charts.py`
  - add ATM IV term structure figure
  - add multi-expiry OI overlay figure
  - add multi-expiry IV smile overlay figure
  - add expected move cone figure
- `option_chain_state.py`
  - add selected compare-expiry set and normalization mode
- `app.py`
  - add expiry strip UI
  - add compare-expiry selector capped at three expiries
  - add chart-tab routing for term structure and expected move views
- `tests/unit/test_option_chain_metrics.py`
  - add tests for term structure, expected move by expiry, and event premium distortion
- `tests/unit/test_option_chain_charts.py`
  - add tests for multi-expiry trace construction
- `tests/integration/test_option_chain.py`
  - add multi-expiry render and selector tests

### Deliverables

- expiry comparison strip
- multi-expiry overlays
- term structure and expected move views

### Acceptance tests

- `pytest tests/unit/test_option_chain_metrics.py -q`
- `pytest tests/unit/test_option_chain_charts.py -q`
- `pytest tests/integration/test_option_chain.py -q`
- user can verify in the page that:
  - up to three expiries can be compared
  - ATM IV term structure renders with sensible ordering by expiry
  - front expiry distortion is flagged when fixture data indicates event premium

## Phase 4: Intraday Snapshots and Replay

### Objective

Turn intraday option-chain history into a usable analysis feature with replay and change-over-time views.

### File-level tasks

- `live_feed.py`
  - add aggregation path to roll live updates into 1-minute strike/side intervals
  - expose quote freshness metadata needed for liquidity scoring
- `persistence.py`
  - add finalized 1-minute intraday snapshot writes
  - add query APIs for change-since-open and rolling 5/15/30/60-minute windows
  - add retention logic for full-resolution and downsampled history
- `option_chain_service.py`
  - add replay-time slice loading
  - add change-since-open and rolling-window comparison datasets
  - add session high/low IV by strike view-model fields
- `option_chain_charts.py`
  - add OI heatmap by strike/time
  - add skew shift replay figure
  - add replay-aware delta-OI figure
- `option_chain_state.py`
  - add replay timestamp and replay mode
- `app.py`
  - add replay slider
  - add change-window controls for 5/15/30/60 minutes and since-open
  - add session replay views in chart panel
- `tests/unit/test_persistence_unit.py`
  - add 1-minute aggregation correctness tests
  - add replay query tests
  - add retention cleanup tests
- `tests/unit/test_option_chain_service.py`
  - add replay slice assembly and rolling-window comparison tests
- `tests/integration/test_option_chain.py`
  - add replay and intraday delta rendering tests

### Deliverables

- intraday time-sliced persistence
- replay slider
- change-over-time analytics

### Acceptance tests

- `pytest tests/unit/test_persistence_unit.py -q`
- `pytest tests/unit/test_option_chain_service.py -q`
- `pytest tests/integration/test_option_chain.py -q`
- user can verify in the page that:
  - replay slider changes ladder and charts consistently
  - since-open and rolling-window analytics change when replay timestamp changes
  - OI heatmap uses stored intraday snapshots rather than only current session memory

## Phase 5: Alerts, Commentary, and Advanced Positioning

### Objective

Add deterministic decision-support output and advanced positioning analytics on top of the stable data foundation.

### File-level tasks

- `option_chain_alerts.py`
  - add deterministic rules for call wall shift, put wall shift, skew steepening, ATM IV jump, spread blowout, and unusual pinned-strike volume
  - expose alert objects with severity, cause, strike/expiry context, and timestamp
- `option_chain_metrics.py`
  - add net gamma by strike
  - add gamma wall candidate detection
  - add vanna and charm aggregate profiles using available Greeks inputs
- `option_chain_charts.py`
  - add gamma exposure profile
  - add vanna/charm profile
  - add liquidity scatter
- `option_chain_service.py`
  - build deterministic commentary strings from metrics and alerts
  - expose top movers for OI addition, OI reduction, spread widening, and volume burst
- `option_chain_state.py`
  - add monitored-strike watchlist state
- `app.py`
  - add alerts panel
  - add commentary panel
  - add monitored-strike filter/watchlist controls
- `tests/unit/test_option_chain_alerts.py`
  - add fixture-driven deterministic alert tests
- `tests/unit/test_option_chain_metrics.py`
  - add gamma wall, vanna, and charm tests
- `tests/integration/test_option_chain.py`
  - add alert/commentary render tests

### Deliverables

- deterministic alert engine
- rule-based summary commentary
- advanced dealer-positioning charts

### Acceptance tests

- `pytest tests/unit/test_option_chain_alerts.py -q`
- `pytest tests/unit/test_option_chain_metrics.py -q`
- `pytest tests/integration/test_option_chain.py -q`
- user can verify in the page that:
  - alerts are stable for the same fixture input
  - commentary references real strikes and expiries from the current dataset
  - gamma wall markers align with charted strike positioning

## Fixture Matrix

The following fixtures should be used across unit and integration tests:

- `tests/fixtures/option_chain_balanced.json`
  - neutral baseline with healthy liquidity and centered OI
- `tests/fixtures/option_chain_put_heavy.json`
  - defensive positioning with strong put OI concentration
- `tests/fixtures/option_chain_call_wall_trend.json`
  - trending-up market with strong call wall and rising call-side participation
- `tests/fixtures/option_chain_expiry_day.json`
  - distorted front-expiry pricing and unstable skew
- `tests/fixtures/option_chain_illiquid_otm.json`
  - far OTM strikes with poor spread, low quote size, and weak liquidity

## Cross-Phase Exit Criteria

The project is complete only when all of the following are true:

- `app.py` is reduced to page composition and UI wiring rather than core option-chain analytics
- option-chain business logic is covered by dedicated unit tests
- intraday persistence supports replay and rolling-window analytics
- core charts are built in `option_chain_charts.py`
- multi-expiry comparison is supported without breaking the single-expiry default workflow
- deterministic alerts and commentary are backed by fixtures and tests

## Recommended Build Order

Implement phases in this order without overlap:

1. Phase 0
2. Phase 1
3. Phase 2
4. Phase 3
5. Phase 4
6. Phase 5

Do not start Phase 3 before Phase 2 acceptance passes. Do not start Phase 5 before replay and intraday persistence are stable in Phase 4.
