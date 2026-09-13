# Target-warning key-health evidence — 2026-09-12

## 结论

Jina 与 Firecrawl 的候选均为 `insufficient evidence`，不提交生产修复，也不新增候选专用正式回归契约。当前分支的生产代码与基线保持一致。

已确认的只是：

- Jina 官方 issue #1226 展示了 provider HTTP envelope 为 `code: 200`、`status: 20000`，并带有 `data.warning = "Target URL returned error 403: Forbidden"`；但同一响应的 `data.text` 非空。因此它不能证明“HTTP 200 + 空正文 + target 403 warning”的完整触发组合。
- Firecrawl 的公开响应模型存在 `warning` 字段；在限定的官方文档和源码范围内，没有找到本候选的精确 warning 文本及“成功 envelope + 空 `markdown`/`content`”样本。

## 范围与固定基线

- 工单基线：`eb2d5cdeb222b52060c4509c45a22aff4ce911fa`
- 调查分支：`codex/skill-03-target-warning`
- 报告时间：2026-09-12；本地时间：`America/Los_Angeles`
- 代码范围：`multi_search_mcp/src/scrape/scrapers/jina.py`、`firecrawl.py`，共享入口 `scrape.py`、key 状态 `key_state.py`，以及本地 Jina schema/glossary。
- 运行时/离线探针安全边界：只使用合成 key、合成 JSON 和临时 SQLite；未读取真实 key/cookie/config，未进行外部 HTTP/DNS/进程调用。调查阶段对公开网页和官方源码的读取仅限下方列出的证据来源。

## 证据来源与搜索边界

### Jina

1. 本地 adapter：[`jina.py`](../multi_search_mcp/src/scrape/scrapers/jina.py)，函数从第 114 行开始；空正文路径在 150–153 行读取 `warning` 并返回普通 `error`；HTTP 429 路径独立产生 `rate_limited`。
2. 本地生成的官方 schema：[`docs/jina/reader.md`](jina/reader.md) 的 `FormattedPageDto` 从第 779 行开始，在 788、792、798 行分别列出 `content`、`text`、`warning`；本地 `docs/jina/openapi.json` 作为同一 schema 的机器可读副本。
3. 官方样本：[`Jina Reader issue #1226`](https://github.com/jina-ai/reader/issues/1226)。脱敏字段结构如下，正文明确非空：

   ```json
   {
     "code": 200,
     "status": 20000,
     "data": {
       "warning": "Target URL returned error 403: Forbidden",
       "title": "",
       "url": "<target URL>",
       "text": "<non-empty blocked-page explanation>"
     }
   }
   ```

   该 issue 页面没有提供 provider 版本或固定 commit revision；因此它是可定位的官方样本，不是固定 revision 的协议 fixture。

### Firecrawl

1. 官方接口文档：[`POST /v2/scrape`](https://docs.firecrawl.dev/api-reference/endpoint/scrape) 说明响应的 `success`/`data` 结构，并展示 `data.warning` 作为响应字段；没有定义本候选的 target-warning 语义。
2. 官方源码检查范围：[`scrape.ts`](https://raw.githubusercontent.com/firecrawl/firecrawl/main/apps/api/src/controllers/v2/scrape.ts)、[`entities.ts`](https://raw.githubusercontent.com/firecrawl/firecrawl/main/apps/api/src/lib/entities.ts)、[`scrapeURL/index.ts`](https://raw.githubusercontent.com/firecrawl/firecrawl/main/apps/api/src/scraper/scrapeURL/index.ts)、[`engines/index.ts`](https://raw.githubusercontent.com/firecrawl/firecrawl/main/apps/api/src/scraper/scrapeURL/engines/index.ts)。`Document` 有可选 `warning`，engine result 有 `statusCode`/`error`；未找到精确字符串 `Target page returned 403 Forbidden` 对应的官方成功响应样本。
3. 上述 Firecrawl `main` 链接未固定 commit；这是明确的证据缺口，不据此宣称当前线上版本协议。

### 本地搜索停止边界

已检查现有变体报告、JSON 结果、搜索日志、两个 keyed adapter、共享 key pool、Jina schema、Firecrawl API 文档/限定源码路径，并做了精确 warning 文本搜索。停止于“没有完整官方样本/固定 revision”的结论；没有继续扩大 provider 或版本搜索。

## 离线合成探针

原探针只读位置：`D:\0-code-project\multi-search-skill\.scratch\skill-comparison-20260912\variants\probe.py`；结果：`D:\0-code-project\multi-search-skill\docs\skill-comparison-2026-09-12\variant-analysis\probe-results.json`。该脚本的 `ROOT` 指向主 checkout，不能从该位置重跑，以免导入或重写主工作区；本次只读取既有源码和结果。

两适配器使用的完整脱敏 JSON payload 相同：

```json
{
  "success": true,
  "data": {
    "warning": "Target page returned 403 Forbidden",
    "markdown": "",
    "content": ""
  }
}
```

这只是 adapter-level 合成响应；探针记录的 `http_status` 为 `null`，没有真实 HTTP 200。适配器输出分别为 `Jina: Target page returned 403 Forbidden` 与 `Firecrawl: Target page returned 403 Forbidden`，随后三次以合成时间推进的 keyed 状态均为 `transient_invalid/1`、`transient_invalid/2`、`invalid/3`。这证明现有条件性分类链路，不证明 provider 会发送该完整组合。

对照结果：

- Exa target control 和 Tavily target control 带 `error_origin=target`、`error_type=target`，key 保持 `active`。
- Jina HTTP 429 control 带 `rate_limited=true`，key 进入 `cooldown`。
- 探针拒绝 opener、DNS、socket connect、subprocess，并禁用 `load_keys`/`load_config`；没有真实 provider 消耗或 MCP 网络传输验收。

## 候选裁决

| 候选 | 结论 | 依据 | 代码动作 |
| --- | --- | --- | --- |
| Jina：target 403 warning + 空正文导致 key health 误判 | `insufficient evidence` | 官方 #1226 只有同类 warning 的非空正文样本；空正文组合仅来自无真实 HTTP 状态的合成 payload | 不改 `jina.py`；不增加 target 分类规则 |
| Firecrawl：target 403 warning + 空正文导致 key health 误判 | `insufficient evidence` | 官方仅确认 warning 字段/通用响应模型，未确认精确文字、版本、状态码和空正文组合 | 不改 `firecrawl.py`；不增加 target 分类规则 |

因此没有“confirmed”或“refuted”的新 provider 缺陷；两项都停留在待补协议证据。未知 warning 仍按现有行为暴露，不把包含 `401`/`403` 的任意文字自动当作 target，也不把所有 auth failure 当作 target。

## 正式验证边界

本次没有保留只服务于未确认候选的新增测试。保留并复跑既有成功、认证、限流、配额及目标错误对照测试；测试使用临时状态或已有合成 fixture，不代表真实 provider/cutover 验收。

待补证据若要重新打开候选，至少需要同一 provider 版本与固定 revision/时间下的完整脱敏记录：请求条件、真实 HTTP status、完整成功 envelope、`warning` 原文、`markdown`/`content` 是否为空，以及一次真实 adapter → shared key pool → key-state 的使用计数和状态对照；不得用真实密钥或无授权目标替代脱敏 fixture。

## 最终 checkout 验证

- 导入路径检查：`D:\0-code-project\multi-search-skill\.venv\Scripts\python.exe -B -c "import multi_search_mcp; print(multi_search_mcp.__file__)"`，解析到当前 worktree 的 `multi_search_mcp/__init__.py`。
- 既有目标错误/抓取契约对照：`-m unittest -v test_exa_target_errors test_tavily_target_errors test_jina_blocked_content test_scrape_output_contract`，`Ran 33 tests`、`OK`。
- 全套：`D:\0-code-project\multi-search-skill\.venv\Scripts\python.exe -B scripts/run_tests.py`，`Ran 576 tests`、`OK`。
- `git diff --check`：通过。
