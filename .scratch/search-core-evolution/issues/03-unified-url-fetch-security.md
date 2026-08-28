# 03: 统一 URL 抓取安全边界

**What to build:** 为所有按 URL 抓取正文的入口建立同一套默认拒绝的安全策略，先保护现有 `scrape_url`，并让后续 `fetch_source` 直接复用，防止危险协议、内网地址、DNS 解析和重定向形成 SSRF 通道。

**Blocked by:** None (can start immediately).

**Status:** resolved

- [x] 只接受有效的 HTTP/HTTPS 目标，其他协议和无效 URL 在访问网络前明确失败。
- [x] 解析后的 loopback、private、link-local、reserved、multicast 等非公网地址默认被拒绝。
- [x] 域名解析到危险地址时被拒绝，不能通过主机名绕过地址分类。
- [x] 每次 HTTP 重定向后的目标都重新执行同一安全校验。
- [x] 合法公网 URL 仍能进入现有抓取后端，安全失败不会静默切换到绕过校验的备用路径。
- [x] 错误结果提供可诊断但不泄露凭据或敏感网络信息的原因。
- [x] 测试覆盖危险协议、地址类别、DNS 解析和重定向，且不访问真实网络。

## Answer

已在 `f6bb21e` 与 `d6e9732` 完成：统一拒绝危险 URL/DNS/IP，本地 `urllib` 的每个重定向目标重新校验，安全错误不回显私网主机、具体 IP 或敏感 query。远端 Provider 服务内部的跳转属于外部不可观测边界，不作为本地已验证行为。

验证：Python 3.11、3.12、3.14 下全量 261 项测试通过；CLI/MCP smoke、compileall、pip check 与 Standards/Spec 两轴审查通过。
