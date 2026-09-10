# 付费搜索源实际验收（2026-09-10）

7 个源均成功返回候选；首轮有 5 个源取得与问题相关的文档或代码正文，Tavily 返回的视频页面仅验证到页面描述，Baidu 暴露了摘要冒充正文的问题。修复后，重放 Baidu 的真实候选并实时抓取原 URL，成功取得文章。不能把首轮 7 个 `body_success_count=1` 直接解释为 7 个源的正文质量全部通过。

## 执行边界

- 问题：`Python asyncio TaskGroup exception cancellation`。每源独立执行 `--count 1`，未预选结果。
- 首轮时间：2026-09-10 12:51–12:53，Asia/Shanghai。使用已独立安装的 `multi-search-mcp 0.3.0`，从仓库外运行；CLI 确认加载自安装环境的 `Lib\site-packages\multi_search_mcp\cli.py`。
- bootstrap 仅设置临时 SQLite 路径并收集 CLI 输出、stderr 和计时。未修改用户 keys、cookies、配置或真实状态库；未设置 `--timeout`，沿用默认时限。
- 各源一次真实 search，再对该次返回的原始 source ID 执行一次 `fetch --full-content`。另对 Baidu 做了一次必要的真实响应字段诊断；修复期间重放已记录的 Baidu 公开结果并实时抓取其 URL，另核查一次 Jina 原始公开响应，未再次调用 Baidu。
- 表中耗时不含 Python 启动和模块导入。冷指本次临时正文缓存为空，未验证上游缓存。

实际 CLI 参数形态：

```powershell
multi-search search "Python asyncio TaskGroup exception cancellation" --source <source> --count 1 --format json
multi-search fetch <本次返回的 source_id> --full-content --format json
```

## 首轮结果

| 搜索源 | search 耗时 | 命中目标 | 取得文本字符数 | 原 ID fetch 耗时 | 语义核查 |
|---|---:|---|---:|---:|---|
| Baidu | 4.157 s | [PHP 中文网 TaskGroup 文章](https://www.php.cn/faq/2306825.html) | 379 | 0.028 s | **未通过**：provider 摘要被误标为正文，详见下节 |
| Brave | 3.219 s | [Python asyncio 官方文档](https://docs.python.org/3/library/asyncio-task.html) | 70,011 | 0.305 s | 取得 Task groups、异常与取消规则等正文 |
| Parallel | 8.102 s | [CPython taskgroups.py](https://github.com/python/cpython/blob/main/Lib/asyncio/taskgroups.py) | 10,755 | 0.270 s | 取得 TaskGroup 类、异常处理和任务取消实现 |
| Tavily | 8.935 s | [EuroPython TaskGroup 演讲页面](https://www.youtube.com/watch?v=FvWXyAXyb4Q) | 14,279 | 0.032 s | 页面及演讲描述可读；未展开字幕，不能称已读视频全文 |
| Exa | 4.266 s | [Python asyncio 官方文档](https://docs.python.org/3/library/asyncio-task.html) | 70,011 | 0.256 s | 正文可读；索引标题为 3.14.5，抓取页面为 3.14.7 |
| Firecrawl | 3.495 s | [Python asyncio 官方文档](https://docs.python.org/3/library/asyncio-task.html) | 70,011 | 0.246 s | 取得 Task groups、异常与取消规则等正文 |
| SerpAPI | 6.781 s | [Python asyncio TaskGroup by example](https://sglmr.com/blog/python-asyncio-taskgroup-by-example/) | 9,024 | 0.043 s | 取得示例文章正文 |

首轮 14 次 CLI 调用退出码均为 0。每个主 provider 状态均为 `ok`、`raw_hits=1`，每次 search 最终返回 1 条候选，`errors=[]`；Baidu/Tavily 的附加 answer 行不计入候选数。Baidu 文本来自 provider 预取并被记录为 `content-store`，其余 6 次 search 的页面文本来自 Jina。

7 次原 ID fetch 均为 `cache_hit=true`、`truncated=false`。逐项检查完整返回字符串长度等于 `content_length`，SHA-256 等于 `content_hash`。这证明输出与缓存一致，不证明缓存内容本身是完整网页正文；Baidu 恰好是反例。

原 ID：

| 源 | source_id |
|---|---|
| Baidu | `src_f11c777e19e31bbb7d35` |
| Brave | `src_a7787bf62d8b1a6756df` |
| Parallel | `src_6492f14e227836431b9d` |
| Tavily | `src_ff920d8d312c7dbfe827` |
| Exa | `src_05dde4e16d7a6c986733` |
| Firecrawl | `src_e7c5f78a333f0e4bfc1a` |
| SerpAPI | `src_98466a7f2c8b99f068dd` |

## Baidu：复现、修复与访问限制

2026-09-10 13:00 的真实诊断确认：请求使用 `/v2/ai_search/web_summary`，未设置 `enable_full_content`；返回的 `content` 与 `snippet` 都是 379 字符且完全相同，没有 `markdown_text` 字段。[Baidu 官方接口文档](https://cloud.baidu.com/doc/qianfan/s/Kmiy99ziv) 将未启用全文时的 `content` 定义为网页摘要，将 `snippet` 定义为非原文摘要。诊断也观察到未公开说明的 `markdown_content` 字段名，但未保留其值，不能拿它证明已经取得全文。

根因是适配器无条件把 `content` 标为 `body` 并写入 `scraped_content`，导致统一正文阶段跳过 URL 抓取。修复将这一路返回标为 `excerpt`；现有明确 `markdown_text` 分支保留兼容，未添加未经验证的请求参数。对应回归先复现 `scraper` 调用 0 次，再验证修复后调用抓取并只缓存抓取正文。

2026-09-10 13:02 使用当前工作区代码，在全新的临时 SQLite 中重放该真实 Baidu 公开结果，并对同一个 PHP 中文网 URL 实时抓取。CLI 耗时 4.504 s，Jina 返回了 **254 字符的安全验证页面**，正文标题为 `Performing security verification`，没有文章正文。此次结果仍错误计为 `body_success_count=1`，因此同时发现了 Jina 适配器缺少这类挑战页识别。进一步核查原始公开响应，其 `page.title` 为 `Just a moment...`。

Jina 修复仅在该精确页面标题、验证标题与防机器人说明同时出现时返回明确 `blocked` 错误，继续沿用原有后端流程。回归先复现挑战页被接受，再验证修复后返回错误；普通文章引用相同验证文案、只有同名标题或验证小标题均不误判。

2026-09-10 13:07 再用新临时 SQLite 重放同一份真实 Baidu 公开候选，并实时抓取原 URL：Jina 明确报告 `Jina: blocked by website security verification`，原有后端流程随后由 **Firecrawl 取得 25,036 字符的文章**，含标题、TaskGroup 段落及代码。CLI 耗时 37.213 s、退出码 0，最终 `body_backend=firecrawl`，不再缓存挑战页。其原 ID `src_d3e624c9137d651f5bca` 的 full fetch 耗时 0.022 s，`cache_hit=true`、`truncated=false`，完整字符串长度和 SHA-256 均与缓存字段一致。

该重放只验证修复后的候选解释和真实 URL 抓取路径，不冒称重新安装后的完整 Baidu 在线 search 验收。修复前已缓存的旧 source ID 仍可能保留摘要直到正常 TTL；升级后重新搜索取得新 ID，不修改旧缓存内容。

定向验证：

```powershell
uv run python -m unittest -v test_jina_blocked_content test_baidu_content test_content_semantics test_mcp_core test_mcp_architecture test_search_fetch_pipeline
```

177 项通过，覆盖摘要语义、明确 Markdown 兼容、触发正文抓取、缓存完整正文、Jina 挑战识别及现有抓取流程。

## 通过范围与证据

本轮验证了 7 个付费源的真实候选获取、独立安装的 CLI 调用和原 ID 缓存读取。三个源命中同一份 Python 官方文档，不是三个独立证据主体；Parallel 的 GitHub 页面虽带通用加载错误横幅，仍含实际源码，不应因横幅字符串误判整页失败。CPython `main` 不是冻结版本，Exa 的标题差异属于本次观察到的索引与现场页面版本差异。PHP 中文网文章存在 `GroupExeption` 拼写等内容质量问题，取得正文不等于为其技术说法背书。

原始 JSON、stderr、逐次参数和计时、字段诊断及修复后重放结果位于本机临时目录 `C:\Users\zhiyu_liu\AppData\Local\Temp\multi-search-paid-acceptance-ee6jzmnf`。本报告不复制凭据或大段正文。访问限制和视频字幕缺口均按实际观察保留，未通过换查询、扩大量或绕过访问限制掩盖。
