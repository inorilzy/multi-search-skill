## REQ-23 — 目标页面错误不改key健康状态、不轮换key

> 明确的目标错误保留使用记录，但不轮换 key、不写密钥健康状态
> — docs/glossary.md:L62

**Verdict:** implemented · confidence: high

---

**What this demands of an implementation:** 目标页面错误不改key健康状态、不轮换key。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/src/scrape/scrape.py:L100-L123
def _record_key_result(provider: str, key: str, result: dict, key_manager) -> None:
    # A target-page failure is neutral to credential health, including any
    # auth failure another in-flight request may already have recorded.
    if key_manager is None or result.get("error_origin") == "target":
        return
    candidate = _candidate_for(provider, key)
    key_manager.record_result(provider, candidate, key_manager.classify_result(provider, result))


```

```python
# multi_search_mcp/src/state/key_state.py:L82-L104
    def classify_result(self, provider: str, results: list | dict | None) -> KeyOutcome:
        rows = [results] if isinstance(results, dict) else list(results or [])
        error_rows = [row for row in rows if isinstance(row, dict) and row.get("error")]
        if not error_rows:
            return KeyOutcome(success=True, retryable=False)
        message = "; ".join(str(row.get("error", "")) for row in error_rows)
        # Target failures carry no evidence that a provider credential failed.
        error_rows = [row for row in error_rows if row.get("error_origin") != "target"]
        if not error_rows:
```

```python
# multi_search_mcp/src/support/auth.py:L1-L34
"""Shared auth and retry helpers for provider adapters."""
from __future__ import annotations


KEY_RETRY_PATTERNS = (
    "401", "403", "429", "unauthorized", "forbidden", "invalid api",
    "invalid key", "api key expired", "api key disabled", "api key revoked",
    "expired api key", "quota", "rate limit", "rate_limit",
    "too many requests", "limit exceeded", "exceeded your", "credits",
```

**Paths walked:**

scrape循环先record_use；_record_key_result遇target立刻返回；is_key_retryable_error对明确target返回False，因此不改健康也不试下一key。探针对已有key row注入target401后整行健康记录不变。本条只判ScrapeResult明确标注target路径；所有adapter是否正确标target另未全查。

**Searched:**

- `rg -n 'error_origin|target|retryable' multi_search_mcp/src/scrape/scrape.py multi_search_mcp/src/state/key_state.py multi_search_mcp/src/support/auth.py` → 24 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

scrape循环先record_use；_record_key_result遇target立刻返回；is_key_retryable_error对明确target返回False，因此不改健康也不试下一key。探针对已有key row注入target401后整行健康记录不变。本条只判ScrapeResult明确标注target路径；所有adapter是否正确标target另未全查。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
