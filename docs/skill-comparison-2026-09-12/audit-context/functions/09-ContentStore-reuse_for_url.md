## `ContentStore.reuse_for_url` in multi_search_mcp/src/state/content_store.py (L94-L136)

**Purpose:** 将已有内容对象绑定到新的 source_id，并保持原始到期上限。

---

**Inputs & Assumptions:**

- source_id/canonical_url/cache_scope：内部调用者提供，非空在 L102-L103 检查；clock 为 trusted 默认 UTC（L16-L17）。
- 前提：当前 retention 许可由调用者建立；enforcement：service.py L244-L254。
- 前提：scope 确定 provider/backend/keys 上下文；enforcement：service.py L247-L251。
- 前提：事务中任一步失败回滚；enforcement：state/state_store.py L153-L158。

---

**Outputs & Effects:**

BEGIN IMMEDIATE 下清理过期、查询合格对象、绑定新引用、更新 LRU、按容量逐出（L105-L136）。

---

**Block-by-Block:**

```python
# L102-L126
cached = conn.execute(...).fetchone()
...
expires_at = min(datetime.fromisoformat(str(cached["expires_at"])), now + timedelta(seconds=self.ttl_seconds)).isoformat()
```

- **What:** 匹配权限 scope 和 URL；过期或过大对象不复用。
- **Why here:** 复用不会刷新原采集内容的寿命。
- **Assumes:** 调用者已检查 retention；service.py L244。
- **Establishes:** 新 expiry <= 原 expiry，且 <= 当前 TTL；L123-L126。
- **Depended on by:** 读引用 TTL 的 get/purge。

```python
# L127-L136
self._bind_source_conn(...)
...
self._evict_lru(conn, protected_hash=str(cached["content_hash"]))
return self._lookup_conn(conn, source_id)
```

- **What:** 重绑前后都在同一事务，旧对象仅无其他引用才删。
- **Why here:** 失败回滚避免只写一半。
- **Assumes:** 连接上下文 commit/rollback/close，state_store.py L150-L160。
- **Establishes:** bind 更新引用、孤儿清除、对象容量规则共同完成；L171-L268。
- **Depended on by:** 后续 source_id hit。

---

**Cross-Function Dependencies:**

- `_purge_expired_conn` (internal)：先删过期引用，再删孤儿正文；L215-L236。
- `_bind_source_conn` (internal)：upsert source_id，旧 hash 无引用时才删除；L171-L194。
- `_evict_lru` (internal)：容量过大时逐出非 protected 对象及其所有引用；无可逐出对象则报错；L238-L268。
- `StateStore.connect` (internal)：commit、rollback、finally close；state_store.py L150-L160。
- Callers: service.py L252；rg 全包其他生产调用未发现
- Shared state: content_sources/content_objects；state_store.py L108-L128
- Invariant coupling: URL 复用不延长原始到期时间 (content_store.py L123-L126)
- Invariant coupling: 正文对象和来源引用分别存储，删除单一来源不必删除共享正文 (content_store.py L171-L194、L227-L236)

---

**Open Questions:**

无本函数特有未决问题；外部运行边界见 DOSSIER。
