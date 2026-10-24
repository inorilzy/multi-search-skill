## `run_keyed_source` in multi_search_mcp/src/search/search_runner.py (L247-L284)

**Purpose:** 顺序尝试候选 key，保留部分结果，记录实际调用和结果。

---

**Inputs & Assumptions:**

- source/provider 是内部身份；key_value trusted 配置值；call_with_key 为 registry 注入 callable（L338-L348）。
- 前提：key deadline 每次尝试前检查；enforcement：search_runner.py L262-L264。
- 前提：失败类别来自 provider 行而非 HTTP code 单独推断；enforcement：key_state.py L82-L104；support/auth.py L25-L33。

---

**Outputs & Effects:**

调用 provider；可能修改 key_state 的使用和结果计数；耗尽时返回明确错误与累积部分行（L265-L284）。

---

**Block-by-Block:**

```python
# L255-L270
candidates = manager.candidates(provider, key_value)
...
manager.record_use(provider, candidate)
results = _attach_provider_ranks(as_dicts(call_with_key(key) or []))
outcome = manager.classify_result(provider, results)
manager.record_result(provider, candidate, outcome)
```

- **What:** 候选快照→使用记账→外部调用→结果记账。
- **Why here:** 调用次数与最终结果不是同一状态字段。
- **Assumes:** SQLite candidates 排除当时禁用/冷却项；key_state.py L146-L155；没有租约语义。
- **Establishes:** provider 公开名称与 key 身份分开；L252-L254。
- **Depended on by:** 后续选择利用 last_used_at 和 outcome 状态。

```python
# L271-L284
if not outcome.retryable:
    return _merge_partial_rows(source, partial_rows, results) if partial_rows else results
partial_rows.extend(row for row in results if "error" not in row)
```

- **What:** 只对 retryable 结果尝试下一个 key，保留已经成功的行。
- **Why here:** 失败时不丢先前结果。
- **Assumes:** classify_result 排除 target 错误再分类；key_state.py L82-L104；auth.py L25-L33。
- **Establishes:** 耗尽后的错误经 scrub，部分行经 canonical identity 合并；L280-L284。
- **Depended on by:** SearchRunner.run 收集或异常转换 L391-L406。

---

**Cross-Function Dependencies:**

- `SQLiteKeyManager.candidates` (internal)：按状态过滤并按 never_used/last_used_at/order 排序；key_state.py L125-L160。
- `record_use/record_result` (internal)：独立 SQL 事务；key_state.py L162-L240。
- `_attach_provider_ranks/_merge_partial_rows` (internal)：合法候选附 rank；部分行按 identity 合并；search_runner.py L168-L244。
- `call_with_key` (internal)：选定 Brave 路径：registry.py L54-L59；异步池异常处理在 search_runner.py L393-L396。
- Callers: SearchRunner._run_keyed_source L413-L416
- Shared state: key_state；key_state.py L162-L240
- Invariant coupling: key use_count 与 success/failure_count 是不同时间的记录 (search_runner.py L266-L270；key_state.py L162-L174)
- Invariant coupling: 重试中保留部分候选并以来源+canonical URL 去重 (search_runner.py L225-L243、L276-L284)

---

**Open Questions:**

- unclear; need to inspect 运营对同一 key 并行使用的要求；当前选择快照与使用记账之间无独占预留，不能把 LRU 排序描述为独占分配。
