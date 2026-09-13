# 术语表 (Glossary)

> 本文件维护术语与代码字段的映射。候选、摘要、正文、预览与来源引用的概念定义见 [CONTEXT.md](../CONTEXT.md)，此处只说明它们如何映射到接口。
>
> 标注了「代码出处」的术语，其权威定义在对应代码里；本表只是它的中文解释。
> 标注「概念性」的术语在代码里**没有对应字段**，只是为了方便描述而约定的说法，不要去代码里找它。

## 1. 核心概念

| 术语 | 定义 | 代码出处 |
|------|------|---------|
| **source（搜索源）** | 单个搜索后端，最小调用单位。如 `brave`、`github_repos`、`twitter`。 | `search_runner.py` → `ALL_SOURCE_NAMES` |
| **source 别名** | source 的对外友好写法，调用时会被归一化。如 `github` → `github_repos`、`baidu-ai-search` → `baidu`。 | `search_runner.py` → `SOURCE_ALIASES` |
| **route（路由）** | 一组预设 source，负责粗粒度选源。两个公共搜索入口使用相同的排序和正文获取流程。 | `search_runner.py` → `ROUTE_PROFILES` |
| **profile（源集合）** | 某个 route 对应的那组 source 集合。`profile` 和 `route` 常被混用，但严格说 profile 只指「源集合」这一部分。 | `ROUTE_PROFILES` 的 value |
| **route_meta（兼容行为参数）** | route 的搜索超时、每源召回数量和展示默认值等。旧抓取数量字段不再控制公共流程；最终 RRF 前 15 条统一获取正文。 | `search_runner.py` → `ROUTE_META` / `DEFAULT_ROUTE_META` |
| **want_content（正文内联）** | 搜索器兼容字段。公共搜索在召回阶段固定为 false，先取得候选并排序，再统一获取最终结果正文。 | `search_runner.py` / `service.py` |

## 2. route 分类（概念性，非代码标签）

> 代码里**没有**「通用 / 专用」这个字段。这只是按 source 性质做的概念划分，便于描述。

| 类别 | 包含 route | 说明 |
|------|-----------|------|
| **通用搜索** | `default` / `web`、`fast`、`all` | 用综合搜索引擎搜索。`fast` 选择较少的通用源；`all` 尽可能广泛召回。所有 route 排序后都获取正文。 |
| **专用搜索** | `social`、`dev` | 绑定垂直平台，只搜特定领域。 |

> 注意：旧的 `level`（fast/normal）维度已删除。`fast` 现在是一个 route。

各 route 当前定义（以 `ROUTE_PROFILES` 为准，可能随代码变动）：

| route | 类别 | source 集合 |
|-------|------|------------|
| `default` / `web` | 通用 | brave + parallel + tavily + exa + serpapi + firecrawl + baidu |
| `fast` | 通用 | baidu + tavily + firecrawl + exa |
| `all` | 通用 | default 的源 + twitter + stackoverflow + github_repos + hackernews + v2ex |
| `social` | 专用 | twitter |
| `dev` | 专用 | stackoverflow + github_repos + hackernews |

`v2ex` 是 SOV2EX 提供的第三方 V2EX 专用索引搜索，匿名调用 API，无需 Firecrawl。它加入 `all`，也可通过 `sources=["v2ex"]` 单独选择；不加入 `default` / `fast` / `dev`。搜索阶段只提供标题、URL 和清理后的高亮摘要，忽略 SOV2EX 索引正文。最终入选 RRF 前 15 条后，再统一抓取原帖 URL 或复用此前 URL 抓取的正文缓存。

## 3. 选源方式

| 术语 | 定义 | 代码出处 |
|------|------|---------|
| **route 选源** | 不传 `sources`，按 `route` 取一组预设源。粗粒度。 | `service.py` → `resolve_route` |
| **sources 选源** | 调用时显式传 `sources=["github"]`，精确点名要哪些源。**优先级高于 route，会忽略 route。** | `service.py` `run_multi_search` |
| **route 优先级** | 实际生效的 route：`request.route` → 配置 `type` → 默认 `"default"`。 | `service.py` `run_multi_search` |

## 4. 抓取与结果处理

| 术语 | 定义 | 代码出处 |
|------|------|---------|
| **summary（直接总结）** | provider 针对整个 query 生成的答案/总结，不属于某一条普通搜索结果。如 Tavily `answer`、Baidu answer 行、SerpAPI Knowledge Graph description。快速搜索优先使用它，但严肃结论仍应结合 URL/正文核查。 | `SearchResult` dict 中通常是 `source=*answer` + `answer` |
| **title（结果标题）** | 单条搜索结果标题，用于展示和后续抓取候选。 | `SearchResult.title` / dict `title` |
| **url（结果链接）** | 单条搜索结果的目标 URL，是后续 scrape 正文的入口。 | `SearchResult.url` / dict `url` |
| **content（结果摘要）** | `SearchHit.content` 映射摘要；provider 的 `description` 可以与正文同时存在。`search_content()` 统一分离摘要和正文后，再生成候选输出。 | `support/models.py` → `search_content` / `search/candidate.py` |
| **content_kind（内容语义）** | Provider 行区分 `metadata`、`content`（平台正文）、`excerpt`、`body`、`answer`；其中 `content` / `body` 行的 `scraped_content` 可进入正文缓存，`excerpt` 行的同名字段仅为高亮。候选输出的类型描述其摘要，不继承正文类型。 | `support/models.py` / `search/capabilities.py` |
| **预取正文选择** | `_run_search_candidates` 对原始结果按 canonical URL 只选一次正文：字符数最长优先，等长时依次按 provider 名、正文文本升序选择，与 query/provider/重复行的输入顺序和 `use_state` 无关。同一选择用于可选缓存和 `run_search_web` 的正文获取，再裁剪响应预览；retention 仍按候选全部 providers 合并，已有合法缓存继续按原命中与有效期规则使用。 | `service.py` → `_run_search_candidates` / `run_search_web` |
| **正文预览（Markdown）** | 搜索正文只存放在 `scrapes[].markdown`，按 `source_id` 对应候选，默认最多 1200 字符；需要截断时从完全匹配结果标题的一级标题开始，没有匹配标题时可定位逐字匹配完整摘要的段落（至少 32 个非空白字符，仅允许空白差异），仍无匹配则从开头开始。`preview_start/end` 是原文字符偏移（左闭右开），省略前文也算 `truncated`。`multi_search` 的 markdown/both 模式只在顶层 `markdown` 放正文，`scrapes` 保留元数据。`fetch_source` 的单页文本字段为 `body`；预览不改缓存。 | `service.py` → `run_search_web` / `run_fetch_source` |
| **选读 / 全文** | 调用工具的 Agent 根据问题和预览选 3–5 篇，逐篇用 `fetch_source(full_content=True)` 一次读取全部已取得文本；少于 3 篇合格来源时读取可用数量并说明。Core 继续抓取 RRF 最终 15 条；选读是 Agent 阅读流程。全文受后端现有抓取限制约束，Reddit 仅含已加载评论。 | `skills/multi-search/SKILL.md` / `service.py` → `run_fetch_source` |
| **ScrapeResult（统一抓取结果）** | 五个后端在共享入口统一为 `url/title/markdown/length/via/truncated`。`length` 是取得正文的字符数，`truncated` 标明预览是否截断；失败时正文为空、长度为 0，并增加 `error`。适配器可附带 `error_origin`（`target` 或 `provider`）及 `error_type`：明确的目标错误保留使用记录，但不轮换 key、不写密钥健康状态；明确类别优先于错误文字分类。上游私有响应字段不会直接透传。 | `support/models.py` → `normalize_scrape_result` |
| **SearchHit（搜索候选）** | 概念见 [CONTEXT.md](../CONTEXT.md)。候选包含 `source_id/title/url/canonical_url/content/providers/provider_ranks/rrf_score/body_available`；公共响应在排序后补充抓取状态或 `body_error`，正文由同一 `source_id` 的抓取结果提供。 | `search/candidate.py` / `service.py` |
| **response_id / source_id** | `response_id` 标识一次候选搜索；`source_id` 稳定标识该响应中的 canonical URL，并作为 `fetch_source` / `read_source` 的引用。 | `search/candidate.py` / `state/source_registry.py` |
| **provider_rank / RRF** | 保留 provider 内部原始名次；同一 query 先做等权 RRF，expanded query 再按 query 排名做第二级 RRF，默认等权。`k=40`，两级均无中间截断，最终最多 15 条。provider 原生 score 只保留为诊断，正文不改变排序。 | `search/search_runner.py` / `search/candidate.py` |
| **count（每源召回量）** | 控制每个搜索源请求多少结果，受该源上限约束；不控制融合后的最终 15 条限制。 | `search/resolve.py` / `search/candidate.py` |
| **scrape（抓正文）** | 搜索后自动获取最终 RRF 前 15 条正文，已有 URL 可直接抓取。旧 `scrape_top` / `scrape_per_source` 参数不再裁剪列表，显式传入时 diagnostics 会说明。 | `service.py` → `run_search_web` / `scrape/stage.py` → `run_ranked_fetch_stage` |
| **scrape backend（抓取后端）** | 抓正文用的后端，与搜索源不同。已知集合：`jina`、`exa`、`tavily`、`firecrawl`。 | `scrape.py` → `KNOWN_BACKENDS` |
| **site memory（站点抓取记忆）** | 记录每个站点用哪个 scraper 成功率高，下次优先用它。 | `state/site_memory.py` → `SiteScraperMemory` |
| **dedup（去重）** | 两个搜索入口统一使用保守 canonical URL 后按 RRF 融合，同一 query、同一 provider 的重复 URL 只按最好名次投一票。跨 provider、跨 query 的贡献保留。 | `search/candidate.py` |
| **ContentStore（正文缓存）** | 对后端本次返回的原始正文执行容量检查与持久化，再裁剪本次响应。`max_chars` 只限制返回预览，不能截短缓存；TTL、单对象/总容量、LRU 和 provider retention 继续生效。 | `state/content_store.py` / `service.py` → `_run_scrape_raw` |
| **SourceRegistry（来源注册表）** | 保存短期来源引用；每个注册批次在同一事务中删除已到期记录，按 `expires_at` 索引查找。没有后台定时器，应用停止时不会自动执行清理。 | `state/source_registry.py` / `state/state_store.py` |
| **fetch_source（按需抓取）** | 按 `source_id` 或显式 URL 抓一条正文；先查 ContentStore，未命中才调用现有 scraper 链。`full_content=False` 保留默认 20000 字符及显式 `max_chars` 限制；`True` 覆盖 `max_chars`，一次返回全部已取得文本，缓存容量与 retention 不变。目标 URL 统一执行 SSRF 校验。 | `service.py` → `run_fetch_source` |
| **read_source（局部读取）** | 只读 ContentStore，支持 keyword/offset/limit，供定向查证缓存片段。缺失或过期时明确要求先调用 `fetch_source`，不会隐式联网；默认选读全文使用 `fetch_source(full_content=True)`。 | `service.py` → `run_read_source` |
| **降级 / degradation** | route 的主源全部失败或无可用结果时，在结果里**显式标注**。当前所有 route 的 `degrade_to` 都为空，所以只会输出「primary providers unavailable」提示，不会自动切换到兜底源（兜底机制保留但未启用）。 | `ROUTE_META` 的 `degrade_to` ＋ `service.py` `_route_degradation` |

## 5. Key 与状态

> `~/.search-keys.json` 中 Jina 的 `exhausted` 与 SQLite 状态库中的 `quota_exhausted` 是两层独立状态：前者是操作员维护的配置级静态排除，后者是运行时健康状态。配置仍启用不代表运行时一定可用；运行时暂不可用也不会自动改写配置。

| 术语 | 定义 | 代码出处 |
|------|------|---------|
| **key 轮换** | 同一 provider 有多个 key 时，按「未用过优先 → 最久未用（LRU）」挑选。每次选中更新 `last_used_at` / `use_count`。 | `state/key_state.py` → `SQLiteKeyManager.candidates` |
| **Jina 配置 `exhausted`** | `~/.search-keys.json` 中的静态排除标记，由操作员手动维护；为 `true` 时 `jina_config_keys()` 不会将该 key 交给轮换。它不是运行态状态，不由 HTTP 402 自动写入，也没有 24 小时恢复期。 | `state/keys.py` → `jina_config_keys`；`state/mark_exhausted.py` |
| **key 状态：active** | 运行态当前没有阻止使用的健康状态；若 `manually_disabled` 仍为真，候选选择仍会跳过；也不覆盖 Jina 配置中的静态 `exhausted` 排除。成功回报会将运行态写回 `active`。 | `state/key_state.py` → `ACTIVE` / `SQLiteKeyManager.record_result` |
| **key 状态：cooldown** | 运行态临时失败（如限流）；当前冷却 15 分钟，`cooldown_until` 未到期时跳过，期满后重新允许尝试。 | `state/key_state.py` → `COOLDOWN` / `cooldown_until` |
| **key 状态：quota_exhausted** | 运行态收到配额/余额用尽信号；当前恢复期 24 小时，`exhausted_until` 未到期时跳过，期满后重新允许尝试。它不等于配置级 `exhausted`，不会写回 keys file。 | `state/key_state.py` → `QUOTA_EXHAUSTED` / `exhausted_until` |
| **key 状态：transient_invalid** | 运行态暂时视为无效；invalid 分类失败后先冷却 15 分钟并在冷却期跳过，`invalid_strikes` 达到 3 次才升级为 `invalid`。 | `state/key_state.py` → `TRANSIENT_INVALID` / `INVALID_COOLDOWN` / `INVALID_STRIKE_LIMIT` |
| **key 状态：invalid** | 运行态达到 invalid 计数阈值后的长期排除状态；候选选择会跳过，需调用 `reset_key_state` 或明确重置后才会重新使用。 | `state/key_state.py` → `INVALID` / `SQLiteKeyManager.candidates` |
| **key 状态：disabled** | 运行态被操作员手动禁用（`manually_disabled` 或 `disabled`）；无自动到期恢复，候选选择会跳过，需清除该标记或调用 `reset_key_state`。它也不等于 Jina 配置级 `exhausted`。 | `state/key_state.py` → `DISABLED` / `manually_disabled` |
| **StateStore（状态库）** | SQLite 状态库，存 key 状态、站点记忆、短期 source registry 与 ContentStore，默认 `~/.multi-search/state.sqlite`。 | `state/state_store.py` |
| **use_state（状态开关）** | 工具参数。`false` 时跳过 SQLite 状态、key 轮换、站点记忆，用于干净测试。 | `tools.py` / `service.py` |

`transient_invalid` 的阈值规则按当前产品意图是连续的 invalid 分类失败；但当前实现中 `invalid_strikes` 在 invalid 回报时递增，成功或一般错误时清零，而 `rate_limit` / `quota_exhausted` 分支会保留已有计数。因此本表只把“达到 3 次才升级”作为可观察实现规则，不保证所有非 invalid 回报都严格清零；这项实现边界不在本文档票内修复。时间字段到期后候选选择器会重新允许尝试，但数据库的 `status` 不会仅因时间流逝自动改写为 `active`。

## 6. 入口与配置

| 术语 | 定义 | 代码出处 |
|------|------|---------|
| **MCP 工具** | `search_web` 和 `multi_search` 共用 RRF 搜索及正文获取；`fetch_source` / `scrape_url` 可直接抓 URL，`read_source` 局部读缓存，另有状态/诊断工具。 | `multi_search_mcp/server.py` |
| **CLI** | `multi-search` console entry；`search/fetch/read/doctor/keys` 都直接调用同一 Core 和 StateStore，不反向调用 MCP。 | `multi_search_mcp/cli.py` |
| **SKILL** | 给 agent 的薄自然语言触发层，告诉它何时调工具、传什么 route/sources。 | `skills/multi-search/SKILL.md` |
| **config（行为配置）** | 非敏感的默认值（route/count/timeout 等）。解析顺序：env `MULTI_SEARCH_CONFIG` → `~/.multi-search/multi-search-config.json` → 源码树 fallback。 | `support/config.py` → `resolve_config_path` |
| **keys file（密钥文件）** | 明文 API key / cookie，只从环境变量和 `~/.search-keys.json` 读取，**不**放进 config。 | `state/keys.py` |

## 维护约定

- 改了 `ROUTE_PROFILES` / `ALL_SOURCE_NAMES` / `SOURCE_ALIASES` / `KNOWN_BACKENDS` 等常量，**同步更新本表对应行**。
- 新概念先在这里定义，再在 README / SKILL 里引用，避免同一概念多处各说一套。
- 「概念性」标注的术语不要写进代码注释当成字段名。
