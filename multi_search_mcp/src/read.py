"""Cache-only read path for one source ID."""
from __future__ import annotations

from .state.content_store import ContentStore
from .state.state_store import StateStore
from .support.requests import ReadSourceRequest
from .support.validation import request_int


def run_read_source(
    request: ReadSourceRequest | dict,
    *,
    state_store: StateStore | None = None,
    content_store: ContentStore | None = None,
) -> dict:
    """Read a bounded slice from ContentStore without accessing the network."""
    if isinstance(request, dict):
        request = ReadSourceRequest(**request)
    if not request.source_id:
        raise ValueError("source_id is required")
    if not request.use_state:
        raise ValueError("read_source requires state")
    # Validate the request before touching state, so bad input is reported as such.
    offset = max(0, request_int(request.offset, "offset"))
    limit = max(1, min(request_int(request.limit, "limit"), 8_000))
    store = state_store or (content_store.store if content_store else StateStore())
    cache = content_store or ContentStore(store)
    cached = cache.get(request.source_id)
    if cached is None:
        raise ValueError(
            "cached content is missing or expired; call fetch_source first"
        )

    body = str(cached["content"])
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
