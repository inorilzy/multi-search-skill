"""Brave Search API."""
import gzip
import json
import urllib.parse
import urllib.request

from ...support.http import urlopen_retry
from ...support.secrets import scrub_secrets


def search_brave(
    query: str,
    api_key: str,
    count: int = 10,
    timeout: float = 15,
    search_depth: str = "normal",
) -> list:
    """Call Brave Search API.
    Uses extra_snippets=true: returns up to 5 additional excerpts per result (free, no extra cost).
    """
    depth = (search_depth or "normal").lower()
    extra_snippets = "false" if depth == "fast" else "true"
    url = (
        "https://api.search.brave.com/res/v1/web/search?"
        + urllib.parse.urlencode({"q": query, "count": count, "extra_snippets": extra_snippets})
    )
    req = urllib.request.Request(
        url,
        headers={
            "X-Subscription-Token": api_key,
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        },
    )
    try:
        with urlopen_retry(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            data = json.loads(raw)
    except Exception as e:
        return [{"source": "brave", "error": scrub_secrets(e, api_key)}]

    results = []
    for item in data.get("web", {}).get("results", []):
        desc = item.get("description", "")
        extras = item.get("extra_snippets") or []
        if extras:
            extra_text = " · ".join(s for s in extras if s and s not in desc)
            if extra_text:
                desc = f"{desc} · {extra_text}" if desc else extra_text
        results.append(
            {
                "source": "brave",
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": desc,
                "search_depth": depth,
                "extra_snippets": extra_snippets == "true",
            }
        )
    return results
