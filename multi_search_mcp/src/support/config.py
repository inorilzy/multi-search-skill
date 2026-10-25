"""Load and validate non-secret CLI defaults from JSON config files."""
import json
import os
from pathlib import Path
from typing import Any


CONFIG_ENV_VAR = "MULTI_SEARCH_CONFIG"
USER_CONFIG_PATH = Path.home() / ".multi-search" / "multi-search-config.json"
# Repo root when running from a source checkout. In an installed package this points at
# site-packages; the dev fallback below is only enabled for an actual source checkout.
_SOURCE_ROOT = Path(__file__).resolve().parents[3]


def _is_source_checkout(root: Path) -> bool:
    """True only for the project's own source tree, never for an installed package.

    A wheel installs ``multi_search_mcp/src/support/config.py`` under ``site-packages``;
    that directory has the package but not the project manifest. Requiring both keeps an
    installed CLI from resolving a config next to ``site-packages``.
    """
    return (root / "pyproject.toml").is_file() and (root / "multi_search_mcp" / "cli.py").is_file()


IS_SOURCE_CHECKOUT = _is_source_checkout(_SOURCE_ROOT)
# Never computed for an installed package: there is no dev fallback to point at.
DEV_CONFIG_PATH = _SOURCE_ROOT / "multi-search-config.json" if IS_SOURCE_CHECKOUT else None


def dev_config_path() -> Path | None:
    """The development fallback location, or ``None`` for an installed package."""
    return DEV_CONFIG_PATH if IS_SOURCE_CHECKOUT else None


CONFIG_DB_ENV = "MULTI_SEARCH_CONFIG_DB"


def config_db_path(environ=None) -> Path:
    """Locate the desktop-owned ``config.sqlite`` (settings + DPAPI credentials).

    ``MULTI_SEARCH_CONFIG_DB`` selects an isolated database. It is a literal path
    (desktop ``PathBuf`` semantics): ``~`` and environment variables are not
    expanded. Otherwise the same home order as the desktop process applies.
    """
    env = os.environ if environ is None else environ
    selected = env.get(CONFIG_DB_ENV)
    if selected:
        return Path(selected)
    home = env.get("USERPROFILE") or env.get("HOME")
    return (Path(home) if home else Path.home()) / ".multi-search" / "config.sqlite"


def _sqlite_settings_state() -> tuple[Path, str]:
    """Return the shared config database path and whether it holds settings.

    ``present``: a settings row exists (the desktop saved settings);
    ``absent``: no database or no settings row; ``unreadable``: the database
    exists but cannot be read safely. Never raises.
    """
    path = config_db_path()
    if not path.exists():
        return path, "absent"
    from .credential_store import ConfigDatabase, CredentialStoreError

    try:
        with ConfigDatabase(path).connect() as conn:
            row = conn.execute("SELECT 1 FROM settings WHERE id=1").fetchone() if conn else None
    except CredentialStoreError:
        return path, "unreadable"
    return path, "present" if row else "absent"


def resolve_config_path_source() -> tuple[Path, str]:
    """Resolve the config location and where it came from: ``env``, ``sqlite``,
    ``user``, ``dev_fallback``, or ``defaults``.

    Order of precedence:
    1. ``MULTI_SEARCH_CONFIG`` environment variable (an explicit JSON file).
    2. The shared desktop database (``MULTI_SEARCH_CONFIG_DB`` or
       ``~/.multi-search/config.sqlite``) once it holds saved settings. An
       unreadable database is still selected so loading fails closed instead
       of silently falling back to an older JSON file.
    3. User-level JSON config under ``~/.multi-search``.
    4. Development fallback next to the MCP source tree, only in a source checkout.
    An installed package never reads next to ``site-packages``; it reports the user path
    instead so ``doctor`` and the desktop show the same location the CLI would create.
    """
    env_value = os.environ.get(CONFIG_ENV_VAR)
    if env_value:
        return Path(env_value).expanduser(), "env"
    database, state = _sqlite_settings_state()
    if state != "absent":
        return database, "sqlite"
    if USER_CONFIG_PATH.exists():
        return USER_CONFIG_PATH, "user"
    dev = dev_config_path()
    if dev is not None:
        return dev, "dev_fallback" if dev.exists() else "defaults"
    return USER_CONFIG_PATH, "defaults"


def resolve_config_path() -> Path:
    """The config path the CLI reads (or would create) now. See
    :func:`resolve_config_path_source` for the full precedence and source label."""
    return resolve_config_path_source()[0]


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
    """Load non-secret search defaults.

    An explicit ``path`` (or ``MULTI_SEARCH_CONFIG``) is a JSON file. Otherwise the
    desktop's ``config.sqlite`` settings are authoritative once saved, then the
    user/dev JSON files. API keys and cookies never live here.
    """
    if path is None:
        resolved, source = resolve_config_path_source()
        if source == "sqlite":
            from .credential_store import ConfigDatabase, CredentialStoreError
            try:
                return ConfigDatabase(resolved).read_settings()
            except CredentialStoreError as exc:
                raise ConfigError(f"config database is unreadable: {exc}") from None
        explicit = source == "env"
        config_path = resolved
    else:
        explicit = True
        config_path = Path(path).expanduser()
    if not config_path.exists():
        if explicit:
            raise ConfigError(f"config file not found: {config_path}")
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except Exception:
        # Do not echo parser detail: a malformed file can contain a pasted secret.
        raise ConfigError(f"config file is not valid JSON: {config_path}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"config file must contain a JSON object: {config_path}")
    return data


def resolve_value(request_value: Any, config: dict, key: str, default: Any) -> Any:
    """Resolve an explicit request value, then the config value, then the default."""
    if request_value is not None:
        return request_value
    if key in config and config.get(key) is not None:
        return config.get(key)
    return default


def resolve_int(request_value: Any, config: dict, key: str, default: int) -> int:
    return config_int(resolve_value(request_value, config, key, default), key)


def resolve_nonnegative(request_value: Any, config: dict, key: str, default: int) -> int:
    return max(0, resolve_int(request_value, config, key, default))


def config_bool(config: dict, key: str, default: bool = False) -> bool:
    if key not in config:
        return default
    value = config.get(key)
    if isinstance(value, bool):
        return value
    raise ConfigError(f"{key} requires a boolean value, got {value!r}")


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
            raise ConfigError(f"{key} requires a list of strings, got {value!r}")
        return [v for v in value if v]
    raise ConfigError(f"{key} requires a list of strings, got {value!r}")
