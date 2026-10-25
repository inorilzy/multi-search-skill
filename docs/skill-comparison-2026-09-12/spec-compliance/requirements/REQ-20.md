## REQ-20 — 四个耗时MCP入口共享4槽且满载立即拒绝

> 每个服务进程最多接受 **4 个尚未完成的耗时工具调用**，四个入口共享容量
> — docs/mcp-dispatch.md:L5

**Verdict:** implemented · confidence: high

---

**What this demands of an implementation:** 四个耗时MCP入口共享4槽且满载立即拒绝。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/server.py:L28-L40
# Separate from the provider/fetch pools: cancelled waiters must not free slots
# while their synchronous Core calls are still running.
_TOOL_POOL = BoundedDaemonExecutor(max_workers=4, thread_name_prefix="mcp-tool")


async def _run_tool(fn: Callable[..., dict], *args) -> dict:
    future = _TOOL_POOL.submit_nowait(contextvars.copy_context().run, fn, *args)
    if future is None:
        return {"error": "MCP tool capacity exhausted; retry after active calls finish",
```

```python
# multi_search_mcp/server.py:L148-L166
    return await _run_tool(multi_search_tool, query, route, count, sources, scrape_top, scrape_chars,
                           timeout, scrape_timeout, expand, use_state, output)


@mcp.tool(name="scrape_url")
async def scrape_url(url: str, backends: list[str] | None = None, scrape_chars: int | None = None,
               scrape_timeout: int | None = None, use_state: bool = True,
               output: str = "both") -> dict:
    """Fetch readable page content using state-aware scraper backend ordering.
```

```python
# multi_search_mcp/src/support/concurrency.py:L23-L64
    def __init__(self, *, max_workers: int, thread_name_prefix: str):
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        self._max_workers = max_workers
        self._thread_name_prefix = thread_name_prefix
        self._tasks: queue.Queue = queue.Queue()
        self._slots = threading.BoundedSemaphore(max_workers)
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []
```

**Paths walked:**

search_web/fetch_source/multi_search/scrape_url均走同一个_run_tool；专属pool max_workers=4；semaphore nonblocking admission失败立即返回原格式JSON error。队列对象无size但进入前已占全局slot，因此并非无界可接收队列。未运行真实FastMCP传输，此条静态确认工具注册及pool约束。

**Searched:**

- `rg -n '_TOOL_POOL|_run_tool|submit_nowait' multi_search_mcp/server.py multi_search_mcp/src/support/concurrency.py` → 9 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

search_web/fetch_source/multi_search/scrape_url均走同一个_run_tool；专属pool max_workers=4；semaphore nonblocking admission失败立即返回原格式JSON error。队列对象无size但进入前已占全局slot，因此并非无界可接收队列。未运行真实FastMCP传输，此条静态确认工具注册及pool约束。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
