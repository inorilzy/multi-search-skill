## REQ-21 — MCP取消不能提前释放正在运行任务容量

> 实际返回前始终占用调度槽位。
> — docs/mcp-dispatch.md:L7

**Verdict:** implemented · confidence: high

---

**What this demands of an implementation:** MCP取消不能提前释放正在运行任务容量。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/server.py:L33-L40
async def _run_tool(fn: Callable[..., dict], *args) -> dict:
    future = _TOOL_POOL.submit_nowait(contextvars.copy_context().run, fn, *args)
    if future is None:
        return {"error": "MCP tool capacity exhausted; retry after active calls finish",
                "error_type": "runtime_error"}
    # Cancels queued work if possible, but cannot stop a running thread/network
    # call. The executor retains its slot until actual completion.
    return await asyncio.wrap_future(future)
```

```python
# multi_search_mcp/src/support/concurrency.py:L98-L125
    @staticmethod
    def _execute_task(task) -> None:
        future, fn, args, kwargs = task
        if not future.set_running_or_notify_cancel():
            return
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:
            future.set_exception(exc)
```

**Paths walked:**

await包裹concurrent Future，取消只能在set_running前成功；正在运行Future不能cancel。worker finally在fn结束后释放slot，异常同样释放。离线单槽事件探针证明运行中cancel=False且新提交拒绝，放行实际结束后可退出。未把此probe称为真实MCP取消协议验收。

**Searched:**

- `rg -n 'wrap_future|set_running_or_notify_cancel|_slots.release' multi_search_mcp/server.py multi_search_mcp/src/support/concurrency.py` → 5 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

await包裹concurrent Future，取消只能在set_running前成功；正在运行Future不能cancel。worker finally在fn结束后释放slot，异常同样释放。离线单槽事件探针证明运行中cancel=False且新提交拒绝，放行实际结束后可退出。未把此probe称为真实MCP取消协议验收。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
