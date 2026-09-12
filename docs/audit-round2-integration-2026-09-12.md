# 第二轮工单集成验收 · 2026-09-12

8 张工单均已实施、测试并合并至 `main`。审查基线为 `9b4049142e5fbdbb7eb498a4e7c82a7b880d70a4`，最终代码提交为 `f4d5e0fff64d799a870df5608b32d8a93f1720fc`；本记录之后只新增文档，不再修改代码。

按用户要求新建 8 个独立 Codex Session，均使用 `gpt-5.6-luna` / `max`，各自在新 worktree 中创建 `codex/r2-*` 分支并按 Implement 流程开发。各票没有硬依赖，主 Session 负责复核、处理共享文件冲突及集成验收。8 个实现提交均已验证是 `main` 的祖先，8 个工作树均干净；分支与工作树保留。

## 实现与分支验证

| 票 | 修复行为 | 分支 | 实现提交 | 分支全套测试 |
|---|---|---|---|---:|
| 01 | 正确读取 Stack Overflow 压缩响应 | `codex/r2-01-stackoverflow-compression` | `5062e9b` | 543 PASS |
| 02 | Tavily 目标网页错误不损害密钥健康 | `codex/r2-02-tavily-target-health` | `c561341` | 544 PASS |
| 03 | 换 key 后保留已取得的分页候选 | `codex/r2-03-preserve-partial-results` | `e7dbd5a` | 543 PASS |
| 04 | 按 Tavily 状态码准确处理配额耗尽 | `codex/r2-04-tavily-quota` | `45a2a3b` | 543 PASS |
| 05 | 网络 doctor 运行期间 MCP 保持响应 | `codex/r2-05-async-doctor` | `7d4820a` | 542 PASS |
| 06 | 显式空扩展查询覆盖全局配置 | `codex/r2-06-explicit-empty-expand` | `9303684` | 543 PASS |
| 07 | 任务完成后释放空闲 worker 的对象引用 | `codex/r2-07-worker-reference-cleanup` | `3e9cb4a` | 541 PASS |
| 08 | 按正确 host 隔离抓取冷却与偏好 | `codex/r2-08-site-host-identity` | `09186d3` | 543 PASS |

## 主 Session 验收

- 各票均经过主 Session 的代码复核与相关测试；03 的候选保留、排名与 deadline 合并另经独立 agent 复核，无阻塞问题。
- Tavily 02/04 在 Extract 返回分支发生一处文本冲突。保留目标错误的 `error_origin="target"`，同时接入真实 API `HTTPError` 的 provider 分类；相关 23 项回归通过。
- 四项组合验收全部通过（0.315s）：02+04 目标错误与配额状态互不污染；03+04 配额轮换兼容共享搜索调度；03+06 显式空扩展只调用主查询且保留 10 条分页候选、原始 rank 与诊断计数；05+07 慢 doctor 期间 MCP 可响应且调用结束后对象可回收。取消和容量约束另由正式 MCP 并发回归覆盖。
- 最终完整回归：`.venv/Scripts/python.exe -B -X utf8 scripts/run_tests.py` → **576 tests in 30.004s, OK，exit code 0**。
- 从最终代码提交的干净 `git archive` 在新临时环境做离线、非 editable 安装，随后从仓库外执行已有 `scripts/smoke_install.py`：CLI `--help`、`fetch --help`、MCP 初始化、列出 12 个工具及 `list_sources` 均通过；模块确认来自 `site-packages`。环境为 Windows、Python 3.13.13、MCP 1.30.0、multi-search-mcp 0.4.0。
- 最终代码差异 `git diff --check` 通过。原有测试的必要预期调整：遗漏 `expand` 用 `None` 表示继承；显式 `[]` 表示禁用扩展，避免旧测试继续把二者混用。

## 证据边界与资料

测试使用模拟 provider 响应、测试 key 和临时 SQLite。Tavily 配额测试曾发现正文抓取未完全隔离，已补 fake scraper/resolver 及 HTTP/DNS 拦截并复跑通过；组合验收同样拦截真实 HTTP/DNS。以上结果不代表真实 provider 可用性、实时搜索质量、生产负载或部署验收；未执行其他 Python/操作系统的 CI 矩阵。

08 保留既有站点分组规则，改用正确 hostname 并约束知乎域名边界；错误历史站点键无法可靠还原，按 README 的既有定向 reset 方式处理，不自动猜测迁移。

部分默认审查子代理不受宿主模型支持，改用 Luna Max；03/04 的 Spec 子代理未及时返回，由执行 Session 逐条自审并经主 Session 复核与回归确认，没有将未返回的审查标为通过。

- [原始审查报告](project-audit-2026-09-12-round2.md)保留基线缺陷证据。
- [本地工单与依赖说明](../.scratch/project-audit-round2-2026-09-12/README.md)、[执行映射](../.scratch/project-audit-round2-2026-09-12/execution.json)、[组合验收脚本](../.scratch/project-audit-round2-2026-09-12/verify_combinations.py)位于被 Git 忽略的本地 tracker。

本次完成本地提交与合并，未 push 或部署。
