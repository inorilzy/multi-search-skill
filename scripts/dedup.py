"""URL normalization + cross-source deduplication."""
import urllib.parse


def _norm_url(url: str) -> str:
    """Normalize URL for dedup: force https, lowercase host, strip trailing slash, remove UTM/tracking params."""
    try:
        parts = urllib.parse.urlparse(url.strip())
        scheme = "https" if parts.scheme in ("http", "https") else parts.scheme
        qs = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
        qs = {k: v for k, v in qs.items()
              if not k.lower().startswith(("utm_", "fbclid", "gclid", "ref", "source"))}
        new_query = urllib.parse.urlencode(qs, doseq=True)
        path = parts.path.rstrip("/") or "/"
        return urllib.parse.urlunparse((scheme, parts.netloc.lower(), path, parts.params, new_query, ""))
    except Exception:
        return url


def deduplicate(results: list) -> tuple:
    """Remove duplicate URLs, keeping first occurrence. Returns (deduped, source_counts_raw).

    source_counts_raw counts each source's contribution BEFORE dedup, so users
    see that Brave/Tavily both returned a URL even if only one is shown.
    Each kept item also gets an 'also_from' list of other sources that returned the same URL.
    """
    raw_counts: dict = {}
    for item in results:
        if "error" in item or item.get("source") in ("tavily_answer", "serpapi_answer", "exa_answer"):
            continue
        src = item.get("source", "?")
        raw_counts[src] = raw_counts.get(src, 0) + 1

    seen: dict = {}
    deduped: list = []
    for item in results:
        url = item.get("url", "")
        if not url:
            deduped.append(item)
            continue
        norm = _norm_url(url)
        if norm not in seen:
            seen[norm] = len(deduped)
            item = dict(item)
            item["also_from"] = []
            deduped.append(item)
        else:
            existing = deduped[seen[norm]]
            other_src = item.get("source", "?")
            if other_src != existing.get("source") and other_src not in existing.get("also_from", []):
                existing.setdefault("also_from", []).append(other_src)
    return deduped, raw_counts
