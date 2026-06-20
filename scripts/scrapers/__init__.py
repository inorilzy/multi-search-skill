"""Shared scraper helpers and constants."""
import re
import urllib.parse


_DEFAULT_SCRAPE_TIMEOUT_SECONDS = 30
_GH_REPO_RE = re.compile(r"^https?://github\.com/([^/\s]+)/([^/\s#?]+)/?$")
_JINA_KEY_INFO_URL = "https://dash.jina.ai/api/v1/api_key/fe_user"
_JINA_REMOVE_SELECTOR = (
    "header, nav, footer, aside, script, style, noscript, "
    ".header, .navbar, .navigation, .menu, .sidebar, .footer, "
    ".ad, .ads, .advertisement"
)


def _safe_http_url(url: str) -> str | None:
    """Reject non-http(s) URLs before handing them to a fetcher."""
    try:
        parts = urllib.parse.urlparse(url)
    except Exception:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return url


def _rewrite_for_clean_scrape(url: str) -> str:
    """Rewrite GitHub repo root URLs to raw README to avoid nav/chrome noise."""
    match = _GH_REPO_RE.match(url)
    if match:
        owner, repo = match.group(1), match.group(2).removesuffix(".git")
        return f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/README.md"
    return url
