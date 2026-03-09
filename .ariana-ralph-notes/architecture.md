# Codebase Architecture

## Two layers

### 1. Production package: `app/`

```
app/
  __init__.py
  api/
    __init__.py
    main.py          # FastAPI app with /healthz, /ready, /metrics
  lib/
    __init__.py
    config.py         # Typed Settings dataclass from env vars
    errors.py         # Domain exceptions (BreezeAPIError hierarchy)
    auth.py           # Token lifecycle: TokenRecord, TokenStore, AuthManager
    breeze_client.py  # REST wrapper: rate limiter, circuit breaker, retries, metrics
    breeze_ws.py      # WebSocket feed client with reconnect
    logging_config.py # JSON structured logging
```

This is the clean, testable, production-ready layer. CI lints and tests only this package (plus tests/).

### 2. Legacy Streamlit layer: root-level files

```
app.py              # ~185KB Streamlit UI (the main dashboard)
breeze_api.py       # BreezeAPIClient — original SDK wrapper
analytics.py        # Portfolio analytics (Monte Carlo VaR, IV smile, etc.)
live_feed.py        # WebSocket feed manager for Streamlit
gtt_manager.py      # GTT (Good Till Triggered) order management
persistence.py      # SQLite trade logging and tax export
session_manager.py  # Session/TOTP automation
holiday_calendar.py # Market holiday calendar
risk_monitor.py     # Position risk monitoring
strategies.py       # Trading strategy templates
ta_indicators.py    # Technical analysis indicators
futures.py          # Futures trading helpers
historical.py       # Historical data fetcher
alerting.py         # Alert dispatcher (Telegram, email, webhook)
charts.py           # Plotly chart rendering
paper_trading.py    # Paper trading engine
basket_orders.py    # Basket/multi-leg order execution
validators.py       # Input validators
helpers.py          # Utility functions
app_config.py       # Streamlit app configuration
```

These are excluded from ruff linting (via `pyproject.toml` exclude list) because they are large, convention-heavy files that predate the production `app/` package. Flake8 only runs on `app tests` so these are also excluded from flake8.

### Bridge mode

Setting `BREEZE_USE_PRODUCTION_CLIENT=true` routes calls from the Streamlit frontend through the production `app/lib/breeze_client.py` wrapper, with fallback to the legacy SDK behavior.

## Tests

```
tests/
  conftest.py
  unit/                     # 18 test files, 58 tests
    test_breeze_client.py   # Tests for app/lib/breeze_client.py
    test_auth.py            # Tests for app/lib/auth.py
    test_charts.py          # Tests for charts.py
    ...
  integration/
    test_breeze_integration.py  # Needs live Breeze creds, auto-skips without them
```

## CI Pipeline

`.github/workflows/ci.yml`: lint -> unit tests (80% coverage) -> security scan -> docker build -> integration tests (optional)
