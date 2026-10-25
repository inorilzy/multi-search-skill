## REQ-12 — 有效 source_id 的缓存失效后仍以原ID重抓

> With a valid `source_id`, missing or expired cached content is fetched again
> — skills/multi-search/references/verification.md:L11

**Verdict:** implemented · confidence: high

---

**What this demands of an implementation:** 有效 source_id 的缓存失效后仍以原ID重抓。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/src/service.py:L195-L205
    store = (state_store or StateStore()) if request.use_state else None
    if source_record is not None and source_record.get("source_id") != request.source_id:
        raise ValueError("source record does not match source_id")
    source = source_record
    if source is None and store and request.source_id:
        source = SourceRegistry(store).get(request.source_id)
    if request.source_id and source is None:
        raise ValueError(
            "source_id is unknown or expired; call search_web again before fetch_source"
```

```python
# multi_search_mcp/src/service.py:L230-L254
    content_store = ContentStore(store, ttl_seconds=retention.max_ttl_seconds) if store is not None else None
    cached = content_store.get(source_id) if content_store and source_id else None
    if cached is not None and not retention.persist_body:
        content_store.delete_source(source_id)
        cached = None
    cache_scope = ""
    resolved_config = None
    runtime_keys = keys
    if cached is None:
```

```python
# multi_search_mcp/src/service.py:L270-L316
    updates = []
    if prefetched_body:
        result = {"markdown": prefetched_body, "via": "provider:prefetch"}
    else:
        result, updates, _scrape_chars = _run_scrape_raw(
            ScrapeRequest(
                url=url,
                backends=request.backends,
                # Preview size must not truncate the cached acquisition.
```

**Paths walked:**

fetch先校验来源引用，再查正文；缓存未命中可按同scope URL复用，否则调用scraper，存回原ID；来源本身不存在才报未知/过期。探针删除所有可复用正文、保留registry后同ID重新取得body。

**Searched:**

- `rg -n 'cached is None|source_id|ContentStore' multi_search_mcp/src/service.py` → 43 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

fetch先校验来源引用，再查正文；缓存未命中可按同scope URL复用，否则调用scraper，存回原ID；来源本身不存在才报未知/过期。探针删除所有可复用正文、保留registry后同ID重新取得body。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
