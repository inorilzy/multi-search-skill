# Candidate-First 发布说明

这次发布是兼容性新增，不是入口替换。目标是把普通联网查询的默认工作流切到候选优先：先 `search_web`，再按需 `fetch_source` / `read_source`；同时保留现有 MCP、`multi_search` 和 `scrape_url`。

## 新增能力

- `search_web`：只返回紧凑 `SearchHit` 候选，不隐式批量抓正文。
- `fetch_source`：按 `source_id` 或显式 URL 抓取单条正文，优先复用缓存。
- `read_source`：只读缓存中的局部正文，支持 `keyword`、`offset`、`limit`，不会隐式联网。
- `multi-search` CLI：`search`、`fetch`、`read`、`doctor`、`keys status`、`keys reset` 直接调用与 MCP 相同的 Core。
- 新公共语义：`content_kind`、`response_id` / `source_id`、provider/query 两级 RRF、短期 `ContentStore`、provider retention 边界。

## 兼容边界

- MCP 不删除；`multi_search` 和 `scrape_url` 继续保留给既有调用方和显式深度抓取。
- 普通查询的默认 skill/workflow 改为候选优先，但“深度调研 / 批量正文 / 一次性聚合正文”仍应显式调用 `multi_search(scrape_top=N)`。
- `~/.search-keys.json` 不迁移，环境变量优先级不变。
- `~/.multi-search/state.sqlite` 继续作为共享状态文件；CLI 和 MCP 共用同一路径。
- `search_web` 不新增重复正文别名；正文读取由 `fetch_source` / `read_source` 显式表达。

## 分阶段迁移

### Phase 1：升级包和 server，不改现有调用

- 升级到包含 `search_web`、`fetch_source`、`read_source` 和 CLI 的版本。
- 保留现有 MCP 配置、keys file、`state.sqlite` 路径和旧调用方。
- 如果现有客户端依赖 `multi_search` 或 `scrape_url`，先不改，确认兼容测试通过即可。

### Phase 2：切 skill 默认流程

- 普通联网查询默认改为 `search_web -> fetch_source/read_source`。
- 只对有价值的少量 `source_id` 抓正文，不把 route 当成“是否抓正文”的控制开关。
- 需要旧的一次性重型工作流时，明确写出 `multi_search(scrape_top=N)`。

### Phase 3：逐步迁移新调用方

- 新的 MCP/CLI 调用优先面向 `SearchHit`、`response_id` / `source_id`、`content_kind` 和 `read_source`。
- 既有调用方只在确实需要更小响应、更清晰证据链或 CLI 自动化时再迁移。
- provider retention policy 只约束缓存与持久化边界，不改变调用入口。

## 回滚路径

### 只回滚默认工作流，不回滚代码

- 优先恢复 skill 文案，让普通查询重新显式走 `multi_search`。
- 这种回滚不需要删除新接口；`search_web`、`fetch_source`、`read_source` 和 CLI 可以继续保留在安装包里。
- 现有 keys file、`state.sqlite` 和 MCP 配置都不需要处理。

### 回退代码版本

- 先备份当前安装版本和 `~/.multi-search/state.sqlite`，再 pin 到之前的 tag / package 版本。
- 不要为了回滚删除 `~/.search-keys.json` 或 `state.sqlite`。
- 本次 `state.sqlite` 变更是加表式扩展；新增的 `search_sources`、`content_objects`、`content_sources` 可以保留，不要求做反向迁移。
- 如果旧版本只需要恢复单次重型搜索行为，优先回滚 skill 或客户端调用方式，再考虑整体代码回退。

## 发布验证门槛

以下通过后，才算这次候选优先发布准备完成：

- 合约测试覆盖：`search_web` 无隐式抓取、单 query RRF 确定性、扩展查询两级 RRF、`fetch_source` / `read_source` 缓存与局部读取、URL 安全校验、CLI 共享 Core 契约、`multi_search` / `scrape_url` 兼容回归。
- 本地 smoke 覆盖：`search_web` 返回紧凑候选且不带正文别名；随后 `fetch_source` 能写入缓存，`read_source` 能按关键词或偏移读取；显式 `multi_search(scrape_top=N)` 仍可走旧工作流；CLI 和 MCP 指向同一个 `state.sqlite`。
- 文档核对：README、skill、glossary、route/capability 文档对默认 workflow、`content_kind`、`response_id` / `source_id`、ContentStore 生命周期和 retention 边界的表述一致。

## 本说明不声称已验证的内容

- 不声称真实 provider、真实额度、真实 retention 条款或远端部署已经 live 验证。
- 不声称任何生产客户端、第三方 Agent、托管 MCP 平台或外部网络环境已经完成联调。
- 这些部分需要单独做环境级验证，不能用本地合约测试替代。
