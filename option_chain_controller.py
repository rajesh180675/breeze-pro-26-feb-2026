"""Compatibility shim for the migrated option-chain controller module."""

from app.application.option_chain import controller as _impl
from app.application.option_chain.controller import *  # noqa: F401,F403

import sys as _sys

_sys.modules[__name__] = _impl
