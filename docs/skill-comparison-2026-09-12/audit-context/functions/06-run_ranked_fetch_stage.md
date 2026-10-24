## `run_ranked_fetch_stage` in multi_search_mcp/src/scrape/stage.py (L18-L98)

**Purpose:** 按输入排名并行抓取，deadline 结束后为每个来源保留位置。

---

**Inputs & Assumptions:**

- hits 为 Core 生成列表；fetch 是内部闭包；concurrency >= 1 在 L28-L29 建立。
- 前提：运行中的任务最终释放槽位；enforcement：support/concurrency.py L120-L125。
- 前提：callback 异常可形成对应 hit 错误；enforcement：scrape/stage.py L58-L62。

---

**Outputs & Effects:**

最多 concurrency 个当前调用的活跃 Future，同时受全局 30 槽限制（L12-L14、L65）。返回同序 results 和 errors（L91-L98）。

---

**Block-by-Block:**

```python
# L30-L62
results = [None] * len(hits)
...
remaining = deadline - time.monotonic()
...
result = fetch(hit, remaining)
if time.monotonic() >= deadline:
    return timeout_row(hit)
```

- **What:** 先分配位置，再对 callback 前后检查 deadline。
- **Why here:** 完成时间超预算也形成超时输出。
- **Assumes:** callback 可能已经写缓存；service.py L296-L304；检查不能回滚其副作用。
- **Establishes:** 每个结果回到原始 index；L60。
- **Depended on by:** L91-L96 总长/总序契约。

```python
# L64-L98
future = _SCRAPE_POOL.submit_before(deadline, fetch_hit, hits[next_index])
...
future.cancel()
final_results = [result if result is not None else timeout_row(hit) for hit, result in zip(hits, results)]
```

- **What:** 提交、收集、超时取消未完成任务，缺失位置补错。
- **Why here:** 全局池拥堵消耗同一 budget。
- **Assumes:** 运行中的线程不能因 Future.cancel 结束；concurrency.py L101-L106。
- **Establishes:** 无论空输入、拒绝提交、异常、超时，都返回 len(hits) 项；L31、L91-L96。
- **Depended on by:** run_search_web L653 按位置连接。

---

**Cross-Function Dependencies:**

- `BoundedDaemonExecutor.submit_before` (internal)：等待 semaphore 仅至 deadline；concurrency.py L44-L48。
- `fetch` (internal)：service.py L633-L647 调用 run_fetch_source，异常转结构化 error。
- `scrub_secrets` (internal)：模式替换/显式 secret 集/截长；secrets.py L32-L40，此调用仅传 error。
- Callers: service.py L649-L650
- Shared state: _SCRAPE_POOL；stage.py L12-L14
- Invariant coupling: 超时响应不代表 callback 没有副作用 (stage.py L49-L51；service.py L296-L304)
- Invariant coupling: 完成顺序不影响返回顺序 (stage.py L60、L69、L91-L96)

---

**Open Questions:**

无本函数特有未决问题；外部运行边界见 DOSSIER。
