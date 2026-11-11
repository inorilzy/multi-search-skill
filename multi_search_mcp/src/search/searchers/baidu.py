"""Baidu Qianfan AI Search adapters."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from ...support.http import read_limited, urlopen_retry
from ...support.http_errors import http_error_row
from ...support.secrets import scrub_secrets
from ...support.models import empty_result_row


QIANFAN_BASE = "https://qianfan.baidubce.com"
# docs/baidu/error-codes.md: 401 IAM/key failures, 429 rate_limit_exceeded or
# quota_exceeded (distinguished by error.type).
_BAIDU_HTTP_ERROR_KINDS = {401: "invalid", 403: "invalid", 429: "rate_limit"}

# The web_summary endpoint can report a provider error inside HTTP 200. Its
# ``error.type``/``error.code`` distinguish authentication, quota and rate
# limits; Chinese messages carry the same signals when no type is present.
_BAIDU_QUOTA_TOKENS = (
    "quota", "额度", "配额", "欠费", "余额", "overdue", "insufficient balance",
    "out of credits", "billing",
)
_BAIDU_RATE_LIMIT_TOKENS = (
    "rate_limit", "rate limit", "throttl", "too many requests", "限流",
    "频率", "qps", "rpm",
)
_BAIDU_AUTH_TOKENS = (
    "invalid_iam", "invalid_appid", "invalid_api_key", "invalid api key",
    "invalid_access_token", "invalid token", "token invalid", "invalid key",
    "token expired", "access token invalid",
    "key expired", "access_token_required", "authentication", "authorization",
    "unauthorized", "forbidden", "access denied", "access_denied",
    "permission denied", "no permission", "bearer token", "鉴权", "认证",
    "密钥", "权限", "令牌无效", "token 无效", "token无效",
)


def _baidu_refine(status: int, data, detail: str) -> str | None:
    error = data.get("error") if isinstance(data, dict) else None
    error_type = (error.get("type") or "") if isinstance(error, dict) else ""
    if error_type == "quota_exceeded":
        return "quota_exhausted"
    if error_type == "rate_limit_exceeded":
        return "rate_limit"
    return None


def _baidu_error_kind(error: Any) -> str:
    """Classify a documented Qianfan error object or message.

    Only credential-relevant categories are returned so a malformed request
    does not rotate keys.
    """
    if isinstance(error, dict):
        code = str(error.get("code") or "")
        error_type = str(error.get("type") or "")
        message = str(error.get("message") or error.get("detail") or "")
    else:
        code = error_type = ""
        message = str(error or "")
    text = f"{code} {error_type} {message}".lower()
    if any(token in text for token in _BAIDU_QUOTA_TOKENS):
        return "quota_exhausted"
    if any(token in text for token in _BAIDU_RATE_LIMIT_TOKENS):
        return "rate_limit"
    if any(token in text for token in _BAIDU_AUTH_TOKENS):
        return "invalid"
    return ""


def _baidu_error_row(message: Any, *, api_key: str, request_id: Any = None,
                     kind: str = "") -> dict[str, Any]:
    text = scrub_secrets(str(message or ""), api_key)[:300] or "Baidu API error"
    row: dict[str, Any] = {"source": "baidu", "error": text}
    if request_id:
        row["request_id"] = request_id
    if kind:
        row.update({
            "kind": kind, "error_type": kind,
            "origin": "provider", "error_origin": "provider",
        })
    return row


def search_baidu(query: str, api_key: str, count: int = 10,
                 timeout: float = 30, deadline: float | None = None) -> list[dict[str, Any]]:
    """Search via Baidu AI Search.

    Uses the high-performance web_summary endpoint, which returns an answer
    plus per-reference summaries without enable_full_content.
    """
    return _search_baidu_summary(query, api_key, count, timeout, deadline)


def _search_baidu_summary(query: str, api_key: str, count: int, timeout: float,
                          deadline: float | None = None) -> list[dict[str, Any]]:
    payload = {
        "messages": [{"role": "user", "content": query}],
        "resource_type_filter": [{"type": "web", "top_k": count}],
        "stream": False,
        "temperature": 0.1,
        "top_p": 0.5,
    }
    data = _post_json("/v2/ai_search/web_summary", api_key, payload, timeout, deadline)
    return _rows_from_response(
        data, endpoint="/v2/ai_search/web_summary", max_references=count, api_key=api_key,
    )


def _post_json(path: str, api_key: str, payload: dict[str, Any], timeout: float,
               deadline: float | None = None) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{QIANFAN_BASE}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            # Documented Qianfan public header (cloud.baidu.com/doc/qianfan-api/s/3m9b5lqft).
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen_retry(req, timeout=timeout, deadline=deadline) as resp:
            headers = getattr(resp, "headers", None)
            request_id = headers.get("X-Request-Id") if headers is not None else None
            data = json.loads(read_limited(resp).decode("utf-8"))
            if isinstance(data, dict) and request_id and not data.get("request_id"):
                data["request_id"] = request_id
            return data
    except urllib.error.HTTPError as exc:
        headers = getattr(exc, "headers", None)
        request_id = headers.get("X-Request-Id") if headers is not None else None
        row = http_error_row(
            "baidu", exc, secret=api_key, kinds=_BAIDU_HTTP_ERROR_KINDS, refine=_baidu_refine,
        )
        if request_id:
            row["request_id"] = request_id
        return {"_error_row": row}
    except Exception as exc:
        return {"error": scrub_secrets(exc, api_key)}


def _rows_from_response(data: dict[str, Any], *, endpoint: str,
                        max_references: int, api_key: str = "") -> list[dict[str, Any]]:
    if data.get("_error_row"):
        return [data["_error_row"]]
    error = data.get("error")
    request_id = data.get("id") or data.get("request_id") or data.get("requestId")
    if isinstance(error, dict):
        text = " ".join(str(error.get(k)) for k in ("code", "message") if error.get(k))
        return [_baidu_error_row(
            text or json.dumps(error, ensure_ascii=False),
            api_key=api_key, request_id=request_id, kind=_baidu_error_kind(error),
        )]
    if error:
        return [_baidu_error_row(
            error, api_key=api_key, request_id=request_id,
            kind=_baidu_error_kind(error),
        )]
    if data.get("code") or data.get("message"):
        detail = {"code": data.get("code"), "message": data.get("message")}
        return [_baidu_error_row(
            f"{data.get('code', '')} {data.get('message', '')}".strip(),
            api_key=api_key, request_id=request_id, kind=_baidu_error_kind(detail),
        )]

    rows: list[dict[str, Any]] = []
    answer = _answer_text(data)
    request_id = data.get("request_id") or data.get("requestId")
    if answer:
        rows.append({
            "source": "baidu_answer",
            "answer": answer,
            "content_kind": "answer",
            "request_id": request_id,
            "endpoint": endpoint,
        })

    references = list(data.get("references") or [])[:max(0, max_references)]
    for ref in references:
        content = ref.get("content") or ""
        snippet = ref.get("snippet") or content
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
        if snippet:
            # This request does not enable full content: content is a summary,
            # just like snippet, and must not bypass the page-body fetch.
            row["content_kind"] = "excerpt"
        else:
            row["content_kind"] = "metadata"
        rows.append(row)
    if not rows:
        return [empty_result_row("baidu", request_id=request_id)]
    return rows


def _answer_text(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return str(message.get("content") or "").strip()
