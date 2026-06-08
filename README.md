# multi-search-skill

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

并行聚合搜索 — 一条命令按路由调用最多 **7 个信源**：Web 搜索、Google SERP、代码仓库、Twitter/X，以及可选全文抓取，按“共识权重”排序输出去重 Markdown 结果。

> 不是所有信源都能零配置使用。GitHub 需要 `GITHUB_TOKEN` / `GH_TOKEN`，或本机已登录 `gh` CLI；Twitter/X 需要 `twikit-ng` 和 cookies。

---

## ✨ 特性

- **3 个主 route**：`default` 跑全源，`lite` 跑 Tavily + Exa，`discussion` 跑 Twitter/X
- **多 key 池**：API key 字段可作为 string 或 string 列表，随机轮换；遇到 401/403/429/额度错误会自动尝试同池下一个 key
- **共识权重排序**：被多个信源同时命中的结果置顶，标记 `【×N】from: brave, tavily, ...`
- **GitHub fallback**：GitHub 在本机 `gh auth login` 后也可用，无需额外 token
- **聚合策略**：先拆分“已有正文 / 无正文”结果；正文进入正文池时就按 URL 合并；无正文里删除已由正文池覆盖的重复 URL，再额外抓取
- **抓取后端可调**：默认 `scrape_top=30`，额外抓网页优先 B 类 metadata/snippet 源，再按共识权重排序；抓取后端使用 Jina Reader / Exa Contents / Tavily Extract；可用 `--no-scrape` 或配置 `no_scrape: true` 关闭额外抓取
- **Agent 友好输出**：默认隐藏 provider AI Answer 和普通 snippet；`--verbose` 才展开摘要细节
- **TLS 稳定**：内置 SSL 上下文 + 重试，解决 Python 3.12 严格 TLS 下的 EOF 错误

---

## 📦 安装

```powershell
git clone https://github.com/inorilzy/multi-search-skill.git
cd multi-search-skill

# 核心搜索仅依赖 Python 3.10+ 标准库；Twitter/X 路由需要可选依赖 twikit-ng
python search.py "epub to markdown"
```

### 安装后检查 / 初始化

每次把 skill 装到一台新机器后，建议先跑一次环境检查。Windows 上优先用 PowerShell 脚本；它会先检查 `python` / `py -3` 是否真可用，再调用 Python 内部 doctor：

```powershell
./scripts/check-env.ps1
```

推荐初始化方式是用 `uv` 管理本 skill 的 Python 和依赖，不要求系统级 `python` 永远挂在 PATH 上：

```powershell
# 如果本机还没有 uv，让脚本通过 winget 安装 uv
./scripts/init.ps1 -InstallUv

# 如果已经有 uv，直接初始化本地 .venv + Twitter/X 依赖
./scripts/init.ps1
```

初始化脚本会执行：检查/可选安装 `uv`、`uv python install 3.12`、创建本目录 `.venv`、安装 `twikit-ng`，最后运行 `uv run python search.py --doctor`。如果不需要 Twitter/X，可用 `./scripts/init.ps1 -SkipTwitter`。

如果 Python 已经可用，也可以直接跑：

```powershell
python search.py --doctor
```

检查项包括 Python 版本、`~/.search-keys.json`、各搜索源 key、GitHub token 或 `gh auth login`、Twitter/X 的 `twikit-ng` 依赖和 cookies。Twitter/X 是可选源，但 `default` / `discussion` 会尝试调用它；要启用推特搜索，需要：

```powershell
python -m pip install twikit-ng
```

然后在 `~/.search-keys.json` 写入 `twitter` cookie dict，至少包含 `auth_token` 和 `ct0`；或设置 `TWITTER_COOKIES_PATH` 指向 cookies JSON 文件。

---

## 🔑 API Keys

所有 key 写入 `~/.search-keys.json`（**不要提交到仓库**）：

```json
{
  "brave": "BSAxxxx",
  "tavily": ["tvly-key1", "tvly-key2"],
  "exa": ["exa-key1", "exa-key2", "exa-key3"],
  "jina": "jina_xxx_optional",
  "firecrawl": "fc-xxxx",
  "serpapi": "xxxx",
  "github": "ghp_xxxx",
  "twitter": { "auth_token": "...", "ct0": "..." }
}
```

> **多 key 池**：API key 字段可以是 single string 或 array of strings。Brave / Tavily / Exa / Firecrawl / SerpAPI 会随机打乱 key 池；遇到 401/403/429、quota、rate limit、credits 等明显 key/额度错误时自动尝试下一个 key。Jina 默认匿名抓取，只有匿名限流且配置了 `jina` key 时才带 key 重试；Jina 的 RPM/429 只按临时限流轮换或 fallback，只有余额接口返回 `wallet.total_balance <= 0` 时才自动标记 `exhausted`。Twitter 的 `twitter` 可以是 cookie dict 或 cookies JSON 路径，不参与随机轮换。

或用环境变量：`BRAVE_SEARCH_API_KEY` / `BRAVE_API_KEY` / `TAVILY_API_KEY` / `EXA_API_KEY` / `JINA_API_KEY` / `JINA_KEY` / `FIRECRAWL_API_KEY` / `SERPAPI_API_KEY` / `SERPAPI_KEY` / `GITHUB_TOKEN` / `GH_TOKEN` / `TWITTER_COOKIES_PATH`。

加载顺序是先读 `~/.search-keys.json`，再用环境变量覆盖同名 key；因此环境变量优先级更高。

## ⚙️ 默认配置

非敏感默认参数可以单独放在 skill 根目录的 `multi-search-config.json`。API key 和 Twitter cookies 继续放 `~/.search-keys.json`；route、count、timeout、scrape 偏好放 config。

```json
{
  "type": "default",
  "count": null,
  "counts": {
    "brave": 10,
    "tavily": 10,
    "exa": 10,
    "firecrawl": 5,
    "serpapi": 10,
    "github": 10,
    "twitter": 10
  },
  "serpapi_engine": "google_light",
  "timeout": 60,
  "scrape_top": 30,
  "no_scrape": false,
  "scrape_chars": 6000,
  "scrape_per_source": 6,
  "scrape_timeout": 60,
  "scrape_concurrency": 5,
  "expand": [],
  "brief": false,
  "verbose": false
}
```

也可以指定自定义路径：

```powershell
python search.py "agent memory" --config ./multi-search-config.json
```

除搜索词本身和 `--config PATH` 外，所有运行参数都可以放进这个 JSON。CLI 参数优先级高于 JSON 默认值。默认配置文件不存在时会忽略；但显式传入 `--config PATH` 时，文件必须存在、必须是合法 JSON object，否则会在搜索前退出。

### 配置字段怎么理解

| JSON 字段 | CLI 参数 | 默认 | 说明 |
|---|---|---:|---|
| `type` | `--type` | `default` | 搜索路由：`default` 全源，`lite` 轻量详情源，`discussion` Twitter/X 讨论，也可写单源 |
| `count` | `--count` | `null` | 正整数全局数量。`null` 表示不用全局数量，而是走 `counts` 里的单源数量 |
| `counts.brave` | `--brave-count` | `10` | Brave 正整数返回条数，上限 20 |
| `counts.tavily` | `--tavily-count` | `10` | Tavily 正整数返回条数，上限 20 |
| `counts.exa` | `--exa-count` | `10` | Exa 正整数返回条数，上限 100 |
| `counts.firecrawl` | `--firecrawl-count` | `5` | Firecrawl metadata search 正整数返回条数；本 skill 保守限制 10；不启用 Firecrawl scrape |
| `counts.serpapi` | `--serpapi-count` | `10` | SerpAPI 正整数目标返回条数；按文档使用 `start` 分页，本地最多截取 100 条 |
| `counts.github` | `--github-count` | `10` | GitHub repositories 正整数返回条数，上限 100 |
| `counts.twitter` | `--twitter-count` | `10` | Twitter/X 正整数返回条数，上限 20 |
| `serpapi_engine` | `--serpapi-engine` | `google_light` | `google_light` 更轻；`google` 通常才有 Knowledge Graph，但更慢/更贵 |
| `timeout` | `--timeout` | `60` | 一批并发 source 最多等多少秒；各 provider 内部还有自己的 HTTP timeout |
| `scrape_top` | `--scrape-top` | `30` | 默认最多额外抓取 30 个缺正文 URL；已有正文不消耗额度；0 表示不额外抓取 |
| `no_scrape` | `--no-scrape` | `false` | 设为 `true` 等价于 `scrape_top = 0` |
| `scrape_chars` | `--scrape-chars` | `6000` | 每个抓取页面输出多少字符；轻量预览可降到 2000，深挖可升到 12000+ |
| `scrape_per_source` | `--scrape-per-source` | `6` | 正整数；额外抓取时，每个来源最多抓几条，避免单一来源刷屏 |
| `scrape_timeout` | `--scrape-timeout` | `60` | 非负整数；整批额外抓取最多等待多少秒，超时 URL 会输出 error row |
| `scrape_concurrency` | `--scrape-concurrency` | `5` | 正整数；额外抓取 worker 数，多个 key 会按 URL offset 分布使用 |
| `expand` | `--expand` | `[]` | 额外 query 列表；扩展 query 走 `lite` 路由，节省请求；也兼容 `expand_queries` |
| `brief` | `--brief` | `false` | 只输出标题和 URL，减少 token |
| `verbose` | `--verbose` | `false` | 展示 provider AI Answer 和普通搜索 snippet；默认隐藏以节省 agent token |

`count` 的理解方式：如果只想“每个源尽量拿 N 条”，设置 `"count": 10`，并删除 `counts` 或把不想单独控制的 `counts.xxx` 设为 `null`；如果想精细控 quota，就保持 `"count": null`，再分别调 `counts.firecrawl`、`counts.twitter` 等。JSON 中的数值字段按 CLI 同样校验：`count`、`counts.xxx`、`scrape_chars`、`scrape_per_source`、`scrape_concurrency` 必须为正整数；`timeout`、`scrape_top`、`scrape_timeout` 必须为非负整数；`no_scrape`、`brief`、`verbose` 必须是 JSON boolean；`expand` / `expand_queries` 必须是 string array；`serpapi_engine` 只允许 `google_light` 或 `google`。非法值会在搜索前退出。只有 `scrape_top: 0` / `--scrape-top 0` 用来关闭额外抓取。优先级是：CLI 单源 count > CLI `--count` > JSON `counts.xxx` > JSON `count` > 代码默认值。

### API / 免费额度

免费额度来自各服务公开免费层或常见免费用法，可能随服务商调整；代码不会校验套餐类型。

| 信源 | 免费额度 | 注册要求 | 注册地址 | 备注 |
|------|----------|----------|----------|------|
| 🔍 **Brave Search** | 1,000 次/月 | 邮箱 + 信用卡 | https://brave.com/search/api/ | 可用，但不是最轻量的免费配置 |
| 🌐 **Tavily** | 1,000 次/月 | 邮箱，无需信用卡 | https://tavily.com | 推荐；AI 优化结果 + advanced answer |
| ✨ **Exa** | 1,000 次/月 | 邮箱，无需信用卡 | https://exa.ai | 推荐；搜索 + `contents.text` 正文 |
| 🔥 **Firecrawl** | 1,000 次/月 | 邮箱，无需信用卡 | https://www.firecrawl.dev | 只做 metadata search；不使用 Firecrawl scrape 后端 |
| 🔎 **SerpAPI**（Google） | 250 次/月 | 邮箱，无需信用卡 | https://serpapi.com | 推荐；默认 `google_light`；`google` 才通常返回 Knowledge Graph |
|  **GitHub** | REST API token 额度以 GitHub 为准 | GitHub 账号 | https://github.com/settings/tokens | 没有 token 时 fallback 到已登录的 `gh` CLI |

### Twitter / X 可选配置

Twitter / X 需要 `pip install twikit-ng`，并提供 cookies（`~/.search-keys.json` 的 `twitter` 字段、`TWITTER_COOKIES_PATH`，或默认 `~/.mcp-twikit/cookies.json`）。

`default` 和 `discussion` 会尝试调用 Twitter/X，因为它常常提供最新项目反馈和讨论。但 Twitter/X 不是零配置源：需要安装 `twikit-ng`，并提供登录 cookies。

```powershell
python -m pip install twikit-ng
```

如果没有安装依赖、cookies 缺失/过期、或遇到 429 限流，命令不会整体失败；结果中会显示 `twitter error`，其它来源仍会正常输出。需要稳定社交结果时，先确认：

- `python -c "import twikit"` 能成功
- `~/.search-keys.json` 中有 `"twitter": {"auth_token": "...", "ct0": "..."}`
- cookies 没有过期，且账号没有触发登录验证/限流

---

## 🚀 使用示例

```powershell
# 默认全源聚合：覆盖网页、详情、仓库和 Twitter/X
python search.py "epub to markdown"

# 轻量详情搜索：Tavily + Exa，通常能直接带回正文/摘要
python search.py "agent memory" --type lite

# Twitter/X 讨论
python search.py "Claude Code feedback" --type discussion

# 默认全源 + 自动抓取前 3 条 URL 全文
python search.py "rust async runtime" --scrape-top 3

# 仅 GitHub 仓库
python search.py "vector database" --type github

# 单一信源
python search.py "latest Rust 1.80 features" --type serpapi

# 调整数量和超时
python search.py "react hooks" --count 15 --timeout 60

# 节省 token
python search.py "react hooks" --brief
```

抓取阶段默认是 best-effort：每个候选 URL 会尝试 Jina Reader / Exa Contents / Tavily Extract fallback 链；成功就进入正文池，失败或超过 `--scrape-timeout` 会写入 Errors，不会静默丢掉，也不会自动用别的 URL 补位。

### 输出格式

```
## Search Results: `fastapi framework`

**Sources (raw hits):** 🔍 **brave**: 10 | 🌐 **tavily**: 10 | ✨ **exa**: 10 | 🔎 **serpapi**: 10 | 📦 **github-repos**: 10

### Source Status
| Source | Raw hits | Status | Detail |
|---|---:|---|---|
| 🔍 brave | 10 | OK | |
| 🔎 serpapi | 0 | ERROR | HTTP Error 401: Unauthorized |

**Consensus:** 42 unique URLs, 6 matched by 2+ sources (top weight: ×4)

### URL Inventory
| # | Source | Weight | Title | URL |
|---:|---|---:|---|---|
| 1 | 🐦 twitter | 1 | Example tweet | https://x.com/i/web/status/... |

### Errors
| Source | Error |
|---|---|
| 🔎 serpapi | HTTP Error 401: Unauthorized |

### Ranked Results

1. **【×4】** 📦 **[fastapi/fastapi](https://github.com/fastapi/fastapi)** ⭐90000  _from: github-repos, brave, tavily, exa_

2. **【×2】** 🔍 **[Building a CRUD App with FastAPI](https://example.com/fastapi-crud)**  _from: brave, tavily_
```

---

## 🛠 命令行参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `--type` | `default` | 主路由：`default` / `lite` / `discussion`；单源直连：`brave` / `tavily` / `exa` / `firecrawl` / `serpapi` / `github` / `twitter` |
| `--count N` | 各源独立 | 正整数；全局覆盖单源 count；随后按各 provider/page-size 或本地保守上限 clamp |
| `--brave-count` / `--tavily-count` / `--exa-count` / `--firecrawl-count` / `--serpapi-count` / `--github-count` / `--twitter-count` | 见 SKILL.md | 单源覆盖 |
| `--serpapi-engine` | `google_light` | 也支持 `google`；`google` 才通常包含 Knowledge Graph |
| `--timeout N` | `60` | 每批并发 source 的等待上限；各 provider 内部还有自己的 HTTP timeout |
| `--config PATH` | `./multi-search-config.json` | 非敏感默认参数配置文件；CLI 参数优先 |
| `--scrape-top N` | `30` | 默认最多额外抓取 30 个缺正文 URL；已有正文不消耗额度；传 `0` 或 `--no-scrape` 关闭 |
| `--no-scrape` | — | 快捷关闭 scrape |
| `--scrape-chars N` | `6000` | 每页最大字符数；轻量预览用 2000，深挖用 12000+ |
| `--scrape-per-source N` | `6` | 正整数；每个来源最多抓几条（防霸屏） |
| `--scrape-timeout N` | `60` | 整批额外抓取等待上限；超时 URL 会在 Errors 中显示，不会静默消失 |
| `--scrape-concurrency N` | `5` | 额外抓取并发 worker 数；key 池按 URL 错开起始 key，并保留同 URL 内 fallback |
| `--expand "q2" "q3"` | — | 并行扩展查询（扩展查询使用 `lite` 路由，省请求链路） |
| `--brief` | — | 仅输出标题+URL |
| `--verbose` | — | 展示 Tavily AI Answer / SerpAPI KG 和普通搜索 snippet |

结果会先输出诊断信息再输出排序列表：

- **Sources (raw hits)**：URL 去重前每个 provider 的原始命中数。
- **Source Status**：每个已运行、跳过或失败的 source 一行。
- **URL Inventory**：所有 unique URL 表格；Twitter/X 推文也必须有可点击 URL。
- **Errors**：缺 key、依赖缺失、timeout、401/403/429、provider exception 都会列出。
- **Ranked Results**：默认只保留标题、URL、来源、权重，以及 Twitter 的短状态信号；普通 snippet 用 `--verbose` 展开。

---

## 📋 作为 GitHub Copilot / Claude Code Skill 使用

将本仓库内容放进 agent 的 skills 目录：

```
.github/skills/multi-search/
├── search.py
└── SKILL.md
```

然后在对话中说"搜索 ..."、"multi-search ..."、"查一下 ..." 即可触发。详见 [SKILL.md](SKILL.md)。

---

## 🔒 安全

- API key 文件 `.search-keys.json` 已在 `.gitignore` 中
- **绝不要把 key 写进任何提交的代码**
- 推荐用环境变量或 OS 凭据管理器（macOS Keychain / Windows Credential Manager）

---

## 📄 License

[MIT](LICENSE)
