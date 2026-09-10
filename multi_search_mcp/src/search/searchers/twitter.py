"""Twitter/X search via twikit-ng using saved cookies."""
import json
import os
import re
import time
from collections.abc import Callable

from ...support.secrets import scrub_secrets


REPLY_LIMIT = 20  # per tweet

# Strip session credentials from any exception text before it reaches stdout/logs.
_CRED_RE = re.compile(
    r"(auth_token|ct0|kdt|guest_id|twid|personalization_id|att)=[A-Za-z0-9%_+\-./]+",
    re.I,
)


def _scrub(msg: str, cookies=None) -> str:
    redacted = _CRED_RE.sub(r"\1=<redacted>", str(msg))
    return scrub_secrets(redacted, cookies, limit=300)


def search_twitter(
    query: str,
    count: int = 10,
    cookies: "dict | str" = "",
    timeout: float | None = None,
    *,
    publish_partial: Callable[[list], None] | None = None,
    deadline: float | None = None,
) -> list:
    """Search Twitter/X via twikit-ng using saved cookies.

    `cookies` accepts:
      - dict: {auth_token, ct0, ...} (e.g. from ~/.search-keys.json `"twitter": {...}`)
      - str: path to a JSON cookies file (e.g. ~/.mcp-twikit/cookies.json)
      - "" / falsy: falls back to ~/.mcp-twikit/cookies.json
    """
    try:
        import asyncio
        from twikit import Client  # type: ignore
    except ImportError:
        return [{"source": "twitter", "error": "twikit-ng not installed (pip install twikit-ng)"}]

    if isinstance(cookies, dict):
        cookies_dict = cookies
    else:
        cookies_path = cookies or os.path.expanduser("~/.mcp-twikit/cookies.json")
        if not os.path.exists(cookies_path):
            return [{"source": "twitter", "error": f"cookies file not found: {cookies_path}"}]
        try:
            with open(cookies_path, "r", encoding="utf-8") as f:
                cookies_dict = json.load(f)
        except Exception as e:
            return [{"source": "twitter", "error": f"cookies load failed: {_scrub(str(e))}"}]

    items = []
    reply_errors = {}
    if timeout is not None and timeout > 0:
        timeout_deadline = time.monotonic() + timeout
        deadline = min(deadline, timeout_deadline) if deadline is not None else timeout_deadline

    def result_rows() -> list:
        rows = []
        for item in items:
            row = dict(item)
            error = reply_errors.get(row["url"])
            if error:
                row["scraped_content"] += f"\n\n_Replies incomplete: {error}_"
            rows.append(row)
        rows.extend({"source": "twitter", "url": url, "error": f"{url}: {error}"}
                    for url, error in reply_errors.items())
        return rows

    def publish() -> None:
        if publish_partial is not None:
            publish_partial(result_rows())

    async def request(call, *args, **kwargs):
        if deadline is None:
            return await call(*args, **kwargs)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise asyncio.TimeoutError("search deadline exhausted")
        return await asyncio.wait_for(call(*args, **kwargs), timeout=remaining)

    async def search() -> list:
        client = Client("en-US")
        client.set_cookies(cookies_dict)
        try:
            tweets = await request(client.search_tweet, query, "Top", count=count)
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            if not ("404" in message or "429" in message or "rate" in message.lower()):
                raise
            await request(asyncio.sleep, 5)
            tweets = await request(client.search_tweet, query, "Top", count=count)
        tweets = list(tweets[:count])
        for t in tweets:
            screen = getattr(getattr(t, "user", None), "screen_name", "") or "i/web"
            tid = getattr(t, "id", "")
            url = f"https://x.com/{screen}/status/{tid}"
            text = (getattr(t, "text", "") or "").strip()
            first_line = text.split("\n", 1)[0][:120]
            items.append({
                "source": "twitter",
                "title": f"@{screen}: {first_line}" if screen != "i/web" else first_line,
                "url": url,
                "description": f"💬{getattr(t, 'reply_count', 0)} ♥{getattr(t, 'favorite_count', 0)} 🔁{getattr(t, 'retweet_count', 0)}",
                "scraped_content": text,
                "content_kind": "content",
            })
            reply_errors[url] = "replies have not been loaded"
        # Publish candidates before any optional reply request can block.
        publish()
        for t, item in zip(tweets, items):
            url = item["url"]
            fetched = 0
            try:
                full = await request(client.get_tweet_by_id, t.id)
                full_text = (getattr(full, "text", "") or "").strip()
                if len(full_text) > len(item["scraped_content"]):
                    item["scraped_content"] = full_text
                page = getattr(full, "replies", None)
                more = False
                while page is not None:
                    unread = False
                    for reply in page:
                        if fetched >= REPLY_LIMIT:
                            unread = True
                            break
                        if fetched == 0:
                            item["scraped_content"] += "\n\n**💬 Top replies:**"
                        user = getattr(getattr(reply, "user", None), "screen_name", "") or "anon"
                        text = (getattr(reply, "text", "") or "").strip()
                        likes = getattr(reply, "favorite_count", 0)
                        item["scraped_content"] += f"\n  - @{user} (♥{likes}): {text}"
                        fetched += 1
                    more = unread or bool(getattr(page, "next_cursor", None))
                    if not more:
                        break
                    if fetched >= REPLY_LIMIT:
                        reply_errors[url] = f"replies limit {REPLY_LIMIT} reached; additional replies are not included"
                        break
                    reply_errors[url] = "more replies remain unloaded"
                    publish()
                    page = await request(page.next)
                if not more:
                    reported = getattr(full, "reply_count", getattr(t, "reply_count", 0)) or 0
                    if reported > fetched:
                        reply_errors[url] = f"only {fetched} of {reported} reported replies loaded"
                    else:
                        reply_errors.pop(url, None)
            except asyncio.TimeoutError:
                reply_errors[url] = "replies fetch timed out before completion"
            except Exception as exc:
                reply_errors[url] = f"replies fetch failed: {_scrub(str(exc) or type(exc).__name__, cookies_dict)}"
            publish()
        return result_rows()

    try:
        return asyncio.run(search())
    except Exception as exc:
        return result_rows() + [{"source": "twitter", "error": _scrub(str(exc) or type(exc).__name__, cookies_dict)}]
