"""Load API keys from ~/.search-keys.json + environment variables."""
import json
import os
import random
import sys
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


def pick_key(value) -> str:
    """Return a single key string. If `value` is a list, pick one at random.

    Tolerates None / "" / str / list[str]. Empty lists or falsy values -> "".
    """
    if not value:
        return ""
    if isinstance(value, list):
        choices = [v for v in value if v]
        return random.choice(choices) if choices else ""
    return str(value)


def key_pool(value) -> list[str]:
    """Return a shuffled list of candidate keys for fallback retry."""
    if not value:
        return []
    if isinstance(value, list):
        choices = [str(v) for v in value if v]
    else:
        choices = [str(value)]
    random.shuffle(choices)
    return choices


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


# Providers whose single secret may be stored in the Windows credential store.
# Resolution order for these providers: environment variable > credential store
# > ~/.search-keys.json. Environment variables always win so automation can
# override a UI-saved secret without editing it.
CREDENTIAL_STORE_PROVIDERS = ("tavily",)
TEST_ISOLATION_ENV = "MULTI_SEARCH_TEST_ISOLATION"
CREDENTIAL_NAMESPACE_ENV = "MULTI_SEARCH_CREDENTIAL_NAMESPACE"


def _credential_store_enabled(environ: Mapping[str, str]) -> bool:
    """Use the Windows store only on Windows, and never inside the test runner.

    Under test isolation the store stays off unless a disposable namespace is set
    explicitly, so the regression suite cannot read or write real user entries.
    """
    if sys.platform != "win32":
        return False
    if environ.get(TEST_ISOLATION_ENV) == "1" and not environ.get(CREDENTIAL_NAMESPACE_ENV):
        return False
    return True


def _default_credential_store(use_process_env: bool, environ: Mapping[str, str], injected):
    if injected is not None or not use_process_env or not _credential_store_enabled(environ):
        return injected
    from ..support.credential_store import default_store

    return default_store(environ)


def load_keys(
    keys_file: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    credential_store=None,
) -> dict:
    """Load API keys: environment > credential store > ~/.search-keys.json.

    ``credential_store`` may be injected (tests). When omitted, the Windows store
    is consulted only for the real process environment (see ``_credential_store_enabled``).
    """
    keys_file = Path(keys_file).expanduser() if keys_file else Path.home() / ".search-keys.json"
    use_process_env = environ is None
    environ = os.environ if environ is None else environ
    keys: dict = {}
    if keys_file.exists():
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
    store = _default_credential_store(use_process_env, environ, credential_store)
    if store is not None:
        from ..support.credential_store import CredentialStoreError

        env_providers = {key_name for env_name, key_name in KEY_ENV_PAIRS if environ.get(env_name)}
        for provider in CREDENTIAL_STORE_PROVIDERS:
            if provider in env_providers:
                # An environment variable overrides the store, so the store is not read.
                # A broken store therefore never blocks an env-driven run.
                continue
            try:
                value = store.get(provider)
            except CredentialStoreError as exc:
                # Explicit failure: a present-but-unreadable store must never be
                # silently bypassed in favor of the plaintext file.
                raise KeysError(f"credential store unavailable for {provider}: {exc}") from None
            if value:
                keys[provider] = value
    for env_name, key_name in KEY_ENV_PAIRS:
        val = environ.get(env_name)
        if val:
            keys[key_name] = val
            if env_name == "TWITTER_COOKIES_PATH":
                keys["twitter"] = val
    return keys


def key_sources(
    keys_file: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    credential_store=None,
) -> dict[str, dict]:
    """Report provenance (never values) of each credential-store provider's key."""
    from ..support.credential_store import CredentialStoreError

    keys_file = Path(keys_file).expanduser() if keys_file else Path.home() / ".search-keys.json"
    use_process_env = environ is None
    environ = os.environ if environ is None else environ
    file_keys: dict = {}
    if keys_file.exists():
        try:
            loaded = json.loads(keys_file.read_text(encoding="utf-8-sig"))
            file_keys = loaded if isinstance(loaded, dict) else {}
        except Exception:
            file_keys = {}
    store = _default_credential_store(use_process_env, environ, credential_store)
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
        if env_names:
            effective = "env"
        elif in_store:
            effective = "credential_store"
        elif file_keys.get(provider):
            effective = "file"
        else:
            effective = "none"
        report[provider] = {
            "effective_source": effective,
            "env_vars_set": env_names,
            "env_overrides_store": bool(env_names and in_store),
            "credential_store": store_state,
            "file_present": bool(file_keys.get(provider)),
            **({"credential_store_error": store_error} if store_error else {}),
        }
    return report
