# 01: 恢复 Route 对抓取默认值的控制

**What to build:** 当请求和用户配置没有显式指定抓取深度时，让每个 Route 自己的默认值决定 `count`、`timeout` 和 `scrape_top`，避免仓库共享配置把普通搜索意外变成批量正文抓取；显式配置和旧 `multi_search` 行为继续兼容。

**Blocked by:** None (can start immediately).

**Status:** resolved

- [x] 未提供请求级或用户级覆盖时，运行时使用对应 Route 的默认 `count`、`timeout` 和 `scrape_top`。
- [x] 请求显式值仍具有最高优先级，用户配置的既有优先级和兼容行为不变。
- [x] 仓库随附的共享或开发配置不再通过全局 `scrape_top=30` 覆盖全部 Route。
- [x] 普通或快速 Route 不会仅因共享配置而进入批量抓取；显式深度抓取仍可正常启用。
- [x] 自动化测试覆盖请求值、用户配置、Route 默认值和最终默认值的优先级组合。

## Answer

已在 `f6bb21e` 完成：请求值、用户配置、Route 默认值和最终默认值的优先级恢复为可预测行为，仓库示例配置不再全局强制批量抓取。

验证：Python 3.11、3.12、3.14 下全量 261 项测试通过；CLI/MCP smoke、compileall、pip check 与 Standards/Spec 两轴审查通过。
