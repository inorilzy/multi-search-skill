## REQ-24 — Jina自动exhausted必须先由余额接口确认

> 只有余额接口确认 `wallet.total_balance <= 0` 时才会自动标记 exhausted。
> — README.md:L217

**Verdict:** undecidable · confidence: high

---

**What this demands of an implementation:** Jina自动exhausted必须先由余额接口确认。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/src/scrape/scrapers/jina.py:L167-L197
        except urllib.error.HTTPError as exc:
            message = _jina_error_message(exc)
            last_error = f"HTTP {exc.code}: {message}"
            limited = _jina_rate_limited(exc.code, message)
            if limited:
                rate_limited = True
                if not key:
                    _record_jina_anonymous_rate_limit()
                # Classify exhaustion from the error itself instead of issuing a
```

```python
# multi_search_mcp/src/state/key_state.py:L92-L95
        if any(row.get("exhausted") or row.get("key_exhausted") for row in error_rows):
            return KeyOutcome(False, True, "quota_exhausted", message)
        if any(row.get("rate_limited") for row in error_rows):
            return KeyOutcome(False, True, "rate_limit", message)
```

```python
# multi_search_mcp/src/state/key_state.py:L219-L222
        elif error_type == "quota_exhausted":
            status = QUOTA_EXHAUSTED
            exhausted_until = _iso(_now() + timedelta(hours=24))
            quota_inc = 1
```

```python
# multi_search_mcp/src/state/keys.py:L90-L98
def jina_config_keys(value) -> list[str]:
    """Return configured Jina keys that are not statically disabled.

    Honors the config-level ``exhausted: true`` flag (a user/operator opt-out),
    but performs no shuffling and no runtime exhaustion bookkeeping. Live key
    health (cooldown / quota / invalid) is owned by ``SQLiteKeyManager`` so that
    Jina shares the same state-aware LRU rotation as the other providers.
    """
    return [e["key"] for e in normalize_jina_config(value) if not e["exhausted"]]
```

```python
# multi_search_mcp/src/state/mark_exhausted.py:L32-L52
    def _mark(val):
        nonlocal changed
        if isinstance(val, str):
            if val == key_to_mark:
                changed = True
                return {"key": val, "exhausted": True}
            return val
        if isinstance(val, dict):
            if val.get("key") == key_to_mark and not val.get("exhausted"):
```

**Paths walked:**

实际HTTP402直接产生result.exhausted/key_exhausted，并被状态manager写为24h quota_exhausted。探针只有1次模拟reader HTTP调用，无余额调用。反证：README紧邻的是配置对象exhausted软删除；该持久配置与SQLite运行态不是同一状态，自动HTTP路径并不调用mark_exhausted写配置。故不能得出永久禁用或业务bug，只能判文档没有明确exhausted指哪一层。

**Searched:**

- `rg -n 'wallet|balance|exhausted|mark_config' multi_search_mcp/src/scrape/scrapers/jina.py multi_search_mcp/src/state/key_state.py multi_search_mcp/src/state/keys.py multi_search_mcp/src/state/mark_exhausted.py` → 43 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

实际HTTP402直接产生result.exhausted/key_exhausted，并被状态manager写为24h quota_exhausted。探针只有1次模拟reader HTTP调用，无余额调用。反证：README紧邻的是配置对象exhausted软删除；该持久配置与SQLite运行态不是同一状态，自动HTTP路径并不调用mark_exhausted写配置。故不能得出永久禁用或业务bug，只能判文档没有明确exhausted指哪一层。

**Open questions:**

需主代理独立重读文档与运行态/配置态调用链；当前不是确认业务bug。
