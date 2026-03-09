# Breeze Pro — Task Notes

Production-ready ICICI Direct Breeze Connect integration.
Repo: [rajesh180675/breeze-pro-26-feb-2026](https://github.com/rajesh180675/breeze-pro-26-feb-2026)

## What is the task about

Build a production-grade wrapper around the ICICI Direct Breeze Connect SDK. The repo has two layers:

1. **Production `app/` package** — FastAPI service with typed config, REST client (retries, rate limiting, circuit breaker), WebSocket feed client, auth lifecycle, Prometheus metrics, and structured logging.
2. **Legacy Streamlit UI** — root-level `app.py` (~185KB) plus ~15 supporting modules (analytics, GTT, paper trading, alerting, etc.) that interact with Breeze via a separate `BreezeAPIClient`.

The task is to get CI green and the production layer fully validated. See [ci-status.md](ci-status.md) for current CI state and blockers.

## How to iterate on the task

1. **Branch from `main`**, name: `devin/<timestamp>-<slug>`
2. **Run lint locally before pushing:**
   ```bash
   ruff check .
   flake8 app tests
   ```
3. **Run unit tests:**
   ```bash
   pytest tests/unit --cov=app/lib --cov-report=term-missing
   ```
4. **Run security scan:**
   ```bash
   bandit -q -r app
   ```
5. Push, create PR, wait for CI.

See [dev-setup.md](dev-setup.md) for full local setup instructions.

## Validation criteria

| # | Criterion | Status |
|---|-----------|--------|
| 1 | `ruff check .` passes | DONE (PR #22) |
| 2 | `flake8 app tests` passes | DONE (PR #22) |
| 3 | `bandit -q -r app` passes | DONE (was already passing) |
| 4 | All 58 unit tests pass | BLOCKED — 1 test fails (see [ci-status.md](ci-status.md)) |
| 5 | Coverage >= 80% on `app/lib` | BLOCKED — currently 65% (see [ci-status.md](ci-status.md)) |
| 6 | Docker build succeeds | NOT TESTED locally |
| 7 | Integration tests pass (with creds) | NOT TESTED (needs Breeze sandbox creds) |

## Last units of work done

1. **PR #22** — [Fix all ruff and flake8 lint errors for CI](https://github.com/rajesh180675/breeze-pro-26-feb-2026/pull/22)
   - Added `pyproject.toml` (ruff config: line-length=120, exclude legacy root files, per-file-ignores E402 for tests)
   - Added `setup.cfg` (flake8 config: max-line-length=120, per-file-ignores E402 for tests)
   - Fixed unused imports (F401), blank line issues (E301/E302/E303/E305), long lines (E501) in `app/` and `tests/`
   - Result: both `ruff check .` and `flake8 app tests` now pass cleanly

## File index

- [ci-status.md](ci-status.md) — CI pipeline details, remaining blockers, and fix strategies
- [dev-setup.md](dev-setup.md) — Local development setup
- [architecture.md](architecture.md) — Codebase architecture and module map
- [lessons-learned.md](lessons-learned.md) — Mistakes to avoid, gotchas discovered
