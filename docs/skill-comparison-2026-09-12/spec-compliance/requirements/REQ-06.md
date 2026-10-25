## REQ-06 — 两级 RRF 无中间截断且最终最多15

> Expanded queries fuse in two stages:
> — skills/multi-search/references/search.md:L55

**Verdict:** implemented · confidence: high

---

**What this demands of an implementation:** 两级 RRF 无中间截断且最终最多15。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/src/search/candidate.py:L216-L229
def _fuse_one_query(
    query: str, rows: list[dict]
) -> tuple[dict[str, list[tuple[str, dict]]], dict[str, float], list[str]]:
    provider_rows = _candidate_rows(query, rows)
    by_url: dict[str, list[tuple[str, dict]]] = {}
    scores: dict[str, float] = {}
    for provider in sorted(provider_rows):
        for canonical_url, row in provider_rows[provider].items():
            by_url.setdefault(canonical_url, []).append((provider, row))
```

```python
# multi_search_mcp/src/search/candidate.py:L249-L287
    per_query = [
        (query, *_fuse_one_query(query, rows)) for query, rows in query_runs
    ]
    if len(per_query) == 1:
        _query, by_url, provider_scores, ordered_urls = per_query[0]
        return [
            _public_hit(
                response_id=response_id,
                canonical_url=url,
```

```python
# multi_search_mcp/src/service.py:L440-L445
    response_id = f"resp_{uuid.uuid4().hex}"
    limit = SEARCH_RESULT_LIMIT
    hits = fuse_search_results(
        query_runs, response_id=response_id, limit=limit,
        primary_query=query_plan.primary_query, query_policy=query_policy,
    )
```

**Paths walked:**

每 query _fuse_one_query 返回全部 ordered_urls；多query对全部列表 enumerate、默认权重1，再只在最终列表切片。单query也只在最终切片。离线例中首query rank20因第二query支持进入第一名。原生score仅附在diagnostic provider_ranks，不参与加分。

**Searched:**

- `rg -n 'RRF_RANK_CONSTANT|ordered_urls|limit' multi_search_mcp/src/search/candidate.py multi_search_mcp/src/service.py` → 35 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

每 query _fuse_one_query 返回全部 ordered_urls；多query对全部列表 enumerate、默认权重1，再只在最终列表切片。单query也只在最终切片。离线例中首query rank20因第二query支持进入第一名。原生score仅附在diagnostic provider_ranks，不参与加分。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
