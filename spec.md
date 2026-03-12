# Startup UI Redesign Spec

## Goal

Redesign the Breeze PRO startup and shell UI so the app always exposes a visible connection path, remains navigable when the sidebar is collapsed, and feels more like a professional trading terminal than a Streamlit dashboard with a hidden login panel.

This spec is implementation-oriented. It is based on the current Streamlit shell in `app.py` and addresses the exact failure mode where the user lands on the dashboard, hides the sidebar, and can no longer discover how to reconnect or reach the connect screen.

## Current Baseline

### What the app does today

- `main()` renders global layout controls before auth state is resolved.
- If the user is not authenticated, the app still renders `page_dashboard()` as the main body.
- The login form exists only inside `render_sidebar()`.
- When the sidebar is hidden, the only recovery path is a small `Show Menu` button in the top layout controls row.

### Code references

- `app.py:382-392`
  - `render_layout_controls()` shows `Hide Menu` / `Show Menu`
- `app.py:1062-1185`
  - `render_sidebar()` contains both navigation and the login form entrypoint
- `app.py:1316-1367`
  - unauthenticated dashboard is a feature overview, not a dedicated connect screen
- `app.py:4964-4980`
  - unauthenticated startup flow still routes into dashboard content

### Root problems

1. Startup state is not treated as a first-class screen.
2. Authentication is coupled to sidebar visibility.
3. Navigation recovery is weak because the restore control is small and easy to miss.
4. The shell mixes pre-login, post-login, and layout state in one flow.
5. The current visual system is functional but not cohesive enough to feel professional.

## Redesign Principles

1. The app must have an explicit startup mode.
2. Connect must never depend on the sidebar being open.
3. Navigation must be recoverable from at least two independent controls.
4. Dashboard is a post-login workspace, not the default login screen.
5. The shell should separate global navigation, page chrome, and page content.
6. Styling should use a tighter design system with stronger hierarchy and less default Streamlit feel.

## Target Information Architecture

### App modes

- `startup`
  - shown when `SessionState.is_authenticated()` is false
  - full-page connect experience
  - no dependency on sidebar for login
- `workspace`
  - shown after successful login
  - dashboard, option chain, positions, analytics, settings

### Global shell structure

1. Top app bar
   - product mark
   - current mode or page title
   - connection status pill
   - primary actions: `Connect`, `Reconnect`, `Menu`

2. Left navigation rail
   - icon-first primary destinations
   - collapsible to slim rail, not fully undiscoverable
   - separate from the startup auth form

3. Main content region
   - page content only
   - no critical auth dependency

4. Context panel
   - optional right-side area for account health, market status, alerts
   - desktop only in later phase

## Startup Experience Spec

### Primary objective

On cold start, the user should immediately understand:

- whether they are connected
- how to connect
- which account/profile is active
- whether credentials are available
- what happens after login

### Startup layout

Use a dedicated full-width startup screen with a three-zone composition:

1. Hero header
   - product name
   - concise terminal tagline
   - market/session status badge

2. Connect panel
   - primary card in the visual center
   - credential state summary
   - profile selector if available
   - login form or quick connect form
   - primary CTA: `Connect to Breeze`
   - secondary CTA: `Use Saved Profile`

3. Readiness panel
   - connection prerequisites
   - secrets detected or missing
   - last successful login time
   - websocket readiness
   - database readiness

### Startup content rules

- Do not show the trading dashboard before authentication.
- Replace the current unauthenticated dashboard cards with startup-specific onboarding cards.
- Show a disabled preview of core modules below the connect panel:
  - Option Chain
  - Positions
  - Risk Monitor
  - Paper Trading
- Each preview card explains what unlocks after login.

### Recovery controls

Startup mode must expose all of these:

- top-right `Connect` action
- persistent `Menu` action
- keyboard shortcut hint
- visible account/profile selector in the main body

## Navigation Redesign

### Desktop behavior

- Replace the current fully hideable sidebar with a two-state rail:
  - `expanded`
  - `compact`
- Do not allow a zero-visibility navigation state.
- Keep an always-visible menu toggle in the top app bar.
- Add a compact floating edge handle if Streamlit CSS limitations require it.

### Mobile behavior

- Use an overlay drawer pattern.
- Keep the top bar fixed with `Menu` and `Connect`.
- Never hide both navigation access and connect access at the same time.

### Navigation groups

- `Home`
- `Trading`
- `Monitoring`
- `Analysis`
- `System`

### Proposed destination mapping

- Home
  - Dashboard
- Trading
  - Option Chain
  - Sell Options
  - Square Off
  - Orders & Trades
  - Positions
  - Futures Trading
  - GTT Orders
  - Paper Trading
- Monitoring
  - Risk Monitor
  - Watchlist
- Analysis
  - Historical Data
  - Strategy Builder
  - Analytics
- System
  - Settings

## Professional Visual Direction

### Design language

Use a modern trading-terminal aesthetic:

- dense but calm
- sharp hierarchy
- restrained color accents
- fewer emoji-led headings in primary chrome
- stronger typography and spacing consistency

### Suggested tokens

- Background: deep slate, layered surfaces, subtle gradient in startup hero
- Accent: cyan/teal for primary actions
- Success: muted green
- Warning: amber
- Danger: red
- Neutral borders: cool gray with better contrast than the current border token

### Typography

- Primary UI font: `IBM Plex Sans`, fallback `Segoe UI`, sans-serif
- Data and metrics font: `IBM Plex Mono`, fallback `Consolas`, monospace

### Component styling goals

- consistent card radii
- one button hierarchy
- one badge system
- one spacing scale
- standardized metric tiles
- cleaner separators than repeated markdown rules

## Page-Level Shell Changes

### Startup page

- new `page_startup()` replaces unauthenticated use of `page_dashboard()`
- owns connect form, readiness state, profile access, onboarding copy

### Dashboard page

- becomes authenticated-only
- focuses on portfolio summary, market pulse, and launch actions
- remove responsibility for explaining login behavior

### Sidebar / rail

- remove login form responsibility
- keep it focused on:
  - navigation
  - active account
  - connection health
  - quick actions

### App bar

- new persistent top shell for:
  - menu toggle
  - page title
  - connection/session state
  - reconnect or disconnect actions

## Recommended Refactor Shape

Do not continue expanding `app.py` as a single UI file. Split shell responsibilities into focused modules.

### New files to add

- `ui_shell.py`
  - top app bar
  - nav rail
  - shell container
  - layout mode state
- `ui_startup.py`
  - startup page
  - connect card
  - readiness card
  - onboarding module previews
- `ui_theme.py`
  - design tokens
  - CSS blocks
  - typography
  - shell utility styles

### Existing files expected to change

- `app.py`
  - route startup mode to `page_startup()`
  - remove unauthenticated dependency on `render_sidebar()`
  - mount new shell components
- `session_manager.py`
  - add shell mode state such as `nav_mode`
  - keep `sidebar_visible` only if needed for migration
- `tests/integration/test_sidebar_layout_controls.py`
  - replace hide/restore expectations with compact/expand shell behavior
- add startup flow integration tests

## Delivery Plan

## Phase 0: Baseline Capture

### Objective

Freeze current behavior before redesign.

### Tasks

- add tests for current unauthenticated startup behavior
- add tests for session transitions:
  - logged out -> startup
  - startup -> connected workspace
  - connected workspace -> expired session

### Acceptance

- existing auth and sidebar tests still pass

## Phase 1: Startup-First Routing

### Objective

Make startup a dedicated screen independent of sidebar visibility.

### Tasks

- add `page_startup()`
- update `main()` to route unauthenticated users to startup, not dashboard
- move login form UI out of `render_sidebar()`
- keep existing dashboard intact for authenticated users only

### Acceptance

- on fresh load, connect UI is visible without opening sidebar
- hiding navigation does not remove login access

## Phase 2: Shell and Navigation Refactor

### Objective

Replace the hidden-sidebar model with a professional app shell.

### Tasks

- add top app bar
- convert sidebar into compactable rail
- add visible menu toggle in app bar
- keep quick reconnect action in top chrome
- migrate page titles into shell header

### Acceptance

- there is no UI state where nav access disappears completely
- user can move between major pages in one click from expanded rail

## Phase 3: Visual System Upgrade

### Objective

Give the app a cohesive and professional visual identity.

### Tasks

- centralize theme tokens in `ui_theme.py`
- restyle cards, badges, metrics, tabs, and forms
- update startup hero and dashboard summary blocks
- reduce ad hoc inline HTML styling in sidebar and dashboard sections

### Acceptance

- visual hierarchy is consistent across startup, dashboard, and settings
- critical actions are immediately distinguishable

## Phase 4: Page Polish and Validation

### Objective

Make sure the shell works across the full app.

### Tasks

- validate all pages under the new shell
- check compact rail behavior with option chain and dashboard
- confirm session-expiry recovery path is visible in top chrome and startup
- add regression coverage for compact nav and startup rendering

### Acceptance

- auth entry, reconnect, and page navigation remain discoverable on desktop and mobile widths

## Acceptance Criteria

The redesign is complete only when all of the following are true:

1. On startup, the user sees a dedicated connect screen immediately.
2. Dashboard is not used as the login surface.
3. Connect remains visible even when navigation is compacted.
4. Navigation always has at least one visible recovery control.
5. Session-expired state provides a first-class reconnect path.
6. The app shell looks consistent and intentionally designed across pages.

## Implementation Notes

- The current `sidebar_visible` flag solves only hide/show, not startup architecture.
- The safest path is to keep page functions intact and refactor the shell around them first.
- The highest-value change is Phase 1, because it fixes the user-facing startup problem immediately.
- The highest-risk change is Phase 2, because Streamlit layout behavior can be limiting; keep tests tight around shell state transitions.

## Recommended Next Build Order

1. Implement `page_startup()` and route unauthenticated users there.
2. Move login and profile switching logic into startup components.
3. Add top app bar with persistent `Menu` and `Connect/Reconnect`.
4. Convert sidebar hide/show into compact/expand rail behavior.
5. Apply the visual system refresh after shell structure is stable.
