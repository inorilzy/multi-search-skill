# Skill 后续三票集成验收 · 2026-09-12

三个分支已全部合并至 `main`，最终集成验证提交为 `10ca0340467ac64f0b4e23dc1162af8daf025fbe`；之后仅新增本验收记录。基线：`eb2d5cdeb222b52060c4509c45a22aff4ce911fa`。按用户授权创建三个独立 Codex 任务、三个 worktree、三个 `codex/` 分支；已核实三个任务的模型均为 `gpt-5.6-luna`，推理强度为 `max`。每个任务读取并使用 `implement`，主 Session 负责独立验收、合并及最终验证。

## 工单与交付

| 票 | 分支 | 实现提交 | 交付与分支验证 |
|---|---|---|---|
| 01 | `codex/skill-01-stateful-mcp` | `3f20e206ee71c13af6a91a5a227caa6be3209233` | 7 个状态工具的 SQLite 路径复用现有 4 槽池；保留无状态快路、错误格式和取消边界。全套 582 项通过；测试清理修正后 15 项并发回归再通过。 |
| 02 | `codex/skill-02-key-health-docs` | `b8a2a1fb408b69d013b803027ef7ec2a828b2978` | 区分配置 `exhausted` 和运行态 `quota_exhausted`，补齐 `transient_invalid` 及计数边界。只改 README 和 glossary；全套 576 项通过。 |
| 03 | `codex/skill-03-target-warning` | `8e6c17510566f74d0a5bcacbf1fd590bf0ae1616` | Jina、Firecrawl 均为证据不足，仅交付调查报告；生产代码及正式测试保持基线行为；全套 576 项通过。 |

三个任务、worktree 和分支的完整映射保存在本地 [execution.json](../.scratch/skill-review-followups-2026-09-12/execution.json)。它们互无硬依赖；原目录中未提交的第三轮审查及 skill 比较报告未纳入实现提交。

## 主 Session 独立验收

- 01：独立审查确认复用同一个有界执行池，未新增后台容量；真实 SQLite 写锁与 MCP `CancelledNotification` 覆盖等待期间的响应性。发现的测试清理竞态已在分支中修正，主 Session 复跑 15 项并发回归通过（1.795s）。
- 01：合并前从固定基线取得 12 个工具的输入/输出 schema，使用真实 MCP 内存会话比较 28 个正常、缺失、无效参数及 SQLite 连接失败场景；分支结果与基线完全一致，包括结构化错误与 MCP `isError` 的区别。缓存样本使用固定时间，避免把到期时间差异误当接口回归。
- 02 Standards：独立 agent 审查实际两文件差异，范围、Markdown 表格、术语及现有文档风格通过。
- 02 Spec：另一独立 agent 对照工单及 `key_state.py`、`keys.py`、`mark_exhausted.py`、`jina.py`，六项验收通过。未把 invalid 计数的已知实现偏差固化为产品规则。
- 03：主 Session 复核官方页面与原探针。Jina 官方 issue 的正文非空；原合成响应没有真实 HTTP 状态。最终结论只能是证据不足，不能称为已修复或已反证。报告记录搜索范围、脱敏字段及重新调查所需证据。另经主 Session 的独立 Standards / Spec 双轴审查通过。

部分实现任务的审查子代理遇到宿主模型不支持或错误使用空三点 diff；未将这些尝试计作通过。主 Session 以实际文件差异补足独立审查，再允许合并。

## 合并后验证

- `.venv/Scripts/python.exe -B -X utf8 .scratch/skill-review-followups-2026-09-12/run_guarded_suite.py`：运行现有 `scripts/run_tests.py`，增加临时 home、清空 provider 环境凭据及 HTTP/DNS 拦截；**582 tests in 29.530s，OK，exit 0**。
- `.venv/Scripts/python.exe -B -X utf8 .scratch/skill-review-followups-2026-09-12/verify_contracts.py D:/0-code-project/multi-search-skill .scratch/skill-review-followups-2026-09-12/final-contracts.json .scratch/skill-review-followups-2026-09-12/baseline-contracts.json`：**12 个 schema、28 个真实 MCP 场景与基线完全一致**。
- 从 `10ca034` 的干净 `git archive` 在新临时环境离线非 editable 安装，然后运行 `scripts/smoke_install.py`：CLI `--help`、`fetch --help`、stdio MCP 初始化、12 个工具发现、`list_sources` 均通过；导入路径确认在新环境的 `site-packages`。
- Windows / Python 3.13.13 / MCP 1.30.0 / multi-search-mcp 0.4.0。未执行其他 OS/Python 的 CI 矩阵，也未执行独立类型检查；没有将编译检查当作类型检查。
- `git diff --check eb2d5cd...HEAD` 通过；三个实现提交均为 `main` 的祖先，三个 worktree 均干净。
- 开始时已有的 78 个报告文件 SHA-256 全部保持一致；未打包进实现提交。

本地可复核材料：[全套日志](../.scratch/skill-review-followups-2026-09-12/final-suite.log)、[安装日志](../.scratch/skill-review-followups-2026-09-12/install-smoke.log)、[最终接口样本](../.scratch/skill-review-followups-2026-09-12/final-contracts.json)。

## 证据边界

本次是本地实施、离线回归和本地合并验收；不代表真实 provider 可用性、搜索质量、线上负载或部署验收。临时 SQLite、合成凭据及网络拦截用于运行时验证；第三张票的调查允许读取公开官方网页和源码。

`invalid_strikes` 在部分非 invalid 回报后保留计数的旧问题不在本批修复范围；文档已明确。目标 warning 候选仍需完整真实协议证据，详见 [调查报告](target-warning-evidence-2026-09-12.md)。未 push 或部署；分支及 worktree 保留。
