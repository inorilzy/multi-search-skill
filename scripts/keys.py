"""Load API keys from ~/.search-keys.json + environment variables."""
import json
import os
import random
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


def load_keys() -> dict:
    """Load API keys from ~/.search-keys.json or environment variables."""
    keys_file = Path.home() / ".search-keys.json"
    keys: dict = {}
    if keys_file.exists():
        try:
            # utf-8-sig tolerates BOM (PowerShell 5.1 writes BOM by default)
            keys = json.loads(keys_file.read_text(encoding="utf-8-sig"))
        except Exception:
            pass
    for env_name, key_name in [
        ("BRAVE_SEARCH_API_KEY", "brave"),
        ("BRAVE_API_KEY", "brave"),
        ("TAVILY_API_KEY", "tavily"),
        ("EXA_API_KEY", "exa"),
        ("GITHUB_TOKEN", "github"),
        ("GH_TOKEN", "github"),
        ("FIRECRAWL_API_KEY", "firecrawl"),
        ("SERPAPI_API_KEY", "serpapi"),
        ("SERPAPI_KEY", "serpapi"),
        ("JINA_API_KEY", "jina"),
        ("TWITTER_COOKIES_PATH", "twitter_cookies"),
    ]:
        val = os.getenv(env_name)
        if val:
            keys[key_name] = val
    return keys
