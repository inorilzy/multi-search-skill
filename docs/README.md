# 文档索引

现行文档用于理解当前接口；历史档案仅保留当时的审计、计划和验收证据，不代表当前行为、安装方式或完成状态。历史资料保留原路径，避免破坏引用；本次未删除或移动文档。

## 现行有效

- [项目 README](../README.md)：安装、入口与配置边界。
- [CLI 指南](../skills/multi-search/references/cli.md)：实际 CLI 使用说明（不另建重复的 docs/cli.md）。
- [architecture-simple.md](architecture-simple.md)
- [route-capability-table.md](route-capability-table.md)
- [glossary.md](glossary.md)
- [candidate-first-release.md](candidate-first-release.md)
- [scrape-chain-acceptance-tickets.md](scrape-chain-acceptance-tickets.md)
- [抓取链交接](../HANDOFF-SCRAPE-CHAIN.md)：仅开头最新状态有效，旧记录已折叠。

## 本轮修复交付

- [最终独立复验（t14）](independent-review-final-2026-10-22.md)：记录冻结时的失败结论、F-01–F-04 与未验边界；后续修复不追改该历史 verdict，也不代表全部问题完成。
- [阶段独立审查](independent-review-stage-2026-10-22.md)：跨语言兼容问题及阶段证据。
- [Python 修复证据与剩余工作](python-review-evidence-2026-10-22.md)：包含 v2 截断、managed Cookie、原子 reserve 和明确延期事项。

- [Rust/Tauri 修复与验证](../desktop/src-tauri/REVIEW-2026-10-22.md)：本轮实现、验证与保留边界，不等同真实 bundle 发布验收。
- [Managed Twitter cookies 协议 v1](../desktop/src-tauri/COOKIE-PROTOCOL.md)：存储校验、IPC 契约、file/managed 模式迁移、DPAPI 威胁边界及跨语言修复验证命令；属实现证据，不是独立验收。
- [仓库卫生复核台账](repo-hygiene-review-2026-10-22.md)：文档与生成物处置依据。

## Provider 参考

以下为外部服务接入参考；免费额度和远端 API 以服务商最新声明为准。

- [brave/web-search-skill.md](brave/web-search-skill.md)
- [brave/web-search.md](brave/web-search.md)
- [exa/contents-api-guide-for-coding-agents.md](exa/contents-api-guide-for-coding-agents.md)
- [exa/contents-api-guide.md](exa/contents-api-guide.md)
- [exa/contents-best-practices.md](exa/contents-best-practices.md)
- [exa/search-api-guide-for-coding-agents.md](exa/search-api-guide-for-coding-agents.md)
- [exa/search-api-guide.md](exa/search-api-guide.md)
- [exa/search-best-practices.md](exa/search-best-practices.md)
- [firecrawl/search.md](firecrawl/search.md)
- [jina/reader.md](jina/reader.md)
- [parallel/search.md](parallel/search.md)
- [serpapi/google-light-api.md](serpapi/google-light-api.md)
- [tavily/extract.md](tavily/extract.md)
- [tavily/search.md](tavily/search.md)

## 历史档案：带日期记录

以下为已跟踪或本轮交付的带日期记录，不沿用旧报告中的固定数量。审查报告是问题来源，不是当前契约。

- [agent-acceptance-2026-09-10.md](agent-acceptance-2026-09-10.md)
- [architecture-review-2026-09-05.md](architecture-review-2026-09-05.md)
- [architecture-review-2026-09-07.md](architecture-review-2026-09-07.md)
- [audit-fixes-2026-09-10.md](audit-fixes-2026-09-10.md)
- [audit-integration-2026-09-12.md](audit-integration-2026-09-12.md)
- [audit-remaining-integration-2026-09-13.md](audit-remaining-integration-2026-09-13.md)
- [audit-round2-integration-2026-09-12.md](audit-round2-integration-2026-09-12.md)
- [deep-research-framework-notes-2026-09-10.md](deep-research-framework-notes-2026-09-10.md)
- [deep-research-opportunities-2026-09-10.md](deep-research-opportunities-2026-09-10.md)
- [legacy-scrape-cleanup-2026-09-12.md](legacy-scrape-cleanup-2026-09-12.md)
- [project-audit-2026-09-10.md](project-audit-2026-09-10.md)
- [project-audit-2026-09-12-round2.md](project-audit-2026-09-12-round2.md)
- [project-audit-2026-09-12.md](project-audit-2026-09-12.md)
- [provider-acceptance-2026-09-10.md](provider-acceptance-2026-09-10.md)
- [provider-acceptance-community-2026-09-10.md](provider-acceptance-community-2026-09-10.md)
- [provider-acceptance-paid-2026-09-10.md](provider-acceptance-paid-2026-09-10.md)
- [review-2026-10-22.md](review-2026-10-22.md)
- [search-focused-improvement-plan-2026-09-10.md](search-focused-improvement-plan-2026-09-10.md)
- [skill-ticket-integration-2026-09-12.md](skill-ticket-integration-2026-09-12.md)
- [target-warning-evidence-2026-09-12.md](target-warning-evidence-2026-09-12.md)

## 历史档案：早期设计与迁移研究

- [legacy-skill.md](legacy-skill.md)
- [mcp-dispatch.md](mcp-dispatch.md)
- [query-fusion-evaluation.md](query-fusion-evaluation.md)
- [query-fusion-experiments.md](query-fusion-experiments.md)
- [route-redesign-plan.md](route-redesign-plan.md)
- [search-snapshot-replay.md](search-snapshot-replay.md)
- [source-tracing-validation.md](source-tracing-validation.md)

## 仓库卫生处置

见 [复核台账](repo-hygiene-review-2026-10-22.md)。本地构建产物、需求草稿与历史证据均保留；任何删除或移出索引操作须另行确认。

## 本地可选历史资料（非交付依赖）

以下路径在本轮开始前未跟踪，可能只存在于维护者工作区；不自动纳入版本控制，不作为 CI 的必需链接目标。

- `project-audit-2026-09-12-round3.md`
- `skill-comparison-2026-09-12/audit-context/DOSSIER.md`
- `skill-comparison-2026-09-12/audit-context/functions/01-_run_tool.md`
- `skill-comparison-2026-09-12/audit-context/functions/02-run_search_web.md`
- `skill-comparison-2026-09-12/audit-context/functions/03-run_fetch_source.md`
- `skill-comparison-2026-09-12/audit-context/functions/04-run_read_source.md`
- `skill-comparison-2026-09-12/audit-context/functions/05-run_keyed_source.md`
- `skill-comparison-2026-09-12/audit-context/functions/06-run_ranked_fetch_stage.md`
- `skill-comparison-2026-09-12/audit-context/functions/07-search_brave.md`
- `skill-comparison-2026-09-12/audit-context/functions/08-urlopen_retry.md`
- `skill-comparison-2026-09-12/audit-context/functions/09-ContentStore-reuse_for_url.md`
- `skill-comparison-2026-09-12/audit-context/functions/10-SQLiteKeyManager-record_result.md`
- `skill-comparison-2026-09-12/README.md`
- `skill-comparison-2026-09-12/spec-compliance/REPORT.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-01.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-02.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-03.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-04.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-05.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-06.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-07.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-08.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-09.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-10.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-11.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-12.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-13.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-14.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-15.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-16.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-17.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-18.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-19.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-20.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-21.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-22.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-23.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-24.md`
- `skill-comparison-2026-09-12/spec-compliance/requirements/REQ-25.md`
- `skill-comparison-2026-09-12/variant-analysis/REPORT.md`
