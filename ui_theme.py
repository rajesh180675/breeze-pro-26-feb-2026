"""Centralized design tokens and shell styles for Breeze PRO."""

THEME_CSS = """
<style>
:root {
  --bp-font-ui: "IBM Plex Sans", "Segoe UI", sans-serif;
  --bp-font-mono: "IBM Plex Mono", Consolas, monospace;
  --bp-bg-primary: #071018;
  --bp-bg-secondary: #0d1722;
  --bp-surface-1: #111d2a;
  --bp-surface-2: #162435;
  --bp-surface-3: #1a2b3e;
  --bp-border: rgba(148, 163, 184, 0.20);
  --bp-border-strong: rgba(34, 211, 238, 0.24);
  --bp-text-primary: #e2e8f0;
  --bp-text-secondary: #cbd5e1;
  --bp-text-muted: #8aa0b4;
  --bp-accent: #1ec8df;
  --bp-accent-strong: #0f9db6;
  --bp-success: #38b26a;
  --bp-warning: #d7a43d;
  --bp-danger: #d85f5f;
  --bp-radius-sm: 10px;
  --bp-radius-md: 14px;
  --bp-radius-lg: 18px;
}

html, body, [class*="css"] {
  font-family: var(--bp-font-ui);
}

code, pre, .stCode, .stTextInput input, .stNumberInput input, div[data-testid="stMetricValue"] {
  font-family: var(--bp-font-mono);
}

#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
header { visibility: hidden; }
.block-container { padding-top: 1rem; padding-bottom: 1rem; }

.page-header {
  font-size: 1.9rem;
  font-weight: 800;
  background: linear-gradient(135deg, #8ff1ff, #1ec8df 45%, #3b82f6 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  border-bottom: 2px solid rgba(30, 200, 223, 0.55);
  padding-bottom: 0.5rem;
  margin-bottom: 1.5rem;
}

.section-header {
  font-size: 1.22rem;
  font-weight: 700;
  color: var(--bp-text-primary);
  margin: 1.2rem 0 0.8rem;
  border-left: 4px solid var(--bp-accent);
  padding-left: 0.7rem;
}

.subsection {
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--bp-text-secondary);
  margin: 0.8rem 0 0.4rem;
}

.badge-connected,
.badge-warning,
.badge-danger {
  padding: 5px 14px;
  border-radius: 999px;
  font-weight: 700;
  font-size: 0.82rem;
  display: inline-block;
  border: 1px solid transparent;
}

.badge-connected {
  background: rgba(34, 197, 94, 0.12);
  color: #b8f5cb;
  border-color: rgba(34, 197, 94, 0.22);
}

.badge-warning {
  background: rgba(245, 158, 11, 0.12);
  color: #fde68a;
  border-color: rgba(245, 158, 11, 0.22);
}

.badge-danger {
  background: rgba(239, 68, 68, 0.12);
  color: #fecaca;
  border-color: rgba(239, 68, 68, 0.22);
}

.profit { color: var(--bp-success) !important; font-weight: 700; }
.loss { color: var(--bp-danger) !important; font-weight: 700; }
.neutral { color: var(--bp-text-muted) !important; }

.metric-card,
.metric-card-green,
.metric-card-red {
  padding: 1rem 1.1rem;
  border-radius: var(--bp-radius-md);
  margin: 0.4rem 0;
  border: 1px solid var(--bp-border);
  box-shadow: 0 12px 32px rgba(2, 6, 23, 0.18);
  background: linear-gradient(180deg, rgba(17, 29, 42, 0.98), rgba(13, 23, 34, 0.94));
}

.metric-card-green {
  border-color: rgba(34, 197, 94, 0.30);
}

.metric-card-red {
  border-color: rgba(239, 68, 68, 0.30);
}

.metric-card-label {
  color: var(--bp-text-muted);
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.metric-card-value {
  display: inline-block;
  margin-top: 0.35rem;
  font-size: 1.5rem;
  font-weight: 800;
  font-family: var(--bp-font-mono);
}

.metric-card-value.positive { color: var(--bp-success); }
.metric-card-value.negative { color: var(--bp-danger); }
.metric-card-value.neutral { color: var(--bp-text-primary); }

.info-box,
.danger-box,
.warn-box,
.success-box {
  padding: 1rem;
  margin: 0.8rem 0;
  border-radius: 0 var(--bp-radius-sm) var(--bp-radius-sm) 0;
  color: var(--bp-text-primary);
  border: 1px solid transparent;
}

.info-box {
  background: rgba(14, 116, 144, 0.14);
  border-left: 5px solid var(--bp-accent);
  border-color: rgba(30, 200, 223, 0.22);
}

.danger-box {
  background: rgba(153, 27, 27, 0.12);
  border-left: 5px solid var(--bp-danger);
  border-color: rgba(239, 68, 68, 0.20);
}

.warn-box {
  background: rgba(146, 64, 14, 0.12);
  border-left: 5px solid var(--bp-warning);
  border-color: rgba(245, 158, 11, 0.20);
}

.success-box {
  background: rgba(22, 101, 52, 0.12);
  border-left: 5px solid var(--bp-success);
  border-color: rgba(34, 197, 94, 0.20);
}

.empty-state {
  text-align: center;
  padding: 2.5rem 1rem;
  color: var(--bp-text-muted);
}

.empty-state-icon {
  font-size: 3rem;
  margin-bottom: 0.8rem;
  opacity: 0.55;
}

.empty-state-sub {
  opacity: 0.72;
}

.mkt-open,
.mkt-closed {
  padding: 4px 12px;
  border-radius: 999px;
  font-weight: 700;
  font-size: 0.8rem;
  border: 1px solid transparent;
}

.mkt-open {
  background: rgba(34, 197, 94, 0.12);
  color: #bbf7d0;
  border-color: rgba(34, 197, 94, 0.22);
}

.mkt-closed {
  background: rgba(239, 68, 68, 0.12);
  color: #fecaca;
  border-color: rgba(239, 68, 68, 0.22);
}

[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #0a121b 0%, #0f1722 100%);
  border-right: 1px solid rgba(148, 163, 184, 0.08);
}

[data-testid="stSidebar"] * {
  color: #f8fafc;
}

.paper-mode-banner {
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.92), rgba(217, 119, 6, 0.94));
  color: #111827;
  padding: 0.65rem 0.75rem;
  border-radius: var(--bp-radius-sm);
  text-align: center;
  font-weight: 800;
  letter-spacing: 0.03em;
}

.live-price-badge {
  display: inline-flex;
  align-items: baseline;
  gap: 0.45rem;
  flex-wrap: wrap;
}

.live-price-price,
.live-price-change,
.live-price-freshness {
  display: inline-flex;
  align-items: center;
}

.live-price-price {
  font-size: 1.08rem;
  font-weight: 700;
  font-family: var(--bp-font-mono);
}

.live-price-change {
  font-size: 0.85rem;
  font-weight: 600;
}

.live-price-price.positive,
.live-price-change.positive {
  color: var(--bp-success);
}

.live-price-price.negative,
.live-price-change.negative {
  color: var(--bp-danger);
}

.live-price-price.muted {
  color: var(--bp-text-muted);
}

.live-price-freshness {
  color: var(--bp-text-muted);
}

.dashboard-metric-wrap div[data-testid="stMetric"] {
  background: linear-gradient(135deg, rgba(8, 145, 178, 0.13), rgba(29, 78, 216, 0.08));
  border: 1px solid rgba(34, 211, 238, 0.18);
  border-radius: var(--bp-radius-sm);
  padding: 0.65rem 0.75rem;
  min-height: 6.25rem;
}

.startup-recovery-panel {
  margin: 0 0 1rem;
  padding: 1rem 1.1rem;
  border-radius: var(--bp-radius-md);
  border: 1px solid rgba(245, 158, 11, 0.26);
  background: linear-gradient(135deg, rgba(120, 53, 15, 0.22), rgba(69, 26, 3, 0.18));
}

.startup-recovery-title {
  color: #fde68a;
  font-size: 0.84rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 0.4rem;
}

.startup-recovery-copy {
  color: var(--bp-text-primary);
  line-height: 1.45;
}

.startup-status-value.mono {
  font-family: var(--bp-font-mono);
}

.stDataFrame {
  border-radius: var(--bp-radius-sm);
  overflow: hidden;
}

.stButton button[kind="primary"] {
  background: linear-gradient(135deg, #0f9db6, #1d4ed8);
  border: none;
  font-weight: 700;
  box-shadow: 0 8px 18px rgba(15, 157, 182, 0.24);
}

.stButton button[kind="primary"]:hover {
  background: linear-gradient(135deg, #18b5cf, #2563eb);
}
</style>
"""

BREEZE_PRO_CSS = """
<style>
.stApp {
  background:
    radial-gradient(circle at top left, rgba(30, 200, 223, 0.06), transparent 30%),
    linear-gradient(180deg, #061018 0%, #0b141d 100%);
  color: var(--bp-text-primary);
}

.page-header {
  color: var(--bp-text-primary);
}

.metric-label { color: var(--bp-text-muted); }
.metric-value {
  color: var(--bp-text-primary);
  font-weight: 700;
}

.stDataFrame thead {
  background: rgba(13, 23, 34, 0.95) !important;
}

.stDataFrame tbody tr:hover {
  background: rgba(22, 36, 53, 0.95) !important;
}

.badge-success { color: var(--bp-success); font-weight: 600; }
.badge-danger { color: var(--bp-danger); font-weight: 600; }
.badge-warning { color: var(--bp-warning); font-weight: 600; }
.badge-muted { color: var(--bp-text-muted); }

.scroll-table {
  max-height: 400px;
  overflow-y: auto;
  border: 1px solid var(--bp-border);
  border-radius: 6px;
}
</style>
"""

KEYBOARD_SHORTCUTS_JS = """
<script>
document.addEventListener('keydown', function(e) {
  if (e.altKey && e.key >= '1' && e.key <= '9') {
    e.preventDefault();
    const pages = document.querySelectorAll('[data-testid="stRadio"] label');
    const idx = parseInt(e.key) - 1;
    if (pages[idx]) pages[idx].click();
  }
  if (e.altKey && (e.key === 'r' || e.key === 'R')) {
    e.preventDefault();
    const refreshBtns = document.querySelectorAll('button');
    for (const btn of refreshBtns) {
      if (btn.textContent.includes('Refresh') || btn.textContent.includes('🔄')) {
        btn.click();
        break;
      }
    }
  }
});
</script>
"""

RESPONSIVE_CSS = """
<style>
@media (max-width: 768px) {
  section[data-testid="stSidebar"] {
    width: 0 !important;
  }

  .page-header {
    font-size: 1.2rem;
  }

  .stColumns {
    flex-direction: column !important;
  }
}
</style>
"""

APP_SHELL_CSS = """
<style>
.shell-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.95rem 1.1rem;
  border: 1px solid rgba(30, 200, 223, 0.18);
  border-radius: 16px;
  background: linear-gradient(135deg, rgba(7, 16, 24, 0.96), rgba(13, 23, 34, 0.94));
  box-shadow: 0 18px 45px rgba(2, 6, 23, 0.22);
  margin-bottom: 0.9rem;
}

.shell-brand {
  display: flex;
  align-items: center;
  gap: 0.85rem;
}

.shell-brand-mark {
  width: 2.5rem;
  height: 2.5rem;
  border-radius: 0.8rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0f9db6, #1d4ed8);
  color: #f8fafc;
  font-weight: 800;
  font-size: 1rem;
  box-shadow: 0 10px 22px rgba(29, 78, 216, 0.28);
}

.shell-brand-copy,
.shell-rail-copy {
  display: flex;
  flex-direction: column;
  gap: 0.08rem;
}

.shell-brand-name,
.shell-rail-name {
  color: #f8fafc;
  font-size: 1rem;
  font-weight: 800;
  line-height: 1.1;
}

.shell-brand-meta,
.shell-rail-meta {
  color: var(--bp-text-muted);
  font-size: 0.78rem;
}

.shell-page-title {
  color: #f8fafc;
  font-size: 1.1rem;
  font-weight: 700;
  line-height: 1.2;
  margin-bottom: 0.15rem;
}

.shell-page-copy {
  color: #b7c8da;
  font-size: 0.84rem;
}

.shell-status-stack {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  justify-content: flex-end;
}

.shell-pill {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 0.38rem 0.75rem;
  font-size: 0.8rem;
  font-weight: 700;
  border: 1px solid transparent;
}

.shell-pill.connected {
  color: #bbf7d0;
  background: rgba(22, 163, 74, 0.14);
  border-color: rgba(34, 197, 94, 0.25);
}

.shell-pill.warning {
  color: #fde68a;
  background: rgba(245, 158, 11, 0.14);
  border-color: rgba(245, 158, 11, 0.24);
}

.shell-pill.offline {
  color: #cbd5e1;
  background: rgba(71, 85, 105, 0.28);
  border-color: rgba(148, 163, 184, 0.18);
}

.shell-pill.market {
  color: #67e8f9;
  background: rgba(8, 145, 178, 0.15);
  border-color: rgba(34, 211, 238, 0.18);
}

.shell-note {
  color: var(--bp-text-muted);
  font-size: 0.82rem;
  margin: 0.1rem 0 0.85rem;
}

.shell-rail-brand {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  margin-bottom: 0.75rem;
}

.shell-rail-mark {
  width: 2.15rem;
  height: 2.15rem;
  border-radius: 0.75rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0f9db6, #1d4ed8);
  color: #f8fafc;
  font-weight: 800;
}

@media (max-width: 900px) {
  .shell-bar {
    padding: 0.8rem 0.9rem;
  }

  .shell-page-copy {
    display: none;
  }
}
</style>
"""

SIDEBAR_COMPACT_CSS = """
<style>
[data-testid="stSidebar"] {
  min-width: 14rem !important;
  max-width: 14rem !important;
}

[data-testid="stSidebar"] > div:first-child {
  width: 14rem !important;
}

.rail-detail {
  display: none !important;
}
</style>
"""

STARTUP_SCREEN_CSS = """
<style>
.startup-hero {
  background:
    radial-gradient(circle at top right, rgba(30, 200, 223, 0.12), transparent 28%),
    linear-gradient(135deg, rgba(7, 16, 24, 0.98), rgba(9, 35, 56, 0.94));
  border: 1px solid rgba(34, 211, 238, 0.18);
  border-radius: 18px;
  padding: 1.5rem;
  margin-bottom: 1.25rem;
  box-shadow: 0 20px 50px rgba(2, 6, 23, 0.35);
}

.startup-kicker {
  color: #67e8f9;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  margin-bottom: 0.65rem;
}

.startup-title {
  color: #f8fafc;
  font-size: 2rem;
  font-weight: 800;
  line-height: 1.1;
  margin-bottom: 0.55rem;
}

.startup-subtitle {
  color: rgba(226, 232, 240, 0.84);
  font-size: 1rem;
  max-width: 50rem;
}

.startup-badge-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem;
  margin-top: 1rem;
}

.startup-badge {
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(15, 23, 42, 0.42);
  color: #e2e8f0;
  border-radius: 999px;
  padding: 0.4rem 0.8rem;
  font-size: 0.85rem;
  font-weight: 600;
}

.startup-status-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.85rem;
  margin-bottom: 1rem;
}

.startup-status-card {
  border-radius: 14px;
  padding: 0.95rem 1rem;
  min-height: 7rem;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(15, 23, 42, 0.82);
}

.startup-status-card.ok { border-color: rgba(34, 197, 94, 0.35); }
.startup-status-card.warn { border-color: rgba(245, 158, 11, 0.35); }
.startup-status-card.danger { border-color: rgba(248, 113, 113, 0.35); }

.startup-status-label {
  color: #94a3b8;
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 0.55rem;
}

.startup-status-value {
  color: #f8fafc;
  font-size: 1.05rem;
  font-weight: 700;
  margin-bottom: 0.35rem;
}

.startup-status-detail {
  color: rgba(226, 232, 240, 0.7);
  font-size: 0.88rem;
  line-height: 1.35;
}

.startup-preview-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.85rem;
  margin-top: 0.65rem;
}

.startup-preview-card {
  background: rgba(248, 250, 252, 0.04);
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 14px;
  padding: 1rem;
}

.startup-preview-title {
  color: #f8fafc;
  font-size: 1rem;
  font-weight: 700;
  margin-bottom: 0.35rem;
}

.startup-preview-copy {
  color: rgba(226, 232, 240, 0.72);
  font-size: 0.9rem;
  line-height: 1.4;
}

.startup-side-note {
  color: rgba(226, 232, 240, 0.78);
  font-size: 0.92rem;
  line-height: 1.5;
  padding: 1rem;
  border-radius: 14px;
  background: rgba(15, 23, 42, 0.62);
  border: 1px solid rgba(148, 163, 184, 0.14);
}

.startup-shortcuts {
  color: #94a3b8;
  font-size: 0.84rem;
  margin-top: 0.85rem;
}

@media (max-width: 900px) {
  .startup-status-grid,
  .startup-preview-grid {
    grid-template-columns: 1fr;
  }

  .startup-title {
    font-size: 1.65rem;
  }
}
</style>
"""
