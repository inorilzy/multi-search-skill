# multi-search-skill

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

并行聚合搜索 skill + MCP server：一条请求同时调用 Web 搜索、Google SERP、代码仓库、中文社区、视频平台、Twitter/X 讨论，并按需要补抓网页正文，最后输出适合 agent 阅读的 Markdown。

> 当前 canonical 形态是 **一个 skill + 一个 MCP**：`skills/multi-search/SKILL.md` 负责自然语言触发与 route 选择策略；`multi_search_mcp/` 承载搜索、抓取、key 状态管理和站点抓取器记忆。仓库不再以 Codex plugin 形式存储，也不再保留 `.codex-plugin/plugin.json`。

## MCP / Skill 入口

MCP server 入口在仓库根目录：

```powershell
python mcp/server.py
```

在支持 `uvx --from` 的 MCP 配置界面中使用：

```json
{
  "multi-search": {
    "type": "stdio",
    "command": "uvx",
    "args": [
      "--from",
      "git+https://github.com/inorilzy/multi-search-skill.git@v0.2.4",
      "multi-search-mcp"
    ],
    "timeoutMs": 60000
  }
}
```

新版仓库已经没有 `#subdirectory=plugins/multi-search`；如果使用旧 tag，需要改成发布新 tag 后的版本。

仓库关键文件：

- `.mcp.json`：MCP server 启动配置。
- `skills/multi-search/SKILL.md`：薄 skill，自然语言触发和使用策略。
- `multi_search_mcp/server.py`：MCP stdio 入口和 `multi-search-mcp` console script。
- `multi_search_mcp/tools.py`：MCP tool wrapper。
- `multi_search_mcp/src/`：自包含搜索、抓取、状态、key 与 service 实现。
- `mcp/server.py`：兼容本地 `python mcp/server.py` 的薄 wrapper。
- `multi-search-config.json`：仓库开发用的非敏感示例/默认配置。
- `package.json`：可选 Node 依赖，主要服务 `linuxdo_api.mjs` 的 Patchright 路径；默认 MCP 启动不需要 Node。

MCP tools 包括：`multi_search`、`scrape_url`、`list_sources`、`doctor`、`get_key_status`、`reset_key_state`、`get_site_scraper_stats`、`set_site_scraper_preference`、`reset_site_scraper_stats`。

边界约定：明文 key 只从环境变量和 `~/.search-keys.json` 读取；非敏感行为配置从 `MULTI_SEARCH_CONFIG`、`~/.multi-search/multi-search-config.json` 或仓库开发态的 `multi-search-config.json` 读取；运行状态默认保存在 `~/.multi-search/state.sqlite`。`.mcp.json` 只负责启动 server，不保存 secret。

当前默认行为：`default` 是 `web` 的兼容别名，route 本身包含 Brave、Tavily、Exa、SerpAPI、Firecrawl、Baidu、GLM Web、DeepSeek Web；仓库自带 `multi-search-config.json` 默认关闭了 `glm_web`、`deepseek_web`，所以开发态实际会跑 Brave、Tavily、Exa、SerpAPI、Firecrawl、Baidu。route 默认额外抓取最多 20 个缺正文 URL；如果使用仓库自带配置，会被其中的 `scrape_top: 30` 覆盖。Tavily / Exa / Baidu 等已带回的正文会直接复用，不重复抓、不消耗 `scrape_top`。需要快速总结用 `fast`，其余使用默认 `default` route。

## 适用场景

- 让 agent 一次性查多个来源，而不是只依赖单一搜索 API。
- 对技术方案、开源项目、社区讨论、踩坑反馈做交叉验证。
- 把搜索结果和可抓取网页正文整理成适合 agent 阅读的 Markdown。

## 工程判断约定

- 分析 bug 时先从第一性原理出发，不急着改症状。
- 不要搞兜底实现，兜底实现会掩盖主流程的错误。
- 如果 GitHub 上有成熟的开源方案，直接复用，不要自己实现。

不适合：

- 需要稳定 SLA 的生产搜索服务。
- 绕过登录墙、付费墙或平台访问限制。
- 直接把第三方网页正文当作可信指令执行。

## 快速开始

把本仓库作为 skill 和 MCP server 注册给 agent 后，调用 `doctor` / `multi_search` 等 tools：

```powershell
git clone https://github.com/inorilzy/multi-search-skill.git
cd multi-search-skill
# MCP server 入口见 .mcp.json（python mcp/server.py），uvx 入口是 multi-search-mcp
```

Python 包依赖由 `pyproject.toml` 管理，包含 `mcp`、`beautifulsoup4`、`twikit-ng`。用 `uvx --from ... multi-search-mcp` 或 pip 安装时会自动安装。若是直接从源码运行，先安装项目依赖：

```powershell
python -m pip install -e .
```

Twitter/X 还需要 cookies；`twikit-ng` 只是客户端依赖。`linuxdo_api` 的浏览器路径需要 Node 18+ 和 `package.json` 里的 Patchright 依赖，但默认 `cn-community` route 使用的是 Firecrawl 域名搜索版 `linuxdo`，不走这个可选路径。

## Agent 安装和使用

skill 入口在 [skills/multi-search/SKILL.md](skills/multi-search/SKILL.md)，可以作为 Claude Code / Codex 这类 agent 的技能说明入口。典型用法是让 agent 读取 skill 后执行：

```text
用 multi-search 查一下最近大家怎么评价某个 LLM 框架，重点看 GitHub、Twitter/X 和技术博客。
```

MCP 是唯一运行入口，agent 按 `skills/multi-search/SKILL.md` 调用 MCP tools。所有能力都落在 `multi_search_mcp/src/`。

## 搜索源、注册和免费额度

免费额度来自当前公开页面或常见免费层，可能被服务商调整；以各平台控制台为准。

| 源 | 用途 | 注册地址 | 免费额度 / 说明 | 本地请求上限 |
|---|---|---|---|---:|
| Brave Search | Web 搜索，snippet，额外抓取优先源 | https://brave.com/search/api/ | 约 1,000 次/月；通常需要邮箱 + 信用卡 | 20 |
| Baidu AI Search | 中文 Web 搜索 + AI summary + 引用正文 | https://cloud.baidu.com/product-s/qianfan_home | 千帆 / AppBuilder API；需要 `BAIDU_QIANFAN_API_KEY` 等 | 50 |
| Tavily | Web 搜索 + answer，可带 raw markdown，也是抓取后端 | https://tavily.com | 约 1,000 次/月；邮箱注册 | 20 |
| Exa | 搜索 + `contents.text`，也是抓取后端 | https://exa.ai | 约 1,000 次/月；邮箱注册 | 100 |
| Firecrawl | Web metadata search；抓取 backend | https://firecrawl.dev | 搜索仍需要 API key；`/v2/scrape` 无 key 可匿名使用但有 IP 级免费日额度，配置 key 后额度和限流更高 | 100 |
| Zhihu | Zhihu OpenAPI search | https://developer.zhihu.com | 优先用官方 `zhihu_search` API；无 `zhihu` key 时可 fallback 到 Firecrawl `includeDomains` | 10 |
| V2EX | V2EX 域名限制搜索 | https://firecrawl.dev | 通过 Firecrawl `includeDomains` 搜索 V2EX | 100 |
| Linux Do | Linux Do 域名限制搜索 | https://firecrawl.dev | 默认 route 使用 Firecrawl `includeDomains`；另有可选 `linuxdo_api` cookie + Patchright 路径 | 20 |
| YouTube | YouTube video search | https://console.cloud.google.com/apis/library/youtube.googleapis.com | 官方 YouTube Data API；metadata only，不抓视频正文 | 50 |
| Bilibili | Bilibili video search | https://search.bilibili.com | 公开视频搜索接口；cookie 可选；metadata only，不抓视频正文 | 50 |
| SerpAPI Google Light | Google SERP | https://serpapi.com/users/sign_up?plan=free | 250 次/月；`google_light` 默认更省 | 100 |
| GitHub Repos | 仓库搜索 | https://github.com/settings/tokens | REST API 常见免费额度：未认证约 60 req/hour，token 约 5,000 req/hour；也可 fallback 到已登录 `gh` CLI | 100 |
| Hacker News | Hacker News story search | https://hn.algolia.com/api | 匿名可用，使用 Hacker News Algolia 搜索接口 | 100 |
| Stack Overflow | Stack Overflow question search | https://api.stackexchange.com/docs/advanced-search | 匿名可用，使用 Stack Exchange advanced search | 100 |
| Twitter/X | 社交讨论、推文和 top replies | https://x.com | 无官方搜索 API 免费层；使用 `twikit-ng` + cookies，受账号状态和限流影响 | 20 |
| GLM Web | GLM native web-search answers | local `glm2api` compatible service | 反向/本地兼容服务路径，仓库默认禁用 | 30 |
| DeepSeek Web | DeepSeek web-search answers | https://chat.deepseek.com | 需要用户 token/cookie/export，仓库默认禁用 | 30 |
| Jina Reader | 额外网页正文抓取 | https://r.jina.ai/docs | 匿名可用，约 20 rpm；key 是固定额度，可作为匿名限流后的 fallback | scrape only |

## 路由：选择搜哪些源

`route` 决定**搜哪些源**以及是否让 provider 直接返回正文。

### `route`（搜哪些源 / 场景）

| Route | Sources | 适合场景 |
|---|---|---|
| `default` / `web` | Brave + Tavily + Exa + SerpAPI + Firecrawl + Baidu + GLM Web + DeepSeek Web | 普通事实搜索；默认 route |
| `fast` | Baidu + Tavily + Firecrawl + Exa | 只跑“搜索 API 自带正文”的源，默认 `scrape_top=0`；快速总结、当前背景 |
| `social` | Twitter/X | 看社交反馈、口碑、讨论 |
| `dev` | Stack Overflow + GitHub Repos + Hacker News | 技术问题、仓库、工程讨论 |
| `cn-community` | Zhihu + V2EX + Linux Do | 中文社区讨论 |
| `video` | YouTube + Bilibili | 搜视频；默认 title/url-only，不进入网页抓取 |
| `all` | default + social + dev + cn-community（不含 video，且不含 `linuxdo_api` 重复路径） | 尽可能广的非视频召回 |
| 指定源 | 通过 `sources` 参数，例如 `sources=["brave"]`、`sources=["github"]`、`sources=["deepseek-web"]` | 绕过 route，直接指定一个或多个源 |

`fast` 路由只跑那些搜索 API 直接返回正文的 provider（不再有独立的 `level` 参数），route 默认不额外抓取；显式传入 `scrape_top` 或配置文件里的 `scrape_top` 仍会覆盖默认值。
若想“用 default 召回 + 再抓正文”，用 `route=default` 搭配 `scrape_top=N`。

> 实际生效的源以响应里的 `diagnostics.active_sources` 为准：`multi-search-config.json`
> 通过 `disabled_sources` 全局关闭的源（仓库内默认关闭了 `glm_web`、`deepseek_web`）
> 会从 route 中减去，不会执行。

### Route 默认参数

| Route | count | scrape_top | timeout |
|---|---:|---:|---:|
| `default` / `web` | 10 | 20 | 60s |
| `fast` | 10 | 0 | 45s |
| `all` | 10 | 30 | 90s |
| `social` | 10 | 0 | 60s |
| `dev` | 10 | 20 | 60s |
| `cn-community` | 10 | 20 | 60s |
| `video` | 10 | 0 | 45s |

缺 key 的源会显示 error row，不会静默消失。`fast` 路由不会跨路由降级；缺 key 时只显示该源的 error row。GitHub 没 token 时可用 `gh auth login` 后 fallback。Twitter/X 依赖、cookies、认证或限流失败时只影响 Twitter/X，其它源继续输出。

## Keys

把 key 放到 `~/.search-keys.json`，不要提交到仓库：

```json
{
  "brave": "BSAxxxx",
  "baidu": "qianfan-or-appbuilder-key",
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
  "twitter": {"auth_token": "...", "ct0": "..."},
  "linuxdo": "optional_linuxdo_cookie",
  "deepseek_web": {"token": "...", "cookie": "..."}
}
```

环境变量会覆盖同名配置：

```text
BRAVE_SEARCH_API_KEY / BRAVE_API_KEY
BAIDU_QIANFAN_API_KEY / QIANFAN_API_KEY / APPBUILDER_API_KEY
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
DEEPSEEK_WEB_TOKEN / DEEPSEEK_USER_TOKEN
DEEPSEEK_WEB_COOKIE
DEEPSEEK_WEB_AUTH_EXPORT
```

GLM Web 由 `glm_web.py` 直接读取环境变量：`GLM_WEB_BASE_URL`、`GLM_WEB_MODEL`、`GLM_WEB_API_KEY`。仓库默认禁用 `glm_web`，启用前需要先准备本地兼容服务。

多数 key 字段支持 string 或 string array。Jina 支持 `{ "key": "...", "exhausted": true|false }`；只有余额接口确认 `wallet.total_balance <= 0` 时才会自动标记 exhausted。需要手动软删除 Jina key：

```powershell
# 在 multi_search_mcp/ 目录下运行（该目录会被加入 sys.path）
cd multi_search_mcp
python -m src.state.mark_exhausted <jina-key>
```

## 架构和术语

> 概念定义见术语表：[docs/glossary.md](docs/glossary.md)（route / source / 降级 / key 轮换等的单一事实来源）。

```mermaid
flowchart LR
    Q[MCP tool / skill] --> SVC[src/service.py]
    SVC --> SR[SearchRunner<br/>route · SQLite key state · timeout · fanout]
    SR --> S[Searcher 搜索器<br/>multi_search_mcp/src/search/searchers/*]
    S --> M[Merger / Ranker<br/>multi_search_mcp/src/support/dedup.py]
    M --> SP[ScrapePlanner 抓取规划器<br/>multi_search_mcp/src/scrape/scrape_planner.py]
    SP --> SO[Scrape orchestration<br/>multi_search_mcp/src/scrape/scrape.py]
    SO --> B[Scraper 抓取器 backend<br/>multi_search_mcp/src/scrape/scrapers/*]
    B --> WB[正文回写 + 统一排序<br/>apply_scraped_content · rank_results]
    M --> WB
    WB --> R[Renderer 渲染器<br/>multi_search_mcp/src/support/format.py]
    R --> O[Markdown diagnostics + results]
```

术语固定如下：

- **Service 服务层**：`multi_search_mcp/src/service.py`，统一 MCP 参数、config、key、search、scrape、render。
- **Searcher 搜索器**：`multi_search_mcp/src/search/searchers/*`，只负责 query -> `SearchResult`/dict，输出 title、url、description、source、score、raw metadata。
- **SearchRunner 搜索调度器**：`multi_search_mcp/src/search/search_runner.py`，负责 route、并发、timeout、SQLite key state 和 source status。
- **Merger/Ranker 合并排序器**：`multi_search_mcp/src/support/dedup.py`，负责 URL 归一化、去重、`also_from`、共识权重、canonical source 选择，以及统一排序（`rank_results`）。抓取成功的正文通过 `apply_scraped_content` 回写到对应结果条目的 `scraped_content`，因此 JSON `results` 与 markdown 看到的是同一份「已富集」结果，而不是空骨架 + 底部附录两套数据。`rank_results` 在 `service.py` 层统一执行一次，JSON `results`、markdown `Ranked Results`、`provider_status` 共享同一排序（优先级：错误置底 → 已抓取正文 → 共识权重 → 正文长度 → stars）。
- **ScrapePlanner 抓取规划器**：`multi_search_mcp/src/scrape/scrape_planner.py`，负责决定哪些 URL 需要抓、每源 quota、backend 顺序和 key 候选。
- **Scraper 抓取器 backend**：`multi_search_mcp/src/scrape/scrapers/*`，负责 url -> 正文。Jina、Exa、Tavily、Firecrawl、old.reddit 都是 backend。
- **Scrape orchestration 抓取调度执行器**：`multi_search_mcp/src/scrape/scrape.py`，负责单 URL fallback 链、站点策略和 key 使用结果记录。
- **Renderer 渲染器**：`multi_search_mcp/src/support/format.py`，负责诊断信息、搜索结果、抓取正文和 untrusted 安全围栏。

## 抓取流程

关键规则：

- `scrape_top` 只计算额外抓取的缺正文 URL；已有正文不占额度。
- 默认抓取后端从可用能力构建：Jina 匿名优先；Exa / Tavily 只有配置对应 key 后才进入 fallback 链；Firecrawl `/v2/scrape` 无 key 也会作为最后 fallback，但匿名额度是 IP 级免费日额度，不参与批量抓取 primary 轮换。Reddit URL remote-first：`www.reddit.com` 走 Jina / Tavily / Exa / Firecrawl / old.reddit fallback，`old.reddit.com` 走 Tavily / Jina / Exa / Firecrawl / old.reddit fallback。Zhihu 搜索优先使用官方摘要结果，后续抓取知乎 URL 时仍会过滤“荒原页 / 登录墙”假正文。Jina 先匿名，匿名限流后才用 Jina key。
- Exa / Tavily / Firecrawl 在 search 和 scrape 中都走 SQLite key state：跳过 invalid / disabled / cooldown 未过期 / quota_exhausted 未过期；从未使用过的 key 优先；同等情况下按 `last_used_at` 最早优先；每次选中会更新 `last_used_at` 和 `use_count`。
- 每个候选 URL 只走一次完整 fallback 链；失败或 `scrape_timeout` 后记录 Errors，不自动补位。
- GitHub repo 根 URL 抓取时会改写到 raw README。

## 公共数据契约

代码仍兼容 dict，但核心边界已经有 dataclass：`SearchResult`、`ScrapeResult`、`ProviderStatus`、`ProviderError`，定义在 `multi_search_mcp/src/support/models.py`。

- `SearchResult`/dict：`source`、`title`、`url`、`description`、`scraped_content`、`also_from`、`stars`、`score`、`raw`。
- `ScrapeResult`/dict：`url`、`title`、`markdown`、`length`、`via`，可带 backend chain 等 raw metadata。
- `ProviderStatus`/dict：`source`、`status`、`raw_hits`。
- `ProviderError`/dict：`source`、`error`，错误输出会尽量脱敏。

## 常用调用

通过 MCP `multi_search` tool 调用（以 JSON 入参示意）：

```jsonc
// 默认 default route + 额外抓取缺正文 URL
{ "query": "epub to markdown" }

// 快速总结（route=fast，只跑自带正文的 provider，默认不额外抓取）
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

// default 召回 + 额外抓正文
{ "query": "vector database 选型", "route": "default", "scrape_top": 5 }

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
| `route` | `default` | 选源/场景：`web` / `fast` / `social` / `dev` / `cn-community` / `video` / `all`；`fast` 只跑自带正文的源，默认不抓取 |
| `sources` | — | 直接指定一个或多个源，绕过 route |
| `count` | per-source | 全局 count，会按各源上限 clamp |
| `timeout` | 60 | 搜索阶段整批 deadline |
| `scrape_top` | 由 `route` 推导，可被配置覆盖 | 额外抓取缺正文 URL 数，上限 30；传 0 关闭。`fast` 路由默认是 0，但 tool 入参或配置文件可覆盖；仓库开发配置当前写了 `scrape_top: 30` |
| `scrape_chars` | provider | 单页抓取正文最大字符数 |
| `expand` | — | 额外扩展查询（list），常用于给中文查询补英文 |
| `use_state` | true | 是否使用 SQLite key 状态与站点抓取器记忆 |
| `output` | `both` | 输出形态：`json` / `markdown` / `both` |

`count` 解析优先级：tool 入参 `count` > 配置文件 `counts{}` / `*_count` > 配置文件全局 `count` > route 默认值，最后按各 provider 的上限 clamp。响应里的 `diagnostics.effective_counts` 会回显最终每个 provider 使用的数量；`diagnostics.route_meta.route_default_count` 只表示 route 默认值。

JSON 配置支持 `disabled_sources`（没有配置时默认为 `[]`；仓库自带配置为 `["glm_web", "deepseek_web"]`）用来全局关闭某些搜索源。route 正常解析后会从结果里减去这些源，对 tool 显式传入的 `sources` 同样生效。它只是调度开关：不删除 API key、不改变 provider 能力，被禁用源在 `counts{}` 里的配置保留但不生效。支持源别名（如 `deepseek-web`、`github`），只接受搜索源，不接受 scrape backend（如 `jina`）；填入未知名称会报错。若某次请求的全部源都被禁用，会返回明确错误而不是静默返回空结果。响应的 `diagnostics` 会回显 `route_sources`（原始选择）、`disabled_sources`（已关闭）、`active_sources`（实际执行）。

`scrape_url` tool 用于单独抓取一个 URL，支持 `backends`、`scrape_chars`、`scrape_timeout`、`use_state` 等参数。

## 输出

输出包含：

- JSON `summary`：首个 provider 原生 query-level answer/summary；`summaries` 保留全部 `*_answer` 来源及 metadata。`source_briefs` 为每个 provider 提供一条展示 brief，优先使用原生 answer，否则从该来源的 URL 结果 title/snippet/highlights 生成 brief；兼容字段 `source_summaries` 仍会返回，但新代码应使用 `source_briefs`，避免把 per-result snippet 误读成 query-level summary。每条 `results[]` 继续保留旧字段 `description`/`scraped_content`，同时补充公共别名 `content`/`body`/`full_content`。
- `display_results[]`：从最终排序后的有效 `results[]` 抽取的展示清单，固定包含 title、source、URL 和 snippet，供 UI / agent 优先展示。新闻、时事和需要核验的查询必须先列出这些可点击来源链接，再给摘要；不能只输出无链接的叙述性总结。
- `Sources (raw hits)`：各源原始命中数。
- `Source Status`：OK / PARTIAL / ERROR。
- `URL Inventory`：去重后的 URL 和共识权重。
- `Errors`：缺 key、依赖问题、timeout、provider exception、抓取失败。
- `Ranked Results`：统一排序后的结果（错误置底 → 已抓取正文 → 共识权重 → 正文长度 → stars）；JSON `results` 与此顺序一致。
- `Scraped Content`：正文内容，统一包在 untrusted block 里。

Provider 参考文档保存在 [docs/](docs/)，agent 说明在 [skills/multi-search/SKILL.md](skills/multi-search/SKILL.md)。

## 安全

- 不要提交 `~/.search-keys.json`、`.env` 或真实 provider key。
- provider error 输出前会尽量 scrub 可能出现的 key 值。
- 第三方抓取正文始终按 untrusted data 处理。

## Troubleshooting

### 某个搜索源一直报错怎么办？

先调用 `doctor` tool 检查依赖和 key。缺 key、quota 用完、网络超时都会在 `Source Status` 和 `Errors` 中显示，不会静默吞掉。

### 为什么结果里没有 Twitter/X？

Twitter/X 需要 cookies。确认依赖已安装，并配置 `TWITTER_COOKIES_PATH` 或 `~/.search-keys.json` 中的 `twitter` 字段；源码直接运行时先执行 `python -m pip install -e .`。

### 抓取正文太慢怎么办？

降低 `scrape_top`，或设 `scrape_top: 0` 只看搜索结果。正文抓取会受目标网站、Jina / Exa / Tavily / Firecrawl 状态和网络影响。

## License

[MIT](LICENSE)


