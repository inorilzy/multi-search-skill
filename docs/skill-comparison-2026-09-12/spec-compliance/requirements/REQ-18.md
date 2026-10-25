## REQ-18 — 搜索timeout是整批共享deadline

> 搜索阶段整批 deadline
> — README.md:L339

**Verdict:** implemented · confidence: medium

---

**What this demands of an implementation:** 搜索timeout是整批共享deadline。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/src/service.py:L402-L422
    search_deadline = time.monotonic() + plan.timeout
    if len(queries) == 1:
        query_results[queries[0]] = runner.run(queries[0], deadline=search_deadline)
    else:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(queries), MAX_EXPAND_CONCURRENCY)
        ) as pool:
            futures = {
                pool.submit(runner.run, query, deadline=search_deadline): query
```

```python
# multi_search_mcp/src/search/search_runner.py:L302-L328
    def run(self, query: str, *, deadline: float | None = None) -> list[dict]:
        results: list[dict] = []
        jobs: list[tuple[str, Callable[[], list]]] = []
        source_names = self.route_resolver(self.config.route)
        timeout_seconds = max(0, self.config.timeout if self.config.timeout is not None else 60)
        source_deadline = time.monotonic() + timeout_seconds
        if deadline is not None:
            source_deadline = min(source_deadline, deadline)
        partial_results: dict[str, list[dict]] = {}
```

```python
# multi_search_mcp/src/search/search_runner.py:L366-L407
        pending = {name for name, _ in jobs}
        future_sources: dict[Future, str] = {}
        for name, call in jobs:
            future = _SEARCH_POOL.submit_before(source_deadline, call)
            if future is not None:
                future_sources[future] = name

        while future_sources:
            done = {future for future in future_sources if future.done()}
```

```python
# multi_search_mcp/src/support/concurrency.py:L36-L48
    def submit_before(
        self,
        deadline: float,
        fn: Callable[..., Any],
        /,
        *args,
        **kwargs,
    ) -> Future | None:
        remaining = deadline - time.monotonic()
```

**Paths walked:**

所有expanded query共享service创建的绝对deadline；runner取min，提交池等待、provider context、结果等待都用同一时点。超时保留已publish_partial、为pending写timeout。运行中的线程可能继续，不把返回deadline解释成停止所有底层socket。未逐provider模拟慢DNS/所有SDK边界，因此confidence medium。

**Searched:**

- `rg -n 'search_deadline|source_deadline|submit_before' multi_search_mcp/src/service.py multi_search_mcp/src/search/search_runner.py multi_search_mcp/src/support/concurrency.py` → 13 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

所有expanded query共享service创建的绝对deadline；runner取min，提交池等待、provider context、结果等待都用同一时点。超时保留已publish_partial、为pending写timeout。运行中的线程可能继续，不把返回deadline解释成停止所有底层socket。未逐provider模拟慢DNS/所有SDK边界，因此confidence medium。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
