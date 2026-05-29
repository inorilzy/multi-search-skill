# multi-search-skill

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)

并行聚合搜索 — 一条命令同时调用 **9 个信源**：Web 搜索 + Google + 代码仓库 + 社区问答 + Twitter/X + 可选全文抓取，按“共识权重”排序输出去重 Markdown 结果。

> 全部信源都有 **永久免费额度**，下方列出每个 key 的免费申请地址。

---

## ✨ 特性

- **9 信源并行**：12 个 worker 线程，5–15 秒完成全部查询
- **共识权重排序**：被多个信源同时命中的结果置顶，标记 `【×N】from: brave, tavily, ...`
- **零配置可用**：无 key 时仍可跑 HackerNews / Stack Overflow / GitHub（gh CLI）
- **聚合策略**：A 类（Tavily/Exa/Firecrawl）自带全文不二抓；B 类（Brave/SerpAPI/Baidu/HN/SO/GitHub Repos）按共识权重调 Jina Reader（GitHub Repos 自动重写到 raw README）；Twitter 作为独立详情类，推文 + 评论与 A/B 合并输出
- **AI Answer 顶部展示**：Tavily / Exa / SerpAPI Knowledge Graph / Baidu 千帆答案合并置顶
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
  "tavily": "tvly-xxxx",
  "exa": "xxxx",
  "firecrawl": "fc-xxxx",
  "serpapi": "xxxx",
  "baidu": "bce-v3/ALTAK-xxxx/xxxx",
  "github": "ghp_xxxx",
  "jina": "jina_xxxx"
}
```

或用环境变量：`BRAVE_SEARCH_API_KEY` / `TAVILY_API_KEY` / `EXA_API_KEY` / `FIRECRAWL_API_KEY` / `SERPAPI_KEY` / `BAIDU_API_KEY` / `GITHUB_TOKEN` / `JINA_API_KEY`。

### 免费额度 & 申请地址

| 信源 | 免费额度 | 注册地址 | 备注 |
|------|----------|----------|------|
| 🔍 **Brave Search** | 2,000 次/月 | https://brave.com/search/api/ | 邮箱注册即得 |
| 🌐 **Tavily** | 1,000 次/月 | https://tavily.com | AI 优化结果 + advanced answer |
| ✨ **Exa** | 1,000 次/月 | https://exa.ai | 神经搜索 + outputSchema 全局答案 |
| 🔥 **Firecrawl** | 500 credits/月 | https://www.firecrawl.dev | 搜索时直接返回全文 markdown |
| 🔎 **SerpAPI**（Google） | 250 次/月 | https://serpapi.com | 默认 `google_light` 引擎更省 quota |
| 🐾 **百度千帆 AI Search** | 1,500 次/月 + AI 100/天 | https://console.bce.baidu.com/qianfan | 中文搜索效果最好 |
| 📦 **GitHub** | 5,000 req/h（PAT） | https://github.com/settings/tokens | 推荐 `gh auth login`（自动管理） |
| 📖 **Jina Reader**（可选） | 20 RPM 免费 | https://jina.ai/reader/ | scrape-top 默认走 Jina，Firecrawl 兜底 |

### 无需 key 的信源

| 信源 | 说明 |
|------|------|
| 🟠 HackerNews | Algolia 公共 API |
| 🏆 Stack Overflow | StackExchange 公共 API |

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
python search.py "中文大模型对比" --type baidu

# 调整数量和超时
python search.py "react hooks" --count 15 --timeout 60

# 节省 token
python search.py "react hooks" --brief
```

### 输出格式

```
## Sources (raw hits): brave=20, tavily=20, exa=20, serpapi=15, baidu=20, github=20, ...
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
| `--type` | `all` | `all` / `web` / `repos` / `github` / `community` / `twitter` / `x` / `brave` / `tavily` / `exa` / `firecrawl` / `serpapi` / `google` / `baidu` / `hn` / `so` |
| `--count N` | 各源独立 | 全局覆盖单源 count |
| `--brave-count` / `--tavily-count` / `--exa-count` / `--firecrawl-count` / `--serpapi-count` / `--baidu-count` / `--github-count` / `--hn-count` / `--so-count` | 见 SKILL.md | 单源覆盖 |
| `--serpapi-engine` | `google_light` | 也支持 `google`（含 Knowledge Graph） |
| `--timeout N` | `60` | 单源超时秒数 |
| `--scrape-top N` | `0` | 搜完后抓 Top N URL 全文（Jina → Firecrawl 兜底，上限 30） |
| `--scrape-chars N` | `2000` | 每页最大字符数 |
| `--scrape-per-source N` | `3` | 每个来源最多抓几条（防霸屏） |
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
