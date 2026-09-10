# 社区搜索源实际验收（2026-09-10）

> 以下记录首轮安装快照；后续 SO/V2EX 预览及 Windows 编码的最终安装验证见 [全源验收](provider-acceptance-2026-09-10.md)。

本轮覆盖 `github_repos`、`hackernews`、`stackoverflow`、`v2ex`、`twitter`、`linuxdo_api` 六个源。四个源检索、正文抓取和按 source ID 读取完整缓存正文成功；Twitter 两次超时，LinuxDo 返回 HTTP 403。不能把六个源都记为通过。

## 执行方式

- 时间：2026-09-10 12:53–12:55，Asia/Shanghai。
- 使用独立安装的 `multi-search-mcp 0.3.0`，依赖 `mcp 1.30.0`。解释器为 `C:\Users\zhiyu_liu\AppData\Roaming\uv\tools\multi-search-mcp\Scripts\python.exe`，CLI 实际从同一工具环境的 `Lib\site-packages\multi_search_mcp\cli.py` 加载。
- 每次在仓库外启动新进程，bootstrap 仅把 `state_store.DEFAULT_STATE_PATH` 指向各源独立的临时 SQLite，再调用 `cli.entrypoint()`。搜索与后续 fetch 共享该源临时库；重试使用新的临时库。读取原有凭据，没有改动用户凭据、配置或真实状态库。
- 每个源用一个普通查询、`--count 1`，取得结果后执行 `fetch <source_id> --full-content --format json`。所有请求都未传 `--timeout`，沿用正常默认预算；没有登录、浏览器操作或访问限制绕过。
- 耗时从 CLI 入口前计到返回，排除 Python 启动和模块导入。新临时库表示本地正文缓存为空；未验证上游服务是否使用缓存。
- 当前表格来自安装快照，尚未包含此轮新增的预览起点和 Windows 管道 UTF-8 修复。后续重新安装验证由全源验收主报告记录。

## 可解析 UTF-8 输出的验收结果

首次运行暴露 Windows GBK 管道编码错误。为区分提供方故障与输出编码故障，四个有结果的源各重试一次，进程显式使用 `-I -X utf8 -B`，参数和默认网络预算不变。Twitter 也只做了一次必要的瞬时错误重试；LinuxDo 403 没有重试。

| 源参数 | 实际 query | Search 耗时 | 退出码 / 命中 | 正文 backend / 已取得字符 | 按 ID 全文耗时 |
|---|---|---:|---|---|---:|
| `github_repos` | `asyncio language:Python` | 2.749 s | 0 / 1 | Jina / 22,562 | 0.023 s |
| `hackernews` | `Python` | 2.096 s | 0 / 1 | Jina / 8,855 | 0.021 s |
| `stackoverflow` | `Python asyncio` | 3.047 s | 0 / 1 | Jina / 78,446 | 0.022 s |
| `v2ex` | `Python` | 3.384 s | 0 / 1 | Jina / 8,000 | 0.024 s |
| `twitter` | `OpenAI` | 6.577 s | 1 / 0 | `ReadTimeout` | 无可读结果 |
| `linuxdo_api` | `Python` | 0.699 s | 1 / 0 | `HTTP Error 403: Forbidden` | 无可读结果 |

前四行 `provider_status.status=ok`，`errors=[]`，search 和 fetch 的 stderr 为空。Search 返回 1,200 字符预览；fetch 退出码均为 0，`cache_hit=true`、`backend=content-store`、`persisted=true`、`truncated=false`，实际返回长度等于表中已取得字符数。这里的“全文”指完整已获取正文，不证明原网页未漏段。

Twitter 和 LinuxDo 的 `provider_status.status=error`，并输出 `error: all selected search providers failed`。零结果的直接原因已显式报告，没有归类为成功但无匹配。

实际 CLI 参数示例：

```powershell
multi-search search "asyncio language:Python" --source github_repos --count 1 --format json
multi-search search "Python" --source hackernews --count 1 --format json
multi-search search "Python asyncio" --source stackoverflow --count 1 --format json
multi-search search "Python" --source v2ex --count 1 --format json
multi-search search "OpenAI" --source twitter --count 1 --format json
multi-search search "Python" --source linuxdo_api --count 1 --format json
multi-search fetch src_3394ecd62f430b5fc355 --full-content --format json
```

## 结果和正文质量

| 来源 | 实际选中页面 | source ID | 安装快照的预览情况 |
|---|---|---|---|
| GitHub Repos | [fastapi/fastapi](https://github.com/fastapi/fastapi) | `src_7e3daecee8065c1be6aa` | 前段主要是 README 中的 HTML logo、badges 和文档链接；全文读到 License 段 |
| Hacker News | [Uv is the best thing to happen to the Python ecosystem in a decade](https://emily.space/posts/251023-uv) | `src_36103abeb1a9ee443586` | 预览已包含标题与文章主体，全文包含安装、依赖管理及文档引用 |
| Stack Overflow | [multiprocessing vs multithreading vs asyncio](https://stackoverflow.com/questions/27435284/multiprocessing-vs-multithreading-vs-asyncio) | `src_3394ecd62f430b5fc355` | 预览大部分是推广、题目与统计，只在末尾开始问题主体；全文包含问答及页脚 |
| V2EX | [关于学习 Python](https://www.v2ex.com/t/114961) | `src_5d46b111e142e1647fec` | 预览主要是导航、广告和 Python 侧栏，尚未进入主题；完整已获取文本确实包含主题与 19 条回帖，但缺失标题及 Markdown heading，标题锚定也无法改善该样本预览 |

V2EX 的 8,000 字符需区分正文与预览：搜索 excerpt 的前 25 字在完整 body 的字符偏移 1,614 精确匹配；正文声明 19 条回帖，实际编号和作者标记也为 19，最后一条作者 Kabie 位于偏移 7,070，页脚从 7,311 开始，结尾为完整站点标语。没有证据表明本地把正文截在半句，但已获取文本中确实缺少题目标题。该样本的主题与回帖可读，预览质量未通过。

这证明各源的这一个样本可完成检索和按 ID 读取链路，不代表所有查询的相关性、覆盖率或页面完整性均已通过。Stack Overflow 的预览质量问题需用更新安装包继续验证；V2EX 缺少标题以及 GitHub README 的 HTML 头部是当前标题锚定预览策略的边界。

## 首次运行发现的 Windows 编码问题

初始进程使用 `-I -B`。虽然父进程设置了 UTF-8 相关环境变量，`-I` 会忽略它们，实际标准输出仍为 GBK。检索本身成功后，JSON 的 `ensure_ascii=False` 输出遇到 GBK 无法编码的字符，导致 CLI 失败：

| 源 / 操作 | 首次 CLI 耗时 | 实际观察 |
|---|---:|---|
| GitHub Repos search → fetch | 2.665 s → 0.019 s | search 成功；fetch 因 `U+2328` 编码失败，退出码 1 |
| Stack Overflow search | 9.461 s | 因 `U+2122` 编码失败，退出码 1 |
| V2EX search | 9.746 s | 因 `U+203A` 编码失败，退出码 1 |
| Hacker News search | 5.528 s | CLI 退出码 0，但按 UTF-8 解码 GBK 字节会损坏非 ASCII 内容；采用重试结果作正文证据 |
| Twitter search | 6.205 s | `ReadTimeout`，退出码 1；一次重试仍失败 |

首次原始字节已保留；没有把 GBK 解码损坏的数据当成可靠正文证据。本轮新增 `test_cli_encoding.py` 先稳定复现三个输出格式的编码失败与 stderr 乱码，再在 `cli.entrypoint()` 将 Windows 重定向的标准文本 stdout/stderr 设置为 UTF-8，保留各自错误处理方式；TTY、自定义流和非 Windows 行为保持不变。相关 CLI、错误处理与诊断共 29 项测试在项目解释器及 Python 3.10 中通过。该单元验证与最终安装包复测分别记录。

原始 JSON、stderr、参数、安装模块位置和计时文件位于 `C:\Users\ZHIYU_~1\AppData\Local\Temp\multi-search-community-acceptance-gk34snus`。各源目录保留首次运行；`retry-utf8` 子目录保留有效 UTF-8 重试证据。顶层 `summary.json` 与 `utf8-summary.json` 汇总两轮结果。
