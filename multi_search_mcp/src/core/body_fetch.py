"""Per-source body acquisition, content caching and bounded reads."""
from __future__ import annotations

import hashlib
import json
import time
import uuid

from ..scrape.scrapers.twitter import is_twitter_url, validate_twitter_url
from ..search.candidate import canonicalize_url, make_source_id
from ..search.capabilities import retention_policy_for_sources
from ..search.resolve import _resolve_nonnegative
from ..state.content_store import DEFAULT_MAX_OBJECT_BYTES
from ..state.source_registry import SourceRegistry
from ..support.url_security import validate_public_http_url
from . import runtime
from .requests import FetchSourceRequest, ReadSourceRequest, ScrapeRequest
from .scrape_pipeline import run_scrape_raw


def run_read_source(
    request: ReadSourceRequest | dict,
    *,
    state_store=None,
    content_store=None,
) -> dict:
    """Read a bounded slice from ContentStore without accessing the network."""
    if isinstance(request, dict):
        request = ReadSourceRequest(**request)
    if not request.source_id:
        raise ValueError("source_id is required")
    if not request.use_state:
        raise ValueError("read_source requires state")
    store = state_store or (content_store.store if content_store else runtime.new_state_store())
    cache = content_store or runtime.new_content_store(store)
    cached = cache.get(request.source_id)
    if cached is None:
        raise ValueError(
            "cached content is missing or expired; call fetch_source first"
        )

    body = str(cached["content"])
    offset = max(0, int(request.offset))
    limit = max(1, min(int(request.limit), 8_000))
    match_offset = None
    if request.keyword:
        lower_match_offset = body.lower().find(str(request.keyword).lower())
        if lower_match_offset < 0:
            raise ValueError("keyword was not found in cached content")
        # Preserve lower() matching, but map expanded characters (e.g. İ) back
        # to their original positions before applying character offsets.
        lower_end = 0
        for match_offset, char in enumerate(body):
            lower_end += len(char.lower())
            if lower_end > lower_match_offset:
                break
        start = min(len(body), match_offset + offset)
    else:
        start = min(len(body), offset)
    end = min(len(body), start + limit)
    return {
        "source_id": request.source_id,
        "content": body[start:end],
        "start": start,
        "end": end,
        "match_offset": match_offset,
        "has_more": end < len(body),
        "next_offset": (offset + (end - start)) if end < len(body) else None,
        "content_length": len(body),
        "content_hash": cached["content_hash"],
        "expires_at": cached["expires_at"],
        "untrusted_content": True,
    }


def run_fetch_source(
    request: FetchSourceRequest | dict,
    *,
    state_store=None,
    scraper=None,
    keys: dict | None = None,
    config: dict | None = None,
    url_resolver=None,
    source_record: dict | None = None,
    prefetched_body: str | None = None,
    deadline: float | None = None,
    runtime_timeout: float | None = None,
) -> dict:
    """Fetch one registered source and persist its untrusted body briefly."""
    if isinstance(request, dict):
        request = FetchSourceRequest(**request)
    if bool(request.source_id) == bool(request.url):
        raise ValueError("provide exactly one of source_id or url")
    if not request.use_state and request.source_id and source_record is None:
        raise ValueError("source_id fetch requires state; provide an explicit URL")

    store = (state_store or runtime.new_state_store()) if request.use_state else None
    if source_record is not None and source_record.get("source_id") != request.source_id:
        raise ValueError("source record does not match source_id")
    source = source_record
    if source is None and store and request.source_id:
        source = SourceRegistry(store).get(request.source_id)
    if request.source_id and source is None:
        raise ValueError(
            "source_id is unknown or expired; call search_web again before fetch_source"
        )
    url = str(request.url or source["url"])
    resolved_config = dict(config) if config is not None else None
    if deadline is None:
        budget_started = time.monotonic()
        if resolved_config is None and request.timeout is None:
            resolved_config = runtime.load_config_safe(request.config_path)
        timeout = _resolve_nonnegative(
            request.timeout, resolved_config or {}, "scrape_timeout", 60,
        )
        deadline = budget_started + timeout
    if is_twitter_url(url):
        validate_twitter_url(url)
    else:
        validate_public_http_url(url, resolver=url_resolver, deadline=deadline)
    source_providers = list((source or {}).get("providers") or ["direct"])
    retention = retention_policy_for_sources(source_providers)
    source_id = str(request.source_id or "")
    if not source_id:
        response_id = f"resp_{uuid.uuid4().hex}"
        canonical_url = canonicalize_url(url)
        source_id = make_source_id(response_id, canonical_url)
        if store is not None:
            SourceRegistry(
                store, ttl_seconds=retention.max_ttl_seconds
            ).register(response_id, [{
                "source_id": source_id,
                "title": url,
                "url": url,
                "canonical_url": canonical_url,
                "content": "",
                "content_kind": "metadata",
                "providers": ["direct"],
                "body_available": False,
            }])
        source = {"providers": ["direct"]}
    max_chars = None if request.full_content else max(1, min(int(request.max_chars), 20_000))

    content_store = runtime.new_content_store(
        store, ttl_seconds=retention.max_ttl_seconds,
    ) if store is not None else None
    cached = content_store.get(source_id) if content_store and source_id else None
    # Previous X search prefetches (and generic scrapes) did not acquire XKit
    # details. Only reuse bodies produced by the dedicated detail scraper.
    if cached is not None and is_twitter_url(url) and not str(cached.get("cache_scope") or "").startswith("twitter-detail-v1:"):
        content_store.delete_source(source_id)
        cached = None
    if cached is not None and not retention.persist_body:
        content_store.delete_source(source_id)
        cached = None
    cache_scope = ""
    runtime_keys = keys
    if cached is None:
        if resolved_config is None:
            resolved_config = runtime.load_config_safe(request.config_path)
        if not prefetched_body:
            runtime_keys = runtime.load_runtime_keys(resolved_config) if keys is None else dict(keys)
            if content_store and retention.persist_body:
                # Hash the permission context; never persist credentials. Provider
                # prefetches and older unscoped entries remain source-ID-only.
                cache_scope = hashlib.sha256(json.dumps({
                    "providers": sorted(source_providers),
                    "backends": list(request.backends or []),
                    "keys": runtime_keys,
                }, sort_keys=True).encode("utf-8")).hexdigest()
                if is_twitter_url(url):
                    cache_scope = "twitter-detail-v1:" + cache_scope
                cached = content_store.reuse_for_url(
                    source_id, canonical_url=canonicalize_url(url), cache_scope=cache_scope,
                )
    if cached is not None:
        return {
            "source_id": source_id,
            "url": url,
            "body": str(cached["content"])[:max_chars],
            "content_hash": cached["content_hash"],
            "content_length": len(str(cached["content"])),
            "expires_at": cached["expires_at"],
            "backend": "content-store",
            "cache_hit": True,
            "persisted": True,
            "truncated": max_chars is not None and len(str(cached["content"])) > max_chars,
            "untrusted_content": True,
        }

    updates = []
    if prefetched_body:
        result = {"markdown": prefetched_body, "via": "provider:prefetch"}
    else:
        result, updates, _scrape_chars = run_scrape_raw(
            ScrapeRequest(
                url=url,
                backends=request.backends,
                # Preview size must not truncate the cached acquisition.
                scrape_chars=DEFAULT_MAX_OBJECT_BYTES,
                timeout=request.timeout,
                output="json",
                use_state=request.use_state,
            ),
            state_store=store,
            scraper=scraper,
            keys=runtime_keys,
            config=resolved_config,
            url_resolver=url_resolver,
            deadline=deadline,
            runtime_timeout=runtime_timeout,
        )
    if result.get("error"):
        raise ValueError(str(result["error"]))
    body = str(result.get("markdown") or "")
    if not body:
        raise ValueError("fetch_source returned empty body")
    stored = (
        content_store.put(
            source_id, body,
            canonical_url=canonicalize_url(url) if cache_scope else "",
            cache_scope=cache_scope,
        )
        if content_store and source_id and retention.persist_body
        else None
    )
    return {
        "source_id": source_id or None,
        "url": url,
        "body": body[:max_chars],
        "content_length": len(body),
        "content_hash": stored.get("content_hash") if stored else None,
        "expires_at": stored.get("expires_at") if stored else None,
        "backend": str(result.get("via") or "unknown"),
        "cache_hit": False,
        "persisted": stored is not None,
        "truncated": max_chars is not None and len(body) > max_chars,
        "untrusted_content": True,
        "site_scraper_updates": updates,
    }
