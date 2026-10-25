## REQ-03 — 显式 sources 覆盖 route 选源

> **优先级高于 route，会忽略 route。**
> — docs/glossary.md:L47

**Verdict:** implemented · confidence: high

---

**What this demands of an implementation:** 显式 sources 覆盖 route 选源。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/src/search/resolve.py:L114-L128
def _resolve_sources(route: str, requested_sources: list[str] | None) -> set[str] | None:
    if requested_sources:
        source_names = {normalize_source_name(str(source)) for source in requested_sources}
        unknown_sources = source_names - ALL_SOURCE_NAMES
        if unknown_sources:
            raise ValueError(
                f"unknown source(s): {', '.join(sorted(unknown_sources))}; "
                f"valid sources: {', '.join(sorted(ALL_SOURCE_NAMES))}"
            )
```

```python
# multi_search_mcp/src/search/resolve.py:L147-L154
def resolve_active_sources(
    route: str,
    requested_sources: set[str] | None,
    disabled_sources: set[str],
) -> tuple[set[str], set[str]]:
    """Return (selected, active) sources, where active drops disabled ones."""
    selected = requested_sources or resolve_route(route)
    return selected, selected - disabled_sources
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

resolve_search_plan → _resolve_sources 将指定源及别名校验成集合；resolve_active_sources 选 requested_sources 或 route。无显式源进入 route，未知源失败。此处“忽略”限于本节选源，不把 route 默认 timeout/count 也解释为被清除。

**Searched:**

- `rg -n 'requested_sources|source_names' multi_search_mcp/src/search/resolve.py multi_search_mcp/src/service.py` → 11 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

resolve_search_plan → _resolve_sources 将指定源及别名校验成集合；resolve_active_sources 选 requested_sources 或 route。无显式源进入 route，未知源失败。此处“忽略”限于本节选源，不把 route 默认 timeout/count 也解释为被清除。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
