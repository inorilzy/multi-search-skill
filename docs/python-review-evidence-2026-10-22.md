# Python review 处置证据与剩余工作

本台账记录 t1、t9、t12、t15，不代表全部审查问题已修复。原报告没有逐项编号的“42 条”；以下按任务列出的 19 组映射。t1 的完成报告存在夸大及统计遗漏，本文件明确纠正。

## t12 追加：真实安全边界闭合

以下 supersede t9 表中对应 partial（其余架构延期仍有效）。

- DNS admission 后重算 remaining；redirect resolver 在原 deadline 内只调用一次，校验捕获的同一答案构建 pinned sockaddr，连接不重复 DNS。慢 resolver/单次 resolver 回归已验证。
- HTTP literal fake-IP 即使 opt-in 也拒绝；仅 resolved=True 的域名答案可获 fake-IP 例外。代理例外移至连接 request 确认为 proxy/tunnel 且精确配置 host:port，不再额外豁免端口80/443。代理仍是用户选择的信任边界，远端 DNS 无法由本地证明。
- SQLiteKeyManager.reserve 在 BEGIN IMMEDIATE 内重新检查健康状态、按最新 last_used_at 选候选并原子递增 use_count。rotate_keys 使用 reserve（不再先选后记）；一次旋转不重复使用同候选。不是独占 lease：provider 允许同 key 并发，目标是 LRU 分配而非串行化网络。双并发分配回归验证两把可用 key 不再基于旧快照总取第一把。
- generic scraper Jina/Exa/Firecrawl/Tavily 的 ctx.deadline 传到 urlopen_retry；固定 Reddit 和 XKit 原有 deadline 保留。测试 doubles 接收明确 deadline，不删除断言。
- cache_scope 使用实际配置的默认 backend 链和相关 credential；无关搜索 key 不影响正文 scope。managed cookie reference 不序列化为 secret，也不执行 eager 解密：以每次随机非秘密 scope 禁止跨 source URL reuse；source-id 缓存仍为原 TTL（访问同一个 source-id 本来就是显式缓存读取）。t9 truncated 元数据原样保留。
- Cookie 协议按 t11：独立 `twitter_cookies` secret provider，v1 envelope、compact UTF8 map<=65536，1..128项、ASCII名字、值<=4096 bytes且非空/无Unicode Cc，auth_token/ct0必须非空白。mode 缺省file；managed lazy reference 在实际 Twitter调用中解密验证并作为dict交给既有set_cookies路径；无临时文件，缺失/损坏/非Windows不回退file，不加入API key轮换/诊断读取池。doctor声明file为明文边界；未知mode fail closed。合成cookie回归覆盖延迟加载、禁止文件访问、缺失/损坏/Linux、校验限制与API pool隔离；真实DPAPI跨语言互操作由t11测试负责。
- site_memory 新记录仅保留 scheme+hostname 根路径（去userinfo/port/path/query/fragment），仍按原输入计算稳定site分类。历史数据通过独立 privacy_migrations 标记在事务中不可逆清理：attempt URL/sample URL规范化、历史原始错误全部清空（避免猜测未知秘密），保留site、scraper、聚合计数、pin、priority、cooldown。新增全局最近5000 attempts上限及30天TTL，未删除站点偏好统计。历史旧秘密可能残留于旧备份/SQLite未回收页，逻辑迁移不声称磁盘取证安全擦除；需用户管理备份/安全删除策略。站点聚合表保留有效记忆，仍可能随新域增长，不宣称总DB固定容量。
- t12 新增13条（6边界+5cookie+2历史迁移/全局上限），837→850；隔离runner通过。无需state schema v3，v2仅content_sources.truncated；privacy_migrations是可选内部数据迁移标记，不改变Rust读取表。

## t15 F-01：hostname 本地代理精确授权

- 复现（独立临时脚本，不修改产品）：合成 `localhost:7890`→`127.0.0.1` 后，旧路径 `resolve_validated_addresses` 输出 `unsafe HTTP connection: resolved address is loopback`；修复后 `_is_trusted_proxy_hop(localhost,7890)=True`，错误端口 `7891=False`，直接 `127.0.0.1` 目标 `=False`。该输出与 `t14-proxy-hostname.log` 的旧症状一致。
- 实现：[http.py](../multi_search_mcp/src/support/http.py) `_trusted_proxy_targets` 合并进程代理设置与该请求由 urllib 配置的 `req.host`（HTTP proxy 的 `has_proxy()` 或 HTTPS tunnel 的 `_tunnel_host`），仅精确 host:port 命中；命中的 hop 用未做目标校验的 DNS 结果连接，其他任何目标仍走 `resolve_validated_addresses`/`_ensure_connect_address`。literal 分支同样使用精确 hop 判断。redirect 仍只验证重定向目标，不因代理配置获得豁免。
- 回归：[test_proxy_trust_boundary.py](../tests/test_proxy_trust_boundary.py) 8 条：localhost、127.0.0.1、`[::1]`、错误端口、直接 loopback/private 拒绝、hostname 代理真实 connect 成功且发出 `Host: example.com`、无 env 的显式 ProxyHandler、代理存在时 redirect 到 localhost 仍拒绝且错误不含 token。
- 残留风险：代理 hostname 的 DNS 仍是用户信任边界（系统 DNS 可将其指向非代理地址）；远程代理可转发任意目标，本地无法证明其行为。本修复只保证“用户显式配置的精确 hop”不再被 loopback 规则误杀，不放宽直接目标和重定向。`_configured_proxy_addresses` 解析无 scheme 的 env 值可能失败，但请求自身 `req.host` 路径覆盖常见情况；未构造系统级 Windows 代理注册表测试。
- 未改 `scripts/test_isolation.py`；集成测试通过替换 socket transport 满足隔离器约束。

## t15 key_state 旧 success 覆盖新失败：当时证据

- 可复现证据：[test_key_state_concurrency.py](../tests/test_key_state_concurrency.py) 新增
  - `test_success_after_permanent_invalid_is_a_verified_recovery`：3 次 401 达到 INVALID 后一次真实 success → ACTIVE、strikes 0、key 重新可用（有意恢复语义）。
  - 并发测试证明无 lost update，但当时实现仍是 last-completion-wins：success 若晚提交会清掉并发写入的强状态。t15 只提出 generation 升级条件，**没有修复因果缺陷**。
- t15 新增 10 条（8 proxy + 2 key_state 证据），850→860；隔离 runner 通过。

## t20 key_state 迟到 success 因果缺陷：已修复

- 列核实：`PRAGMA table_info(key_state)` 现有 `updated_at / last_used_at / last_success_at / last_failure_at / cooldown_until / exhausted_until`。无需 schema 变更，未 bump `STATE_SCHEMA_VERSION`（保持 v2），Rust 读取兼容。
- 方案：将 `updated_at` 明确为“最后一次影响凭据状态的写入代际”，并只在 strong verdict 与 success 写入时推进；`record_use`、`reserve`、中性错误（timeout/network/unclassified）不再推进 `updated_at`（中性错误仍写 `last_failure_at` 和计数，不改状态/strikes）。
- `rotate_keys` 在调用 provider 前捕获 `started_at`，并在 `record_result(..., started_at=...)` 传回。success 的 UPDATE 用单条 SQL CASE 与 `updated_at > started_at` 比较：若期间已有更新（另一请求的 invalid/rate_limit/quota 或另一 success）则保留当前 status/cooldown/invalid_strikes/last_error；成功计数、`last_success_at` 和 `updated_at` 仍推进。比较在 SQL 内原子完成，不存在读后写窗口。
- 反方向仍允许正常恢复：`started_at` 晚于强状态代际的 success 会清冷却、strikes 并恢复 ACTIVE。
- 确定性/并发/多进程测试：[test_key_state_generation.py](../tests/test_key_state_generation.py)
  - 迟到 success 保留 QUOTA_EXHAUSTED、COOLDOWN、INVALID(3 strikes)；
  - barrier 控制“success 先开始、failure 中途提交、success 后提交”，强状态保留；
  - 正常 success（开始于 failure 之后）恢复 ACTIVE；
  - 中性错误与 `record_use` 不推进代际，不阻断恢复；
  - 父子进程用例：子进程写 quota，父进程迟到 success 仍保留；代际更新后恢复。
  - `rotate_keys` 传递 `started_at` 的直接断言。
- 语义边界：同一微秒内开始的 success 与 failure 比较为 `>`，同刻视为非更新（可恢复）；跨进程系统时钟回拨会使比较失真，但本机进程共享同一 wall clock。`updated_at` 从“每次访问时间”变为“状态代际”，doctor/status 输出仍只展示该字段，无协议字段变化。
- 计数：t15 860 → t20 869（新增 9 条 generation 测试）；隔离 runner 通过。

## 验证与计数

- 初始隔离运行 `python scripts/run_tests.py`：810 tests，5 skipped。
- t1 隔离运行：832 tests，5 skipped。
- t9 隔离运行：837 tests，5 skipped（60.078s），isolation clean。
- 核对方式：AST 提取各测试类的 `test_*` 方法，与 git HEAD（5c2de01，Python 修复尚未提交）比较。方法计数与 unittest discover 的运行数一致。
- t1 净增 **22 = 19 + 3 + 1 + 1 - 2**：新安全测试模块 19；CLI 3；invalid streak 新增 neutral 1；Reddit 原一条拆两条净增 1；删除两个无生产调用的旧随机选 key helper 测试 2。另有测试改名/行为变更，净计数为 0。
- 先前只报告“19 新增、2 删除”遗漏 CLI、neutral、Reddit 拆分，共 5 条；不是测试框架改变计数。
- t9 新增 5 条缓存元数据测试，故 832 → 837。恢复 full-content 测试的缓存命中 `truncated=True` 断言，不再以删除断言回避缺陷。

## t9 截断元数据契约

实现：[content_store.py](../multi_search_mcp/src/state/content_store.py)、[state_store.py](../multi_search_mcp/src/state/state_store.py)、[body_fetch.py](../multi_search_mcp/src/core/body_fetch.py)。

- state.sqlite schema v2：`content_sources.truncated INTEGER NOT NULL DEFAULT 0`，在已有 BEGIN IMMEDIATE 迁移事务中 ADD COLUMN；v0/v1 库内容和绑定保留。旧缓存没有截断证据，按默认 false 读取，不声称能够重建过去丢失的信息。
- 标记属于 **source/acquisition 绑定**，不属于 content hash；相同正文可以来自完整页面或截断页面，二者不会互相污染。
- `put(..., truncated=False)` 保持既有调用兼容；`get`、URL reuse 保留标记；同 source 重写为完整正文会清除旧标记。
- fetch 输出 `truncated = acquisition_truncated OR preview_truncated`。只为展示截取的 preview 不会污染完整缓存的标记。上游 scraper 的 truncated 同样持久化。
- read 输出 `truncated` 表示缓存 acquisition 本身不完整；`has_more` 只表示缓存内还有可读字符，两者独立。因此 `truncated=true, has_more=false` 合法。
- UTF-8 按字节截断、去掉末尾不完整编码，不拆 Unicode 字符。SQLite/OSError/ContentStoreError 写失败返回已获得正文、`persisted=false`、脱敏 cache_error；不捕获任意编程异常。
- 测试：[test_cache_truncation_metadata.py](../tests/test_cache_truncation_metadata.py)：中文/emoji 字节边界，首次/cache/read 一致，source 级别元数据与 URL reuse，v1 迁移保留正文，三类写失败，preview 不污染 acquisition。

## t1 逐组处置（纠正原完成报告）

| 组 | 状态 | 已有变更与限制 / 必要的剩余工作 |
|---|---|---|
| 1 key 健康状态 | partial → 因果项 fixed（t20） | 中性错误不改 status/strikes；失败 CASE 保强状态；t20 用 `updated_at` 代际阻止迟到 success 清除其开始后写入的强状态（零 schema 变更，见下文）。仍保留 partial 的原因：quota 分支后 invalid 达阈值的优先级、到期 quota 状态等状态机细节未逐一证明；不宣称完整状态机正确。 |
| 2 run_all_before | fixed | 到期只读取 done futures；其余取消/超时行，运行中的线程仍占槽直到返回（Python 无安全强杀线程机制）。有 deadline 回归。 |
| 3 fake-IP 与信任边界 | partial | 默认禁止 benchmark IP、显式环境 opt-in；Reddit 只取 ID，固定端点禁 redirect，去掉无意义 permalink DNS 预检。代抓做字面量/localhost 检查。需继续复核 HTTP literal 与 resolved opt-in 区分、代理精确端口授权；body_fetch 入口仍做 public URL DNS 预检，故不能称全 fetch fake-IP 问题已解决。 |
| 4 字节缓存 | fixed in t9 | t1 截断但未保存 metadata；t9 加 v2 source 元数据并恢复命中断言。首次、缓存、read 一致，写失败返回正文。 |
| 5 HTTP SSRF | partial | 连接前逐地址复核，内嵌 NAT64/6to4 v4 检查，redirect 保存地址。现有 redirect 仍可能重复解析（validator 与 pin），pin 自定义 resolver 的等待也需重新检查 deadline；环境代理信任例外应由独立安全复核收口。 |
| 6 DNS capacity | partial | 8→32，submit_before 等待槽；等待后的 result timeout 必须重算 remaining（当前保留初始 remaining），否则可超出 deadline。仍未实现 runtime 注入 DNS executor。 |
| 7 site_memory | partial | query/fragment 去除，错误 scrub；30 天 TTL，每站 200 条。仍无全局站点/条数上限，历史敏感数据未迁移，userinfo/path secrets 仍需策略。 |
| 8 SQLite | partial | WAL/busy timeout、版本/列检查快速路径，候选读取+注册 BEGIN IMMEDIATE，多进程增量计数测试。候选选择事务并未原子预留首 key，也未合并后续 record_use，因此不等于并发 LRU 分配解决。 |
| 9 Twitter cookies | partial | utf-8-sig 已修；文件仍明文。DPAPI 不是仅 Python 内部替换：桌面导入/管理、配置兼容需共同设计。不能以 schema 工作为借口称已修复。 |
| 10 HTTP retry/read | partial | POST SSL/EOF 不重试，HTTPResponse.read(None) 上限，gzip 限流；部分读取协议、显式 amt/第三方 curl/XKit 未全覆盖，StackOverflow deflate 仅截输出而未显式报超限。通用 read_limited 并未替换所有调用点。 |
| 11 统一错误/Provider | partial | row_kind/row_origin 合并到 support.auth；保留 error_type/error_origin 输入兼容、诊断/DB 字段。registry 仍 12 lambda 和签名 introspection。统一协议可降低新增 provider 成本，但需兼容现有 monkeypatch/公开函数，不应假称现有 ProviderSpec 已达到统一签名。 |
| 12 分层 | deferred | 默认 backend tuple 收敛为 KNOWN_BACKENDS 别名；resolve 仍 import scrape。snapshots/evaluation 和 credential_store 未迁移。迁移有助无环分层；应另做导入边界测试与兼容 re-export，而非以改 patch 点为永久拒绝理由。 |
| 13 长函数/返回值 | deferred | body_fetch 新增截断/scope helper，但没有完成 resolve/cache/acquire/persist 分段；search_candidates 未完成 plan/fan_out/fuse/persist 分段，prefetched_bodies 仍是可变输出参数。应做纯重构并保持快照一致。 |
| 14 CLI/渲染/双入口 | partial | outcome 移 core，CLI 映射退出码；三处渲染未合并，run_multi_search 重复解析仍存在。须厘清 human/markdown/both 契约再合并。 |
| 15 死代码/命名 | partial | 删除 pick_key/key_pool、CONFIG_ENV_VAR；公开 resolve helpers、Jina imports 改公开函数。Twitter 规范名优先但保留别名；scrape_top/degrade_to 兼容仍在。公开别名与测试 patch 点并非完整清理。 |
| 16 deadline/池 | partial | 多个 search adapter 接收并传 deadline，registry 已传。不是所有路径：scrapers/Jina/Exa/Firecrawl、Tavily 内部 urlopen 仍待贯通；全局池仍 import 时实例化（线程惰性启动），env 容量可配，仅 SearchRunner/stage 支持显式注入；expand/DNS 未全贯通 runtime。 |
| 17 CLI 安全 | fixed scoped | reset 无选择需 --all，保留 manually_disabled；异常 scrub，stdout replace/stderr backslashreplace。匹配到的 secrets 才能脱敏，不宣称任意文本可识别全部凭据。 |
| 18 依赖/gh | partial/external | bs4 零引用已报告 repo-hygiene；pytest 非现有 unittest 必需。gh 用 which 检查存在，但仍用原 argv 启动，不等于固定 executable 路径。pyproject/lock 不在本任务范围。 |
| 19 测试 | fixed scoped | 810→832 真实计数见下；新增多进程计数验证不等于原子选 key 证明。t9 修复缓存遗漏并增至 837。通过现有测试不构成全部安全问题修复证明。 |

## 测试逐名差异

以下自动提取 AST 名称。`+/-` 同文件相近名称常为改名/语义更新，而非净新增。对旧断言的替换理由：网络/超时不再清健康状态；大页面不再整次失败，而是标记截断并可缓存；固定 Reddit endpoint 不以 permalink DNS 决定能否调用；keys 文件模式与 sys.platform 无关。随机 helper 的两条测试随无生产调用的 helper 删除，BasicKeyManager 配置顺序测试保留。


### [test_architecture_regressions.py](../tests/test_architecture_regressions.py)

```text
+ ContentFlowRegressionTests.test_short_preview_truncates_at_the_content_store_byte_limit
- ContentFlowRegressionTests.test_short_preview_does_not_bypass_content_store_capacity
```

### [test_cache_truncation_metadata.py](../tests/test_cache_truncation_metadata.py)

```text
+ CacheTruncationTests.test_cache_write_errors_preserve_body_and_truncation
+ CacheTruncationTests.test_metadata_is_per_acquisition_not_shared_content_hash
+ CacheTruncationTests.test_preview_truncation_does_not_mark_complete_acquisition
+ CacheTruncationTests.test_utf8_boundary_survives_cache_hit_and_read
+ CacheTruncationTests.test_version_one_migrates_without_losing_body
```

### [test_cli.py](../tests/test_cli.py)

```text
+ CliTests.test_keys_reset_all_clears_every_row
+ CliTests.test_keys_reset_requires_a_selection_or_all
+ CliTests.test_service_exception_output_is_secret_scrubbed
```

### [test_credential_store.py](../tests/test_credential_store.py)

```text
+ LoadKeysPriorityTests.test_process_store_is_not_consulted_when_a_keys_file_is_supplied
- LoadKeysPriorityTests.test_process_store_disabled_off_windows
```

### [test_dns_deadline_r3_06.py](../tests/test_dns_deadline_r3_06.py)

```text
+ DnsDeadlineTests.test_direct_reddit_scraper_does_not_dns_preflight_the_post_url
+ DnsDeadlineTests.test_scrape_core_does_not_resolve_delegated_urls_locally
- DnsDeadlineTests.test_direct_reddit_scraper_timeout_bounds_second_url_preflight
- DnsDeadlineTests.test_scrape_core_does_not_dispatch_after_url_preflight_deadline
```

### [test_full_content_flow.py](../tests/test_full_content_flow.py)

```text
+ FullContentFlowTests.test_oversized_body_is_truncated_to_the_cache_byte_limit
- FullContentFlowTests.test_full_content_does_not_bypass_existing_cache_capacity_errors
```

### [test_invalid_streaks.py](../tests/test_invalid_streaks.py)

```text
+ InvalidStreakTests.test_each_credential_result_clears_invalid_strikes
+ InvalidStreakTests.test_neutral_network_failure_preserves_invalid_streak
- InvalidStreakTests.test_each_non_invalid_provider_result_clears_invalid_strikes
```

### [test_key_state_concurrency.py](../tests/test_key_state_concurrency.py)

```text
+ KeyStateConcurrencyTests.test_credential_results_update_state_and_neutral_errors_preserve_it
- KeyStateConcurrencyTests.test_non_invalid_results_clear_strikes_and_success_preserves_quota_expiry
```

### [test_mcp_architecture.py](../tests/test_mcp_architecture.py)

```text
+ PluginScrapeReviewFixTests.test_invalid_strikes_reset_on_success_but_not_on_neutral_failures
- PluginScrapeReviewFixTests.test_invalid_strikes_reset_on_success_and_other_failures
```

### [test_mcp_core.py](../tests/test_mcp_core.py)

```text
- KeyTests.test_key_pool_shuffles_non_empty_candidates
- KeyTests.test_pick_key_supports_key_pool_arrays
```

### [test_prefetched_body_selection.py](../tests/test_prefetched_body_selection.py)

```text
+ PrefetchedBodySelectionTests.test_oversize_selected_body_is_truncated_to_the_byte_limit
- PrefetchedBodySelectionTests.test_oversize_selected_body_is_rejected_without_storing_a_shorter_alternative
```

### [test_reddit_scraper.py](../tests/test_reddit_scraper.py)

```text
+ RedditRoutingTests.test_credentials_are_rejected_before_auth
+ RedditRoutingTests.test_private_dns_answer_does_not_block_fixed_endpoint_fetch
- RedditRoutingTests.test_private_resolution_and_credentials_are_rejected_before_auth
```

### [test_review_security_fixes.py](../tests/test_review_security_fixes.py)

```text
+ EmbeddedAddressTests.test_6to4_embedded_private_ipv4_is_rejected
+ EmbeddedAddressTests.test_dns_answers_with_embedded_private_ipv4_are_rejected
+ EmbeddedAddressTests.test_nat64_embedded_private_ipv4_is_rejected
+ EmbeddedAddressTests.test_nat64_embedded_public_ipv4_is_allowed
+ FakeIpCompatibilityTests.test_connect_address_check_accepts_fake_ip_only_when_opted_in
+ FakeIpCompatibilityTests.test_fake_ip_is_allowed_when_opted_in
+ FakeIpCompatibilityTests.test_fake_ip_is_rejected_by_default
+ FakeIpCompatibilityTests.test_fake_ip_opt_in_never_allows_a_literal_ip
+ HttpHardeningTests.test_get_still_retries_after_ssl_eof
+ HttpHardeningTests.test_gunzip_limited_rejects_compression_bomb
+ HttpHardeningTests.test_post_is_not_retried_after_ssl_eof
+ HttpHardeningTests.test_read_limited_rejects_oversized_body
+ KeyStatePreservationTests.test_neutral_failure_does_not_downgrade_quota_state
+ MultiProcessStateStoreTests.test_concurrent_processes_share_key_state_without_lock_errors
+ RunAllBeforeDeadlineTests.test_deadline_returns_timeout_rows_without_waiting_for_slow_tasks
+ SiteMemoryPrivacyTests.test_attempt_history_is_bounded_per_site
+ SiteMemoryPrivacyTests.test_error_message_is_scrubbed
+ SiteMemoryPrivacyTests.test_old_attempts_are_purged
+ SiteMemoryPrivacyTests.test_query_tokens_are_not_persisted
```
