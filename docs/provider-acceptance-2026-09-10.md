# 13 源验收与最终安装复测（2026-09-10）

13 个搜索源已逐一实际调用：11 个返回候选，Twitter 两次 `ReadTimeout`，LinuxDo 返回 HTTP 403。搜索是否成功、取得文本是否可读、内容是否支持结论分别判断；没有把这次验收写成全源始终可用或搜索质量评分。

原始逐源记录见 [7 个付费源](provider-acceptance-paid-2026-09-10.md) 和 [6 个社区源](provider-acceptance-community-2026-09-10.md)。首轮使用当时独立安装的 0.3.0，在仓库外运行真实 CLI，每源 count=1，保留默认超时；不修改凭据或用户状态库。后续发现的问题修复后另做回归和安装复测。

## 逐源结果

| 源 | 搜索 | 正文验收与限制 |
|---|---|---|
| Baidu | 成功，1 条 | 发现摘要误标正文；修复后重放真实候选、实时抓取原 URL，Firecrawl 取得 25,036 字符文章。不是重新在线调用 Baidu |
| Brave | 成功，1 条 | Python 官方文档正文可读 |
| Parallel | 成功，1 条 | CPython TaskGroup 源码可读；main 分支不是固定版本 |
| Tavily | 成功，1 条 | 命中视频，取得页面描述；未取得字幕，不能据此称已读演讲全文 |
| Exa | 成功，1 条 | Python 官方文档正文可读；搜索标题与当前页面的小版本不同 |
| Firecrawl | 成功，1 条 | Python 官方文档正文可读 |
| SerpAPI | 成功，1 条 | TaskGroup 示例文章正文可读 |
| GitHub Repos | 成功，1 条 | FastAPI README，22,562 字符；仍含 HTML logo/badges |
| Hacker News | 成功，1 条 | uv 文章，8,855 字符 |
| Stack Overflow | 成功，1 条 | 问答页面，78,446 字符；最终安装复测预览已进入问题主体 |
| V2EX | 成功，1 条 | 8,000 字符，核对包含主题及页面标明的 19 条回帖；最终安装复测预览已进入主题 |
| Twitter | 失败 | 两次默认预算请求均 ReadTimeout，CLI exit 1；未获得可读结果 |
| LinuxDo | 失败 | HTTP 403，CLI exit 1；未绕过访问限制 |

## 实测发现并修复的问题

1. **预览先显示导航。** 仅调整搜索响应的原文选区：优先完全匹配页面一级标题；没有匹配标题时，可用完整搜索摘要定位原文段首，要求至少 32 个非空白字符且只允许空白差异。无匹配保留正文开头，短正文整个返回。`preview_start/end` 使用原文字符索引，省略前文也标为 `truncated`。不改全文、hash、source ID、排序或抓取数量。
2. **Windows 管道无法输出 Unicode。** CLI 重定向 stdout/stderr 改用 UTF-8，保留原错误处理方式；TTY、自定义流和非 Windows 行为保持。此前 fetch 遇到 `U+2328` 会退出 1，成功搜索也可能因为 `U+2122`、`U+203A` 输出失败。
3. **Baidu 摘要冒充正文。** 当前 `web_summary` 请求未启用全文，`content/snippet` 应是摘要；现在进入统一 URL 抓取流程，能力声明同步纠正。明确的旧 `markdown_text` 分支保留兼容。旧 ID 的既有摘要缓存等待正常 TTL，升级后重新搜索取得新 ID；不改写旧缓存。
4. **Jina 验证页被当作正文。** 精确识别本次观察到的页面标题和验证正文组合，返回明确 blocked 错误。原有后端流程继续执行，最终由 Firecrawl 取得文章；未新增抓取后端或绕过验证。普通文章引用同类文案不会仅因此失败。

这些修复均先复现再补回归。独立复核还修正了 Setext 多行标题与混合空格/Tab 代码缩进的误匹配。规则只定位已取得文本，不保证每个网站的导航都能去除；例如没有匹配标题或原文摘要的 README 仍可能显示 badges。

## 最终独立安装复测

重新执行 `uv tool install --force --reinstall .` 后，从仓库外核对安装包的 64 个 Python/MJS/PowerShell 文件，SHA-256 全部与当前源码一致。独立 CLI、stdio MCP 握手、12 个工具注册及 `list_sources` 调用通过。

本轮 7 次 CLI 特意使用 `-I -X utf8=0`，让 Windows 进程初始管道编码为 GBK；未通过打开 Python UTF-8 模式避开 bug。实际入口均将重定向输出切到 UTF-8，7 次全部 exit 0，输出能严格按 UTF-8 解码。

| 操作 | CLI 耗时 | 验证 |
|---|---:|---|
| SO search `Python asyncio`，count=1 | 5.644 s | 原文区间 `[492,1692)`，78,446 字符正文中的连续预览 |
| SO fetch 全文 / read 预览区间 | 0.018 / 0.009 s | 全文缓存命中；read 与预览逐字符相同，hash 与全文缓存相同 |
| V2EX search `Python`，count=1 | 3.807 s | 原文区间 `[1614,2814)`，直接从主题首段开始，跳过导航广告 |
| V2EX fetch 全文 / read 预览区间 | 0.018 / 0.010 s | 同上；保留 8,000 字符完整已取得文本 |
| GitHub 原 ID fetch 全文 | 0.912 s | 22,562 字符与首轮原文完全一致，`U+2328` 保真，缓存命中 |

计时不含 Python 启动和模块导入。SO/V2EX 使用新临时缓存，GitHub 使用本轮社区验收缓存；原始输出及逐字符/hash校对记录在本机临时目录 `C:\Users\ZHIYU_~1\AppData\Local\Temp\multi-search-final-acceptance-_0_vdix3`。最初 TaskGroup 样本也已重放：35,051 字符原文的 `[492,1692)` 能读到此前被 1,200 字符预算挡住的问题首句。

## 回归与交付

| 本地 Windows 环境 | 全量回归 | 用时 |
|---|---:|---:|
| Python 3.10.20 | 472/472 | 29.990 s |
| Python 3.13.13 | 472/472 | 22.106 s |
| Python 3.14.5 | 472/472 | 21.726 s |

命令：`python scripts/run_tests.py`；独立安装检查：已安装解释器执行 `python scripts/smoke_install.py`。新增核心回归位于 `test_search_preview.py`、`test_cli_encoding.py`、`test_baidu_content.py`、`test_jina_blocked_content.py`。

个人 Skill 和 CLI reference 已同步，保留 Engineering Judgment。GitHub Actions 配置 Windows/Linux × Python 3.10/3.14；对应提交的远端结果以 [Actions](https://github.com/inorilzy/multi-search-skill/actions) 为准。版本保持 0.3.0，本轮提交并推送 main，不创建 release/tag；安装远端当前代码使用 `@main`。
