# 仓库卫生复核台账

范围：原审查第五部分及相关 CI/依赖建议。按本轮安全边界，不删除本地产物、历史资料或已跟踪需求，不提交。测试和实现结论分开记录。

| 项目 | 处置 | 证据 / 边界 |
|---|---|---|
| README 已删除入口引用 | 已修正 | 删除不存在的请求适配器和旧标记脚本引用；模块划分更新到 Core facade 与 core/search/scrape/state/support。 |
| glossary 代码出处与来源语义 | 已修正 | 使用仓库相对路径及真实函数名；SQLite 为默认配置和凭据权威，JSON 仅显式兼容输入；通用后端与平台专用适配器分开描述。 |
| build、根缓存、egg-info | 保留；待确认是否清理 | `git ls-files build/ __pycache__/ multi_search_mcp.egg-info/` 无结果；`git check-ignore -v` 确认均已忽略。旧产物不是当前实现依据。 |
| scratch | 保留；待确认是否移出索引 | 实测 11 个已跟踪文件均为 search-core-evolution 需求/规格，不能当无价值缓存删除；不执行 `git rm --cached`。未跟踪内容已有忽略规则。 |
| zvec-grep | 已修正 | 新增 `.zvec-grep/` 忽略规则；保留本地数据。 |
| 历史文档状态 | 已修正 | 新增 [文档索引](README.md)，按当前树枚举历史文档，保留全部原路径；[交接文档](../HANDOFF-SCRAPE-CHAIN.md) 仅顶部状态有效，旧记录折叠。 |
| 包名和 src 布局 | 兼容保留 | README 开头说明历史命名，不进行破坏导入、安装和脚本的重命名。 |
| beautifulsoup4 | 已移除直接声明 | 产品源码与测试无 bs4/BeautifulSoup 引用；重新生成锁文件。仍可能由 xkit-py 间接依赖，不能手动删除传递依赖。 |
| pytest | 不适用，不强制引入 | 项目 runner 使用标准库 unittest，源码与测试未使用 pytest；README 明确 runner，不虚构开发依赖需求。 |
| happy-dom | 原报告已过时 | desktop/package.json 已声明 happy-dom 开发依赖；UI 组拥有 package 文件。新增 CI 使用 npm ci 安装锁定开发依赖。 |
| CI 锁定安装 | 已补充 | 保留原非锁、非 editable 安装兼容矩阵；新增 Windows/Linux × Python 3.10/3.14 的 uv 锁定回归矩阵及前端测试/typecheck。远程 CI 尚未运行。xkit Git URL 的在线可达性未在本轮验证，不预设私有或鉴权要求。 |
| 配置样例 | 复核后保留 | count=10、timeout=60、scrape_chars=1200、scrape_timeout=60、scrape_concurrency=5 与 resolve 默认一致；scrape_top/no_scrape/scrape_per_source 仍被兼容解析，不宣称已删除。样例不隐式加载；degrade_to 本来不在样例中。 |
| 新增 mark-exhausted | 不实施 | 不增加未请求产品功能或把 key 暴露到 argv；删除失效说明，保留现有桌面凭据管理与 keys reset。 |
| ts-rs 正式依赖、申请链接 | 由 Rust 任务处理 | 非本任务所有权；以 Rust 组处置和独立验收台账为准。 |

## 本任务验证

- `uv lock --offline`、`uv lock --check --offline`：成功；锁文件只移除项目对 beautifulsoup4 的直接依赖边。
- `python scripts/check_glossary_paths.py`：校验 glossary 所有出处文件存在，并校验 README、glossary、索引内的本地链接。
- 新脚本正反例验证通过：缺失出处/链接均报错，补齐目标后通过。脚本使用标准库，无需新增测试框架；CI 在非锁和锁定 Python 矩阵均执行该检查。
- `uv run --no-project --with pyyaml` 解析 CI YAML 并断言三类任务与安装命令：通过。未运行远程 Actions。
- 原有未跟踪 round3 / skill-comparison 资料只列为本地可选路径，不纳入 CI 必需链接或自动加入版本控制。
- 共享工作树存在其他任务修改和原有未跟踪审计资料；不以删除它们或自行提交来伪造“git status 干净”。
- 补充忽略 `.agent-teams/` 团队运行时状态；不纳入版本控制。

## glossary 语义依据与待集成复核

首次同步是在 Python 任务并行修改期间完成，**不是对 Python 本轮最终实现的语义验收**。本轮仓库 HEAD 为 `c035da15e6113be84e4634ce28d1a591178c1fb6`；读取工作树时没有固定文件快照，因此不能把所有内容归因到该提交。

- Core 路径与函数名映射：实际读取 [service facade](../multi_search_mcp/src/service.py)，并枚举 [core](../multi_search_mcp/src/core/) 中定义；抓取实现出处改为 [scrape_pipeline](../multi_search_mcp/src/core/scrape_pipeline.py) 的 `run_scrape_raw`，不是旧 facade 私有函数。
- 配置/凭据语义：实际读取 [config](../multi_search_mcp/src/support/config.py)、[keys](../multi_search_mcp/src/state/keys.py) 的默认与显式兼容输入分支；据此纠正 SQLite 权威来源和 Jina 静态 exhausted 描述。
- key 状态转换与抓取错误分类：主要**保留原 glossary 的既有描述**，仅重映射出处；当时未逐条复核 [key_state](../multi_search_mcp/src/state/key_state.py)、[models](../multi_search_mcp/src/support/models.py) 和 [scrape orchestration](../multi_search_mcp/src/scrape/scrape.py) 的最终行为。尤其“成功写回 active”“invalid_strikes 清零”“target 中立事件”须在 Python 完成后重新核对；不能视为已与本轮并发状态保护修改同步。
- site memory 排序：实际读取 [site_memory](../multi_search_mcp/src/state/site_memory.py) 的 `reorder_backends`，纠正为 pin、配置顺序与冷却，而非历史成功率。
- 抓取后端数量：按当前通用链与平台适配器划分为四个通用后端及 Reddit、Twitter/X 专用适配器；数量纠正不等同于已验证本轮错误处理行为。

补记时 `git status` 显示 key_state 与 scrape orchestration 正有未提交修改。最终独立验收应等待 Python 任务完成，再由文档维护者据其最终实现/测试修订 glossary 与 README 对应语义，并补充验证证据。
