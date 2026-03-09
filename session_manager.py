"""Session management, credentials, caching."""

import streamlit as st
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import hashlib
import base64
import hmac
import struct
import time as _time
import app_config as C

log = logging.getLogger(__name__)


# Session health checks are throttled in app.get_client()
_SESSION_HEALTH_CHECK_INTERVAL = 300


def check_session_health(client: Any) -> bool:
    """Validate session token health with a lightweight funds call.

    Returns False only for *permanent* auth/session failures.
    """
    try:
        resp = client.get_funds()
    except (ConnectionError, TimeoutError) as exc:
        log.warning("Session health check transient failure: %s", exc)
        return True
    except Exception as exc:  # pragma: no cover - defensive for SDK/network errors
        log.warning("Session health check unexpected error: %s", exc)
        return True

    if not isinstance(resp, dict):
        return True

    if resp.get("success"):
        return True

    payload = resp.get("data") if isinstance(resp.get("data"), dict) else {}
    err_text = " ".join(
        str(v) for v in [
            resp.get("error"),
            resp.get("message"),
            payload.get("Error"),
            payload.get("Status"),
        ] if v
    ).lower()

    permanent_markers = (
        "invalid session",
        "session expired",
        "unauthorized",
        "forbidden",
    )
    if any(marker in err_text for marker in permanent_markers):
        Credentials.clear_runtime_credentials()
        log.warning("Detected permanent session error during health check: %s", err_text)
        return False
    return True


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
        "authenticated": False, "breeze_client": None, "current_page": "🏠 Dashboard",
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
        return st.session_state.get("current_page", "🏠 Dashboard")

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

    @staticmethod
    def warning(msg):
        try:
            st.toast(msg, icon="⚠️")
        except Exception:
            pass

    @staticmethod
    def info(msg):
        try:
            st.toast(msg, icon="ℹ️")
        except Exception:
            pass


def generate_totp(secret: str, digits: int = 6, period: int = 30) -> str:
    """Generate RFC6238 TOTP from a base32 secret."""
    secret_clean = str(secret or "").upper().replace(" ", "").replace("-", "")
    if not secret_clean:
        raise ValueError("Invalid TOTP secret: secret is empty")
    padding = (8 - len(secret_clean) % 8) % 8
    secret_padded = secret_clean + "=" * padding

    try:
        key = base64.b32decode(secret_padded, casefold=True)
    except Exception as e:
        raise ValueError(f"Invalid TOTP secret: {e}") from e

    counter = int(_time.time()) // int(period)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    code = code_int % (10 ** int(digits))
    return str(code).zfill(int(digits))


def auto_connect_with_totp(client, api_key: str, session_token: str, totp_secret: Optional[str] = None) -> Dict:
    """Connect with explicit token or auto-generated TOTP from secret.

    ``api_key`` is accepted for interface compatibility but the client already
    holds its own API key from construction time.  If the caller needs to
    connect with a *different* API key they should create a new client.
    """
    token = str(session_token or "").strip()
    if totp_secret and not token:
        token = generate_totp(totp_secret)
        log.info("Auto-generated TOTP for login")
    if not token:
        raise ValueError("session_token or totp_secret must be supplied")
    return client.connect(token)


# ── Task 4.1: Multi-Account Support with Fernet Encryption ────


class MultiAccountManager:
    """Manage multiple account profiles with encrypted credentials (Task 4.1).

    Credentials are encrypted at rest using Fernet symmetric encryption.
    The encryption key is derived from a master password via PBKDF2.
    """

    _SALT = b"breeze_pro_salt_v1"  # Fixed salt for key derivation
    _ITERATIONS = 100_000

    def __init__(self, master_password: str = ""):
        self._fernet: Optional[Any] = None
        if master_password:
            self._init_fernet(master_password)

    def _init_fernet(self, master_password: str) -> None:
        """Derive Fernet key from master password via PBKDF2."""
        try:
            import hashlib as _hl
            dk = _hl.pbkdf2_hmac(
                "sha256",
                master_password.encode(),
                self._SALT,
                self._ITERATIONS,
            )
            key = base64.urlsafe_b64encode(dk[:32])
            # Use cryptography.fernet if available, else basic fallback
            try:
                from cryptography.fernet import Fernet
                self._fernet = Fernet(key)
            except ImportError:
                log.warning("cryptography package not available; credentials stored as base64 only")
                self._fernet = _Base64Fallback(key)
        except Exception as exc:
            log.error("MultiAccountManager key derivation failed: %s", exc)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a string credential."""
        if not self._fernet:
            return plaintext
        try:
            return self._fernet.encrypt(plaintext.encode()).decode()
        except Exception as exc:
            log.error("Encryption failed: %s", exc)
            return plaintext

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt an encrypted credential."""
        if not self._fernet:
            return ciphertext
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except Exception as exc:
            log.error("Decryption failed: %s", exc)
            return ciphertext

    def has_encryption(self) -> bool:
        return self._fernet is not None


class _Base64Fallback:
    """Minimal fallback when cryptography package is not installed."""

    def __init__(self, key: bytes):
        self._key = key

    def encrypt(self, data: bytes) -> bytes:
        return base64.urlsafe_b64encode(data)

    def decrypt(self, token: bytes) -> bytes:
        return base64.urlsafe_b64decode(token)


class AppWarmupManager:
    """Background prefetch manager to reduce first-page latency after login."""

    WARMUP_TIMEOUT = 30

    def __init__(self, client: Any):
        self._client = client
        self._done = threading.Event()
        self._results: Dict[str, Any] = {}
        self._errors: Dict[str, str] = {}

    def start(self) -> None:
        threading.Thread(target=self._run_warmup, name="AppWarmup", daemon=True).start()

    def wait(self, timeout: float = 5.0) -> bool:
        """Wait for warmup to complete."""
        return self._done.wait(timeout=timeout)

    def get_result(self, key: str) -> Optional[Any]:
        return self._results.get(key)

    @property
    def errors(self) -> Dict[str, str]:
        return dict(self._errors)

    def _run_warmup(self) -> None:
        tasks = [
            ("funds", getattr(self._client, "get_funds", None)),
            ("positions", getattr(self._client, "get_positions", None)),
            ("orders", getattr(self._client, "get_order_list", None)),
        ]
        callable_tasks = [(k, fn) for k, fn in tasks if callable(fn)]
        if not callable_tasks:
            self._done.set()
            return

        with ThreadPoolExecutor(max_workers=min(3, len(callable_tasks))) as pool:
            futures = {pool.submit(fn): key for key, fn in callable_tasks}
            try:
                for future in as_completed(futures, timeout=self.WARMUP_TIMEOUT):
                    key = futures[future]
                    try:
                        self._results[key] = future.result()
                    except Exception as exc:  # pragma: no cover
                        self._errors[key] = str(exc)
                        log.warning("Warmup %s failed: %s", key, exc)
            except Exception as exc:  # pragma: no cover
                log.warning("Warmup timeout/error: %s", exc)
        self._done.set()
        log.info("App warmup complete. Results: %s", list(self._results.keys()))
