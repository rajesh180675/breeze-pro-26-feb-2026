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

app_main.render_sidebar = lambda: st.sidebar.caption("Sidebar navigation")
app_main.render_alert_banners = lambda: None
app_main.page_dashboard = lambda: st.write("Dashboard body")
app_main.page_startup = lambda: st.write("Startup screen")
app_main.get_client = lambda: None
app_main.SessionState.is_authenticated = staticmethod(lambda: False)

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

app_main.render_sidebar = lambda: st.sidebar.caption("Sidebar navigation")
app_main.render_alert_banners = lambda: None
app_main.page_dashboard = lambda: st.write("Dashboard body")
app_main.PAGE_FN["🏠 Dashboard"] = app_main.page_dashboard
app_main.get_client = lambda: None
app_main.SessionState.is_authenticated = staticmethod(lambda: True)
app_main.SessionState.is_session_expired = staticmethod(lambda: False)
app_main.SessionState.get_current_page = staticmethod(lambda: "🏠 Dashboard")

app_main.main()
"""


def test_logged_out_users_land_on_startup_screen():
    at = AppTest.from_string(_startup_layout_script())
    at.run(timeout=10)

    assert [item.label for item in at.button] == ["Hide Menu"]
    assert not at.sidebar.caption
    assert "Startup screen" in [item.value for item in at.markdown]
    assert "Dashboard body" not in [item.value for item in at.markdown]


def test_workspace_layout_can_hide_and_restore_sidebar():
    at = AppTest.from_string(_workspace_layout_script())
    at.run(timeout=10)

    assert [item.label for item in at.button] == ["Hide Menu"]
    assert [item.value for item in at.sidebar.caption] == ["Sidebar navigation"]
    assert "Dashboard body" in [item.value for item in at.markdown]

    at.button[0].click().run()

    assert [item.label for item in at.button] == ["Show Menu"]
    assert not at.sidebar.caption
    assert "Left menu hidden. Use Show Menu to reopen it." in [item.value for item in at.caption]
    assert "Dashboard body" in [item.value for item in at.markdown]

    at.button[0].click().run()

    assert [item.label for item in at.button] == ["Hide Menu"]
    assert [item.value for item in at.sidebar.caption] == ["Sidebar navigation"]
