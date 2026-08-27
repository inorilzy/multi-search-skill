# 术语表 (Glossary)

> 本文件是 multi-search 项目概念的**单一事实来源**。新增或改名一个概念时，先改这里。
>
> 标注了「代码出处」的术语，其权威定义在对应代码里；本表只是它的中文解释。
> 标注「概念性」的术语在代码里**没有对应字段**，只是为了方便描述而约定的说法，不要去代码里找它。

## 1. 核心概念

| 术语 | 定义 | 代码出处 |
|------|------|---------|
| **source（搜索源）** | 单个搜索后端，最小调用单位。如 `brave`、`github_repos`、`youtube`。 | `search_runner.py` → `ALL_SOURCE_NAMES` |
| **source 别名** | source 的对外友好写法，调用时会被归一化。如 `github` → `github_repos`、`reddit-browser` → `reddit_browser`。 | `search_runner.py` → `SOURCE_ALIASES` |
| **route（路由）** | 一组预设 source，负责粗粒度选源。`search_web` 的搜索深度由操作本身表达；兼容入口 `multi_search` 还会读取同名 route_meta。 | `search_runner.py` → `ROUTE_PROFILES` |
| **profile（源集合）** | 某个 route 对应的那组 source 集合。`profile` 和 `route` 常被混用，但严格说 profile 只指「源集合」这一部分。 | `ROUTE_PROFILES` 的 value |
| **route_meta（兼容行为参数）** | `multi_search` 的 route 默认值：抓几个、超时、返回数量、降级源、是否让 provider 内联正文等。请求值和用户 config 仍可覆盖。`search_web` 固定为候选模式，不运行批量 scrape。 | `search_runner.py` → `ROUTE_META` / `DEFAULT_ROUTE_META` |
| **want_content（正文内联）** | `multi_search` 兼容入口的 route_meta 字段。`True` 时让支持的 provider 返回正文。`search_web` 不开启它；正文由 `fetch_source` 显式获取。 | `search_runner.py` → `ROUTE_META["fast"]` |

## 2. route 分类（概念性，非代码标签）

> 代码里**没有**「通用 / 专用」这个字段。这只是按 source 性质做的概念划分，便于描述。

| 类别 | 包含 route | 说明 |
|------|-----------|------|
| **通用搜索** | `default` / `web`、`fast`、`all` | 用综合搜索引擎，什么主题都能搜。`fast` 只跑“搜索 API 自带正文”的 provider 且不抓取；`all` 是尽可能广的非视频召回。 |
| **专用搜索** | `social`、`dev`、`cn-community`、`vertical`、`video` | 绑定垂直平台，只搜特定领域。 |

> 注意：旧的 `level`（fast/normal）维度已删除。`fast` 现在是一个 route。

各 route 当前定义（以 `ROUTE_PROFILES` 为准，可能随代码变动）：

| route | 类别 | source 集合 |
|-------|------|------------|
| `default` / `web` | 通用 | brave + parallel + tavily + exa + serpapi + firecrawl + baidu |
| `fast` | 通用 | baidu + tavily + firecrawl + exa（`scrape_top=0`、`want_content=True`） |
| `all` | 通用 | default 的源 + twitter + stackoverflow + github_repos + hackernews + zhihu + v2ex + linuxdo（不含 video） |
| `social` | 专用 | twitter |
| `dev` | 专用 | stackoverflow + github_repos + hackernews |
| `cn-community` | 专用 | zhihu + v2ex + linuxdo |
| `vertical` | 专用 | reddit_browser（浏览器登录态 Reddit 搜索，正文/评论内联，`scrape_top=0`） |
| `video` | 专用 | youtube + bilibili |

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
| **content（结果摘要）** | 单条结果的紧凑摘要。`SearchHit.content` 是新公共字段；旧结果仍兼容 `description`。正文不会写进这个字段。 | `search/candidate.py` / `SearchResult.description` |
| **content_kind（内容语义）** | 明确区分 `metadata`、`content`（平台正文）、`excerpt`、`body`、`answer`。ScrapePlanner 根据 capability + content_kind 决策，不再按字符数猜正文。 | `support/models.py` / `search/capabilities.py` |
| **body / full_content（正文）** | 旧 `multi_search` 的兼容正文别名；底层仍兼容 `scraped_content`。新 `search_web` 不返回正文，只返回 `body_available` 和 `content_ref`。 | `SearchResult.scraped_content` / `search/candidate.py` |
| **SearchHit（紧凑候选）** | `search_web` 的稳定公共投影：`source_id/title/url/canonical_url/content/providers/provider_ranks/rrf_score/body_available`。不含正文。 | `search/candidate.py` |
| **response_id / source_id** | `response_id` 标识一次候选搜索；`source_id` 稳定标识该响应中的 canonical URL，并作为 `fetch_source` / `read_source` 的引用。 | `search/candidate.py` / `state/source_registry.py` |
| **provider_rank / RRF** | 保留 provider 内部原始名次；同一 query 先做等权 RRF，expanded query 再按 query 排名做第二级 RRF。provider 原生 score 只保留为诊断。 | `search/search_runner.py` / `search/candidate.py` |
| **scrape（抓正文）** | 搜索拿到链接后，再抓取页面正文。是否抓、抓几个由 `scrape_top` 控制（0 = 不抓）。 | `service.py` `_run_scrape_stage` |
| **scrape backend（抓取后端）** | 抓正文用的后端，与搜索源不同。已知集合：`jina`、`exa`、`tavily`、`firecrawl`。 | `scrape.py` → `KNOWN_BACKENDS` |
| **site memory（站点抓取记忆）** | 记录每个站点用哪个 scraper 成功率高，下次优先用它。 | `state/site_memory.py` → `SiteScraperMemory` |
| **dedup（去重）** | 旧 `multi_search` 通过 `deduplicate` 合并；`search_web` 使用保守 canonical URL 后按 RRF 融合，同一 provider 的重复 URL 只投一票。 | `support/dedup.py` / `search/candidate.py` |
| **ContentStore（正文缓存）** | SQLite 短期正文缓存，按 content hash 去重，带 TTL、单对象/总容量限制和 LRU；provider retention 决定是否写入。 | `state/content_store.py` |
| **fetch_source（按需抓取）** | 按 `source_id` 或显式 URL 抓一条正文；先查 ContentStore，未命中才调用现有 scraper 链。目标 URL 统一执行 SSRF 校验。 | `service.py` → `run_fetch_source` |
| **read_source（局部读取）** | 只读 ContentStore，支持 keyword/offset/limit。缺失或过期时明确要求先调用 `fetch_source`，不会隐式联网。 | `service.py` → `run_read_source` |
| **降级 / degradation** | route 的主源全部失败或无可用结果时，在结果里**显式标注**。当前所有 route 的 `degrade_to` 都为空，所以只会输出「primary providers unavailable」提示，不会自动切换到兜底源（兜底机制保留但未启用）。 | `ROUTE_META` 的 `degrade_to` ＋ `service.py` `_route_degradation` |

## 5. Key 与状态

| 术语 | 定义 | 代码出处 |
|------|------|---------|
| **key 轮换** | 同一 provider 有多个 key 时，按「未用过优先 → 最久未用（LRU）」挑选。每次选中更新 `last_used_at` / `use_count`。 | `state/key_state.py` → `SQLiteKeyManager.candidates` |
| **key 状态：active** | 正常可用。 | `key_state.py` → `ACTIVE` |
| **key 状态：cooldown** | 临时失败（如限流），冷却期内跳过。 | `key_state.py` → `COOLDOWN` |
| **key 状态：quota_exhausted** | 配额用尽，恢复期内跳过。 | `key_state.py` → `QUOTA_EXHAUSTED` |
| **key 状态：invalid** | key 无效，跳过。 | `key_state.py` → `INVALID` |
| **key 状态：disabled** | 被手动禁用，跳过。 | `key_state.py` → `DISABLED` |
| **StateStore（状态库）** | SQLite 状态库，存 key 状态、站点记忆、短期 source registry 与 ContentStore，默认 `~/.multi-search/state.sqlite`。 | `state/state_store.py` |
| **use_state（状态开关）** | 工具参数。`false` 时跳过 SQLite 状态、key 轮换、站点记忆，用于干净测试。 | `tools.py` / `service.py` |

## 6. 入口与配置

| 术语 | 定义 | 代码出处 |
|------|------|---------|
| **MCP 工具** | 候选优先入口为 `search_web`、`fetch_source`、`read_source`；`multi_search`、`scrape_url` 保留兼容，另有状态/诊断工具。 | `multi_search_mcp/server.py` |
| **CLI** | `multi-search` console entry；`search/fetch/read/doctor/keys` 都直接调用同一 Core 和 StateStore，不反向调用 MCP。 | `multi_search_mcp/cli.py` |
| **SKILL** | 给 agent 的薄自然语言触发层，告诉它何时调工具、传什么 route/sources。 | `skills/multi-search/SKILL.md` |
| **config（行为配置）** | 非敏感的默认值（route/count/timeout 等）。解析顺序：env `MULTI_SEARCH_CONFIG` → `~/.multi-search/multi-search-config.json` → 源码树 fallback。 | `support/config.py` → `resolve_config_path` |
| **keys file（密钥文件）** | 明文 API key / cookie，只从环境变量和 `~/.search-keys.json` 读取，**不**放进 config。 | `state/keys.py` |

## 维护约定

- 改了 `ROUTE_PROFILES` / `ALL_SOURCE_NAMES` / `SOURCE_ALIASES` / `KNOWN_BACKENDS` 等常量，**同步更新本表对应行**。
- 新概念先在这里定义，再在 README / SKILL 里引用，避免同一概念多处各说一套。
- 「概念性」标注的术语不要写进代码注释当成字段名。
