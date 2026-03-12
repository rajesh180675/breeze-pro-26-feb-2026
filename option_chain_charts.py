"""Compatibility shim for the migrated option-chain charts module."""

from app.application.option_chain import charts as _impl
from app.application.option_chain.charts import *  # noqa: F401,F403

import sys as _sys

_sys.modules[__name__] = _impl
