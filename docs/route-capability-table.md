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
| `body` / `full_content` | 已抓取或 provider 预取的页面正文/长文本 | `scraped_content` | 专家模式证据、最终综合总结 |

## 通用搜索能力矩阵

| Provider | Docs 原始字段 | `summary` | `content` | `title/url` | `body/full_content` | depth 适配 | Scrape 策略 | 建议路由 | 说明 |
|---|---|---:|---:|---:|---:|---|---|---|---|
| baidu | `choices[].message.content`、`references[].title/url/snippet/content/markdown_text` | 是 | 是 | 是 | 是 | `fast/normal` -> `web_summary`；`deep` -> `chat/completions + enable_deep_search` | prefetch | 快速、专家、中文 Web | 和刚才测试一致：answer 行作为 `summary`，references 作为结果；`snippet/content` 进 `content`，`markdown_text/content` 进 `body`。 |
| tavily | `answer`、`results[].title/url/content/raw_content` | 是 | 是 | 是 | deep 是 | `fast` -> `search_depth=fast`；`normal` -> `basic answer`；`deep` -> `advanced answer + raw_content=markdown` | prefetch | 快速、专家 | docs 明确 `content` 是 short description，`raw_content` 才是 cleaned/parsed HTML content。 |
| exa | `results[].title/url/highlights/text/summary`、Contents API `text/highlights/summary` | 否 | 是 | 是 | 是 | `fast` -> `type=fast + highlights`；`normal` -> `auto + highlights`；`deep` -> `deep + highlights + text` | prefetch | 快速、专家、发现 | Exa 的 highlights 很适合当 `content`；`text` 是正文。官方还支持 LLM summaries，但当前 searcher 没单独产 answer 行。 |
| brave | `web.results[].title/url/description/extra_snippets` | 否 | 是 | 是 | 否 | `fast` 不开 extra snippets；`normal/deep` 开 `extra_snippets` | candidate | 发现、专家 | docs 的 `description` 和 `extra_snippets` 都是摘要/片段，不是正文。正文需要后续 scrape。 |
| serpapi | `organic_results[].title/link/snippet`、`knowledge_graph.description` | 有时 | 是 | 是 | 否 | `fast` -> `google_light`；`normal/deep` -> 配置 engine | candidate | 快速、新闻、发现 | organic result 的 `link` 归一到 `url`，`snippet` 归一到 `content`；Knowledge Graph 可形成 `summary`。 |
| firecrawl | `web[].title/url/description/snippet`、`markdown` with `scrapeOptions` | 否 | 是 | 是 | deep 是 | `fast/normal` 只 search；`deep` 加 `scrapeOptions.formats=["markdown"]` | candidate / deep prefetch | 专家、域名搜索 | docs 说明 search 默认返回 title/description/url，加 `scrapeOptions` 才返回 full-page markdown。 |
| deepseek-web | answer、引用 URL、snippet | 是 | 是 | 是 | 否 | 不适配统一 depth 参数，作为 answer source | candidate | 快速、新闻、答案 | 原生联网回答，适合 fast；严肃任务要抓 URL 正文复核。 |
| glm-web | answer、引用 URL、web_search_results | 是 | 是 | 是 | 是 | 不适配统一 depth 参数，作为 answer source | prefetch | 快速、新闻、答案 | 本地 glm2api 服务返回总结、引用和部分正文。 |

## 专用搜索能力矩阵

| Provider | `summary` | `content` | `title/url` | `body/full_content` | Scrape 策略 | 认证方式 | 当前 key 轮换 | 建议路由 | 说明 |
|---|---:|---:|---:|---:|---|---|---|---|---|
| github-repos | 否 | 是 | 是 | 否 | candidate | 可选 api_key | 不接入 | 发现、技术 | repo description/metadata 进 `content`，README 正文靠后续 scrape。 |
| twitter | 否 | 是 | 是 | 是 | prefetch | cookie | 不接入 SQLite key 轮换 | 讨论 | tweet 文本本身就是平台内容，可作为 `body`；互动数据是元数据。 |
| reddit-oauth | 否 | 是 | 是 | 是 | prefetch | token/CLI | 不接入 SQLite key 轮换 | 讨论 | API thread/post 文本可作为平台正文。 |
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

`level`（fast/normal）维度已删除。是否让 provider 在搜索响应里直接返回正文，
由 route_meta 的 `want_content` 控制，目前只有 `fast` 路由开启（`want_content=True`、`scrape_top=0`）。

- **作用范围**：`want_content` 只传给支持内联正文的 4 个 provider（baidu / tavily / exa / firecrawl）。其它 searcher 不接受该参数，会被 `call_optional_timeout` 按签名静默忽略。
- **Tavily**：`want_content=True` 时设 `include_raw_content="markdown"` 回填正文；`search_depth` 固定为 `basic`。
- **Exa**：`want_content=True` 时请求 `contents={"text": True}` 拿全文，否则只取 `highlights`；`type` 固定为 `auto`。
- **Firecrawl**：`want_content=True` 时追加 `scrapeOptions.formats=["markdown"]` 回填正文（`body`），否则只做 search。
- **Baidu**：走 `web_summary` 端点，原生返回 answer + 引用 snippet/正文。
- **想“召回 + 再抓正文”**：用 `route=default` 搭配 `scrape_top=N`，由 scrape 阶段统一抓正文。

## 最终 Route 设计

| Route | Provider 组合 | 默认 scrape | 行为目标 |
|---|---|---:|---|
| `default` / `web` | `brave`, `tavily`, `exa`, `serpapi` | 8 | 保守默认事实搜索，不混入平台源。 |
| `fast` | `baidu`, `tavily`, `firecrawl`, `exa` | 0 | 只跑“搜索 API 自带正文”的 provider（`want_content=True`），不额外抓取。缺 key 时只显示该源的 error row，不跨路由降级。 |
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
