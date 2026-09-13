# MCP 入口调度

`server.py` 的 `search_web`、`multi_search`、`fetch_source`、`scrape_url` 和 `doctor` 是异步入口；它们通过专属的 `BoundedDaemonExecutor` 在工作线程中调用同步 `tools.py` / Core。7 个会触及 SQLite 状态的入口（`read_source`、`list_sources` 的两个状态开关、`get_key_status`、`reset_key_state`、`get_site_scraper_stats`、`set_site_scraper_preference`、`reset_site_scraper_stats`）也复用同一个调度池。普通 `list_sources`、`read_source(use_state=False)` 和无效 scraper 参数保留事件循环内的快速路径；CLI 仍直接调用同步 Core。

每个服务进程最多接受 **4 个进入该调度池且尚未完成的工具调用**；12 个 MCP 入口的耗时/状态路径共享容量，普通 `list_sources`、`read_source(use_state=False)` 和无效 scraper 参数的快速路径不占用容量。不使用 asyncio 默认线程池，也不建立无界等待队列。满载时立即返回原有格式的 `{"error": "MCP tool capacity exhausted; retry after active calls finish", "error_type": "runtime_error"}`。该错误与已有 Core 错误一样放在工具的 JSON 内容中；没有新增参数、工具名或 MCP 协议错误类型。

MCP 取消通知可以在耗时调用期间被处理。取消 await 会尝试取消尚未开始的工作；**不能终止已经运行的 Python 线程或网络请求**。运行中的 Core 继续执行，并可能完成缓存/状态写入；实际返回前始终占用调度槽位。连续取消不会腾出容量来启动无限后台工作。daemon 工作线程不会阻止服务进程退出。

这层调度不改变 Core 的搜索/抓取 deadline、超时后的部分成功结果、provider/fetch 全局执行池或其容量。Core 预算仍在实际执行时计算；入口满载立即拒绝，所以没有额外的排队等待预算。状态 SQLite I/O 同样不在事件循环中执行。现有底层取消/超时边界仍适用；取消与状态写入的边界是：等待被取消后，已经运行的状态任务仍可能完成写入，并继续占用槽位直到真正返回。

验证入口：`python -m unittest tests.test_mcp_dispatch_concurrency -v`。测试用事件保持慢 Core 或 SQLite 写锁未完成，通过真实 FastMCP 调度检查轻量调用；覆盖 7 个状态入口（含 `list_sources` 两种状态开关）的锁竞争、无状态/无效参数对照、四个耗时入口、满载拒绝、取消后容量保留和实际结束后的容量恢复；通过 MCP 内存传输的 ClientSession/ServerSession 检查真实取消通知和工具错误。网络均模拟。
