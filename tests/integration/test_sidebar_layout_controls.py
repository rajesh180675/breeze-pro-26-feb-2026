import pytest
from streamlit.testing.v1 import AppTest


pytestmark = pytest.mark.integration


def _sidebar_layout_script() -> str:
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
app_main.get_client = lambda: None
app_main.SessionState.is_authenticated = staticmethod(lambda: False)

app_main.main()
"""


def test_main_layout_can_hide_and_restore_sidebar():
    at = AppTest.from_string(_sidebar_layout_script())
    at.run()

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
