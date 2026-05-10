# multi-search-skill

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/inorilzy/multi-search-skill/pulls)

并行聚合搜索 — 一条命令同时调用 **9+ 信源**：Web 搜索 + 代码搜索 + 社区问答 + 软件包注册中心 + 可选全文抓取，输出按"共识权重"排序的去重 Markdown 结果。

> 全部信源都有 **永久免费额度**，下方 README 列出每个 key 的免费申请地址。

---

## ✨ 特性

- **9+ 信源并行**：12 个 worker 线程，5–15 秒完成全部查询
- **共识权重排序**：被多个信源同时命中的结果置顶，标记 `【×N】from: brave, tavily, ...`
- **零配置可用**：无 key 时仍可跑 HackerNews / Stack Overflow / PyPI / npm / grep.app
- **TLS 稳定**：内置 SSL 上下文 + 重试，解决 Python 3.12 严格 TLS 下的 EOF 错误
- **Firecrawl 抓取**（可选）：搜完之后自动抓取 Top N 结果的全文 Markdown

---

## 📦 安装

```powershell
git clone https://github.com/inorilzy/multi-search-skill.git
cd multi-search-skill

# 仅依赖 Python 3.9+ 标准库 —— 无 pip 安装步骤
python search.py "epub to markdown" --type all
```

---

## 🔑 API Keys（全部免费）

所有 key 写入 `~/.search-keys.json`（**不要提交到仓库**）：

```json
{
  "brave": "BSAxxxx",
  "tavily": "tvly-xxxx",
  "serpapi": "xxxx",
  "exa": "xxxx",
  "firecrawl": "fc-xxxx",
  "sourcegraph": "sgp_xxxx",
  "baidu": "bce-v3/ALTAK-xxxx/xxxx",
  "github": "ghp_xxxx"
}
```

或用环境变量：`BRAVE_SEARCH_API_KEY` / `TAVILY_API_KEY` / `SERPAPI_KEY` / `EXA_API_KEY` / `FIRECRAWL_API_KEY` / `SOURCEGRAPH_TOKEN` / `BAIDU_API_KEY` / `GITHUB_TOKEN`。

### 免费额度 & 申请地址

| 信源 | 免费额度 | 注册地址 | 备注 |
|------|----------|----------|------|
| 🔍 **Brave Search** | 2,000 次/月 | https://brave.com/search/api/ | 邮箱注册即得，无需信用卡 |
| 🌐 **Tavily** | 1,000 次/月 | https://tavily.com | AI 优化的搜索结果，免费层够用 |
| 🔎 **SerpAPI**（Google） | 100 次/月 | https://serpapi.com | 真正的 Google 搜索结果 |
| ✨ **Exa** | 1,000 次/月 | https://exa.ai | 神经搜索，适合发现性查询 |
| 🔥 **Firecrawl** | 500 credits/月 | https://www.firecrawl.dev | 1 credit/抓取，可抓全文 Markdown |
| 🔎 **Sourcegraph** | 完全免费 | https://sourcegraph.com/user/settings/tokens | 公开代码搜索，需登录拿 token |
| 🐾 **百度千帆 AI Search** | 1,500 次/月 | https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application | 中文搜索效果最好，需要百度智能云账号 |
| 📦 **GitHub** | 5,000 req/h（PAT）<br>60 req/h（匿名） | https://github.com/settings/tokens | 推荐用 `gh auth login`（CLI 自动管理） |

### 无需 key 的信源

| 信源 | 说明 |
|------|------|
| 🟠 HackerNews | Algolia 公共 API |
| 🏆 Stack Overflow | StackExchange 公共 API |
| 🐍 PyPI | JSON API |
| 📗 npm | Registry API |
| 🧬 grep.app | 公共代码正则搜索（有速率限制，opt-in） |

---

## 🚀 使用示例

```powershell
# 默认全信源搜索（约 9 个并行）
python search.py "epub to markdown"

# Web 搜索 + 自动抓取 Top 3 结果全文
python search.py "rust async runtime" --type web --scrape-top 3

# 只搜代码（Sourcegraph 支持 lang:/repo: 过滤语法）
python search.py "epub parsing lang:python" --type code

# 只搜软件包（npm + PyPI）
python search.py "markdown parser" --type packages

# 只搜社区讨论
python search.py "async python performance" --type community

# 单一信源
python search.py "latest Rust 1.80 features" --type serpapi
python search.py "中文大模型对比" --type baidu

# 调整数量和超时
python search.py "react hooks" --count 15 --timeout 60
```

### 输出格式

```
## Sources (raw hits): brave=10, tavily=10, serpapi=8, baidu=10, github=10, ...
## Consensus: 47 unique URLs, 12 matched by 2+ sources (top weight: ×4)

### 【×4】fastapi-admin/fastapi-admin
_from: brave, tavily, serpapi, github_
A fast admin dashboard based on FastAPI...
https://github.com/fastapi-admin/fastapi-admin

### 【×2】Building a CRUD App with FastAPI
_from: brave, tavily_
...
```

---

## 🛠 命令行参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `--type` | `all` | `all` / `web` / `code` / `repos` / `packages` / `community` / `serpapi` / `firecrawl` / `baidu` / `grep` / `hn` / `so` / `pypi` / `npm` / `github` / `github-code` / `sourcegraph` |
| `--count N` | `10` | 每个信源返回数量 |
| `--brave-count` / `--tavily-count` / `--github-count` / `--sg-count` | 同 `--count` | 单源覆盖 |
| `--timeout N` | `45` | 单源超时秒数 |
| `--scrape-top N` | `0` | 搜完后用 Firecrawl 抓 Top N URL 全文 |
| `--scrape-chars N` | `2000` | 抓取每页最大字符数 |

---

## 📋 作为 GitHub Copilot / Claude Code Skill 使用

将本仓库内容放进你 agent 的 skills 目录：

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
