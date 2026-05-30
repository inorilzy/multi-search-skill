# multi-search-skill

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)

并行聚合搜索 — 一条命令按路由调用最多 **9 个信源**：Web 搜索、Google SERP、代码仓库、社区问答、Twitter/X，以及可选全文抓取，按“共识权重”排序输出去重 Markdown 结果。

> 不是所有信源都能零配置使用。无 key 时仍可跑 HackerNews / Stack Overflow；GitHub 需要 `GITHUB_TOKEN` / `GH_TOKEN`，或本机已登录 `gh` CLI；Twitter/X 需要 `twikit-ng` 和 cookies。

---

## ✨ 特性

- **3 个主 route**：`default` 跑全源，`lite` 跑 Tavily + Exa + Firecrawl，`discussion` 跑 Twitter/X + HackerNews + Stack Overflow
- **多 key 池**：API key 字段可作为 string 或 string 列表，`pick_key()` 随机轮换，降低单 key 配额耗尽风险
- **共识权重排序**：被多个信源同时命中的结果置顶，标记 `【×N】from: brave, tavily, ...`
- **基础零配置**：无 key 时可跑 HackerNews / Stack Overflow；GitHub 在本机 `gh auth login` 后也可用
- **聚合策略**：Tavily / Exa / Firecrawl / Twitter/X 搜索结果若带 `scraped_content` 会直接进入抓取内容区；Brave / SerpAPI / HN / SO / GitHub Repos 进入后续抓取候选池，GitHub repo 根 URL 抓取时会重写到 raw README
- **抓取后端可调**：默认不抓全文；传 `--scrape-top N` 后在 Tavily / Exa / Firecrawl 间轮转抓取
- **AI Answer 顶部展示**：Tavily / Exa / SerpAPI Knowledge Graph 答案合并置顶
- **TLS 稳定**：内置 SSL 上下文 + 重试，解决 Python 3.12 严格 TLS 下的 EOF 错误

---

## 📦 安装

```powershell
git clone https://github.com/inorilzy/multi-search-skill.git
cd multi-search-skill

# 核心搜索仅依赖 Python 3.9+ 标准库；Twitter/X 路由需要可选依赖 twikit-ng
python search.py "epub to markdown"
```

---

## 🔑 API Keys

所有 key 写入 `~/.search-keys.json`（**不要提交到仓库**）：

```json
{
  "brave": "BSAxxxx",
  "tavily": ["tvly-key1", "tvly-key2"],
  "exa": ["exa-key1", "exa-key2", "exa-key3"],
  "firecrawl": "fc-xxxx",
  "serpapi": "xxxx",
  "github": "ghp_xxxx",
  "twitter": { "auth_token": "...", "ct0": "..." }
}
```

> **多 key 池**：API key 字段可以是 single string 或 array of strings。多数源每次调用随机选一个 key；Twitter 的 `twitter` 字段是 cookie dict，不参与随机轮换。

或用环境变量：`BRAVE_SEARCH_API_KEY` / `BRAVE_API_KEY` / `TAVILY_API_KEY` / `EXA_API_KEY` / `FIRECRAWL_API_KEY` / `SERPAPI_API_KEY` / `SERPAPI_KEY` / `GITHUB_TOKEN` / `GH_TOKEN` / `TWITTER_COOKIES_PATH`。

### API / 配额参考

额度来自各服务公开免费层或常见免费用法，可能随服务商调整；代码不会校验套餐类型。

| 信源 | 参考额度 | 注册地址 | 备注 |
|------|----------|----------|------|
| 🔍 **Brave Search** | 2,000 次/月 | https://brave.com/search/api/ | 邮箱注册即得 |
| 🌐 **Tavily** | 1,000 次/月 | https://tavily.com | AI 优化结果 + advanced answer |
| ✨ **Exa** | 1,000 次/月 | https://exa.ai | 神经搜索 + outputSchema 全局答案 |
| 🔥 **Firecrawl** | 500 credits/月 | https://www.firecrawl.dev | 搜索时直接返回全文 markdown |
| 🔎 **SerpAPI**（Google） | 免费层额度以 SerpAPI 后台为准 | https://serpapi.com | 默认 `google_light`；`google` 才通常返回 Knowledge Graph |
|  **GitHub** | REST API token 额度以 GitHub 为准 | https://github.com/settings/tokens | 没有 token 时 fallback 到已登录的 `gh` CLI |

### 不使用 API key 的信源

| 信源 | 说明 |
|------|------|
| 🟠 HackerNews | Algolia 公共 API |
| 🏆 Stack Overflow | StackExchange 公共 API |
| 🐦 Twitter / X | 需要 `pip install twikit-ng`，并提供 cookies（`~/.search-keys.json` 的 `twitter` 字段、`TWITTER_COOKIES_PATH`，或默认 `~/.mcp-twikit/cookies.json`） |

### Twitter / X 可选配置

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
# 默认全源聚合：覆盖网页、详情、代码、社区和 Twitter/X
python search.py "epub to markdown"

# 轻量详情搜索：Tavily + Exa + Firecrawl，通常能直接带回正文/摘要
python search.py "agent memory" --type lite

# 社交和社区讨论：Twitter/X + HackerNews + Stack Overflow
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

### 输出格式

```
**Sources (raw hits):** 🔍 **brave**: 10 | 🌐 **tavily**: 10 | ✨ **exa**: 10 | 🔎 **serpapi**: 10 | 📦 **github-repos**: 10
**Consensus:** 42 unique URLs, 6 matched by 2+ sources (top weight: ×4)

### 【×4】fastapi/fastapi
_from: brave, tavily, serpapi, github-repos_
FastAPI framework, high performance, easy to learn...
https://github.com/fastapi/fastapi

### 【×2】Building a CRUD App with FastAPI
_from: brave, tavily_
...
```

---

## 🛠 命令行参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `--type` | `default` | 主路由：`default` / `lite` / `discussion`；常用别名：`all`、`social+community`、`social-community`；单源直连：`brave` / `tavily` / `exa` / `firecrawl` / `serpapi` / `google` / `github` / `hn` / `so` / `twitter` / `x` |
| `--count N` | 各源独立 | 全局覆盖单源 count；随后按各 provider 上限 clamp |
| `--brave-count` / `--tavily-count` / `--exa-count` / `--firecrawl-count` / `--serpapi-count` / `--github-count` / `--hn-count` / `--so-count` / `--twitter-count` | 见 SKILL.md | 单源覆盖 |
| `--serpapi-engine` | `google_light` | 也支持 `google`；`google` 才通常包含 Knowledge Graph |
| `--timeout N` | `60` | 单源超时秒数 |
| `--scrape-top N` | `0` | 默认不输出全文抓取内容；传 `N` 后复用源自带全文，并对候选 URL 抓取补充内容，候选抓取上限 30 |
| `--no-scrape` | — | 快捷关闭 scrape |
| `--scrape-chars N` | `2000` | 每页最大字符数 |
| `--scrape-per-source N` | `6` | 每个来源最多抓几条（防霸屏） |
| `--expand "q2" "q3"` | — | 并行扩展查询（扩展查询使用 `lite` 路由，省请求链路） |
| `--brief` | — | 仅输出标题+URL |

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
