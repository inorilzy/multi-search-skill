"""Twitter/X search via twikit-ng using saved cookies."""
import json
import os


REPLY_LIMIT = 20  # per tweet


def search_twitter(query: str, count: int = 10, cookies_path: str = "") -> list:
    """Search Twitter/X via twikit-ng using saved cookies.

    Cookies file should be a JSON dict with at minimum {"auth_token": "...", "ct0": "..."}.
    Default path: ~/.mcp-twikit/cookies.json (shared with mcp-twikit).
    Override via keys.json "twitter_cookies" field or TWITTER_COOKIES_PATH env var.
    """
    try:
        import asyncio
        from twikit import Client  # type: ignore
    except ImportError:
        return [{"source": "twitter", "error": "twikit-ng not installed (pip install twikit-ng)"}]

    if not cookies_path:
        cookies_path = os.path.expanduser("~/.mcp-twikit/cookies.json")
    if not os.path.exists(cookies_path):
        return [{"source": "twitter", "error": f"cookies file not found: {cookies_path}"}]

    try:
        with open(cookies_path, "r", encoding="utf-8") as f:
            cookies = json.load(f)
    except Exception as e:
        return [{"source": "twitter", "error": f"cookies load failed: {e}"}]

    async def _do_search() -> list:
        client = Client("en-US")
        client.set_cookies(cookies)
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
                replies.append(f"  - _(replies fetch failed: {str(e)[:80]})_")
            out.append((t, replies))
        return out

    try:
        tweet_pairs = asyncio.run(_do_search())
    except Exception as e:
        msg = str(e) or repr(e) or type(e).__name__
        if "404" in msg or "429" in msg or "rate" in msg.lower():
            import time as _t
            _t.sleep(5)
            try:
                tweet_pairs = asyncio.run(_do_search())
            except Exception as e2:
                return [{"source": "twitter", "error": f"retry failed: {str(e2)[:180]}"}]
        else:
            return [{"source": "twitter", "error": msg[:200]}]

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
