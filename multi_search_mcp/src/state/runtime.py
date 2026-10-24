"""Runtime configuration and key loading shared by service entry points.

Both helpers are deliberately module-level functions so tests and callers can
inject a configuration or key loader without touching the service layer.
"""
from __future__ import annotations

from ..support.config import ConfigError, config_str, load_config
from .keys import KeyLoad, load_keys


def load_config_safe(path: str | None) -> dict:
    """Load config, translating its parse error into the service error type."""
    try:
        return load_config(path)
    except ConfigError as exc:
        raise ValueError(str(exc)) from exc


def load_runtime_key_context(config: dict | None = None) -> KeyLoad:
    """Load keys plus per-provider credential errors, with the config's Twitter reference."""
    reference = config_str(config or {}, "twitter_cookies_path") or None
    if reference is None:
        # Keep the original call shape when config carries no Twitter reference.
        loaded = load_keys()
    else:
        loaded = load_keys(twitter_cookies_path=reference)
    # `load_keys` is the long-standing seam callers patch; plain dicts (e.g. a
    # test double) simply carry no per-provider errors.
    return KeyLoad(keys=dict(loaded), errors=dict(getattr(loaded, "errors", {})))


def load_runtime_keys(config: dict | None = None) -> dict:
    """Load keys, adding the config's non-secret Twitter cookie path reference.

    Providers whose store entry is unreadable are simply absent; search paths use
    :func:`load_runtime_key_context` to surface their explicit error.
    """
    return load_runtime_key_context(config).keys
