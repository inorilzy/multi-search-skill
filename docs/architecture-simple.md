# 当前项目简易架构

按 2026-09-09 当前工作区代码核对。箭头表示主要调用或数据流；MCP 和 CLI 共用同一个 Core。

```mermaid
flowchart TB
    A["用户 / AI Agent<br/>Skill：工具选择与检索策略"]
    A --> M["MCP 入口 · stdio"]
    A --> L["CLI 入口 · multi-search"]
    M --> C["共享 Core · service.py<br/>搜索 / 抓取 / 读取 / 诊断"]
    L --> C

    CFG["行为配置 + 凭据<br/>配置文件 / 环境变量 / keys 文件"] -.-> C
    C -->|search_web / multi_search| S["检索计划与并发调度<br/>route / sources / expand"]
    S --> P["并行调用选定搜索源<br/>已注册 12 个：网页 / 技术 / 社区"]
    P --> R["URL 去重 + RRF 排序<br/>保留前 15 条"]
    R --> F["正文获取<br/>fetch_source / scrape_url"]
    C -->|已知 URL，直接抓取| F

    F -->|需要联网时| D{"按 URL 域名分派"}
    D -->|Reddit| RE["Reddit 专用 scraper<br/>eddrit 匿名 Token → Reddit API<br/>帖子正文 + 已加载评论"]
    D -->|其他网站| G["通用 scraper<br/>Jina / Exa / Tavily / Firecrawl"]

    DB[("SQLite · state.sqlite<br/>来源记录 / 正文缓存<br/>Key 健康 / 站点抓取记忆")]
    C <-->|运行状态| DB
    C -->|read_source：仅读缓存片段| DB
    F <-->|fetch_source：复用与写入正文缓存| DB
```

## 搜索源

| 分组 | 注册源 |
|---|---|
| 网页 | Brave、Parallel、Baidu、Tavily、Exa、SerpAPI、Firecrawl |
| 技术 | GitHub Repos、Hacker News、Stack Overflow |
| 社交与社区 | Twitter/X、V2EX |

`route` 或 `sources` 决定本次调用哪些源；`all` 包含全部 12 个搜索源。全局禁用配置仍会进一步过滤。

## 关键边界

- 搜索先排序，再为最终最多 15 条结果获取正文；可以复用已有正文或缓存，正文失败不会改变排名。结果包含摘要、正文预览及明确错误，MCP/CLI 按各自接口输出 JSON 或 Markdown。
- Reddit 仅位于正文抓取层，不是搜索源。`reddit.com` 及子域、`redd.it` 进入专用适配器；不支持的链接或请求失败明确报错。匿名 Token 保存在进程内，不写入 SQLite，也不需要账号 Cookie。
- `fetch_source` 可留存取得的正文，预览长度不截断缓存，仍受大小和保留期限约束；`read_source` 只读缓存。`scrape_url` 是直接抓取入口，不负责建立 `source_id` 正文缓存。
- URL 安全校验、超时与并发控制、凭据脱敏由共享支持模块提供。SQLite 保存运行状态，明文凭据由环境变量或 keys 文件提供。
- 辅助工具在 `scripts/` 和根目录 `test_*.py`：快照回放、查询融合评估、来源追踪验证及回归测试。查询加权是显式实验选项，默认仍使用等权融合。

## 代码入口

- [Skill](../skills/multi-search/SKILL.md)、[MCP](../multi_search_mcp/server.py)、[CLI](../multi_search_mcp/cli.py)
- [共享 Core](../multi_search_mcp/src/service.py)、[搜索源注册](../multi_search_mcp/src/search/registry.py)
- [正文域名分派](../multi_search_mcp/src/scrape/scrape.py)、[Reddit 适配器](../multi_search_mcp/src/scrape/scrapers/reddit.py)
- [SQLite 状态](../multi_search_mcp/src/state/state_store.py)
