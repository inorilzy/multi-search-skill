# 术语表 (Glossary)

> 本文件是 multi-search 项目概念的**单一事实来源**。新增或改名一个概念时，先改这里。
>
> 标注了「代码出处」的术语，其权威定义在对应代码里；本表只是它的中文解释。
> 标注「概念性」的术语在代码里**没有对应字段**，只是为了方便描述而约定的说法，不要去代码里找它。

## 1. 核心概念

| 术语 | 定义 | 代码出处 |
|------|------|---------|
| **source（搜索源）** | 单个搜索后端，最小调用单位。如 `brave`、`github_repos`、`youtube`。 | `search_runner.py` → `ALL_SOURCE_NAMES` |
| **source 别名** | source 的对外友好写法，调用时会被归一化。如 `github` → `github_repos`、`deepseek-web` → `deepseek_web`。 | `search_runner.py` → `SOURCE_ALIASES` |
| **route（路由）** | 一组预设 source ＋ 一套源相关行为参数的组合，**只决定搜哪些源**。用户用 `route="dev"` 这种粗粒度方式选源。 | `search_runner.py` → `ROUTE_PROFILES` |
| **profile（源集合）** | 某个 route 对应的那组 source 集合。`profile` 和 `route` 常被混用，但严格说 profile 只指「源集合」这一部分。 | `ROUTE_PROFILES` 的 value |
| **route_meta（行为参数）** | route 除源之外的**源相关**行为：默认抓几个、超时、返回数量、降级源等。**不含搜索深度**（深度归 `level` 管）。 | `search_runner.py` → `ROUTE_META` / `DEFAULT_ROUTE_META` |
| **level（深度）** | 与 route **正交**的维度，**只控制搜索深度/抓取/是否要 provider answer**，不换源。`fast`=用 provider 自带 summary（不抓正文）；`normal`=返回 URL 抓取后由主模型总结（默认）；`expert`=用 provider deep 参数、多抓正文，但**已返回 summary 的源不重抓**（见下表）。 | `search_runner.py` → `LEVEL_META` / `DEFAULT_LEVEL` |

## 2. route 分类（概念性，非代码标签）

> 代码里**没有**「通用 / 专用」这个字段。这只是按 source 性质做的概念划分，便于描述。

| 类别 | 包含 route | 说明 |
|------|-----------|------|
| **通用搜索** | `default` / `web` | 用综合搜索引擎（brave/tavily/exa/serpapi 等），什么主题都能搜。 |
| **专用搜索** | `social`、`dev`、`cn-community`、`video` | 绑定垂直平台，只搜特定领域。 |

> 注意：`fast`/`expert` 现在**不再是 route**，已迁移为 `level`（深度维度）。

各 route 当前定义（以 `ROUTE_PROFILES` 为准，可能随代码变动）：

| route | 类别 | source 集合 |
|-------|------|------------|
| `default` / `web` | 通用 | brave + tavily + exa + serpapi |
| `social` | 专用 | twitter + reddit_oauth |
| `dev` | 专用 | stackoverflow + github_repos + hackernews |
| `cn-community` | 专用 | zhihu + v2ex + linuxdo |
| `video` | 专用 | youtube + bilibili |

各 level 当前定义（以 `LEVEL_META` 为准）：

| level | search_depth | provider answer | 抓取 |
|-------|--------------|-----------------|------|
| `fast` | fast | 是（show_answer） | 不抓（scrape_top=0） |
| `normal`（默认） | normal | 否 | 走 route 默认，抓所有候选 |
| `expert` | deep | 否 | 多抓（scrape_top=20），但**已给出 summary 的源（tavily/exa/baidu/serpapi/glm_web/deepseek_web）不重抓其 URL**，只抓无 summary 的源（github/zhihu/...）。由 `LEVEL_META["expert"]["skip_summarized_sources"]` 控制。 |

## 3. 选源方式

| 术语 | 定义 | 代码出处 |
|------|------|---------|
| **route 选源** | 不传 `sources`，按 `route` 取一组预设源。粗粒度。 | `service.py` → `resolve_route` |
| **sources 选源** | 调用时显式传 `sources=["github"]`，精确点名要哪些源。**优先级高于 route，会忽略 route。** | `service.py` `run_multi_search` |
| **route 优先级** | 实际生效的 route：`request.route` → 配置 `type` → 默认 `"default"`。 | `service.py` `run_multi_search` |
| **level 优先级** | 实际生效的 level：`request.level` → 配置 `level` → 默认 `"normal"`。 | `service.py` `run_multi_search` |

## 4. 抓取与结果处理

| 术语 | 定义 | 代码出处 |
|------|------|---------|
| **summary（直接总结）** | provider 针对整个 query 生成的答案/总结，不属于某一条普通搜索结果。如 Tavily `answer`、Baidu answer 行、SerpAPI Knowledge Graph description。快速搜索优先使用它，但严肃结论仍应结合 URL/正文核查。 | `SearchResult` dict 中通常是 `source=*answer` + `answer` |
| **title（结果标题）** | 单条搜索结果标题，用于展示和后续抓取候选。 | `SearchResult.title` / dict `title` |
| **url（结果链接）** | 单条搜索结果的目标 URL，是后续 scrape 正文的入口。 | `SearchResult.url` / dict `url` |
| **content（结果摘要）** | 单条搜索结果的短摘要、snippet、highlight 或 provider 对该条结果的简短描述。注意：这是 multi-search 对外统一语义；各 provider 文档里的 `content` 不一定代表同一件事。现有代码字段名仍是 `description`。 | `SearchResult.description` / dict `description` |
| **body / full_content（正文）** | 已抓取或 provider 预取的页面正文/长文本。Tavily `raw_content`、Firecrawl `markdown`、Exa `text` 更接近这个概念。现有代码字段名是 `scraped_content`。 | `SearchResult.scraped_content` / scrape result `markdown` |
| **scrape（抓正文）** | 搜索拿到链接后，再抓取页面正文。是否抓、抓几个由 `scrape_top` 控制（0 = 不抓）。 | `service.py` `_run_scrape_stage` |
| **scrape backend（抓取后端）** | 抓正文用的后端，与搜索源不同。已知集合：`jina`、`exa`、`tavily`、`firecrawl`。 | `scrape.py` → `KNOWN_BACKENDS` |
| **site memory（站点抓取记忆）** | 记录每个站点用哪个 scraper 成功率高，下次优先用它。 | `state/site_memory.py` → `SiteScraperMemory` |
| **dedup（去重）** | 跨源合并重复结果，并按共识排序。 | `support/dedup.py` → `deduplicate` |
| **降级 / degradation** | route 的主源失败时，退回兜底源，并在结果里显式标注。如 `social degraded to ...`。 | `ROUTE_META` 的 `degrade_to` ＋ `service.py` `_route_degradation` |

## 5. Key 与状态

| 术语 | 定义 | 代码出处 |
|------|------|---------|
| **key 轮换** | 同一 provider 有多个 key 时，按「未用过优先 → 最久未用（LRU）」挑选。每次选中更新 `last_used_at` / `use_count`。 | `state/key_state.py` → `SQLiteKeyManager.candidates` |
| **key 状态：active** | 正常可用。 | `key_state.py` → `ACTIVE` |
| **key 状态：cooldown** | 临时失败（如限流），冷却期内跳过。 | `key_state.py` → `COOLDOWN` |
| **key 状态：quota_exhausted** | 配额用尽，恢复期内跳过。 | `key_state.py` → `QUOTA_EXHAUSTED` |
| **key 状态：invalid** | key 无效，跳过。 | `key_state.py` → `INVALID` |
| **key 状态：disabled** | 被手动禁用，跳过。 | `key_state.py` → `DISABLED` |
| **StateStore（状态库）** | SQLite 状态库，存 key 状态和站点记忆，默认 `~/.multi-search/state.sqlite`。 | `state/state_store.py` |
| **use_state（状态开关）** | 工具参数。`false` 时跳过 SQLite 状态、key 轮换、站点记忆，用于干净测试。 | `tools.py` / `service.py` |

## 6. 入口与配置

| 术语 | 定义 | 代码出处 |
|------|------|---------|
| **MCP 工具** | 暴露给 agent 的入口函数：`multi_search`、`scrape_url`、`list_sources`、`doctor` 等。 | `mcp/server.py` |
| **SKILL** | 给 agent 的薄自然语言触发层，告诉它何时调工具、传什么 route/sources。 | `multi-search-plugin/skills/multi-search/SKILL.md` |
| **config（行为配置）** | 非敏感的默认值（route/count/timeout 等）。解析顺序：env `MULTI_SEARCH_CONFIG` → `~/.multi-search/multi-search-config.json` → 源码树 fallback。 | `support/config.py` → `resolve_config_path` |
| **keys file（密钥文件）** | 明文 API key / cookie，只从环境变量和 `~/.search-keys.json` 读取，**不**放进 config。 | `state/keys.py` |

## 维护约定

- 改了 `ROUTE_PROFILES` / `ALL_SOURCE_NAMES` / `SOURCE_ALIASES` / `KNOWN_BACKENDS` 等常量，**同步更新本表对应行**。
- 新概念先在这里定义，再在 README / SKILL 里引用，避免同一概念多处各说一套。
- 「概念性」标注的术语不要写进代码注释当成字段名。
