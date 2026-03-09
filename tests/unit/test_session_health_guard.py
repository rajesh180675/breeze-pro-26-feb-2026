import sys
import types
from unittest.mock import patch


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


fake_st = types.ModuleType("streamlit")
fake_st.secrets = {}
fake_st.session_state = _SessionState({"api_key": "k", "api_secret": "s", "session_token": "t"})
sys.modules.setdefault("streamlit", fake_st)

import session_manager


class _Client:
    def __init__(self, resp):
        self._resp = resp

    def get_funds(self):
        return self._resp


def test_check_session_health_true_on_success():
    with patch.object(session_manager, "st", fake_st):
        assert session_manager.check_session_health(_Client({"success": True, "data": {}})) is True


def test_check_session_health_false_and_clears_on_permanent_error():
    fake_st.session_state.update({"api_key": "k", "api_secret": "s", "session_token": "t"})
    with patch.object(session_manager, "st", fake_st):
        ok = session_manager.check_session_health(_Client({"success": False, "error": "invalid session"}))
        assert ok is False
        assert fake_st.session_state["api_key"] == ""
        assert fake_st.session_state["api_secret"] == ""
        assert fake_st.session_state["session_token"] == ""


def test_check_session_health_true_on_transient_error():
    fake_st.session_state.update({"api_key": "k", "api_secret": "s", "session_token": "t"})
    with patch.object(session_manager, "st", fake_st):
        ok = session_manager.check_session_health(_Client({"success": False, "error": "503 service unavailable"}))
        assert ok is True
        assert fake_st.session_state["api_key"] == "k"
