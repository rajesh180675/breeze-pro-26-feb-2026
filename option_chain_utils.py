"""Compatibility shim for the migrated option-chain utils module."""

from app.domain.option_chain import utils as _impl
from app.domain.option_chain.utils import *  # noqa: F401,F403

import sys as _sys

_sys.modules[__name__] = _impl
