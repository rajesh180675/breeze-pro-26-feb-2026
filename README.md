# Breeze Production Integration

Production-ready Breeze integration components for ICICI Direct + Breeze Connect.

## Features
- Typed configuration via environment variables (`app/core/settings.py`).
- Central REST wrapper with retries, quota enforcement (100/min, 5000/day), circuit breaker, token handling, and typed errors (`app/infrastructure/breeze/rest_client.py`).
- Session token lifecycle helpers and pluggable token stores (`app/infrastructure/breeze/auth.py`).
- WebSocket feed client with reconnect and subscription cap management (`app/infrastructure/breeze/websocket_client.py`).
- FastAPI service with an application factory and system routes in `app/api/main.py` and `app/api/routes/system.py`.
- Service-layer runtime checks in `app/application/system.py` and centralized metrics in `app/infrastructure/observability/metrics.py`.
- CI workflow with linting, tests, security scan, and Docker build (`.github/workflows/ci.yml`).

## Environment variables
- `BREEZE_CLIENT_ID`
- `BREEZE_CLIENT_SECRET`
- `BREEZE_SESSION_TOKEN`
- `BREEZE_BASE_URL` (optional)
- `MAX_REQUESTS_PER_MINUTE` (optional; default `100`)
- `MAX_REQUESTS_PER_DAY` (optional; default `5000`)

For local development only, use `.env` (already gitignored).

## Run locally
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000
```

## Tests
```bash
pytest tests/unit --cov=app --cov-report=term-missing
pytest tests/integration -m integration
```
Integration tests auto-skip when Breeze credentials are missing.
Use strict mode to fail-fast when integration validation is mandatory:
```bash
BREEZE_INTEGRATION_STRICT=true pytest tests/integration -m integration
```
Strict mode now fails once during test collection with the exact missing env var names.

## Docker
```bash
docker build -t breeze-service:local .
docker run --rm -p 8000:8000 --env-file .env breeze-service:local
```

## Operations runbook
- **429/RateLimitError spikes**: reduce polling, migrate reads to websocket subscriptions.
- **AuthenticationError**: rotate and re-issue session token; restart deployment to refresh env-based token.
- **CircuitOpenError**: upstream is unhealthy; wait for breaker cooldown, monitor 5xx errors.
- **Websocket disconnect loops**: verify network egress, subscription count, and feed token validity.

## Package architecture
```text
app/
  api/
    main.py
    routes/system.py
  application/
    system.py
    option_chain/
  core/
    lifecycle.py
    logging.py
    settings.py
  domain/
    errors.py
    option_chain/
  infrastructure/
    breeze/
      auth.py
      rest_client.py
      websocket_client.py
    observability/
      metrics.py
    option_chain/
  lib/
    compatibility shims for legacy imports
```

## Migration status
- `app/lib/*` remains as the supported compatibility surface for the older production import paths.
- Root-level `option_chain_*.py` modules now delegate to the layered `app/` implementation so `main` stays backward-compatible during the migration.
- Transitional directories from early revamp drafts are intentionally not part of the target architecture.

## Security checklist
- Never commit secrets (`.env`, `.streamlit/secrets.toml`, `*.pem`, `*.key` are ignored).
- Keep TLS verification enabled (no `verify=False`).
- Rotate API keys and session tokens periodically.
- Run `bandit -q -r app` in CI before deployment.

## Kubernetes manifest
See `k8s/deployment.yaml` for deployment, service, probes, and HPA example.

## UI recommendation and integration status
- **Yes — Streamlit is the best fit for this project right now** because the app is trader-facing, Python-native, and already implemented as a Streamlit terminal (`app.py`).
- The frontend is **already integrated** with Breeze via `BreezeAPIClient` (`breeze_api.py`).
- Optional bridge mode is now available to route supported frontend calls through the new production wrapper (`app/lib/breeze_client.py`) by setting:
  - `BREEZE_USE_PRODUCTION_CLIENT=true`
- In bridge mode, `get_positions()` uses the production client first and safely falls back to SDK behavior if needed.
