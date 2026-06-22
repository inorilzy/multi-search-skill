"""Load API keys from ~/.search-keys.json + environment variables."""
import json
import os
import random
import threading
from pathlib import Path


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


_JINA_EXHAUSTED: set[str] = set()
_JINA_EXHAUSTED_LOCK = threading.Lock()


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


def get_active_jina_keys(value) -> list[str]:
    """Return non-exhausted Jina keys, shuffled.

    Filters keys already marked exhausted in the config *and* keys
    recorded in the runtime ``_JINA_EXHAUSTED`` set (session-scoped).
    """
    entries = normalize_jina_config(value)
    with _JINA_EXHAUSTED_LOCK:
        exhausted = set(_JINA_EXHAUSTED)
    active = [e["key"] for e in entries if not e["exhausted"] and e["key"] not in exhausted]
    random.shuffle(active)
    return active


def count_jina_keys(value) -> tuple[int, int]:
    """Return ``(active, total)`` Jina key counts."""
    entries = normalize_jina_config(value)
    total = len(entries)
    with _JINA_EXHAUSTED_LOCK:
        exhausted = set(_JINA_EXHAUSTED)
    active = sum(1 for e in entries if not e["exhausted"] and e["key"] not in exhausted)
    return active, total


def mark_jina_exhausted_runtime(key: str) -> None:
    """Record *key* as exhausted for the current process session."""
    if key:
        with _JINA_EXHAUSTED_LOCK:
            _JINA_EXHAUSTED.add(key)


def mark_jina_exhausted_persistent(key_to_mark: str) -> bool:
    """Mark a Jina key as exhausted in ``~/.search-keys.json``.

    Returns ``True`` when the file was updated.
    """
    with _JINA_EXHAUSTED_LOCK:
        keys_file = Path.home() / ".search-keys.json"
        if not keys_file.exists():
            return False
        try:
            data = json.loads(keys_file.read_text(encoding="utf-8-sig"))
        except Exception:
            return False
        if not isinstance(data, dict):
            return False

        jina_val = data.get("jina")
        if not jina_val:
            return False

        changed = False

        def _mark(val):
            nonlocal changed
            if isinstance(val, str):
                if val == key_to_mark:
                    changed = True
                    return {"key": val, "exhausted": True}
                return val
            if isinstance(val, dict):
                if val.get("key") == key_to_mark and not val.get("exhausted"):
                    val["exhausted"] = True
                    changed = True
                return val
            if isinstance(val, list):
                return [_mark(item) for item in val]
            return val

        data["jina"] = _mark(jina_val)

        if changed:
            try:
                keys_file.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                return True
            except Exception:
                return False
        return False


def load_keys() -> dict:
    """Load API keys from ~/.search-keys.json or environment variables."""
    keys_file = Path.home() / ".search-keys.json"
    keys: dict = {}
    if keys_file.exists():
        try:
            # utf-8-sig tolerates BOM (PowerShell 5.1 writes BOM by default)
            keys = json.loads(keys_file.read_text(encoding="utf-8-sig"))
            if not isinstance(keys, dict):
                keys = {}
        except Exception:
            pass
    for env_name, key_name in [
        ("BRAVE_SEARCH_API_KEY", "brave"),
        ("BRAVE_API_KEY", "brave"),
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
        ("DEEPSEEK_WEB_TOKEN", "deepseek_web_token"),
        ("DEEPSEEK_USER_TOKEN", "deepseek_web_token"),
        ("DEEPSEEK_WEB_COOKIE", "deepseek_web_cookie"),
        ("DEEPSEEK_WEB_AUTH_EXPORT", "deepseek_web_auth_export"),
    ]:
        val = os.getenv(env_name)
        if val:
            keys[key_name] = val
            if env_name == "TWITTER_COOKIES_PATH":
                keys["twitter"] = val
    deepseek_web = keys.get("deepseek_web") if isinstance(keys.get("deepseek_web"), dict) else {}
    if keys.get("deepseek_web_token") or keys.get("deepseek_web_cookie") or keys.get("deepseek_web_auth_export"):
        merged = dict(deepseek_web)
        if keys.get("deepseek_web_token"):
            merged["token"] = keys.get("deepseek_web_token")
        if keys.get("deepseek_web_cookie"):
            merged["cookie"] = keys.get("deepseek_web_cookie")
        if keys.get("deepseek_web_auth_export"):
            merged["auth_export"] = keys.get("deepseek_web_auth_export")
        keys["deepseek_web"] = merged
    return keys
