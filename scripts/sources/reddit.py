"""Reddit search via OAuth (script app, no user auth needed).

Reddit blocks unauthenticated `*.reddit.com/*.json` requests as of 2024.
Set up a free "script" type app at https://www.reddit.com/prefs/apps and
add to `~/.search-keys.json`:

    "reddit": {"client_id": "...", "client_secret": "..."}

If unconfigured, returns a single helpful error item (no crash).
"""
import base64
import json
import time
import urllib.parse
import urllib.request

from ..http import urlopen_retry


_UA = "multi-search-agent/1.0"
_TOKEN_CACHE: dict = {}  # {client_id: (token, expires_at)}


def _get_token(client_id: str, client_secret: str) -> str:
    cached = _TOKEN_CACHE.get(client_id)
    if cached and cached[1] > time.time() + 60:
        return cached[0]
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    req = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token",
        data=b"grant_type=client_credentials",
        headers={
            "Authorization": f"Basic {auth}",
            "User-Agent": _UA,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urlopen_retry(req, timeout=15) as resp:
        data = json.loads(resp.read())
    tok = data["access_token"]
    _TOKEN_CACHE[client_id] = (tok, time.time() + int(data.get("expires_in", 3600)))
    return tok


def search_reddit(query: str, count: int = 10, creds: "dict | str" = "",
                  subreddit: str = "") -> list:
    """Search Reddit posts via OAuth. `creds` is a dict {client_id, client_secret}.

    Returns submission posts with selftext as scraped_content so the agent
    gets the actual discussion text without a redundant fetch.
    """
    if not isinstance(creds, dict) or not creds.get("client_id") or not creds.get("client_secret"):
        return [{
            "source": "reddit",
            "error": "reddit OAuth not configured — add "
                     '"reddit": {"client_id": "...", "client_secret": "..."} '
                     "to ~/.search-keys.json (create a 'script' app at "
                     "https://www.reddit.com/prefs/apps)",
        }]
    try:
        token = _get_token(creds["client_id"], creds["client_secret"])
    except Exception as e:
        return [{"source": "reddit", "error": f"token fetch failed: {e}"}]

    if subreddit:
        path = f"https://oauth.reddit.com/r/{urllib.parse.quote(subreddit)}/search"
        params = {"q": query, "limit": min(count, 25), "restrict_sr": "on", "sort": "relevance"}
    else:
        path = "https://oauth.reddit.com/search"
        params = {"q": query, "limit": min(count, 25), "sort": "relevance"}
    url = path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "User-Agent": _UA,
    })
    try:
        with urlopen_retry(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"source": "reddit", "error": str(e)}]

    items: list = []
    for child in (data.get("data") or {}).get("children") or []:
        d = child.get("data") or {}
        permalink = d.get("permalink") or ""
        url_val = f"https://www.reddit.com{permalink}" if permalink else d.get("url", "")
        if not url_val:
            continue
        score = d.get("score", 0)
        num_comments = d.get("num_comments", 0)
        sub = d.get("subreddit", "")
        selftext = (d.get("selftext") or "").strip()
        items.append({
            "source": "reddit",
            "title": d.get("title", "") or "(no title)",
            "url": url_val,
            "description": f"r/{sub} ⬆{score} 💬{num_comments}",
            "scraped_content": selftext[:4000] if selftext else "",
        })
    return items
