"""Stack Overflow question search via the Stack Exchange API."""
import gzip
import html
import json
import urllib.parse
import urllib.request
import zlib

from ...support.http import urlopen_retry


def _content_encoding(resp) -> str:
    headers = getattr(resp, "headers", {})
    value = headers.get("Content-Encoding")
    if value is None:
        value = headers.get("content-encoding")
    return str(value or "").strip().lower()


def _looks_like_json(body: bytes) -> bool:
    return body.lstrip().startswith((b"{", b"["))


def _decode_response(resp) -> bytes:
    body = resp.read()
    encoding = _content_encoding(resp) or "gzip"

    # A proxy may have already decompressed the body, and early API errors are
    # allowed to bypass compression. Keep those JSON bodies intact.
    if _looks_like_json(body):
        return body
    if encoding == "gzip":
        return gzip.decompress(body)
    if encoding == "deflate":
        return zlib.decompress(body)
    if encoding == "identity":
        return body
    raise ValueError(f"unsupported Content-Encoding: {encoding}")


def search_stackoverflow(query: str, count: int = 10, timeout: float = 20) -> list:
    """Search Stack Overflow questions by relevance."""
    params = {
        "order": "desc",
        "sort": "relevance",
        "q": query,
        "site": "stackoverflow",
        "pagesize": max(1, count),
    }
    url = "https://api.stackexchange.com/2.3/search/advanced?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": "multi-search/1.0",
        },
    )
    try:
        with urlopen_retry(req, timeout=timeout) as resp:
            data = json.loads(_decode_response(resp))
            if not isinstance(data, dict):
                raise ValueError("Stack Exchange response must be a JSON object")
    except Exception as e:
        return [{"source": "stackoverflow", "error": str(e)[:300]}]

    if data.get("error_message"):
        return [{"source": "stackoverflow", "error": str(data["error_message"])[:300]}]

    items = []
    for result in data.get("items") or []:
        if not isinstance(result, dict):
            continue
        title = html.unescape(result.get("title") or "")
        url_value = result.get("link") or ""
        tags = result.get("tags") or []
        stats = [
            f"score {result.get('score', 0)}",
            f"{result.get('answer_count', 0)} answers",
            f"{result.get('view_count', 0)} views",
        ]
        if result.get("is_answered"):
            stats.append("answered")
        if tags:
            stats.append("tags: " + ", ".join(str(tag) for tag in tags[:5]))
        items.append({
            "source": "stackoverflow",
            "title": title or url_value or "(no title)",
            "url": url_value,
            "description": " · ".join(stats),
            "content_kind": "metadata",
        })
    return items
