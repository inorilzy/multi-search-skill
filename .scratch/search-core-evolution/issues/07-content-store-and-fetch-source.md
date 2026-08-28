# 07: 交付 Content Store 与 fetch_source

**What to build:** 让调用方可以用搜索得到的 `source_id` 或显式公网 URL 只抓取一条正文，并在 Provider 留存策略允许时写入受限的短期 Content Store；已有且未过期的正文优先复用，不重复抓取。

**Blocked by:** 02: 统一内容语义与 Provider Capability; 03: 统一 URL 抓取安全边界; 04: 交付紧凑 search_web 与 Source Registry.

**Status:** resolved

- [x] `fetch_source` 通过共享 Core 和 MCP 接受有效 `source_id` 或显式 URL，并返回有硬字符上限的单条正文结果。
- [x] 有未过期缓存时直接复用；没有缓存时调用现有抓取后端链，并记录实际 backend 与抓取时间。
- [x] Provider 搜索阶段已提供真正 `body` 时可复用该正文；`excerpt` 不得冒充正文缓存。
- [x] Content Store 具备短期 TTL、单对象大小上限、总容量上限、LRU 清理、内容 hash 去重和按 source 删除能力。
- [x] 搜索结果、content 和 body 是否持久化及最大 TTL 由 Provider retention policy 决定；未知策略采用短期、最小留存。
- [x] 禁止持久化的正文不会写入持久层，但在策略允许的当前调用内仍可使用。
- [x] URL 抓取和所有重定向复用 Ticket 03 的统一安全策略，没有旁路。
- [x] 返回正文始终标记为不可信外部数据，网页内容不能改变工具参数、配置、密钥或状态操作。
- [x] 即使正文已缓存，`search_web` 也只返回 `body_available` 和内容引用，不返回正文大文本。
- [x] 测试使用临时存储、可控时钟和假的抓取后端，不读取用户密钥或访问真实 Provider。

## Answer

已在 `f6bb21e` 与 `d6e9732` 完成：交付单条 `fetch_source`、受限 Content Store、TTL/容量/LRU/hash 去重、retention policy、正文复用和统一 URL/重定向安全边界。

验证：Python 3.11、3.12、3.14 下全量 261 项测试通过；CLI/MCP smoke、compileall、pip check 与 Standards/Spec 两轴审查通过。
