## `_run_tool` in multi_search_mcp/server.py (L33-L40)

**Purpose:** 把同步 Core 调用放入独立有界池，保留 MCP 事件循环。

---

**Inputs & Assumptions:**

- fn/args：服务内注册的 callable 与用户参数，前者 trusted、后者 untrusted；注册入口 server.py L80-L82、L102-L105。
- 前提：提交不等待可用槽位；enforcement：support/concurrency.py L50-L54。
- 前提：异常也回收 worker 槽位；enforcement：support/concurrency.py L105-L106、L121-L125。

---

**Outputs & Effects:**

返回业务 dict 或容量错误；提交工作可继续写 Core 状态（server.py L34-L40）。

---

**Block-by-Block:**

```python
# L34-L40
future = _TOOL_POOL.submit_nowait(contextvars.copy_context().run, fn, *args)
if future is None:
    return {"error": "MCP tool capacity exhausted; retry after active calls finish", "error_type": "runtime_error"}
return await asyncio.wrap_future(future)
```

- **What:** 提交失败立即形成工具错误，成功后等待 Future。
- **Why here:** 准入先于 Core 执行。
- **Assumes:** 槽位释放取决于 worker；concurrency.py L120-L123。
- **Establishes:** 最多 4 个未实际结束调用；server.py L30，concurrency.py L29、L52-L54。
- **Depended on by:** search/fetch/legacy scrape 及 doctor 共用该边界。

---

**Cross-Function Dependencies:**

- `BoundedDaemonExecutor.submit_nowait` (internal)：非阻塞 semaphore，满载返回 None；L50-L54；shutdown 抛错路径 L59-L61。
- `asyncio.wrap_future` (external-black-box)：桥接同步 Future；本轮未读 asyncio 实现，取消协议是外部运行问题。
- Callers: server.py search_web L80、fetch_source L102、multi_search L148、scrape_url L165、doctor L177
- Shared state: _TOOL_POOL；server.py L30
- Invariant coupling: 取消 await 不等于释放正在执行的槽位 (support/concurrency.py L99-L106、L120-L123)

---

**Open Questions:**

- unclear; need to inspect 目标 MCP/asyncio 版本实际取消传播；本轮仅源码，不运行 MCP 会话。
