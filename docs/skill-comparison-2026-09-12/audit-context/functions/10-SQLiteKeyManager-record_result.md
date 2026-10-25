## `SQLiteKeyManager.record_result` in multi_search_mcp/src/state/key_state.py (L174-L240)

**Purpose:** 将一次 provider outcome 转成 key 健康状态和计数。

---

**Inputs & Assumptions:**

- candidate/outcome 为内部 key manager 数据；classify_result L82-L104 生成类别，_ensure_row L266-L275 建立主键行。
- 前提：结果状态更新对应行存在；enforcement：key_state.py L175、L266-L275。
- 前提：SQL 写入错误传播并回滚；enforcement：state/state_store.py L153-L158。

---

**Outputs & Effects:**

单次 SQL 更新 success/failure/rate/quota/invalid strike 等字段；错误消息写库前 scrub（L177-L240）。

---

**Block-by-Block:**

```python
# L177-L214
if outcome.success:
    ...
    return
...
strike_assignment = "invalid_strikes = invalid_strikes + 1"
```

- **What:** 成功恢复 active 并清 strikes；invalid 原子递增，并在第三次转 permanent invalid。
- **Why here:** CASE 与增量在同一 UPDATE 中使用原行值。
- **Assumes:** 同一 key 行由 provider,key_id 标识；state_store.py L36。
- **Establishes:** 并发结果按 SQL 提交顺序更新，无 Python 先读后写 strike；L204-L212、L226-L240。
- **Depended on by:** candidates L146-L155 根据新状态过滤。

```python
# L215-L240
elif error_type == "rate_limit":
    ...
elif error_type == "quota_exhausted":
    ...
else:
    strike_assignment = "invalid_strikes = 0"
```

- **What:** rate_limit 15分钟、quota 24小时；其他失败保持 active 并清 strikes。
- **Why here:** 失败类别是状态转移输入。
- **Assumes:** target 在 scrape helper 提前跳过；scrape.py L103-L106；search 分类仍产生 target outcome，key_state.py L89-L91。
- **Establishes:** 同一个 record_result 对所有非 success 都增加 failure_count；L229。
- **Depended on by:** 选择状态与运营诊断。

---

**Cross-Function Dependencies:**

- `_ensure_row` (internal)：INSERT OR IGNORE 建立唯一 provider/key_id；L266-L275。
- `classify_error` (internal)：显式类型优先；否则字符串顺序分类；L278-L292。
- `StateStore.execute/connect` (internal)：每次 UPDATE 独立连接事务；state_store.py L150-L160、L191-L193。
- `scrub_secrets` (internal)：对已知 candidate.key 与常见模式替换；secrets.py L32-L40。
- Callers: search_runner.py L270；scrape.py L106
- Shared state: key_state，同 candidates/record_use/reset 共享；L125-L275
- Invariant coupling: invalid strike 增量与状态选择使用同一 SQL 更新 (key_state.py L204-L212、L226-L240)
- Invariant coupling: 错误字符串入 key_state 前应用已知 key 脱敏 (key_state.py L237；support/secrets.py L32-L40)

---

**Open Questions:**

- unclear; need to inspect 所有 search provider 是否发送 target origin；本轮只记录 search/scrape 两条调用链的不同处理，未判定业务影响。
