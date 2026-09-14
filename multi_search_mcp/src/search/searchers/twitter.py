"""Twitter/X search candidates via XKit-py using saved cookies."""
import time
from collections.abc import Callable

from ...support.xkit import load_twitter_cookies, scrub_twitter_error


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
        import asyncio
        from xkit import Client  # type: ignore
    except ImportError:
        return [{"source": "twitter", "error": "XKit-py unavailable; reinstall multi-search-mcp with its dependencies"}]

    try:
        cookies_dict = load_twitter_cookies(cookies)
    except Exception as exc:
        return [{"source": "twitter", "error": scrub_twitter_error(str(exc) or type(exc).__name__, cookies)}]

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

    async def search(client) -> list:
        client.set_cookies(cookies_dict)
        try:
            tweets = await request(client.search_tweet, query, "Top", count=count)
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            if not ("404" in message or "429" in message or "rate" in message.lower()):
                raise
            await request(asyncio.sleep, 5)
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
