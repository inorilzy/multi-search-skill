"""URL normalization shared by result deduplication and scraper planning."""
import urllib.parse


# Exact tracking-parameter names to drop during URL normalization. Prefix
# matching on "ref"/"source" used to also delete meaningful params like
# ref_id / reference / source_id, collapsing distinct URLs into one and
# silently dropping results. Only utm_* keeps prefix semantics.
TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "msclkid", "yclid",
    "ref", "ref_src", "source",
}


def _is_tracking_param(key: str) -> bool:
    k = key.lower()
    return k.startswith("utm_") or k in TRACKING_PARAMS


def _norm_url(url: str) -> str:
    """Normalize URL for dedup: force https, lowercase host, strip trailing slash, remove UTM/tracking params."""
    try:
        parts = urllib.parse.urlparse(url.strip())
        scheme = "https" if parts.scheme in ("http", "https") else parts.scheme
        qs = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
        qs = {k: v for k, v in qs.items() if not _is_tracking_param(k)}
        new_query = urllib.parse.urlencode(qs, doseq=True)
        path = parts.path.rstrip("/") or "/"
        return urllib.parse.urlunparse((scheme, parts.netloc.lower(), path, parts.params, new_query, ""))
    except Exception:
        return url
