## REQ-19 — 正文超时保留排名结果及显式失败

> 超时会保留 RRF 结果并显式报告正文失败。
> — README.md:L416

**Verdict:** implemented · confidence: high

---

**What this demands of an implementation:** 正文超时保留排名结果及显式失败。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/src/scrape/stage.py:L30-L96
    deadline = time.monotonic() + timeout
    results: list[dict | None] = [None] * len(hits)
    active: dict[Future, int] = {}
    next_index = 0

    def error_row(hit: dict, error: Any) -> dict:
        return {
            "source_id": hit.get("source_id", ""),
            "url": hit.get("url", ""),
```

```python
# multi_search_mcp/src/service.py:L649-L687
    fetched = run_ranked_fetch_stage(
        response["results"], fetch=fetch, timeout=body_timeout, concurrency=concurrency,
    )
    scrapes = []
    for hit, body_result in zip(response["results"], fetched["results"]):
        page = normalize_scrape_result({
            "title": hit["title"], "markdown": body_result.get("body"),
            "length": body_result.get("content_length"),
            "truncated": bool(body_result.get("truncated")),
```

**Paths walked:**

stage固定槽位按hit输入顺序收集；已完成成功保留，pending/未提交返回timeout行，晚返回也不伪装成功；service将body_error和errors stage=fetch填回而不重排结果。离线一快一慢示例约0.04s返回、原顺序保留且第二项显式错误。

**Searched:**

- `rg -n 'timeout_row|results|future.cancel' multi_search_mcp/src/scrape/stage.py multi_search_mcp/src/service.py` → 44 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

stage固定槽位按hit输入顺序收集；已完成成功保留，pending/未提交返回timeout行，晚返回也不伪装成功；service将body_error和errors stage=fetch填回而不重排结果。离线一快一慢示例约0.04s返回、原顺序保留且第二项显式错误。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
