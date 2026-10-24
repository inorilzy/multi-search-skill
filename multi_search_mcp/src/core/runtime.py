"""Runtime assembly: configuration, credentials and state-store construction.

This module is the single seam shared by every core pipeline. Tests inject
configuration, keys and state by patching the names here; pipelines import the
module and call its functions rather than binding them locally, so one patch
covers the whole request path.
"""
from __future__ import annotations

from ..state.content_store import ContentStore
from ..state.key_state import BasicKeyManager, SQLiteKeyManager
from ..state.keys import load_keys
from ..state.state_store import StateStore
from ..support.config import ConfigError, config_str, load_config, resolve_config_path


def load_config_safe(path: str | None) -> dict:
    """Load configuration, translating storage failures into ValueError."""
    try:
        return load_config(path)
    except ConfigError as exc:
        raise ValueError(str(exc)) from exc


def load_runtime_keys(config: dict | None = None) -> dict:
    """Load keys, adding the config's non-secret Twitter cookie path reference."""
    mode = config_str(config or {}, "twitter_cookies_mode") if "twitter_cookies_mode" in (config or {}) else "file"
    if mode not in {"file", "managed"}:
        from ..state.keys import KeysError
        raise KeysError("unsupported Twitter cookies mode")
    if mode == "managed":
        from ..providers.xkit import ManagedTwitterCookies
        keys = load_keys()
        keys["twitter_cookies_path"] = ManagedTwitterCookies()
        return keys
    reference = config_str(config or {}, "twitter_cookies_path") or None
    if reference is None:
        # Keep the original call shape when config carries no Twitter reference.
        return load_keys()
    return load_keys(twitter_cookies_path=reference)


def new_state_store() -> StateStore:
    return StateStore()


def key_manager_for(store):
    return SQLiteKeyManager(store) if store else BasicKeyManager()


def new_content_store(store, *, ttl_seconds=None):
    if ttl_seconds is None:
        return ContentStore(store)
    return ContentStore(store, ttl_seconds=ttl_seconds)
