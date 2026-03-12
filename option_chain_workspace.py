"""Compatibility shim for the migrated option-chain workspace module."""

from app.domain.option_chain import workspace as _impl
from app.domain.option_chain.workspace import *  # noqa: F401,F403

import sys as _sys

_sys.modules[__name__] = _impl
