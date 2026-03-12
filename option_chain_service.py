"""Compatibility shim for the migrated option-chain service module."""

from app.application.option_chain import service as _impl
from app.application.option_chain.service import *  # noqa: F401,F403

import sys as _sys

_sys.modules[__name__] = _impl
