## REQ-07 — 候选摘要与正文各自保留

> 排序入选后可附带正文预览，摘要与正文各自保留。
> — CONTEXT.md:L7

**Verdict:** implemented · confidence: high

---

**What this demands of an implementation:** 候选摘要与正文各自保留。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/src/support/models.py:L59-L78
def search_content(row: dict) -> SearchContent:
    """Interpret legacy provider fields once for candidate output and caching.

    Some adapters also put highlights in scraped_content. Only body/content
    rows contain bodies; a body row can independently carry a description.
    """
    kind = normalize_content_kind(row.get("content_kind"))
    body = (
        str(row.get("scraped_content") or "")
```

```python
# multi_search_mcp/src/search/candidate.py:L143-L162
    content_rows = []
    for provider, row in contributions:
        content = search_content(row)
        if content.snippet.strip():
            content_rows.append((provider, row, content))
    if content_rows:
        _content_provider, _content_row, content = sorted(
            content_rows,
            key=lambda item: (
```

```python
# multi_search_mcp/src/service.py:L653-L676
    for hit, body_result in zip(response["results"], fetched["results"]):
        page = normalize_scrape_result({
            "title": hit["title"], "markdown": body_result.get("body"),
            "length": body_result.get("content_length"),
            "truncated": bool(body_result.get("truncated")),
            "error": body_result.get("error"),
        }, url=hit["url"], via=body_result.get("backend") or "")
        page["source_id"] = hit["source_id"]
        scrapes.append(page)
```

**Paths walked:**

search_content 从 body/content类型取 scraped_content，同时保留独立 description；candidate仅存snippet，run_search_web将body放scrapes并按source_id关联，失败写body_error且不删除snippet。端到端离线模拟验证snippet与1200字body分离。

**Searched:**

- `rg -n 'search_content|markdown|content' multi_search_mcp/src/support/models.py multi_search_mcp/src/search/candidate.py multi_search_mcp/src/service.py` → 107 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

search_content 从 body/content类型取 scraped_content，同时保留独立 description；candidate仅存snippet，run_search_web将body放scrapes并按source_id关联，失败写body_error且不删除snippet。端到端离线模拟验证snippet与1200字body分离。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
