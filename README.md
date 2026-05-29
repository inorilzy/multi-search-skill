# multi-search-skill

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)

并行聚合搜索 — 一条命令同时调用 **8 个信源**：Web 搜索 + Google + 代码仓库 + 社区问答 + Twitter/X + 可选全文抓取，按“共识权重”排序输出去重 Markdown 结果。

> 全部信源都有 **永久免费额度**，下方列出每个 key 的免费申请地址。

---

## ✨ 特性

- **8 信源并行**：12 个 worker 线程，5–15 秒完成全部查询
- **多 key 池**：任何 key 字段可作为 string 或 string 列表，`pick_key()` 随机轮换，免单 key 耗尽
- **共识权重排序**：被多个信源同时命中的结果置顶，标记 `【×N】from: brave, tavily, ...`
- **零配置可用**：无 key 时仍可跑 HackerNews / Stack Overflow / GitHub（gh CLI）
- **聚合策略**：A 类（Tavily/Exa/Firecrawl）自带全文不二抓；B 类 PREFER（Brave/SerpAPI/HN/SO/GitHub Repos）按共识权重抓取（GitHub Repos 自动重写到 raw README）；Twitter 本身 `scraped_content` 已有推文+评论，不进抓取队列
- **抓取后端可调**：默认全走 Jina；`--jina-first N` 调成「前 N 走 Jina + 剩下在 tavily/exa/firecrawl 间 round-robin」；`--no-jina` 跳过 Jina
- **AI Answer 顶部展示**：Tavily / Exa / SerpAPI Knowledge Graph 答案合并置顶
- **TLS 稳定**：内置 SSL 上下文 + 重试，解决 Python 3.12 严格 TLS 下的 EOF 错误

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
  "tavily": ["tvly-key1", "tvly-key2"],
  "exa": ["exa-key1", "exa-key2", "exa-key3"],
  "firecrawl": "fc-xxxx",
  "serpapi": "xxxx",
  "github": "ghp_xxxx",
  "jina": ["jina_key1", "jina_key2"],
  "twitter": { "auth_token": "...", "ct0": "..." }
}
```

> **多 key 池**：任何字段都可以是 single string 或 array of strings。多 key 时随机轮换（jina 按 URL index round-robin），单 key 颍度耗尽后仍能切下一个。

或用环境变量：`BRAVE_SEARCH_API_KEY` / `TAVILY_API_KEY` / `EXA_API_KEY` / `FIRECRAWL_API_KEY` / `SERPAPI_KEY` / `GITHUB_TOKEN` / `JINA_API_KEY`。

### 免费额度 & 申请地址

| 信源 | 免费额度 | 注册地址 | 备注 |
|------|----------|----------|------|
| 🔍 **Brave Search** | 2,000 次/月 | https://brave.com/search/api/ | 邮箱注册即得 |
| 🌐 **Tavily** | 1,000 次/月 | https://tavily.com | AI 优化结果 + advanced answer |
| ✨ **Exa** | 1,000 次/月 | https://exa.ai | 神经搜索 + outputSchema 全局答案 |
| 🔥 **Firecrawl** | 500 credits/月 | https://www.firecrawl.dev | 搜索时直接返回全文 markdown |
| 🔎 **SerpAPI**（Google） | 250 次/月 | https://serpapi.com | 默认 `google_light` 引擎更省 quota |
|  **GitHub** | 5,000 req/h（PAT） | https://github.com/settings/tokens | 推荐 `gh auth login`（自动管理） |
| 📖 **Jina Reader**（可选） | 20 RPM 免费 | https://jina.ai/reader/ | scrape-top 默认主用 Jina；Tavily Extract / Exa contents / Firecrawl 作 fallback |

### 无需 key 的信源

| 信源 | 说明 |
|------|------|
| 🟠 HackerNews | Algolia 公共 API |
| 🏆 Stack Overflow | StackExchange 公共 API |
| 🐦 Twitter / X | 使用 cookies（放 `~/.search-keys.json` 的 `twitter` 字段，或复用 `~/.mcp-twikit/cookies.json`） |

---

## 🚀 使用示例

```powershell
# 默认全信源搜索
python search.py "epub to markdown"

# Web 搜索 + 自动抓取前 3 条 URL 全文
python search.py "rust async runtime" --type web --scrape-top 3

# 仅 GitHub 仓库（默认还会抓 README）
python search.py "vector database" --type repos

# 仅社区讨论（HN + Stack Overflow + Twitter）
python search.py "async python performance" --type community

# 单一信源
python search.py "latest Rust 1.80 features" --type serpapi

# 调整数量和超时
python search.py "react hooks" --count 15 --timeout 60

# 节省 token
python search.py "react hooks" --brief
```

### 输出格式

```
## Sources (raw hits): brave=20, tavily=20, exa=20, serpapi=15, github=20, ...
## Consensus: 87 unique URLs, 14 matched by 2+ sources (top weight: ×4)

### 【×4】fastapi/fastapi
_from: brave, tavily, serpapi, github_
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
| `--type` | `all` | `all` / `web` / `repos` / `github` / `community` / `twitter` / `x` / `brave` / `tavily` / `exa` / `firecrawl` / `serpapi` / `google` / `hn` / `so` |
| `--count N` | 各源独立 | 全局覆盖单源 count |
| `--brave-count` / `--tavily-count` / `--exa-count` / `--firecrawl-count` / `--serpapi-count` / `--github-count` / `--hn-count` / `--so-count` | 见 SKILL.md | 单源覆盖 |
| `--serpapi-engine` | `google_light` | 也支持 `google`（含 Knowledge Graph） |
| `--timeout N` | `60` | 单源超时秒数 |
| `--scrape-top N` | `30` | 搜完后抓 Top N URL 全文（默认开，上限 30；传 `0` 或 `--no-scrape` 关闭） |
| `--no-scrape` | — | 快捷关闭 scrape |
| `--scrape-chars N` | `2000` | 每页最大字符数 |
| `--scrape-per-source N` | `6` | 每个来源最多抓几条（防霸屏） |
| `--jina-first N` | `scrape_top` (all-Jina) | 前 N 个 URL 走 Jina；剩余 tavily/exa/firecrawl 轮转。Jina 额度紧张时设小（如 `20`） |
| `--no-jina` | — | 跳过 Jina，全 tavily/exa/firecrawl |
| `--expand "q2" "q3"` | — | 并行扩展查询（lite 模式仅 brave+tavily） |
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
