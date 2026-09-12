# MCP 入口调度

`server.py` 的 `search_web`、`multi_search`、`fetch_source`、`scrape_url` 是异步入口；它们通过专属的 `BoundedDaemonExecutor` 在工作线程中调用同步 `tools.py` / Core。`list_sources` 等本地轻量工具继续由 MCP 直接调度。CLI 仍直接调用同步 Core。

每个服务进程最多接受 **4 个尚未完成的耗时工具调用**，四个入口共享容量；不使用 asyncio 默认线程池，也不建立无界等待队列。满载时立即返回原有格式的 `{"error": "MCP tool capacity exhausted; retry after active calls finish", "error_type": "runtime_error"}`。该错误与已有 Core 错误一样放在工具的 JSON 内容中；没有新增参数、工具名或 MCP 协议错误类型。

MCP 取消通知可以在耗时调用期间被处理。取消 await 会尝试取消尚未开始的工作；**不能终止已经运行的 Python 线程或网络请求**。运行中的 Core 继续执行，并可能完成缓存/状态写入；实际返回前始终占用调度槽位。连续取消不会腾出容量来启动无限后台工作。daemon 工作线程不会阻止服务进程退出。

这层调度不改变 Core 的搜索/抓取 deadline、超时后的部分成功结果、provider/fetch 全局执行池或其容量。Core 预算仍在实际执行时计算；入口满载立即拒绝，所以没有额外的排队等待预算。现有底层取消/超时边界仍适用。

验证入口：`python -m unittest test_mcp_dispatch_concurrency -v`。测试用事件保持慢 Core 未完成，通过真实 FastMCP 调度检查轻量调用；通过 MCP 内存传输的 ClientSession/ServerSession 检查取消通知、工具错误；同时检查四个耗时入口、满载拒绝、取消后容量保留和实际结束后的容量恢复。网络均模拟。
