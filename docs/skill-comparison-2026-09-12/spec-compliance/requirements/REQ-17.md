## REQ-17 — use_state=false跳过SQLite及站点记忆

> `false` 时跳过 SQLite 状态、key 轮换、站点记忆
> — docs/glossary.md:L88

**Verdict:** implemented · confidence: high

---

**What this demands of an implementation:** use_state=false跳过SQLite及站点记忆。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/src/service.py:L190-L195
    if bool(request.source_id) == bool(request.url):
        raise ValueError("provide exactly one of source_id or url")
    if not request.use_state and request.source_id and source_record is None:
        raise ValueError("source_id fetch requires state; provide an explicit URL")

    store = (state_store or StateStore()) if request.use_state else None
```

```python
# multi_search_mcp/src/service.py:L366-L368
    runtime_keys = load_keys() if keys is None else dict(keys)
    store = (state_store or StateStore()) if request.use_state else None
    key_manager = SQLiteKeyManager(store) if store else BasicKeyManager()
```

```python
# multi_search_mcp/src/service.py:L621-L622
    runtime_keys = load_keys() if keys is None else dict(keys)
    store = (state_store or StateStore()) if request.use_state else None
```

```python
# multi_search_mcp/src/service.py:L804-L823
    store = (state_store or StateStore()) if request.use_state else None
    key_manager = SQLiteKeyManager(store) if store else BasicKeyManager()
    site_memory = SiteScraperMemory(store) if store else None
    scraper_fn = scraper or scrape_url_smart
    result = scraper_fn(
        request.url,
        timeout=timeout,
        deadline=deadline,
        backends=tuple(request.backends) if request.backends else None,
```

```python
# multi_search_mcp/src/state/key_state.py:L73-L116
class BasicKeyManager:
    """Compatibility key manager using the existing random key pool."""

    def candidates(self, provider: str, key_value: Any) -> list[KeyCandidate]:
        return [
            KeyCandidate(key=key, key_id=key_id_for(provider, key), fingerprint=key_fingerprint(key))
            for key in _ordered_key_pool(key_value)
        ]

```

**Paths walked:**

search/fetch/scrape由开关决定store=None、BasicKeyManager和site_memory=None；Basic无DB写入，固定key候选不做持久LRU。按IDfetch无state且无内部source_record时拒绝，read无state拒绝。端到端探针将默认StateStore构造设为异常，搜索prefetch依然成功。

**Searched:**

- `rg -n 'request.use_state|BasicKeyManager|site_memory' multi_search_mcp/src/service.py multi_search_mcp/src/state/key_state.py` → 19 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

search/fetch/scrape由开关决定store=None、BasicKeyManager和site_memory=None；Basic无DB写入，固定key候选不做持久LRU。按IDfetch无state且无内部source_record时拒绝，read无state拒绝。端到端探针将默认StateStore构造设为异常，搜索prefetch依然成功。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
