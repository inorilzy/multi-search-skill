# 10: 切换 Skill 默认候选优先流程并完成兼容回归

**What to build:** 更新 Multi-search Skill 与使用文档，使普通联网查询默认执行 `search_web → fetch_source/read_source`，只在用户明确要求深度调研、批量阅读或一次性正文聚合时使用兼容的重型 `multi_search`，并证明 CLI、MCP 和既有调用方没有行为回归。

**Blocked by:** 06: 交付扩展查询两级 RRF 与失败诊断; 08: 交付 read_source 局部读取; 09: 增加共享 Core 的薄 CLI.

**Status:** resolved

- [x] Skill 明确区分候选搜索、单条正文抓取、缓存局部读取和显式深度抓取的使用时机。
- [x] 普通联网查询默认先调用 `search_web`，只对确有价值的候选调用 `fetch_source` 或 `read_source`。
- [x] 深度调研、批量正文和旧工作流仍可显式使用 `multi_search` 与 `scrape_url`。
- [x] CLI 和 MCP 文档描述同一 Core、配置、keys file、StateStore 与 key 状态共享关系。
- [x] 文档说明 `content_kind`、SearchHit、RRF、`response_id/source_id`、Content Store 生命周期和 Provider retention 边界。
- [x] 旧 MCP 参数与主要返回字段继续通过兼容回归测试；新接口没有增加重复正文别名。
- [x] 最终测试覆盖候选搜索无隐式抓取、RRF 确定性、fetch/read 缓存、安全校验、CLI 契约和旧入口兼容。
- [x] 发布说明给出分阶段迁移和回滚路径，不删除 MCP、不要求迁移现有密钥或状态文件。

## Answer

已在 `f6bb21e` 与 `d6e9732` 完成：Skill 默认切换为候选优先流程，保留重型兼容入口，并新增分阶段迁移、发布门槛和回滚说明 `docs/candidate-first-release.md`。

验证：Python 3.11、3.12、3.14 下全量 261 项测试通过；CLI/MCP smoke、compileall、pip check 与 Standards/Spec 两轴审查通过。
