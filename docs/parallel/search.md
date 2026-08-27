# Parallel Search API 调研与适配说明

调研日期：2026-08-27
调研范围：Parallel Search API（不包含 Task、Responses、FindAll）
资料范围：Parallel 官网、官方文档、官方 OpenAPI。

## 结论

建议新增一个名为 `parallel` 的普通 Web 搜索适配器，直接调用 GA 接口：

```text
POST https://api.parallel.ai/v1/search
x-api-key: $PARALLEL_API_KEY
```

不要照产品页中的 `/v1beta/search` 示例实现。Parallel 的官方迁移指南已经明确：`/v1/search` 是 GA 版本，也是所有新集成的推荐接口；V1 的字段位置和 mode 含义与 Beta 不相同。[V1 API reference](https://docs.parallel.ai/api-reference/search/search) · [Beta → V1 migration guide](https://docs.parallel.ai/search/search-migration-guide)

本项目应优先直接使用现有 `urllib` HTTP 层，不需要为了一个请求引入 `parallel-web` SDK。Parallel 返回的是排序后的 URL 和 LLM 优化压缩摘录，不是完整网页正文；适配器应保留这个边界，不要把 excerpt 宣称为 `full_content`。[Search quickstart](https://docs.parallel.ai/search/search-quickstart)

## 1. 认证与 endpoint

- Endpoint：`POST https://api.parallel.ai/v1/search`。
- 认证头：`x-api-key: <key>`，不是 Bearer token。
- 请求类型：`Content-Type: application/json`。
- 官方 SDK 默认读取环境变量 `PARALLEL_API_KEY`；本项目也应沿用这个名称。[Search API reference](https://docs.parallel.ai/api-reference/search/search)
- API key 在 [Parallel Platform](https://platform.parallel.ai/) 创建。

最小请求示例（不包含真实 key）：

```bash
curl https://api.parallel.ai/v1/search \
  -H "Content-Type: application/json" \
  -H "x-api-key: $PARALLEL_API_KEY" \
  -d '{
    "objective": "Parallel Search API current documentation",
    "search_queries": ["Parallel Search API documentation"],
    "mode": "fast",
    "advanced_settings": {
      "max_results": 10
    }
  }'
```

## 2. V1 请求结构

`search_queries` 是唯一必填字段；其他字段可选。官方建议同时提供 `objective`，以便搜索器理解关键词背后的完整目标。[Best practices](https://docs.parallel.ai/search/best-practices) · [OpenAPI](https://docs.parallel.ai/public-openapi.json)

| 字段 | 类型 | 约束与含义 |
|---|---|---|
| `search_queries` | `string[]` | 必填，至少 1 个非空查询；最多 5 个，每个最多 200 字符。建议每个 3–6 个词、通常给 2–3 个查询。超出 5 个时，多余项会被丢弃并返回 warning。 |
| `objective` | `string | null` | 可选，自包含的自然语言搜索目标，最多 5000 字符。 |
| `mode` | enum | `turbo`、`fast`、`basic`、`advanced`；省略时为 `advanced`。 |
| `max_chars_total` | `int | null` | 所有结果 excerpt 的总字符上限；默认由请求内容和 `client_model` 动态决定。 |
| `session_id` | `string | null` | 最多 1000 字符，用于把同一任务内的 Search/Extract 调用归组；省略时服务端生成。 |
| `client_model` | `string | null` | 消费搜索结果的模型名称，用于服务端优化；不是必填。 |
| `advanced_settings` | object | source、live fetch、excerpt、地区和结果数控制。无明确产品需求时应省略不必要的高级限制。 |

V1 OpenAPI 对请求对象设置了 `additionalProperties: false`。不要发送 Beta 字段形状，例如顶层 `max_results`、顶层 `source_policy`，或旧的顶层 `excerpts`；错误字段可能得到 `422`。[V1 migration guide](https://docs.parallel.ai/search/search-migration-guide) · [OpenAPI](https://docs.parallel.ai/public-openapi.json)

### `advanced_settings`

| 字段 | 说明 |
|---|---|
| `max_results` | 大于 0，默认 10。公开 Search mode 当前最多返回 20 个；传入更大值会被降到 20，并附带 input validation warning。API 也可能少于请求数。 |
| `excerpt_settings.max_chars_per_result` | 每个 URL 的 excerpt 字符上限；实际内容可能更短。 |
| `source_policy` | 域名 allow/deny 和发布日期下限。过度限制会降低召回与质量。 |
| `fetch_policy` | 控制使用索引缓存还是实时抓取；实时抓取会明显增加延迟。 |
| `location` | 支持列表内的 ISO 3166-1 alpha-2 国家代码，不区分大小写并归一化为小写；无效值被忽略并返回 warning。中国为 `cn`，英国必须用 `gb` 而不是 `uk`。 |

完整的国家列表和字段说明见 [Advanced Search Settings](https://docs.parallel.ai/search/advanced-search-settings)。

### source policy 边界

- `include_domains` 与 `exclude_domains` 合计硬上限 200；超出会产生 validation error。
- `after_date` 使用 RFC 3339 日期格式 `YYYY-MM-DD`。
- apex domain 会包含其子域；可用 `.gov`、`.org`、`.co.uk` 这类裸后缀，但不支持 `*.org`。
- 域名中不要携带 scheme、path 或 port。
- 同时传 include/exclude 时，include 已经构成硬白名单，exclude 是冗余的；官方建议单次只用一种。

这些规则来自 [Source Policy](https://docs.parallel.ai/resources/source-policy)。本项目现有 `search(query)` 接口没有域名/日期参数，首版适配器不应自行解析查询并偷偷生成 source policy。

### fetch policy 边界

- 默认关闭 live fetch，优先返回索引缓存内容。
- `max_age_seconds` 的最小值为 600 秒；内容更旧时触发 live fetch。
- `timeout_seconds` 控制 live fetch 等待时间。
- `disable_cache_fallback` 默认 `false`；live fetch 失败时允许回退到更旧缓存。设为 `true` 时则返回错误。

首版适配器不需要启用 live fetch。默认缓存行为更符合多源并发搜索的延迟目标。[Advanced Search Settings](https://docs.parallel.ai/search/advanced-search-settings) · [OpenAPI](https://docs.parallel.ai/public-openapi.json)

## 3. Search modes，不是 processors

`/v1/search` 没有 `processor` 字段；它使用 `mode`。`lite`、`base`、`core`、`pro`、`ultra` 等是 Task API processor，不能传给 Search。若未来需要合成答案或深度研究，应单独接 Task/Responses，不能塞进这个搜索适配器。[Search API reference](https://docs.parallel.ai/api-reference/search/search) · [Pricing](https://docs.parallel.ai/getting-started/pricing)

| mode | 官方定位 | 典型延迟 | 价格（默认 10 条） |
|---|---|---:|---:|
| `turbo` | 最低延迟与成本，高并发简单查询 | ~250 ms | $1 / 1000 requests |
| `fast` | 大多数 agent 的官方推荐，质量与延迟平衡 | ~700 ms | $1 / 1000 requests |
| `basic` | 每条结果提供更长 excerpt，适合 2–3 个高质量 queries | ~1 s | $5 / 1000 requests |
| `advanced` | 默认；更高级的检索和压缩，质量最高，适合 multi-hop | ~3 s | $5 / 1000 requests |

模式、延迟与价格来自 [Search Modes](https://docs.parallel.ai/search/modes) 和 [Pricing](https://docs.parallel.ai/getting-started/pricing)。`turbo` 当前只支持英文和日文查询；更广的多语言覆盖应使用 `basic` 或 `advanced`。因此首版可以用 `fast` 控制多源 fan-out 的成本和延迟，但中文检索质量必须单独评测；若不达标，应显式改为 `basic`/`advanced`，不要按字符集做隐藏自动切换。

注意名称冲突：本项目的 `route="fast"` 是“哪些 provider 参与、是否二次抓取”的路由；Parallel 的 `mode="fast"` 是单个 provider 的检索 preset，两者不是同一个概念。

## 4. 响应结构

成功响应顶层字段：[API reference](https://docs.parallel.ai/api-reference/search/search) · [OpenAPI](https://docs.parallel.ai/public-openapi.json)

| 字段 | 必填 | 说明 |
|---|---:|---|
| `search_id` | 是 | 本次 Search ID。 |
| `results` | 是 | 按相关性递减排序的结果数组。 |
| `session_id` | 是 | 回显请求值，或由服务端生成。 |
| `warnings` | 否 | 非致命调整/校验警告。 |
| `usage` | 否 | SKU usage 数组，每项为 `{name, count}`。 |

单条 `results[]`：

```json
{
  "url": "https://example.com/page",
  "title": "Example title",
  "publish_date": "2026-08-27",
  "excerpts": [
    "Relevant excerpt in Markdown..."
  ]
}
```

- `url` 和 `excerpts` 必有；`title`、`publish_date` 可以为 `null`。
- `excerpts` 是 Markdown 格式的相关压缩摘录，不保证是完整正文。
- `warnings[]` 的当前结构是 `{type, message, detail?}`；已知 type 包括 `spec_validation_warning`、`input_validation_warning`、`warning`。新 warning type 被视为向后兼容变化，所以不能写死枚举后拒绝整个响应。[OpenAPI](https://docs.parallel.ai/public-openapi.json)

## 5. 错误与重试边界

官方通用错误表：[Warnings and Errors](https://docs.parallel.ai/resources/warnings-and-errors)

| HTTP | 含义 | 官方建议重试 |
|---:|---|---:|
| 401 | key 缺失或无效 | 否 |
| 402 | 账户 credit 不足 | 否 |
| 403 | 无权限/请求能力不可用 | 否 |
| 404 | 资源不存在 | 否 |
| 408 | 同步请求超时 | 是 |
| 422 | 请求校验失败 | 否 |
| 429 | rate limit 或 quota 超限 | 是，指数退避 |
| 500 / 502 / 503 | 服务端或上游临时错误 | 是，退避 |

Search OpenAPI 的 `422` 示例是：

```json
{
  "type": "error",
  "error": {
    "ref_id": "search_...",
    "message": "Request validation error"
  }
}
```

通用错误页还展示了 `error.message` + `error.detail` 的形状。适配器不应假设所有错误 body 完全一致；HTTP status 是主要分类依据，body 只作为经过 secret scrub 的诊断内容。[Search API reference](https://docs.parallel.ai/api-reference/search/search) · [Warnings and Errors](https://docs.parallel.ai/resources/warnings-and-errors)

对本项目的处理建议：

- `401/403` 保留状态码文本，让现有 key manager 进入 invalid strike 流程。
- `402` 保留 `Payment Required`/credit 文本，让现有 classifier 标记 `quota_exhausted`。
- `429` 保留状态码，让 key 进入 cooldown，并允许 key pool 尝试下一把 key。
- `408/5xx` 是请求或服务端瞬时故障，不应把 key 标记为坏 key；首版直接返回显式 error row，不增加静默 provider fallback。
- 成功响应里的 `warnings` 不是失败，不应转换成伪搜索结果。若以后增加 provider diagnostics，可把 warning、`search_id` 和 `usage` 放进诊断层。

## 6. 限流与计费

- Search 默认限流为每分钟 600 个 `POST /v1/search`；需要更高额度要联系 Parallel。[Rate limits](https://docs.parallel.ai/getting-started/rate-limits)
- 默认每次返回 10 个 page results + excerpts。
- `turbo`/`fast`：$1 / 1000 requests，即默认请求基价 $0.001。
- `basic`/`advanced`：$5 / 1000 requests，即默认请求基价 $0.005。
- 额外 page result + excerpt：$1 / 1000，即默认 10 条之外每增加 1 条再计 $0.001。[Pricing](https://docs.parallel.ai/getting-started/pricing)
- public mode 的结果硬上限是 20；不要把本项目的 `count` 无限制透传。[Advanced Search Settings](https://docs.parallel.ai/search/advanced-search-settings)

本项目的 `expand` 会让同一 provider 对多个查询分别调用。每次 `POST` 都独立计入限流和账单，所以 adapter 内部不要再偷偷生成额外 queries 或二次请求。

## 7. 本项目的最小适配方案

### Provider contract

| 项目字段 | 建议值 |
|---|---|
| internal/public name | `parallel` |
| key name | `parallel` |
| env | `PARALLEL_API_KEY` |
| auth mode | `API_KEY` |
| provider kind | `SEARCHER` |
| max count | `20` |
| count key | `parallel` |
| timeout default | `15s` |
| output | URLs + snippets/excerpts；无 synthesized answer；无完整正文 |
| scrape policy | `CANDIDATE` |
| routes | 建议加入 `default`、`all`；首版不加入项目的 `fast` route |

不把 Parallel 标成 `CONTENT_SEARCHER` 的原因：官方只承诺 compressed excerpts，而不是完整页面。可以保留完整 excerpts，但应明确它们是摘录，并让默认 scrape stage 仍有机会为高排名 URL 获取正文。

### 请求映射

当前 provider 接口一次只接收一个 `query`。首版应做直接、可预测的映射：

```python
body = {
    "objective": query,
    "search_queries": [query],
    "mode": "fast",
    "advanced_settings": {
        "max_results": max(1, min(count, 20)),
    },
}
```

官方建议 2–3 个 queries，但当前架构并没有把一组 query 一次性交给 provider。不要在 adapter 内自行编造变体；这会改变搜索意图、制造隐藏请求并增加费用。以后若要利用 Parallel 的多 query 单调用能力，应从上层正式引入 batch query contract。

### 结果映射

建议把每条 Parallel result 映射为：

```python
excerpt_text = "\n\n".join(item.get("excerpts") or []).strip()

row = {
    "source": "parallel",
    "title": item.get("title") or "",
    "url": item.get("url") or "",
    "description": excerpt_text,
    "excerpts": item.get("excerpts") or [],
    "publish_date": item.get("publish_date"),
}
```

这里故意不写 `scraped_content`：在本项目中该字段意味着已经取得可作为页面正文使用的内容，会跳过二次抓取，并公开为 `body/full_content`。`description` 会由 service 层公开为 `content`，完整 excerpts 也单独保留，但都不冒充完整正文。

空 URL 行应丢弃。没有结果时返回空 list，让现有 runner 生成统一的 zero-result status；HTTP 或解析失败时返回：

```python
[{"source": "parallel", "error": "<scrubbed error>"}]
```

### key 配置与状态管理

支持现有两种入口：

```text
PARALLEL_API_KEY=<secret>
```

或 `~/.search-keys.json`：

```json
{
  "parallel": ["<key-1>", "<key-2>"]
}
```

接入 `KEY_ENV_PAIRS`、capability 的 `key_name="parallel"` 和 provider registry 后，不需要为 Parallel 新建状态系统。现有 `SQLiteKeyManager` 会以 provider=`parallel` 给每把 key 建独立状态，并继续复用 LRU 选择、invalid strike、rate-limit cooldown、quota exhaustion 与 reset/status 查询。

## 8. 验证清单

没有真实 key 时也能完成：

1. searcher request/body 单元测试：确认 endpoint、`x-api-key`、V1 字段嵌套、count clamp。
2. response mapping：`null` title/date、多个 excerpts、空结果、warning、usage。
3. HTTP error：401、402、429、422、500，且错误中不泄漏 key。
4. registry、capability、route、counts、env key、README/Skill 列表一致。
5. `list_sources()` 与 key status 能看到 `parallel`。

有真实 key 后再做一次小额在线验收：

1. 英文与中文查询各 1 次，`max_results=3`。
2. 记录实际延迟、结果数、excerpt 质量和 usage。
3. 验证 401/429/402 对 key 状态的映射。
4. 比较 `fast` 与 `basic` 的中文召回后，再决定是否开放 provider mode 配置。

## 官方资料索引

- [Parallel Search product](https://parallel.ai/products/search)
- [Search API Quickstart](https://docs.parallel.ai/search/search-quickstart)
- [Search API Reference](https://docs.parallel.ai/api-reference/search/search)
- [Official OpenAPI](https://docs.parallel.ai/public-openapi.json)
- [Search Best Practices](https://docs.parallel.ai/search/best-practices)
- [Search Modes](https://docs.parallel.ai/search/modes)
- [Advanced Search Settings](https://docs.parallel.ai/search/advanced-search-settings)
- [Source Policy](https://docs.parallel.ai/resources/source-policy)
- [Beta → V1 Migration](https://docs.parallel.ai/search/search-migration-guide)
- [Pricing](https://docs.parallel.ai/getting-started/pricing)
- [Rate Limits](https://docs.parallel.ai/getting-started/rate-limits)
- [Warnings and Errors](https://docs.parallel.ai/resources/warnings-and-errors)
