import pytest
from streamlit.testing.v1 import AppTest


pytestmark = pytest.mark.integration


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


def test_logged_out_users_land_on_startup_screen():
    at = AppTest.from_string(_startup_layout_script())
    at.run(timeout=10)

    assert [item.label for item in at.button] == ["Connect", "Compact Menu"]
    assert [item.value for item in at.sidebar.caption] == ["Sidebar navigation"]
    assert "Startup screen" in [item.value for item in at.markdown]
    assert "Dashboard body" not in [item.value for item in at.markdown]


def test_workspace_layout_can_compact_and_restore_sidebar():
    at = AppTest.from_string(_workspace_layout_script())
    at.run(timeout=10)

    assert [item.label for item in at.button] == ["Reconnect", "Disconnect", "Compact Menu"]
    assert [item.value for item in at.sidebar.caption] == ["Sidebar navigation"]
    assert "Dashboard body" in [item.value for item in at.markdown]

    at.button[2].click().run()

    assert [item.label for item in at.button] == ["Reconnect", "Disconnect", "Expand Menu"]
    assert [item.value for item in at.sidebar.caption] == ["Sidebar navigation"]
    assert "Navigation rail is compact. Expand it for full context." in [item.value for item in at.caption]
    assert "Dashboard body" in [item.value for item in at.markdown]

    at.button[2].click().run()

    assert [item.label for item in at.button] == ["Reconnect", "Disconnect", "Compact Menu"]
    assert [item.value for item in at.sidebar.caption] == ["Sidebar navigation"]


def test_compact_rail_keeps_option_chain_accessible():
    at = AppTest.from_string(_compact_option_chain_layout_script())
    at.run(timeout=10)

    assert [item.label for item in at.button] == ["Reconnect", "Disconnect", "Expand Menu"]
    assert [item.value for item in at.sidebar.caption] == ["Sidebar navigation"]
    assert "Navigation rail is compact. Expand it for full context." in [item.value for item in at.caption]
    assert "Option chain body" in [item.value for item in at.markdown]


def test_expired_session_routes_to_startup_with_reconnect_action():
    at = AppTest.from_string(_expired_session_recovery_script())
    at.run(timeout=10)

    assert [item.label for item in at.button] == ["Reconnect", "Compact Menu"]
    assert [item.value for item in at.sidebar.caption] == ["Sidebar navigation"]
    assert any("Session Expired" in item.value for item in at.markdown)
    assert "Startup recovery: expired" in [item.value for item in at.markdown]
