# 旧抓取链清理 · 2026-09-12

Ticket 09，基于 `b429580`。本记录对应本分支实现；带日期的历史审查报告保留原语境。

## 调用方核对与删除边界

删除前逐项核对仓库 Python 引用、README、CLI/MCP schema 和测试。公共入口由 `multi_search_mcp/cli.py`、`server.py`、`tools.py` 提供；没有公开导出旧 planner/stage/helper 的承诺。README 原先把 planner 列为现行 backend 选择者，已修正。

| 代码 | 删除前调用者 | 处理依据 |
|---|---|---|
| `scrape/stage.run_scrape_stage`、`_backfill_scrape_title` | `service.py` 未使用的导入，以及旧 stage 测试 | 删除旧阶段及其内部标题回填。现行搜索正文展示直接使用候选标题 |
| `scrape/scrape_planner.py` | 旧 stage 与 planner 专属测试 | 整模块删除，包括配额、video 排除、primary/key 轮换、旧正文池 |
| `support/dedup` 的 `deduplicate`、`split_by_content`、`result_to_scrape`、`apply_scraped_content` 及专属辅助函数 | 旧 planner/stage 与测试 | 删除旧去重、正文分流和正文回写；现行搜索使用共享 RRF 与 `run_fetch_source` |
| `capabilities.infer_content_kind`、`content_kind_blocks_scrape` 及专属 import | 旧 `dedup` | 删除无现行调用的旧分类/抓取判断；保留 `ScrapePolicy`、能力表和现行 `models.search_content` |
| `service._limit_scrape_rows`、`_provider_status`、`_add_public_content_aliases`、`_strip_public_body_fields` | 仅定义 | 删除；当前投影、状态汇总由其他现行函数负责 |
| `service._valid_result_count` | 一条旧 helper 测试 | 删除 helper，把状态行不计入结果的断言迁至 `run_multi_search` |
| `support/dedup.rank_results`、`consensus_weight` | `support/format.py` | 保留原实现，包含 RRF 排序和非 RRF 展示行为 |
| `dedup._norm_url`、`service.COUNT_CAPS/DEFAULT_COUNTS` | 已有重导出与测试 | 保留兼容重导出及其实际定义，不扩大接口删除范围 |

## 当前生产路径

- CLI `search`、MCP `search_web` → `run_search_web` → `_run_search_candidates` → `fuse_search_results` → 最终最多 15 条 → `run_ranked_fetch_stage` → `run_fetch_source`。
- MCP `multi_search` → `run_multi_search` → 同一个 `run_search_web`；兼容入口仅添加 summaries、display_results、Markdown 和诊断展示。
- `run_fetch_source` 复用可用正文/缓存，否则进入 `_run_scrape_raw` → `scrape_url_smart`。共享 key manager 提供候选 key，scraper 维护 backend 顺序、key 尝试与站点记忆。
- `run_ranked_fetch_stage` 保留有界线程池、共享 deadline 和按输入顺序收集结果；不包含 planner 导入或第二次候选配额筛选。

CLI/MCP 入口与 schema 未改。`MultiSearchRequest.scrape_top/scrape_per_source`、MCP `scrape_top` 及 `legacy_scrape_limits` 忽略说明保留，最终 RRF 最多 15 条仍全部进入正文获取。成功/失败响应、格式化、SourceRegistry、ContentStore、key 状态和站点记忆保持；未改变正文选择或 Unicode 读取语义。

`docs/current-architecture.*` 由 Ticket 10 统一同步；需移除旧独立重型路径及 planner/正文回写节点，使用上述已落地调用边。

## 回归迁移

- `test_package_identity` 新增公共入口不加载废弃 planner 的回归：删除前实际失败，删除后通过。
- `test_content_semantics` 原四组 planner/writeback 公共断言迁到真实 `run_search_web`：长摘要仍抓取、短正文复用、重复 URL 正文复用，以及摘要/正文与缓存分离。预取复用覆盖有状态和无状态。
- `test_concurrency_lifecycle` 保留连续六次超时、线程数受限的断言，改为现行 `run_ranked_fetch_stage`。
- `test_mcp_architecture` 的状态行不计入有效结果改经真实 `run_multi_search` 验证；保留全部格式化与排序测试。
- `test_search_fetch_pipeline` 验证业务参数 URL 不合并、tracking alias 合并且来源追踪保留、搜索标题及配置超时，以及 answer/video 候选仍进入最终获取。已有测试继续验证最终 15 条、兼容参数忽略、CLI/MCP 成功/失败输出、完整缓存和 retention。
- 无 key 时默认先 Jina、失败后尝试匿名 Firecrawl 的公开顺序，从旧 planner 测试迁至 `run_search_web` → 真实 `scrape_url_smart`，仅模拟 backend 响应。
- 删除仅针对旧 quota、video 排除、skip-summarized、轮换 primary、旧 canonical-source 选择、plan-items 完成条件和旧正文回写对象结构的测试。它们描述的是已退出公共入口的内部实现；未将这些规则重新引入现行流程。

## 验证结果

解释器：`D:\0-code-project\multi-search-skill\.venv\Scripts\python.exe`；从独立 worktree cwd 执行并断言 `service.__file__` 位于本 worktree。

| 验证 | 结果 |
|---|---|
| `-m unittest test_package_identity.PackageIdentityTests.test_public_entrypoints_do_not_load_retired_scrape_planner` | 删除前失败：公共入口加载了 planner；删除后通过 |
| `-m unittest test_package_identity test_mcp_core test_mcp_architecture test_search_fetch_pipeline test_ranked_fetch_stage` | 152 项通过；后续新增匿名 backend 顺序测试单独通过 |
| `scripts/run_tests.py` | 最终 462 项通过，24.138 秒，临时 SQLite |
| 非 editable 安装后 `scripts/smoke_install.py` | CLI help、fetch help、MCP stdio 握手/list_sources 通过；模块路径确认为临时安装的 `site-packages`，12 个工具注册 |
| `git diff --check` | 通过 |

相对基线 475 项：移除 18 条直接依赖旧实现的测试函数，其中仍适用的公共断言纳入现行入口回归；新增 5 条，另原位迁移 6 条已有测试并保留原断言目的。安装使用 worktree 内 `.scratch/audit-09-install` 和独立 uv 缓存，离线构建并非 editable 安装；运行依赖只读复用已装版本（Python 3.13.13 / MCP 1.30.0），未修改主目录环境。

测试只使用模拟网络和临时 SQLite，不读取真实 keys 或调用付费 API。本轮没有重装全套依赖、执行 Linux/Python 3.10/3.14 矩阵或验证线上 provider 可用性。
