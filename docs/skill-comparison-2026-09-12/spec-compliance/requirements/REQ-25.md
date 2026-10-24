## REQ-25 — fetch目标URL统一执行SSRF输入校验

> 目标 URL 统一执行 SSRF 校验。
> — docs/glossary.md:L73

**Verdict:** implemented · confidence: high

---

**What this demands of an implementation:** fetch目标URL统一执行SSRF输入校验。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/src/service.py:L199-L206
    if source is None and store and request.source_id:
        source = SourceRegistry(store).get(request.source_id)
    if request.source_id and source is None:
        raise ValueError(
            "source_id is unknown or expired; call search_web again before fetch_source"
        )
    url = str(request.url or source["url"])
    validate_public_http_url(url, resolver=url_resolver)
```

```python
# multi_search_mcp/src/support/url_security.py:L31-L60
def _validate_url(url: str, *, label: str, resolver: Resolver | None) -> str:
    candidate = str(url or "").strip()
    try:
        parts = urllib.parse.urlsplit(candidate)
    except Exception as exc:
        raise UrlSecurityError(f"{label} is not a valid URL: {exc}") from exc

    scheme = (parts.scheme or "").lower()
    if scheme not in {"http", "https"}:
```

```python
# multi_search_mcp/src/support/url_security.py:L100-L117
def _unsafe_reason(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    if ip.is_unspecified:
        return "unspecified"
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link-local"
    if ip.is_multicast:
        return "multicast"
```

```python
# multi_search_mcp/src/scrape/scrape.py:L134-L142
def _prepare_scrape_target(url: str, *, resolver=None) -> tuple[str, str]:
    safe_url = validate_scrape_url(url, resolver=resolver)
    return safe_url, safe_url


def scrape_url_smart(url: str, firecrawl_key: str | None = None,
                     timeout: int = _DEFAULT_SCRAPE_TIMEOUT_SECONDS,
                     exa_key: str = "", tavily_key: str = "",
                     primary: str | None = None,
```

**Paths walked:**

fetch无论source_id/url、cache hit/miss均在取正文前校验；通用scrape目标与重写目标也经校验。只接受http/https、禁userinfo、所有DNS答案需public；离线私网/元数据IP/unsafe scheme/凭据URL/混合DNS全部拒绝。此条确认入口校验，不能推导DNS绑定、远端provider重定向或所有外部SDK绝无SSRF。

**Searched:**

- `rg -n 'validate_public_http_url|validate_scrape_url|_ensure_public_ip' multi_search_mcp/src/service.py multi_search_mcp/src/support/url_security.py multi_search_mcp/src/scrape/scrape.py` → 10 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

fetch无论source_id/url、cache hit/miss均在取正文前校验；通用scrape目标与重写目标也经校验。只接受http/https、禁userinfo、所有DNS答案需public；离线私网/元数据IP/unsafe scheme/凭据URL/混合DNS全部拒绝。此条确认入口校验，不能推导DNS绑定、远端provider重定向或所有外部SDK绝无SSRF。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
