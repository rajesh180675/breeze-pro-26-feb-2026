# Contributing

## Local setup
1. `python -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt`
3. `pytest tests/unit -q`

## Quality checks
- `ruff check .`
- `ruff format --check .`
- `mypy app/lib/`
- `bandit -q -r . -x tests/,./data/`
