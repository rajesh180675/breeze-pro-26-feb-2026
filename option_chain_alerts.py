"""Compatibility shim for the migrated option-chain alerts module."""

from app.domain.option_chain import alerts as _impl
from app.domain.option_chain.alerts import *  # noqa: F401,F403

import sys as _sys

_sys.modules[__name__] = _impl
