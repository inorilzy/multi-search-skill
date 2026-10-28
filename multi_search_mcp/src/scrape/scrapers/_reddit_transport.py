"""Reddit post transport over the public, unauthenticated JSON endpoint.

Requests identify this tool honestly with a descriptive User-Agent, carry no
token, cookie or OAuth scope, and use the shared ``urlopen_retry`` transport, so
proxy selection (standard ``HTTP(S)_PROXY`` / ``ALL_PROXY`` / ``NO_PROXY``),
redirect validation and the request deadline match every other provider.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from ...support.http import urlopen_retry
from ...support.url_security import validate_public_http_url


API_ORIGIN = "https://www.reddit.com"
USER_AGENT = "multi-search/1.0 (post reader; +https://github.com/inorilzy/multi-search)"
# Reddit post JSON with 100 comments is well below this; it only bounds memory.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class RedditError(ValueError):
    """A public error that never embeds response bodies or credentials."""


def remaining(deadline: float) -> float:
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError("Reddit scrape deadline exceeded")
    return seconds


def post_json_url(post_id: str, params: dict) -> str:
    query = urllib.parse.urlencode(params)
    return f"{API_ORIGIN}/comments/{post_id}.json" + (f"?{query}" if query else "")


def _decode(resp) -> object:
    content_type = str(resp.headers.get("Content-Type") or "").lower()
    if "application/json" not in content_type:
        raise RedditError("Reddit returned a non-JSON response (possibly a block page)")
    body = resp.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise RedditError("Reddit response is larger than the size cap")
    try:
        return json.loads(body)
    except (ValueError, TypeError):
        raise RedditError("Reddit returned invalid JSON") from None


def get_post_json(post_id: str, params: dict, deadline: float):
    url = post_json_url(post_id, params)
    validate_public_http_url(url, deadline=deadline)
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urlopen_retry(
            request, timeout=remaining(deadline), retries=0,
            deadline=deadline,
        ) as resp:
            return _decode(resp)
    except urllib.error.HTTPError as exc:
        try:
            exc.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup only
            pass
        raise RedditError(f"Reddit returned HTTP {exc.code}") from None
