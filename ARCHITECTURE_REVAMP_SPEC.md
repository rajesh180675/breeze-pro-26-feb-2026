# Breeze Pro Architecture Revamp Spec

## Objective

Modernize the application into a professional, layered Python service architecture without breaking current runtime entrypoints or tests. The current repository mixes:

- a newer production API package under `app/`
- a large legacy root-level Streamlit codebase
- flat infrastructure code grouped under `app/lib/`

This revamp establishes clear package boundaries, an application factory, service-layer orchestration, and compatibility shims so the migration can land safely on `main`.

## Current Problems

1. `app/lib/` is a generic bucket rather than an architectural boundary.
2. API endpoints own operational logic instead of delegating to services.
3. Metrics, logging, configuration, auth, and transport concerns are tightly mixed.
4. CI and type-checking target only a narrow subset of the actual package structure.
5. The repository has no explicit migration plan between the legacy root modules and the new production package.

## Target Architecture

```text
app/
  api/
    main.py
    routes/
      system.py
  application/
    system.py
  core/
    lifecycle.py
    logging.py
    settings.py
  domain/
    errors.py
  infrastructure/
    observability/
      metrics.py
    breeze/
      auth.py
      rest_client.py
      websocket_client.py
  lib/
    ... compatibility shims only
```

## Design Principles

1. API modules are thin transport adapters.
2. Business and operational logic lives in services.
3. Shared configuration, logging, lifecycle, errors, and metrics live in explicit foundational packages.
4. External systems are isolated behind infrastructure modules.
5. Existing import paths remain valid during migration through compatibility shims.

## Phase Plan

### Phase 1

Ship a safe architectural baseline for the production package.

- Introduce `core`, `domain`, `services`, `observability`, `api/routes`, and `clients/breeze`
- Introduce explicit `application`, `core`, `domain`, `infrastructure`, and `api/routes` boundaries
- Add an application factory in `app/api/main.py`
- Move system health/version/readiness logic into `app/application/system.py`
- Centralize metrics in `app/infrastructure/observability/metrics.py`
- Migrate Breeze auth/rest/ws implementations into `app/infrastructure/breeze/*`
- Convert `app/lib/*` into compatibility re-export shims
- Expand CI and mypy scope from `app/lib/` to the full `app/` package

### Phase 2

Unify the legacy Streamlit root modules behind the same layered package.

- Move root-level domain logic into `app/`
- Introduce module boundaries for trading, analytics, persistence, and UI state
- Replace direct cross-module imports with explicit service interfaces
- Add package-level lint and type enforcement for migrated modules

### Phase 3

Operational hardening.

- Settings validation with startup checks
- Dependency injection for Breeze clients and persistence adapters
- Structured request correlation and API middleware
- Repo-wide observability and deployment configuration cleanup

## Immediate Deliverables

This change set implements all of Phase 1.

## Acceptance Criteria

1. Existing `app.lib.*` imports continue to work.
2. FastAPI app still exposes `/healthz`, `/ready`, `/version`, and `/metrics`.
3. Production-package tests pass after the refactor.
4. CI checks the full `app/` package instead of only `app/lib/`.
5. The repository contains a clear architectural migration document on `main`.
