"""Load API keys from ~/.search-keys.json + environment variables."""
import json
import os
import random
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
    ("ZHIHU_ACCESS_SECRET", "zhihu"),
    ("YOUTUBE_API_KEY", "youtube"),
    ("BILIBILI_COOKIE", "bilibili"),
    ("TWITTER_COOKIES_PATH", "twitter_cookies"),
    ("REDDIT_COOKIE_EXPORT", "reddit_cookie_export"),
    ("REDDIT_BROWSER_PROFILE", "reddit_browser_profile"),
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


def load_keys(
    keys_file: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict:
    """Load API keys from ~/.search-keys.json or environment variables."""
    keys_file = Path(keys_file).expanduser() if keys_file else Path.home() / ".search-keys.json"
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
    for env_name, key_name in KEY_ENV_PAIRS:
        val = environ.get(env_name)
        if val:
            keys[key_name] = val
            if env_name == "TWITTER_COOKIES_PATH":
                keys["twitter"] = val
    reddit_browser = keys.get("reddit_browser") if isinstance(keys.get("reddit_browser"), dict) else {}
    if keys.get("reddit_cookie_export") or keys.get("reddit_browser_profile"):
        merged = dict(reddit_browser)
        if keys.get("reddit_cookie_export"):
            merged["cookie_export"] = keys.get("reddit_cookie_export")
        if keys.get("reddit_browser_profile"):
            merged["profile"] = keys.get("reddit_browser_profile")
        keys["reddit_browser"] = merged
    return keys
