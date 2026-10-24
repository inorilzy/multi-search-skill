## `urlopen_retry` in multi_search_mcp/src/support/http.py (L175-L212)

**Purpose:** 为 SSL 重试、redirect、socket 读取传递同一相对调用预算。

---

**Inputs & Assumptions:**

- Request/url：由本轮固定 API endpoint 的 provider 创建，fetch 目标的本地预检在 service.py L206；timeout 来自剩余时间，retries 默认 2（L178）。
- 前提：response read 执行预算检查；enforcement：support/http.py L76-L78、L89、L53-L66。
- 前提：redirect 检查全部解析 IP；enforcement：support/http.py L139；url_security.py L52-L59。

---

**Outputs & Effects:**

打开网络连接并返回 HTTPResponse 协议；非 SSL 类 OSError 立即传播，SSL 类重试耗尽抛 last_exc（L200-L212）。

---

**Block-by-Block:**

```python
# L187-L202
deadline = time.monotonic() + timeout
request._multi_search_deadline = deadline
...
return opener.open(request, timeout=_remaining(deadline))
```

- **What:** 只建立一次 deadline，每次 open 重新取剩余值。
- **Why here:** SSL 重试不重置预算。
- **Assumes:** response 必须使用 deadline-aware handler；_build_safe_opener L163-L167。
- **Establishes:** readinto 每次 socket read 前后检查；L53-L66。
- **Depended on by:** provider 的 resp.read()。

```python
# L203-L212
except (ssl.SSLEOFError, ssl.SSLError) as e:
    last_exc = e
    continue
except OSError as e:
    ...
    raise
```

- **What:** 限定网络重试类别，其他错误传播。
- **Why here:** 调用者区分失败由更上层负责。
- **Assumes:** 标准库连接、TLS、代理与 resolver 行为，非本仓库控制。
- **Establishes:** redirect 不会重置 deadline，敏感 header 跨 origin 被拒绝；L137-L155。
- **Depended on by:** Brave/Exa 的异常投影。

---

**Cross-Function Dependencies:**

- `_remaining/_build_safe_opener/_open_with_deadline` (internal)：remaining<=0 抛错；创建连接/响应 handler 保留 deadline；http.py L32-L36、L81-L129、L158-L168。
- `_SafeHTTPRedirectHandler.redirect_request` (internal)：校验新 URL/origin/credentials，并在错误时关闭 fp；L137-L155。
- `urllib/http.client/socket/TLS` (external-black-box)：运行库未逐函数分析；本轮不把 Python 的 DNS/代理/TLS 行为当成完成验证。
- Callers: searchers/brave.py L36；scrapers/exa.py L33；其余调用者 inventory-only
- Shared state: _shared_opener 为进程共享且 install_opener；http.py L171-L172
- Invariant coupling: SSL 重试及重定向沿用原 deadline (http.py L147-L151、L187-L202)
- Invariant coupling: 带凭据的跨 origin redirect 与 HTTPS 降级被拒绝 (http.py L139-L145)

---

**Open Questions:**

- unclear; need to inspect 目标 Python socket DNS、代理 CONNECT 与 TLS 在该运行环境的计时边界；本轮不声称硬实时超时。
