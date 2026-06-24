# multi-search-skill

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

并行聚合搜索 skill：一条命令同时调用 Web 搜索、Google SERP、代码仓库、Twitter/X 讨论，并按需要补抓网页正文，最后输出适合 agent 阅读的 Markdown。

> 当前 canonical 运行时是 **薄 skill + MCP plugin**：`multi-search-plugin/mcp/src/` 承载搜索、抓取、key 状态管理和站点抓取器记忆；薄 skill 只负责自然语言触发与 route 选择策略。旧的 `scripts/` / `search.py` CLI 路径已删除，MCP plugin 是唯一入口。

## MCP / 插件入口

本仓库现在包含 Codex 插件元数据和 MCP server。正式插件入口在 `multi-search-plugin/`：

```powershell
python multi-search-plugin/mcp/server.py
```

插件相关文件：

- `multi-search-plugin/.codex-plugin/plugin.json`：插件 manifest。
- `multi-search-plugin/.mcp.json`：MCP server 启动配置。
- `multi-search-plugin/skills/multi-search/SKILL.md`：薄 skill，自然语言触发和使用策略。

> 根目录不再保留独立的 `.mcp.json` / `.codex-plugin` / `skills` / `SKILL.md` / `mcp` shim。
> canonical 入口只有 `multi-search-plugin/`，避免双 manifest 与 skill route 漂移。

MCP tools 包括：`multi_search`、`scrape_url`、`list_sources`、`doctor`、`get_key_status`、`reset_key_state`、`get_site_scraper_stats`、`set_site_scraper_preference`、`reset_site_scraper_stats`。

边界约定：明文 key 只从环境变量和 `~/.search-keys.json` 读取；非敏感行为配置放在 `multi-search-plugin/multi-search-config.json`；运行状态默认保存在 `~/.multi-search/state.sqlite`。`.mcp.json` 和 plugin manifest 只负责启动 server，不保存 secret。

当前默认行为：`default` 是 `web` 的兼容别名，跑 Brave、Tavily、Exa、SerpAPI；默认额外抓取最多 8 个缺正文 URL。Tavily / Exa 已带回的正文会直接复用，不重复抓、不消耗 `scrape_top`。需要快速总结用 `fast`，需要更深证据用 `expert`。

## 适用场景

- 让 agent 一次性查多个来源，而不是只依赖单一搜索 API。
- 对技术方案、开源项目、社区讨论、踩坑反馈做交叉验证。
- 把搜索结果和可抓取网页正文整理成适合 agent 阅读的 Markdown。

不适合：

- 需要稳定 SLA 的生产搜索服务。
- 绕过登录墙、付费墙或平台访问限制。
- 直接把第三方网页正文当作可信指令执行。

## 快速开始

canonical 运行时是 **MCP plugin**（`multi-search-plugin/`）。把它作为 MCP server 注册给 agent 后，调用 `doctor` / `multi_search` 等 tools：

```powershell
git clone https://github.com/inorilzy/multi-search-skill.git
cd multi-search-skill
# MCP server 入口见 multi-search-plugin/.mcp.json（python mcp/server.py）
```

核心搜索只依赖 Python 3.10+ 标准库。Twitter/X 需要额外安装：

```powershell
python -m pip install twikit-ng
```

## Agent 安装和使用

skill 入口在 [multi-search-plugin/skills/multi-search/SKILL.md](multi-search-plugin/skills/multi-search/SKILL.md)，可以作为 Claude Code / Codex 这类 agent 的技能说明入口。典型用法是让 agent 读取 skill 后执行：

```text
用 multi-search 查一下最近大家怎么评价某个 LLM 框架，重点看 GitHub、Twitter/X 和技术博客。
```

MCP plugin 是唯一入口，agent 按 plugin 的 `skills/multi-search/SKILL.md` 调用 MCP tools。所有能力都落在 `multi-search-plugin/mcp/src/`。

## 搜索源、注册和免费额度

免费额度来自当前公开页面或常见免费层，可能被服务商调整；以各平台控制台为准。

| 源 | 用途 | 注册地址 | 免费额度 / 说明 | 本地请求上限 |
|---|---|---|---|---:|
| Brave Search | Web 搜索，snippet，额外抓取优先源 | https://brave.com/search/api/ | 约 1,000 次/月；通常需要邮箱 + 信用卡 | 20 |
| Tavily | Web 搜索 + answer，可带 raw markdown，也是抓取后端 | https://tavily.com | 约 1,000 次/月；邮箱注册 | 20 |
| Exa | 搜索 + `contents.text`，也是抓取后端 | https://exa.ai | 约 1,000 次/月；邮箱注册 | 100 |
| Firecrawl | Web metadata search；有 key 时可作为抓取 fallback | https://firecrawl.dev | 约 1,000 次/月；CLI 默认 count 10；搜索默认只取 metadata，抓取阶段仅在配置 key 后进入 fallback 链 | 100 |
| Zhihu | Zhihu OpenAPI search | https://developer.zhihu.com | 优先用官方 `zhihu_search` API；无 `zhihu` key 时可 fallback 到 Firecrawl `includeDomains` | 10 |
| Reddit | Reddit domain-restricted search + remote-first 抓取 | https://firecrawl.dev | 搜索用 Firecrawl `includeDomains`；`www.reddit.com` 优先 Jina，`old.reddit.com` 优先 Tavily，本地 old.reddit 只做最后兜底 | 100 |
| YouTube | YouTube video search | https://console.cloud.google.com/apis/library/youtube.googleapis.com | 官方 YouTube Data API；metadata only，不抓视频正文 | 50 |
| Bilibili | Bilibili video search | https://search.bilibili.com | 公开视频搜索接口；cookie 可选；metadata only，不抓视频正文 | 50 |
| SerpAPI Google Light | Google SERP | https://serpapi.com/users/sign_up?plan=free | 250 次/月；`google_light` 默认更省 | 100 |
| GitHub Repos | 仓库搜索 | https://github.com/settings/tokens | REST API 常见免费额度：未认证约 60 req/hour，token 约 5,000 req/hour；也可 fallback 到已登录 `gh` CLI | 100 |
| Hacker News | Hacker News story search | https://hn.algolia.com/api | 匿名可用，使用 Hacker News Algolia 搜索接口 | 100 |
| Stack Overflow | Stack Overflow question search | https://api.stackexchange.com/docs/advanced-search | 匿名可用，使用 Stack Exchange advanced search | 100 |
| Twitter/X | 社交讨论、推文和 top replies | https://x.com | 无官方搜索 API 免费层；使用 `twikit-ng` + cookies，受账号状态和限流影响 | 20 |
| Jina Reader | 额外网页正文抓取 | https://r.jina.ai/docs | 匿名可用，约 20 rpm；key 是固定额度，可作为匿名限流后的 fallback | scrape only |

## 路由

| Route | Sources | 适合场景 |
|---|---|---|
| `default` / `web` | Brave + Tavily + Exa + SerpAPI | 普通事实搜索；默认 route |
| `fast` | DeepSeek Web + GLM Web + Tavily + Exa | 快速总结、新闻速览、当前背景；默认不额外抓正文 |
| `expert` | Brave + Tavily + Exa + SerpAPI + Firecrawl | 需要证据的调研、比较、架构 review；默认抓取更多正文 |
| `social` | Twitter/X + Reddit OAuth | 看社交反馈、口碑、讨论 |
| `dev` | Stack Overflow + GitHub Repos + Hacker News | 技术问题、仓库、工程讨论 |
| `cn-community` | Zhihu + V2EX + Linux Do | 中文社区讨论 |
| `video` | YouTube + Bilibili | 搜视频；默认 title/url-only，不进入网页抓取 |
| 单源 | 通过 `sources` 参数，例如 `sources=["brave"]`、`sources=["github"]`、`sources=["deepseek-web"]` | 控 quota 或调试；不再使用单源 route |

缺 key 的源会显示 error row，不会静默消失。`fast` 的 DeepSeek/GLM 这类 cookie/session 源不可用时会显式标注降级到 Tavily/Exa。GitHub 没 token 时可用 `gh auth login` 后 fallback。Twitter/X 依赖、cookies、认证或限流失败时只影响 Twitter/X，其它源继续输出。

## Keys

把 key 放到 `~/.search-keys.json`，不要提交到仓库：

```json
{
  "brave": "BSAxxxx",
  "tavily": ["tvly-key1", "tvly-key2"],
  "exa": ["exa-key1", "exa-key2"],
  "jina": [
    {"key": "jina_xxx_optional_1", "exhausted": false}
  ],
  "firecrawl": "fc-xxxx",
  "zhihu": "your_zhihu_access_secret",
  "youtube": "your_youtube_api_key",
  "bilibili": "optional_cookie",
  "serpapi": "xxxx",
  "github": "ghp_xxxx",
  "twitter": {"auth_token": "...", "ct0": "..."}
}
```

环境变量会覆盖同名配置：

```text
BRAVE_SEARCH_API_KEY / BRAVE_API_KEY
TAVILY_API_KEY
EXA_API_KEY
JINA_API_KEY / JINA_KEY
FIRECRAWL_API_KEY
ZHIHU_ACCESS_SECRET
YOUTUBE_API_KEY
BILIBILI_COOKIE
SERPAPI_API_KEY / SERPAPI_KEY
GITHUB_TOKEN / GH_TOKEN
TWITTER_COOKIES_PATH
```

多数 key 字段支持 string 或 string array。Jina 支持 `{ "key": "...", "exhausted": true|false }`；只有余额接口确认 `wallet.total_balance <= 0` 时才会自动标记 exhausted。需要手动软删除 Jina key：

```powershell
python -m scripts.mark_exhausted <jina-key>
```

## 架构和术语

> 概念定义见术语表：[docs/glossary.md](docs/glossary.md)（route / source / 降级 / key 轮换等的单一事实来源）。

```mermaid
flowchart LR
    Q[MCP tool / skill] --> SVC[src/service.py]
    SVC --> SR[SearchRunner<br/>route · SQLite key state · timeout · fanout]
    SR --> S[Searcher 搜索器<br/>mcp/src/search/searchers/*]
    S --> M[Merger / Ranker<br/>mcp/src/support/dedup.py]
    M --> SP[ScrapePlanner 抓取规划器<br/>mcp/src/scrape/scrape_planner.py]
    SP --> SO[Scrape orchestration<br/>mcp/src/scrape/scrape.py]
    SO --> B[Scraper 抓取器 backend<br/>mcp/src/scrape/scrapers/*]
    B --> WB[正文回写 + 统一排序<br/>apply_scraped_content · rank_results]
    M --> WB
    WB --> R[Renderer 渲染器<br/>mcp/src/support/format.py]
    R --> O[Markdown diagnostics + results]
```

术语固定如下：

- **Service 服务层**：`multi-search-plugin/mcp/src/service.py`，统一 MCP 参数、config、key、search、scrape、render。
- **Searcher 搜索器**：`multi-search-plugin/mcp/src/search/searchers/*`，只负责 query -> `SearchResult`/dict，输出 title、url、description、source、score、raw metadata。
- **SearchRunner 搜索调度器**：`multi-search-plugin/mcp/src/search/search_runner.py`，负责 route、并发、timeout、SQLite key state 和 source status。
- **Merger/Ranker 合并排序器**：`multi-search-plugin/mcp/src/support/dedup.py`，负责 URL 归一化、去重、`also_from`、共识权重、canonical source 选择，以及统一排序（`rank_results`）。抓取成功的正文通过 `apply_scraped_content` 回写到对应结果条目的 `scraped_content`，因此 JSON `results` 与 markdown 看到的是同一份「已富集」结果，而不是空骨架 + 底部附录两套数据。`rank_results` 在 `service.py` 层统一执行一次，JSON `results`、markdown `Ranked Results`、`provider_status` 共享同一排序（优先级：错误置底 → 已抓取正文 → 共识权重 → 正文长度 → stars）。
- **ScrapePlanner 抓取规划器**：`multi-search-plugin/mcp/src/scrape/scrape_planner.py`，负责决定哪些 URL 需要抓、每源 quota、backend 顺序和 key 候选。
- **Scraper 抓取器 backend**：`multi-search-plugin/mcp/src/scrape/scrapers/*`，负责 url -> 正文。Jina、Exa、Tavily、Firecrawl、old.reddit 都是 backend。
- **Scrape orchestration 抓取调度执行器**：`multi-search-plugin/mcp/src/scrape/scrape.py`，负责单 URL fallback 链、站点策略和 key 使用结果记录。
- **Renderer 渲染器**：`multi-search-plugin/mcp/src/support/format.py`，负责诊断信息、搜索结果、抓取正文和 untrusted 安全围栏。
- **Cache 缓存**：`multi-search-plugin/mcp/src/support/cache.py`，默认关闭；启用后先缓存 scrape 结果。

## 抓取流程

关键规则：

- `scrape_top` 只计算额外抓取的缺正文 URL；已有正文不占额度。
- 默认抓取后端从可用能力构建：Jina 匿名优先；Exa / Tavily / Firecrawl 只有配置对应 key 后才进入 fallback 链。Reddit URL remote-first：`www.reddit.com` 走 Jina / Tavily / Exa / Firecrawl / old.reddit fallback，`old.reddit.com` 走 Tavily / Jina / Exa / Firecrawl / old.reddit fallback。Zhihu 搜索优先使用官方摘要结果，后续抓取知乎 URL 时仍会过滤“荒原页 / 登录墙”假正文。Jina 先匿名，匿名限流后才用 Jina key。
- Exa / Tavily / Firecrawl 在 search 和 scrape 中都走 SQLite key state：跳过 invalid / disabled / cooldown 未过期 / quota_exhausted 未过期；从未使用过的 key 优先；同等情况下按 `last_used_at` 最早优先；每次选中会更新 `last_used_at` 和 `use_count`。
- 每个候选 URL 只走一次完整 fallback 链；失败或 `scrape_timeout` 后记录 Errors，不自动补位。
- GitHub repo 根 URL 抓取时会改写到 raw README。

## 公共数据契约

代码仍兼容 dict，但核心边界已经有 dataclass：`SearchResult`、`ScrapeResult`、`ProviderStatus`、`ProviderError`，定义在 `multi-search-plugin/mcp/src/support/models.py`。

- `SearchResult`/dict：`source`、`title`、`url`、`description`、`scraped_content`、`also_from`、`stars`、`score`、`raw`。
- `ScrapeResult`/dict：`url`、`title`、`markdown`、`length`、`via`，可带 `cache`、backend chain 等 raw metadata。
- `ProviderStatus`/dict：`source`、`status`、`raw_hits`。
- `ProviderError`/dict：`source`、`error`，错误输出会尽量脱敏。

## 常用调用

通过 MCP `multi_search` tool 调用（以 JSON 入参示意）：

```jsonc
// 默认 default route + 额外抓取缺正文 URL
{ "query": "epub to markdown" }

// 快速总结源
{ "query": "agent memory", "route": "fast" }

// Twitter/X 讨论
{ "query": "Claude Code feedback", "route": "social" }

// 关闭额外抓取
{ "query": "latest Rust features", "scrape_top": 0 }

// 只额外抓 3 个缺正文 URL
{ "query": "rust async runtime", "scrape_top": 3 }

// 专用平台 route
{ "query": "vector database", "route": "dev" }
{ "query": "AI Agent", "route": "cn-community" }

// 视频搜索（默认只输出 title + URL，不抓视频）
{ "query": "agent memory tutorial", "route": "video" }

// 中文技术查询可以手动加英文扩展查询
{ "query": "agent 编排最佳实践", "expand": ["agent orchestration best practices multi-agent"], "route": "fast" }

// 指定单源
{ "query": "rust async runtime", "sources": ["brave", "exa"] }
```

## 配置和参数

非敏感默认值放在 [multi-search-config.json](multi-search-config.json)，MCP tool 入参优先级更高。

`multi_search` tool 最常用参数：

| 参数 | 默认 | 说明 |
|---|---:|---|
| `query` | — | 搜索查询（必填） |
| `route` | `default` | 语义 route：`web` / `fast` / `expert` / `social` / `dev` / `cn-community` / `video` |
| `sources` | — | 直接指定一个或多个源，绕过 route |
| `count` | per-source | 全局 count，会按各源上限 clamp |
| `timeout` | 60 | 搜索阶段整批 deadline |
| `scrape_top` | 30 | 额外抓取缺正文 URL 数，上限 30；传 0 关闭 |
| `scrape_chars` | provider | 单页抓取正文最大字符数 |
| `expand` | — | 额外扩展查询（list），常用于给中文查询补英文 |
| `use_state` | true | 是否使用 SQLite key 状态与站点抓取器记忆 |
| `output` | `both` | 输出形态：`json` / `markdown` / `both` |

`scrape_url` tool 用于单独抓取一个 URL，支持 `backends`、`scrape_chars`、`scrape_timeout`、`use_state` 等参数。

JSON 配置还支持缓存字段：`cache_enabled`、`no_cache`、`cache_ttl_seconds`、`cache_dir`。缓存默认关闭；启用后 scrape 文件写到 `.cache/multi-search/scrape/{hash}.json`，cache key 只包含 normalized URL、backend 顺序和重要 options，不写入 API key。

## 输出

输出包含：

- `Sources (raw hits)`：各源原始命中数。
- `Source Status`：OK / PARTIAL / ERROR。
- `URL Inventory`：去重后的 URL 和共识权重。
- `Errors`：缺 key、依赖问题、timeout、provider exception、抓取失败。
- `Ranked Results`：统一排序后的结果（错误置底 → 已抓取正文 → 共识权重 → 正文长度 → stars）；JSON `results` 与此顺序一致。
- `Scraped Content`：正文内容，统一包在 untrusted block 里。

Provider 参考文档保存在 [docs/](docs/)，agent 说明在 [multi-search-plugin/skills/multi-search/SKILL.md](multi-search-plugin/skills/multi-search/SKILL.md)。

## 安全

- 不要提交 `~/.search-keys.json`、`.env` 或真实 provider key。
- provider error 输出前会尽量 scrub 可能出现的 key 值。
- 第三方抓取正文始终按 untrusted data 处理。

## Troubleshooting

### 某个搜索源一直报错怎么办？

先调用 `doctor` tool 检查依赖和 key。缺 key、quota 用完、网络超时都会在 `Source Status` 和 `Errors` 中显示，不会静默吞掉。

### 为什么结果里没有 Twitter/X？

Twitter/X 需要额外依赖和 cookies。确认已安装 `twikit-ng`，并配置 `TWITTER_COOKIES_PATH` 或 `~/.search-keys.json` 中的 `twitter` 字段。

### 抓取正文太慢怎么办？

降低 `scrape_top`，或设 `scrape_top: 0` 只看搜索结果。正文抓取会受目标网站、Jina / Exa / Tavily / Firecrawl 状态和网络影响。

## License

[MIT](LICENSE)
