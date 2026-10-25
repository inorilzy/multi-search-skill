# 独立阶段验收：review-2026-10-22

## 结论与快照边界

**不建议宣布全部问题修复完成。** 本次为 t5 阶段审查，发现两项确定的跨语言回归（IV-01、IV-02）；现有分语言测试全部通过却未覆盖它们。captain 已交 t11 修复，最终必须重新独立验证。

- 比较基线：`c035da15e6113be84e4634ce28d1a591178c1fb6`。
- 启动时 HEAD：`5c2de01ccb33a7598937d71fbd6b1d0d2c41570c`；包含 `fbae887` 文档/CI、`654a5df` CSS、`5c2de01` 前端检查点及未提交 Rust/Python 改动。
- 时间：2026-10-23 00:52 起（America/Guatemala）。工作树不是冻结快照。启动后 captain 明确改为阶段审查，t11/t12/t13 已并行实施；不将阶段测试结果归因到结束时所有文件，也不重跑活动树最终验收。
- 只写本报告，未修改实现、真实配置、凭据、PATH、安装，未 commit/push。
- 已加载 audit-context-building、ponytail。上下文映射委派被团队成员 delegation limit=0 拒绝；已报告 captain，改为本地读取边界相关源文件。

## 独立运行结果

| 命令 | 实际结果 | 限制 |
|---|---|---|
| `.venv/Scripts/python.exe scripts/run_tests.py` | exit 0；837 tests，5 skipped，80.193s | runner 在 discovery 前建立临时配置/状态及外网拦截；不是后续 t12 完成态 |
| `npm --prefix desktop test` | exit 0；129 passed，0 skipped/failed，2431.6419ms | happy-dom，不验证真实排版/读屏/原生 IPC |
| `npm --prefix desktop run typecheck` | exit 0 | 使用现有 checkJs:true 配置；非 strict 全类型证明 |
| `cargo test --no-default-features` | exit 0；16 lib + 2 release-boundary = 18 passed | feature 门控使该命令不再代表全部测试 |
| `cargo test --no-default-features --features test-fixtures,ts` | exit 0；165 passed，3 ignored | 2 个真实 installed_cli 验收、1 个类型生成 ignored；未含 install/install_lifecycle、native-window |
| 测试名基线核对 Python 脚本 | 首次 exit 1（Windows 默认 GBK 解码 git UTF-8 失败），显式 encoding=utf8 后 exit 0 | 工具脚本错误，不是产品失败 |

后台任务均已收集：`pwsh-076134c8cac14cec`、`pwsh-69d28b20bc024e9a`、`pwsh-822418976c0f4498`。

没有在阶段任务新增运行 native overlay/default check、install-test-boundary 或真实浏览器，避免把活动树当最终版本。依赖报告中的 overlay 204 passed/4 ignored、原生编译成功、默认资源缺失等是**实施者证据**，不是本次独立复现。真实 bundle/安装验收及远程 CI 均未验证；无假占位 bundle。

### Rust 覆盖核对

原 17 个显式 targets 均仍在，无删除。比对原测试名称，无旧测试名删除；新增 diagnostics 1、execution 1、scrape_memory 1、settings 1、ui_contract 1。t11 开始后另出现 cookies target，未包含本次运行，不冒充已验收。

| target | 基线 test 函数数 | 阶段读取数 | 本次 fixture,ts 结果 |
|---|---:|---:|---|
| credential_rows | 10 | 10 | 10 passed |
| credential_sources | 15 | 15 | 15 passed |
| credentials | 10 | 10 | 10 passed |
| diagnostics | 7 | 8 | 8 passed |
| execution | 12 | 13 | 13 passed |
| install | 19 | 19 | 未运行；需 install-test-boundary |
| install_lifecycle | 21 | 21 | 未运行；需 install-test-boundary |
| install_release_boundary | 2 | 2 | 2 passed |
| installed_cli | 2 | 2 | 2 ignored |
| process_env | 12 | 12 | 8 passed；另外4项受 feature 条件影响 |
| provider_parity | 2 | 2 | 2 passed |
| scrape_memory | 10 | 11 | 11 passed，但 fixture 写死 v1，漏掉 IV-01/02 |
| settings | 33 | 34 | 34 passed |
| skill | 6 | 6 | 6 passed |
| skill_manage | 19 | 19 | 19 passed |
| sqlite_credentials | 8 | 8 | 8 passed（包含跨语言 DPAPI/API-key 协议） |
| ui_contract | 3 | 4 | 3 passed，生成1 ignored |

## 确定发现

### IV-01 — high：Python schema v2 被 Rust 全面拒绝

阶段读取证据：[state_store.py](../multi_search_mcp/src/state/state_store.py#L15) 为 `STATE_SCHEMA_VERSION = 2`，迁移最终写 `PRAGMA user_version=2`；[scrape_memory.rs](../desktop/src-tauri/src/scrape_memory.rs#L114-L139) 的 read_only/read_write 均 `if version != 1` 返回“不支持的抓取状态数据库版本”。

结果：正常 Python 新建或迁移 state.sqlite 后，桌面抓取记忆 view unavailable，pin/reset 失败。这是既有正确流程被破坏，不是仅缺测试。阶段 Rust [fixture](../desktop/src-tauri/tests/scrape_memory.rs#L30-L45) 手工建 `user_version=1`，因此11项通过不反驳该缺陷。

必要修复/复验：明确接受已知 v1/v2，未知版本保持 fail closed；用真实 Python StateStore 创建 v2、实际 v1→v2 迁移数据库，然后 Rust view/pin/reset；证明既有内容缓存绑定/截断标记及其他站点数据不受修改。已交 captain/t11，不在本报告宣称关闭。

### IV-02 — high：hostname-only 校验拒绝合法 GitHub site key

阶段读取证据：[site_memory.py](../multi_search_mcp/src/state/site_memory.py#L46-L55) 的 `site_key` 返回 `github.com/repo`、`github.com/issues`、`github.com/pull`、`github.com/discussions`；[scrape_memory.rs](../desktop/src-tauri/src/scrape_memory.rs#L76-L80) 新 validate_site 只允许 hostname 字符，view(filter)、pin、reset 都调用。

结果：Python 正常生成的 GitHub 分类行，即使可在未过滤全表出现，也不能按行站点过滤、固定或恢复。该结论不依赖 IV-01（使用可接受的 v1 库仍成立）。

必要修复/复验：共享或精确兼容 site_key 定义，不宽放任意 URL/path；四种真实 Python 生成键逐一验证 view/filter/pin/reset，同时保留非法主机、任意路径、URL/端口拒绝测试。已交 captain/t11，待最终关闭。

## 原审查条目阶段处置总表

状态含义：**阶段通过**只覆盖本次运行/阅读证据；**实施证据**尚未独立复现全部性质；**保留/不成立**不等于未检查；**待闭合**不能计入全部修复。原报告按组归并，子项逐项说明保留在各域台账，不能将组内 partial 涂成 fixed。

| 原报告位置/组 | 阶段判定与证据/剩余项 |
|---|---|
| 一.1 Tauri 攻击面 | API/handler/ACL 静态契约测试通过。AppManifest + 显式 allow 已实现；真正窗口/来源授权拒绝需 native 验证。withGlobalTauri 为无 bundler 兼容保留，不独立认定漏洞。fixture public API 不自动等同 IPC。动态文本恶意输入测试通过。 |
| 一.2 明文 Key / 任意 exe | 默认 masked/read、显式 reveal、摘要删除 guard 的 UI 与 Rust 测试通过；API-key DPAPI 跨语言8项通过。显式 exe 未受管路径拒绝测试通过。后续 cookie 新协议不包含在本阶段。 |
| 一.3 query 注入 | `--` 分隔及 option-like 查询回归通过。 |
| 一.4 桌面互斥/poison/cancel | mutation fail-fast、执行锁恢复、completion/cancel 竞争回归通过；install feature 的完整生命周期未独立跑。 |
| 一.5 key 并发健康状态 | 中性错误保留强状态测试通过；success 仍可能清后来的失败、quota/invalid 阈值及到期优先级在 Python 台账明确 partial，待 t12/最终复验。 |
| 一.6 deadline 无限等待 | 隔离 suite 包含 bounded future 回归通过；不可取消线程占槽属明确限制，不宣称强杀。 |
| 一.7 fake-IP | 默认拒绝+opt-in 有测试；代抓入口/HTTP literal/代理边界仍需最终端到端证明，不以单 helper 通过概括全部 fetch。 |
| 一.8 导航竞态 | stale mount、stale rejection、失败重试的 happy-dom 测试通过；独立子容器与 dispose 设计有源代码支持。 |
| 一.9 失败 promise 缓存 | provider load 失败后重试测试通过。 |
| 二 分层越界 | snapshots/evaluation、resolve→scrape、credential_store 迁移仍 deferred；不能说已修。 |
| 二 Provider/HTTP样板 | 统一 row_kind/row_origin 有改动；registry lambda、签名 introspection、Searcher 协议、通用HTTP调用归一仍 partial/deferred。 |
| 二 两套错误模型 | canonical origin/kind + legacy 输入兼容；不应机械要求删除兼容字段。现有 suite 通过不证明所有 provider 已结构化。 |
| 二 长函数 | body_fetch/search_pipeline 责任拆分仍未完成；新增 helper 不等于完成拆分。 |
| 二 渲染/两个入口 | outcome 下沉已做；三处渲染和重复解析仍 partial/deferred。 |
| 二 并发池/deadline | import 时创建池（线程惰性）、容量注入/全 scraper deadline 尚未完整；DNS remaining 在本次读取时已重算，与 t9 旧说明不同，标为“观察到实施修改，待最终验证”，不重复报旧版本缺陷。 |
| 二 缓存scope/Twitter命名 | source scope 改动及别名兼容需最终确认；规范名优先不等于别名删除。 |
| 二 Rust模块 | 保留 skill/common/lifecycle 职责划分与完整性哈希，未证明性能瓶颈，不强制大合并；共享resolver/临时名改动由实施者记录。 |
| 二 死代码 | 删除无生产调用随机选key helper/常量；对应旧测试删除有解释，不是测试减少掩盖回归。其他 import/返回值以完整diff最终核对。 |
| 三 SSRF | HTTP实际连接复核、NAT64/6to4相关回归在837项内；代理/redirect/deadline为活动 t12 重点，未最终接受。 |
| 三 大页面/缓存 | t9 的source级 truncated v2、首次/cache/read回归在837项内通过；产生 IV-01 集成回归，不能只看Python绿灯。 |
| 三 POST/响应大小 | 非幂等SSL重试、gzip/size helper回归通过；第三方/分段read/deflate全覆盖仍待闭合。 |
| 三 DNS | 32 workers及bounded等待改动存在；运行时注入/完整deadline链待最终验收。 |
| 三 SQLite | WAL/迁移快速路径/并发计数测试通过；候选读取事务与record_use分离，不等于原子LRU预留。 |
| 三 敏感数据 | 新URL去query/fragment、scrub、TTL/每站上限有测试；历史数据、userinfo/path、全局上限仍partial。Twitter BOM已修但明文文件风险尚未关闭，t11-13新方案待验证。 |
| 三 Rust脱敏 | 最短8、统一标记/cookie路径快照有实施证据；未把短Key全文替换当可接受。真实cookie托管后的脱敏待最终。 |
| 三 IPC性能/安装hash | spawn_blocking实施；保留完整SHA-256安全语义。未测性能，不凭建议宣称缺陷已复现或已消失。 |
| 三 Jina/junction/output | Jina metadata跨语言测试通过；junction、截断和poison回归有证据；完整安装feature另验。 |
| 三 契约测试 | 普通类型漂移及命令/参数/ACL3项通过，生成显式ignored。不能用该测试替代动态授权或新增cookie最终契约。 |
| 三 CLI低风险 | reset显式选择/--all、manual disable、scrub、stdout编码在隔离suite内；仅可识别秘密可脱敏，不保证任意文本全识别。 |
| 四 小字/对比度/token | CSS交付已提交；颜色比值为实施者静态证据，未真实渲染；无暗色模式本身非已确认缺陷。 |
| 四 断点/反馈/文案 | responsive、busy/spinner、结构化结果、语义色、编号/标题改动有实施证据；760/1080截图未独立验收。 |
| 四 无障碍 | 共享confirm焦点/Escape、导航focus/live region已实现；真实浏览器键盘/读屏未验证，不以happy-dom代替。 |
| 四 重复逻辑/竞态计数器 | 单一错误归一与page容器已改；保留成熟页面草稿状态机有兼容理由，不要求无收益全局抽象。 |
| 四 checkJs/api错误 | checkJs:true独立typecheck通过，strict:false边界已说明；API errors与payload验证测试通过。 |
| 四 scrape旧快照 | 专用事务patch + UI仅发backends已实现并有独立测试通过；同字段最后提交胜出不被包装成CAS。 |
| 四 diagnostics/provider图标 | 动态provider列表/timeout例外/fallback已有测试，未以硬编码90→60破坏既有all路由。 |
| 五 文档/卫生 | 文档组提供路径/锁检查证据，未在本阶段重跑；本地产物/11个已跟踪scratch需求按限制保留，不删除资料伪装clean。 |
| 五 命名/依赖 | 包名/src布局兼容保留；bs4直接依赖移除，传递依赖可留；pytest非unittest必需；happy-dom原已声明（原报告过时）；ts-rs可选feature。 |
| 五 历史文档/CI/申请链接 | 索引与交接折叠、锁定矩阵已做；远程CI未跑。固定HTTPS链接已实现（Baidu未猜地址），系统浏览器真人操作未验收。 |

详见原始[审查报告](review-2026-10-22.md)、[Python处置台账](python-review-evidence-2026-10-22.md)、[Rust处置台账](../desktop/src-tauri/REVIEW-2026-10-22.md)、[UI证据](../desktop/tests/ui-review-evidence.md)、[卫生台账](repo-hygiene-review-2026-10-22.md)。这些是源材料，不自动升级为独立通过。

## 最终复验门槛

1. t11/t12/t13 后冻结提交/工作树范围，再运行隔离Python、前端test/typecheck、Rust minimal + fixture,ts + install-test-boundary + native overlay；比较targets/名字及所有ignored理由。
2. IV-01/02 用真实Python数据库/站点键穿越Rust，不再只手写合成schema；拒绝未来schema且不改数据。
3. cookie managed/file模式显式切换、失败不回退、dict验证、DPAPI跨语言、默认不reveal、不自动删除源文件；秘密不进入argv/日志/UI默认payload。
4. 复核t12部分安全声明，尤其proxy精确授权、fake-IP literal、redirect单次校验解析/deadline、key状态因果与选择、敏感历史/上限及全HTTP响应限流。
5. native ACL/CSP实际来源行为和正式bundle要求，与编译overlay分开证明；不能把缺bundle隐藏。
6. 760/1080真实浏览器布局与键盘交互，如不能完成明确未验收；不能用静态CSS数值替代截图和操作证据。
7. 未完成架构重构等条目必须明确保留/延期是否获得用户接受，不能宣称“原报告所有问题均修复”。
