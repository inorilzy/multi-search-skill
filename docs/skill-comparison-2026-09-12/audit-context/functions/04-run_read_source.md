## `run_read_source` in multi_search_mcp/src/service.py (L120-L172)

**Purpose:** 从缓存正文中按原始字符位置返回一段文本。

---

**Inputs & Assumptions:**

- source_id/keyword/offset/limit：untrusted。source_id 非空、use_state 为真在 L129-L132 检查。
- 前提：已过期缓存不能读取；enforcement：state/content_store.py L142、L215-L225。
- 前提：匹配失败不返回一个无关片段；enforcement：service.py L146-L148。

---

**Outputs & Effects:**

无网络调用；ContentStore.get 可删除过期引用并更新 LRU（content_store.py L138-L151）。返回 offsets/hash/expiry/untrusted_content（L160-L171）。

---

**Block-by-Block:**

```python
# L135-L159
cached = cache.get(request.source_id)
...
limit = max(1, min(int(request.limit), 8_000))
...
end = min(len(body), start + limit)
```

- **What:** 缓存缺失报错；限制最多 8000 原文字符；keyword 在 lower 后匹配再映射回原文。
- **Why here:** 原始字符位置在切片之前确定。
- **Assumes:** cache.get 不返回已到期正文；content_store.py L142、L215-L225。
- **Establishes:** 0 <= start <= end <= len(body)，长度 <= 8000；L142-L159。
- **Depended on by:** next_offset 与后续分页请求。

---

**Cross-Function Dependencies:**

- `ContentStore.get` (internal)：None 为缺失/过期；有效命中同时触碰 LRU；L138-L151。
- Callers: tools.py L92；cli.py L174
- Shared state: content_sources/content_objects（同 fetch）；state_store.py L108-L128
- Invariant coupling: 分页边界以原始正文字符为单位 (service.py L149-L159)
- Invariant coupling: read 不建立新的来源 TTL (content_store.py L146-L150 仅更新 last_access_at)

---

**Open Questions:**

无本函数特有未决问题；外部运行边界见 DOSSIER。
