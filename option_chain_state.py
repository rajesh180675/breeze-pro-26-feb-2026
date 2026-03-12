"""Compatibility shim for the migrated option-chain state module."""

from app.application.option_chain import state as _impl
from app.application.option_chain.state import *  # noqa: F401,F403

import sys as _sys

_sys.modules[__name__] = _impl
