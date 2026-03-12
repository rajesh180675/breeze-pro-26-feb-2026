"""Compatibility shim for logging configuration."""

from app.core.logging import JsonFormatter, configure_logging

__all__ = ["JsonFormatter", "configure_logging"]
