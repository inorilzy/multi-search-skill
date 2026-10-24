## REQ-14 — full_content 覆盖max_chars并保留取得的全部正文

> 设为 `True` 时覆盖 `max_chars`，一次返回全部已取得文本。
> — README.md:L345

**Verdict:** implemented · confidence: high

---

**What this demands of an implementation:** full_content 覆盖max_chars并保留取得的全部正文。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/src/service.py:L228-L268
    max_chars = None if request.full_content else max(1, min(int(request.max_chars), 20_000))

    content_store = ContentStore(store, ttl_seconds=retention.max_ttl_seconds) if store is not None else None
    cached = content_store.get(source_id) if content_store and source_id else None
    if cached is not None and not retention.persist_body:
        content_store.delete_source(source_id)
        cached = None
    cache_scope = ""
    resolved_config = None
```

```python
# multi_search_mcp/src/service.py:L278-L315
                # Preview size must not truncate the cached acquisition.
                scrape_chars=DEFAULT_MAX_OBJECT_BYTES,
                timeout=request.timeout,
                output="json",
                use_state=request.use_state,
            ),
            state_store=store,
            scraper=scraper,
            keys=runtime_keys,
```

```python
# multi_search_mcp/src/state/content_store.py:L55-L69
        payload = content.encode("utf-8")
        content_bytes = len(payload)
        if content_bytes > self.max_object_bytes:
            raise ContentStoreError(
                f"content size {content_bytes} exceeds max object bytes {self.max_object_bytes}"
            )
        if content_bytes > self.max_total_bytes:
            raise ContentStoreError(
                f"content size {content_bytes} exceeds max total bytes {self.max_total_bytes}"
```

**Paths walked:**

full_content将切片上限设None，缓存命中和新抓取均使用相同变量。原body先进行容量检查与put，再裁剪响应；超过容量抛错不静默截缓存。5510字探针先7字预览，再max_chars=1/full_content=True返回5510字。

**Searched:**

- `rg -n 'full_content|max_chars|content_store.put' multi_search_mcp/src/service.py multi_search_mcp/src/state/content_store.py` → 17 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

full_content将切片上限设None，缓存命中和新抓取均使用相同变量。原body先进行容量检查与put，再裁剪响应；超过容量抛错不静默截缓存。5510字探针先7字预览，再max_chars=1/full_content=True返回5510字。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
