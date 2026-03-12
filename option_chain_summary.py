"""Compatibility shim for the migrated option-chain summary module."""

from app.domain.option_chain import summary as _impl
from app.domain.option_chain.summary import *  # noqa: F401,F403

import sys as _sys

_sys.modules[__name__] = _impl
