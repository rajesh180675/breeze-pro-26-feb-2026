import pytest
from streamlit.testing.v1 import AppTest


pytestmark = pytest.mark.integration


def _find_button(at: AppTest, label: str):
    return next(button for button in at.button if button.label == label)


def _startup_layout_script() -> str:
    return """
import sys
import types
import importlib.util
import streamlit as st

if "breeze_connect" not in sys.modules:
    stub = types.ModuleType("breeze_connect")

    class BreezeConnect:
        pass

    stub.BreezeConnect = BreezeConnect
    sys.modules["breeze_connect"] = stub

spec = importlib.util.spec_from_file_location("app_main_test", r"/workspaces/breeze-pro-26-feb-2026/app.py")
app_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_main)

app_main.components.html = lambda *args, **kwargs: None
app_main.render_sidebar = lambda: st.sidebar.caption("Sidebar navigation")
app_main.render_alert_banners = lambda: None
app_main.page_dashboard = lambda: st.write("Dashboard body")
app_main.page_startup = lambda: st.write("Startup screen")
app_main.get_client = lambda: None
app_main.C.get_market_status = lambda: {"label": "Market Open", "status": "open"}
app_main.SessionState.is_authenticated = staticmethod(lambda: False)
app_main.SessionState.is_session_expired = staticmethod(lambda: False)

app_main.main()
"""


def _workspace_layout_script() -> str:
    return """
import sys
import types
import importlib.util
import streamlit as st

if "breeze_connect" not in sys.modules:
    stub = types.ModuleType("breeze_connect")

    class BreezeConnect:
        pass

    stub.BreezeConnect = BreezeConnect
    sys.modules["breeze_connect"] = stub

spec = importlib.util.spec_from_file_location("app_main_test", r"/workspaces/breeze-pro-26-feb-2026/app.py")
app_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_main)

app_main.components.html = lambda *args, **kwargs: None
app_main.render_sidebar = lambda: st.sidebar.caption("Sidebar navigation")
app_main.render_alert_banners = lambda: None
app_main.page_dashboard = lambda: st.write("Dashboard body")
app_main.PAGE_FN["🏠 Dashboard"] = app_main.page_dashboard
app_main.get_client = lambda: None
app_main.C.get_market_status = lambda: {"label": "Market Open", "status": "open"}
app_main.SessionState.is_authenticated = staticmethod(lambda: True)
app_main.SessionState.is_session_expired = staticmethod(lambda: False)
app_main.SessionState.get_current_page = staticmethod(lambda: "🏠 Dashboard")

app_main.main()
"""


def _compact_option_chain_layout_script() -> str:
    return """
import sys
import types
import importlib.util
import streamlit as st

if "breeze_connect" not in sys.modules:
    stub = types.ModuleType("breeze_connect")

    class BreezeConnect:
        pass

    stub.BreezeConnect = BreezeConnect
    sys.modules["breeze_connect"] = stub

st.session_state["nav_mode"] = "compact"

spec = importlib.util.spec_from_file_location("app_main_test", r"/workspaces/breeze-pro-26-feb-2026/app.py")
app_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_main)

app_main.components.html = lambda *args, **kwargs: None
app_main.render_sidebar = lambda: st.sidebar.caption("Sidebar navigation")
app_main.render_alert_banners = lambda: None
app_main.page_option_chain = lambda: st.write("Option chain body")
app_main.PAGE_FN["⛓️ Option Chain"] = app_main.page_option_chain
app_main.get_client = lambda: None
app_main.C.get_market_status = lambda: {"label": "Market Open", "status": "open"}
app_main.SessionState.is_authenticated = staticmethod(lambda: True)
app_main.SessionState.is_session_expired = staticmethod(lambda: False)
app_main.SessionState.get_current_page = staticmethod(lambda: "⛓️ Option Chain")

app_main.main()
"""


def _expired_session_recovery_script() -> str:
    return """
import sys
import types
import importlib.util
import streamlit as st

if "breeze_connect" not in sys.modules:
    stub = types.ModuleType("breeze_connect")

    class BreezeConnect:
        pass

    stub.BreezeConnect = BreezeConnect
    sys.modules["breeze_connect"] = stub

st.session_state["authenticated"] = True
st.session_state["force_expired"] = True
st.session_state["current_page"] = "⛓️ Option Chain"

spec = importlib.util.spec_from_file_location("app_main_test", r"/workspaces/breeze-pro-26-feb-2026/app.py")
app_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_main)

app_main.components.html = lambda *args, **kwargs: None
app_main.render_sidebar = lambda: st.sidebar.caption("Sidebar navigation")
app_main.render_alert_banners = lambda: None
app_main.page_startup = lambda: st.write(
    f"Startup recovery: {app_main._get_startup_recovery_state().get('reason', 'missing')}"
)
app_main.get_client = lambda: None
app_main.C.get_market_status = lambda: {"label": "Market Open", "status": "open"}
app_main.SessionState.is_authenticated = staticmethod(lambda: st.session_state.get("authenticated", False))
app_main.SessionState.is_session_expired = staticmethod(lambda: st.session_state.get("force_expired", False))
app_main.SessionState.get_current_page = staticmethod(lambda: st.session_state.get("current_page", "🏠 Dashboard"))
app_main._cleanup_session = lambda reason="", detail="": (
    st.session_state.__setitem__("authenticated", False),
    st.session_state.__setitem__("force_expired", False),
    st.session_state.__setitem__("current_page", "🏠 Dashboard"),
    st.session_state.__setitem__(
        "startup_recovery_state",
        {"reason": reason or "expired", "detail": detail or "Reconnect with a fresh token."},
    ),
)

app_main.main()
"""


def _sidebar_module_navigation_script() -> str:
    return """
import sys
import types
import importlib.util
import streamlit as st

if "breeze_connect" not in sys.modules:
    stub = types.ModuleType("breeze_connect")

    class BreezeConnect:
        pass

    stub.BreezeConnect = BreezeConnect
    sys.modules["breeze_connect"] = stub

st.session_state["authenticated"] = False
st.session_state["nav_mode"] = "expanded"
if "post_login_target" not in st.session_state:
    st.session_state["post_login_target"] = "🏠 Dashboard"

spec = importlib.util.spec_from_file_location("app_main_test", r"/workspaces/breeze-pro-26-feb-2026/app.py")
app_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_main)

with st.sidebar:
    app_main.render_sidebar_module_navigation("sidebar_test")

st.write(f"Launch target: {app_main._page_display_name(app_main._get_post_login_target())}")
"""


def _workspace_module_launcher_script() -> str:
    return """
import sys
import types
import importlib.util
import streamlit as st

if "breeze_connect" not in sys.modules:
    stub = types.ModuleType("breeze_connect")

    class BreezeConnect:
        pass

    stub.BreezeConnect = BreezeConnect
    sys.modules["breeze_connect"] = stub

st.session_state["authenticated"] = True
if "current_page" not in st.session_state:
    st.session_state["current_page"] = "🏠 Dashboard"

spec = importlib.util.spec_from_file_location("app_main_test", r"/workspaces/breeze-pro-26-feb-2026/app.py")
app_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_main)

app_main.render_workspace_module_directory("workspace_test")
st.write(f"Current module: {app_main._page_display_name(app_main.SessionState.get_current_page())}")
"""


def _dashboard_without_workspace_launcher_script() -> str:
    return """
import sys
import types
import importlib.util
import streamlit as st

if "breeze_connect" not in sys.modules:
    stub = types.ModuleType("breeze_connect")

    class BreezeConnect:
        pass

    stub.BreezeConnect = BreezeConnect
    sys.modules["breeze_connect"] = stub

st.session_state["authenticated"] = True
st.session_state["current_page"] = "🏠 Dashboard"

spec = importlib.util.spec_from_file_location("app_main_test", r"/workspaces/breeze-pro-26-feb-2026/app.py")
app_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_main)

app_main.page_header = lambda *args, **kwargs: None
app_main.render_auto_refresh = lambda *args, **kwargs: None
app_main.get_client = lambda: object()
app_main.get_dashboard_metrics = lambda client: {
    "NIFTY SPOT": {"value": "22000", "delta": ""},
    "BANKNIFTY SPOT": {"value": "48000", "delta": ""},
    "VIX": {"value": "15", "delta": ""},
    "NIFTY PCR": {"value": "1.00", "delta": ""},
    "NIFTY MAX PAIN": {"value": "22000", "delta": ""},
    "MARKET STATUS": {"value": "Open", "delta": ""},
    "SESSION TIME": {"value": "1h", "delta": ""},
}
app_main.get_market_regime_snapshot = lambda **kwargs: {"regime": "RANGE_BOUND", "confidence": 0.5, "risk_level": "MEDIUM"}
app_main.get_cached_funds = lambda client: {
    "allocated_fno": 25000,
    "total_balance": 100000,
    "unallocated": 75000,
}
app_main.get_cached_positions = lambda client: []
app_main.split_positions = lambda positions: ([], [])
app_main.enrich_positions = lambda positions: []
app_main._db.get_trade_summary = lambda: None
app_main._db.get_pnl_history = lambda days: []
app_main.render_workspace_module_directory = lambda key: st.write("WORKSPACE MODULE DIRECTORY")
app_main.SessionState.is_authenticated = staticmethod(lambda: True)

app_main.page_dashboard()
"""


def test_logged_out_users_land_on_startup_screen():
    at = AppTest.from_string(_startup_layout_script())
    at.run(timeout=20)

    assert [item.label for item in at.button] == ["Connect", "Collapse Sidebar"]
    assert [item.value for item in at.sidebar.caption] == ["Sidebar navigation"]
    assert "Startup screen" in [item.value for item in at.markdown]
    assert "Dashboard body" not in [item.value for item in at.markdown]


def test_workspace_layout_can_compact_and_restore_sidebar():
    at = AppTest.from_string(_workspace_layout_script())
    at.run(timeout=20)

    assert [item.label for item in at.button] == ["Reconnect", "Disconnect", "Collapse Sidebar"]
    assert [item.value for item in at.sidebar.caption] == ["Sidebar navigation"]
    assert "Dashboard body" in [item.value for item in at.markdown]

    at.button[2].click().run()

    assert [item.label for item in at.button] == ["Reconnect", "Disconnect", "Expand Sidebar"]
    assert [item.value for item in at.sidebar.caption] == ["Sidebar navigation"]
    assert "The left module rail is collapsed. Expand it to browse the full workspace." in [item.value for item in at.caption]
    assert "Dashboard body" in [item.value for item in at.markdown]

    at.button[2].click().run()

    assert [item.label for item in at.button] == ["Reconnect", "Disconnect", "Collapse Sidebar"]
    assert [item.value for item in at.sidebar.caption] == ["Sidebar navigation"]


def test_compact_rail_keeps_option_chain_accessible():
    at = AppTest.from_string(_compact_option_chain_layout_script())
    at.run(timeout=20)

    assert [item.label for item in at.button] == ["Reconnect", "Disconnect", "Expand Sidebar"]
    assert [item.value for item in at.sidebar.caption] == ["Sidebar navigation"]
    assert "The left module rail is collapsed. Expand it to browse the full workspace." in [item.value for item in at.caption]
    assert "Option chain body" in [item.value for item in at.markdown]


def test_expired_session_routes_to_startup_with_reconnect_action():
    at = AppTest.from_string(_expired_session_recovery_script())
    at.run(timeout=20)

    assert [item.label for item in at.button] == ["Reconnect", "Collapse Sidebar"]
    assert [item.value for item in at.sidebar.caption] == ["Sidebar navigation"]
    assert any("Session Expired" in item.value for item in at.markdown)
    assert "Startup recovery: expired" in [item.value for item in at.markdown]


def test_prelogin_sidebar_module_navigation_exposes_full_workspace():
    at = AppTest.from_string(_sidebar_module_navigation_script())
    at.run(timeout=20)

    labels = [item.label for item in at.button]
    assert "Dashboard" in labels
    assert "Option Chain" in labels
    assert "Historical Data" in labels
    assert "Futures Trading" in labels
    assert "Strategy Builder" in labels
    assert "Analytics" in labels
    assert "Risk Monitor" in labels
    assert "Paper Trading" in labels


def test_prelogin_sidebar_module_navigation_updates_launch_target():
    at = AppTest.from_string(_sidebar_module_navigation_script())
    at.run(timeout=20)

    _find_button(at, "Analytics").click().run()

    assert "Launch target: Analytics" in [item.value for item in at.markdown]


def test_workspace_module_launcher_can_open_previous_modules():
    at = AppTest.from_string(_workspace_module_launcher_script())
    at.run(timeout=20)

    _find_button(at, "Futures Trading").click().run()

    assert "Current module: Futures Trading" in [item.value for item in at.markdown]


def test_dashboard_workspace_stays_clear_of_module_launcher_cards():
    at = AppTest.from_string(_dashboard_without_workspace_launcher_script())
    at.run(timeout=20)

    assert "WORKSPACE MODULE DIRECTORY" not in [item.value for item in at.markdown]
    assert any(
        "Use the left sidebar to switch between Option Chain, Paper Trading, Square Off, Analytics"
        in item.value
        for item in at.markdown
    )
