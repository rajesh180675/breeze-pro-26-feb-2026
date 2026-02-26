import sys
import types

fake_st = types.ModuleType("streamlit")
fake_st.secrets = {}
fake_st.session_state = {}
sys.modules.setdefault("streamlit", fake_st)

import base64
import hashlib
import hmac
import struct

import pytest

from session_manager import generate_totp


def _totp_at(secret: str, ts: int, digits: int = 6, period: int = 30):
    sec = secret.upper().replace(" ", "").replace("-", "")
    sec += "=" * ((8 - len(sec) % 8) % 8)
    key = base64.b32decode(sec, casefold=True)
    counter = ts // period
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    val = struct.unpack(">I", digest[offset:offset+4])[0] & 0x7FFFFFFF
    return str(val % (10**digits)).zfill(digits)


def test_generate_totp_matches_reference(monkeypatch):
    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setattr("session_manager._time.time", lambda: 1700000000)
    got = generate_totp(secret)
    exp = _totp_at(secret, 1700000000)
    assert got == exp


def test_totp_changes_every_30_seconds(monkeypatch):
    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setattr("session_manager._time.time", lambda: 1700000000)
    a = generate_totp(secret)
    monkeypatch.setattr("session_manager._time.time", lambda: 1700000031)
    b = generate_totp(secret)
    assert a != b


def test_generate_totp_invalid_secret_raises():
    with pytest.raises(ValueError):
        generate_totp("not@@base32")
