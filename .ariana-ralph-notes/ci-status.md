# CI Status & Blockers

CI pipeline: `.github/workflows/ci.yml`

## Pipeline steps (in order)

| Step | Command | Status |
|------|---------|--------|
| Lint (ruff) | `ruff check .` | PASSING (after PR #22) |
| Lint (flake8) | `flake8 app tests` | PASSING (after PR #22) |
| Unit tests | `pytest tests/unit --cov=app/lib --cov-report=term-missing --cov-fail-under=80` | FAILING |
| Security scan | `bandit -q -r app` | PASSING |
| Docker build | `docker build -t breeze-service:$SHA .` | UNTESTED |
| Integration tests | `pytest tests/integration -m integration` | SKIPPED (needs creds) |

## Remaining blockers

### 1. Failing test: `test_monte_carlo_var_runtime_and_monotonicity`

**File:** `tests/unit/test_portfolio_analytics_advanced.py:75`
**Error:** `assert elapsed < 5.0` — actual runtime ~12s on this machine
**Root cause:** The `monte_carlo_var()` function in `analytics.py` runs 10,000 simulations with scipy/numpy. The 5-second threshold is too tight for CI-class hardware.
**Fix options:**
- (a) Raise the threshold to 15s or 20s (simplest, least risky)
- (b) Reduce `simulations` param in the test to 1,000 (still tests correctness)
- (c) Optimize the `monte_carlo_var()` implementation (most work, highest risk)
- (d) Mark the test with `@pytest.mark.slow` and skip it in CI

**Recommendation:** Option (a) or (b) — minimal change, doesn't modify production code.

### 2. Coverage below 80%

**Current:** 65% on `app/lib`
**Required:** 80% (`--cov-fail-under=80`)

Coverage breakdown:
| Module | Coverage | Missing |
|--------|----------|---------|
| `app/lib/__init__.py` | 100% | — |
| `app/lib/config.py` | 100% | — |
| `app/lib/errors.py` | 100% | — |
| `app/lib/auth.py` | 82% | lines 28, 59, 62-65, 71-72, 92, 105, 110 |
| `app/lib/breeze_client.py` | 72% | many lines in request(), probe, error-mapping, convenience methods |
| `app/lib/breeze_ws.py` | 0% | entire file untested |
| `app/lib/logging_config.py` | 0% | entire file untested |

**Fix strategy:**
1. Add tests for `breeze_ws.py` (mock `BreezeConnect`, test connect/subscribe/disconnect)
2. Add tests for `logging_config.py` (test `configure_logging()` sets handler)
3. Add tests for more `breeze_client.py` paths (probe logic, error mapping, convenience methods)
4. Add tests for `auth.py` gaps (FileTokenStore load/save, edge cases)

Getting `breeze_ws.py` and `logging_config.py` from 0% to even 50% would push overall coverage significantly toward 80%.

## v11 autonomous pass update

- Updated CI to Python 3.11/3.12 matrix with pip cache.
- Replaced fixed docker sleep with retry-based health polling.
- Added new unit tests for futures, holiday calendar, GTT validators, historical cache, futures quote validation.
