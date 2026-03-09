# Breeze Pro Codebase Deep Dive Report (2026-03-09)

## Scope and Method
- Audited full repository structure, with focus on runtime paths and production package (`app/`), plus large legacy modules at repo root.
- Ran automated checks in a clean virtualenv:
  - `pytest -q` -> `86 passed, 6 skipped`
  - `ruff check .` -> all checks passed
  - `bandit -r app -q` and targeted root-module security scans
- Performed manual runtime verification for startup/import flows and high-risk auth/persistence paths.

## Critical Findings (Fix First)

### 1) Production API cannot start due to broken import paths
- Severity: Critical
- Impact: FastAPI app fails to import; `uvicorn app.api.main:app` crashes, so `/healthz`, `/ready`, `/metrics` are unavailable.
- Evidence:
  - Runtime repro: `uvicorn app.api.main:app --host 127.0.0.1 --port 8010` -> `ModuleNotFoundError: No module named 'lib'`
  - Broken imports:
    - `app/api/main.py:19`
    - `app/lib/auth.py:12`
    - `app/lib/breeze_client.py:49-58`
    - `app/lib/breeze_ws.py:12-13`
- Root cause:
  - Modules inside `app.*` use `from lib...` absolute imports instead of package-correct `from app.lib...` or relative imports.
  - Tests mask this by mutating `sys.path` to include `app/` (see `tests/conftest.py:4-8`).
- Fix recommendation:
  - Replace all `from lib...` imports with package-safe imports (`from app.lib...` or relative imports).
  - Add a smoke test that imports `app.api.main` without `sys.path` hacks.
  - Keep `tests/conftest.py` from hiding packaging defects (remove `APP_DIR` insertion).

### 2) Token refresh logic never refreshes before expiry
- Severity: Critical
- Impact: `AuthManager.ensure_fresh_token()` can keep using near-expired token until it is already expired; causes avoidable auth failures under load/session rollover.
- Evidence:
  - `TokenRecord.refresh_at` is computed as:
    - `app/lib/auth.py:23-25`
    - `refresh_at = now + (expires_at - now) * 0.9`
  - This moving-threshold formula makes `should_refresh()` become true only at/after expiry (`app/lib/auth.py:30-31`).
- Root cause:
  - Refresh threshold is recalculated from current time each call, rather than from token issuance lifetime or fixed lead-time.
- Fix recommendation:
  - Store token `issued_at` and compute deterministic `refresh_at = issued_at + 0.9 * (expires_at - issued_at)`, or
  - Use fixed margin (e.g., refresh when `< 10-15 min` to expiry).
  - Add tests for refresh behavior at 50%, 90%, 95%, and 99% of lifetime.

## High-Risk Security/Operational Findings

### 3) Sensitive local database is committed to git and stores secrets in plaintext
- Severity: High
- Impact:
  - Credential material is persisted unencrypted (`api_secret`, `totp_secret`) and repository currently tracks a real DB file.
  - Any repo access exposes account profile metadata and potentially secrets.
- Evidence:
  - Schema stores raw credentials:
    - `persistence.py:104-114`
    - `persistence.py:689-714`
  - Tracked binary DB file:
    - `data/breeze_trader.db` (git-tracked object in index).
- Fix recommendation:
  - Immediately remove DB from git tracking and rotate any potentially exposed credentials.
  - Encrypt sensitive fields at rest (OS keyring/KMS or envelope encryption with key outside repo).
  - Add explicit `.gitignore` for all runtime DB artifacts and secret-bearing exports.

### 4) Readiness endpoint is unconditional and can report ready while dependencies are broken
- Severity: High
- Impact:
  - Kubernetes may route traffic to pods that are not functionally ready (auth/config/upstream not validated).
- Evidence:
  - `app/api/main.py:36-38` returns `{"ready": True}` unconditionally.
  - Used by probe in `k8s/deployment.yaml` readinessProbe (`/ready`).
- Fix recommendation:
  - Implement dependency-aware readiness checks (config presence, auth state/token availability, optional upstream probe with timeout budget).
  - Return non-2xx when critical dependencies are unavailable.

## Medium Findings

### 5) Test harness hides real packaging defects
- Severity: Medium
- Impact:
  - CI can pass while runtime packaging is broken, delaying detection until deployment.
- Evidence:
  - `tests/conftest.py:4-8` prepends both repo root and `app/` directory to `sys.path`.
- Fix recommendation:
  - Keep only repo root in `sys.path` (or none if package install used).
  - Add CI stage that runs `python -c "import app.api.main"` before tests.

### 6) Broad exception swallowing in core paths reduces debuggability and can mask bad state
- Severity: Medium
- Impact:
  - Several critical workflows use `except Exception: pass/continue`, potentially hiding failed calculations or failed side effects.
- Evidence examples:
  - `app/lib/breeze_client.py:69-70`
  - `app/lib/breeze_client.py:406-408`
  - `persistence.py:653-654`
  - Multiple root modules similarly swallow exceptions.
- Fix recommendation:
  - Replace blanket catches with narrowed exception types and structured warning/error logs with context.
  - Fail loudly for state-changing operations.

## Automated Check Summary
- Tests: `86 passed, 6 skipped`
- Ruff: clean under current config
- Bandit:
  - `app/` scan found low-severity catch-all patterns.
  - Targeted root scan surfaced additional medium findings (`urlopen`, SQL-string warning), mostly requiring contextual triage.

## Prioritized Fix Plan
1. Fix package imports in `app/` and add import/startup smoke tests.
2. Correct token refresh semantics and add lifecycle unit tests.
3. Purge tracked DB artifacts from git history going forward; rotate credentials; implement encryption for stored sensitive fields.
4. Implement real readiness checks for k8s deployment safety.
5. Reduce blanket exception swallowing in auth/trading/persistence hot paths.
6. Tighten test environment so packaging/runtime issues cannot be masked.

## Suggested Verification After Fixes
- `python -c "import app.api.main"`
- `uvicorn app.api.main:app --host 127.0.0.1 --port 8000` (health/readiness endpoints reachable)
- `pytest -q`
- `ruff check .`
- `bandit -q -r app`
