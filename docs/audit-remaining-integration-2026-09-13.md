# 七张剩余审查工单：集成验收

七张工单分别在七个 Codex task、worktree 和分支中使用 `implement` 执行，模型均核实为 `gpt-5.6-luna`、推理强度 `max`。主任务完成独立复核、本地合并和统一验收；没有 push。

- 起始基线：`3b69069609e92d9cd393c5b9b42d1c598d3529df`。
- 七分支合并点：`be4dac1a53cac384149169ddaafd2a68d0e8038c`。
- 最终测试提交：`0f4900ad2fe6fae939e20a691b0652823877362a`；后续报告提交仅添加本文。
- 本地工单、任务 ID、模型、worktree 和合并记录：[execution.json](../.scratch/audit-remaining-fixes-2026-09-13/execution.json)。该 tracker 按仓库既有规则被 Git 忽略。

## 交付

| 工单 | 结果 | 实现提交 | 主任务独立定向测试 |
|---|---|---|---|
| 01 | GitHub primary/secondary 403、429 限流进入可恢复冷却 | `34db365` | 35 通过 |
| 02 | 非认证失败打断 invalid 连续计数，target 保持中立 | `f4f137e` | 28 通过 |
| 03 | Firecrawl 已知目标错误保留来源及并发写入的密钥冷却 | `59e784a` | 26 通过 |
| 04 | 保留不足一秒的抓取预算，继续共享绝对截止时间 | `8f43818` | 33 通过 |
| 05 | 导入和请求不覆盖宿主 urllib opener | `4ba1476` | 30 通过 |
| 06 | DNS 等待受请求预算约束，固定容量限制未完成解析 | `65656d8` | 41 通过 |
| 07 | 正式 runner 与安装 smoke 使用临时凭据环境及网络检查 | `9e1317a` | 11 通过 |

七票没有硬依赖；共享文件按责任协调，主任务检查 01/02、02/03、04/06、05/06 的组合行为。所有七个实现提交均为最终 main 的祖先，七个 worktree 均无未提交改动。

审查中的具体问题已处理，包括默认/config timeout 在首次 DNS 前建立 deadline、Reddit 直接入口使用有效截止时间、C transport 与子进程隔离。部分 Spec 审查代理超时，其覆盖由主任务独立代码检查和实际测试补齐，不把超时记作通过。不纳入会改变既有成功正文长度或接受超时后成功结果的审查建议。

## 主分支验证

1. **正式全量回归：639/639，通过，36.800 秒，进程 exit 0。** runner 的意外网络违规检查通过。执行外层临时 home 启动器，再运行正式 `scripts/run_tests.py`，日志：[final-suite.log](../.scratch/audit-remaining-fixes-2026-09-13/final-suite.log)。
2. **组合行为验收通过。** invalid 序列为 `[1,0,1,0,1]`；连续三次 GitHub 限流仍为 cooldown、0 strikes；Firecrawl target 保留冷却；1/2 秒抓取预算均成功；50ms 慢 DNS 测得约 54ms 返回、0 次 TCP；显式和 config 的 1 秒 fetch 预算均约 1.004 秒返回且不调用 backend；宿主 opener 保持有效。证据：[acceptance.json](../.scratch/audit-remaining-fixes-2026-09-13/acceptance.json)。
3. **MCP 兼容性：12 个工具 schema、28 个实际协议用例与起始基线完全一致。** 包括正常状态和 SQLite 失败响应。证据：[final-contracts.json](../.scratch/audit-remaining-fixes-2026-09-13/final-contracts.json)。
4. **干净非 editable 安装通过。** 从七分支合并点 `git archive` 导出源码，在专用新 venv 离线安装项目；实际导入位于该环境的 `site-packages`。仓库外 CLI help、fetch help、MCP stdio 握手、12 工具注册及 list_sources 调用通过。证据：[final-install-smoke.log](../.scratch/audit-remaining-fixes-2026-09-13/final-install-smoke.log)。之后唯一代码库修改是下述测试断言；已用 `git diff --exit-code` 确认产品代码、脚本、打包配置和锁文件与安装归档相同。
5. **工作区保护通过。** 起始 78 份未提交报告文件逐文件 SHA-256 不变；所有实现提交均已合并，`git diff --check` 通过。证据：[workspace-verification.json](../.scratch/audit-remaining-fixes-2026-09-13/workspace-verification.json)。

首次主分支全量运行发现一处旧测试断言：配置预算 7 秒经过 DNS 后，应传递剩余预算，而非仍精确等于 7。集成提交 `0f4900a` 仅修改该测试，使用受控时钟模拟 DNS 消耗 0.25 秒，断言同一 deadline 为 107、剩余预算为 6.75；随后重跑完整套件通过。生产代码没有因此放宽截止语义。

主要复验命令（仓库根目录，Python 3.13.13）：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts/run_tests.py
.\.scratch\audit-remaining-fixes-2026-09-13\integration-install\Scripts\python.exe -B -X utf8 .scratch/audit-remaining-fixes-2026-09-13/integration-source/scripts/smoke_install.py
.\.venv\Scripts\python.exe -B -X utf8 .scratch/audit-remaining-fixes-2026-09-13/verify_remaining.py
```

本次主任务实际执行在上述命令外加了 [isolated_run.py](../.scratch/audit-remaining-fixes-2026-09-13/isolated_run.py)，在 Python 启动前即设置独立物理 home、空配置和空密钥文件，并排除本机代理设置。

## 验证期间发生的凭据读取事件

主任务早期直接运行尚未完成的隔离测试时，该测试仍依赖正式 runner 预先建立隔离，读取了本机默认密钥配置；失败断言把部分密钥内容写入了工具输出。已向用户说明。随后停止该路径，采用启动前的独立物理 home，并修复测试自行建立隔离、子进程传播和断言只报告键名/布尔值的问题。

没有证据表明这些密钥被发送到外网，但已产生的工具输出无法由本次代码修复撤回；建议轮换已出现在输出中的密钥。本报告及新验收文件不复制密钥值。最终通过的隔离验收不能抹去这一早期事件。

## 覆盖边界

本次实际验证为 Windows、Python 3.13.13、MCP 1.30.0。未执行 Linux/Python 3.10/3.14 矩阵或真实 provider/远程部署验收。网络检查覆盖本仓库使用的 Python DNS/socket/urllib 代理、同步 curl_cffi 与相应 Python 子进程边界，不是操作系统防火墙。OS 内部正在执行的 DNS 无法被 Python 强制取消：超时后仍占用固定池的槽位，直到解析实际结束。
