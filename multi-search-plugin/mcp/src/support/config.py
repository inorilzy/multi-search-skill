"""Load and validate non-secret CLI defaults from JSON config files."""
import json
from pathlib import Path


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "multi-search-config.json"


class ConfigError(ValueError):
    """Raised when a config file is present but cannot be used safely."""


def load_config(path: str | None = None) -> dict:
    """Load non-secret search defaults.

    This intentionally does not replace ~/.search-keys.json. Keep API keys and
    cookies in the keys file; use this config file for route/count/timeout
    preferences that are safe to share.
    """
    explicit = path is not None
    config_path = Path(path).expanduser() if explicit else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        if explicit:
            raise ConfigError(f"config file not found: {config_path}")
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise ConfigError(f"config file is not valid JSON: {config_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"config file must contain a JSON object: {config_path}")
    return data


def config_bool(config: dict, key: str, default: bool = False) -> bool:
    if key not in config:
        return default
    value = config.get(key)
    if isinstance(value, bool):
        return value
    raise ConfigError(f"{key} requires a boolean value, got {value!r}")


def config_list(config: dict, key: str) -> list[str]:
    if key not in config:
        return []
    value = config.get(key)
    if value is None:
        return []
    if isinstance(value, list):
        bad = [v for v in value if not isinstance(v, str)]
        if bad:
            raise ConfigError(f"{key} requires a list of strings, got {value!r}")
        return [v for v in value if v]
    raise ConfigError(f"{key} requires a list of strings, got {value!r}")
