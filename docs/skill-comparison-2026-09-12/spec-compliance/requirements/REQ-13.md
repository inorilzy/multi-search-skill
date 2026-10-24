## REQ-13 — read_source 缓存未命中不会隐式联网

> 缺失或过期时明确要求先调用 `fetch_source`，不会隐式联网
> — docs/glossary.md:L74

**Verdict:** implemented · confidence: high

---

**What this demands of an implementation:** read_source 缓存未命中不会隐式联网。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/src/service.py:L120-L171
def run_read_source(
    request: ReadSourceRequest | dict,
    *,
    state_store: StateStore | None = None,
    content_store: ContentStore | None = None,
) -> dict:
    """Read a bounded slice from ContentStore without accessing the network."""
    if isinstance(request, dict):
        request = ReadSourceRequest(**request)
```

```python
# multi_search_mcp/src/state/content_store.py:L138-L151
    def get(self, source_id: str) -> dict | None:
        now = self.clock()
        now_iso = now.isoformat()
        with self.store.connect() as conn:
            self._purge_expired_conn(conn, now)
            row = self._lookup_conn(conn, source_id)
            if row is None:
                return None
            conn.execute(
```

```python
# multi_search_mcp/src/state/content_store.py:L215-L225
    def _purge_expired_conn(self, conn, now: datetime) -> int:
        expired_rows = conn.execute(
            "SELECT source_id, content_hash FROM content_sources WHERE expires_at <= ?",
            (now.isoformat(),),
        ).fetchall()
        if not expired_rows:
            return 0
        conn.execute("DELETE FROM content_sources WHERE expires_at <= ?", (now.isoformat(),))
        for row in expired_rows:
```

**Paths walked:**

read只调用ContentStore.get，get清理过期对象；缺缓存立刻ValueError，没有scraper/HTTP分支。use_state=False明确拒绝。离线探针在所有网络边界禁止条件下同时读成功和未命中错误。

**Searched:**

- `rg -n 'run_read_source|cached is None|fetch_source first' multi_search_mcp/src/service.py multi_search_mcp/src/state/content_store.py` → 5 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

read只调用ContentStore.get，get清理过期对象；缺缓存立刻ValueError，没有scraper/HTTP分支。use_state=False明确拒绝。离线探针在所有网络边界禁止条件下同时读成功和未命中错误。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
