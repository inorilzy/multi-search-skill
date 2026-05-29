---
name: multi-search
description: >
  Aggregated search across 8 sources: Brave, Tavily, Exa, Firecrawl, SerpAPI,
  GitHub Repos, HackerNews, Stack Overflow, Twitter/X. Combines web
  results, AI answers, repo discovery and community Q&A in one
  parallel request, with optional Jina / Firecrawl scraping of top URLs.
  Activate when user says: search, find, look up, multi-search, search everywhere,
  搜索, 查找, 查一下, 聚合搜索, 多源搜索.
argument-hint: "<query> [--type all|web|code|repos|community|...] [--count N] [--scrape-top N] [--timeout N]"
---

# Multi-Search

Parallel aggregated search across **8 sources** in a single command, with optional
full-page scraping of top result URLs (Jina Reader → Firecrawl fallback).

## Sources Overview

| Icon | Source | Type | Key | In `--type all` | 详情自带? | 免费上限 |
|------|--------|------|-----|:-:|:-:|:-:|
| 🔍 | Brave | Web | `brave` | ✅ | ⚠️ +extra_snippets | 20/req |
| 🌐 | Tavily | Web (AI) + Answer | `tavily` | ✅ | ✅ raw_content (markdown) | 20/req |
| ✨ | Exa | Neural + Answer | `exa` | ✅ if key | ✅ summary + highlights | 100/req |
| 🔥 | Firecrawl | Web + 内联抓取 | `firecrawl` | ✅ if key | ✅ markdown + summary | 1 credit/result |
| 🔎 | SerpAPI | Google (`google_light`) | `serpapi` | ✅ if key | ❌ snippet | 250/月（free） |
|  | GitHub Repos | 仓库元数据 + README | `github` or `gh` CLI | ✅ | ✅ 抽 README (Jina) | 100/req |
| 🟠 | HackerNews | 技术社区 | None | ✅ | ❌ 标题 | Algolia 1000/req |
| 🏆 | Stack Overflow | Q&A | None | ✅ | ❌ 问题标题 | 100/req |
| 🐦 | Twitter / X | 社交实时 | cookies (twikit-ng) | ✅ if cookies | ✅ 推文全文 + 剧评论 | 免费无额度（限 IP）|

### 聚合策略

| 类 | 信源 | scrape 行为 |
|---|---|---|
| 🟢 **A. 自带全文** | Tavily / Exa / Firecrawl | 搜索时已带 `scraped_content`，**显式 SKIP** 抓取队列，零额外调用 |
| 🟠 **B. 仅 snippet，进抓取队列** | Brave / SerpAPI / HackerNews / StackOverflow / **GitHub Repos（抽 README）** | `--scrape-top` 优先抓这一层（PREFER 源） |
| 🐦 **Twitter·独立详情** | Twitter / X | `search_twitter` 已把推文 + 评论塞进 `scraped_content`，**SKIP** 抓取队列 |

## API Key Setup

Keys are loaded in priority order:
1. Env vars: `BRAVE_SEARCH_API_KEY`, `TAVILY_API_KEY`, `EXA_API_KEY`, `FIRECRAWL_API_KEY`, `SERPAPI_KEY`, `GITHUB_TOKEN`, `JINA_API_KEY`
2. `~/.search-keys.json`:
   ```json
   {
     "brave": "BSAxxxx",
     "tavily": ["tvly-key1", "tvly-key2"],
     "exa": ["exa-key1", "exa-key2", "exa-key3"],
     "firecrawl": "fc-xxxx",
     "serpapi": "xxxx",
     "github": "ghp_xxxx",
     "jina": ["jina_key1", "jina_key2"],
     "twitter": { "auth_token": "...", "ct0": "..." }
   }
   ```

> **多 key 池**：任何字段可以是 string 或 string 数组。多 key 时调用前由 `pick_key()` 随机轮换（jina 例外，按 URL index round-robin），降低单 key 配额耗尽风险。

GitHub token is **optional** — falls back to `gh` CLI if absent (must be `gh auth login`'d).
Sources without their required key are silently skipped in `--type all` mode.

Free key sources:
- **Brave**: https://brave.com/search/api/ (2000 queries/month)
- **Tavily**: https://tavily.com (1000 queries/month)
- **Exa**: https://exa.ai (free tier)
- **Firecrawl**: https://firecrawl.dev (free credits)
- **SerpAPI**: https://serpapi.com (250 queries/month with `google_light`)
- **Twitter / X**: 需要登录后导出浏览器 cookies。推荐直接在 `~/.search-keys.json` 加 `"twitter": {"auth_token":"...", "ct0":"..."}`；或者复用 `~/.mcp-twikit/cookies.json`（跳 mcp-twikit 共享会话，同格式）。需 `pip install twikit-ng`。

## Count & Timeout Control

各源有独立的默认值（基于免费版实测上限调优）。`--count N` 覆盖所有源；`--xxx-count N` 单独覆盖。

| Parameter | 默认 | 说明 |
|-----------|------|------|
| `--count N` | 不传则用各源独立默认 | 全局覆盖，brave/serpapi 自动 clamp |
| `--brave-count N` | **10** (上限 20) | Brave |
| `--tavily-count N` | **10** (上限 20) | Tavily |
| `--exa-count N` | **10** (上限 100) | Exa |
| `--serpapi-count N` | **10** (上限 20) | SerpAPI |
| `--serpapi-engine` | `google_light` | 也可用 `google`（含 Knowledge Graph，更慢/更贵） |
| `--firecrawl-count N` | **5** (上限 10，每条 1 credit) | Firecrawl |
| `--github-count N` | **10** (上限 100) | GitHub repos / code |
| `--hn-count N` | **10** | HackerNews |
| `--so-count N` | **10** (上限 100) | Stack Overflow |
| `--twitter-count N` | **10** (上限 20) | Twitter / X（需 `~/.mcp-twikit/cookies.json`） |
| `--timeout N` | `60` | 每源超时秒数 |
| `--scrape-top N` | `30` | 默认开：按共识权重抓取前 N 条 URL 全文（上限 30）。传 `0` 或 `--no-scrape` 关闭 |
| `--no-scrape` | — | 快捷关闭 scrape（等价于 `--scrape-top 0`） |
| `--scrape-chars N` | `2000` | 每页最大字符数（stdout 截断；完整内容仍在 memory） |
| `--scrape-per-source N` | `6` | 每个来源最多抓几条（防霸屏） |
| `--jina-first N` | `scrape_top` (all-Jina) | 前 N 个 URL 走 Jina；剩余在 tavily/exa/firecrawl 间 round-robin。Jina 额度紧张时设小（如 `20`） |
| `--no-jina` | — | 跳过 Jina，全部走 tavily/exa/firecrawl 轮转（等价 `--jina-first 0`） |
| `--expand "q2" "q3"` | — | 额外并行查询（lite 模式只跑 brave+tavily，省 quota） |
| `--brief` | — | 仅输出标题+URL，省 token |

## Search Types

| Flag | Sources Used |
|------|-------------|
| `--type all` (default) | Brave + Tavily + Exa + Firecrawl + SerpAPI + GitHub Repos + HackerNews + Stack Overflow + Twitter |
| `--type web` | Brave + Tavily + Exa + Firecrawl + SerpAPI |
| `--type repos` / `github` | GitHub Repos only |
| `--type community` | HackerNews + Stack Overflow + Twitter |
| `--type twitter` / `x` | Twitter / X only |
| `--type brave` / `tavily` / `exa` / `firecrawl` / `serpapi` / `google` / `hn` / `so` | Single source only |

\* Sources whose key is missing are silently skipped.

## Scraping (默认开启)

默认 `--scrape-top 30`：搜索完成后自动按**共识权重**抓 30 条 URL，**全部走 Jina Reader**（当前 Jina 额度充足）；Jina 失败时按 `scrape_url_smart()` fallback 链 tavily → exa → firecrawl。

```
python search.py "rust async runtime"               # 默认 30 条全 Jina
python search.py "react hooks" --scrape-top 10        # 只抓 10 条
python search.py "news today" --no-scrape             # 时效查询，关闭 scrape
python search.py "x" --jina-first 20                  # Jina 额度紧张：前 20 Jina + 后 10 三家轮转
python search.py "x" --no-jina                        # 不用 Jina：全部 tavily/exa/firecrawl 轮转
```

Output adds a `## 🔥 Scraped Content` section with a **关键信息速览** summary table, then full per-page sections.

**Smart routing**:
- A 类（Tavily / Exa / Firecrawl）已自带 `scraped_content`，直接注入，**SKIP 抓取队列**
- B 类 PREFER 源（Brave / SerpAPI / HN / SO / GitHub Repos）按共识权重抓取，每源上限 `--scrape-per-source` (默认 6)
- **Twitter** SKIP：`search_twitter` 已通过 twikit-ng 把推文 + 翻页评论塞进 `scraped_content`，不进抓取队列
- GitHub Repos 被抓时自动重写到 `raw.githubusercontent.com/.../README.md`，远比 description 富信息
- 后端分配：默认全 Jina；`--jina-first N` 前 N 个 Jina，剩余 tavily/exa/firecrawl round-robin；`--no-jina` 完全跳过 Jina
- 单条 URL 失败时 `scrape_url_smart()` 自动 fallback：jina → tavily → exa → firecrawl

Hard cap: 30 URLs/run。Tavily Extract / Exa contents / Firecrawl 各为付费/限流后端，按需轮换。

### 整体流程

```mermaid
flowchart TD
    U[用户查询] --> K[加载 keys]
    K --> FAN[并行 fan-out · 12 workers]

    FAN --> A[A类·自带全文<br/>Tavily / Exa / Firecrawl]
    FAN --> B[B类·仅 snippet<br/>Brave / SerpAPI<br/>HN / SO / GitHub Repos]
    FAN --> TW[Twitter·独立详情<br/>get_tweet_by_id<br/>翻页 replies.next 拿 N 条评论<br/>sleep 0.4s 节流]

    TW --> RT{遇到 404/429?}
    RT -->|是| RTY[等 5s · 整次 search 重试 1 次]
    RT -->|否| TWE[推文 + 评论 → scraped_content]
    RTY --> TWE

    A --> INJ[直接 inject scraped_content]
    TWE --> INJ

    INJ --> M[URL 去重 · 共识权重打分]
    B --> M

    M --> SCR{需要 scrape?}
    SCR -->|是| SCR1[B 类按权重抓 Jina Reader<br/>GitHub Repos → README markdown<br/>Firecrawl 兑底]
    SCR -->|否| OUT
    SCR1 --> OUT

    OUT[渲染 Markdown<br/>AI Answers + 共识列表<br/>+ Scraped Content + Top replies]
    OUT --> SUM[Agent 总结回复]
```

## Expand Queries (`--expand`)

并行跑多个查询，自动合并去重：

```
python search.py "agent 编排 不同模型" \
  --expand "multi-agent model routing different LLM per agent" \
  --type web
```

**中英混语最佳实践**：中文短语作主查询 + 英文技术词作 `--expand`：
- 中文结果来自 Tavily CN 、Brave 中文页
- 英文结果来自 Brave、Tavily、Exa、Firecrawl、SerpAPI、HackerNews、Stack Overflow、GitHub
- 同一共识排序池，去重后呈现

Expand 查询使用 **lite 模式**（只跑 brave + tavily），不会 N 倍消耗 API 配额。

## Workflow

When the user provides a search query:

1. **Check keys** — `~/.search-keys.json` or env vars
2. **Classify the query**:
   - 技术查询（代码、工具、框架、API、算法）→ 多语言搜索高价值
   - 新闻 / 时效查询 → 单语言已足够
3. **Auto-translate for Chinese technical queries**：中文技术查询自动加英文 `--expand`，不要问用户：
   ```
   # 用户: "搜索 agent 编排最佳实践"
   python search.py "agent 编排最佳实践" \
     --expand "agent orchestration best practices multi-agent" \
     --type web
   ```
   新闻类 (`最新 AI 新闻`) 则不加 expand。
4. **Run** the script and present its Markdown output directly
5. **Follow up** — offer `--scrape-top N` or `fetch_webpage` for deep dives on top URLs

## Example Invocations

```powershell
# 默认全源搜索
python .github/skills/multi-search/search.py "epub to markdown"

# Web 搜索 + 自动抓取前 3 条 URL 全文
python search.py "rust async runtime" --type web --scrape-top 3

# 社区讨论
python search.py "async python performance" --type community

# 仅 Google（SerpAPI）
python search.py "WebGPU compute" --type serpapi

# 仅 GitHub 仓库（默认会抓 README）
python search.py "vector database" --type repos

# 节省 token：只要标题+URL
python search.py "react hooks" --brief --count 10
```

## Notes

- 结果按归一化 URL 去重；同一 URL 被多源命中时显示 `also_from` 共识标记
- `--type all` 默认并行最多 12 个源（ThreadPoolExecutor）
- 各源默认 count 已调优到免费版上限附近，直接运行无需手工调参
- Firecrawl 在 `--type all` 中**会**被调用（已含内联抓取，每条 1 credit）；预算敏感时用 `--type all` 之外的具体类型
- Tavily 内置 `include_answer="advanced"`，搜索结果顶部直接显示 LLM 合成答案
- Exa 通过 `outputSchema` 内置全局合成答案 + 每条 summary，含引用编号 `[1][2]`
- AI Answer 块（Tavily / Exa / SerpAPI KG）始终置顶展示
