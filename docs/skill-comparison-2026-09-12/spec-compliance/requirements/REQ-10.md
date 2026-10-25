## REQ-10 — 旧 scrape_top 不再裁剪最终抓取列表

> `scrape_top` no longer selects how many URLs to fetch.
> — skills/multi-search/references/search.md:L67

**Verdict:** implemented · confidence: high

---

**What this demands of an implementation:** 旧 scrape_top 不再裁剪最终抓取列表。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/src/service.py:L697-L714
def run_multi_search(request: MultiSearchRequest | dict) -> dict:
    """Compatibility presentation of the shared RRF search-and-fetch flow."""
    if isinstance(request, dict):
        request = MultiSearchRequest(**request)
    config = _load_config_safe(request.config_path)
    plan = resolve_search_plan(request, config)
    query_runs = []
    response = run_search_web(
        SearchWebRequest(
```

```python
# multi_search_mcp/src/service.py:L734-L757
    if request.scrape_top is not None or request.scrape_per_source is not None:
        response["diagnostics"]["legacy_scrape_limits"] = (
            "scrape_top and scrape_per_source no longer limit fetching; "
            "all final RRF results (at most 15) are fetched"
        )
    if plan.output_mode in {"markdown", "both"}:
        raw_counts = {}
        for row in rows:
            if row.get("url") and not row.get("error") and not is_empty_result(row):
```

```python
# multi_search_mcp/src/service.py:L649-L651
    fetched = run_ranked_fetch_stage(
        response["results"], fetch=fetch, timeout=body_timeout, concurrency=concurrency,
    )
```

**Paths walked:**

run_multi_search 包装 run_search_web；传正文预览/超时/并发，但不以scrape_top裁剪response.results。最终list整体交fetch stage。显式旧参数只产生diagnostic；markdown/both输出仅移除scrapes中的重复正文副本。负旧参数仍被输入验证，未声称任意旧参数值都接受。

**Searched:**

- `rg -n 'scrape_top|legacy_scrape_limits|run_ranked_fetch_stage' multi_search_mcp/src/service.py` → 8 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

run_multi_search 包装 run_search_web；传正文预览/超时/并发，但不以scrape_top裁剪response.results。最终list整体交fetch stage。显式旧参数只产生diagnostic；markdown/both输出仅移除scrapes中的重复正文副本。负旧参数仍被输入验证，未声称任意旧参数值都接受。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
