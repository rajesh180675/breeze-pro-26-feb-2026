"""Compatibility shim for the migrated option-chain page module."""

from app.application.option_chain import page as _impl
from app.application.option_chain.page import *  # noqa: F401,F403

import sys as _sys

_sys.modules[__name__] = _impl
