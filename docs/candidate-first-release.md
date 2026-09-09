# 搜索排序与正文获取发布说明

当前契约统一为：搜索取得候选，全部有效排名参与两级 RRF，最终取前 15 条并自动获取正文；已有 URL 直接用 `fetch_source` / `scrape_url`。`search_web` 和 `multi_search` 共用流程，MCP 和 CLI 保留各自的参数及展示入口。本文件沿用原路径，内容描述当前发布契约。

## 新增能力

- `search_web`：返回 RRF 最终前 15 条与正文预览，抓取失败保留结果并显式报告 `body_error`。
- `fetch_source`：按 `source_id` 或显式 URL 抓取单条正文，优先复用缓存。
- `read_source`：只读缓存中的局部正文，支持 `keyword`、`offset`、`limit`，不会隐式联网。
- `multi-search` CLI：`search`、`fetch`、`read`、`doctor`、`keys status`、`keys reset` 直接调用与 MCP 相同的 Core。
- 公共语义：`content` 保留摘要，正文只在 `scrapes[].markdown` 或展示模式的顶层 `markdown` 中出现；`content_kind`、`response_id` / `source_id`、短期 `ContentStore` 和 provider retention 边界继续有效。两级 RRF 保留 `k=40`、默认等权，取消中间窗口。

## 兼容边界

- MCP 不删除；`multi_search` 保留兼容展示，但与 `search_web` 使用相同排序及正文流程，`scrape_url` 继续支持直接 URL。
- 普通查询自动获取最终列表正文；`count` 只控制每源召回，最终最多 15 条。旧 `scrape_top` / `scrape_per_source` 包括 0 在内都不再裁剪或关闭正文抓取，显式传入时 diagnostics 会说明。
- `~/.search-keys.json` 不迁移，环境变量优先级不变。
- `~/.multi-search/state.sqlite` 继续作为共享状态文件；CLI 和 MCP 共用同一路径。
- 两个搜索入口的正文预览默认每篇返回最多 6000 字符；预览限制不截短已取得且允许缓存的正文，`read_source` 可读取预览以外的片段。

## 分阶段迁移

### Phase 1：升级包和 server，不改现有调用

- 升级到包含 `search_web`、`fetch_source`、`read_source` 和 CLI 的版本。
- 保留现有 MCP 配置、keys file、`state.sqlite` 路径和旧调用方。
- 检查既有客户端对结果数量、排序、正文开关和延迟的假设：`multi_search` 现同样执行最终前 15 条正文获取，不能继续依赖旧 `scrape_top=0` 行为。

### Phase 2：切 skill 默认流程

- 普通联网查询默认调用 `search_web`，直接使用摘要和正文预览，需要更多片段时调用 `read_source`。
- route 只用于选源，不作为正文开关；所有 route 都获取最终 RRF 前 15 条。
- 输入已是 URL 时直接 `fetch_source(url=...)` / `scrape_url`，无需先搜索。

### Phase 3：逐步迁移新调用方

- 新的 MCP/CLI 调用优先面向 `SearchHit`、`response_id` / `source_id`、`content_kind` 和 `read_source`。
- 既有调用方读取 `results[].content` 摘要，并按 `source_id` 关联 `scrapes[].markdown`；展示模式读取顶层 `markdown`，避免再以正文长度自行重排结果。
- provider retention policy 只约束缓存与持久化边界，不改变调用入口。

## 回滚路径

### 只调整调用入口

- `search_web` 与 `multi_search` 现在共用流程，仅修改 skill 文案或改用另一个入口不会恢复候选-only、旧排序或 `scrape_top=0` 行为。
- 已知 URL 可调整为直接抓取；要恢复旧搜索契约，必须回退对应代码版本。
- 现有 keys file、`state.sqlite` 和 MCP 配置都不需要处理。

### 回退代码版本

- 先备份当前安装版本和 `~/.multi-search/state.sqlite`，再 pin 到之前的 tag / package 版本。
- 不要为了回滚删除 `~/.search-keys.json` 或 `state.sqlite`。
- 本次 `state.sqlite` 变更是加表式扩展；新增的 `search_sources`、`content_objects`、`content_sources` 可以保留，不要求做反向迁移。
- 离线搜索快照现为 schema 2；旧窗口算法快照不能按当前算法宣称精确重放，版本回退时保留各自算法和快照的匹配关系。

## 发布验证门槛

以下通过后，才算这次统一排序与正文获取发布准备完成：

- 合约测试覆盖：两个搜索入口的 RRF 一致性、第 16 名以后候选进入最终列表、仅最后截取 15 条、抓取顺序与失败隔离、`fetch_source` / `read_source` 缓存与局部读取、URL 安全校验、CLI 共享 Core 契约、旧参数明确诊断。
- 本地 smoke 覆盖：搜索返回 `content` 摘要及单份 Markdown 正文预览；缓存保留已取得的完整正文，`read_source` 能读取预览外片段；直接 URL 抓取不调用 searcher；CLI 和 MCP 指向同一个 `state.sqlite`。
- 文档核对：README、skill、glossary、route/capability 文档对默认 workflow、`content_kind`、`response_id` / `source_id`、ContentStore 生命周期和 retention 边界的表述一致。

## 本说明不声称已验证的内容

- 不声称真实 provider、真实额度、真实 retention 条款或远端部署已经 live 验证。
- 不声称任何生产客户端、第三方 Agent、托管 MCP 平台或外部网络环境已经完成联调。
- 这些部分需要单独做环境级验证，不能用本地合约测试替代。
