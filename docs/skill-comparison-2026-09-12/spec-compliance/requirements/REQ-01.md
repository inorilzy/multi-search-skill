## REQ-01 — MCP 与 CLI 搜索调用共享 Core

> MCP 与 CLI 使用同一套搜索、key 状态和 SQLite 缓存
> — README.md:L6

**Verdict:** implemented · confidence: high

---

**What this demands of an implementation:** MCP 与 CLI 搜索调用共享 Core。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/src/service.py:L595-L628
def run_search_web(
    request: SearchWebRequest | dict,
    *,
    providers: dict | None = None,
    keys: dict | None = None,
    config: dict | None = None,
    state_store: StateStore | None = None,
    query_runs_observer: Callable[[list[tuple[str, list[dict]]]], None] | None = None,
    scraper=None,
```

```python
# multi_search_mcp/tools.py:L45-L62
def search_web_tool(
    query: str,
    route: str | None = None,
    count: int | None = None,
    sources: list[str] | None = None,
    timeout: int | None = None,
    expand: list[str] | None = None,
    use_state: bool = True,
) -> dict[str, Any]:
```

```python
# multi_search_mcp/cli.py:L145-L154
def _handle_search(args: argparse.Namespace) -> dict[str, Any]:
    return run_search_web(
        SearchWebRequest(
            query=args.query,
            route=args.route,
            count=args.count,
            sources=list(args.sources or []),
            timeout=args.timeout,
            expand=None if args.expand is None else list(args.expand),
```

```python
# multi_search_mcp/server.py:L80-L83
    return await _run_tool(
        search_web_tool,
        query, route, count, sources, timeout, expand, use_state
    )
```

**Paths walked:**

CLI _handle_search → service.run_search_web；server.search_web → _run_tool → tools.search_web_tool → 同一 run_search_web。tools._safe_call 将 ValueError/Exception 分类，CLI main 将异常转换退出码；本条只判共享调用路径，参数逐个版本兼容不在此条。

**Searched:**

- `rg -n 'run_search_web|search_web_tool' multi_search_mcp/src/service.py multi_search_mcp/tools.py multi_search_mcp/cli.py multi_search_mcp/server.py` → 9 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

CLI _handle_search → service.run_search_web；server.search_web → _run_tool → tools.search_web_tool → 同一 run_search_web。tools._safe_call 将 ValueError/Exception 分类，CLI main 将异常转换退出码；本条只判共享调用路径，参数逐个版本兼容不在此条。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
