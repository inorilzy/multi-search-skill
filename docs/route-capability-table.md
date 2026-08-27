# multi-search 路由能力表

这份文档用于重新设计 multi-search 的 route。重点不是代码风格，而是回答几个产品和架构问题：

- 每个 search provider 到底能返回什么？
- 哪些 provider 适合快速模式？
- 哪些 provider 需要进入专家模式，先抓 URL 正文再总结？
- 哪些 provider 只是发现链接、社区讨论或视频搜索？
- 哪些 key 能被 SQLite 状态管理轮换，哪些不能？

## 路由模式定义

| 模式 | 产品目标 | 典型输出 | scrape 阶段 | 适合场景 |
|---|---|---|---|---|
| 快速模式 | 尽快给出可用答案 | provider 总结 + URL + 短摘要 | 默认关闭或只抓少量 top URL | 新闻速览、快速查询、当前背景、初步调研 |
| 专家模式 | 给出更可审计的答案 | URL 清单 + 网页正文 + 主模型综合总结 | 默认开启，抓取更深 | 技术决策、方案比较、事实核查、架构 review、争议问题 |
| 发现模式 | 找候选来源，不强制总结 | 排序 URL、摘要、元数据 | 可选 | 找项目、找资料源、找 repo、找文章 |
| 讨论模式 | 找社区/社交反馈 | 帖子、评论、热度、讨论链接 | 默认关闭或只使用 provider 预取内容 | 大家怎么说、用户反馈、社区评价、踩坑经验 |
| 视频模式 | 找视频/教程 | 标题、URL、频道/平台元数据、摘要 | 关闭 | 视频、教程、演示内容 |

## 统一结果字段

这部分是所有 search provider 的对外统一契约。不同官方文档会把字段叫作 `content`、`snippet`、`description`、`raw_content`、`markdown`，但进入 multi-search 后必须归一：

| 统一字段 | 含义 | 当前代码字段 | 后续用途 |
|---|---|---|---|
| `summary` | provider 针对整个 query 生成的直接答案/总结 | answer 行的 `answer` | 快速搜索直接回答；作为深搜线索 |
| `title` | 单条搜索结果标题 | `title` | 展示、去重辅助、抓正文标题 |
| `url` | 单条搜索结果链接 | `url` | 后续 scrape 的入口 |
| `content` | 单条搜索结果摘要/snippet/highlight，不是网页全文 | `description` | 快速预览、轻量引用、排序辅助 |
| `content_kind` | `metadata/content/excerpt/body/answer` 的显式语义 | `content_kind` | capability 驱动的正文/抓取决策 |
| `body` / `full_content` | 旧 `multi_search` 的兼容正文别名 | `scraped_content` | 兼容调用方；新 SearchHit 不携带正文 |
| `source_id` | 一次 `response_id` 内 canonical URL 的稳定引用 | `SearchHit.source_id` | `fetch_source` / `read_source` |
| `provider_ranks` / `rrf_score` | provider 原始名次与跨源 RRF 共识分 | `SearchHit` | 与完成顺序、正文长度解耦的排序 |

`search_web` 只输出紧凑 `SearchHit`。即使 provider 搜索阶段返回了 body，
公共响应也只给出 `body_available=true` 和 `content_ref`；允许留存时正文进入
短期 ContentStore，再由 `fetch_source` / `read_source` 按需读取。

## 通用搜索能力矩阵

| Provider | Docs 原始字段 | `summary` | `content` | `title/url` | `body/full_content` | depth 适配 | Scrape 策略 | 建议路由 | 说明 |
|---|---|---:|---:|---:|---:|---|---|---|---|
| baidu | `choices[].message.content`、`references[].title/url/snippet/content/markdown_text` | 是 | 是 | 是 | 是 | `fast/normal` -> `web_summary`；`deep` -> `chat/completions + enable_deep_search` | prefetch | 快速、专家、中文 Web | 和刚才测试一致：answer 行作为 `summary`，references 作为结果；`snippet/content` 进 `content`，`markdown_text/content` 进 `body`。 |
| tavily | `answer`、`results[].title/url/content/raw_content` | 是 | 是 | 是 | deep 是 | `fast` -> `search_depth=fast`；`normal` -> `basic answer`；`deep` -> `advanced answer + raw_content=markdown` | prefetch | 快速、专家 | docs 明确 `content` 是 short description，`raw_content` 才是 cleaned/parsed HTML content。 |
| exa | `results[].title/url/highlights/text/summary`、Contents API `text/highlights/summary` | 否 | 是 | 是 | 是 | `fast` -> `type=fast + highlights`；`normal` -> `auto + highlights`；`deep` -> `deep + highlights + text` | prefetch | 快速、专家、发现 | Exa 的 highlights 很适合当 `content`；`text` 是正文。官方还支持 LLM summaries，但当前 searcher 没单独产 answer 行。 |
| brave | `web.results[].title/url/description/extra_snippets` | 否 | 是 | 是 | 否 | `fast` 不开 extra snippets；`normal/deep` 开 `extra_snippets` | candidate | 发现、专家 | docs 的 `description` 和 `extra_snippets` 都是摘要/片段，不是正文。正文需要后续 scrape。 |
| parallel | `results[].title/url/publish_date/excerpts` | 否 | 是 | 是 | 否 | 固定 Search API `mode=fast` | candidate | 默认、发现、专家 | `excerpts` 是 LLM 优化压缩摘录，不是完整正文；使用 GA `/v1/search`。 |
| serpapi | `organic_results[].title/link/snippet`、`knowledge_graph.description` | 有时 | 是 | 是 | 否 | `fast` -> `google_light`；`normal/deep` -> 配置 engine | candidate | 快速、新闻、发现 | organic result 的 `link` 归一到 `url`，`snippet` 归一到 `content`；Knowledge Graph 可形成 `summary`。 |
| firecrawl | `web[].title/url/description/snippet`、`markdown` with `scrapeOptions` | 否 | 是 | 是 | deep 是 | `fast/normal` 只 search；`deep` 加 `scrapeOptions.formats=["markdown"]` | candidate / deep prefetch | 专家、域名搜索 | docs 说明 search 默认返回 title/description/url，加 `scrapeOptions` 才返回 full-page markdown。 |

## 专用搜索能力矩阵

| Provider | `summary` | `content` | `title/url` | `body/full_content` | Scrape 策略 | 认证方式 | 当前 key 轮换 | 建议路由 | 说明 |
|---|---:|---:|---:|---:|---|---|---|---|---|
| github-repos | 否 | 是 | 是 | 否 | candidate | 可选 api_key | 不接入 | 发现、技术 | repo description/metadata 进 `content`，README 正文靠后续 scrape。 |
| twitter | 否 | 是 | 是 | 是 | prefetch | cookie | 不接入 SQLite key 轮换 | 讨论 | tweet 文本本身就是平台内容，可作为 `body`；互动数据是元数据。 |
| reddit-oauth | 否 | 是 | 是 | 是 | prefetch | token/CLI | 不接入 SQLite key 轮换 | 讨论 | **未实现**（设计预留）。当前 reddit 仅作为 scrape backend，无 OAuth 搜索源。 |
| reddit | 否 | 是 | 是 | 否 | candidate | firecrawl api_key | 通过 firecrawl 轮换 | 讨论、专家 | Firecrawl 搜 Reddit，thread 正文仍建议 scrape。 |
| hackernews | 否 | 是 | 是 | 否 | candidate | 无 | 无 key | 讨论、技术 | HN 标题、URL、points/comments 适合发现讨论源。 |
| stackoverflow | 否 | 是 | 是 | 否 | candidate | 无 | 无 key | 技术 | Q&A 发现源，正文靠 scrape 或 StackExchange API 扩展。 |
| zhihu | 否 | 是 | 是 | 否 | candidate | mixed | 部分接入 | 讨论、中文 Web | 有凭证时可取更好摘要，否则走 Firecrawl fallback。 |
| v2ex | 否 | 是 | 是 | 否 | candidate | firecrawl api_key | 通过 firecrawl 轮换 | 讨论、中文技术 | 通过 Firecrawl 搜 V2EX。 |
| linuxdo | 否 | 是 | 是 | 否 | candidate | firecrawl api_key | 通过 firecrawl 轮换 | 讨论、中文技术 | 通过 Firecrawl 搜 Linux Do。 |
| linuxdo-api | 否 | 是 | 是 | 是 | prefetch | cookie | 不接入 SQLite key 轮换 | 讨论、中文技术 | API/cookie 可直接得到帖子内容。 |
| youtube | 否 | 是 | 是 | 否 | skip | api_key | 接入 | 视频 | 只做视频搜索，scrape 默认关闭。 |
| bilibili | 否 | 是 | 是 | 否 | skip | 可选 api_key/cookie | 不接入 SQLite key 轮换 | 视频 | 中文视频搜索，scrape 默认关闭。 |
| jina | 否 | 否 | 否 | 是 | scraper | 可选 api_key | 仅 active key 池 | 专家模式抓正文阶段 | 不是搜索 provider，只负责 URL -> Markdown/text。 |

## want_content 行为与注意事项

`level`（fast/normal）维度已删除。`want_content` 只服务于兼容入口
`multi_search`，目前只有 `fast` route 开启。候选入口 `search_web` 固定传
`want_content=False` 且不运行 scrape stage；读取深度由 `fetch_source` /
`read_source` 显式表达。

- **作用范围**：`want_content` 只传给支持内联正文的 4 个 provider（baidu / tavily / exa / firecrawl）。其它 searcher 不接受该参数，会被 `call_optional_timeout` 按签名静默忽略。
- **Tavily**：`want_content=True` 时设 `include_raw_content="markdown"` 回填正文；`search_depth` 固定为 `basic`。
- **Exa**：`want_content=True` 时请求 `contents={"text": True}` 拿全文，否则只取 `highlights`；`type` 固定为 `auto`。
- **Firecrawl**：`want_content=True` 时追加 `scrapeOptions.formats=["markdown"]` 回填正文（`body`），否则只做 search。
- **Baidu**：走 `web_summary` 端点，原生返回 answer + 引用 snippet/正文。
- **想“召回 + 再抓正文”**：用 `route=default` 搭配 `scrape_top=N`，由 scrape 阶段统一抓正文。

## 最终 Route 设计

> 以代码为准（route A）：下表已同步到 `search_runner.py` 的 `ROUTE_PROFILES` /
> `ROUTE_META` 实际值。原设计稿（收窄 `default`、`expert`、`reddit_oauth` 等）见
> `docs/route-redesign-plan.md` 顶部「实际落地差异」。

| Route | Provider 组合 | `multi_search` 默认 scrape | 行为目标 |
|---|---|---:|---|
| `default` / `web` | `brave`, `parallel`, `tavily`, `exa`, `serpapi`, `firecrawl`, `baidu` | 20 | 默认事实搜索；广 web 召回。 |
| `fast` | `baidu`, `tavily`, `firecrawl`, `exa` | 0 | 只跑“搜索 API 自带正文”的 provider（`want_content=True`），不额外抓取。缺 key 时只显示该源的 error row，不跨路由降级。 |
| `all` | `default` 的源 + `twitter`, `stackoverflow`, `github_repos`, `hackernews`, `zhihu`, `v2ex`, `linuxdo` | 30 | 尽可能广的非视频召回（不含 video）。 |
| `social` | `twitter` | 0 | 社交反馈、用户评价、讨论热度。 |
| `dev` | `github_repos`, `stackoverflow`, `hackernews` | 20 | 技术资料、项目、实现方案搜索。默认不要混入纯社交源。 |
| `cn-community` | `zhihu`, `v2ex`, `linuxdo` | 20 | 中文社区反馈、中文技术讨论。 |
| `video` | `youtube`, `bilibili` | 0 | 视频/教程搜索。 |

单 provider 调用不再放进 `ROUTE_PROFILES`，统一走 `sources` 参数，例如 `sources=["brave"]` 或 `sources=["github"]`。

上表的 scrape 默认值不适用于 `search_web`；后者对所有 route 都是 0。

## 直接总结 vs 抓正文后总结

### Provider 直接总结

适合放在快速模式。

优点：

- 延迟低，链路短，失败点少。
- 很适合新闻速览、当前背景、快速了解一个问题。
- Baidu、Tavily 可以直接返回答案和引用 URL，不需要再跑完整 scrape。
- 成本更低，也更少遇到网页反爬、正文抽取失败、超时等问题。

风险：

- Provider 已经替主模型筛选和压缩了一次网页，主模型看到的是二手总结。
- 如果 route 不抓正文，主模型无法完整核查证据。
- 引用 URL 不一定完全支撑 provider 的总结。
- 出错时更难 debug，因为错误可能发生在 provider 的内部搜索/总结过程中。

### 抓 URL 正文后由主模型总结

适合放在专家模式。

优点：

- 更可审计：主模型能直接看到网页正文。
- 更适合高风险判断、技术方案比较、事实核查和争议问题。
- dedup、跨来源一致性、引用证据会更有意义。
- 最终回答更容易说明“这个结论来自哪些原文”。

风险：

- 更慢、更贵。
- 失败模式更多：网页被拦、正文抽取质量差、scraper 超时、页面噪声大。
- 占用更多上下文。
- 最终质量依赖 scrape 选择和正文抽取质量。

## 建议

把“直接总结 + URL + 摘要”作为快速模式的核心能力，但不要让它成为唯一证据路径。

推荐默认行为：

| 模式 | 默认行为 |
|---|---|
| 普通 / 快速 | `search_web` 返回候选；只对支撑回答所需的少量 `source_id` 调 `fetch_source` / `read_source`。 |
| 专家模式 | `search_web` 扩展查询后按需读证据；用户明确要批量正文或一调用聚合时才用 `multi_search(scrape_top=N)`。 |
| 新闻模式 | 不单独设 route；查询包含时间语义，保留 provider failure diagnostics，并为主要结论读取可点击来源。 |

实践规则：

- 用户问“发生了什么 / 快速总结 / 最新情况 / news”：`search_web(route=fast)`，再按需读少量来源。
- 用户问“比较 / 决策 / 验证 / 架构 review / 为什么 / 给证据”：`search_web(route=default, expand=[...])`，对关键 `source_id` 做 fetch/read。
- 用户问“给我链接 / 找来源”：`search_web(route=web)`；明确找 repo/Q&A/HN 时走 `dev`。
- 用户问“大家怎么说 / 评价 / 社区反馈 / 踩坑”：走 `social` 或 `cn-community`。

## 已确定边界

| 问题 | 结论 |
|---|---|
| route 是否表达读取深度？ | 否。route 选源；`search_web`、`fetch_source`、`read_source` 表达逐步读取。 |
| 何时使用批量 scrape？ | 仅显式深度/批量需求走兼容 `multi_search(scrape_top=N)`。 |
| provider body 如何进入上下文？ | 受 retention policy 约束写入短期 ContentStore，再按 `source_id` 局部读取。 |
