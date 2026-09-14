"""Fetch X post text and replies through XKit-py using saved cookies."""
from __future__ import annotations

import asyncio
import re
import time
from urllib.parse import urlsplit

from ...support.url_security import UrlSecurityError
from ...support.xkit import load_twitter_cookies, scrub_twitter_error


REPLY_LIMIT = 20
_HOSTS = {"x.com", "www.x.com", "mobile.x.com",
          "twitter.com", "www.twitter.com", "mobile.twitter.com"}
_POST_PATH = re.compile(
    r"^/(?:[A-Za-z0-9_]{1,15}/status|i/web/status)/([0-9]+)"
    r"(?:/(?:photo|video)/[0-9]+)?/?$"
)


def is_twitter_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        return (parts.scheme.lower() in {"http", "https"}
                and (parts.hostname or "").lower() in _HOSTS)
    except ValueError:
        return False


def _tweet_id(url: str) -> str:
    parts = urlsplit(url)
    if parts.username is not None or parts.password is not None:
        raise ValueError("X/Twitter post URL must not include credentials")
    if not is_twitter_url(url) or parts.port not in {None, 80, 443}:
        raise ValueError("Twitter scraper only accepts X/Twitter post URLs")
    match = _POST_PATH.fullmatch(parts.path)
    if not match:
        raise ValueError("Unsupported X/Twitter URL; use a post permalink containing /status/<id>")
    return match[1]


def validate_twitter_url(url: str) -> str:
    """Validate a post identifier URL, never an arbitrary HTTP destination.

    XKit receives only the numeric post ID and contacts its fixed X endpoints.
    Input URL DNS checks would reject TUN fake-IP routing without protecting
    another connection: the supplied URL itself is never fetched.
    """
    candidate = str(url or "").strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in candidate):
        raise UrlSecurityError("X/Twitter post URL must not contain control characters")
    try:
        _tweet_id(candidate)
    except ValueError as exc:
        raise UrlSecurityError(str(exc)) from None
    return candidate


def _remaining(end: float) -> float:
    remaining = end - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Twitter scrape deadline exhausted")
    return remaining


def _text(tweet) -> str:
    # XKit's text property reads legacy.full_text, which can be a long-post
    # preview. full_text also reads note_tweet_results when present.
    text = tweet.full_text
    if not isinstance(text, str) or not text.strip():
        raise ValueError("X returned an empty post/reply body")
    return text


def scrape_url_twitter(url: str, cookies: dict | str = "", timeout: float = 60, *,
                       deadline: float | None = None, url_resolver=None) -> dict:
    end = time.monotonic() + max(0.0, timeout)
    if deadline is not None:
        end = min(end, deadline)
    safe_url, cookies_dict = url, {}
    title, metadata, body, replies, incomplete = "", "", "", [], ""

    async def fetch(client, tweet_id: str) -> None:
        nonlocal title, metadata, body, incomplete
        full = await client.get_tweet_by_id(tweet_id)
        text = _text(full)
        screen = getattr(getattr(full, "user", None), "screen_name", "")
        first_line = text.split("\n", 1)[0][:120]
        title = f"@{screen}: {first_line}" if screen else first_line
        metadata = (f"[Original post]({safe_url})" + (f" · @{screen}" if screen else "")
                    + f" · ♥{getattr(full, 'favorite_count', 0)}"
                    + f" · 🔁{getattr(full, 'retweet_count', 0)}"
                    + f" · 💬{getattr(full, 'reply_count', 0)}")
        body = text
        # Optional pagination must return before the outer stage deadline so
        # session cleanup, rendering, and caching can publish the acquired body.
        reply_end = end - min(0.25, max(0.0, end - time.monotonic()) * 0.1)
        page = getattr(full, "replies", None)
        while page is not None:
            unread = False
            for reply in page:
                if len(replies) >= REPLY_LIMIT:
                    unread = True
                    break
                reply_text = _text(reply)
                user = getattr(getattr(reply, "user", None), "screen_name", "") or "anon"
                likes = getattr(reply, "favorite_count", 0)
                replies.append(f"  - @{user} (♥{likes}): {reply_text}")
            more = unread or bool(getattr(page, "next_cursor", None))
            if not more:
                incomplete = ""
                break
            if len(replies) >= REPLY_LIMIT:
                incomplete = f"replies limit {REPLY_LIMIT} reached; additional replies are not included"
                return
            incomplete = "more replies remain unloaded"
            try:
                remaining = _remaining(reply_end)
                page = await asyncio.wait_for(page.next(), timeout=remaining)
            except (TimeoutError, asyncio.TimeoutError):
                incomplete = "replies fetch timed out before completion (comment budget exhausted)"
                return
        reported = getattr(full, "reply_count", 0) or 0
        if reported > len(replies):
            incomplete = f"only {len(replies)} of {reported} reported replies loaded"

    async def run(client_type, tweet_id: str) -> None:
        client = client_type("en-US", timeout=_remaining(end))
        try:
            client.set_cookies(cookies_dict)
            await asyncio.wait_for(fetch(client, tweet_id), timeout=_remaining(end))
        finally:
            await client.http.aclose()

    try:
        _remaining(end)
        safe_url = validate_twitter_url(url)
        tweet_id = _tweet_id(safe_url)
        cookies_dict = load_twitter_cookies(cookies)
        from xkit import Client
        asyncio.run(run(Client, tweet_id))
    except Exception as exc:
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
            error = "Twitter scrape timed out before completion (deadline exhausted)"
        elif isinstance(exc, ImportError):
            error = "XKit-py unavailable; reinstall multi-search-mcp with its dependencies"
        else:
            error = scrub_twitter_error(exc, cookies_dict)
        if not body:
            return {"url": safe_url, "error": error}
        incomplete = f"replies fetch failed: {error}"

    chunks = [metadata, body]
    if replies:
        chunks.extend(["**💬 Top replies:**", "\n".join(replies)])
    if incomplete:
        chunks.append(f"_Replies incomplete: {incomplete}_")
    markdown = "\n\n".join(chunks)
    # As with other scrapers, truncated concerns returned text cropping.
    # Known omissions from the remote discussion are stated in the Markdown.
    return {"url": safe_url, "title": title, "markdown": markdown,
            "length": len(markdown), "via": "twitter", "truncated": False}
