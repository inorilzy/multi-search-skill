## REQ-09 — 有匹配H1时预览偏移指向原正文标题

> 预览从与结果标题完全匹配的页面一级标题开始
> — README.md:L69

**Verdict:** implemented · confidence: medium

---

**What this demands of an implementation:** 有匹配H1时预览偏移指向原正文标题。以当前陈述为规范，部署计划、未来roadmap和历史例子不升级成硬要求。

**Where enforcement lives:**

```python
# multi_search_mcp/src/support/format.py:L34-L80
def body_preview_start(body: str, title: str, max_chars: int, snippet: str = "") -> int:
    """Locate an exact H1 or quoted snippet without rewriting acquired text.

    Prefer an exact plain/link H1. A sufficiently long verbatim snippet may
    locate a paragraph when no title matches; only whitespace may differ.
    """
    if len(body) <= max_chars:
        return 0
    expected = unescape(title).strip().casefold()
```

```python
# multi_search_mcp/src/service.py:L666-L672
        body = page["markdown"]
        start = body_preview_start(body, hit["title"], max_chars, hit.get("content") or "")
        end = min(len(body), start + max_chars)
        page.update(
            markdown=body[start:end], preview_start=start, preview_end=end,
            truncated=page["truncated"] or start > 0 or end < len(body),
        )
```

**Paths walked:**

正文超过max_chars才定位；扫描跳过围栏code block，识别ATX/Setext及整行链接H1；在service切片并设置原字符偏移、省略前文则truncated。探针位置12且正文不改。实际标题比较会unescape/strip/casefold；文档“完全匹配”未定义大小写归一化，报告不把此实现细节包装为已证bug。

**Searched:**

- `rg -n 'body_preview_start|preview_start|preview_end' multi_search_mcp/src/support/format.py multi_search_mcp/src/service.py` → 4 hits。完整逐行命中记录见本条JSON的searched.matches。
- 逐段阅读了上列源码范围和报告中列明的调用方/失败路径；这不是按函数名判定。

**How the verdict was reached:**

正文超过max_chars才定位；扫描跳过围栏code block，识别ATX/Setext及整行链接H1；在service切片并设置原字符偏移、省略前文则truncated。探针位置12且正文不改。实际标题比较会unescape/strip/casefold；文档“完全匹配”未定义大小写归一化，报告不把此实现细节包装为已证bug。

**Open questions:**

本条范围如上；未声称所有第三方网络行为、全部参数组合或全仓库无缺陷。
