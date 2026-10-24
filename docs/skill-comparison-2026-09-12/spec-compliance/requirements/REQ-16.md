## REQ-16 — 禁止正文持久化的provider策略优先

> provider 的 retention policy 可禁止保存结果、摘要或正文。
> — README.md:L252

**Verdict:** implemented · confidence: high

---

**What this demands of an implementation:** 禁止正文持久化的provider策略优先。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/src/search/capabilities.py:L349-L365
def retention_policy_for_sources(names: list[str] | tuple[str, ...]) -> RetentionPolicy:
    policies = []
    for name in names:
        capability = get_capability_optional(name)
        policies.append(
            capability.retention if capability is not None else DEFAULT_RETENTION_POLICY
        )
    if not policies:
        policies = [DEFAULT_RETENTION_POLICY]
```

```python
# multi_search_mcp/src/service.py:L456-L466
    if store is not None:
        for hit in hits:
            retention = retention_policy_for_sources(list(hit.get("providers") or []))
            if not retention.persist_search_result:
                continue
            registry_hit = dict(hit)
            if not retention.persist_content:
                registry_hit["content"] = ""
            SourceRegistry(
```

```python
# multi_search_mcp/src/service.py:L484-L499
    if store is not None:
        for hit in hits:
            retention = retention_policy_for_sources(list(hit.get("providers") or []))
            if not retention.persist_body:
                continue
            body = selected_bodies.get(str(hit["canonical_url"]))
            if not body:
                continue
            try:
```

```python
# multi_search_mcp/src/service.py:L230-L234
    content_store = ContentStore(store, ttl_seconds=retention.max_ttl_seconds) if store is not None else None
    cached = content_store.get(source_id) if content_store and source_id else None
    if cached is not None and not retention.persist_body:
        content_store.delete_source(source_id)
        cached = None
```

```python
# multi_search_mcp/src/service.py:L296-L303
    stored = (
        content_store.put(
            source_id, body,
            canonical_url=canonicalize_url(url) if cache_scope else "",
            cache_scope=cache_scope,
        )
        if content_store and source_id and retention.persist_body
        else None
```

**Paths walked:**

合并provider策略对权限取all、TTL取min；候选注册受persist_search_result、摘要受persist_content、预取与fetch缓存写入受persist_body；已有缓存遇当前persist_body=False删除binding并重新取得。此条原子判定的是persist_body禁止开关，其他两种开关仅记录邻接调用，未展开第三方条款正确性。

**Searched:**

- `rg -n 'persist_body|persist_content|persist_search_result' multi_search_mcp/src/search/capabilities.py multi_search_mcp/src/service.py` → 15 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

合并provider策略对权限取all、TTL取min；候选注册受persist_search_result、摘要受persist_content、预取与fetch缓存写入受persist_body；已有缓存遇当前persist_body=False删除binding并重新取得。此条原子判定的是persist_body禁止开关，其他两种开关仅记录邻接调用，未展开第三方条款正确性。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
