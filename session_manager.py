"""Session management, credentials, caching."""

import streamlit as st
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import logging
import hashlib
import app_config as C

log = logging.getLogger(__name__)


class Credentials:
    @staticmethod
    def get_stored_api_key():
        """Safely fetch API Key from secrets."""
        try:
            # Check strictly for the key in secrets
            if "BREEZE_API_KEY" in st.secrets:
                return str(st.secrets["BREEZE_API_KEY"]).strip()
            return ""
        except Exception:
            return ""

    @staticmethod
    def get_stored_api_secret():
        """Safely fetch API Secret from secrets."""
        try:
            if "BREEZE_API_SECRET" in st.secrets:
                return str(st.secrets["BREEZE_API_SECRET"]).strip()
            return ""
        except Exception:
            return ""

    @staticmethod
    def has_stored_credentials():
        """Check if both keys exist in secrets."""
        k = Credentials.get_stored_api_key()
        s = Credentials.get_stored_api_secret()
        return bool(k and s)

    @staticmethod
    def get_all_credentials() -> Tuple[str, str, str]:
        """
        Get credentials with priority: 
        1. Secrets (if available)
        2. Session State (runtime input)
        """
        # Try secrets first
        api_key = Credentials.get_stored_api_key()
        api_secret = Credentials.get_stored_api_secret()

        # Fallback to session state if secrets missing
        if not api_key:
            api_key = st.session_state.get("api_key", "")
        if not api_secret:
            api_secret = st.session_state.get("api_secret", "")

        return (
            api_key,
            api_secret,
            st.session_state.get("session_token", "")
        )

    @staticmethod
    def save_runtime_credentials(api_key, api_secret, session_token):
        """Save manual inputs to session state."""
        st.session_state.api_key = api_key
        st.session_state.api_secret = api_secret
        st.session_state.session_token = session_token
        st.session_state.login_time = datetime.now(C.IST).isoformat()

    @staticmethod
    def clear_runtime_credentials():
        for k in ("api_key", "api_secret", "session_token"):
            st.session_state[k] = ""
        st.session_state.login_time = None


class SessionState:
    DEFAULTS = {
        "authenticated": False, "breeze_client": None, "current_page": "Dashboard",
        "selected_instrument": "NIFTY", "api_key": "", "api_secret": "",
        "session_token": "", "login_time": None, "user_name": "", "user_id": "",
        "debug_mode": False, "activity_log": [], "_order_in_progress": False,
    }

    @staticmethod
    def initialize():
        for k, v in SessionState.DEFAULTS.items():
            if k not in st.session_state:
                st.session_state[k] = v

    @staticmethod
    def is_authenticated():
        return st.session_state.get("authenticated", False)

    @staticmethod
    def get_client():
        return st.session_state.get("breeze_client")

    @staticmethod
    def set_authentication(auth, client=None):
        st.session_state.authenticated = auth
        st.session_state.breeze_client = client

    @staticmethod
    def get_current_page():
        return st.session_state.get("current_page", "Dashboard")

    @staticmethod
    def navigate_to(page):
        st.session_state.current_page = page

    @staticmethod
    def log_activity(action, detail=""):
        if "activity_log" not in st.session_state:
            st.session_state.activity_log = []
        st.session_state.activity_log.insert(0, {
            "time": datetime.now(C.IST).strftime("%H:%M:%S"),
            "action": action, "detail": detail
        })
        st.session_state.activity_log = st.session_state.activity_log[:C.MAX_ACTIVITY_LOG_ENTRIES]

    @staticmethod
    def get_activity_log():
        return st.session_state.get("activity_log", [])

    @staticmethod
    def get_login_duration():
        lt = st.session_state.get("login_time")
        if not lt:
            return None
        try:
            login_dt = datetime.fromisoformat(lt)
            now = datetime.now(C.IST)
            if login_dt.tzinfo is None:
                login_dt = C.IST.localize(login_dt)
            s = int((now - login_dt).total_seconds())
            return f"{s // 3600}h {(s % 3600) // 60}m"
        except Exception:
            return None

    @staticmethod
    def is_session_stale():
        lt = st.session_state.get("login_time")
        if not lt:
            return True
        try:
            d = datetime.fromisoformat(lt)
            if d.tzinfo is None:
                d = C.IST.localize(d)
            return (datetime.now(C.IST) - d).total_seconds() > C.SESSION_WARNING_SECONDS
        except Exception:
            return True

    @staticmethod
    def is_session_expired():
        lt = st.session_state.get("login_time")
        if not lt:
            return True
        try:
            d = datetime.fromisoformat(lt)
            if d.tzinfo is None:
                d = C.IST.localize(d)
            return (datetime.now(C.IST) - d).total_seconds() > C.SESSION_TIMEOUT_SECONDS
        except Exception:
            return True


class CacheManager:
    @staticmethod
    def _key(k, t):
        return f"{t}_{hashlib.md5(k.encode()).hexdigest()}"

    @staticmethod
    def set(key, value, cache_type="general", ttl=30):
        ck = CacheManager._key(key, cache_type)
        cache_k = f"{cache_type}_cache"
        ts_k = f"{cache_type}_ts"
        if cache_k not in st.session_state:
            st.session_state[cache_k] = {}
        if ts_k not in st.session_state:
            st.session_state[ts_k] = {}
        st.session_state[cache_k][ck] = value
        st.session_state[ts_k][ck] = {"time": datetime.now(), "ttl": ttl}

    @staticmethod
    def get(key, cache_type="general"):
        ck = CacheManager._key(key, cache_type)
        cache = st.session_state.get(f"{cache_type}_cache", {})
        ts = st.session_state.get(f"{cache_type}_ts", {})
        if ck not in cache:
            return None
        if ck in ts:
            info = ts[ck]
            if (datetime.now() - info["time"]).total_seconds() > info["ttl"]:
                CacheManager.invalidate(key, cache_type)
                return None
        return cache[ck]

    @staticmethod
    def invalidate(key, cache_type="general"):
        ck = CacheManager._key(key, cache_type)
        st.session_state.get(f"{cache_type}_cache", {}).pop(ck, None)
        st.session_state.get(f"{cache_type}_ts", {}).pop(ck, None)

    @staticmethod
    def clear_all(cache_type=None):
        keys = [k for k in list(st.session_state.keys())
                if k.endswith("_cache") or k.endswith("_ts")]
        if cache_type:
            keys = [k for k in keys if k.startswith(cache_type)]
        for k in keys:
            st.session_state[k] = {}


class Notifications:
    @staticmethod
    def success(msg):
        try:
            st.toast(msg, icon="✅")
        except Exception:
            pass

    @staticmethod
    def error(msg):
        try:
            st.toast(msg, icon="❌")
        except Exception:
            pass
