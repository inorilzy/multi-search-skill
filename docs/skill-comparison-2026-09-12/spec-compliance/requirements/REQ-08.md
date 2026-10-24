## REQ-08 — 预取正文按长度/provider/文本确定性选择

> 字符数最长优先，等长时依次按 provider 名、正文文本升序选择
> — docs/glossary.md:L59

**Verdict:** implemented · confidence: high

---

**What this demands of an implementation:** 预取正文按长度/provider/文本确定性选择。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/src/service.py:L468-L499
    # Select once for both persistence and fetching, independently of use_state.
    # Longest body wins; ties use source then body text in ascending order.
    bodies: dict[str, tuple[int, str, str]] = {}
    for _query, query_rows in query_runs:
        for row in query_rows:
            body = search_content(row).body
            if not body or not row.get("url") or row.get("error"):
                continue
            url = canonicalize_url(str(row["url"]))
```

```python
# multi_search_mcp/src/service.py:L623-L643
    prefetched = {}
    response = _run_search_candidates(
        request, providers=providers, keys=runtime_keys, config=resolved_config,
        state_store=store, query_runs_observer=query_runs_observer,
        prefetched_bodies=prefetched,
    )
    max_chars = max(1, min(_resolve_int(scrape_chars, resolved_config, "scrape_chars", 1200), 20_000))
    body_timeout = _resolve_nonnegative(scrape_timeout, resolved_config, "scrape_timeout", 60)
    concurrency = max(1, _resolve_int(scrape_concurrency, resolved_config, "scrape_concurrency", 5))
```

**Paths walked:**

_run_search_candidates 为所有原始行按canonical URL选择(-len,source,body)最小tuple；错误/无URL/无body跳过。选择发生于use_state分支外，同一map用于可选缓存及fetch。字符串等长tie不是依赖到达顺序。

**Searched:**

- `rg -n 'selected_bodies|candidate =|prefetched' multi_search_mcp/src/service.py` → 14 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

_run_search_candidates 为所有原始行按canonical URL选择(-len,source,body)最小tuple；错误/无URL/无body跳过。选择发生于use_state分支外，同一map用于可选缓存及fetch。字符串等长tie不是依赖到达顺序。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
