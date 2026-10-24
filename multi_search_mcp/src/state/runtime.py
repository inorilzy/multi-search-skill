"""Runtime configuration and key loading shared by service entry points.

Both helpers are deliberately module-level functions so tests and callers can
inject a configuration or key loader without touching the service layer.
"""
from __future__ import annotations

from ..support.config import ConfigError, config_str, load_config
from .keys import load_keys


def load_config_safe(path: str | None) -> dict:
    """Load config, translating its parse error into the service error type."""
    try:
        return load_config(path)
    except ConfigError as exc:
        raise ValueError(str(exc)) from exc


def load_runtime_keys(config: dict | None = None) -> dict:
    """Load keys, adding the config's non-secret Twitter cookie path reference."""
    reference = config_str(config or {}, "twitter_cookies_path") or None
    if reference is None:
        # Keep the original call shape when config carries no Twitter reference.
        return load_keys()
    return load_keys(twitter_cookies_path=reference)
