"""Baidu Qianfan AI Search adapters."""
from __future__ import annotations

import json
import urllib.request
from typing import Any

from ...support.http import urlopen_retry
from ...support.secrets import scrub_secrets


QIANFAN_BASE = "https://qianfan.baidubce.com"


def search_baidu(query: str, api_key: str, count: int = 10,
                 timeout: float = 30) -> list[dict[str, Any]]:
    """Search via Baidu AI Search.

    Uses the high-performance web_summary endpoint, which returns answer plus
    per-reference body content inline.
    """
    return _search_baidu_summary(query, api_key, count, timeout)


def _search_baidu_summary(query: str, api_key: str, count: int, timeout: float) -> list[dict[str, Any]]:
    payload = {
        "messages": [{"role": "user", "content": query}],
        "resource_type_filter": [{"type": "web", "top_k": count}],
        "stream": False,
        "temperature": 0.1,
        "top_p": 0.5,
    }
    data = _post_json("/v2/ai_search/web_summary", api_key, payload, timeout)
    return _rows_from_response(data, endpoint="/v2/ai_search/web_summary", max_references=count)


def _post_json(path: str, api_key: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{QIANFAN_BASE}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "X-Appbuilder-Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen_retry(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"error": scrub_secrets(exc, api_key)}


def _rows_from_response(data: dict[str, Any], *, endpoint: str,
                        max_references: int) -> list[dict[str, Any]]:
    if data.get("error"):
        return [{"source": "baidu", "error": str(data["error"])}]
    if data.get("code") or data.get("message"):
        return [{
            "source": "baidu",
            "error": f"{data.get('code', '')} {data.get('message', '')}".strip(),
            "request_id": data.get("request_id") or data.get("requestId"),
        }]

    rows: list[dict[str, Any]] = []
    answer = _answer_text(data)
    request_id = data.get("request_id") or data.get("requestId")
    if answer:
        rows.append({
            "source": "baidu_answer",
            "answer": answer,
            "request_id": request_id,
            "endpoint": endpoint,
        })

    references = list(data.get("references") or [])[:max(0, max_references)]
    for ref in references:
        content = ref.get("content") or ""
        snippet = ref.get("snippet") or content
        markdown_text = ref.get("markdown_text") or ""
        row = {
            "source": "baidu",
            "title": ref.get("title", ""),
            "url": ref.get("url", ""),
            "description": (snippet or content)[:300],
            "score": ref.get("rerank_score"),
            "request_id": request_id,
            "endpoint": endpoint,
            "reference_id": ref.get("id"),
            "date": ref.get("date"),
            "website": ref.get("website") or ref.get("web_anchor"),
            "authority_score": ref.get("authority_score"),
        }
        if markdown_text:
            row["scraped_content"] = markdown_text
        elif content:
            row["scraped_content"] = content
        rows.append(row)
    if not rows:
        return [{"source": "baidu", "status": "ok", "raw_hits": 0, "request_id": request_id}]
    return rows


def _answer_text(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return str(message.get("content") or "").strip()
