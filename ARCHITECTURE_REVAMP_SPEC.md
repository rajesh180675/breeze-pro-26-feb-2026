# Breeze Pro Architecture Revamp Spec

## Purpose

Define a professional target architecture for the repository and a safe migration plan from the current mixed codebase into a clearer, maintainable application structure.

This document is intentionally a spec only. It does not assume the implementation happens in one large refactor.

## Current State Summary

The repository currently has two distinct layers:

1. A newer production-oriented package under `app/`
   - FastAPI entrypoint in `app/api/main.py`
   - Infrastructure and domain concerns grouped together under `app/lib/`
2. A large legacy root-level application surface
   - Streamlit/UI modules
   - trading logic
   - persistence
   - analytics
   - option-chain and session workflows

### Current Architectural Problems

1. `app/lib/` is a catch-all package rather than a real architectural boundary.
2. API transport concerns and operational logic are coupled.
3. External integrations, configuration, logging, and domain errors are mixed at the same level.
4. The legacy root-level modules are not organized into explicit bounded contexts.
5. CI and typing targets do not fully reflect the intended production package architecture.
6. The repository has no defined migration contract between legacy modules and the newer `app/` package.

## Revamp Goals

1. Introduce explicit architectural layers with clear responsibilities.
2. Preserve runtime stability during migration.
3. Reduce cross-module coupling and improve import discipline.
4. Make testing, CI, and deployment align with the intended package boundaries.
5. Establish a path to migrate legacy root modules without a disruptive big-bang rewrite.

## Non-Goals

1. Rewriting the entire trading domain in one step.
2. Replacing Streamlit immediately.
3. Changing external behavior without tests or migration guards.
4. Moving every root-level module into `app/` in a single PR.

## Target Architecture

```text
app/
  api/
    main.py
    routes/
    middleware/
    dependencies/
  core/
    settings.py
    logging.py
    lifecycle.py
  domain/
    errors.py
    models/
    value_objects/
    services/
  application/
    use_cases/
    orchestrators/
    dto/
  infrastructure/
    breeze/
      rest_client.py
      websocket_client.py
      auth.py
    persistence/
    cache/
    observability/
  interfaces/
    streamlit/
    api/
```

### Architectural Responsibilities

1. `api/`
   - HTTP transport only
   - routing, validation, middleware, dependency wiring
   - no direct business logic
2. `core/`
   - app settings
   - logging
   - startup/shutdown lifecycle
   - environment and process-level concerns
3. `domain/`
   - domain models
   - domain rules
   - typed errors and value objects
4. `application/`
   - orchestration and use cases
   - combines domain logic with infrastructure adapters
   - no framework-specific code
5. `infrastructure/`
   - Breeze SDK integration
   - REST and websocket clients
   - persistence and monitoring adapters
6. `interfaces/`
   - Streamlit UI
   - external service adapters
   - integration-facing presentation logic

## Legacy Migration Strategy

The legacy root-level modules should not be moved blindly. They should be grouped by bounded context first.

### Proposed Bounded Contexts

1. `market_data`
   - `historical.py`
   - `live_feed.py`
   - charts and technical indicator helpers
2. `orders_execution`
   - `basket_orders.py`
   - `gtt_manager.py`
   - order lifecycle logic
3. `risk_and_portfolio`
   - `risk_monitor.py`
   - `paper_trading.py`
   - analytics and portfolio summaries
4. `session_and_auth`
   - `session_manager.py`
   - auth/session health and multi-account support
5. `option_chain`
   - option chain controller, services, metrics, view-models, charts, workspace
6. `ui_shell`
   - `app.py`
   - Streamlit page composition and theme wiring

## Migration Principles

1. Move behavior behind stable interfaces before moving files.
2. Prefer compatibility shims over mass import rewrites.
3. Keep vertical slices testable at each phase.
4. Migrate modules by bounded context, not alphabetically.
5. Update CI scope as new package boundaries become authoritative.

## Proposed Phases

### Phase 1: Foundation

Objective: professionalize the current `app/` package without breaking public imports.

Changes:

1. Replace `app/lib/` as the primary architecture boundary.
2. Introduce:
   - `app/core/`
   - `app/domain/`
   - `app/infrastructure/`
   - `app/api/routes/`
3. Convert `app/api/main.py` to an application factory.
4. Move health/readiness/version logic into a service module.
5. Centralize metrics and logging.
6. Keep `app/lib/*` as compatibility shims during migration.

Acceptance criteria:

1. Existing tests still pass.
2. `/healthz`, `/ready`, `/version`, and `/metrics` remain stable.
3. CI targets the entire production package rather than only `app/lib/`.

### Phase 2: Option Chain Vertical Slice

Objective: migrate the strongest root-level bounded context first.

Why this first:

1. The option-chain code already behaves like a subsystem.
2. It has dedicated tests.
3. It spans controller, metrics, service, view-model, and UI concepts that benefit from explicit layering.

Changes:

1. Create `app/application/option_chain/`
2. Move domain calculations into `app/domain/option_chain/`
3. Move adapters and persistence into `app/infrastructure/option_chain/`
4. Leave import shims at root for one release cycle

Acceptance criteria:

1. Option-chain tests pass from new package paths.
2. Streamlit option-chain behavior is unchanged.
3. Root-level compatibility imports remain operational.

### Phase 3: Session/Auth and Execution Services

Objective: isolate critical runtime workflows.

Changes:

1. Create:
   - `app/application/session/`
   - `app/application/orders/`
   - `app/infrastructure/auth/`
   - `app/infrastructure/execution/`
2. Move session lifecycle and multi-account coordination into application services.
3. Move Breeze order transport to explicit infrastructure adapters.

Acceptance criteria:

1. Session and order lifecycle tests pass.
2. Core auth and order orchestration are no longer rooted in top-level files.

### Phase 4: UI Shell Professionalization

Objective: make the Streamlit app a thin interface layer.

Changes:

1. Convert `app.py` into a composition root only.
2. Move feature page composition under `app/interfaces/streamlit/`
3. Move UI state and page orchestration out of feature logic modules.
4. Standardize navigation, layout, and shared widgets.

Acceptance criteria:

1. Streamlit entrypoint is small and declarative.
2. Feature logic is imported from application/domain layers rather than root utilities.

### Phase 5: Repository Cleanup

Objective: finalize the migration.

Changes:

1. Remove compatibility shims once internal imports are migrated.
2. Remove obsolete root-level modules.
3. Tighten Ruff, mypy, and coverage scopes.
4. Align Docker, deployment, and docs with final package layout.

Acceptance criteria:

1. No production code depends on legacy root compatibility modules.
2. CI and documentation reflect the final architecture.

## Testing and Quality Strategy

1. Add contract tests around compatibility shims during transition.
2. Expand CI from narrow package checks to full-package checks incrementally.
3. Require each migration phase to ship with:
   - focused unit tests
   - import compatibility validation
   - smoke validation of FastAPI and Streamlit entrypoints where applicable

## Risks

1. Large import churn can break the legacy UI unexpectedly.
2. The repo has many root-level modules with implicit shared state.
3. Test coverage exists but is uneven across subsystems.
4. A single massive move would make regression triage difficult.

## Risk Mitigations

1. Migrate by bounded context.
2. Keep compatibility shims until each subsystem is proven stable.
3. Avoid simultaneous architectural and behavioral rewrites in the same phase.
4. Land each phase on `main` only after targeted tests pass.

## Recommended Immediate Scope

The first implementation PR should only cover Phase 1:

1. professionalize the `app/` package
2. add an app factory
3. move system endpoint logic into services
4. isolate configuration, logging, metrics, and Breeze client concerns into explicit packages
5. preserve `app.lib.*` imports via shims

This is the highest-leverage, lowest-risk starting point.

## Final Acceptance Criteria for the Full Program

1. The repository has explicit package boundaries and a documented migration path.
2. The production API package is layered and framework-thin.
3. The legacy UI becomes an interface layer rather than a business-logic container.
4. CI, typing, linting, and coverage match the final architecture.
5. The migration reaches `main` incrementally without destabilizing live functionality.
