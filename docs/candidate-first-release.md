# 搜索排序与正文获取发布说明

发布版本：`0.3.3`（[版本源码](https://github.com/inorilzy/multi-search-skill/tree/v0.3.3)）。本版本包含下述默认搜索行为变化；实际客户端联调需分别验证。

当前契约统一为：搜索取得候选，全部有效排名参与两级 RRF，最终取前 15 条并自动获取正文；已有 URL 直接用 `fetch_source` / `scrape_url`。`search_web` 和 `multi_search` 共用流程，MCP 和 CLI 保留各自的参数及展示入口。本文件沿用原路径，内容描述当前发布契约。

## 0.3.3 修复

- SerpAPI 分页共享搜索截止时间，超时停止后续请求并保留已取得结果；单次 HTTP 请求仍最多 20 秒。
- 显式指定抓取后端顺序时保留调用方顺序，默认 Jina 不再抢占首位。
- GitHub 仓库根 URL 保持原样，不再猜测根目录 README.md 路径。
- MCP 工具描述与 Skill 的无固定来源配额、按需全文读取策略一致。

## 0.3.2 Skill 更新

- 明确子代理粗筛与主 Agent 最终判断的职责，保留候选原始预览。
- 精简 Skill 入口，将搜索、委派、验证与 CLI 细节放入按需参考文件。
- 委派失败明确报错，后续搜索继承预算和停止计数。Core 排序及抓取接口不变。
- 已验证 Codex 子代理搜索及共享来源读取；最新无数量配额的交接规则通过静态检查，尚未重跑端到端测试。Pi 尚未实测。

## 已有能力

- `search_web`：返回 RRF 最终前 15 条与正文预览，抓取失败保留结果并显式报告 `body_error`。
- `fetch_source`：按 `source_id` 或显式 URL 抓取单条正文，优先复用缓存；`full_content=True` 覆盖 `max_chars`，一次返回全部已取得文本。
- `read_source`：只读缓存中的局部正文，支持 `keyword`、`offset`、`limit`，用于定向查证，不会隐式联网。
- `multi-search` CLI：`search`、`fetch`、`read`、`doctor`、`keys status`、`keys reset` 直接调用与 MCP 相同的 Core；`fetch --full-content` 对应全文读取。
- 公共语义：`content` 保留摘要，正文只在 `scrapes[].markdown` 或展示模式的顶层 `markdown` 中出现；`content_kind`、`response_id` / `source_id`、短期 `ContentStore` 和 provider retention 边界继续有效。两级 RRF 保留 `k=40`、默认等权，取消中间窗口。

## 兼容边界

- MCP 不删除；`multi_search` 保留兼容展示，但与 `search_web` 使用相同排序及正文流程，`scrape_url` 继续支持直接 URL。
- 普通查询自动获取最终列表正文；`count` 只控制每源召回，最终最多 15 条。旧 `scrape_top` / `scrape_per_source` 包括 0 在内都不再裁剪或关闭正文抓取，显式传入时 diagnostics 会说明。
- `~/.search-keys.json` 不迁移，环境变量优先级不变。
- `~/.multi-search/state.sqlite` 继续作为共享状态文件；CLI 和 MCP 共用同一路径。
- 两个搜索入口的正文预览默认最多 1200 字符；需要截断时，从与结果标题完全匹配的页面一级标题开始，没有匹配标题时可定位逐字匹配完整摘要的段落（至少 32 个非空白字符，仅允许空白差异），仍无匹配则从开头开始。`preview_start/end` 标注原文字符区间；完整正文和缓存不变。
- `fetch_source.full_content` 默认 `False`，保留现有 `max_chars` 行为（默认 20000，显式值限制在 1–20000）。全文仅指后端实际取得文本，Reddit 包括已加载评论，不扩展未加载评论；现有抓取、缓存容量、TTL 和 retention 限制继续生效。

## 分阶段迁移

### Phase 1：升级包和 server，不改现有调用

- 升级到包含 `search_web`、`fetch_source`、`read_source` 和 CLI 的版本。
- 保留现有 MCP 配置、keys file、`state.sqlite` 路径和旧调用方。
- 检查既有客户端对结果数量、排序、正文开关和延迟的假设：`multi_search` 现同样执行最终前 15 条正文获取，不能继续依赖旧 `scrape_top=0` 行为。

### Phase 2：切 skill 默认流程

- 普通联网查询由宿主配置的轻量子代理执行搜索，只排除明确无关项。其余候选（包括不确定项）按原顺序连同每篇最多 1200 字符的原始预览交给主 Agent，不设保留数量配额；主 Agent 最终筛选并按需调用 `fetch_source(source_id=..., full_content=True)` 读取全文。无子代理能力或用户要求直接执行时，由主 Agent 执行同一流程。
- 选读由调用工具的 Agent 完成，Core 继续获取 RRF 最终 15 条并按策略缓存；不增加服务端 AI 选择器、摘要或智能摘录。`read_source` 保留用于定向查证。
- 保留 `body_error` 和每次读取错误。缓存缺失或过期但 `source_id` 有效时，`fetch_source(source_id=..., full_content=True)` 按原 ID 重新抓取；只有 ID 本身未知或失效时，才按已观察到的 URL 显式 `fetch_source(url=..., full_content=True)`，使用返回的新 `source_id`。
- route 只用于选源，不作为正文开关；所有 route 都获取最终 RRF 前 15 条。
- 输入已是 URL 时直接 `fetch_source(url=..., full_content=True)` / `scrape_url`，无需先搜索。

### Phase 3：逐步迁移新调用方

- 新的 MCP/CLI 调用优先面向 `SearchHit`、`response_id` / `source_id`、`content_kind` 和 `fetch_source(full_content=True)`；`read_source` 用于定向查证。
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
- 本次 `state.sqlite` 变更是加表、加列式扩展；新增的 `search_sources`、`content_objects`、`content_sources` 及正文关联的 `canonical_url/cache_scope` 列可以保留，不要求做反向迁移。旧的无 scope 正文仍按原 ID 读取。
- 离线搜索快照现为 schema 2；旧窗口算法快照不能按当前算法宣称精确重放，版本回退时保留各自算法和快照的匹配关系。

## 发布验证门槛

以下通过后，才算这次统一排序与正文获取发布准备完成：

- 合约测试覆盖：两个搜索入口的 RRF 一致性、第 16 名以后候选进入最终列表、仅最后截取 15 条、抓取顺序与失败隔离、`fetch_source` 全文与默认/显式预览的兼容、缓存与 `read_source` 局部读取、URL 安全校验、CLI `--full-content` 共享 Core 契约、旧参数明确诊断。
- 本地 smoke 覆盖：搜索返回 `content` 摘要及单份最多 1200 字符的 Markdown 正文预览；选读来源通过 `fetch_source(full_content=True)` 一次返回已取得全文，缓存与 fresh fetch 均覆盖，`read_source` 可定向读取预览外片段；直接 URL 抓取不调用 searcher；CLI 和 MCP 指向同一个 `state.sqlite`。
- 文档核对：README、skill、glossary、route/capability 文档对默认 workflow、`content_kind`、`response_id` / `source_id`、ContentStore 生命周期和 retention 边界的表述一致。
- 安装边界：非 editable、未使用开发锁文件的安装运行 `scripts/smoke_install.py`，验证仓库外两个 console scripts 和 MCP 握手/工具调用；`scripts/run_tests.py` 覆盖总预算、部分失败、缓存并发和URL跨响应复用。

2026-09-10 审查问题的修复与验收记录见 [audit-fixes-2026-09-10.md](audit-fixes-2026-09-10.md)。CLI 全源失败及 doctor 诊断失败现在退出 `1`；正常零匹配或部分搜索成功仍为 `0`，调用脚本应检查返回码和结构化错误。

## 本说明不声称已验证的内容

- 13 个 provider 已逐一实际调用，11 个搜索成功，Twitter 超时、LinuxDo 403；见 [最终验收](provider-acceptance-2026-09-10.md)。这不代表全部查询、持续可用性、真实 retention 条款或远端部署已经验证。
- 不声称任何生产客户端、第三方 Agent、托管 MCP 平台或外部网络环境已经完成联调。
- 这些部分需要单独做环境级验证，不能用本地合约测试替代。

## 0.3.0 本机 CLI 验证（2026-09-09）

- `uv run --locked` 已将项目环境同步到 `multi-search-mcp==0.3.0`；锁文件检查和 0.3.0 Wheel 构建通过。
- `test_cli`、`test_full_content_interfaces`、`test_full_content_flow`、`test_preview_defaults` 共 26 项通过，测试使用临时 SQLite 状态库。
- 真实运行 `uv run --locked multi-search search "SQLite" --source hackernews --count 3 --timeout 30 --format json`：9.88 秒返回 3 条结果与 3 份各 1200 字符的正文预览，errors 为空。
- 在独立 CLI 进程中按返回的 `source_id` 执行 `fetch --full-content`：缓存命中，返回 13273 字符，`truncated=false`；随后 `read --offset 1200 --limit 200` 成功读取 200 字符。该 smoke 验证本机搜索、正文和跨进程缓存链路，不代表全部来源或真实 Agent 引用质量已通过。
