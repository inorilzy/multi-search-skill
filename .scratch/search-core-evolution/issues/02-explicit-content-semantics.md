# 02: 统一内容语义与 Provider Capability

**What to build:** 让所有默认搜索 Provider 用明确的 `content_kind` 描述其返回内容，并让运行时根据 Provider Capability 与内容类型判断正文是否已存在，消除依赖来源名称、字段别名或字符长度猜测正文的行为，同时保留旧结果字段兼容性。

**Blocked by:** None (can start immediately).

**Status:** resolved

- [x] 领域词汇明确包含 `metadata`、`content`、`excerpt`、`body` 和 `answer`，且公共说明与运行时含义一致。
- [x] 默认 Web Provider 的结果都经过显式内容分类；highlight 或摘要归为 `excerpt`，真正预取的网页正文才归为 `body`。
- [x] Exa 风格 highlights 不再被视为正文，也不会阻止后续显式抓取完整页面。
- [x] Provider 已提供真正 `body` 时，正文可被复用且不会触发重复抓取。
- [x] Scrape Planner 使用 Capability 与 `content_kind` 做决策，不再依赖 300 字符阈值或 Provider 名称硬编码。
- [x] 旧 `description`、`scraped_content` 等兼容字段继续工作，但新增逻辑不再依赖这些字段推断内容类型。
- [x] 契约测试覆盖各默认 Provider，并在 Capability 声明与实际解析行为漂移时失败。

## Answer

已在 `f6bb21e` 完成：默认 Provider 显式输出 `content_kind`，Capability 驱动正文复用与 Scrape Planner 决策，旧内容字段保持兼容。

验证：Python 3.11、3.12、3.14 下全量 261 项测试通过；CLI/MCP smoke、compileall、pip check 与 Standards/Spec 两轴审查通过。
