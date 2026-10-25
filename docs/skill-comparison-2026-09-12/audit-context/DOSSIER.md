# audit-context-building 首轮上下文档案

固定源码：`eb2d5cdeb222b52060c4509c45a22aff4ce911fa`。这是 **Codex 子代理适配试用**：已读取原版 SKILL、ANALYSIS_FORMAT、DOMAIN_NOTES、function-analyzer 与 workflow；没有 Workflow 工具，没有原版逐函数 agent 扇出，也没有运行时 schema 强制。`records.json` 对照原版 RECORD_SCHEMA 手工构造并做字段检查；这不等于原版执行。

本轮目标是建立约束与状态流，未做漏洞判断、等级、修复或运行测试。没有联网、读取实际 key/cookie 或打开默认 SQLite。已有历史审查报告保持未读；memory 快速检索只作为工作区定位线索，以下源码事实均在固定 HEAD 重查，未引用旧发现。

## 范围与可见性

AST 清单包含 `multi_search_mcp/` 的 60 个 Python 文件（含空 `__init__.py`）；逐函数深查 10 个，其他已读函数只作为调用链依赖，不因此算作深查。31 个文件至少读过相关源码区段。完整状态见 [coverage.json](coverage.json)，紧凑索引见 [records.json](records.json)，时间/数量见 [metrics.json](metrics.json)。`startedUTC` 从成功 AST 清单开始计时，未涵盖更早的技能阅读与初始定位；不能当作完整成本。

选取主链：MCP/CLI → Core search/fetch/read → Brave 搜索、Exa 抓取 → HTTP/deadline → key_state、source reference、body cache。配置/路由/融合在此链上读作依赖。其余 provider 的网络行为、Reddit/eddrit、Jina/Tavily/Firecrawl 抓取内部、snapshot/evaluation、部署宿主权限、第三方框架/标准库内部不在本轮深查结论内。

## 谁能进入，数据属于谁

|参与者/数据|入口与到达路径|信任与状态|
|---|---|---|
|本地 CLI 调用者|`cli.py` L145-L180 直接调用同步 Core；异常与 exit code 在 L104-L134|用户 query/URL/offset 为输入；运行身份与 OS 权限未验证|
|MCP 调用者|`server.py` L80、L102、L148、L165、L177 经 `_run_tool`，`tools.py` L36-L43 转换异常|search/fetch/legacy/doctor 共用 4 槽；轻量 read 入口 `server.py` L109-L117 不经该池|
|搜索/抓取服务|Brave `searchers/brave.py` L23-L42；Exa `scrapers/exa.py` L20-L34|上游返回为不可信数据；候选/正文有 `untrusted_content=True`，`candidate.py` L206、`service.py` L267/L316|
|配置与凭据提供者|`config.py` L44-L63；`keys.py` L112-L138|加载器源码已读，实际配置/secret 值未读；运行 key 只传给相关 API/健康管理|
|本地持久状态|`state_store.py` L144-L160 建立 DB 连接并提交/回滚|SQLite 同时存 key 健康、来源映射、正文引用/对象、站点统计；不是单一搜索结果缓存|

## 五条跨函数约束

### 1. deadline、取消、状态副作用是三个不同边界

候选阶段在 `service.py` L402 建立 search deadline；正文阶段在 L630/L649 使用独立 body timeout，`stage.py` L30 才建立本阶段 deadline。不能把 search timeout 解释成整个 search+body 响应的统一预算。

MCP 取消等待不会释放仍在运行的 worker 槽：`server.py` L34-L40 → `concurrency.py` L101-L106、L120-L123。正文 callback 完成后才检查 deadline（`stage.py` L49-L51），而 callback 内 `service.py` L296-L304 已可写缓存。因此“响应报超时”和“本次没有写状态”不是同一事实。这是后续并发实验必须保留的状态模型。

源码当前有五个经 `_run_tool` 的入口（`server.py` L80、L102、L148、L165、L177，包括 doctor）；`docs/mcp-dispatch.md` 描述四个主业务入口。这里只并列记录，未推断文档差异的影响。

### 2. 同一来源存在三种身份，缓存权限由两层分工

`response_id + canonical_url → source_id` 由 `candidate.py` L73-L77 建立；正文按 UTF-8 的 SHA-256 去重（`content_store.py` L55-L69）；跨 source_id 复用按 `canonical_url + cache_scope` 查询（L113）。这三者不能互换。

`run_fetch_source` 首先按 source_id 取缓存（`service.py` L231），未命中才在当前 retention 许可下构造 providers/backends/keys scope（L244-L254）。`ContentStore.reuse_for_url` 本身只检查非空与相等；业务许可由调用者建立。多 provider retention 取布尔交集与最短 TTL（`capabilities.py` L349-L365）。调用连续性在这里比仅看缓存 SQL 更有价值。

### 3. 预览上限、采集上限、缓存字节上限各司其职

搜索抓取闭包用 `full_content=True`（`service.py` L637），fetch 先保存再切输出（L296-L308）；搜索预览最后才按原文 offset 切片（L666-L671）。正文是否存在由 `models.py` L65-L78 的 content kind 决定，Brave 摘要声明 excerpt/metadata（`brave.py` L52-L63），不是以长度推断。

`ContentStore.put` 检查 UTF-8 字节数（L55-L64），`read_source` 用原文字符 offset/limit（`service.py` L142-L159）。`full_content` 是完整“已经取得的文本”，不构成完整远端网页或无限大正文保证；Exa 请求本身带 maxCharacters（`exa.py` L19-L24）。

### 4. 来源引用与正文对象共同形成可回收图

来源映射 `search_sources` 由 `SourceRegistry.get` 独立判断 TTL（L59-L72）；正文通过 `content_sources` 引用 `content_objects`（`state_store.py` L108-L128）。删除单一正文引用只在没有其他引用时删除对象（`content_store.py` L227-L236）。URL 复用继承旧 expiry 与当前 TTL 的较小值（L123-L126），不能因反复命中新来源而续命。

put/reuse 的 bind、清理、逐出由 BEGIN IMMEDIATE 包在同一事务（`content_store.py` L72/L106），提交/回滚由 `StateStore.connect` L153-L160 建立。读取还会触碰 LRU（`content_store.py` L146-L150）；所以 read 是无网络，但不是无状态写入。

### 5. key 选择、使用与结果归档是三个时点

`run_keyed_source` 先取 candidates（L255），随后记 record_use（L267），调用 provider 后才 classify/record_result（L268-L270）。候选是状态快照：`key_state.py` L146-L160 排除当时冷却/禁用项并排序，没有独占预留接口。不能把 LRU 描述为一个 key 同时仅由一个请求持有。

invalid strike 的增量与阈值决定在同一 SQL UPDATE 内（`key_state.py` L204-L212、L226-L240）；提交顺序是结果状态顺序。抓取的 target 错误在 `scrape.py` L103-L106 跳过健康写入，而搜索分类会产生 target outcome（`key_state.py` L89-L91）再由 `search_runner.py` L270 记账。这两条记录并列保留，其他 search provider 的 target 标记使用情况仍开放。

## 未约束假设与开放问题

本轮没有把任何条目标成 `establishedBy: nothing found`。原因是未完成所有外部与部署约束的检查，不能把“还没读到”升格为“整个系统没有约束”。以下 8 个问题从逐函数记录原样携带：

1. unclear; need to inspect 目标 MCP/asyncio 版本实际取消传播；本轮仅源码，不运行 MCP 会话。
2. unclear; need to inspect 其他 provider 对 body/content_kind 的实际来源保证；本轮只深入 Brave 与 Exa 抓取。
3. unclear; need to inspect 部署是否把 source_id 当作同一可信调用方的 bearer reference；当前入口无 tenant 字段，运行宿主权限未检查。
4. unclear; need to inspect DNS 预检与最终连接之间、远端抓取服务内实际目标的契约；本轮不做网络实验。
5. unclear; need to inspect 运营对同一 key 并行使用的要求；当前选择快照与使用记账之间无独占预留，不能把 LRU 排序描述为独占分配。
6. unclear; need to inspect Brave API 当前 schema/压缩体规模保证；本轮离线不验证上游。
7. unclear; need to inspect 目标 Python socket DNS、代理 CONNECT 与 TLS 在该运行环境的计时边界；本轮不声称硬实时超时。
8. unclear; need to inspect 所有 search provider 是否发送 target origin；本轮只记录 search/scrape 两条调用链的不同处理，未判定业务影响。

## 方法实用性与成本

独到收益是把一句“有缓存/有 deadline/有 key pool”拆成调用者、被调者、状态变化时点与成立条件。最有价值的产物是以上五条耦合关系及能定位到原代码的函数文件，而不是发现数量。

成本主要是依赖追踪与逐函数材料：同一 Core 函数涉及 URL、retention、cache、scraper、key、HTTP，十个函数已读到 31 个生产文件。原版方法的逐函数 agent 与 schema 可限制主上下文膨胀；本轮适配把这些阅读留在同一子代理，未实际验证这一自动化收益。

局限：这适合陌生系统的审查前置材料，不能单独回答“现在有什么 bug、应优先修什么”。本輪 10 个逐函数文件是有边界的首轮材料，未完成全部内部/第三方库调用的递归闭包；已读依赖不等于已独立深查，未检查部分保留在 coverage/open questions。需要后续独立反证，不能把本报告当成全仓安全通过或生产行为验收。
