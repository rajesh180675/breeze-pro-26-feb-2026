import sys
import types


fake_st = types.ModuleType("streamlit")
fake_st.secrets = {}
fake_st.session_state = {}
sys.modules.setdefault("streamlit", fake_st)

from session_manager import SessionState, check_session_health


class _Client:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    def get_funds(self):
        if self._exc is not None:
            raise self._exc
        return self._response


def _seed_auth_state():
    fake_st.session_state.clear()
    SessionState.initialize()
    fake_st.session_state["authenticated"] = True
    fake_st.session_state["breeze_client"] = object()
    fake_st.session_state["api_key"] = "k"
    fake_st.session_state["api_secret"] = "s"
    fake_st.session_state["session_token"] = "t"
    fake_st.session_state["login_time"] = "2026-03-09T00:00:00"


def test_check_session_health_accepts_success():
    _seed_auth_state()
    client = _Client(response={"success": True, "data": {}, "message": "", "error_code": None})
    assert check_session_health(client) is True
    assert fake_st.session_state["authenticated"] is True


def test_check_session_health_clears_state_on_permanent_error_code():
    _seed_auth_state()
    client = _Client(
        response={"success": False, "data": {}, "message": "invalid session", "error_code": "PERMANENT"}
    )
    assert check_session_health(client) is False
    assert fake_st.session_state["authenticated"] is False
    assert fake_st.session_state["breeze_client"] is None
    assert fake_st.session_state["api_key"] == ""
    assert fake_st.session_state["api_secret"] == ""
    assert fake_st.session_state["session_token"] == ""
    assert fake_st.session_state["login_time"] is None


def test_check_session_health_ignores_transient_failure():
    _seed_auth_state()
    client = _Client(response={"success": False, "message": "gateway timeout", "error_code": "MAX_RETRIES"})
    assert check_session_health(client) is True
    assert fake_st.session_state["authenticated"] is True
