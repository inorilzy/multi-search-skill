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
| **route（路由）** | 一组 source，负责粗粒度选源。内置 5 组由 `ROUTE_PROFILES` 定义；设置中的完整 `routes` 映射（路由组）存在时以它为准，可增删改组的标签、源和超时。两个公共搜索入口使用相同的排序和正文获取流程。 | `multi_search_mcp/src/search/search_runner.py` → `ROUTE_PROFILES`；`multi_search_mcp/src/search/resolve.py` → `resolve_configured_routes` |
| **profile（源集合）** | 某个 route 对应的那组 source 集合。`profile` 和 `route` 常被混用，但严格说 profile 只指「源集合」这一部分。 | `multi_search_mcp/src/search/search_runner.py` → `ROUTE_PROFILES` 的 value |
| **route_meta（兼容行为参数）** | route 的搜索超时、每源召回数量和展示默认值等。旧抓取数量字段不再控制公共流程；最终 RRF 前 15 条统一获取正文。 | `multi_search_mcp/src/search/search_runner.py` → `ROUTE_META` / `DEFAULT_ROUTE_META` |
| **want_content（正文内联）** | 仅保留为搜索器函数的兼容参数。公共搜索不再暴露路由/配置开关，召回阶段固定不请求内联正文，先取得候选并排序，再统一获取最终结果正文。 | `multi_search_mcp/src/search/searchers/tavily.py` 等搜索器 / `multi_search_mcp/src/search/candidates.py` |

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
| **预取正文选择** | `run_search_candidates` 对原始结果按 canonical URL 只选一次正文：字符数最长优先，等长时依次按 provider 名、正文文本升序选择，与 query/provider/重复行的输入顺序和 `use_state` 无关。同一选择用于可选缓存和 `run_search_web` 的正文获取，再裁剪响应预览；retention 仍按候选全部 providers 合并，已有合法缓存继续按原命中与有效期规则使用。 | `multi_search_mcp/src/search/candidates.py` → `run_search_candidates` / `multi_search_mcp/src/search_web.py` → `run_search_web` |
| **仅候选（no_fetch）** | `search --no-fetch` / `SearchWebRequest.no_fetch`：只融合排序候选，不抓取正文、不写正文缓存；结果仍带 `source_id`，之后可按需 `fetch`。 | `multi_search_mcp/src/support/requests.py` → `SearchWebRequest` / `multi_search_mcp/src/search_web.py` → `run_search_web` |
| **正文预览（Markdown）** | 搜索正文只存放在 `scrapes[].markdown`，按 `source_id` 对应候选，默认最多 1200 字符；需要截断时从完全匹配结果标题的一级标题开始，没有匹配标题时可定位逐字匹配完整摘要的段落（至少 32 个非空白字符，仅允许空白差异），仍无匹配则从开头开始。`preview_start/end` 是原文字符偏移（左闭右开），省略前文也算 `truncated`。`multi_search` 的 markdown/both 模式只在顶层 `markdown` 放正文，`scrapes` 保留元数据。`fetch_source` 的单页文本字段为 `body`；预览不改缓存。 | `multi_search_mcp/src/search_web.py` → `run_search_web` / `multi_search_mcp/src/scrape/fetch.py` → `run_fetch_source` |
| **选读 / 全文** | 调用工具的 Agent 根据问题和预览选 3–5 篇，逐篇用 `fetch_source(full_content=True)` 一次读取全部已取得文本；少于 3 篇合格来源时读取可用数量并说明。Core 继续抓取 RRF 最终 15 条；选读是 Agent 阅读流程。全文受后端现有抓取限制约束，Reddit 仅含已加载评论。 | `skills/multi-search/SKILL.md` / `multi_search_mcp/src/scrape/fetch.py` → `run_fetch_source` |
| **ScrapeResult（统一抓取结果）** | 四个通用后端（Jina、Exa、Tavily、Firecrawl）及 Reddit、Twitter/X 专用适配器在共享入口统一为 `url/title/markdown/length/via/truncated`。`length` 是取得正文的字符数，`truncated` 标明预览是否截断；失败时正文为空、长度为 0，并增加 `error`。适配器可附带 `error_origin`（`target` 或 `provider`）及 `error_type`：明确的目标错误保留使用记录，但不轮换 key、不写密钥健康状态；明确类别优先于错误文字分类。上游私有响应字段不会直接透传。 | `multi_search_mcp/src/support/models.py` → `normalize_scrape_result` |
| **SearchHit（搜索候选）** | 概念见 [CONTEXT.md](../CONTEXT.md)。候选包含 `source_id/title/url/canonical_url/content/providers/provider_ranks/rrf_score/relevance_score/body_available`；`relevance_score` 恒为 `null` 除非模型重排实际打分。公共响应在排序后补充抓取状态或 `body_error`，正文由同一 `source_id` 的抓取结果提供。 | `multi_search_mcp/src/search/candidate.py` / `multi_search_mcp/src/search_web.py` |
| **response_id / source_id** | `response_id` 标识一次候选搜索；`source_id` 稳定标识该响应中的 canonical URL，并作为 `fetch_source` / `read_source` 的引用。 | `multi_search_mcp/src/search/candidate.py` / `multi_search_mcp/src/state/source_registry.py` |
| **provider_rank / RRF** | 保留 provider 内部原始名次；同一 query 先做等权 RRF，expanded query 再按 query 排名做第二级 RRF，默认等权。`k=40`，两级均无中间截断，最终最多 15 条。provider 原生 score 只保留为诊断，正文不改变排序。`k` 固定且计入 `FUSION_ALGORITHM` 快照指纹，不作为配置项暴露。 | `multi_search_mcp/src/search/search_runner.py` / `multi_search_mcp/src/search/candidate.py` |
| **ranking（重排配置块）** | 概念见 [CONTEXT.md](../CONTEXT.md)。设置顶层 `ranking` 对象控制可选模型重排，键为 `mode`（`rrf` 默认 / `rrf_model`）、`reranker_profile_id`（默认 `jev_default`，须已在 core 注册）、`candidate_limit`（默认 50，10–200）、`batch_size`（默认 20，1–50）、`rerank_timeout`（默认 5 秒，1–60）；区间与桌面端一致，未知键、错误类型与越界值是 `ConfigError`，不静默忽略。`rrf_k`/`top_k`/`keep_per_source` 按评审结论刻意不提供。`SearchWebRequest.ranking` / `MultiSearchRequest.ranking` 可按请求覆盖同名键。 | `multi_search_mcp/src/search/rerank.py` → `RerankPolicy.from_config` / `multi_search_mcp/src/support/requests.py` |
| **重排（rerank）** | 概念见 [CONTEXT.md](../CONTEXT.md)。`ranking.mode="rrf_model"` 时，RRF 先融合出最多 `candidate_limit` 条候选，模型给每条打 `relevance_score`（[0,1]），被打分候选按分数降序写回原 RRF 槽位（同分保持 RRF 顺序，未打分不动），随后截取前 15 条再抓正文。模型分不与 RRF 分相加；送入模型的字段只有 `source_id`/`url`/`title`/`content`/`published_at`，排序元信息不外发。 | `multi_search_mcp/src/search/rerank.py` → `apply_rerank` / `multi_search_mcp/src/search/candidates.py` → `run_search_candidates` |
| **reranker / 重排器** | `Reranker` Protocol 的实现，把一批候选映射为 `source_id -> [0,1]` 分数；`mode="rrf_model"` 且未显式注入 `reranker=` 时，core 按 `reranker_profile_id` 经 `build_reranker` 从唯一注册表 `RERANKER_PROFILES` 构造适配器（新增 profile 需在此注册）；显式注入优先，用于测试与离线回放。v1 唯一 profile `jev_default` → `JevReranker`（Typesafe Jev）：密钥存在时每次搜索都会外发请求，缺 key 时 fail-closed 按 `auth` 回退；密钥只读环境变量 `TYPESAFE_API_KEY`（endpoint 可用 `TYPESAFE_JEV_ENDPOINT` 改指），不落配置、不进凭据库轮换。其 wire format 未经在线核实（`docs.typesafe.ai` 在开发机解析到非公网地址），属待实测确认项。 | `multi_search_mcp/src/search/rerank.py` → `Reranker` / `RERANKER_PROFILES` / `build_reranker` / `JevReranker`；`multi_search_mcp/src/search/candidates.py` → `run_search_candidates` |
| **relevance_score（相关性分数）** | 概念见 [CONTEXT.md](../CONTEXT.md)。模型对单条候选的归一化评分，只对实际打分的候选写入；未打分或纯 RRF 响应恒为 `null`，展示层不渲染为 0。 | `multi_search_mcp/src/search/rerank.py` → `apply_rerank` / `multi_search_mcp/src/support/format.py` → `_relevance_suffix` |
| **mode_used / fallback_reason** | 响应级排序元数据：`mode_requested` 回显请求的 mode，`mode_used` 是实际生效的排序（`rrf` 或 `rrf_model`）；模型阶段任何失败（timeout/rate_limit/auth/invalid_response/unavailable）整体放弃重排、保留完整 RRF 顺序，记 `mode_used="rrf"` 与无凭据的 `fallback_reason`，绝不部分应用。CLI 的 `--rerank-profile` 未注册值（按 core `RERANKER_PROFILES` 校验，旧写法 `jev` 也属此类）与 `--rerank-profile` 不带 `--rerank` 是用法错误（退出码 2），不是静默回退。 | `multi_search_mcp/src/search/rerank.py` → `apply_rerank` / `multi_search_mcp/cli.py` → `_ranking_override` |
| **count（每源召回量）** | 控制每个搜索源请求多少结果，受该源上限约束；不控制融合后的最终 15 条限制。 | `multi_search_mcp/src/search/resolve.py` / `multi_search_mcp/src/search/candidate.py` |
| **scrape（抓正文）** | 搜索后自动获取最终 RRF 前 15 条正文，已有 URL 可直接抓取。旧 `scrape_top` / `scrape_per_source` 请求参数已移除；旧配置中的失效键会被忽略并给出弃用警告（`FutureWarning`）。 | `multi_search_mcp/src/search_web.py` → `run_search_web` / `multi_search_mcp/src/scrape/stage.py` → `run_ranked_fetch_stage` |
| **scrape backend（抓取后端）** | 抓正文用的后端，与搜索源不同。已知集合：`jina`、`exa`、`tavily`、`firecrawl`。 | `multi_search_mcp/src/support/backends.py` → `KNOWN_BACKENDS` |
| **抓取链（scrape_backends）** | 概念见 [CONTEXT.md](../CONTEXT.md)。设置顶层 `scrape_backends` 数组给出通用抓取的 fallback 顺序，取值为上述四个后端；重复项只保留首次出现，省略或 `null` 使用默认 `["jina", "exa", "tavily", "firecrawl"]`，空数组或未知名称是配置错误。需要 key 的后端（Exa、Tavily）缺 key 时运行时跳过；`fetch --backend` 只覆盖单次调用。Reddit / Twitter 按域名固定走专用抓取器。 | `multi_search_mcp/src/search/resolve.py` → `resolve_scrape_backends` / `multi_search_mcp/src/scrape/service.py` → `run_scrape_raw` |
| **site memory（站点抓取记忆）** | 概念见 [CONTEXT.md](../CONTEXT.md)。记录站点抓取结果、手动固定与冷却；排序以抓取链顺序为基线，手动固定的后端提前，冷却中的后端靠后，不按历史成功率自动重排。CLI 用 `site stats/set-preference/reset` 操作，桌面端「抓取设置」页读写同一状态。 | `multi_search_mcp/src/state/site_memory.py` → `SiteScraperMemory`，`multi_search_mcp/src/state/operations.py` 统一入口 |
| **dedup（去重）** | 两个搜索入口统一使用保守 canonical URL 后按 RRF 融合，同一 query、同一 provider 的重复 URL 只按最好名次投一票。跨 provider、跨 query 的贡献保留。 | `multi_search_mcp/src/search/candidate.py` |
| **ContentStore（正文缓存）** | 对后端本次返回的原始正文执行容量检查与持久化，再裁剪本次响应。`max_chars` 只限制返回预览，不能截短缓存；TTL、单对象/总容量（单对象按 UTF-8 字节计）、LRU 和 provider retention 继续生效。正文超过单对象上限时不截断存储：本次仍返回已取得正文，并标 `persisted=false` 与 `persist_error`，之后的 `read_source` 无法复用它。 | `multi_search_mcp/src/state/content_store.py` / `multi_search_mcp/src/scrape/fetch.py` → `run_fetch_source` |
| **SourceRegistry（来源注册表）** | 保存短期来源引用；每个注册批次在同一事务中删除已到期记录，按 `expires_at` 索引查找。没有后台定时器，应用停止时不会自动执行清理。 | `multi_search_mcp/src/state/source_registry.py` / `multi_search_mcp/src/state/state_store.py` |
| **fetch_source（按需抓取）** | 按 `source_id` 或显式 URL 抓一条正文；先查 ContentStore，未命中才调用现有 scraper 链。`full_content=False` 保留默认 20000 字符及显式 `max_chars` 限制；`True` 覆盖 `max_chars`，一次返回全部已取得文本，缓存容量与 retention 不变。目标 URL 统一执行 SSRF 校验。 | `multi_search_mcp/src/scrape/fetch.py` → `run_fetch_source` |
| **read_source（局部读取）** | 只读 ContentStore，支持 keyword/offset/limit，供定向查证缓存片段。`has_more` 仅表示缓存内还有更多字符，不代表原页面完整。缺失或过期时明确要求先调用 `fetch_source`，不会隐式联网；默认选读全文使用 `fetch_source(full_content=True)`。 | `multi_search_mcp/src/read.py` → `run_read_source` |
| **降级 / degradation** | route 的主源全部失败或无可用结果时，在结果里**显式标注**。当前所有 route 的 `degrade_to` 都为空，所以只会输出「primary providers unavailable」提示，不会自动切换到兜底源（兜底机制保留但未启用）。 | `multi_search_mcp/src/search/search_runner.py` → `ROUTE_META` 的 `degrade_to` ＋ `multi_search_mcp/src/search/formatting.py` → `route_degradation` |

| 术语 | 定义 | 代码出处 |
|---|---|---|
| **deadline / 池饱和** | provider 调用和正文抓取在有界守护线程池中执行，按整批截止时间收集结果。Python 不能强杀运行线程：到期的任务被 `abandon`（排队的取消、运行中的脱离并归还准入槽，脱离数量也有上限，预算耗尽时运行中的任务继续占槽直到返回），守护线程不阻塞进程退出。池满时返回「池饱和」错误而不是超时，文字上避开 timeout/deadline，避免 key 健康和站点记忆把本地饱和误判为慢 provider 或慢目标。 | `multi_search_mcp/src/support/concurrency.py` → `BoundedDaemonExecutor` / `pool_saturated_message` |
| **错误分类与 key 重试** | 公开结果行仍保留 `error_origin` / `error_type`。兼容读取器 `row_kind` 先读非空 kind，再读 error_type，最后兼容旧布尔标记；`row_origin` 先读非空 origin，再读 error_origin，缺失时可从 target 类别推导。结构化类别优先于错误文字，仅缺类别时才匹配文字；target 不触发 key 轮换、不写健康结果，缺 key 归为 `missing_key`。provider invalid/quota/rate-limit 可轮换下一个 key，直到成功、不再可重试或截止时间到期。 | `multi_search_mcp/src/support/auth.py` → `row_kind` / `row_origin` / `classify_error` / `is_key_retryable_error` |

## 5. Key 与状态

> Jina 凭据条目中的静态 `exhausted`（凭据库或 `~/.search-keys.json`）与 SQLite 状态库中的 `quota_exhausted` 是两层独立状态：前者是操作员维护的配置级静态排除，后者是运行时健康状态。配置仍启用不代表运行时一定可用；运行时暂不可用也不会自动改写配置。

| 术语 | 定义 | 代码出处 |
|------|------|---------|
| **key 轮换** | 同一 provider 有多个 key 时，按「未用过优先 → 最久未用（LRU）」挑选。`reserve()` 在 `BEGIN IMMEDIATE` 写事务内重新检查健康状态，按最新 `last_used_at` 选取仍可用的候选，并原子更新 `use_count` / `last_used_at`；没有可用候选时返回空。它分配调用尝试，不是独占租约，同一 key 可以并发使用。 | `multi_search_mcp/src/state/key_state.py` → `SQLiteKeyManager.candidates` / `SQLiteKeyManager.reserve` |
| **key 指纹** | 状态库与诊断只保存 `sha256:<8hex>` 形式的 key 指纹，不落明文或可逆片段。 | `multi_search_mcp/src/state/key_state.py` → `key_fingerprint` |
| **Jina 配置 `exhausted`** | Jina 凭据条目（凭据库或 `~/.search-keys.json`）中的静态排除标记，由操作员手动维护；为 `true` 时 `jina_config_keys()` 不会将该 key 交给轮换。它不是运行态状态，不由 HTTP 402 自动写入，也没有 24 小时恢复期。 | `multi_search_mcp/src/state/keys.py` → `jina_config_keys`；`multi_search_mcp/src/state/mark_exhausted.py` |
| **key 状态：active** | 运行态当前没有阻止使用的健康状态；若 `manually_disabled` 仍为真，候选选择仍会跳过；也不覆盖 Jina 配置中的静态 `exhausted` 排除。成功回报在通过 `started_at` 因果检查后写回 `active`；迟到成功不会清除请求开始后新写入的状态。 | `multi_search_mcp/src/state/key_state.py` → `ACTIVE` / `SQLiteKeyManager.record_result` |
| **key 状态：cooldown** | 运行态临时失败（如限流）；当前冷却 15 分钟，`cooldown_until` 未到期时跳过，期满后重新允许尝试。 | `multi_search_mcp/src/state/key_state.py` → `COOLDOWN` / `cooldown_until` |
| **key 状态：quota_exhausted** | 运行态收到配额/余额用尽信号；当前恢复期 24 小时，`exhausted_until` 未到期时跳过，期满后重新允许尝试。它不等于配置级 `exhausted`，不会写回凭据。 | `multi_search_mcp/src/state/key_state.py` → `QUOTA_EXHAUSTED` / `exhausted_until` |
| **key 状态：transient_invalid** | provider 的 invalid 分类失败会原子累加 `invalid_strikes`；无既存强状态时，前两次冷却 15 分钟，第三次升级为 `invalid`。已有 invalid/quota_exhausted/disabled 时保留其状态与期限。rate_limit、quota_exhausted 清零 strikes；success 只有通过因果检查才清零，timeout/network/未分类失败和 target 错误均不清零。显式健康 reset 也会清零 strikes。 | `multi_search_mcp/src/state/key_state.py` → `TRANSIENT_INVALID` / `INVALID_COOLDOWN` / `INVALID_STRIKE_LIMIT` / `SQLiteKeyManager.record_result` |
| **key 状态：invalid** | 运行态达到 invalid 计数阈值后的长期排除状态；候选选择会跳过，需调用 `reset_key_state` 或明确重置后才会重新使用。 | `multi_search_mcp/src/state/key_state.py` → `INVALID` / `SQLiteKeyManager.candidates` |
| **key 状态：disabled** | `status=disabled` 与 `manually_disabled` 是独立的阻止使用条件，都没有自动到期恢复。`keys reset` / `reset_key_state` 只重置运行态 status、期限和 strikes，不清除 `manually_disabled`；因此手动标记仍为真时即使 status 变成 active 也不能使用。当前 CLI/Core 没有解除该标记的专用命令，须由维护者显式维护状态库中的该标记，不能用健康 reset 代替。它也不等于 Jina 配置级 `exhausted`。 | `multi_search_mcp/src/state/key_state.py` → `SQLiteKeyManager.reset` / `SQLiteKeyManager.candidates` |
| **StateStore（状态库）** | SQLite 状态库，存 key 状态、站点记忆、短期 source registry 与 ContentStore，默认 `~/.multi-search/state.sqlite`。与存放凭据和设置的 `config.sqlite` 是两个文件。 | `multi_search_mcp/src/state/state_store.py` |
| **use_state（状态开关）** | 请求参数，CLI 对应 `--no-state`。`false` 时跳过 SQLite 状态、key 轮换、正文缓存与站点记忆，用于干净测试。 | `multi_search_mcp/src/support/requests.py` / `multi_search_mcp/src/state/runtime.py` |

失败写入保护不是简单的全序：rate_limit / invalid 失败保留既有 invalid、quota_exhausted、disabled 状态及其期限；quota_exhausted 失败保留既有 invalid、disabled 状态及 exhausted_until（其 cooldown_until 会清空）。invalid 失败仍原子累加 strikes；rate_limit / quota_exhausted 清零 strikes。timeout、network、未分类失败只累计失败次数并记录脱敏错误，不改状态、期限、strikes 或状态版本 updated_at；target 不写健康结果。success 总会记录成功次数，但若已有 updated_at 晚于该请求的 started_at，则保留状态、冷却、错误和 strikes；否则恢复 active、清冷却与 strikes。健康 reset 可重置运行态，但不解除手动禁用。期限到期只允许候选再尝试，不自动把数据库 status 改写为 active。

## 6. 入口与配置

| 术语 | 定义 | 代码出处 |
|------|------|---------|
| **Core 请求** | `search_web` 和 `multi_search` 共用 RRF 搜索及正文获取；`fetch_source` / `scrape_url` 可直接抓 URL，`read_source` 局部读缓存，另有状态/诊断能力。无 MCP 服务入口。 | `multi_search_mcp/src/service.py` |
| **CLI** | `multi-search` console entry；`search/fetch/read/doctor/sources/keys/site/migrate-legacy` 都直接调用同一 Core 和 StateStore，是唯一产品入口；按需启动并退出，不依赖 MCP 或常驻服务。 | `multi_search_mcp/cli.py` |
| **受管 CLI** | 概念见 [CONTEXT.md](../CONTEXT.md)。由桌面端把应用资源里的受控 bundle 装到当前用户目录：Windows 为 `%LOCALAPPDATA%\MultiSearch\cli\multi-search.exe`，macOS 为 `~/Library/Application Support/MultiSearch/cli/bin/multi-search`。两平台 bundle 都自带运行时（Windows 内置 CPython、macOS `runtime/bin/python3.12`），安装后不依赖仓库或系统 Python；写入前先比对 manifest 原始字节的 SHA-256 锚点再逐文件校验，Unix 还要求可执行位仍在，否则判为不可验证。 | `scripts/build_cli_bundle.py`（锚点） |
| **SKILL** | 给 agent 的薄自然语言触发层，告诉它何时调工具、传什么 route/sources。 | `skills/multi-search/SKILL.md` |
| **config（行为配置）** | 非敏感的默认值（route/count/timeout、路由组 `routes`、抓取链 `scrape_backends`、Twitter Cookie 模式等）。解析顺序：env `MULTI_SEARCH_CONFIG`（JSON 文件）→ `config.sqlite` 的 settings 记录（存在即权威，桌面端写入）→ `~/.multi-search/multi-search-config.json` → 源码树开发 fallback → 内置默认值；显式指定却不存在的文件是错误。 | `multi_search_mcp/src/support/config.py` → `resolve_config_path` |
| **credential store（凭据库）** | 概念见 [CONTEXT.md](../CONTEXT.md)。`config.sqlite` 中按 provider 保存、以当前用户 DPAPI 加密的凭据（含 Jina 与托管 Twitter Cookie）。Key 来源只判定一次：环境变量（`env`）> 凭据库（`credential_store`）> `~/.search-keys.json`（`keys_file`）；同一 provider 不跨来源合并，凭据库条目不可读时该 provider fail-closed、不回退明文文件。旧 Windows 凭据管理器条目只作 `migrate-legacy` 的显式迁移源。 | `multi_search_mcp/src/support/credential_store.py` / `multi_search_mcp/src/state/keys.py` |
| **Twitter Cookie 模式** | 概念见 [CONTEXT.md](../CONTEXT.md)。settings 的 `twitter_cookies_mode` 缺省为 `file`：按 `TWITTER_COOKIES_PATH` > 设置中的 `twitter_cookies_path` > keys 文件 `twitter` 条目读取明文 Cookie，不自动迁移。Windows 桌面显式导入后切换为 `managed`：独立 `twitter_cookies` 加密条目在实际调用时解密为字典交给 XKit，无临时明文文件，不属于 API-key 轮换集合，此模式下忽略 `TWITTER_COOKIES_PATH`。managed 缺失/损坏/非 Windows 一律 fail-closed，不回退 file。协议细节见 [Cookie 协议](../desktop/src-tauri/COOKIE-PROTOCOL.md)。 | `multi_search_mcp/src/state/runtime.py` → `load_runtime_keys` / `multi_search_mcp/src/providers/xkit.py` → `ManagedTwitterCookies` |
| **providers（调用方适配）** | 第三方 SDK/服务的调用封装：XKit（Twitter/X 搜索与帖子抓取、托管 Cookie 装配）与 Tavily。搜索器和抓取器通过这里取得客户端，不直接拼装凭据。 | `multi_search_mcp/src/providers/xkit.py` / `multi_search_mcp/src/providers/tavily.py` |

## 维护约定

- 从仓库根目录执行 `uv run --locked python scripts/check_glossary_paths.py`，检查每个代码出处文件存在、README / 文档索引 / 本表的本地链接可解析；CI 的 Python 与 locked-regression 作业都会运行它。
- 改了 `ROUTE_PROFILES` / `ALL_SOURCE_NAMES` / `SOURCE_ALIASES` / `KNOWN_BACKENDS` 等常量，**同步更新本表对应行**。
- 新概念先在这里定义，再在 README / SKILL 里引用，避免同一概念多处各说一套。
- 「概念性」标注的术语不要写进代码注释当成字段名。
