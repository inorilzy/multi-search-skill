"""Load API keys from authoritative SQLite, or an explicitly supplied keys file."""
import json
import os
from collections.abc import Mapping
from pathlib import Path


class KeysError(ValueError):
    """Raised when the keys file exists but cannot be parsed safely.

    Carries only the file path, never the file contents, so a malformed keys
    file cannot leak secrets into a user-visible error.
    """


KEY_ENV_PAIRS = (
    ("BRAVE_SEARCH_API_KEY", "brave"),
    ("BRAVE_API_KEY", "brave"),
    ("PARALLEL_API_KEY", "parallel"),
    ("BAIDU_QIANFAN_API_KEY", "baidu"),
    ("QIANFAN_API_KEY", "baidu"),
    ("APPBUILDER_API_KEY", "baidu"),
    ("TAVILY_API_KEY", "tavily"),
    ("EXA_API_KEY", "exa"),
    ("JINA_API_KEY", "jina"),
    ("JINA_KEY", "jina"),
    ("GITHUB_TOKEN", "github"),
    ("GH_TOKEN", "github"),
    ("FIRECRAWL_API_KEY", "firecrawl"),
    ("SERPAPI_API_KEY", "serpapi"),
    ("SERPAPI_KEY", "serpapi"),
    ("TWITTER_COOKIES_PATH", "twitter_cookies"),
)

KEY_ENV_NAMES = [env_name for env_name, _key_name in KEY_ENV_PAIRS]


def normalize_jina_config(value) -> list[dict]:
    """Normalize Jina config to list of {key, exhausted}.

    Supports: str, list[str], list[{key, exhausted}], single {key, exhausted}.
    """
    if not value:
        return []
    if isinstance(value, str):
        return [{"key": value, "exhausted": False}] if value else []
    if isinstance(value, dict):
        k = value.get("key", "")
        return [{"key": k, "exhausted": bool(value.get("exhausted"))}] if k else []
    if isinstance(value, list):
        out: list[dict] = []
        for item in value:
            if isinstance(item, str):
                if item:
                    out.append({"key": item, "exhausted": False})
            elif isinstance(item, dict):
                k = item.get("key", "")
                if k:
                    out.append({"key": k, "exhausted": bool(item.get("exhausted"))})
        return out
    return []


def jina_config_keys(value) -> list[str]:
    """Return configured Jina keys that are not statically disabled.

    Honors the config-level ``exhausted: true`` flag (a user/operator opt-out),
    but performs no shuffling and no runtime exhaustion bookkeeping. Live key
    health (cooldown / quota / invalid) is owned by ``SQLiteKeyManager`` so that
    Jina shares the same state-aware LRU rotation as the other providers.
    """
    return [e["key"] for e in normalize_jina_config(value) if not e["exhausted"]]


def count_jina_keys(value) -> tuple[int, int]:
    """Return ``(config_active, total)`` Jina key counts.

    Reflects only static config state. Runtime health lives in the key-state DB.
    """
    entries = normalize_jina_config(value)
    total = len(entries)
    active = sum(1 for e in entries if not e["exhausted"])
    return active, total


# JSON-valued key providers stored in shared SQLite; Twitter is a settings path.
# Legacy sources participate only when explicitly supplied/imported.
CREDENTIAL_STORE_PROVIDERS = (
    "baidu", "brave", "parallel", "tavily", "exa", "firecrawl", "serpapi", "github", "jina",
)
def load_keys(
    keys_file: str | Path | None = None,  # legacy migration only; not a runtime override
    environ: Mapping[str, str] | None = None,
    credential_store=None,
    *,
    twitter_cookies_path: str | None = None,
) -> dict:
    """Load only SQLite by default; ``environ`` never supplies provider overrides.

    An explicitly supplied keys file is a separate opt-in compatibility input.
    Tests may inject a store. Twitter's non-secret settings path is never opened here.
    """
    # Only an explicitly supplied file is read; process keys/env/legacy manager
    # are never implicit overrides of desktop-saved configuration.
    keys_file = Path(keys_file).expanduser() if keys_file else None
    keys: dict = {}
    if keys_file is not None and keys_file.exists():
        try:
            # utf-8-sig tolerates BOM (PowerShell 5.1 writes BOM by default)
            keys = json.loads(keys_file.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            # Fail loudly instead of silently returning zero keys: a corrupt
            # keys file otherwise surfaces as every provider "missing key",
            # hiding the real cause. Reference only the path, never the
            # (secret-bearing) file contents or parser detail.
            raise KeysError(f"keys file is not valid JSON: {keys_file}") from None
        if not isinstance(keys, dict):
            keys = {}
    from ..support.credential_store import CredentialStoreError, default_store
    store = credential_store if credential_store is not None else (None if keys_file is not None else default_store())
    if store is not None:
        for provider in CREDENTIAL_STORE_PROVIDERS:
            try:
                value = store.get(provider)
            except CredentialStoreError as exc:
                raise KeysError(f"configuration credential unavailable for {provider}: {exc}") from None
            if value:
                keys[provider] = value
    if twitter_cookies_path:
        # Canonical credential name; ``twitter`` remains as a compatibility
        # alias for older adapters and keys files.
        keys["twitter_cookies_path"] = twitter_cookies_path
        keys["twitter"] = twitter_cookies_path
    return keys


def _file_key_count(value) -> int:
    if isinstance(value, list):
        return sum(1 for item in value if item)
    return 1 if value else 0


def key_sources(
    keys_file: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    credential_store=None,
) -> dict[str, dict]:
    """Report provenance (never values) of each credential-store provider's key."""
    from ..support.credential_store import CredentialStoreError

    keys_file = Path(keys_file).expanduser() if keys_file else None
    environ = os.environ if environ is None else environ
    file_keys: dict = {}
    if keys_file is not None and keys_file.exists():
        try:
            loaded = json.loads(keys_file.read_text(encoding="utf-8-sig"))
            file_keys = loaded if isinstance(loaded, dict) else {}
        except Exception:
            file_keys = {}
    from ..support.credential_store import default_store
    store = credential_store if credential_store is not None else default_store()
    report: dict[str, dict] = {}
    for provider in CREDENTIAL_STORE_PROVIDERS:
        env_names = [name for name, key_name in KEY_ENV_PAIRS if key_name == provider and environ.get(name)]
        store_state = "disabled"
        store_error = None
        if store is not None:
            try:
                store_state = "present" if store.get(provider) else "absent"
            except CredentialStoreError as exc:
                store_state = "unavailable"
                store_error = str(exc)
        in_store = store_state == "present"
        effective = "sqlite" if in_store else "none"
        report[provider] = {
            "effective_source": effective,
            "env_vars_set": env_names,
            "env_overrides_store": False,
            "legacy_not_imported": bool((env_names or file_keys.get(provider)) and not in_store),
            "credential_store": store_state,
            "file_present": bool(file_keys.get(provider)),
            # Count only: the file list is kept on disk and does not rotate with a store key.
            "file_key_count": _file_key_count(file_keys.get(provider)),
            **({"credential_store_error": store_error} if store_error else {}),
        }
    return report
