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


def error_fields(*, kind: str = "", origin: str = "") -> dict:
    """Return a scraper error row's classification metadata.

    The tree is migrating to the ``kind``/``origin`` taxonomy owned by
    ``support.models`` while the current key-state classifier still reads
    ``error_type``/``error_origin``. Scrapers emit both spellings until that
    move lands, so key health is classified correctly either way.
    """
    fields = {}
    if kind:
        fields["kind"] = kind
        fields["error_type"] = kind
    if origin:
        fields["origin"] = origin
        fields["error_origin"] = origin
    return fields

