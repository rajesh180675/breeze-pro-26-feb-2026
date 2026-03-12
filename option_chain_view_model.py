"""Compatibility shim for the migrated option-chain view-model module."""

from app.application.option_chain import view_model as _impl
from app.application.option_chain.view_model import *  # noqa: F401,F403

import sys as _sys

_sys.modules[__name__] = _impl
