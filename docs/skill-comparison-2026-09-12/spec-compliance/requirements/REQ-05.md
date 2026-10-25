## REQ-05 — 同 query/provider 重复 URL 仅按最佳名次投票

> 同一 query、同一 provider 的重复 URL 只按最好名次投一票。
> — docs/glossary.md:L70

**Verdict:** implemented · confidence: high

---

**What this demands of an implementation:** 同 query/provider 重复 URL 仅按最佳名次投票。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/src/search/candidate.py:L87-L123
def _candidate_rows(query: str, rows: list[dict]) -> dict[str, dict[str, dict]]:
    """Return one deterministic row per provider/canonical URL."""
    grouped: dict[str, dict[str, dict]] = {}
    ordered = sorted(
        (dict(row) for row in rows),
        key=lambda row: (
            str(row.get("source") or ""),
            int(row["provider_rank"]) if row.get("provider_rank") else float("inf"),
            canonicalize_url(str(row.get("url") or "")),
```

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

**Paths walked:**

_candidate_rows 先规范化URL，再以 provider→canonical URL 保存最小 rank；_fuse_one_query 对每个保留行累加一次。error/answer/无URL/非正rank不会贡献；跨query贡献由第二层保留。探针重复跟踪参数URL仅保留rank20，不让rank80多投票。

**Searched:**

- `rg -n 'grouped|existing|provider_rank' multi_search_mcp/src/search/candidate.py` → 15 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

_candidate_rows 先规范化URL，再以 provider→canonical URL 保存最小 rank；_fuse_one_query 对每个保留行累加一次。error/answer/无URL/非正rank不会贡献；跨query贡献由第二层保留。探针重复跟踪参数URL仅保留rank20，不让rank80多投票。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
