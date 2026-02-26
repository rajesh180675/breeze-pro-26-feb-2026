# Breeze Production Integration

Production-ready Breeze integration components for ICICI Direct + Breeze Connect.

## Features
- Typed configuration via environment variables (`app/lib/config.py`).
- Central REST wrapper with retries, quota enforcement (100/min, 5000/day), circuit breaker, token handling, and typed errors (`app/lib/breeze_client.py`).
- Session token lifecycle helpers and pluggable token stores (`app/lib/auth.py`).
- WebSocket feed client with reconnect and subscription cap management (`app/lib/breeze_ws.py`).
- FastAPI service with `/healthz`, `/ready`, and `/metrics` endpoints (`app/api/main.py`).
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
pytest tests/unit --cov=app/lib --cov-report=term-missing
pytest tests/integration -m integration
```
Integration tests auto-skip when Breeze credentials are missing.

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

