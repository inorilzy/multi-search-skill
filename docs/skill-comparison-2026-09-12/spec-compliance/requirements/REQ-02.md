## REQ-02 — CLI 全失败、零匹配、部分成功退出语义

> 搜索全部活动源失败时 CLI 退出 `1`，JSON 仍保留完整错误；正常零匹配和部分成功退出 `0`。
> — README.md:L35

**Verdict:** implemented · confidence: high

---

**What this demands of an implementation:** CLI 全失败、零匹配、部分成功退出语义。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/cli.py:L115-L128
        payload = args.handler(args)
        _write_payload(payload, args.format, stdout)
        if args.command == "search":
            statuses = payload.get("provider_status") or []
            if statuses and all(row.get("status") == "error" for row in statuses):
                stderr.write("error: all selected search providers failed\n")
                return 1
        if args.command == "doctor" and (
            payload.get("config_error") or payload.get("keys_error")
```

```python
# multi_search_mcp/src/service.py:L533-L563
def _query_provider_status(
    query_runs: list[tuple[str, list[dict]]],
) -> list[dict]:
    sources = sorted({
        str(row.get("source") or "?")
        for _query, rows in query_runs
        for row in rows
    })
    output = []
```

```python
# multi_search_mcp/src/search/search_runner.py:L392-L406
                    source_results = future.result()
                except Exception as exc:
                    with partial_lock:
                        results.extend(partial_results.get(source, []))
                    results.append({"source": source, "error": scrub_secrets(exc, self.config.keys)})
                else:
                    if source_results:
                        results.extend(_attach_provider_ranks(source_results))
                    else:
```

**Paths walked:**

SearchRunner 空返回生成 empty_result_row；_query_provider_status 将无错误空响应置 ok、成功和错误并存置 partial；CLI 在写完 payload 后仅全 error 返回1。探针实测三个退出码1/0/0。

**Searched:**

- `rg -n 'provider_status|succeeded|return 1' multi_search_mcp/cli.py multi_search_mcp/src/service.py multi_search_mcp/src/search/search_runner.py` → 9 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

SearchRunner 空返回生成 empty_result_row；_query_provider_status 将无错误空响应置 ok、成功和错误并存置 partial；CLI 在写完 payload 后仅全 error 返回1。探针实测三个退出码1/0/0。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
