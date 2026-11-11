"""Twitter/X search candidates via XKit-py using saved cookies."""
import time
from collections.abc import Callable

from ...providers.xkit import TwitterCookiesMissing, load_twitter_cookies, scrub_twitter_error

# X's retry wait after a 429. Waiting is only useful when the caller's budget
# covers both the wait and a fresh request.
RATE_LIMIT_RETRY_SECONDS = 5


def search_twitter(
    query: str,
    count: int = 10,
    cookies: "dict | str" = "",
    timeout: float | None = None,
    *,
    publish_partial: Callable[[list], None] | None = None,
    deadline: float | None = None,
) -> list:
    """Return ranked candidates; the fetch pipeline owns tweet details/replies.

    ``cookies`` accepts a cookie dict or JSON file path. An empty value uses
    ``~/.mcp-twikit/cookies.json``.
    """
    try:
        cookies_dict = load_twitter_cookies(cookies)
    except Exception as exc:
        row = {"source": "twitter", "error": scrub_twitter_error(str(exc) or type(exc).__name__, cookies)}
        if isinstance(exc, TwitterCookiesMissing) or "cookies file not found" in str(exc):
            # The desktop maps missing_key to the "save a cookie" guide; a
            # missing dependency or malformed file is a different failure.
            row["error_type"] = "missing_key"
        return [row]

    try:
        import asyncio
        from xkit import Client  # type: ignore
    except ImportError:
        return [{"source": "twitter", "error": "XKit-py unavailable; reinstall multi-search-mcp with its dependencies"}]

    items = []
    if timeout is not None and timeout > 0:
        timeout_deadline = time.monotonic() + timeout
        deadline = min(deadline, timeout_deadline) if deadline is not None else timeout_deadline

    async def request(call, *args, **kwargs):
        if deadline is None:
            return await call(*args, **kwargs)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise asyncio.TimeoutError("search deadline exhausted")
        return await asyncio.wait_for(call(*args, **kwargs), timeout=remaining)

    async def wait_before_retry(seconds: float) -> bool:
        """Wait for the provider hint, but never past the caller's deadline."""
        if deadline is None:
            await asyncio.sleep(seconds)
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        try:
            await asyncio.wait_for(asyncio.sleep(seconds), timeout=remaining)
        except (asyncio.TimeoutError, TimeoutError):
            return False
        return True

    async def search(client) -> list:
        client.set_cookies(cookies_dict)
        try:
            tweets = await request(client.search_tweet, query, "Top", count=count)
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            rate_limited = "429" in message or "rate" in message.lower()
            if not (rate_limited or "404" in message):
                raise
            if not await wait_before_retry(RATE_LIMIT_RETRY_SECONDS):
                if rate_limited:
                    # Report the real cause instead of a generic deadline timeout.
                    items.append({
                        "source": "twitter",
                        "error": "Twitter rate limited (429); remaining budget is shorter than the 5s retry wait",
                        "kind": "rate_limit", "error_type": "rate_limit",
                        "rate_limited": True, "retry_after": RATE_LIMIT_RETRY_SECONDS,
                    })
                else:
                    items.append({"source": "twitter", "error": scrub_twitter_error(message, cookies_dict)})
                return items
            tweets = await request(client.search_tweet, query, "Top", count=count)
        for tweet in tweets[:count]:
            screen = getattr(getattr(tweet, "user", None), "screen_name", "") or "i/web"
            tweet_id = getattr(tweet, "id", "")
            text = (tweet.full_text or "").strip()
            first_line = text.split("\n", 1)[0][:120]
            items.append({
                "source": "twitter",
                "title": f"@{screen}: {first_line}" if screen != "i/web" else first_line,
                "url": f"https://x.com/{screen}/status/{tweet_id}",
                "description": (
                    f"💬{getattr(tweet, 'reply_count', 0)} ♥{getattr(tweet, 'favorite_count', 0)} "
                    f"🔁{getattr(tweet, 'retweet_count', 0)}\n{text[:500]}"
                ),
                "scraped_content": "",
                "content_kind": "excerpt",
                "author": screen if screen != "i/web" else "",
                "tweet_id": tweet_id,
                "reply_count": getattr(tweet, "reply_count", 0),
                "favorite_count": getattr(tweet, "favorite_count", 0),
                "retweet_count": getattr(tweet, "retweet_count", 0),
            })
        if publish_partial is not None:
            publish_partial([dict(item) for item in items])
        return items

    async def run() -> list:
        # HTTPX otherwise imposes its own 5-second timeout during X's lazy
        # transaction initialization, before the provider budget is exhausted.
        request_timeout = max(0.001, deadline - time.monotonic()) if deadline is not None else 20.0
        client = Client("en-US", timeout=request_timeout)
        try:
            return await search(client)
        finally:
            await client.http.aclose()

    try:
        return asyncio.run(run())
    except Exception as exc:
        return items + [{"source": "twitter", "error": scrub_twitter_error(str(exc) or type(exc).__name__, cookies_dict)}]
