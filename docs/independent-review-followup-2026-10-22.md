# F-01–F-04 独立后续复验（t18）

## 结论

**FAILED：F-04 新增 CI 矩阵入口不能在干净环境导入仓库 scripts。** F-01 的代码与合成 transport 回归通过（真实 socket 验证受主机权限限制）；F-02/F-03 关闭。本报告不替代原审查的延期项与未验收边界。

固定比较基线 `c035da15e6113be84e4634ce28d1a591178c1fb6`，HEAD `5c2de01ccb33a7598937d71fbd6b1d0d2c41570c`。419 个已跟踪及非忽略新文件开始/结束 SHA256一致，包含本轮未提交实现。清单：[start](verification-evidence/t18-start-hashes.json)、[end](verification-evidence/t18-end-hashes.json)。不包含验证证据目录本身。未修改产品实现、真实用户配置/凭据/PATH/安装，未提交。

## 独立回归

| 命令 | 结果 |
|---|---|
| `.venv/Scripts/python.exe scripts/run_tests.py` | 860 tests，5 skipped，74.462s，exit0 |
| `npm --prefix desktop test` | 138 passed，0 skipped，exit0 |
| `npm --prefix desktop run typecheck` | exit0 |
| `cargo test --manifest-path desktop/src-tauri/Cargo.toml --no-default-features --features test-fixtures,ts` | 172 passed，3 ignored，exit0 |
| `.venv/Scripts/python.exe -m unittest tests.test_proxy_trust_boundary -v` | 8 passed，exit0 |
| `python scripts/check_glossary_paths.py` | exit0 |
| 临时 CI import 探针，清空 PYTHONPATH | child exit1，ModuleNotFoundError |
| 真实本地代理探针 | exit1，WinError10013（主机 socket 权限拒绝），未冒充通过 |

日志：[Python](verification-evidence/t18-python.log)、[UI](verification-evidence/t18-ui.log)、[类型](verification-evidence/t18-types.log)、[Rust](verification-evidence/t18-rust.log)、[代理回归](verification-evidence/t18-proxy-unit.log)、[真实socket探针](verification-evidence/t18-local-proxy.log)。所有后台任务已收集。

t14 完整 native/install 矩阵与真实视觉证据仍作为未变更领域的历史证据，本轮未重复运行 native/install/视觉；不把历史计数写成此次执行。

## F-01：修复通过（限定证据）

[http.py](../multi_search_mcp/src/support/http.py#L140-L159) 使用 req.has_proxy() / _tunnel_host + 精确host:port，解析后的代理地址豁免仅在实际proxy-hop分支。8项测试验证localhost、IPv4/IPv6、错误端口、直接loopback/private、redirect拒绝。旧失败路径已被覆盖，未观察直接目标被当成代理。

### req.host 信任分析

独立读取当前 Python urllib 源码：
- `Request.has_proxy()` 是 `self.selector == self.full_url`，不是一个HTTP header。
- 正常 `Request(url)` 的 `_parse()` 将scheme后的host和selector分离，`_tunnel_host` 默认为None。远程URL和响应头不能直接设置这两个Python属性。
- `Request.set_proxy()` 对HTTP把selector设为full_url，并把host改为代理host；HTTPS设置_tunnel_host并改host。这发生于本地ProxyHandler，不由远端页面执行。
- 正常loopback、含嵌套http字符串的path、userinfo URL以及异常斜杠样例均 has_proxy=False。
- 本地Python调用者能构造/修改Request属性或自定义handler，因此该helper并非防御恶意嵌入代码的安全边界；本产品外部输入为URL/文本，不是任意Python Request实例。没有发现远端目标能够通过HTTP参数/headers伪造该标志的可利用路径。

真实本地合成HTTP代理脚本 [t18-local-proxy.py](verification-evidence/t18-local-proxy.py) 只绑定loopback，使用 `.invalid` origin以避免外网，计划验证localhost/IPv4/IPv6转发与拒绝边界；主机连接在第一轮被WinError10013拒绝，server在finally关闭。未扩大权限/改网络设置/绕过限制，**真实transport验证未完成**。当前关闭依据是源代码链路与fake socket回归，不声称真实系统代理/注册表/HTTPS CONNECT全覆盖。

## key_state 迟到success：明确独立结论

基线 `c035da15` 已有 success 无条件写 ACTIVE、清cooldown/strikes；原报告一.5明确指出的是“超时或网络错误把key恢复ACTIVE”，不是明确规定所有失败必须压过任何并发成功。因此中性失败保持状态的原缺陷已修；不能据此推导此前存在 generation 契约。

但是实施台账“success证明凭据此刻可用”不成立：旧请求可能早已成功、响应/线程调度延迟才提交。事务只保证更新线性化，不保证事件时序符合远端因果。

- 在现有公开契约（成功回报恢复ACTIVE、允许同key并发）下，last-completion-wins **与既有行为一致，属于保留的策略限制，不作为本轮新实现回归**。
- 它不满足“新失败不能被更早开始的成功清除”的更强熔断不变式。若用户/产品要求该不变式，则**必须新增generation/状态版本或请求开始序号**；在reserve读取版本，失败变更版本，success仅在没有较新健康失败时恢复（具体排序仍需定义）。无需靠独占网络锁解决。
- 目前不能把key状态机标为fully fixed；并发测试得到两个串行结果之一，只证明无撕裂，不证明因果安全。永久invalid后的新成功可以恢复，与拒绝旧success两者并不冲突，generation可区分。

结论：原“中性错误覆盖强状态”关闭；迟到success风险 **RETAINED，需明确接受策略或另行定义generation契约**，不是“已证明并发全部正确”。

## F-02：关闭

实际读取的 [glossary](glossary.md#L63) 已写schema v2 acquisition级truncated、URL reuse/read、预览不污染；[glossary](glossary.md#L101-L103) 已写file/managed、独立secret provider、Windows限制、不回退/不删除原文件；reserve与非独占lease也明确。README同步，不再使用t9待验旧说法。路径检查通过。旧t14报告是历史版本，不要求改写旧失败事实。

## F-03：关闭

本轮 Rust 172 passed 包含新 `baidu_application_link_is_the_official_iam_key_page`。固定地址是 `https://console.bce.baidu.com/iam/#/iam/apikey/list`，UI仍由key_application_available启用。

独立抓取[百度官方Python SDK文档](https://cloud.baidu.com/doc/qianfan-docs/s/Fm9l6ocai)，HTTP200，代码注释明确将“如何获取API Key”指向该地址，并使用千帆v2基址。没有登录或调用付费API。该证据确认申请入口来自官方，不证明账户已有搜索API权限。

## F-04：未关闭；新发现 CI-01（high）

受审版本 [.github/workflows/test.yml](../.github/workflows/test.yml#L90-L128) 将runner写到 `$TEMP/t16-ci/rust_matrix.py`，第98行先执行 `from scripts.test_isolation import isolated_test_environment`，未提前设置repo sys.path；随后从临时路径执行该脚本。

Python脚本的sys.path[0]是脚本目录，不是当前工作目录。干净runner没有继承工作区PYTHONPATH，editable安装multi_search_mcp也不保证仓库scripts包可导入。

独立复现：清空进程PYTHONPATH，在repo cwd用现有 `.venv/Scripts/python.exe -B <TEMP>/t18-ci-import-....py`，脚本仅包含上述import，结果 **ModuleNotFoundError: No module named 'scripts.test_isolation'，child exit1**。因此远程CI会在运行任何Rust矩阵前失败；本地继承PYTHONPATH的成功不能反驳。

必要修复：仓库内固定脚本显式计算repo root，在任何仓库import前加入sys.path；CI调用该脚本，不依赖cwd/PYTHONPATH。验收必须清空PYTHONPATH、从任意cwd运行，并检查venv Python、rustc PATH、toolchain homes及isolation.assert_clean。captain已建t19处理；本轮不等待或擅改实现。

其他CI内容审阅：Windows runner、venv PATH、Rust homes、fetch在隔离前、offline串行5矩阵、显式overlay和ignored说明均具备；30分钟预算与WebView2检查存在。远程Actions尚未运行，不能据静态配置批准。

## 保留范围

继续承接 [t14报告](independent-review-final-2026-10-22.md) 原审查逐项表：Provider/registry签名收敛、HTTP样板统一、snapshots/evaluation/credential_store分层迁移、search/body长函数拆分、三处渲染整合、两个公共入口重复解析均DEFERRED；技能模块合并、现有页面状态机及包名布局为有理由保留。默认file cookie仍明文，managed是opt-in。真实native ACL窗口/来源、真实bundle/安装器、Linux cookie执行、远程CI仍未验证，不称全部修复。
