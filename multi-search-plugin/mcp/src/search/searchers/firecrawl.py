"""Firecrawl /v2/search."""
import json
import urllib.request

from ...support.http import urlopen_retry
from ...support.secrets import scrub_secrets


def search_firecrawl(
    query: str,
    api_key: str,
    count: int = 10,
    timeout: float = 60,
    include_domains: list[str] | tuple[str, ...] | None = None,
    source: str = "firecrawl",
) -> list:
    """Search via Firecrawl /v2/search without inline scraping."""
    body = {
        "query": query,
        "limit": count,
    }
    if include_domains:
        body["includeDomains"] = list(include_domains)
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        "https://api.firecrawl.dev/v2/search",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen_retry(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"source": source, "error": scrub_secrets(e, api_key)}]

    if data.get("success") is False:
        error = data.get("error") or data.get("message") or "request failed"
        if isinstance(error, dict):
            error = json.dumps(error, ensure_ascii=False)
        return [{"source": source, "error": scrub_secrets(error, api_key)}]

    items = []
    data_field = data.get("data") or []
    if isinstance(data_field, dict):
        web_results = data_field.get("web")
        if web_results is None:
            web_results = [data_field] if any(k in data_field for k in ("title", "url", "description")) else []
    else:
        web_results = data_field
    if isinstance(web_results, dict):
        web_results = [web_results]
    if not isinstance(web_results, list):
        web_results = []
    for result in web_results:
        if not isinstance(result, dict):
            continue
        item = {
            "source": source,
            "title": result.get("title", ""),
            "url": result.get("url", ""),
            "description": (result.get("description") or "")[:300],
        }
        items.append(item)
    return items


V2EX_DOMAINS = ("www.v2ex.com", "v2ex.com", "global.v2ex.com")
REDDIT_DOMAINS = ("www.reddit.com", "old.reddit.com", "new.reddit.com", "reddit.com")
ZHIHU_DOMAINS = ("www.zhihu.com", "zhuanlan.zhihu.com", "zhihu.com")
LINUXDO_DOMAINS = ("linux.do",)


def search_v2ex(query: str, api_key: str, count: int = 10, timeout: float = 60) -> list:
    """Search V2EX via Firecrawl domain-restricted web search."""
    return search_firecrawl(
        query,
        api_key,
        count,
        timeout=timeout,
        include_domains=V2EX_DOMAINS,
        source="v2ex",
    )


def search_reddit(query: str, api_key: str, count: int = 10, timeout: float = 60) -> list:
    """Search Reddit via Firecrawl domain-restricted web search."""
    return search_firecrawl(
        query,
        api_key,
        count,
        timeout=timeout,
    include_domains=REDDIT_DOMAINS,
    source="reddit",
)


def search_zhihu(query: str, api_key: str, count: int = 10, timeout: float = 60) -> list:
    """Search Zhihu via Firecrawl domain-restricted web search."""
    return search_firecrawl(
        query,
        api_key,
        count,
        timeout=timeout,
        include_domains=ZHIHU_DOMAINS,
        source="zhihu",
    )


def search_linuxdo(query: str, api_key: str, count: int = 10, timeout: float = 60) -> list:
    """Search Linux.do via Firecrawl domain-restricted web search."""
    return search_firecrawl(
        query,
        api_key,
        count,
        timeout=timeout,
        include_domains=LINUXDO_DOMAINS,
        source="linuxdo",
    )
