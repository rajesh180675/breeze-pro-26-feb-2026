"""Compatibility shim for the migrated option-chain metrics module."""

from app.domain.option_chain import metrics as _impl
from app.domain.option_chain.metrics import *  # noqa: F401,F403

import sys as _sys

_sys.modules[__name__] = _impl
