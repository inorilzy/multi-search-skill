# 术语表 (Glossary)

> 本文件维护术语与代码字段的映射。候选、摘要、正文、预览与来源引用的概念定义见 [CONTEXT.md](../CONTEXT.md)，此处只说明它们如何映射到接口。
>
> 标注了「代码出处」的术语，其权威定义在对应代码里；本表只是它的中文解释。
> 标注「概念性」的术语在代码里**没有对应字段**，只是为了方便描述而约定的说法，不要去代码里找它。

## 1. 核心概念

| 术语 | 定义 | 代码出处 |
|------|------|---------|
| **source（搜索源）** | 单个搜索后端，最小调用单位。如 `brave`、`github_repos`、`twitter`。 | `multi_search_mcp/src/search/search_runner.py` → `ALL_SOURCE_NAMES` |
| **source 别名** | source 的对外友好写法，调用时会被归一化。如 `github` → `github_repos`、`baidu-ai-search` → `baidu`。 | `multi_search_mcp/src/search/search_runner.py` → `SOURCE_ALIASES` |
| **route（路由）** | 一组预设 source，负责粗粒度选源。两个公共搜索入口使用相同的排序和正文获取流程。 | `multi_search_mcp/src/search/search_runner.py` → `ROUTE_PROFILES` |
| **profile（源集合）** | 某个 route 对应的那组 source 集合。`profile` 和 `route` 常被混用，但严格说 profile 只指「源集合」这一部分。 | `multi_search_mcp/src/search/search_runner.py` → `ROUTE_PROFILES` 的 value |
| **route_meta（兼容行为参数）** | route 的搜索超时、每源召回数量和展示默认值等。旧抓取数量字段不再控制公共流程；最终 RRF 前 15 条统一获取正文。 | `multi_search_mcp/src/search/search_runner.py` → `ROUTE_META` / `DEFAULT_ROUTE_META` |
| **want_content（正文内联）** | 搜索器兼容字段。公共搜索在召回阶段固定为 false，先取得候选并排序，再统一获取最终结果正文。 | `multi_search_mcp/src/search/search_runner.py` / `multi_search_mcp/src/core/search_pipeline.py` |

## 2. route 分类（概念性，非代码标签）

> 代码里**没有**「通用 / 专用」这个字段。这只是按 source 性质做的概念划分，便于描述。

| 类别 | 包含 route | 说明 |
|------|-----------|------|
| **通用搜索** | `default` / `web`、`fast`、`all` | 用综合搜索引擎搜索。`fast` 选择较少的通用源；`all` 尽可能广泛召回。所有 route 排序后都获取正文。 |
| **专用搜索** | `social`、`dev` | 绑定垂直平台，只搜特定领域。 |

> 注意：旧的 `level`（fast/normal）维度已删除。`fast` 现在是一个 route。

各 route 的 source 集合以代码 `ROUTE_PROFILES` 为准，逐项列举见 [route-capability-table.md](route-capability-table.md#最终-route-设计)，本表不再重复。

`sov2ex` 是 SOV2EX 提供的第三方 V2EX 专用索引搜索，匿名调用 API，无需 Firecrawl。它加入 `all`，也可通过 `sources=["sov2ex"]` 单独选择；不加入 `default` / `fast` / `dev`。`v2ex` 仅作为兼容别名保留，会被归一化为 `sov2ex`。搜索阶段只提供标题、URL 和清理后的高亮摘要，忽略 SOV2EX 索引正文。最终入选 RRF 前 15 条后，再统一抓取原帖 URL 或复用此前 URL 抓取的正文缓存。

## 3. 选源方式

| 术语 | 定义 | 代码出处 |
|------|------|---------|
| **route 选源** | 不传 `sources`，按 `route` 取一组预设源。粗粒度。 | `multi_search_mcp/src/search/search_runner.py` → `resolve_route` |
| **sources 选源** | 调用时显式传 `sources=["github"]`，精确点名要哪些源。**优先级高于 route，会忽略 route。** | `multi_search_mcp/src/search/resolve.py` → `resolve_search_plan` |
| **route 优先级** | 实际生效的 route：`request.route` → 配置 `type` → 默认 `"default"`。 | `multi_search_mcp/src/search/resolve.py` → `resolve_search_plan` |

## 4. 抓取与结果处理

| 术语 | 定义 | 代码出处 |
|------|------|---------|
| **summary（直接总结）** | provider 针对整个 query 生成的答案/总结，不属于某一条普通搜索结果。如 Tavily `answer`、Baidu answer 行、SerpAPI Knowledge Graph description。快速搜索优先使用它，但严肃结论仍应结合 URL/正文核查。 | `multi_search_mcp/src/support/models.py` → `SearchResult` dict 中通常是 `source=*answer` + `answer` |
| **title（结果标题）** | 单条搜索结果标题，用于展示和后续抓取候选。 | `multi_search_mcp/src/support/models.py` → `SearchResult.title` / dict `title` |
| **url（结果链接）** | 单条搜索结果的目标 URL，是后续 scrape 正文的入口。 | `multi_search_mcp/src/support/models.py` → `SearchResult.url` / dict `url` |
| **content（结果摘要）** | `SearchHit.content` 映射摘要；provider 的 `description` 可以与正文同时存在。`search_content()` 统一分离摘要和正文后，再生成候选输出。 | `multi_search_mcp/src/support/models.py` → `search_content` / `multi_search_mcp/src/search/candidate.py` |
| **content_kind（内容语义）** | Provider 行区分 `metadata`、`content`（平台正文）、`excerpt`、`body`、`answer`；其中 `content` / `body` 行的 `scraped_content` 可进入正文缓存，`excerpt` 行的同名字段仅为高亮。候选输出的类型描述其摘要，不继承正文类型。 | `multi_search_mcp/src/support/models.py` / `multi_search_mcp/src/search/capabilities.py` |
| **预取正文选择** | `run_search_candidates` 对原始结果按 canonical URL 只选一次正文：字符数最长优先，等长时依次按 provider 名、正文文本升序选择，与 query/provider/重复行的输入顺序和 `use_state` 无关。同一选择用于可选缓存和 `run_search_web` 的正文获取，再裁剪响应预览；retention 仍按候选全部 providers 合并，已有合法缓存继续按原命中与有效期规则使用。 | `multi_search_mcp/src/core/search_pipeline.py` → `run_search_candidates` / `run_search_web` |
| **正文预览（Markdown）** | 搜索正文只存放在 `scrapes[].markdown`，按 `source_id` 对应候选，默认最多 1200 字符；需要截断时从完全匹配结果标题的一级标题开始，没有匹配标题时可定位逐字匹配完整摘要的段落（至少 32 个非空白字符，仅允许空白差异），仍无匹配则从开头开始。`preview_start/end` 是原文字符偏移（左闭右开），省略前文也算 `truncated`。`multi_search` 的 markdown/both 模式只在顶层 `markdown` 放正文，`scrapes` 保留元数据。`fetch_source` 的单页文本字段为 `body`；预览不改缓存。 | `multi_search_mcp/src/core/search_pipeline.py` → `run_search_web` / `multi_search_mcp/src/core/body_fetch.py` → `run_fetch_source` |
| **选读 / 全文** | 调用工具的 Agent 根据问题和预览选 3–5 篇，逐篇用 `fetch_source(full_content=True)` 一次读取全部已取得文本；少于 3 篇合格来源时读取可用数量并说明。Core 继续抓取 RRF 最终 15 条；选读是 Agent 阅读流程。全文受后端现有抓取限制约束，Reddit 仅含已加载评论。 | `skills/multi-search/SKILL.md` / `multi_search_mcp/src/core/body_fetch.py` → `run_fetch_source` |
| **ScrapeResult（统一抓取结果）** | 四个通用后端（Jina、Exa、Tavily、Firecrawl）及 Reddit、Twitter/X 专用适配器在共享入口统一为 `url/title/markdown/length/via/truncated`。`length` 是取得正文的字符数，`truncated` 标明预览是否截断；失败时正文为空、长度为 0，并增加 `error`。统一错误字段为 `origin`（`target` 或 `provider`）及 `kind`；分类辅助函数接受旧 `error_origin` / `error_type` 作为兼容输入，归一化抓取输出仅保留新字段：明确的目标错误保留使用记录，但不轮换 key、不写密钥健康状态；明确类别优先于错误文字分类。上游私有响应字段不会直接透传。 | `multi_search_mcp/src/support/models.py` → `normalize_scrape_result` |
| **SearchHit（搜索候选）** | 概念见 [CONTEXT.md](../CONTEXT.md)。候选包含 `source_id/title/url/canonical_url/content/providers/provider_ranks/rrf_score/body_available`；公共响应在排序后补充抓取状态或 `body_error`，正文由同一 `source_id` 的抓取结果提供。 | `multi_search_mcp/src/search/candidate.py` / `multi_search_mcp/src/core/search_pipeline.py` |
| **response_id / source_id** | `response_id` 标识一次候选搜索；`source_id` 稳定标识该响应中的 canonical URL，并作为 `fetch_source` / `read_source` 的引用。 | `multi_search_mcp/src/search/candidate.py` / `multi_search_mcp/src/state/source_registry.py` |
| **provider_rank / RRF** | 保留 provider 内部原始名次；同一 query 先做等权 RRF，expanded query 再按 query 排名做第二级 RRF，默认等权。`k=40`，两级均无中间截断，最终最多 15 条。provider 原生 score 只保留为诊断，正文不改变排序。 | `multi_search_mcp/src/search/search_runner.py` / `multi_search_mcp/src/search/candidate.py` |
| **count（每源召回量）** | 控制每个搜索源请求多少结果，受该源上限约束；不控制融合后的最终 15 条限制。 | `multi_search_mcp/src/search/resolve.py` / `multi_search_mcp/src/search/candidate.py` |
| **scrape（抓正文）** | 搜索后自动获取最终 RRF 前 15 条正文，已有 URL 可直接抓取。旧 `scrape_top` / `scrape_per_source` 参数不再裁剪列表，显式传入时 diagnostics 会说明。 | `multi_search_mcp/src/core/search_pipeline.py` → `run_search_web` / `multi_search_mcp/src/scrape/stage.py` → `run_ranked_fetch_stage` |
| **scrape backend（抓取后端）** | 抓正文用的后端，与搜索源不同。已知集合：`jina`、`exa`、`tavily`、`firecrawl`。 | `multi_search_mcp/src/scrape/scrape.py` → `KNOWN_BACKENDS` |
| **site memory（站点抓取记忆）** | 记录站点抓取结果、手动固定与冷却；排序按手动固定、配置链顺序及冷却降级，不按历史成功率自动重排。 | `multi_search_mcp/src/state/site_memory.py` → `SiteScraperMemory` |
| **dedup（去重）** | 两个搜索入口统一使用保守 canonical URL 后按 RRF 融合，同一 query、同一 provider 的重复 URL 只按最好名次投一票。跨 provider、跨 query 的贡献保留。 | `multi_search_mcp/src/search/candidate.py` |
| **ContentStore（正文缓存）** | 正文获取先按 UTF-8 单对象字节上限在字符边界截断，再持久化与裁剪响应；首次响应 `truncated` 包含字节或预览裁剪。`max_chars` 本身仅限制预览；TTL、总容量、LRU 和 retention 继续生效。SQLite/OSError/ContentStoreError 写入失败不丢弃已取得正文，返回 `persisted=false` 与 `cache_error`。schema v2 的 `content_sources.truncated` 按 source/acquisition 绑定保存截断状态，get/URL reuse/read 均保留，相关回归已独立通过；不是 content hash 的共享属性。完整重写可清除旧标记，展示 preview 不污染 acquisition；旧缓存默认 false 不代表可重建过去丢失的证据。 | `multi_search_mcp/src/state/content_store.py` / `multi_search_mcp/src/core/body_fetch.py` → `run_fetch_source` |
| **SourceRegistry（来源注册表）** | 保存短期来源引用；每个注册批次在同一事务中删除已到期记录，按 `expires_at` 索引查找。没有后台定时器，应用停止时不会自动执行清理。 | `multi_search_mcp/src/state/source_registry.py` / `multi_search_mcp/src/state/state_store.py` |
| **fetch_source（按需抓取）** | 按 `source_id` 或显式 URL 抓一条正文；先查 ContentStore，未命中才调用现有 scraper 链。`full_content=False` 保留默认 20000 字符及显式 `max_chars` 限制；`True` 覆盖 `max_chars`，一次返回全部已取得文本，缓存容量与 retention 不变。目标 URL 统一执行 SSRF 校验。 | `multi_search_mcp/src/core/body_fetch.py` → `run_fetch_source` |
| **read_source（局部读取）** | 只读 ContentStore，支持 keyword/offset/limit，供定向查证缓存片段。`truncated` 表示 acquisition 不完整，`has_more` 仅表示缓存内有更多字符，两者独立。缺失或过期时明确要求先调用 `fetch_source`，不会隐式联网；默认选读全文使用 `fetch_source(full_content=True)`。 | `multi_search_mcp/src/core/body_fetch.py` → `run_read_source` |
| **降级 / degradation** | route 的主源全部失败或无可用结果时，在结果里**显式标注**。当前所有 route 的 `degrade_to` 都为空，所以只会输出「primary providers unavailable」提示，不会自动切换到兜底源（兜底机制保留但未启用）。 | `multi_search_mcp/src/search/search_runner.py` → `ROUTE_META` 的 `degrade_to` ＋ `multi_search_mcp/src/core/present.py` → `_route_degradation` |

| 术语 | 定义 | 代码出处 |
|---|---|---|
| **deadline（整批截止时间）** | 使用 monotonic 时间控制准入和等待；到期后只收集已完成任务，未完成任务返回准入失败/超时结果，不再无界 result() 等待。Python 不能强杀运行线程，迟到任务仍占池槽至返回，守护线程不阻塞进程退出；每层 fan-out 使用独立池。 | `multi_search_mcp/src/support/concurrency.py` → `BoundedDaemonExecutor.run_all_before` |
| **错误分类与 key 重试** | row_kind 优先 kind，再读取旧 error_type/标记；row_origin 优先 origin，再读旧 error_origin，kind=target 可推导 target。结构化类别优先于文字；仅缺类别时才使用文字匹配。target 不触发 key 轮换；provider invalid/quota/rate-limit 可轮换，直到成功、不再可重试或 deadline 到期。 | `multi_search_mcp/src/support/auth.py` → `row_kind` / `row_origin` / `is_key_retryable_error`；`multi_search_mcp/src/state/key_state.py` → `rotate_keys` |

## 5. Key 与状态

> SQLite 凭据中的 Jina 静态 `exhausted` 与 SQLite 状态库中的 `quota_exhausted` 是两层独立状态：前者是操作员维护的配置级静态排除，后者是运行时健康状态。配置仍启用不代表运行时一定可用；运行时暂不可用也不会自动改写配置。

| 术语 | 定义 | 代码出处 |
|------|------|---------|
| **key 轮换** | 同一 provider 有多个 key 时，按「未用过优先 → 最久未用（LRU）」挑选。SQLite 调用前通过 `reserve` 在 `BEGIN IMMEDIATE` 内重查健康、按最新 LRU 选择并更新 use_count/last_used_at；不是独占 lease，允许同 key 并发。 | `multi_search_mcp/src/state/key_state.py` → `SQLiteKeyManager.candidates` / `SQLiteKeyManager.reserve` |
| **Jina 配置 `exhausted`** | SQLite Jina 凭据元数据中的静态排除标记，由操作员手动维护；为 `true` 时 `jina_config_keys()` 不会将该 key 交给轮换。它不是运行态状态，不由 HTTP 402 自动写入，也没有 24 小时恢复期。 | `multi_search_mcp/src/state/keys.py` → `jina_config_keys`；`multi_search_mcp/src/support/credential_store.py` |
| **key 状态：active** | 运行态当前没有阻止使用的健康状态；若 `manually_disabled` 仍为真，候选选择仍会跳过；也不覆盖 Jina 配置中的静态 `exhausted` 排除。成功回报会将运行态写回 `active`。 | `multi_search_mcp/src/state/key_state.py` → `ACTIVE` / `SQLiteKeyManager.record_result` |
| **key 状态：cooldown** | 运行态临时失败（如限流）；当前冷却 15 分钟，`cooldown_until` 未到期时跳过，期满后重新允许尝试。 | `multi_search_mcp/src/state/key_state.py` → `COOLDOWN` / `cooldown_until` |
| **key 状态：quota_exhausted** | 运行态收到配额/余额用尽信号；当前恢复期 24 小时，`exhausted_until` 未到期时跳过，期满后重新允许尝试。它不等于配置级 `exhausted`，不会写回 keys file。 | `multi_search_mcp/src/state/key_state.py` → `QUOTA_EXHAUSTED` / `exhausted_until` |
| **key 状态：transient_invalid** | 运行态暂时视为无效；连续收到 provider 的 invalid 分类失败时，没有既存强状态时，前两次先冷却 15 分钟并在冷却期跳过，第三次升级为 `invalid`。success、`rate_limit`、`quota_exhausted` 清零 `invalid_strikes`；timeout/network/未分类失败与 target 错误不清零。既存 invalid、quota_exhausted、disabled 在 invalid 失败更新时保留。 | `multi_search_mcp/src/state/key_state.py` → `TRANSIENT_INVALID` / `INVALID_COOLDOWN` / `INVALID_STRIKE_LIMIT` / `SQLiteKeyManager.record_result` |
| **key 状态：invalid** | 运行态达到 invalid 计数阈值后的长期排除状态；候选选择会跳过，需调用 `reset_key_state` 或明确重置后才会重新使用。 | `multi_search_mcp/src/state/key_state.py` → `INVALID` / `SQLiteKeyManager.candidates` |
| **key 状态：disabled** | 运行态被操作员手动禁用（`manually_disabled` 或 `disabled`）；无自动到期恢复，候选选择会跳过，`reset` 仅重置运行时 status/期限/strikes，不清除 `manually_disabled`；手动禁用标记须另行明确解除。它也不等于 Jina 配置级 `exhausted`。 | `multi_search_mcp/src/state/key_state.py` → `DISABLED` / `manually_disabled` |
| **StateStore（状态库）** | SQLite 状态库，存 key 状态、站点记忆、短期 source registry 与 ContentStore，默认 `~/.multi-search/state.sqlite`。 | `multi_search_mcp/src/state/state_store.py` |
| **use_state（状态开关）** | 工具参数。`false` 时跳过 SQLite 状态、key 轮换、站点记忆，用于干净测试。 | `multi_search_mcp/src/core/requests.py` / `multi_search_mcp/src/core/runtime.py` |

失败写入的状态保护并非简单全序覆盖：rate_limit 与 invalid 失败保留已有 invalid/quota_exhausted/disabled；quota_exhausted 失败保留已有 invalid/disabled。invalid 失败仍原子累加 strikes；success、rate_limit、quota_exhausted 清零 strikes。timeout/network/未分类失败仅记录失败计数与脱敏错误，不改变 status、期限或 strikes。target 错误只保留调用使用记录，不写健康结果。成功回报仍写 active、清冷却与 strikes，但不清 manually_disabled；因此不能把失败更新的强状态保护扩展成“成功永不覆盖”。时间到期仅允许候选再尝试，不自动改写数据库 status。

## 6. 入口与配置

| 术语 | 定义 | 代码出处 |
|------|------|---------|
| **Core 请求** | `search_web` 和 `multi_search` 共用 RRF 搜索及正文获取；`fetch_source` / `scrape_url` 可直接抓 URL，`read_source` 局部读缓存，另有状态/诊断能力。无 MCP 服务入口。 | `multi_search_mcp/src/service.py` |
| **CLI** | `multi-search` console entry；`search/fetch/read/doctor/keys` 都直接调用同一 Core 和 StateStore，按需启动并退出，不依赖 MCP 或常驻服务。 | `multi_search_mcp/cli.py` |
| **SKILL** | 给 agent 的薄自然语言触发层，告诉它何时调工具、传什么 route/sources。 | `skills/multi-search/SKILL.md` |
| **config（行为配置）** | 非敏感的默认值（route/count/timeout 等）。默认只从 SQLite settings 读取；JSON 仅在显式传入路径时读取，不自动使用环境变量或源码树 fallback。 | `multi_search_mcp/src/support/config.py` → `resolve_config_path` |
| **credential store（凭据库）** | SQLite 是唯一默认凭据来源；provider 凭据由 DPAPI 加密。旧 keys file 仅为显式迁移/兼容输入，环境变量不覆盖凭据。Twitter file 路径与 file/managed 模式存于 settings；managed 使用独立 twitter_cookies 加密条目，不属于 API-key 轮换集合。 | `multi_search_mcp/src/support/credential_store.py` / `multi_search_mcp/src/state/keys.py` |

| **Twitter Cookie 模式** | settings.twitter_cookies_mode 缺省为 file（旧明文文件，不自动迁移）；Windows 显式导入切换 managed，DPAPI 凭据实际调用时解密为字典，无临时明文文件。managed 缺失/损坏/非 Windows 不回退 file。删除保持 managed，不删除原始文件；当前 UI 不提供 managed→file 切换。DPAPI 不防同用户进程/内存读取。 | `desktop/src-tauri/COOKIE-PROTOCOL.md` / `multi_search_mcp/src/support/credential_store.py` |

## 维护约定

- 从仓库根目录执行 `uv run --locked python scripts/check_glossary_paths.py`，检查每个代码出处文件存在。

- 改了 `ROUTE_PROFILES` / `ALL_SOURCE_NAMES` / `SOURCE_ALIASES` / `KNOWN_BACKENDS` 等常量，**同步更新本表对应行**。
- 新概念先在这里定义，再在 README / SKILL 里引用，避免同一概念多处各说一套。
- 「概念性」标注的术语不要写进代码注释当成字段名。
