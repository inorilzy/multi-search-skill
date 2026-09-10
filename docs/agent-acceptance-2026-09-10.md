# CLI Agent 实际验收：TaskGroup（2026-09-10）

> 此处保留首次验收证据。后续已修复样本预览并补齐全源实测，见 [最终验收](provider-acceptance-2026-09-10.md)。

按当前 `skills/multi-search/SKILL.md` 和 `references/cli.md` 执行一次真实的搜索、选读、原文追踪和缓存查证。问题：**Python TaskGroup 的异常与取消语义，哪些原始资料支持？** 本次没有用预先挑好的搜索结果或模拟 provider。

## 环境与执行边界

- 时间：2026-09-10 12:18–12:23，Asia/Shanghai。
- 使用已安装的独立 `multi-search-mcp 0.3.0`，解释器位于 `C:\Users\zhiyu_liu\AppData\Roaming\uv\tools\multi-search-mcp\Scripts\python.exe`；实际 CLI 从同一环境的 `Lib\site-packages\multi_search_mcp\cli.py` 加载。
- 每一步在仓库外的独立进程执行。临时 bootstrap 仅把 `state_store.DEFAULT_STATE_PATH` 指向同一个临时 SQLite，然后原样调用已安装的 `cli.entrypoint()`，将 JSON、stderr 和计时分别落盘。没有修改用户 key、配置或真实状态库。
- 命令未提供 `--timeout`。没有显式配置文件，沿用安装包的内置默认时限；没有缩短时限、使用浏览器、登录或绕过访问限制。
- 下表耗时从进入 CLI 前开始，到 CLI 返回为止，**不含 Python 进程启动和模块导入**。冷指本次临时正文缓存为空；未验证上游服务是否另有缓存。

## 实际命令与结果

下列为 bootstrap 传给已安装 CLI 的实际参数；`search` 再执行一次用于检查跨响应缓存。

```powershell
multi-search search "Python TaskGroup exception cancellation" --source hackernews --source stackoverflow --count 2 --format json
multi-search fetch src_e798fe4e7645944ee629 --full-content --format json
multi-search search "Python TaskGroup exception cancellation" --source hackernews --source stackoverflow --count 2 --format json
multi-search fetch --url "https://docs.python.org/3/library/asyncio-task.html#asyncio.TaskGroup" --full-content --format json
multi-search fetch --url "https://docs.python.org/3/library/exceptions.html?highlight=exceptiongroup#ExceptionGroup" --full-content --format json
multi-search read src_ae2af9fa6f2d93992472 --keyword "The first time any of the tasks" --limit 700 --format json
```

| 调用 | CLI 耗时 | 实际结果 |
|---|---:|---|
| 冷 search | 13.930 s | Hacker News 成功但 0 命中；Stack Overflow 1 条。1 份正文预览，Jina 抓取成功；errors 为空 |
| 按原 source ID 选读全文 | 0.040 s | `cache_hit=true`，35,051 字符，`truncated=false` |
| 相同条件再次 search | 0.886 s | 同 URL 的新 source ID 为 `src_37e613e0b1c304a5d854`，`body_backend=content-store`；errors 为空 |
| 追踪 TaskGroup 官方文档 | 1.499 s | Jina，`cache_hit=false`，70,309 字符，`truncated=false` |
| 追踪 ExceptionGroup 官方文档 | 6.878 s | Jina，`cache_hit=false`，71,811 字符，`truncated=false` |
| 缓存 keyword 查证 | 0.011 s | 返回 700 字符，区间 `[15110,15810)`；与已取得正文的同区间逐字符一致，content hash 相同 |

全部六次 CLI 调用退出码为 0。搜索阶段只有 **1 条合格候选**，按 Skill 选读该条并明确不足 3 条；随后沿正文中的实际引用补读 2 份官方文档。这是 3 个文档、2 个来源主体，不是 3 个独立来源，也不是搜索最初返回了 3 条。

## 选读理由与实际支持

1. **[Stack Overflow：How to prevent python3.11 TaskGroup from canceling all the tasks](https://stackoverflow.com/questions/75250788/how-to-prevent-python3-11-taskgroup-from-canceling-all-the-tasks)**。来自 Stack Overflow 搜索，标题、Python 3.11 标签与异常后取消兄弟任务的问题直接匹配。读取所得正文后，看到多种社区建议，包括改写内部 `_abort`、Barrier 和在任务内部处理异常；这些建议不作为官方 API 保证。正文明确链接下面两份 Python 官方文档，提供了可追踪的原文入口。
2. **[Python 官方：TaskGroup](https://docs.python.org/3/library/asyncio-task.html#asyncio.TaskGroup)**。经上述页面实际链接取得，页面标识为 **3.14.7 Documentation**。Task groups 段落支持：组内任务以 `CancelledError` 以外的异常失败时，会取消剩余任务；等待任务结束后，相关异常合并为 `ExceptionGroup` 或 `BaseExceptionGroup` 再抛出。文档还明确 `KeyboardInterrupt`、`SystemExit` 的特殊处理，并说明吞掉 `CancelledError` 可能破坏使用取消机制的组件。本次关键词读取核对了第一条语义对应的原文区间。
3. **[Python 官方：ExceptionGroup / BaseExceptionGroup](https://docs.python.org/3/library/exceptions.html?highlight=exceptiongroup#ExceptionGroup)**。经同一 Stack Overflow 页面引用取得，同样标识 3.14.7。Exception groups 段落说明这些类型用于包装多个异常，并可由 `except*` 按子组处理；`ExceptionGroup` 只包装 `Exception` 的子类，`BaseExceptionGroup` 的范围更广。该文档支持异常组本身的类型和处理规则，并未把异常组限定为 TaskGroup 专用。

可核查链路为：**Stack Overflow 搜索 → 该问答正文中的官方文档链接 → 两份官方页面的相应段落**。这些段落支持上述技术结论；没有把 Stack Overflow 作者改写内部方法的方案当成推荐实现。问题未指定 Python 小版本，记录当前取得文档的版本；这次没有以 3.11 的归档文档证明所有后续版本细节一致。

## 通过范围与剩余缺口

- 已实际验证独立安装、仓库外 CLI 加载、两个搜索源的结果状态、按 source ID 读全文、原文链接追踪、跨响应 URL 缓存复用，以及 `read` 与完整缓存正文的一致性。
- 当前预览仍有质量问题：该 Stack Overflow 页面前 1200 字符主要是站点导航、推广、标题和统计，尚未进入问题主体。Agent 这次依靠标题和标签完成选择，不能据此声称预览已经适合可靠选读。
- 此次全量取得文本的长度和 `truncated=false` 证明本次输出未再次截断，不证明原网页无缺段。Hacker News 本题零命中是检索覆盖不足，不是 provider 失败。
- 这是一个未预选结果的问题的真实 Agent 调用轨迹。它不证明其他 11 个源、所有题型、所有版本或引用质量均已通过，也不提供伪造的准确率分数。

原始 JSON、stderr、每次调用参数/时间及 `verification.json` 保存在本机临时目录 `C:\Users\zhiyu_liu\AppData\Local\Temp\multi-search-agent-acceptance-95n_hzb9`。正文缓存有正常 TTL，原始输出文件用于本次证据复核；本报告不复制大段网页正文或任何凭据。
