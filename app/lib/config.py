"""Compatibility shim for runtime settings."""

from app.core.settings import Settings, SettingsValidationError, get_settings, validate_settings

__all__ = ["Settings", "SettingsValidationError", "get_settings", "validate_settings"]
