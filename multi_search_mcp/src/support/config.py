"""Load non-secret defaults from SQLite or an explicitly supplied JSON file."""
import json
import os
from pathlib import Path
from typing import Any


CONFIG_ENV_VAR = "MULTI_SEARCH_CONFIG"
USER_CONFIG_PATH = Path.home() / ".multi-search" / "multi-search-config.json"
# Development fallback: the config file shipped next to the MCP source tree.
DEV_CONFIG_PATH = Path(__file__).resolve().parents[3] / "multi-search-config.json"


def resolve_config_path() -> Path:
    """Resolve the sole authoritative database, with an explicit isolation selector."""
    from .credential_store import config_db_path
    return config_db_path()


class ConfigError(ValueError):
    """Raised when a config file is present but cannot be used safely."""


def config_int(value: Any, key: str) -> int:
    """Keep historical int conversion while rejecting invalid explicit values."""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        # Do not echo the value or conversion error: defaults can contain secrets
        # pasted into the wrong field, before the key store has been loaded.
        raise ConfigError(f"{key} requires a number or integer string") from None


def load_config(path: str | None = None) -> dict:
    """Default to SQLite; legacy JSON is read only when the caller supplies ``path``."""
    if path is None:
        from .credential_store import ConfigDatabase, CredentialStoreError
        try:
            return ConfigDatabase(resolve_config_path()).read_settings()
        except CredentialStoreError as exc:
            raise ConfigError(str(exc)) from None
    config_path = Path(path).expanduser()
    if not config_path.exists():
        raise ConfigError("config file not found")
    try:
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except Exception:
        raise ConfigError("config file is not valid JSON") from None
    if not isinstance(data, dict):
        raise ConfigError(f"config file must contain a JSON object: {config_path}")
    return data


def config_bool(config: dict, key: str, default: bool = False) -> bool:
    if key not in config:
        return default
    value = config.get(key)
    if isinstance(value, bool):
        return value
    raise ConfigError(f"{key} requires a boolean value")


def config_str(config: dict, key: str) -> str:
    """Return an optional string config value ("" when absent). Never echoes the value."""
    if key not in config or config.get(key) is None:
        return ""
    value = config.get(key)
    if not isinstance(value, str):
        raise ConfigError(f"{key} requires a string value")
    return value


def config_list(config: dict, key: str) -> list[str]:
    if key not in config:
        return []
    value = config.get(key)
    if value is None:
        return []
    if isinstance(value, list):
        bad = [v for v in value if not isinstance(v, str)]
        if bad:
            raise ConfigError(f"{key} requires a list of strings")
        return [v for v in value if v]
    raise ConfigError(f"{key} requires a list of strings")
