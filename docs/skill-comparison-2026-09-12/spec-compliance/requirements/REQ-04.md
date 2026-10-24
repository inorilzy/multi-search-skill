## REQ-04 — disabled_sources 对显式源生效且全禁用明确失败

> route 正常解析后会从结果里减去这些源，对 tool 显式传入的 `sources` 同样生效。
> — README.md:L351

**Verdict:** implemented · confidence: high

---

**What this demands of an implementation:** disabled_sources 对显式源生效且全禁用明确失败。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/src/search/resolve.py:L131-L154
def resolve_disabled_sources(config: dict) -> set[str]:
    """Resolve the globally disabled search sources from config.

    Only search sources are accepted; scrape backends (e.g. ``jina``) are not
    valid here. Unknown names fail loudly instead of being silently ignored.
    """
    disabled = {normalize_source_name(source) for source in config_list(config, "disabled_sources")}
    unknown = disabled - ALL_SOURCE_NAMES
    if unknown:
```

```python
# multi_search_mcp/src/service.py:L374-L386
    base_sources, active_sources = resolve_active_sources(
        plan.route, plan.sources, plan.disabled_sources
    )
    if base_sources and not active_sources:
        raise ValueError(
            f"all selected sources are disabled: {', '.join(sorted(base_sources))}"
        )

    def route_resolver(_route):
```

**Paths walked:**

请求源经同一 resolve_active_sources 差集，_run_search_candidates 对非空 selected 且 active 为空抛 ValueError。未知禁用名称在源调用前失败；离线探针验证显式 github 被禁用后 active 为空。

**Searched:**

- `rg -n 'disabled_sources|all selected sources' multi_search_mcp/src/search/resolve.py multi_search_mcp/src/service.py` → 10 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

请求源经同一 resolve_active_sources 差集，_run_search_candidates 对非空 selected 且 active 为空抛 ValueError。未知禁用名称在源调用前失败；离线探针验证显式 github 被禁用后 active 为空。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
