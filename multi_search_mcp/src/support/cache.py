"""Small JSON file cache for search/scrape diagnostics and future reuse."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .dedup import _norm_url


DEFAULT_CACHE_DIR = Path(".cache") / "multi-search"


def cache_key(namespace: str, payload: dict[str, Any]) -> str:
    serial = json.dumps({"namespace": namespace, "payload": payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serial.encode("utf-8")).hexdigest()


class JsonCache:
    def __init__(self, cache_dir: str | Path = DEFAULT_CACHE_DIR, ttl_seconds: int = 86400, enabled: bool = False):
        self.cache_dir = Path(cache_dir)
        self.ttl_seconds = ttl_seconds
        self.enabled = enabled

    def path_for(self, namespace: str, key: str) -> Path:
        return self.cache_dir / namespace / f"{key}.json"

    def get(self, namespace: str, key: str):
        if not self.enabled:
            return None
        path = self.path_for(namespace, key)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        created = float(data.get("created", 0) or 0)
        if self.ttl_seconds >= 0 and time.time() - created > self.ttl_seconds:
            return None
        return data.get("value")

    def set(self, namespace: str, key: str, value) -> bool:
        if not self.enabled:
            return False
        path = self.path_for(namespace, key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"created": time.time(), "value": value}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except Exception:
            return False


def make_scrape_cache_key(url: str, backend_order: list[str] | tuple[str, ...], options: dict[str, Any] | None = None) -> str:
    return cache_key("scrape", {
        "url": _norm_url(url),
        "backend_order": list(backend_order),
        "options": options or {},
    })


def make_search_cache_key(query: str, source: str, count: int, route: str, expand: bool = False) -> str:
    return cache_key("search", {
        "query": query,
        "source": source,
        "count": count,
        "route": route,
        "expand": expand,
    })
