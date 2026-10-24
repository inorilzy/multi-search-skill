"""Per-source body acquisition, content caching and bounded reads."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid

from ..scrape.scrapers.twitter import is_twitter_url, validate_twitter_url
from ..search.candidate import canonicalize_url, make_source_id
from ..search.capabilities import PROVIDER_CAPABILITIES, retention_policy_for_sources
from ..support.config import resolve_nonnegative
from ..search.resolve import resolve_scrape_backends
from ..state.content_store import DEFAULT_MAX_OBJECT_BYTES, ContentStoreError
from ..state.source_registry import SourceRegistry
from ..support.url_security import validate_public_http_url
from ..support.secrets import scrub_secrets
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
        "truncated": bool(cached.get("truncated")),
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
        timeout = resolve_nonnegative(
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
                # Hash only the credentials that can affect this source's body,
                # not every configured provider: an unrelated key rotation must
                # not invalidate a still-authorized cached body.
                cache_scope = hashlib.sha256(json.dumps({
                    "providers": sorted(source_providers),
                    "backends": list(request.backends or resolve_scrape_backends(resolved_config)),
                    "keys": _scope_keys(runtime_keys, source_providers, request.backends or resolve_scrape_backends(resolved_config)),
                }, sort_keys=True).encode("utf-8")).hexdigest()
                if is_twitter_url(url):
                    cache_scope = "twitter-detail-v1:" + cache_scope
                cached = content_store.reuse_for_url(
                    source_id, canonical_url=canonicalize_url(url), cache_scope=cache_scope,
                )
    if cached is not None:
        cached_body = str(cached["content"])
        preview, preview_truncated = _truncate_chars(cached_body, max_chars)
        return {
            "source_id": source_id,
            "url": url,
            "body": preview,
            "content_hash": cached["content_hash"],
            "content_length": len(cached_body),
            "expires_at": cached["expires_at"],
            "backend": "content-store",
            "cache_hit": True,
            "persisted": True,
            "truncated": bool(cached.get("truncated")) or preview_truncated,
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
    # The store caps objects by UTF-8 bytes; acquire by characters. Truncate
    # explicitly at the byte boundary (marking truncated) instead of letting a
    # long CJK page fail the whole fetch at cache-write time.
    max_cache_bytes = int(
        getattr(content_store, "max_object_bytes", DEFAULT_MAX_OBJECT_BYTES)
    )
    body, cache_truncated = _truncate_bytes(body, max_cache_bytes)
    acquisition_truncated = cache_truncated or bool(result.get("truncated"))
    stored = None
    cache_error = ""
    if content_store and source_id and retention.persist_body:
        try:
            stored = content_store.put(
                source_id, body,
                canonical_url=canonicalize_url(url) if cache_scope else "",
                cache_scope=cache_scope,
                truncated=acquisition_truncated,
            )
        except (ContentStoreError, sqlite3.Error, OSError) as exc:
            # A cache failure must not discard the body we already paid for.
            cache_error = scrub_secrets(exc, runtime_keys)
    preview, preview_truncated = _truncate_chars(body, max_chars)
    response = {
        "source_id": source_id or None,
        "url": url,
        "body": preview,
        "content_length": len(body),
        "content_hash": stored.get("content_hash") if stored else None,
        "expires_at": stored.get("expires_at") if stored else None,
        "backend": str(result.get("via") or "unknown"),
        "cache_hit": False,
        "persisted": stored is not None,
        "truncated": acquisition_truncated or preview_truncated,
        "untrusted_content": True,
        "site_scraper_updates": updates,
    }
    if cache_error:
        response["cache_error"] = cache_error
    return response


def _scope_keys(keys: dict, source_providers: list, backends) -> dict:
    """Credentials relevant to this body: provider names plus their key ids."""
    wanted = {str(name) for name in source_providers} | {str(name) for name in (backends or [])}
    if "twitter" in wanted:
        wanted.add("twitter_cookies_path")
    if "github_repos" in wanted:
        wanted.add("github")
    for name in list(wanted):
        capability = PROVIDER_CAPABILITIES.get(name)
        key_name = getattr(getattr(capability, "operation", None), "key_name", None)
        if key_name:
            wanted.add(key_name)
    from ..providers.xkit import ManagedTwitterCookies
    # Managed auth is mutable behind a stable reference: do not cross-source
    # reuse it without an authorization version. Source-id cache remains TTL-bound.
    return {name: ("managed:" + uuid.uuid4().hex if isinstance(value, ManagedTwitterCookies) else value)
            for name, value in keys.items() if name in wanted}


def _truncate_bytes(text: str, max_bytes: int | None) -> tuple[str, bool]:
    """Cut ``text`` to at most ``max_bytes`` UTF-8 bytes on a char boundary."""
    if max_bytes is None or max_bytes < 1:
        return text, False
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text, False
    return raw[:max_bytes].decode("utf-8", "ignore"), True


def _truncate_chars(text: str, max_chars: int | None) -> tuple[str, bool]:
    if max_chars is None or len(text) <= max_chars:
        return text, False
    return text[:max_chars], True
