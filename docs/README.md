# 文档索引

本目录存放设计、审查、验收和 provider 参考文档。**只有“现行文档”描述当前代码**；带日期的审查/验收记录和 `history/` 下的架构材料是历史快照，不再随代码更新。

现行产品入口和桌面端能力见 [仓库 README](../README.md)；搜索概念定义见 [CONTEXT.md](../CONTEXT.md)。MCP `server.py` 入口已在去 MCP 迁移中删除，任何仍描述它的文档都只作历史参考。

## 现行文档

| 文档 | 内容 |
|---|---|
| [glossary.md](glossary.md) | 搜索、来源、路由、正文、缓存、Key 状态的术语和接口约定。 |
| [route-capability-table.md](route-capability-table.md) | 各 route 包含的搜索源、能力与默认超时。 |
| [source-tracing-validation.md](source-tracing-validation.md) | 原文追踪验收流程：用 Skill 驱动一次可复核的来源链。 |
| [search-snapshot-replay.md](search-snapshot-replay.md) | 搜索快照的生成与重放，用于对比排序和正文选择。 |
| [query-fusion-evaluation.md](query-fusion-evaluation.md) | 查询融合的评估方法、指标和人工复核要求。 |

## 历史记录（按日期，不再更新）

这些文档保留当时的审查、验收或发布语境，结论可能已被后续修复改变。

| 文档 | 内容 |
|---|---|
| [candidate-first-release.md](candidate-first-release.md) | 0.4.0 发布说明；仍描述 MCP 入口，仅作历史发布语境。 |
| [legacy-skill.md](legacy-skill.md) | 旧版 Skill 与调用方式存档。 |
| [legacy-scrape-cleanup-2026-09-12.md](legacy-scrape-cleanup-2026-09-12.md) | 旧抓取链清理记录。 |
| [route-redesign-plan.md](route-redesign-plan.md) | 路由重构计划。 |
| [search-focused-improvement-plan-2026-09-10.md](search-focused-improvement-plan-2026-09-10.md) | 搜索改进计划。 |
| [query-fusion-experiments.md](query-fusion-experiments.md) | 查询融合实验记录。 |
| [deep-research-framework-notes-2026-09-10.md](deep-research-framework-notes-2026-09-10.md) | 深度研究框架调研笔记。 |
| [deep-research-opportunities-2026-09-10.md](deep-research-opportunities-2026-09-10.md) | 深度研究工作流机会点。 |
| [project-audit-2026-09-10.md](project-audit-2026-09-10.md) | 2026-09-10 项目审计。 |
| [project-audit-2026-09-12.md](project-audit-2026-09-12.md) | 2026-09-12 项目审计。 |
| [project-audit-2026-09-12-round2.md](project-audit-2026-09-12-round2.md) | 2026-09-12 第二轮项目审计。 |
| [agent-acceptance-2026-09-10.md](agent-acceptance-2026-09-10.md) | Agent 端到端验收记录。 |
| [provider-acceptance-2026-09-10.md](provider-acceptance-2026-09-10.md) | Provider 验收记录。 |
| [provider-acceptance-community-2026-09-10.md](provider-acceptance-community-2026-09-10.md) | 社区来源验收记录。 |
| [provider-acceptance-paid-2026-09-10.md](provider-acceptance-paid-2026-09-10.md) | 付费来源验收记录。 |
| [architecture-review-2026-09-05.md](architecture-review-2026-09-05.md) | 2026-09-05 架构审查（图源 [architecture-review-2026-09-05.mmd](architecture-review-2026-09-05.mmd)）。 |
| [architecture-review-2026-09-07.md](architecture-review-2026-09-07.md) | 2026-09-07 架构审查。 |
| [audit-fixes-2026-09-10.md](audit-fixes-2026-09-10.md) | 2026-09-10 审计修复记录。 |
| [audit-integration-2026-09-12.md](audit-integration-2026-09-12.md) | 2026-09-12 审计项集成记录。 |
| [audit-round2-integration-2026-09-12.md](audit-round2-integration-2026-09-12.md) | 2026-09-12 第二轮审计集成记录。 |
| [audit-remaining-integration-2026-09-13.md](audit-remaining-integration-2026-09-13.md) | 2026-09-13 剩余审计项集成记录。 |
| [target-warning-evidence-2026-09-12.md](target-warning-evidence-2026-09-12.md) | 目标警告证据记录。 |
| [skill-ticket-integration-2026-09-12.md](skill-ticket-integration-2026-09-12.md) | Skill 工单集成记录。 |

## 历史架构（已归档）

`docs/history/` 下的文档描述 MCP 时代的旧架构，入口已删除，仅用于追溯当时的实现。

| 文档 | 内容 |
|---|---|
| [architecture-simple.md](history/architecture-simple.md) | 2026-09-12 简易架构（含已删除的 MCP 入口）。 |
| [mcp-dispatch.md](history/mcp-dispatch.md) | 已删除的 MCP 4 槽位调度设计。 |
| [current-architecture.html](history/current-architecture.html) | 2026-09-12 架构图（静态页面）。 |
| [current-architecture.mmd](history/current-architecture.mmd) | 架构图 Mermaid 源码。 |
| [current-architecture.svg](history/current-architecture.svg) | 架构图 SVG。 |

## Provider 参考

各搜索、抓取服务的接入说明和官方文档摘要：

- Brave：[web-search.md](brave/web-search.md)、[web-search-skill.md](brave/web-search-skill.md)
- Exa：[search-api-guide.md](exa/search-api-guide.md)、[search-best-practices.md](exa/search-best-practices.md)、[contents-api-guide.md](exa/contents-api-guide.md)、[coding-agent 指南](exa/search-api-guide-for-coding-agents.md)
- Firecrawl：[search.md](firecrawl/search.md)
- Jina：[reader.md](jina/reader.md)
- Parallel：[search.md](parallel/search.md)
- SerpAPI：[google-light-api.md](serpapi/google-light-api.md)
- Tavily：[search.md](tavily/search.md)、[extract.md](tavily/extract.md)

## 示例

- [examples/search-snapshot.json](examples/search-snapshot.json)：搜索快照示例。
- [examples/source-tracing/scenarios.json](examples/source-tracing/scenarios.json)：原文追踪场景。
- [exa/contents-best-practices.md](exa/contents-best-practices.md)、[exa/contents-api-guide-for-coding-agents.md](exa/contents-api-guide-for-coding-agents.md)、[exa/search-api-guide-for-coding-agents.md](exa/search-api-guide-for-coding-agents.md)：面向 coding agent 的 Exa 补充说明。
