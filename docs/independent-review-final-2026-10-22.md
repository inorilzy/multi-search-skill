# 最终独立复验：review-2026-10-22（t14）

## 结论

**FAILED / 不建议宣布全部完成。** 主要修复与回归矩阵已独立通过，IV-01/IV-02 已用真实 Python 数据闭合；但发现一个新的真实代理回归（F-01），以及最终文档/CI/申请链接的残留项（F-02–F-04）。按任务约定“有真实缺陷标 failed”，本轮不把绿灯矩阵等同于全部完成。

- 比较基线：`c035da15e6113be84e4634ce28d1a591178c1fb6`。
- 冻结 HEAD：`5c2de01ccb33a7598937d71fbd6b1d0d2c41570c`（未提交实现/测试变更均在工作树）。
- 开始/结束产品文件 SHA-256 清单：`docs/verification-evidence/t14-start-hashes.json`、`t14-end-hashes.json`；417 个文件，**changed=0, missing=0, added=0**。实现冻结期间未修改产品文件。
- 工作树有 108 项 `git status` 变更（含既有未提交实现、未跟踪新文件和本报告证据）；未 commit/push，未修改真实用户配置、凭据、PATH、安装，未删除本地资料。
- 只新增本报告及 `docs/verification-evidence/` 证据文件；未改他域实现或文档。

## 独立命令矩阵

| 命令 | 结果 | 证据 |
|---|---|---|
| `.venv/Scripts/python.exe scripts/run_tests.py` | exit 0；**850 tests，5 skipped**，72.978s；isolation clean | `t14-python.log` |
| `npm --prefix desktop test` | exit 0；**138 passed**，0 failed/skipped，2621ms | `t14-ui.log` |
| `npm --prefix desktop run typecheck` | exit 0（checkJs:true） | `t14-types.log` |
| `cargo test --no-default-features` | exit 0；**18 passed**（16 lib + 2 install_release_boundary），0 ignored | `t14-rust-minimal.log` |
| `cargo test --no-default-features --features test-fixtures,ts` | exit 0；**171 passed，3 ignored** | `t14-rust-fixtures.log` |
| `cargo test --no-default-features --features install-test-boundary` | exit 0；**207 passed，3 ignored** | `t14-rust-install-boundary.log` |
| `TAURI_CONFIG=tauri.check.conf.json cargo check --all-targets --features test-fixtures,ts` | exit 0（native-window 编译） | `t14-native-check.log` |
| `TAURI_CONFIG=... cargo test --features install-test-boundary,ts` | exit 0；**210 passed，4 ignored** | `t14-rust-native.log` |
| 无 overlay `cargo check --all-targets --features test-fixtures,ts` | **exit 101**，`resource path resources\cli-bundle doesn't exist` | `t14-default-check-no-bundle.log` |
| `python scripts/check_glossary_paths.py` | exit 0 | 终端输出 |
| `uv lock --check --offline` | exit 0（27 packages） | 终端输出 |
| `cargo test --test cookies` | exit 0；5 passed（Windows DPAPI/回滚/源文件不变/跨语言） | `t14-cookies.log` |
| 合成 managed-cookie 运行链路 | 2 个场景通过；无 key_state 行 | `t14-cookie-rotation.log` |
| 合成 localhost 代理复现 | `UrlSecurityError unsafe HTTP connection: resolved address is loopback`（【已被票 01–04 取代】该错误路径已删除） | `t14-proxy-hostname.log` |

说明：实施者报告 fixture,ts 为 169 passed，本轮逐 target 实测为 **171**；差异为计数口径（本轮含 `install_release_boundary` 2 项），不是测试减少。旧 17 个 Rust test target 全部保留，旧测试函数名无删除；新增 `cookies` target 及 5 个新测试名。忽略项：fixture 矩阵 3 个（`installed_cli` 2 个真实安装、`ui_contract::emit_types_d_ts` 1 个显式生成）；native 矩阵 4 个（另加 `install` 1 个真实安装）。

## IV-01 / IV-02 关闭

### IV-01 Python schema v2 与 Rust 版本检查

- 当前 Rust `scrape_memory.rs:124,140`：`matches!(version, 1 | 2)`，未来版本拒绝。
- 新增跨语言测试 `python_v2_creation_and_v1_migration_support_category_view_pin_reset` 真实启动 Python `StateStore`：
  - fresh v2 创建；
  - 真实 v1→v2 迁移（删除 `truncated` 列并设 `user_version=1` 后重新迁移）；
  - 对 Python `site_key` 生成的 4 个 GitHub 分类键执行 Rust view/filter/pin/reset；
  - 恶意路径 `github.com/../repo`、`github.com/repo/extra`、`github.com/%2frepo`、`github.com/arbitrary`、完整 URL 均拒绝。
- 独立定向运行：`cargo test --no-default-features --features test-fixtures --test scrape_memory python_v2_...` → **1 passed**；`future_schema_and_invalid_site_never_mutate_memory` → **1 passed**。
- 结论：**IV-01 关闭**；v2 与 v1 均可读写，未知版本 fail closed，其他表/内容缓存列未受影响。

### IV-02 Python 合法 GitHub 分类 site key

- Python `site_memory.py:56-60` 生成 `github.com/repo|issues|pull|discussions`；Rust `scrape_memory.rs:76-82` 精确允许这 4 个键，同时保持 hostname-only 校验。
- 上述真实 Python 生成键测试逐键完成 filter/pin/reset；非法路径仍拒绝。
- 结论：**IV-02 关闭**。

## Cookie 托管（t11/t12/t13）

### 独立证据

- Rust `tests/cookies.rs` 5 项通过：
  - 确认参数先于任何 I/O；file 状态只读；
  - BOM 文件导入后源文件字节不变，DB 中无明文，status 序列化不含 cookie；
  - 非法/超长 map 不回显、不落盘；
  - 事务失败回滚 row+mode 且保留其他 settings 字段；
  - Rust→Python DPAPI 密文协议往返（Python `CredentialStore.get/set('twitter_cookies')`）。
- Python 850 suite 覆盖：managed 延迟读取、缺/损坏/非 Windows fail closed、严格 map 校验、独立 secret provider、history sanitize、global 5000 上限。
- 合成运行链路（`cookie-rotation-check.py`，真实 `SearchRunner`+registry+`search_twitter`，fake X client，无网络）：
  - managed map 直接到达 fake `Client.set_cookies`；
  - 未读取任何明文文件（`builtins.open` 被禁止）；
  - **key_state 行数 0**；
  - managed 缺失时返回受控错误行，仍无 key_state 行。
- UI 138 项包含 cookie status-only mount、显式 import/delete 确认、Escape/焦点、无 reveal 命令、恶意文本转义、失败保持状态。
- `provider_parity` 断言 `twitter_cookies` 属于 credential storage、不属于 API-key keyed 集合；独立运行 Python 集合确认 `CREDENTIAL_STORE_PROVIDERS` 不含它。

### 边界（不是“全部关闭”）

- 默认仍是 `file` 兼容模式，明文文件风险仍在；managed 是显式 opt-in，不自动迁移，原文件不删除。威胁边界是离线 DB/备份复制，不防同用户进程/内存/WebView。
- Linux 的 `cfg(not(windows))` fail-closed 测试未在本机运行（Windows 主机）；代码检查显示 `supported()` 明确拒绝，无明文回退。
- 动态 WebView 授权（ACL 对真实调用窗口/来源）未在 native 运行时验证；静态契约只证明命令/handler/capability/API 列表一致。
- 未运行真实 bundle、安装器、远程 CI；无假占位 bundle。

## 安全边界复核（t12）

- DNS：`_run_bounded_dns` 在准入后重算 remaining；`test_dns_remaining_recomputed_after_admission` 通过。【已被票 01–04 取代：DNS 线程池与 `_run_bounded_dns` 已删除，出站不再在本机解析域名，超时由外层搜索池/抓取池负责。】
- redirect：单次 resolver 捕获 + `_pin_redirect_addresses` 固定地址；`test_redirect_resolver_called_once_and_answers_pinned`、`test_slow_redirect_resolver_is_deadline_bounded` 通过。【已被票 01–04 取代：`_pin_redirect_addresses` 与重定向 DNS 校验已删除，重定向只做同主机/协议规则，不再解析。】
- fake-IP：默认拒绝 literal；resolved 答案需显式 opt-in；`test_literal_fake_ip_rejected_even_with_opt_in` 通过。
- 代理：`_configured_proxy_addresses` 只信任精确 host:port；但发现 **F-01**。
- 原子 reserve：`SQLiteKeyManager.reserve` 在 `BEGIN IMMEDIATE` 内选择并 `use_count+1`；`test_atomic_reservation_distributes_two_simultaneous_attempts` 通过；`rotate_keys` 对 SQLite manager 走 reserve。
- scraper deadline：`_scope_keys`、generic scraper deadline、`test_slow...` 等 850 suite 内通过。
- cache scope：只哈希相关 provider/backends；managed cookie 用一次性 scope 禁用 URL 跨源复用，source-id 缓存仍 TTL 有效（设计限制，非缺陷）。
- truncated：state schema v2 `content_sources.truncated`；首次/cache/read/URL reuse 一致性测试通过；preview 不污染 acquisition；写失败返回正文 + 脱敏 `cache_error`。
- site memory：`_stored_url` 只保留 origin（scheme+host+`/`）；历史 sanitize 事务保留 pins/counts；30 天 TTL、每站 200、全局 5000 测试通过。

## 真实浏览器布局与键盘

使用本机 Edge headless + 临时受控 mock HTTP（仅 `127.0.0.1`，脚本结束即关闭；不替换 DSH GUI），mock API 仅合成数据，未读真实凭据/配置。页面使用真实 `app.js/pages.js/styles.css` 和页面组件。

- 760px：sidebar **172px**，main **573px**，`scrollWidth=745`，最小可见字号 **12px**，横向溢出 **0**；sources/settings 均可用。
- 1080px：sidebar **190px**，main **875px**，`scrollWidth=1065`，最小字号 **12px**，溢出 **0**；sources 详情双栏、settings 单栏正常。
- 对比度（计算值）：`.note` 6.07、`.status-text` 6.07、`.eyebrow` 5.68、`h2` 15.38；sidebar caption 对深绿渐变端点 **7.35–7.91**。初版脚本曾报 sidebar caption 1.63，是未解析 `background:linear-gradient` 的测量错误，已用端点色复算，**不是缺陷**。
- 键盘：Tab 焦点依次落在刷新/选择/输入/按钮，`:focus-visible` 为 **solid 2px**；cookie 导入确认打开后焦点在“确认导入”，Escape 关闭并恢复触发按钮焦点，期间无 IPC 调用。
- 截图：`sources-760.png`、`sources-1080.png`、`settings-760.png`、`settings-1080.png`、`settings-cookie-full.png`；原始指标 `browser-results.json`、`browser-metrics.json`。
- 限制：happy-dom 交互测试不是读屏/真实 Tauri WebView；未做屏幕阅读器、缩放、暗色模式（暗色模式不是已确认缺陷）；未运行真实原生窗口。

## 原审查逐项处置

状态：**FIXED**=独立复现/测试或代码证据；**PARTIAL**=已改但有明确残留；**RETAINED**=有理由保留；**DEFERRED**=未实施；**STALE**=原报告前提已过时；**UNVERIFIED**=环境无法验证。

### 0. 测试与构建现状

| 条目 | 状态 | 证据/残留 |
|---|---|---|
| Python 810 通过 | FIXED | 850/5 skipped |
| Rust 默认 check 缺 bundle、30 命令未编译 | PARTIAL/UNVERIFIED | overlay native check exit0；35 命令契约通过；真实默认 check 仍 exit101；动态 ACL/真实 bundle 未验 |
| install-test-boundary 未跑 | FIXED | 207/3（无 native）、210/4（native） |
| 前端仅 1/9 文件可跑 | STALE/FIXED | happy-dom 基线已声明；138 全通过 |
| CI 不锁依赖 | PARTIAL | 新增 uv locked + frontend job；远程未跑；无 Rust job（F-04） |

### 1. 优先处理（正确性/安全）

| 条目 | 状态 | 证据/残留 |
|---|---|---|
| capability `permissions: []` 不约束自定义命令；30 命令全开放 | FIXED（静态）/UNVERIFIED（动态） | AppManifest+capability+handler+API 35 项一致；真实窗口授权未跑 |
| `withGlobalTauri: true` | RETAINED | 无打包器前端依赖 `window.__TAURI__`；CSP/ACL/无动态 HTML；不单独认定漏洞 |
| 前端 innerHTML 注入 | FIXED | 动态值均 textContent；恶意 provider/error 回归通过 |
| 测试辅助接口编译进正式库 | FIXED | `test-fixtures`/`cfg(test)` 门控；未作为 IPC 远程入口 |
| 自动展开并解密明文 Key | FIXED | 初始不 read/reveal；显式“显示”才 reveal；UI/后端测试 |
| `credential_read` 返回全部明文 | FIXED | 默认前4后4掩码（<=8 全掩码）+ snapshot；显式 `credential_reveal` |
| 删除要求前端明文快照 | FIXED | SHA-256 snapshot；事务内校验 |
| 任意 exe 路径 | FIXED | PATH 发现/受管目录；显式未受管路径拒绝测试 |
| query 参数注入 | FIXED | `--` 终止符；option-like 查询测试 |
| 变更操作无互斥 | FIXED | mutation try_lock，install/update/uninstall/skill 覆盖 |
| 固定 `managed-skills.tmp` | FIXED | pid+counter 临时名 |
| `lock().unwrap()` 中毒不可恢复 | FIXED | execution poison 恢复、mutation fail-closed 说明与测试 |
| 取消时持锁等待子进程 | FIXED | finish 移出锁；spawn_blocking；竞争测试 |
| key 熔断状态被并发覆盖 | PARTIAL | 中性错误/强状态 CASE 已修并有测试；success 与并发旧失败因果、quota/invalid 阈值优先级仍在 Python 台账保留，未宣称完整状态机 |
| deadline 后无限等待 | FIXED | `run_all_before` 到期不等待；回归通过 |
| fake-IP 代理下抓取失败 | FIXED | 出站边界改为按目标划分，不再做本机 DNS 预检，`MULTI_SEARCH_ALLOW_FAKE_IP` 已删除（ticket 01–04） |
| 固定端点 DNS 预检无价值 | FIXED | Reddit/固定端点去预检测试 |
| 前端切页竞态 | FIXED | stale mount/rejection、失败重试测试 |
| dispose 空实现 | FIXED | install/skill dispose 与监听清理 |
| mount 抛错白屏 | FIXED | 文本错误 + 重试 |
| “请重试”永久缓存失败 | FIXED | provider 失败后可重试测试 |

### 2. 架构

| 条目 | 状态 | 证据/残留 |
|---|---|---|
| 分层越界（snapshots/evaluation、resolve→scrape、credential_store） | DEFERRED | 仅 KNOWN_BACKENDS 收敛；迁移未做 |
| Provider 抽象/12 lambda/introspection | DEFERRED/PARTIAL | registry 仍 lambda 与参数 introspection |
| 9 searcher HTTP 样板 | PARTIAL | 未统一；错误类别仅部分结构化 |
| 两套错误模型 | FIXED | `support/auth.py` canonical `origin/kind`；旧字段兼容输入 |
| 上帝函数（219/165 行） | DEFERRED | 仅拆 helper，未完成 plan/fan-out/fuse/persist 分段 |
| 三处渲染、CLI 业务 outcome | PARTIAL | outcome 已下沉；渲染未合并 |
| 两个公共搜索入口重复解析 | DEFERRED | `run_multi_search`/`run_search_web` 仍并存 |
| 全局池 import 创建、容量无关、deadline 不全 | PARTIAL | env 容量/注入/多数 adapter deadline；全局池与全部 scraper 未完全贯通 |
| cache scope 过大 | FIXED | 只哈希相关 provider/backends；managed URL reuse 禁用为设计限制 |
| Twitter 三个键名 | PARTIAL | 规范名优先，别名保留兼容 |
| Rust skill 模块重叠/重复转发 | RETAINED | 职责分离与完整性哈希有理由；未做高风险大合并 |
| 死代码 pick_key/key_pool/CONFIG_ENV_VAR 等 | FIXED | 指定死代码删除；旧随机 helper 测试随之删除并记录 |

### 3. 健壮性与安全（中）

| 条目 | 状态 | 证据/残留 |
|---|---|---|
| SSRF DNS rebinding / 代理失效 / NAT64/6to4 | PARTIAL | 逐地址复核、redirect pin、NAT64/6to4 测试；F-01 hostname 代理回归；代理信任边界未由本地证明 |
| 大页面字符/字节失败 | FIXED | t9 v2 truncated + 字节截断 + 缓存失败降级；850 通过 |
| 付费 POST 自动重试 | FIXED | 非幂等方法不重试；测试 |
| 响应体/gzip 无上限 | FIXED（中心路径）/PARTIAL | `_DeadlineHTTPResponse` + `gunzip_limited`；第三方/分段 read 未全覆盖 |
| DNS 池仅 8 | SUPERSEDED | DNS 线程池已删除（ticket 04）：出站请求不再在本机解析域名，超时由外层搜索池/抓取池负责；单条 fetch 与 doctor --network 的 DNS 残余风险已接受 |
| SQLite 无 WAL/迁移抢锁/选 key 非原子 | FIXED | WAL/busy_timeout/user_version 快速路径/原子 reserve；迁移快速路径 |
| site_memory 原样 URL/错误、永不清理 | FIXED | origin-only、scrub、30 天/200/5000、历史 sanitize 事务 |
| Twitter cookies 明文/BOM | PARTIAL | BOM 已修；managed DPAPI opt-in；默认 file 仍明文，不自动迁移 |
| Rust 脱敏不完整/短 key/全量解密 | FIXED | 统一标记、最短8、cookie 路径与内容、共享快照；性能未基准 |
| 桌面同步 IPC SQLite/注册表、全量 SHA-256 | PARTIAL/RETAINED | spawn_blocking；完整 SHA-256 安全语义保留；无性能基准，不宣称已优化 |
| Jina 读改写非事务 | FIXED | `save_jina` IMMEDIATE + 测试 |
| Skill `.claude` junction | FIXED | `safe_managed_paths` 父链/文件 link 检查；junction 测试 |
| 4 MiB 截断不可感知 | FIXED | `Output.truncated` + reader poison 恢复测试 |
| 契约测试会改写 types.d.ts、无自动对比 | FIXED | 普通漂移只读；生成 ignored；命令/参数/ACL 自动对比 3 项通过 |
| CLI 异常 scrub、reset 全量、stdout strict | FIXED（scoped） | reset 需 `--all`/选择、保留手动禁用；scrub；stdout replace；仅识别已知秘密 |

### 4. UI / 视觉

| 条目 | 状态 | 证据/残留 |
|---|---|---|
| 小字/低对比度 | FIXED（静态+实测） | 最小 12px；muted/note 6.07、eyebrow 5.68；sidebar caption 7.35+；真实浏览器测量 |
| 无设计 token/两套 :root/146 硬编码/无暗色 | PARTIAL | 单一语义 token；暗色未加（非确认缺陷）；仍有硬编码/属性选择器 |
| 1080 折叠、1350/1600 分支、760 侧栏 132 | FIXED | 760=172、1080=190；两宽度截图无横向溢出 |
| 长操作无进度/测试原始 JSON/危险色不一致 | FIXED | busy/spinner、结构化结果、语义色；happy-dom 测试 |
| eyebrow 编号/标点/术语 | FIXED | 页面编号/标题一致性；UI 证据 |
| 确认焦点/role=alert/切页播报/aria-label div | PARTIAL | 焦点/Escape/live region 有测试；真实读屏未验，role 使用仍多 |
| 8 份 inline-confirm/草稿状态机/错误归一/竞态计数器/checkJs/api 错误/scrape 旧快照/diagnostics/图标 | PARTIAL | checkJs、ApiError、专用 scrape 事务、动态 provider、图标 fallback 已改；成熟草稿状态机保留；跨进程同字段 TOCTOU 仍存在（不称 CAS） |

### 5. 仓库卫生与文档

| 条目 | 状态 | 证据/残留 |
|---|---|---|
| README/glossary 失效路径 | FIXED | `check_glossary_paths.py` exit0；路径/链接通过 |
| README/glossary 语义过时 | **PARTIAL（F-02）** | README:48/glossary:63 仍称 t9 待验证；managed cookie 模式未写入 |
| build/egg-info/根缓存 | RETAINED | 均被忽略；按约束保留本地产物，不伪造 clean |
| .scratch 827MB/11 已跟踪 | RETAINED | 已跟踪需求/规格保留；未 `git rm --cached` |
| .zvec-grep 未忽略 | FIXED | `.gitignore` 新增 |
| 52 份历史文档/HANDOFF 叠加 | FIXED（索引/折叠） | docs/README 索引、HANDOFF 顶部状态有效；未归档删除 |
| 包名/src 布局 | RETAINED | 兼容保留，README 说明 |
| bs4 未使用 | FIXED | pyproject/uv.lock 移除直接依赖；传递依赖可留 |
| pytest 未声明 | STALE/NOT-APPLICABLE | 项目用 unittest；不强制引入 |
| happy-dom 未声明 | STALE | 基线已声明；CI npm ci |
| ts-rs 编译进正式产物 | FIXED | optional `ts` feature |
| 申请链接全部 None | PARTIAL（F-03） | 8 个 HTTPS 链接；Baidu 仍 None，按钮仍“待配置” |

## 发现与后续

### F-01 — medium：hostname 形式的本地代理被 SSRF 校验拒绝

- 【已被票 01–04 取代：本条描述的 `connect_socket` 与 `resolve_validated_addresses` 路径已删除；保留作为 F-01 的历史发现记录。】路径：[http.py](../multi_search_mcp/src/support/http.py#L189-L220) 的 `connect_socket`：`proxy_hop` 只在 IP literal 分支使用；非 literal 代理主机走 `resolve_validated_addresses`，随后无条件 `_ensure_connect_address(..., resolved=True)`，把 `localhost`→`127.0.0.1` 当 loopback 拒绝。
- 复现（已保存 `t14-proxy-hostname.log`）：`HTTPS_PROXY/ProxyHandler = http://localhost:7890`，DNS 合成 `127.0.0.1:7890`，结果 `UrlSecurityError unsafe HTTP connection: resolved address is loopback`；同配置 `127.0.0.1:7890` 可用。
- 影响：常见 `localhost` 代理用户全部网络失败；这是“环境代理精确信任”修复的功能回归。
- 建议修复：仅当 `(target_host,target_port)` 精确匹配 `_configured_proxy_addresses()` 时，对解析地址应用 proxy-hop 豁免；仍拒绝任意私有地址；增加 `localhost`/hostname 代理回归，保留 `127.0.0.1` 与恶意代理测试。

### F-02 — low：最终文档语义漂移

- [README.md](../README.md#L48)：“跨缓存命中的截断元数据保留正在 t9 补验”；[docs/glossary.md](glossary.md#L63)：“由 t9 后续验证，不在此宣称已闭合”。t9 已完成（850 suite，v2 truncated 元数据/回归），两处应改为已闭合。
- [docs/glossary.md](glossary.md#L101) 仅写“Twitter cookie 路径存于 settings”，未写 `twitter_cookies_mode` 的 file/managed、DPAPI 托管与默认不自动迁移；COOKIE-PROTOCOL 已存在但 glossary/README 未同步。
- 建议由 repo-hygiene 修正，不改变实现；最终报告尚未加入 docs/README 索引。

### F-03 — low：Baidu 申请链接仍为空

- [credential_commands.rs](../desktop/src-tauri/src/credential_commands.rs#L239) `("baidu", None)`；其余 8 个已固定 HTTPS。原审查“全部为 None”已大部分修复，但 Baidu 按钮仍显示“申请链接待配置”。未猜测官方控制台路径是合理的，但需明确接受该残留或补官方链接。

### F-04 — process：CI 没有 Rust 验证 job

- [.github/workflows/test.yml](../.github/workflows/test.yml) 只有 Python/锁定 Python/前端；没有 `cargo check/test`、overlay、install-boundary 或 ui_contract。远程 CI 也未运行。新 Rust 测试只能靠本地命令，容易回归；建议增加 Windows Rust job 并显式使用 overlay/feature 组合（不能把缺 bundle 隐藏）。

### 验证限制（不是已确认缺陷）

- 真实 Tauri 原生窗口 ACL 对调用窗口/来源的运行时拒绝、真实 bundle/安装器、远程 CI 未验证；`withGlobalTauri` 保留为无 bundler 兼容设计，不单独认定漏洞。
- Linux cookie fail-closed 测试未在 Windows 运行；`cfg(not(windows))` 代码与测试存在，需 Linux runner。
- 动态 WebView 真实 IPC、屏幕阅读器、缩放/高 DPI 未验证；视觉证据为 mock 数据的 headless Edge。
- Python `StateStore._schema_is_current_conn` 对 `user_version > 2` 且必需列存在时返回 current（[state_store.py](../multi_search_mcp/src/state/state_store.py#L211-L225)），与 Rust 的 future-version fail-closed 不一致；未构造不兼容未来 schema，列为跨语言风险/验证缺口，需决定是否收紧。
- 未运行真实用户安装、PATH、凭据、网络；合成 cookie 仅 fake client。

## 最终建议

1. 先修 F-01 并加 hostname 代理回归；F-02 文档由 repo-hygiene 收口；F-03/F-04 由 captain 决定接受或补链接/CI。
2. F-01 修复后重跑：隔离 Python、UI 138、Rust 18/171/207/210、overlay check、cookie 5、合成 rotation，并复跑本报告的命令矩阵。
3. 真实原生 ACL/bundle/远程 CI 需在具备 Windows runner/受控 bundle 的环境单独验收；不得用 overlay 或静态契约替代。
4. 架构 DEFERRED 项（Provider 协议/registry 收敛、HTTP 统一、分层迁移、长函数拆分、渲染统一、双入口合并）仍有价值，未实施；不能宣称“原报告所有问题均修复”。
