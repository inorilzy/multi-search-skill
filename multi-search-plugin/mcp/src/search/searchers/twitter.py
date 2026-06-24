"""Twitter/X search via twikit-ng using saved cookies."""
import json
import os
import re

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

    async def _do_search() -> list:
        client = Client("en-US")
        client.set_cookies(cookies_dict)
        tweets = await client.search_tweet(query, "Top", count=count)
        out = []
        for t in tweets[:count]:
            replies = []
            try:
                full = await client.get_tweet_by_id(t.id)
                page = getattr(full, "replies", None)
                fetched = 0
                while page and fetched < REPLY_LIMIT:
                    for r in page:
                        if fetched >= REPLY_LIMIT:
                            break
                        r_user = getattr(getattr(r, "user", None), "screen_name", "") or "anon"
                        r_text = (getattr(r, "text", "") or "").strip().replace("\n", " ")
                        r_fav = getattr(r, "favorite_count", 0)
                        replies.append(f"  - @{r_user} (♥{r_fav}): {r_text[:200]}")
                        fetched += 1
                    if fetched >= REPLY_LIMIT or not getattr(page, "next_cursor", None):
                        break
                    try:
                        page = await page.next()
                        await asyncio.sleep(0.4)
                    except Exception:
                        break
                await asyncio.sleep(0.6)
            except Exception as e:
                replies.append(f"  - _(replies fetch failed: {_scrub(str(e), cookies_dict)[:80]})_")
            out.append((t, replies))
        return out

    async def _do_search_with_timeout() -> list:
        if timeout is not None and timeout > 0:
            return await asyncio.wait_for(_do_search(), timeout=timeout)
        return await _do_search()

    try:
        tweet_pairs = asyncio.run(_do_search_with_timeout())
    except Exception as e:
        msg = str(e) or repr(e) or type(e).__name__
        if "404" in msg or "429" in msg or "rate" in msg.lower():
            import time as _t
            _t.sleep(min(5, max(0.0, timeout or 5)))
            try:
                tweet_pairs = asyncio.run(_do_search_with_timeout())
            except Exception as e2:
                return [{"source": "twitter", "error": f"retry failed: {_scrub(str(e2), cookies_dict)}"}]
        else:
            return [{"source": "twitter", "error": _scrub(msg, cookies_dict)}]

    items = []
    for t, replies in tweet_pairs:
        screen = getattr(getattr(t, "user", None), "screen_name", "") or "i/web"
        tid = getattr(t, "id", "")
        url_val = f"https://x.com/{screen}/status/{tid}" if screen != "i/web" else f"https://x.com/i/web/status/{tid}"
        text = (getattr(t, "text", "") or "").strip()
        first_line = text.split("\n", 1)[0][:120]
        content = text
        if replies:
            content += "\n\n**💬 Top replies:**\n" + "\n".join(replies)
        items.append({
            "source": "twitter",
            "title": f"@{screen}: {first_line}" if screen != "i/web" else first_line,
            "url": url_val,
            "description": f"💬{getattr(t, 'reply_count', 0)} ♥{getattr(t, 'favorite_count', 0)} 🔁{getattr(t, 'retweet_count', 0)}",
            "scraped_content": content,
        })
    return items
