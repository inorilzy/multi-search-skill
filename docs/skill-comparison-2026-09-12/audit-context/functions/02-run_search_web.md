## `run_search_web` in multi_search_mcp/src/service.py (L595-L694)

**Purpose:** 把候选融合与正文采集连接起来，维持结果顺序和正文预览语义。

---

**Inputs & Assumptions:**

- request 为半可信框架映射值；dict 经 SearchWebRequest 构造（L610-L611），业务合法性继续由候选规划检查。
- 前提：candidate 的 source_id/url/canonical_url 存在；enforcement：search/candidate.py L191-L207。
- 前提：抓取结果总有对应输入槽位；enforcement：scrape/stage.py L31、L91-L96。

---

**Outputs & Effects:**

搜索来源引用、可保存正文、密钥健康与站点统计均可能写入；返回 candidates+scrapes+diagnostics（L621-L694）。

---

**Block-by-Block:**

```python
# L624-L651
response = _run_search_candidates(...)
fetched = run_ranked_fetch_stage(response["results"], fetch=fetch, timeout=body_timeout, concurrency=concurrency)
```

- **What:** 先产生排名，然后按既有排名获取全文。
- **Why here:** 正文失败不得重排候选。
- **Assumes:** 候选不超过 15：candidate.py L14、L261/L287；stage 返回与 hits 同长度同序 L91-L96。
- **Establishes:** 搜索与正文阶段分别建立预算；service.py L402、L630，stage.py L30。
- **Depended on by:** L653 的 zip 逐项关联。

```python
# L653-L677
for hit, body_result in zip(response["results"], fetched["results"]):
    ...
    start = body_preview_start(body, hit["title"], max_chars, hit.get("content") or "")
    end = min(len(body), start + max_chars)
```

- **What:** 错误写入 hit.body_error，成功只在输出阶段切片。
- **Why here:** 全文先通过 fetch/cache，再生成预览。
- **Assumes:** normalize_scrape_result 保证非空 markdown 或 error；models.py L219-L244。
- **Establishes:** 预览长度不超过 max_chars，且原始 body 不被切片覆盖；L666-L671。
- **Depended on by:** 调用者凭 source_id 后续 read。

---

**Cross-Function Dependencies:**

- `_run_search_candidates` (internal)：L321-L530：验证 query/plan；query deadline 共用；选中正文后才存储；provider body 解释见 models.py L59-L78。
- `run_ranked_fetch_stage` (internal)：错误补位，同序返回；stage.py L91-L96。
- `run_fetch_source` (internal)：传 full_content=True 后先缓存正文；service.py L633-L644。
- `body_preview_start` (internal)：在 title/snippet 精确条件下选择原文 offset，失败回 0；format.py L34-L80。
- Callers: tools.py L54；cli.py L146
- Shared state: search_sources/content_sources/content_objects；service.py L456-L495
- Invariant coupling: 抓取结果与候选按输入位置连接，成功/失败不影响排名 (scrape/stage.py L31、L60、L91-L96；service.py L653)
- Invariant coupling: 预览上限不缩短已缓存正文 (service.py L637、L296-L308、L666-L671)

---

**Open Questions:**

- unclear; need to inspect 其他 provider 对 body/content_kind 的实际来源保证；本轮只深入 Brave 与 Exa 抓取。
