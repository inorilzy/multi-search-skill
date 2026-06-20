"""Zhihu OpenAPI search."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from ..http import urlopen_retry
from ..secrets import scrub_secrets


DEFAULT_BASE_URL = "https://developer.zhihu.com"
DEFAULT_SEARCH_PATH = "/api/v1/content/zhihu_search"


def _endpoint() -> str:
    explicit = os.getenv("ZHIHU_ZHIHU_SEARCH_URL", "").strip()
    if explicit:
        return explicit
    base_url = os.getenv("ZHIHU_OPENAPI_BASE_URL", DEFAULT_BASE_URL).strip()
    return f"{base_url.rstrip('/')}{DEFAULT_SEARCH_PATH}"


def search_zhihu(query: str, access_secret: str, count: int = 10, timeout: float = 5) -> list:
    """Search Zhihu via the official Zhihu OpenAPI zhihu_search endpoint."""
    count = max(1, min(int(count or 10), 10))
    params = urllib.parse.urlencode({"Query": query, "Count": str(count)})
    req = urllib.request.Request(
        f"{_endpoint()}?{params}",
        headers={
            "Authorization": f"Bearer {access_secret}",
            "X-Request-Timestamp": str(int(time.time())),
            "Content-Type": "application/json",
        },
        method="GET",
    )

    try:
        with urlopen_retry(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        detail = body or str(exc)
        return [{"source": "zhihu", "error": f"HTTP {exc.code}: {scrub_secrets(detail, access_secret)}"}]
    except Exception as exc:
        return [{"source": "zhihu", "error": scrub_secrets(exc, access_secret)}]

    code = data.get("Code")
    if code not in (0, "0", None):
        message = data.get("Message") or "request failed"
        return [{"source": "zhihu", "error": f"Code {code}: {scrub_secrets(message, access_secret)}"}]

    data_field = data.get("Data") if isinstance(data.get("Data"), dict) else {}
    items = data_field.get("Items") if isinstance(data_field.get("Items"), list) else []
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        description = item.get("ContentText") or ""
        result = {
            "source": "zhihu",
            "title": item.get("Title", ""),
            "url": item.get("Url", ""),
            "description": description[:300],
            "author_name": item.get("AuthorName", ""),
            "vote_up_count": item.get("VoteUpCount", 0),
            "comment_count": item.get("CommentCount", 0),
            "edit_time": item.get("EditTime", 0),
            "content_type": item.get("ContentType", ""),
            "content_id": item.get("ContentID", ""),
            "authority_level": item.get("AuthorityLevel", ""),
            "ranking_score": item.get("RankingScore", 0),
        }
        results.append(result)
    return results
