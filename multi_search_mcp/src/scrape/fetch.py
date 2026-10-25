"""Fetch one source or URL body, reusing the shared cache and scraper chain."""
from __future__ import annotations

import hashlib
import json
import time
import uuid

from ..search.candidate import canonicalize_url, make_source_id
from ..search.capabilities import PROVIDER_CAPABILITIES, retention_policy_for_sources
from ..state import runtime
from ..state.content_store import (
    ContentStore,
    ContentTooLargeError,
    DEFAULT_MAX_OBJECT_BYTES,
    max_acquisition_chars,
)
from ..state.source_registry import SourceRegistry
from ..state.state_store import StateStore
from ..support.config import resolve_nonnegative
from ..support.requests import FetchSourceRequest, ScrapeRequest
from ..support.url_security import validate_public_http_url
from ..support.validation import request_int
from .scrapers.twitter import is_twitter_url, validate_twitter_url
from .service import configured_scrape_backends, run_scrape_raw


def run_fetch_source(
    request: FetchSourceRequest | dict,
    *,
    state_store: StateStore | None = None,
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
    # Validate before any network or state access, so bad input is reported as such.
    requested_max_chars = request_int(request.max_chars, "max_chars")
    if not request.use_state and request.source_id and source_record is None:
        raise ValueError("source_id fetch requires state; provide an explicit URL")

    store = (state_store or StateStore()) if request.use_state else None
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
    max_chars = None if request.full_content else max(1, min(requested_max_chars, 20_000))

    content_store = ContentStore(store, ttl_seconds=retention.max_ttl_seconds) if store is not None else None
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
                scope_backends = list(request.backends or configured_scrape_backends(resolved_config))
                cache_scope = hashlib.sha256(json.dumps({
                    "providers": sorted(source_providers),
                    "backends": scope_backends,
                    "keys": _scope_keys(runtime_keys, source_providers, scope_backends),
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
                # Preview size must not truncate the cached acquisition. The
                # character bound is derived from the cache's byte bound: no body
                # longer than this can ever be stored, and the exact UTF-8 size
                # is checked when persisting.
                scrape_chars=max_acquisition_chars(DEFAULT_MAX_OBJECT_BYTES),
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
    stored = None
    persist_error = None
    if content_store and source_id and retention.persist_body:
        try:
            stored = content_store.put(
                source_id, body,
                canonical_url=canonicalize_url(url) if cache_scope else "",
                cache_scope=cache_scope,
            )
        except ContentTooLargeError as exc:
            # The cache limit is UTF-8 bytes, so a large CJK page can exceed it
            # well below the character acquisition limit. The body is already
            # acquired: return it unpersisted (nothing was written) instead of
            # failing the whole fetch and discarding it.
            persist_error = {
                "reason": "content_too_large",
                "content_bytes": exc.content_bytes,
                "limit_bytes": exc.limit_bytes,
                "message": (
                    f"{exc}; body returned but not cached, so read_source and "
                    "later fetches of this source_id cannot reuse it"
                ),
            }
    response = {
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
    if persist_error is not None:
        response["persist_error"] = persist_error
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
    managed_type = _managed_cookie_type()
    # Managed auth is mutable behind a stable reference: do not cross-source
    # reuse it without an authorization version. Source-id cache remains TTL-bound.
    return {
        name: ("managed:" + uuid.uuid4().hex if managed_type and isinstance(value, managed_type) else value)
        for name, value in keys.items() if name in wanted
    }


def _managed_cookie_type():
    """The provider-owned managed-cookie reference type, when providers/ exists."""
    try:
        from ..providers.xkit import ManagedTwitterCookies
    except ImportError:  # pragma: no cover - providers/ lands with the provider port
        return None
    return ManagedTwitterCookies
