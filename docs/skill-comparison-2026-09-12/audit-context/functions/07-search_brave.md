## `search_brave` in multi_search_mcp/src/search/searchers/brave.py (L11-L64)

**Purpose:** 把 Brave API 响应投影为搜索 excerpt/metadata 行。

---

**Inputs & Assumptions:**

- query：untrusted，urlencode 编码（L23-L25）；api_key trusted header（L30）；count 来自 resolve.build_counts L110。
- 前提：count 受本地 provider cap 限制；enforcement：search/resolve.py L98-L110。
- 前提：运行时 adapter 异常不会逃出 SearchRunner.run；enforcement：search/search_runner.py L391-L396。

---

**Outputs & Effects:**

GET 到固定 Brave API，正文读取/解压/JSON 后逐项输出；异常行含 scrub 后诊断（L23-L64）。

---

**Block-by-Block:**

```python
# L23-L42
with urlopen_retry(req, timeout=timeout) as resp:
    raw = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    data = json.loads(raw)
```

- **What:** 读取、可选解压、JSON 解析位于 try 内。
- **Why here:** HTTP timeout 属于 helper；CPU 解压和 JSON 解析发生其后。
- **Assumes:** 远端 payload schema 是外部契约，不作为已验证事实。
- **Establishes:** 这一段 Exception 被 scrub 转错误；L41-L42。
- **Depended on by:** L45-L64 访问 web.results 并投影。

```python
# L45-L64
for item in data.get("web", {}).get("results", []):
    ...
    content_kind = "excerpt" if desc else "metadata"
```

- **What:** 描述和 extra_snippets 拼为摘要，非正文。
- **Why here:** content_kind 使 Core 不把 snippet 存为 body。
- **Assumes:** 远端 item/extra_snippets 类型；该循环在本函数 try 外，外层 runner future 捕获见 search_runner.py L393-L396。
- **Establishes:** snippet 语义由 models.search_content L65-L78 消费。
- **Depended on by:** 候选融合与预取选择 service.py L473。

---

**Cross-Function Dependencies:**

- `urlopen_retry` (internal)：连接、SSL 重试和 response read 共用 helper deadline；http.py L175-L212。
- `Brave API` (external-black-box)：发送 query/count/API key；响应 schema 和内容真实性需外部契约。
- `scrub_secrets` (internal)：显式 key 与常见 token 模式替换，secrets.py L32-L40。
- Callers: registry.py L54-L59 经 call_optional_timeout L185-L198
- Shared state: 无直接 DB 写入；key 外层记账 search_runner.py L267-L270
- Invariant coupling: Brave 结果只声明 excerpt/metadata (searchers/brave.py L52-L63；models.py L65-L78)

---

**Open Questions:**

- unclear; need to inspect Brave API 当前 schema/压缩体规模保证；本轮离线不验证上游。
