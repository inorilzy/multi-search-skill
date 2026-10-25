## REQ-11 — source_id 是一次响应内canonical URL的短期身份

> 一次搜索响应中某个来源的短期身份
> — CONTEXT.md:L15

**Verdict:** implemented · confidence: high

---

**What this demands of an implementation:** source_id 是一次响应内canonical URL的短期身份。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/src/search/candidate.py:L73-L77
def make_source_id(response_id: str, canonical_url: str) -> str:
    digest = hashlib.sha256(
        f"{response_id}\0{canonical_url}".encode("utf-8")
    ).hexdigest()
    return f"src_{digest[:20]}"
```

```python
# multi_search_mcp/src/search/candidate.py:L191-L206
    source_id = make_source_id(response_id, canonical_url)
    hit = {
        "source_id": source_id,
        "title": str(representative.get("title") or representative.get("url") or ""),
        "url": str(representative.get("url") or canonical_url),
        "canonical_url": canonical_url,
        "content": _compact(content_text),
        "content_kind": content_kind,
        "published_at": published_at,
```

```python
# multi_search_mcp/src/state/source_registry.py:L30-L69
    def register(self, response_id: str, hits: list[dict]) -> None:
        now = self.clock()
        expires_at = now + timedelta(seconds=self.ttl_seconds)
        with self.store.connect() as conn:
            self._purge_expired_conn(conn, now.isoformat())
            for hit in hits:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO search_sources (
```

```python
# multi_search_mcp/src/service.py:L209-L226
    source_id = str(request.source_id or "")
    if not source_id:
        response_id = f"resp_{uuid.uuid4().hex}"
        canonical_url = canonicalize_url(url)
        source_id = make_source_id(response_id, canonical_url)
        if store is not None:
            SourceRegistry(
                store, ttl_seconds=retention.max_ttl_seconds
            ).register(response_id, [{
```

**Paths walked:**

ID由response_id与canonical URL拼接SHA256前20hex构成；新搜索/直接URLfetch创建随机response_id。registry过期查询删引用；未知source fetch抛错。离线跨响应同URL产生不同ID，但cache_scope允许正文复用。未主张此短ID是授权令牌或永久身份。

**Searched:**

- `rg -n 'make_source_id|response_id|expires_at' multi_search_mcp/src/search/candidate.py multi_search_mcp/src/state/source_registry.py multi_search_mcp/src/service.py` → 28 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

ID由response_id与canonical URL拼接SHA256前20hex构成；新搜索/直接URLfetch创建随机response_id。registry过期查询删引用；未知source fetch抛错。离线跨响应同URL产生不同ID，但cache_scope允许正文复用。未主张此短ID是授权令牌或永久身份。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
