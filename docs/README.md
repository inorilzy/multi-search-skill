# 文档索引

本目录存放设计、审查、验收和 provider 参考文档。**只有“现行文档”描述当前代码**；带日期的审查/验收记录、证据目录和 `history/` 下的架构材料是历史快照，不再随代码更新。历史资料保留原路径，避免破坏证据之间的引用。

现行产品入口和桌面端能力见 [仓库 README](../README.md)；搜索概念定义见 [CONTEXT.md](../CONTEXT.md)。MCP `server.py` 入口已在去 MCP 迁移中删除，任何仍描述它的文档都只作历史参考。

## 现行文档

| 文档 | 内容 |
|---|---|
| [glossary.md](glossary.md) | 搜索、来源、路由、正文、缓存、Key 状态的术语和接口约定；「代码出处」列由 `scripts/check_glossary_paths.py` 在 CI 中逐项校验。 |
| [route-capability-table.md](route-capability-table.md) | 各 route 包含的搜索源、能力与默认超时。 |
| [CLI 指南](../skills/multi-search/references/cli.md) | 实际 CLI 用法、shell 安全规则、路由组与抓取链配置（不另建重复的 docs/cli.md）。 |
| [Managed Twitter cookies 协议 v1](../desktop/src-tauri/COOKIE-PROTOCOL.md) | DPAPI 托管 Cookie 的存储校验、IPC 契约、file/managed 模式迁移与威胁边界。 |
| [source-tracing-validation.md](source-tracing-validation.md) | 原文追踪验收流程：用 Skill 驱动一次可复核的来源链。 |
| [search-snapshot-replay.md](search-snapshot-replay.md) | 搜索快照的生成与重放，用于对比排序和正文选择。 |
| [query-fusion-evaluation.md](query-fusion-evaluation.md) | 查询融合的评估方法、指标和人工复核要求。 |

## 抓取链与 2026-10-22 修复交付（历史记录，不再更新）

这些文档记录有序抓取链、站点抓取记忆、DPAPI 托管 Cookie 和 2026-10-22 审查修复的交付语境；其中的失败结论与未验边界是冻结时的历史 verdict，后续修复不追改，也不代表全部问题已完成。文中的 Windows 路径（`C:\Users\...`、`D:\...`）是当时的真实证据位置，保持原样。

| 文档 | 内容 |
|---|---|
| [抓取链交接](../HANDOFF-SCRAPE-CHAIN.md) | 抓取链功能交接；仅开头“最新状态”一节有效，下方折叠内容为历史交接记录。 |
| [scrape-chain-acceptance-tickets.md](scrape-chain-acceptance-tickets.md) | 抓取链集成与验收工单、DAG 和验收边界。 |
| [review-2026-10-22.md](review-2026-10-22.md) | 2026-10-22 全面代码审查（问题来源，不是当前契约）。 |
| [independent-review-stage-2026-10-22.md](independent-review-stage-2026-10-22.md) | 阶段独立审查：跨语言兼容问题（IV-01、IV-02）及阶段证据。 |
| [independent-review-final-2026-10-22.md](independent-review-final-2026-10-22.md) | 最终独立复验（t14）：冻结时的失败结论、F-01–F-04 与未验边界。 |
| [independent-review-followup-2026-10-22.md](independent-review-followup-2026-10-22.md) | F-01–F-04 后续复验（t18）。 |
| [python-review-evidence-2026-10-22.md](python-review-evidence-2026-10-22.md) | Python 修复证据与剩余工作：v2 截断、managed Cookie、原子 reserve 与明确延期事项。 |
| [repo-hygiene-review-2026-10-22.md](repo-hygiene-review-2026-10-22.md) | 仓库卫生复核台账：文档与生成物处置依据。 |
| [Rust/Tauri 修复与验证](../desktop/src-tauri/REVIEW-2026-10-22.md) | 桌面后端本轮实现、验证与保留边界，不等同真实 bundle 发布验收。 |
| [verification-evidence/](verification-evidence/) | t14/t18 复验的原始日志、起止哈希、浏览器截图与复验脚本（`browser-check.mjs`、`cookie-rotation-check.py`、`t18-local-proxy.py` 等）。 |

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
| [project-audit-2026-09-12-round3.md](project-audit-2026-09-12-round3.md) | 2026-09-12 第三轮全仓审查（7 个确认的 P2 问题）。 |
| [skill-comparison-2026-09-12/README.md](skill-comparison-2026-09-12/README.md) | 三个审查 skill（variant-analysis / spec-to-code-compliance / audit-context-building）的实际比较，含各自报告与结构化记录。 |
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

各搜索、抓取服务的接入说明和官方文档摘要；免费额度和远端 API 以服务商最新声明为准：

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
