# 08: 交付 read_source 局部读取

**What to build:** 让调用方按 `source_id` 从短期 Content Store 局部读取已经抓取的正文，支持关键词定位与分页，并在缓存缺失或过期时明确要求先调用 `fetch_source`，绝不因读取操作隐式联网。

**Blocked by:** 07: 交付 Content Store 与 fetch_source.

**Status:** resolved

- [x] `read_source` 通过共享 Core 和 MCP 按 `source_id` 读取正文，且只访问 Content Store。
- [x] 支持关键词、offset 和 limit，并对每次返回设置不可绕过的硬字符上限。
- [x] 关键词命中时返回可继续分页的稳定位置；关键词缺失时返回明确结果，不退化为整页输出。
- [x] offset 或 limit 超出边界时行为稳定、可诊断，不产生负索引或无限输出。
- [x] 缓存不存在或已过期时明确失败并提示调用 `fetch_source`，不会自动访问网络。
- [x] 读取会更新必要的 LRU 访问状态，但不会延长超出 Provider retention policy 的留存期限。
- [x] 支持清理过期内容和按 source 删除缓存，删除后无法继续读取旧正文。
- [x] 测试覆盖关键词命中与缺失、分页、字符上限、缓存缺失、缓存过期、删除和重复读取。

## Answer

已在 `f6bb21e` 与 `d6e9732` 完成：`read_source` 保持 cache-only，支持稳定关键词分页与硬上限；通过可控时钟覆盖过期、删除、重复读取和 LRU，且不延长 retention 到期时间。

验证：Python 3.11、3.12、3.14 下全量 261 项测试通过；CLI/MCP smoke、compileall、pip check 与 Standards/Spec 两轴审查通过。
