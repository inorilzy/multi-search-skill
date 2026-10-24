## REQ-15 — 跨响应URL缓存复用不延长原TTL

> 关联新 ID 不延长原正文 TTL
> — README.md:L254

**Verdict:** implemented · confidence: high

---

**What this demands of an implementation:** 跨响应URL缓存复用不延长原TTL。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/src/service.py:L242-L254
        if not prefetched_body:
            runtime_keys = load_keys() if keys is None else dict(keys)
            if content_store and retention.persist_body:
                # Hash the permission context; never persist credentials. Provider
                # prefetches and older unscoped entries remain source-ID-only.
                cache_scope = hashlib.sha256(json.dumps({
                    "providers": sorted(source_providers),
                    "backends": list(request.backends or []),
                    "keys": runtime_keys,
```

```python
# multi_search_mcp/src/state/content_store.py:L94-L136
    def reuse_for_url(self, source_id: str, *, canonical_url: str, cache_scope: str) -> dict | None:
        """Bind an eligible URL body to another response's source id.

        The caller supplies an already canonical URL and an opaque scope covering
        source, backend and authorization restrictions. It must also check current
        retention permission before calling; empty legacy scopes never participate.
        Reuse never renews the acquired body's expiration.
        """
        if not source_id or not canonical_url or not cache_scope:
```

**Paths walked:**

使用来源集合/显式后端顺序/keys序列化SHA256形成scope，仅同URL同scope命中；新binding expires=min(原expires,now+当前TTL)，created_at沿用原值，禁止legacy空scope。探针验证新ID与旧ID expires_at完全相同。当前同ID策略变更的完整迁移语义没有纳入这条。

**Searched:**

- `rg -n 'cache_scope|expires_at = min|reuse_for_url' multi_search_mcp/src/service.py multi_search_mcp/src/state/content_store.py` → 21 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

使用来源集合/显式后端顺序/keys序列化SHA256形成scope，仅同URL同scope命中；新binding expires=min(原expires,now+当前TTL)，created_at沿用原值，禁止legacy空scope。探针验证新ID与旧ID expires_at完全相同。当前同ID策略变更的完整迁移语义没有纳入这条。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
