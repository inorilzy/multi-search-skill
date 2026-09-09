# multi-search 路由能力表

这份文档描述当前 route、搜索器能力和公共结果契约：

- 每个 search provider 到底能返回什么？
- 哪些 provider 适合快速模式？
- 搜索器摘要与排序后获取的 URL 正文如何区分？
- 哪些 provider 用于发现链接或社区讨论？
- 哪些 key 能被 SQLite 状态管理轮换，哪些不能？

## 路由模式定义

| 模式 | 产品目标 | 典型输出 | scrape 阶段 | 适合场景 |
|---|---|---|---|---|
| 快速模式 | 用较少搜索源获取信息 | 排序 URL + 摘要 + 正文预览 | RRF 最终前 15 条统一获取 | 新闻速览、快速查询、当前背景、初步调研 |
| 专家模式 | 给出更可审计的答案 | URL 清单 + 正文预览 + 按需读取更多片段 | 同上，结合扩展查询和缓存阅读 | 技术决策、方案比较、事实核查、架构 review、争议问题 |
| 发现模式 | 找候选来源，不强制总结 | 排序 URL、摘要、正文预览 | RRF 最终前 15 条统一获取 | 找项目、找资料源、找 repo、找文章 |
| 讨论模式 | 找社区/社交反馈 | 讨论链接、摘要、正文预览 | RRF 最终前 15 条统一获取 | 大家怎么说、用户反馈、社区评价、踩坑经验 |

## 统一结果字段

这部分是所有 search provider 的对外统一契约。不同官方文档会把字段叫作 `content`、`snippet`、`description`、`raw_content`、`markdown`，但进入 multi-search 后必须归一：

| 统一字段 | 含义 | 当前代码字段 | 后续用途 |
|---|---|---|---|
| `summary` | provider 针对整个 query 生成的直接答案/总结 | answer 行的 `answer` | 快速搜索直接回答；作为深搜线索 |
| `title` | 单条搜索结果标题 | `title` | 展示、抓正文标题 |
| `url` | 单条搜索结果链接 | `url` | 后续 scrape 的入口 |
| `content` | 单条搜索结果摘要/snippet/highlight，不是网页全文 | `description` | 快速预览、证据选择；不额外参与相关性评分 |
| `content_kind` | `metadata/content/excerpt/body/answer` 的显式语义 | `content_kind` | capability 驱动的正文/抓取决策 |
| `markdown` | RRF 后获取的正文预览，默认每篇最多 6000 字符 | `scrapes[].markdown`；展示模式为顶层 `markdown` | 阅读证据；完整取得的正文按策略缓存 |
| `source_id` | 一次 `response_id` 内 canonical URL 的稳定引用 | `SearchHit.source_id` | `fetch_source` / `read_source` |
| `provider_ranks` / `rrf_score` | provider 原始名次与跨源 RRF 共识分 | `SearchHit` | 与完成顺序、正文长度解耦的排序 |

`search_web` 与 `multi_search` 共用候选召回、两级 RRF 和正文获取流程。所有有效原始名次参与融合，不在源内或查询内截断 15 条；最终取前 15 条获取正文。成功时在候选上附 `body_available` / `body_truncated` / `body_backend`，失败保留原排名并附 `body_error`。正文只在关联的 `scrapes[].markdown` 中出现；展示模式将正文移至顶层 `markdown`。`content` 始终保留摘要，允许留存的完整正文进入短期 ContentStore，可通过 `read_source` 读取预览以外的片段。

## 通用搜索能力矩阵

| Provider | Docs 原始字段 | `summary` | `content` | `title/url` | API 正文能力 | 当前搜索调用 | 排序后正文 | 建议路由 | 说明 |
|---|---|---:|---:|---:|---:|---|---|---|---|
| baidu | `choices[].message.content`、`references[].title/url/snippet/content/markdown_text` | 是 | 是 | 是 | 是 | `web_summary` | 统一获取 | 快速、专家、中文 Web | answer 行用于 `summary`，references 作为候选；引用摘要与正文分开处理。 |
| tavily | `answer`、`results[].title/url/content/raw_content` | 是 | 是 | 是 | 是 | `search_depth=basic`、basic answer、`include_raw_content=false` | 统一获取 | 快速、专家 | `content` 是摘要；`raw_content` 是正文能力，公共召回阶段不请求。 |
| exa | `results[].title/url/highlights/text/summary`、Contents API `text/highlights/summary` | 否 | 是 | 是 | 是 | `type=auto`、highlights | 统一获取 | 快速、专家、发现 | highlights 作为摘要；全文通过排序后的抓取流程获取。 |
| brave | `web.results[].title/url/description/extra_snippets` | 否 | 是 | 是 | 否 | 启用 `extra_snippets` | 统一获取 | 发现、专家 | `description` 和 `extra_snippets` 都是摘要/片段，不是正文。 |
| parallel | `results[].title/url/publish_date/excerpts` | 否 | 是 | 是 | 否 | 固定 Search API `mode=fast` | 统一获取 | 默认、发现、专家 | `excerpts` 是压缩摘录，不是完整正文；使用 GA `/v1/search`。 |
| serpapi | `organic_results[].title/link/snippet`、`knowledge_graph.description` | 有时 | 是 | 是 | 否 | 使用配置的 engine | 统一获取 | 快速、新闻、发现 | `link` 归一到 `url`，`snippet` 归一到摘要；Knowledge Graph 可形成 `summary`。 |
| firecrawl | `web[].title/url/description/snippet`、`markdown` with `scrapeOptions` | 否 | 是 | 是 | 是 | Search 不携带 `scrapeOptions` | 统一获取 | 专家、域名搜索 | 搜索只请求候选；全文通过后续抓取获取。 |

## 专用搜索能力矩阵

下表的 candidate / prefetch 描述搜索器原始返回能力；公共流程始终对最终 RRF 前 15 条调用统一正文获取，有可用缓存时复用，不按该分类跳过最终结果。

| Provider | `summary` | `content` | `title/url` | 搜索器正文能力 | 原始返回策略 | 认证方式 | 当前 key 轮换 | 建议路由 | 说明 |
|---|---:|---:|---:|---:|---|---|---|---|---|
| github-repos | 否 | 是 | 是 | 否 | candidate | 可选 api_key | 不接入 | 发现、技术 | repo description/metadata 进 `content`，README 正文靠后续 scrape。 |
| twitter | 否 | 是 | 是 | 是 | prefetch | cookie | 不接入 SQLite key 轮换 | 讨论 | tweet 文本本身就是平台内容，可作为 `body`；互动数据是元数据。 |
| hackernews | 否 | 是 | 是 | 否 | candidate | 无 | 无 key | 讨论、技术 | HN 标题、URL、points/comments 适合发现讨论源。 |
| stackoverflow | 否 | 是 | 是 | 否 | candidate | 无 | 无 key | 技术 | Q&A 发现源，正文靠 scrape 或 StackExchange API 扩展。 |
| v2ex | 否 | 是 | 是 | 否 | candidate | 无 | 无 key | `all` 或显式 `sources=["v2ex"]` | SOV2EX 第三方专用索引 API；只返回标题、URL 和高亮摘要，忽略索引正文。默认 10 条，上限 50 条。 |
| linuxdo-api | 否 | 是 | 是 | 是 | prefetch | cookie | 不接入 SQLite key 轮换 | 讨论、中文技术 | API/cookie 可直接得到帖子内容。 |
| jina | 否 | 否 | 否 | 是 | scraper | 可选 api_key | 仅 active key 池 | 专家模式抓正文阶段 | 不是搜索 provider，只负责 URL -> Markdown/text。 |

## want_content 行为与注意事项

`level`（fast/normal）维度已删除。`want_content` 只保留为搜索器兼容字段；公共搜索召回固定传 `want_content=False`，先融合候选，再统一获取最终前 15 条正文。

- **作用范围**：`want_content` 只保留为历史兼容字段，不再作为正文开关。
- **Tavily / Exa / Firecrawl**：召回时不向这些 provider 请求正文，公共入口在 RRF 后统一获取正文。
- **Baidu**：仍可返回 answer + 引用 snippet，随后与其他候选一样进入 RRF 和正文获取。
- **V2EX / SOV2EX**：匿名 `GET /api/search`，使用 `sort=sumup` 按相关性召回；搜索阶段忽略 `_source.content`，仅返回标题、URL 和清理后的高亮摘要。最终入选 RRF 前 15 条后，再统一抓取原帖 URL 或复用此前 URL 抓取的正文缓存。此源不依赖 Firecrawl 搜索，也不是 V2EX 官方 API；索引收录和更新由第三方服务决定。
- **已有 URL**：直接走 `fetch_source(url=...)` / `scrape_url`；搜索得到的正文预览不足时用 `read_source` 局部读取缓存。

## 最终 Route 设计

> 以代码为准（route A）：下表已同步到 `search_runner.py` 的 `ROUTE_PROFILES` /
> `ROUTE_META` 实际值。原设计稿（收窄 `default`、`expert`等）见
> `docs/route-redesign-plan.md` 顶部「实际落地差异」。

| Route | Provider 组合 | 最终正文上限 | 行为目标 |
|---|---|---:|---|
| `default` / `web` | `brave`, `parallel`, `tavily`, `exa`, `serpapi`, `firecrawl`, `baidu` | 15 | 默认事实搜索；广 web 召回。 |
| `fast` | `baidu`, `tavily`, `firecrawl`, `exa` | 15 | 使用较少搜索源，排序后同样获取正文。缺 key 时记录错误，不跨路由降级。 |
| `all` | `default` 的源 + `twitter`, `stackoverflow`, `github_repos`, `hackernews`, `v2ex` | 15 | 尽可能广的 API 召回。 |
| `social` | `twitter` | 15 | 社交反馈、用户评价、讨论热度。 |
| `dev` | `github_repos`, `stackoverflow`, `hackernews` | 15 | 技术资料、项目、实现方案搜索。默认不要混入纯社交源。 |

当前共 13 个搜索源，`all` 包含 12 个；`linuxdo_api` 需显式选择。单 provider 调用不再放进 `ROUTE_PROFILES`，统一走 `sources` 参数，例如 `sources=["brave"]`、`sources=["github"]` 或 `sources=["v2ex"]`。

上表同时适用于 `search_web` 与 `multi_search`。`count` 仅控制每源召回；`scrape_top` / `scrape_per_source` 仍接受但不再二次裁剪或关闭抓取，显式传入时 diagnostics 会说明。

## 直接总结 vs 抓正文后总结

### Provider 直接总结

可作为定位线索；当前公共流程仍获取最终结果正文。

优点：

- 延迟低，链路短，失败点少。
- 很适合新闻速览、当前背景、快速了解一个问题。
- Baidu、Tavily 可以直接返回答案和引用 URL，供后续核对正文。
- 成本更低，也更少遇到网页反爬、正文抽取失败、超时等问题。

风险：

- Provider 已经替主模型筛选和压缩了一次网页，主模型看到的是二手总结。
- 如果正文获取失败，主模型无法只凭 provider 总结完整核查证据。
- 引用 URL 不一定完全支撑 provider 的总结。
- 出错时更难 debug，因为错误可能发生在 provider 的内部搜索/总结过程中。

### 抓 URL 正文后由主模型总结

当前所有公共搜索 route 都使用此流程；需要更深入核查时可扩展查询并读取更多缓存片段。

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

摘要用于快速定位，结论结合搜索自动取得的正文核实，必要时读取更多缓存片段。

推荐默认行为：

| 模式 | 默认行为 |
|---|---|
| 普通 / 快速 | `search_web` 返回 RRF 前 15 条与正文预览；预览不足时 `read_source`。 |
| 专家模式 | `search_web` 扩展查询后同样取最终前 15 条正文；对关键 `source_id` 读取更多证据。 |
| 新闻模式 | 不单独设 route；查询包含时间语义，保留 provider failure diagnostics，并为主要结论读取可点击来源。 |

实践规则：

- 用户问“发生了什么 / 快速总结 / 最新情况 / news”：`search_web(route=fast)`，使用自动返回的正文，必要时 `read_source`。
- 用户问“比较 / 决策 / 验证 / 架构 review / 为什么 / 给证据”：`search_web(route=default, expand=[...])`，对关键 `source_id` 做 fetch/read。
- 用户问“给我链接 / 找来源”：`search_web(route=web)`；明确找 repo/Q&A/HN 时走 `dev`。
- 用户问“大家怎么说 / 评价 / 社区反馈 / 踩坑”：走 `social`；V2EX 讨论可显式指定 `sources=["v2ex"]`，Linux Do 站内讨论可显式指定 `sources=["linuxdo_api"]`。

## 已确定边界

| 问题 | 结论 |
|---|---|
| route 是否表达读取深度？ | 否。route 选源；搜索统一取最终前 15 条正文，`read_source` 读取更多片段。 |
| 何时使用批量 scrape？ | 两个公共搜索入口都在 RRF 后自动执行；已有 URL 直接单页抓取。 |
| body 如何进入上下文？ | 默认返回最多 6000 字符预览；完整取得的正文受 retention 和容量策略约束写入 ContentStore，再按 `source_id` 局部读取。 |
