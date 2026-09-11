"""Shared scraper helpers and constants."""
import urllib.parse


_DEFAULT_SCRAPE_TIMEOUT_SECONDS = 30
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
