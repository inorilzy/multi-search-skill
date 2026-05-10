---
name: multi-search
description: >
  Aggregated search across 12+ sources: Brave, Tavily, SerpAPI (Google), Bing, Exa, GitHub,
  Sourcegraph, HackerNews, Stack Overflow, npm, PyPI, grep.app, plus optional Firecrawl
  scraping of top results. Combines web results, repo discovery, code search, community Q&A,
  package registries, and full-page content extraction in one parallel request.
  Use when researching topics that need broad coverage across web, code, and community.
  Activate when user says: search, find, look up, multi-search, search everywhere,
  搜索, 查找, 查一下, 聚合搜索, 多源搜索.
argument-hint: "<query> [--type all|web|code|repos|packages|community|...] [--count N] [--scrape-top N] [--timeout N]"
---

# Multi-Search

Parallel aggregated search across **12+ sources** in a single command, with optional
Firecrawl scraping of top result URLs.

## Sources Overview

| Icon | Source | Type | Key Required | In `--type all` |
|------|--------|------|-------------|:-:|
| 🔍 | Brave Search | Web | `brave` | ✅ |
| 🌐 | Tavily | Web (AI-tuned) | `tavily` | ✅ |
| 🔎 | SerpAPI | Google results | `serpapi` | ✅ |
| ✨ | Exa | Neural web search | `exa` | ✅ if key |
| 🔥 | Firecrawl | Web search + scrape | `firecrawl` | ❌ (use `--type firecrawl` or `--scrape-top`) |
| 📦 | GitHub Repos | Code repos | `github` token (or `gh` CLI fallback) | ✅ |
| 💻 | GitHub Code | Code search | `github` token (or `gh` CLI fallback) | ❌ (explicit only) |
| 🔎 | Sourcegraph | Code/text search | `sourcegraph` (optional) | ✅ |
| 🐾 | Baidu (千帆) | Chinese web search | `baidu` (Qianfan API Key) | ✅ if key |
| 🧬 | grep.app | Code regex search | None (rate-limited) | ❌ (use `--type code`/`grep`) |
| 🟠 | HackerNews | Community/tech | None | ✅ |
| 🏆 | Stack Overflow | Q&A | None | ✅ |
| 🐍 | PyPI | Python packages | None (JSON API) | ❌ (use `--type packages`) |
| 📗 | npm | JS/TS packages | None | ❌ (use `--type packages`) |

## API Key Setup

Keys are read from (in priority order):
1. Environment variables: `BRAVE_SEARCH_API_KEY`, `TAVILY_API_KEY`, `SOURCEGRAPH_TOKEN`,
   `EXA_API_KEY`, `SERPAPI_KEY`, `FIRECRAWL_API_KEY`, `BAIDU_API_KEY`, `GITHUB_TOKEN`
2. `~/.search-keys.json`:
   ```json
   {
     "brave": "BSAxxxx",
     "tavily": "tvly-xxxx",
     "sourcegraph": "sgp_xxxx",
     "exa": "xxxx",
     "serpapi": "xxxx",
     "firecrawl": "fc-xxxx",
     "baidu": "bce-v3/ALTAK-xxxx/xxxx",
     "github": "ghp_xxxx"
   }
   ```

GitHub token is **optional** — if absent, falls back to `gh` CLI (must be `gh auth login`'d).

Sources without required keys are silently skipped in `--type all` mode.

## Count & Timeout Control

| Parameter | Default | Effect |
|-----------|---------|--------|
| `--count N` | `10` | Global default for all sources |
| `--brave-count N` | fallback → `--count` | Brave Search only |
| `--tavily-count N` | fallback → `--count` | Tavily only |
| `--github-count N` | fallback → `--count` | GitHub only |
| `--sg-count N` | fallback → `--count` | Sourcegraph only |
| `--timeout N` | `45` | Per-source timeout in seconds (raise if SerpAPI is slow) |
| `--scrape-top N` | `0` | Auto-scrape top N result URLs via Firecrawl after search |
| `--scrape-chars N` | `2000` | Max chars per scraped page in output |

## Search Types

| Flag | Sources Used |
|------|-------------|
| `--type all` (default) | Brave + Tavily + SerpAPI + Bing\* + Exa\* + GitHub repos + Sourcegraph + grep.app + HackerNews + StackOverflow |
| `--type web` | Brave + Tavily + SerpAPI + Bing\* + Exa\* + Firecrawl\* |
| `--type code` | Sourcegraph + grep.app |
| `--type repos` | GitHub repositories only |
| `--type packages` | npm + PyPI |
| `--type community` | HackerNews + Stack Overflow |
| `--type sourcegraph` / `serpapi` / `firecrawl` / `bing` / `exa` | Single source only |
| `--type grep` / `hn` / `so` / `pypi` / `npm` / `github` / `github-code` | Single source only |

\* Only active if matching key is configured.

## Firecrawl Scrape (`--scrape-top`)

After the search completes, fetch full Markdown content of the top N URLs in parallel:

```
python search.py "rust async runtime" --type web --scrape-top 3
python search.py "tokio internals" --scrape-top 5 --scrape-chars 1500
```

Output appends a `## 🔥 Scraped Content (Firecrawl)` section with each URL as an H3
heading + extracted main content (`onlyMainContent: true`). Each scrape costs 1 Firecrawl credit.

> **Sourcegraph tips:** Add filter syntax directly in the query:
> - `"epub lang:python"` — Python files only
> - `"auth repo:github.com/org/repo"` — specific repo
> - `"TODO file:*.go"` — Go files only

## Workflow

When user provides a search query:

1. **Check keys** — look for `~/.search-keys.json` or env vars
2. **Run search** using the script:
   ```
   python .github/skills/multi-search/search.py "<query>" [--type TYPE] [--count N]
   ```
3. **Present results** — the script outputs formatted Markdown with source icons
4. **Follow up** — offer to fetch full content from top URLs using `fetch_webpage`

## Key Setup Help

```powershell
# PowerShell — store API keys
$keys = @{ brave = "YOUR_BRAVE_KEY"; tavily = "YOUR_TAVILY_KEY"; sourcegraph = "sgp_xxx" }
$keys | ConvertTo-Json | Set-Content "$env:USERPROFILE\.search-keys.json"
```
```bash
# bash/zsh
echo '{"brave":"BSAxxxx","tavily":"tvly-xxxx","sourcegraph":"sgp_xxxx"}' > ~/.search-keys.json
```

Free API keys:
- **Brave**: https://brave.com/search/api/ (2000 queries/month free)
- **Tavily**: https://tavily.com (1000 queries/month free)
- **Sourcegraph**: https://sourcegraph.com/user/settings/tokens (free)
- **Exa**: https://exa.ai (free tier available)
- **Bing**: Azure portal → Bing Search API (free tier: 1000 queries/month)

## Example Invocations

```
# Full multi-source search (9 sources in parallel)
python .github/skills/multi-search/search.py "epub to markdown" --type all

# Web search + auto-scrape top 3 results to full markdown
python .github/skills/multi-search/search.py "rust async runtime" --type web --scrape-top 3

# Code search with Sourcegraph filter syntax
python .github/skills/multi-search/search.py "epub parsing lang:python" --type sourcegraph

# Community discussions only
python .github/skills/multi-search/search.py "async python performance" --type community

# Package discovery (npm + PyPI)
python .github/skills/multi-search/search.py "epub parser" --type packages

# Bigger result counts + longer timeout for slow sources
python .github/skills/multi-search/search.py "react hooks" --count 15 --timeout 60

# Per-source count tuning
python .github/skills/multi-search/search.py "markdown" --brave-count 5 --tavily-count 3 --sg-count 8

# SerpAPI standalone (Google results)
python .github/skills/multi-search/search.py "latest Rust 1.80 features" --type serpapi

# Firecrawl search standalone (slower but high quality)
python .github/skills/multi-search/search.py "WebGPU compute shader" --type firecrawl
```

## Notes

- Results are deduplicated by URL across all sources
- `--type all` runs ~9 sources in parallel (ThreadPoolExecutor with 12 workers)
- Default `--timeout 45s` covers SerpAPI; raise to 60+ if you see frequent timeouts
- Firecrawl search is excluded from `--type all` (too slow); use `--type firecrawl` or `--scrape-top`
- grep.app may return 429 rate-limit errors — these are caught and shown gracefully
- PyPI uses the JSON API for exact-name lookup (Cloudflare blocks the search page)
- For deep content analysis of a result, use `--scrape-top N` or `fetch_webpage` on the URL
