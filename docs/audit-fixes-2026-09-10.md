# 2026-09-10 审查修复记录

对应 [原始审查](project-audit-2026-09-10.md) F01–F15。源码版本保留 0.3.0；本文件记录 F01–F15 修复。后续全源实测、预览和编码等修复见 [13 源最终验收](provider-acceptance-2026-09-10.md)。本轮不创建 release/tag。

## 修复与回归映射

| 问题 | 修复 | 回归依据 |
|---|---|---|
| F01 MCP 安装兼容性 | `mcp>=1.28.1,<2`；锁定 MCP 1.30.0，cryptography 更新至 50.0.1 | 非 editable 安装；仓库外 console scripts、stdio 握手、工具注册及调用 |
| F02 凭据重定向 | 带凭据跨 origin 跳转拒绝，HTTPS 降级拒绝；保留同 origin 鉴权 | `test_http_deadlines`、`test_url_security` |
| F03 CLI 失败可见性 | 三种输出均保留 provider 错误；全源失败 exit 1，空成功/部分覆盖 exit 0 | `test_cli_failures`；实际 Core 经 CLI 路径 |
| F04 饱和池丢结果 | 截止时先收已完成 Future，保留成功、正常空结果及异常 | `test_concurrency_lifecycle` |
| F05 扩展查询预算 | 排队查询共用搜索阶段绝对 deadline，过期不请求 | `test_query_identity` 六查询超并发边界 |
| F06 HTTP 重试超时 | SSL 重试、TCP/CONNECT/TLS阶段、跳转及响应头/正文读取扣除同一预算；异常重定向流立即释放 | `test_http_deadlines` 慢 SSL、代理/SNI、Content-Length/chunked/错误响应和读取协议 |
| F07 冷却排序 | 冷却后端低于未尝试后端；人工 pinned 仍按 priority 优先 | `test_site_memory` |
| F08 URL 缓存复用 | 同 canonical URL 与来源/后端/凭据 scope 关联新 ID，保留原 expiry 并服从当前 retention | `test_fetch_url_cache`、`test_content_store`、`test_source_content_flow` |
| F09 并发缓存孤儿 | 写入、删除、过期清理与迁移先进入写事务；旧 schema 兼容升级 | `test_content_store` 双写、写删、双迁移确定性调度 |
| F10 显式配置路径 | 环境变量指定的缺失路径抛 ConfigError；无显式路径才用默认值 | `test_configuration_diagnostics` |
| F11 doctor 状态 | 真正解析/校验配置与查询权重；可选两站网络探针区分执行和成功；默认含 key 时也显示完整诊断 | `test_configuration_diagnostics` 坏配置、网络成功/失败/部分成功、两种文本输出 |
| F12 Twitter 部分成功 | 搜索候选先发布；详情/回复失败保留已得推文和正文，缺口逐条可见；移除已取得回复的200字符裁剪 | `test_twitter_partial`，包括真实 Runner 截止边界 |
| F13 URL 参数语义 | 同名参数保留原次序，只对键稳定排序并去除已有追踪参数 | `test_candidate_search` 不同source ID断言 |
| F14 Parallel 日期 | adapter 补公共 published_at，保留旧 publish_date 兼容 | `test_search_snapshots` adapter→Core→snapshot→replay |
| F15 CLI/Skill 交付 | 单一 CLI 指南、完整 Skill references；本机个人 Skill 备份后同步并保留 Engineering Judgment | 文档/文件读回核对，真实 Agent 验收另见下节 |

跨版本回归另发现并修复了评测时间精度问题：冻结时间是浮点秒，snapshot 是微秒 ISO 文本；同一个时刻经过序列化可能误判为“采集早于冻结”。仅在比较时统一精度，artifact 字段、原值和 hash 保持不变；新测试覆盖同精度相等允许、早1微秒仍拒绝。

现有测试的 FakeRunner 签名同步内部可选 deadline；CLI/MCP 对比测试保留排序/内容一致断言，同时明确第二次调用来自 ContentStore。MCP 展示测试移至模块级导入，避免在 mock 生效期间首次导入工具，污染后续测试。

## 兼容与边界

- CLI 调用形态和成功 JSON 保持；失败退出码、doctor 的真实状态及部分查询失败状态被纠正。搜索排序与最终15条流程保持。
- SQLite 只增加默认空的两列及索引，旧缓存按原 ID 继续可读。跨 ID 缓存不续期，不跨来源/后端/凭据上下文。原 provider 预取正文按 ID 复用，避免混入另一抓取上下文。
- 同一次 `source_id` 的缓存读取维持原有行为，不额外加载配置/keys。`read` 仍只读缓存。
- HTTP 回归使用合成socket和模拟凭据。操作系统 DNS/连接建立不能靠 Python deadline 强行中断；测试不构成所有网络环境的墙钟 SLA。
- `doctor --network` 只检查两个公开 API 的连接，不检查全部13源的key、quota或搜索质量。
- 已安装个人 Skill 的旧版本备份于 `~/.agents/skill-backups/multi-search-20260910T041604Z/`；新版附带 `references/cli.md`，保留原 Engineering Judgment。

## 验证记录

- 真实 Agent CLI 全链路见 [TaskGroup 验收](agent-acceptance-2026-09-10.md)：两个搜索源、搜索→选读→追踪两份官方文档→缓存片段校对，6次调用均 exit 0；无预选结果或伪造质量分数。
- 同一真实查询在临时正文缓存为空时为13.930秒，再次查询为0.886秒，正文通过新的source ID复用。计时不含Python启动/导入；“冷”只描述本地缓存，不推断上游是否缓存。
- 依赖审计：`uv export --locked --no-hashes --no-emit-project` 后执行 `uvx pip-audit --no-deps --disable-pip`，本平台适用的46个锁依赖无已知漏洞命中；原审查的两个命中均已更新。
- GitHub Actions 已增加 Windows/Linux × Python 3.10/3.14 的非 editable 安装检查与回归，远端执行结果以对应提交的 Actions 为准。后续已逐一调用全部13源，并修复SO/V2EX样本预览；详见 [最终验收](provider-acceptance-2026-09-10.md)，其中保留Twitter超时、LinuxDo403及视频字幕等缺口。

- 本机独立工具已重装当前0.3.0。仓库外核对64个Python/MJS/PowerShell包文件，SHA-256全部与当前源码一致；CLI help、fetch help、MCP stdio握手、12个工具注册及list_sources调用均通过。
- 已安装版本的真实 `doctor --network` 探针对Hacker News/GitHub均成功；无显式配置时报告 `config_loaded=false, config_status=defaults`，没有冒充加载配置。

以下为 F01–F15 完成时的记录；追加修复后的三个版本各472项回归及最终安装复测见 [13 源最终验收](provider-acceptance-2026-09-10.md)。

| Windows 本地环境 | 全量回归 | 用时 | 安装与MCP |
|---|---:|---:|---|
| Python 3.10.20，干净环境按pyproject解析依赖 | 454/454通过 | 30.785秒 | 非editable安装，仓库外CLI/MCP检查通过 |
| Python 3.13.13，项目锁定环境 | 454/454通过 | 23.880秒 | 另在独立uv工具环境完成当前源码安装/hash/CLI/MCP检查 |
| Python 3.14.5，干净环境按pyproject解析依赖 | 454/454通过 | 20.779秒 | 非editable安装，仓库外CLI/MCP检查通过 |

执行入口：`python scripts/run_tests.py`；安装验证入口：已安装环境的解释器运行 `python scripts/smoke_install.py`。Python 3.10原生urllib把308返回为HTTPError，较新版本自动处理跳转；测试按实际能力覆盖两条正文读取/关闭路径，保留生产行为，没有skip。最终HTTP模块在三个版本各17项通过。

`git diff --check` 按仓库现有换行设置通过，新增文档的本地链接已核对。原有未提交版本/文档改动及 `.scratch/`、`build/` 工作保留；相关修复纳入本轮提交和推送，不创建tag。
