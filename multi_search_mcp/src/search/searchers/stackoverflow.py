"""Stack Overflow question search via the Stack Exchange API."""
import html
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from ...state import backoff
from ...support.http import decompress_limited, read_error_body, read_limited, urlopen_retry
from ...support.secrets import scrub_secrets

# docs/stackexchange/throttle.md: a response with ``backoff`` forbids calling
# the same method for that many seconds; error-handling.md lists the error
# names (errors arrive as HTTP 400 with an error_id/error_name body).
_BACKOFF_NAME = "stackexchange:/search/advanced"
_SE_ERROR_KINDS = {
    "throttle_violation": "rate_limit",
    "access_token_required": "invalid",
    "invalid_access_token": "invalid",
    "key_required": "invalid",
    "access_denied": "invalid",
}


def _content_encoding(resp) -> str:
    headers = getattr(resp, "headers", {})
    value = headers.get("Content-Encoding")
    if value is None:
        value = headers.get("content-encoding")
    return str(value or "").strip().lower()


def _looks_like_json(body: bytes) -> bool:
    return body.lstrip().startswith((b"{", b"["))


def _decode_response(resp) -> bytes:
    body = read_limited(resp)
    encoding = _content_encoding(resp) or "gzip"

    # A proxy may have already decompressed the body, and early API errors are
    # allowed to bypass compression. Keep those JSON bodies intact.
    if _looks_like_json(body):
        return body
    if encoding in {"gzip", "deflate"}:
        # Bounded by the decompressed size, so a small bomb cannot expand.
        return decompress_limited(body, encoding)
    if encoding == "identity":
        return body
    raise ValueError(f"unsupported Content-Encoding: {encoding}")


def _error_row(data: dict, *, key: str = "", status: int | None = None) -> dict:
    name = str(data.get("error_name") or "")
    message = str(data.get("error_message") or name or "Stack Exchange error")
    kind = _SE_ERROR_KINDS.get(name, "error")
    text = f"{name}: {message}" if name and name not in message else message
    row = {"source": "stackoverflow", "error": scrub_secrets(text, key)[:300],
           "kind": kind, "error_type": kind, "origin": "provider", "error_origin": "provider"}
    if status is not None:
        row["http_status"] = status
    if kind == "rate_limit":
        row["rate_limited"] = True
    return row


def _http_error_payload(exc: urllib.error.HTTPError) -> dict:
    """Decode the (possibly gzipped) JSON body of a Stack Exchange HTTP error."""
    try:
        raw = read_error_body(exc, 65536)
        encoding = str((exc.headers or {}).get("Content-Encoding") or "").strip().lower()
        if raw and not _looks_like_json(raw) and encoding in {"gzip", "deflate"}:
            raw = decompress_limited(raw, encoding)
        data = json.loads(raw.decode("utf-8", "replace")) if raw else {}
    except Exception:
        data = {}
    finally:
        try:
            exc.close()
        except Exception:
            pass
    return data if isinstance(data, dict) else {}


def search_stackoverflow(
    query: str, count: int = 10, timeout: float = 20, deadline: float | None = None,
    api_key: str = "",
) -> list:
    """Search Stack Overflow questions by relevance.

    ``api_key`` is optional; when set it is sent as documented
    (``Authorization: Bearer``, docs/stackexchange/authentication.md) for a
    larger daily quota.
    """
    wait = backoff.remaining(_BACKOFF_NAME)
    if wait:
        return [{
            "source": "stackoverflow",
            "error": f"skipped: Stack Exchange asked to back off for {wait}s more",
            "kind": "rate_limit", "error_type": "rate_limit", "rate_limited": True,
            "origin": "provider", "error_origin": "provider", "retry_after": wait,
        }]
    params = {
        "order": "desc",
        "sort": "relevance",
        "q": query,
        "site": "stackoverflow",
        "pagesize": max(1, min(int(count), 100)),
    }
    url = "https://api.stackexchange.com/2.3/search/advanced?" + urllib.parse.urlencode(params)
    headers = {
        "Accept-Encoding": "gzip, deflate",
        "User-Agent": "multi-search/1.0",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urlopen_retry(req, timeout=timeout, deadline=deadline) as resp:
            data = json.loads(_decode_response(resp))
            if not isinstance(data, dict):
                raise ValueError("Stack Exchange response must be a JSON object")
    except urllib.error.HTTPError as e:
        data = _http_error_payload(e)
        if data.get("backoff"):
            backoff.record(_BACKOFF_NAME, float(data["backoff"]))
        if data.get("error_name") or data.get("error_message"):
            return [_error_row(data, key=api_key, status=e.code)]
        return [{"source": "stackoverflow", "error": scrub_secrets(f"HTTP {e.code}: {e.reason}", api_key)[:300]}]
    except Exception as e:
        return [{"source": "stackoverflow", "error": scrub_secrets(str(e), api_key)[:300]}]

    if data.get("backoff"):
        backoff.record(_BACKOFF_NAME, float(data["backoff"]))
    if data.get("error_message") or data.get("error_name"):
        return [_error_row(data, key=api_key)]

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
        row = {
            "source": "stackoverflow",
            "title": title or url_value or "(no title)",
            "url": url_value,
            "description": " · ".join(stats),
            "content_kind": "metadata",
        }
        created = result.get("creation_date")
        if isinstance(created, (int, float)) and not isinstance(created, bool) and created > 0:
            try:
                row["published_at"] = datetime.fromtimestamp(created, timezone.utc).isoformat()
            except (OverflowError, OSError, ValueError):
                pass
        items.append(row)
    if data.get("quota_remaining") == 0:
        # The shared per-IP (or per-key) daily quota is used up.
        quota = {
            "source": "stackoverflow",
            "error": "Stack Exchange daily quota exhausted (quota_remaining is 0)",
            "kind": "quota_exhausted", "error_type": "quota_exhausted",
            "origin": "provider", "error_origin": "provider",
        }
        if items:
            # This response already produced results: record the exhausted key
            # without replaying the same query on every remaining key.
            quota["retryable"] = False
        items.append(quota)
    return items
