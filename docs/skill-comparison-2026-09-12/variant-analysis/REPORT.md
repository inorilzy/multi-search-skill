# variant-analysis 实用试审

基线 `eb2d5cdeb222b52060c4509c45a22aff4ce911fa`。评价：对这次“修一处、漏同类”的问题最直接有用；它需要已知根因，不能代替最初发现问题的审查。本轮没有确认新的线上故障。

## 已核实的同类问题

**P2，同一修复族：同步 MCP 状态入口在 SQLite 写锁下阻塞事件循环。** 精确种子为 `multi_search_mcp/server.py:181` 的 `get_key_status`，随后扩展到所有 12 个工具。7 个工具有同步且触及状态的路径：`read_source`、`list_sources`、`get_key_status`、`reset_key_state`、`get_site_scraper_stats`、`set_site_scraper_preference`、`reset_site_scraper_stats`。另 5 个工具经既有 `_run_tool` 分发。

离线持有写锁 0.30 秒时，真实 FastMCP `Tool.run` 的同步状态路径会把 25ms 定时回调推迟至约 0.3 秒；普通 `list_sources`、`read_source(use_state=False)` 和无效 scraper 参数则及时返回。`list_sources` 两种状态开关分别验证。它们合并为一个问题族，6 个种子外入口不是 6 个独立根因；此前第三轮报告已经描述此族，不能记为首次发现。

位置集中于 `multi_search_mcp/server.py:109,169,181,187,193,199,206`；实际行号以 `coverage.json` 的 AST 清单为准。调用链经过 `tools.py`/`service.py` 创建 `StateStore`，日常连接初始化也会申请迁移写锁。修复方向是复用既有有界分发，保留纯无状态路径；对照测试应在持锁时检查事件循环和取消处理仍能运行。

## 条件性变体，保留证据边界

`multi_search_mcp/src/scrape/scrapers/jina.py:150-153` 与 `firecrawl.py:40-43` 会把空正文响应中的目标网页 warning 变成普通错误，不保留 `error_origin=target`。合成 HTTP 200、空正文、包含 403 的目标 warning，通过真实 adapter 和临时 SQLite 后，三次相隔 16 分钟的报告会把合成 key 从 `transient_invalid/1` 升为永久 `invalid/3`。Exa/Tavily 的目标错误对照保持 active，Jina HTTP429 对照保持 cooldown。

这是**本地条件性行为已复现**，并未证明当前服务会返回该完整组合。Jina 上游 issue [#1226](https://github.com/jina-ai/reader/issues/1226) 能证明 200 响应存在目标 403 warning，但该样本带有非空 text，不能直接当作本探针的触发样本。[Firecrawl 接口文档](https://docs.firecrawl.dev/api-reference/endpoint/scrape)也不能证明本探针的具体 warning 文本。两处列为待补协议样本的候选，不把它们升级为新增确定缺陷。

Brave、Parallel、Baidu、Exa、Firecrawl、SerpAPI、Tavily 的合成 HTTP403 限流实验同样只能证明条件性错误分类；未核实各家真实协议确实如此返回，因此不凭字符串化模式一律报错。匿名 provider 和 Twitter cookies 路径不能直接套用 API-key 健康状态结论。

## 方法执行与复核

- 读取已安装 skill 的根因、搜索、裁决、报告四份参考，采用其允许的直接五步骤。原版 Workflow 未执行。
- `search-log.json` 保留主代理重跑的精确种子、逐步泛化、warning 变体、target-origin 反例查询及全部命中裁决；`coverage.json` 列出 12 个 MCP 工具。
- 子代理生成首版探针后被平台内容检查中止，主代理接手。首版 GitHub 探针误把 key 传给 count，安全拦截阻止了其 `gh` 路径。已改为 `token=key` 并加入种子/对照断言；原结果不作为 GitHub 复现证据。
- 最终复跑 13 组错误场景与 11 组 MCP 调用。临时 SQLite、合成凭据；真实 HTTP/DNS/外部进程被拒绝。使用仅支持定时器/任务的事件循环，未覆盖真实 MCP stdio/网络传输。
- 建议把“状态锁竞争下的 MCP 心跳”和“目标错误不改变已有 key 健康”固化为行为回归；泛用 grep 规则只作候选提示，不能自动判 bug。本次未改测试或 CI。

验证命令：`.venv/Scripts/python.exe -B -X utf8 .scratch/skill-comparison-20260912/variants/probe.py`。探针源码与结果在本仓库中，运行会重写本目录 `probe-results.json`。

停止边界：已将全部 MCP 工具和匹配到的 keyed adapter 分支分类；未确认的 provider 协议保留待查。本次没有证明全部根因变体已穷尽，也没有检查其他缺陷类别。价值在于把同类入口集中盘点与设置反例，不能承诺一次查全。
