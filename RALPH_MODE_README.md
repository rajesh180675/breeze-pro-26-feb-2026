# RALPH Mode — Comprehensive Deep Dive Review (Codebase / Functionality / Scope / Schema)

> This document is the **living Ralph-mode deep-dive report** for autonomous execution.
> It serves both as architecture intelligence and an execution control loop for remaining work.

---

## 1) Executive Summary

Breeze PRO is a hybrid system with two runtime surfaces:

1. **Legacy monolith UI path** (root-level Streamlit modules like `app.py`, `breeze_api.py`, `risk_monitor.py`, `persistence.py`).
2. **Production package path** (`app/lib/*` and `app/api/main.py`) used for typed config, service probes, and CI coverage targeting.

The repo is functionally rich and already has broad unit coverage. The primary engineering challenge is less about feature absence and more about **cohesion**:
- keeping root-level modules stable,
- maintaining production-grade guarantees in `app/lib`, and
- preventing drift between “legacy runtime behavior” and “new package behavior.”

---

## 2) Codebase Scope Map (What exists, where responsibility lives)

### 2.1 Runtime planes

- **UI plane (Streamlit)**
  - Entry/UI orchestration: `app.py`
  - Business-heavy modules at repo root: trading, alerts, risk, persistence, strategies, historical, futures, etc.

- **Service plane (FastAPI)**
  - `app/api/main.py` exposes `/healthz`, `/version`, `/ready`, `/metrics`.
  - Readiness currently validates env + SQLite connectivity.

- **Library plane (`app/lib`)**
  - `config.py` typed settings
  - `breeze_client.py` HTTP wrapper + breaker/metrics
  - `auth.py` token lifecycle/storage
  - `breeze_ws.py` websocket client
  - `errors.py`, `logging_config.py`

### 2.2 Testing scope

- Unit tests under `tests/unit` are extensive and run in CI.
- Integration tests under `tests/integration` are credential/network dependent.
- CI coverage target intentionally focuses on `--cov=app/lib`.

### 2.3 Deployment scope

- Local/prod compose: `docker-compose.prod.yml`
- K8s manifests: `k8s/deployment.yaml`
- Observability assets: `prometheus.yml`, `grafana/dashboards/breeze_pro.json`

---

## 3) Functional Deep Dive (Module-level behavior)

### 3.1 Trading execution path

- Root `breeze_api.py` acts as SDK-facing integration wrapper for quoting/order flows.
- Futures quote path now includes exchange validation (`NFO` / `BFO`) before SDK call.
- Complex order/risk behavior is split across:
  - `paper_trading.py` (simulation engine)
  - `gtt_manager.py` (GTT lifecycle + persistence)
  - `risk_monitor.py` (threaded risk daemon)

**Ralph finding:** Execution logic is mature but distributed. The cost is higher cognitive load and duplicated invariants (e.g., symbol/exchange validation appearing in multiple places).

### 3.2 Risk & alerting path

- `risk_monitor.py` provides polling loop, per-position stop logic, and portfolio-level checks.
- `alerting.py` now includes retry-once semantics and queue flush helper for shutdown/tests.

**Ralph finding:** Operational resiliency improved; next hardening should center on **uniform failure telemetry** (consistent structured fields across all alert channels and risk-generated events).

### 3.3 Data & historical path

- `historical.py` has chunked fetch + in-memory cache.
- Miss accounting and periodic purge controls cache growth behavior.

**Ralph finding:** Good safeguards exist; potential next gain is deterministic cache observability (hit/miss/exported stats endpoint) to support production tuning.

### 3.4 Session/profile path

- `session_manager.py` handles credentials/session state and encrypted profile management.
- Compatibility helpers now expose process-level manager retrieval + profile deletion wrapper.

**Ralph finding:** This patch reduces caller friction. Future work should define an explicit “public API surface” in module docs to avoid accidental dependency on internals.

---

## 4) Schema Deep Dive (Persistence and data contracts)

Primary persistence is SQLite (`persistence.py`) with thread-local connection management, WAL, and migration versioning.

### 4.1 Core tables (functional role)

- `trades`: executed trade ledger (audit/tax and PnL sources)
- `pnl_history`: daily realized/unrealized rollups
- `alerts_log`: operational/risk alerts
- `watchlist`: user tracking instruments
- `state_snapshots`: periodic serialized state
- `idempotency_keys`: duplicate-order protection keys
- `settings`: key/value runtime settings
- `option_chain_history`: IV/volume history store for analytics baselines
- `account_profiles`: encrypted multi-account profile storage
- `schema_version`: migration state

### 4.2 Schema governance quality

- Migration runner is idempotent and tolerant of already-applied operations.
- Transaction wrapper (`_tx`) is broadly used for write operations.
- Recent fix aligned GTT schema init with transaction context.

**Ralph finding:** Schema discipline is adequate for single-node deployment. For horizontal scale, SQLite write contention and lock windows become a strategic constraint; future migration plan to a server DB should be pre-designed (even if not yet executed).

---

## 5) Scope Boundaries & Non-goals (to avoid accidental destabilization)

1. **Do not refactor root Streamlit monolith for style-only reasons** during coverage tasks.
2. **Treat `app/lib` as production contract surface** for CI quality gates.
3. **Keep integration tests optional in unit CI**, but preserve strict mode hooks for release validation.
4. **Prefer additive compatibility changes** over broad API rewrites while autonomous backlog remains active.

---

## 6) Architectural Risks (Current)

### Risk A — Dual-surface drift
Root modules and `app/lib` can diverge in behavior and assumptions.

**Mitigation:** add parity tests for shared semantics (errors, retries, validation behavior).

### Risk B — Hidden coupling via module internals
Tests/callers may reach private fields due to legacy patterns.

**Mitigation:** formalize exported helpers and document intended entrypoints (ongoing with Ralph wrappers).

### Risk C — Performance variance in stochastic analytics tests
Monte Carlo runtime fluctuates by machine class.

**Mitigation:** retain correctness assertions, use realistic performance thresholds, and label truly slow tests.

### Risk D — Operational blind spots
Health/readiness exists, but deeper component health (cache pressure, queue depth, risk loop lag) is not yet fully surfaced as first-class metrics.

**Mitigation:** incremental metrics expansion and dashboarding.

---

## 7) Ralph-Mode Execution Criteria (Authoritative)

A task batch is complete only when:

1. Changes map to prioritized spec items.
2. Code + tests are delivered together.
3. Validation gates pass:
   - syntax checks on touched Python files,
   - targeted tests,
   - `ruff check .`.
4. Scope boundaries are respected (no opportunistic destabilizing refactors).
5. Loop bookkeeping is updated (done/next/blockers).

---

## 8) Ralph Loop Ledger (Current State)

### Completed in recent autonomous passes
- CI matrix + cache + health retry polling.
- FastAPI readiness/version strengthening.
- Alert retry + flush.
- GTT schema transaction safety.
- Historical throttle and cache purge behavior.
- Session multi-account compatibility wrappers.
- Significant expansion of unit tests across risk/strategies/persistence/session/futures/validators.

### Next recommended autonomous focus
1. Continue unresolved spec tasks not yet fully implemented end-to-end (including deeper P2/P3 docs/tooling parity checks).
2. Add parity tests between root wrappers and `app/lib` behavior on key error/validation paths.
3. Expand observability signals for risk loop and alert queue operational state.
4. Keep CI green while reducing brittle timing assumptions.

---

## 9) Task-Lock Exit Conditions

Stop Ralph loop only when one of these is true:

- User explicitly changes scope.
- All scoped tasks are implemented and validated.
- Hard external blocker prevents safe progress (must be documented with fallback path).

---

## 10) Operating Principle

**Ralph mode is not “just coding”; it is controlled systems execution.**
Each patch must increase both capability and confidence, and leave the repo easier to operate than before.
