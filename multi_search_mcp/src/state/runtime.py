"""Runtime configuration and key loading shared by service entry points.

This is the single runtime-assembly seam: every pipeline (search, fetch,
scrape, snapshot capture, doctor) loads configuration and credentials through
these module-level functions, so tests and callers can inject a configuration
or key loader in one place without touching the service layer.
"""
from __future__ import annotations

from ..support.config import ConfigError, config_str, load_config
from .keys import KeyLoad, KeysError, load_keys

TWITTER_COOKIE_MODES = ("file", "managed")


def load_config_safe(path: str | None) -> dict:
    """Load config, translating its parse error into the service error type."""
    try:
        return load_config(path)
    except ConfigError as exc:
        raise ValueError(str(exc)) from exc


def twitter_cookies_mode(config: dict | None) -> str:
    """Return ``file`` (default) or ``managed``; any other value fails closed."""
    config = config or {}
    if "twitter_cookies_mode" not in config:
        return "file"
    mode = config.get("twitter_cookies_mode")
    if not isinstance(mode, str) or mode not in TWITTER_COOKIE_MODES:
        # A credential-routing error, reported by doctor as ``keys_error``;
        # the value itself is never echoed.
        raise KeysError("unsupported Twitter cookies mode")
    return mode


def load_runtime_key_context(config: dict | None = None) -> KeyLoad:
    """Load keys plus per-provider credential errors, with the config's Twitter reference.

    ``twitter_cookies_mode = "managed"`` replaces every file/env cookie reference
    with a non-secret :class:`ManagedTwitterCookies` handle. The DPAPI entry is
    decrypted only inside an actual X call and never falls back to a file.
    """
    mode = twitter_cookies_mode(config)
    reference = None if mode == "managed" else (config_str(config or {}, "twitter_cookies_path") or None)
    if reference is None:
        # Keep the original call shape when config carries no Twitter reference.
        loaded = load_keys()
    else:
        loaded = load_keys(twitter_cookies_path=reference)
    # `load_keys` is the long-standing seam callers patch; plain dicts (e.g. a
    # test double) simply carry no per-provider errors.
    keys = dict(loaded)
    errors = dict(getattr(loaded, "errors", {}))
    if mode == "managed":
        from ..providers.xkit import ManagedTwitterCookies

        managed = ManagedTwitterCookies()
        for name in ("twitter", "twitter_cookies", "twitter_cookies_path"):
            keys[name] = managed
    return KeyLoad(keys=keys, errors=errors)


def load_runtime_keys(config: dict | None = None) -> dict:
    """Load keys, adding the config's non-secret Twitter cookie path reference.

    Providers whose store entry is unreadable are simply absent; search paths use
    :func:`load_runtime_key_context` to surface their explicit error.
    """
    return load_runtime_key_context(config).keys
