## `run_fetch_source` in multi_search_mcp/src/service.py (L175-L318)

**Purpose:** 把临时来源身份或直接 URL 转为本次取得的正文和可选缓存。

---

**Inputs & Assumptions:**

- source_id/url：untrusted；必须恰有一个（L190-L191）。source_record/prefetched_body 为内部搜索调用注入（L633-L644）。
- keys/config：本轮只读加载器源码，不读取实际值。
- 前提：存储失败不会返回 persisted=True；enforcement：state/state_store.py L153-L158；service.py L296-L315。
- 前提：正文内容只作为不可信数据标记；enforcement：service.py L267、L316。

---

**Outputs & Effects:**

可能新增 search_sources，复用或新增 content_sources/content_objects；返回正文、长度、hash、cache_hit、persisted（L210-L318）。

---

**Block-by-Block:**

```python
# L190-L228
if bool(request.source_id) == bool(request.url):
    raise ValueError("provide exactly one of source_id or url")
...
validate_public_http_url(url, resolver=url_resolver)
```

- **What:** 解析身份并做 URL 校验，直接 URL 获得新 response/source id。
- **Why here:** 即使命中缓存，也先解析来源并校验 URL。
- **Assumes:** 来源 TTL 由 SourceRegistry.get L66-L69 检查；source_record 仅核对 source_id L196-L197。
- **Establishes:** 未知/过期来源显式失败；L201-L204。
- **Depended on by:** 后续缓存与抓取均使用解析出的 URL。

```python
# L230-L268
cached = content_store.get(source_id) if content_store and source_id else None
...
cached = content_store.reuse_for_url(source_id, canonical_url=canonicalize_url(url), cache_scope=cache_scope)
```

- **What:** source_id 首查；未命中且允许持久化时，按 URL 与 scope 复用。
- **Why here:** 先执行当前 retention；scope 由 provider/backend/keys 的 JSON hash 建立。
- **Assumes:** reuse 的调用者必须先检查 retention；这里 L244 建立；同 source_id 命中不重算 scope（L231-L255）。
- **Establishes:** 跨 source_id 复用需同 URL、同 scope 且未到期；content_store.py L113。
- **Depended on by:** 缓存命中不启动 scraper。

```python
# L270-L318
body = str(result.get("markdown") or "")
if not body:
    raise ValueError("fetch_source returned empty body")
...
"body": body[:max_chars]
```

- **What:** 预取或 scraper 成功后先 put 全正文，再截输出；error/空正文失败。
- **Why here:** preview cap 和 storage byte cap 是两个独立边界。
- **Assumes:** put 检查 UTF-8 字节数；content_store.py L55-L64。
- **Establishes:** persisted 只由 put 返回非 None 建立；L296-L315。
- **Depended on by:** read_source 能读缓存中的完整采集文本。

---

**Cross-Function Dependencies:**

- `SourceRegistry.get` (internal)：无记录与过期均 None；source_registry.py L59-L72。
- `validate_public_http_url` (internal)：检查 scheme/credentials/全部解析 IP；url_security.py L31-L60；连接时 DNS 状态另见开放问题。
- `retention_policy_for_sources` (internal)：多个来源取布尔交集和最短 TTL；capabilities.py L349-L365。
- `ContentStore.get/reuse_for_url/put` (internal)：清理过期；scope 匹配；UTF-8 容量拒绝；content_store.py L40-L151。
- `_run_scrape_raw` (internal)：配置、key manager、site memory 注入及结果规范化；service.py L787-L823；smart 的各 backend 分支 L210-L300。
- Callers: tools.py L74；cli.py L161；service.py L635
- Shared state: content_sources 与 content_objects；state_store.py L108-L128
- Invariant coupling: 跨来源 URL 缓存命中需要当前 retention 和 scope 相同 (service.py L244-L254；content_store.py L113-L126)
- Invariant coupling: full_content 表示完整已取得正文，仍受采集及持久化容量约束 (service.py L228、L279、L296-L315；content_store.py L55-L64)

---

**Open Questions:**

- unclear; need to inspect 部署是否把 source_id 当作同一可信调用方的 bearer reference；当前入口无 tenant 字段，运行宿主权限未检查。
- unclear; need to inspect DNS 预检与最终连接之间、远端抓取服务内实际目标的契约；本轮不做网络实验。
