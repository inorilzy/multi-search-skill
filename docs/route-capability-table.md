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

## Provider 能力矩阵

| Provider | 类型 | 可搜索 | 直接总结 | URL | 摘要/snippet | 正文/content | Scrape 策略 | 认证方式 | 当前 key 轮换 | 建议路由 | 说明 |
|---|---|---:|---:|---:|---:|---:|---|---|---|---|---|
| deepseek-web | answer_searcher | 是 | 是 | 是 | 是 | 否 | candidate | cookie/token | 不接入 SQLite key 轮换 | 快速、新闻、答案 | DeepSeek 原生联网回答，可返回总结和引用 URL。需要 `DEEPSEEK_WEB_TOKEN` + cookie/export。很适合快速模式，但总结是 provider 已经加工过的，严肃场景需要核查引用。 |
| glm-web | answer_searcher | 是 | 是 | 是 | 是 | 是 | prefetch | 本地服务/可选 key | 不接入 SQLite key 轮换 | 快速、新闻、答案 | GLM 原生联网搜索回答，可返回总结、引用和部分正文。依赖本地 glm2api 服务。 |
| tavily | content_searcher | 是 | 是 | 是 | 是 | 是 | prefetch | api_key | 接入 | 快速、专家 | 混合能力很强：能返回答案、URL、摘要、内置页面文本。既适合快速模式，也适合专家模式。 |
| exa | content_searcher | 是 | 否 | 是 | 是 | 是 | prefetch | api_key | 接入 | 快速、专家、发现 | 语义搜索和内容获取较强。没有直接 answer 行，但经常能返回页面文本，减少额外 scrape 需求。 |
| serpapi | answer_searcher | 是 | 是 | 是 | 是 | 否 | candidate | api_key | 接入 | 快速、新闻、发现 | Google SERP/Knowledge Graph 风格元数据，有时有 answer。完整证据仍需要 scrape。 |
| brave | searcher | 是 | 否 | 是 | 是 | 否 | candidate | api_key | 接入 | 发现、专家 | 泛 Web 搜索，适合找新鲜 URL。不是直接总结源。 |
| firecrawl | searcher | 是 | 否 | 是 | 是 | 否 | candidate | api_key | 接入 | 专家、域名搜索 | 适合域名限定搜索和后续抓取生态。search 结果仍需要 scrape 才有完整正文。 |
| github-repos | platform_searcher | 是 | 否 | 是 | 是 | 否 | candidate | 可选 api_key | 不接入 | 发现、技术 | 找 GitHub 仓库和 repo 元数据，不是通用 Web 答案源。 |
| twitter | platform_searcher | 是 | 否 | 是 | 否 | 是 | prefetch | cookie | 不接入 SQLite key 轮换 | 讨论 | 返回社交文本和元数据，不是中立事实证据。除非用户要社交反馈，否则不建议放进默认事实搜索。 |
| reddit-oauth | platform_searcher | 是 | 否 | 是 | 否 | 是 | prefetch | token/CLI | 不接入 SQLite key 轮换 | 讨论 | 有授权时适合 Reddit 讨论内容，比纯网页搜索更直接。 |
| reddit | platform_searcher | 是 | 否 | 是 | 是 | 否 | candidate | firecrawl api_key | 通过 firecrawl 轮换 | 讨论、专家 | 通过 Firecrawl 搜 Reddit。可能仍需要 scrape 抓 thread 正文。 |
| hackernews | platform_searcher | 是 | 否 | 是 | 是 | 否 | candidate | 无 | 无 key | 讨论、技术 | 适合技术社区讨论、产品发布反馈。 |
| stackoverflow | platform_searcher | 是 | 否 | 是 | 是 | 否 | candidate | 无 | 无 key | 技术 | 适合 Q&A 发现，不是直接总结源。 |
| zhihu | platform_searcher | 是 | 否 | 是 | 是 | 否 | candidate | mixed | 部分接入 | 讨论、中文 Web | 有 Zhihu 凭证时用凭证，否则可走 Firecrawl fallback。 |
| v2ex | platform_searcher | 是 | 否 | 是 | 是 | 否 | candidate | firecrawl api_key | 通过 firecrawl 轮换 | 讨论、中文技术 | 通过 Firecrawl 搜 V2EX 社区讨论。 |
| linuxdo | platform_searcher | 是 | 否 | 是 | 是 | 否 | candidate | firecrawl api_key | 通过 firecrawl 轮换 | 讨论、中文技术 | 通过 Firecrawl 搜 Linux Do。 |
| linuxdo-api | platform_searcher | 是 | 否 | 是 | 否 | 是 | prefetch | cookie | 不接入 SQLite key 轮换 | 讨论、中文技术 | 通过 API/cookie 获取 Linux Do 内容。 |
| youtube | video_searcher | 是 | 否 | 是 | 是 | 否 | skip | api_key | 接入 | 视频 | 只做视频搜索，scrape 应关闭。 |
| bilibili | video_searcher | 是 | 否 | 是 | 是 | 否 | skip | 可选 api_key/cookie | 不接入 SQLite key 轮换 | 视频 | 中文视频搜索，scrape 应关闭。 |
| jina | scraper | 否 | 否 | 否 | 否 | 是 | scraper | 可选 api_key | 仅 active key 池 | 专家模式抓正文阶段 | 不是搜索 provider。用于把已知 URL 转成 Markdown/text。 |

## 最终 Route 设计

| Route | Provider 组合 | 默认 scrape | 行为目标 |
|---|---|---:|---|
| `default` / `web` | `brave`, `tavily`, `exa`, `serpapi` | 8 | 保守默认事实搜索，不混入平台源。 |
| `fast` | `deepseek_web`, `glm_web`, `tavily`, `exa` | 0 | 优先使用 provider 直接总结、URL 和摘要。快速返回“总结 + 来源”。DeepSeek/GLM 不可用时显式降级到 Tavily/Exa。 |
| `expert` | `brave`, `tavily`, `exa`, `firecrawl`, `serpapi` | 20 | 广泛搜索 URL，抓取正文，然后让主模型基于正文综合总结。 |
| `social` | `twitter`, `reddit_oauth` | 0 | 社交反馈、用户评价、讨论热度。 |
| `dev` | `github_repos`, `stackoverflow`, `hackernews` | 5 | 技术资料、项目、实现方案搜索。默认不要混入纯社交源。 |
| `cn-community` | `zhihu`, `v2ex`, `linuxdo` | 5 | 中文社区反馈、中文技术讨论。 |
| `video` | `youtube`, `bilibili` | 0 | 视频/教程搜索。 |

单 provider 调用不再放进 `ROUTE_PROFILES`，统一走 `sources` 参数，例如 `sources=["brave"]` 或 `sources=["github"]`。

## 直接总结 vs 抓正文后总结

### Provider 直接总结

适合放在快速模式。

优点：

- 延迟低，链路短，失败点少。
- 很适合新闻速览、当前背景、快速了解一个问题。
- DeepSeek、GLM、Tavily 可以直接返回答案和引用 URL，不需要再跑完整 scrape。
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
| 快速模式 | 优先使用 answer-capable providers。默认展示 provider 总结、引用 URL 和摘要。只有在摘要太弱或需要核实时，轻量抓取 top 1-3 个 URL。 |
| 专家模式 | 广泛搜索，抓取 top URL 正文，再由主模型基于正文综合。Provider answer 可以作为线索，不作为最终证据。 |
| 新闻模式 | 不单独设 route；从快速模式开始，在查询词中加入时间/最新语义。用户要求准确性、来源、细节时，改走专家模式。 |

实践规则：

- 用户问“发生了什么 / 快速总结 / 最新情况 / news”：走 `fast`。
- 用户问“比较 / 决策 / 验证 / 架构 review / 为什么 / 给证据”：走 `expert`。
- 用户问“给我链接 / 找来源”：走 `web`；明确找 repo/Q&A/HN 时走 `dev`。
- 用户问“大家怎么说 / 评价 / 社区反馈 / 踩坑”：走 `social` 或 `cn-community`。

## 待决策问题

| 问题 | 当前倾向 |
|---|---|
| `default` 应该是快速还是专家？ | `default` 是 `web` 的兼容别名；快速和专家必须显式选择。 |
| DeepSeek 要不要放进 `default`？ | 不建议。DeepSeek 依赖 cookie/token，放进 `fast` / `news` / `answer` 更清晰。 |
| answer 行是否默认显示？ | 对 `fast`、`news`、`answer`、`deepseek-web`、`glm-web` 应默认显示，不应该要求 `verbose=True`。 |
| snippet/摘要是否默认显示？ | 快速/新闻/答案 route 应默认显示。专家模式可以保持 URL 清单 + scraped content。 |
| DeepSeek token 要不要进入 key 轮换？ | 暂时不要假装它是普通 API key。应把浏览器态 session/cookie 和 API key pool 分开建模。 |
