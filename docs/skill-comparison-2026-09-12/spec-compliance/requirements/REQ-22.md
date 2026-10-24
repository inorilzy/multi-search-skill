## REQ-22 — key选择优先未使用其次最久未用

> 按「未用过优先 → 最久未用（LRU）」挑选。
> — docs/glossary.md:L81

**Verdict:** implemented · confidence: high

---

**What this demands of an implementation:** key选择优先未使用其次最久未用。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/src/state/key_state.py:L125-L171
    def candidates(self, provider: str, key_value: Any) -> list[KeyCandidate]:
        raw = [
            KeyCandidate(key=key, key_id=key_id_for(provider, key), fingerprint=key_fingerprint(key))
            for key in _ordered_key_pool(key_value)
        ]
        now = _now()
        rows = {
            row["key_id"]: row
            for row in self.store.rows(
```

```python
# multi_search_mcp/src/search/search_runner.py:L255-L268
    candidates = manager.candidates(provider, key_value)
    if not candidates:
        if key_value and not key_required:
            return [{"source": source, "error": "no usable API keys"}]
        return missing(source, "missing API key")
    last_results: list[dict] = []
    partial_rows: list[dict] = []
    for idx, candidate in enumerate(candidates):
        if deadline is not None and time.monotonic() >= deadline:
```

```python
# multi_search_mcp/src/scrape/scrape.py:L109-L123
def _scrape_with_key_pool(provider: str, keys: list[str], call, deadline: float | None = None, key_manager=None) -> dict | None:
    last: dict | None = None
    for key in keys:
        if deadline is not None and time.monotonic() >= deadline:
            break
        if key_manager is not None:
            key_manager.record_use(provider, _candidate_for(provider, key))
        result = call(key)
        _record_key_result(provider, key, result, key_manager)
```

**Paths walked:**

candidates按never_used/last_used_at/配置顺序排序；search与scrape在真正尝试前调用record_use递增次数、记录时刻。候选列表预取本身不算使用；并发请求可能取到同一key，不在文档中加上未承诺的互斥租约要求。探针用a后选择未使用b。

**Searched:**

- `rg -n 'never_used|last_used_at|record_use' multi_search_mcp/src/state/key_state.py multi_search_mcp/src/search/search_runner.py multi_search_mcp/src/scrape/scrape.py` → 9 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

candidates按never_used/last_used_at/配置顺序排序；search与scrape在真正尝试前调用record_use递增次数、记录时刻。候选列表预取本身不算使用；并发请求可能取到同一key，不在文档中加上未承诺的互斥租约要求。探针用a后选择未使用b。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
