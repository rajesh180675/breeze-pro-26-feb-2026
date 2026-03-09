# Local Development Setup

## Prerequisites

- Python 3.11+ (CI uses 3.11)
- pip

## Quick start

```bash
cd /home/ubuntu/repos/breeze-pro-26-feb-2026
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run lint

```bash
ruff check .
flake8 app tests
```

Config files:
- `pyproject.toml` — ruff settings (line-length=120, excludes legacy root files, E402 ignored in tests)
- `setup.cfg` — flake8 settings (max-line-length=120, E402 ignored in tests)

## Run tests

```bash
# Unit tests with coverage
pytest tests/unit --cov=app/lib --cov-report=term-missing

# With coverage threshold (as CI runs it)
pytest tests/unit --cov=app/lib --cov-report=term-missing --cov-fail-under=80

# Integration tests (need BREEZE_CLIENT_ID, BREEZE_CLIENT_SECRET, BREEZE_SESSION_TOKEN)
pytest tests/integration -m integration
```

## Run security scan

```bash
bandit -q -r app
```

## Run FastAPI server

```bash
uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000
```

Endpoints: `/healthz`, `/ready`, `/metrics`

## Docker

```bash
docker build -t breeze-service:local .
docker run --rm -p 8000:8000 --env-file .env breeze-service:local
```

## Environment variables

Required for production/integration:
- `BREEZE_CLIENT_ID`
- `BREEZE_CLIENT_SECRET`
- `BREEZE_SESSION_TOKEN`

Optional:
- `BREEZE_BASE_URL` (default: `https://api.icicidirect.com/breezeapi/api/v1`)
- `MAX_REQUESTS_PER_MINUTE` (default: 100)
- `MAX_REQUESTS_PER_DAY` (default: 5000)
- `BREEZE_USE_PRODUCTION_CLIENT=true` — routes Streamlit frontend calls through the production wrapper
