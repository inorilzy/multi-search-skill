# 抓取链功能交接

## 2026-10-22 主分支集成更新（优先于后续历史记录）

- C 主仓库与 D 克隆的 `main` 均已快进到修复提交 `d058f7d`；集成树同一代码版本。没有 push 或同步部署副本。
- 功能来自 `multi-search-scrape-integration`，不是重新合并两个旧 CLI/desktop 切片。两个旧切片保留原有未提交修改；T2 独立工作树的 5 个文件已审查集成。目录及 DAG 见 `docs/scrape-chain-acceptance-tickets.md`。
- 独立审查发现并闭合两个验收 runner 阻塞项：同版本 wheel 强制重新安装并逐字节比对；拒绝无所有权目录后不再写入。另修复父解释器 PYTHONHOME 污染，保留运行时 guard。独立 reviewer 已接受；默认 3.12 在同一 evidence 目录连续两次真实 runner PASS，69 个 Python 文件逐字节一致，guard 0 违规。
- Rust 产品源码自 `39dcba0` 未变：完整默认回归 146 passed、2 ignored；feature suites 49 passed、1 ignored，真实 bundle 独立运行 1 passed。最终 Python 全量 810 tests、0 skipped；前端 113 passed、typecheck 通过。正式类型生成器前后 SHA-256 均为 `BB0374778105B288C09ED7D80B6B388CF39FBA12498844E792118444366C925F`，无 diff。证据 `D:\scrape-final-39dcba0`。
- T3 真实 bundle 验收已执行。T4 临时配置真实 UI 已验证排序/停用/保存、缺 key 限制、pin 和 Jina 元数据；最终“确认清除”未点击，等待用户动作时确认。外部付费提供商、真实用户配置和部署均不在本轮范围。
- 当前未宣称全部任务完成。此节和验收台账优先于下方“不合 main / 未执行 UI”等历史记录。

## 2026-10-22 接手更新（优先于下方历史记录）

- 已用 PowerShell 核实工作树 `C:\Users\zhiyu_liu\multi-search-scrape-integration`、分支 `integration/scrape-chain`、基线 `3fd1aa149d87c991c167a9979b81d9819f1df72e`；接手时暂存区为空。Git 可用，不需要修复或继续重试 Git Bash。
- #5 的原有测试已实际运行；在此基础上修复旧 Jina key 首尾空白导致元数据匹配失败的问题。按编辑器的 trim 语义匹配，但保留原条目和全部元数据；重复 key 仍按原顺序逐个消费。
- 另有三处已复现并修复：站点 pin/reset 的失败提示被重绘清除；保存期间草稿仍可编辑并被响应覆盖；DPAPI 无效密文被错误归类为暂时不可用。DPAPI 只将解密错误 13/87 归为不可读，数据库及其他临时错误仍为 unavailable。
- 最终 Rust 回归还复现了 `ui_contract` 生成与读取同一文件的竞态：生成器逐类型重写时，漂移检查读到缺少类型的半成品。为同一测试进程的生成/读取加互斥，保留默认测试并发，不改产品代码、不靠全局串行绕过。
- Rust -> 临时 DPAPI SQLite -> Python CredentialStore/jina_config_keys 测试真实调用主仓库 venv 的 Python，覆盖普通及带空白的 exhausted 条目；没有解释器缺失时跳过的路径。桌面保存抓取顺序 -> Python 配置解析也有断言。
- Python 全量：793 tests，OK，0 skipped。此前 5 个 handoff 用例通过 Rust 在临时目录生成的 SQLite 夹具补齐，没有使用真实用户配置。
- 前端：111/111 tests；`npm run typecheck` 通过。新增故障测试均先记录失败，再验证修复。
- 类型生成器 `cargo test --no-default-features --test ui_contract emit_types_d_ts` 通过，生成前后 `desktop/ui/types.d.ts` SHA-256 均为 `BB0374778105B288C09ED7D80B6B388CF39FBA12498844E792118444366C925F`，前后 diff 相同。生成文件自带行尾空格，保留正式生成器输出；其他源码 `git diff --check` 通过。
- Rust 最终默认特性 `cargo test`：144 passed、0 failed、1 ignored（真实 installed CLI 验收，需独立受控环境）；额外 `--no-default-features --features install-test-boundary --test install --test install_lifecycle`：39 passed、0 failed、1 ignored（真实 release bundle 验收）。两条命令退出码均为 0。统一使用临时 `CARGO_TARGET_DIR`，不关闭运行中的桌面程序。
- 日志位于 `%TEMP%\multi-search-scrape-resume-20261022`，仅含测试夹具和验证输出，不纳入 Git。
- 独立 reviewer 委派 NOT RUN：当前 spawn 接口拒绝角色要求的 `gpt-6.1-sol`，未更换模型重试；复核由主代理完成。真实桌面 UI 人工验收及外部提供商在线请求 NOT RUN，不能把 DOM/IPC 契约测试等同于人工验收。
- 本次仅本地提交；不 push、不合 main、不部署，不修改真实用户配置。下方“未测试/未提交/Git 无法运行”均为接手前的历史状态，不代表本节完成后的状态。
- #5 元数据修复和 #4 本地最终回归已完成；真实 UI、真实安装包、部署及主分支验收仍未执行。

## 接手前历史记录

## 位置与交付状态

- 实际修改目录：`C:\Users\zhiyu_liu\multi-search-scrape-integration`
- 分支（之前已确认，接手时需重新核实）：`integration/scrape-chain`
- 基线：`3fd1aa1`
- 源码主仓库：`C:\Users\zhiyu_liu\multi-search-skill`
- 当前会话目录 `C:\Users\zhiyu_liu\.agents\skills\multi-search` 是部署副本，不是本次修改位置；未同步部署副本。
- 两个最初的实现工作树：`multi-search-scrape-cli`、`multi-search-scrape-desktop`，均在 `C:\Users\zhiyu_liu` 下。最终修复在集成工作树，不要以两个初始切片作为最新版本。
- 本轮未创建任何提交、未推送、未合入 main。用户已授权将可提交部分先提交；但 Git Bash 初始化失败，无法检查实时 diff/index 或执行提交。
- 用户希望由另一个 Agent 接手，原团队已停止，请不要自动恢复原团队或重复实现。

## 用户要求

只做一条全局抓取有序 fallback 链，支持后端排序、启停、站点记忆可视化；不做加权分配、多路由组。修完发现的问题。不要修改真实用户配置或部署副本；本次提交授权不包含 push 或合 main。

## 已完成且有验证证据的范围

### 抓取链原功能

- Python 解析 `scrape_backends`：缺失/null 使用 jina → exa → tavily → firecrawl；拒绝空数组/非法元素/未知名称；去重保序。
- 配置链非 strict，缺 key 的必需凭据后端跳过；显式 `--backend` 保持 strict。
- 站点记忆排序使用 pin、配置链顺序、冷却降级，不再按历史成功数自行调整。
- 桌面“06 抓取设置”：排序、停用、加入链尾、恢复默认、保存；站点记忆筛选、固定、重置。
- 修复平台行错误显示固定按钮、链外后端固定无效、只读状态按钮重建后可编辑、非法保存链静默回落、pin 非原子写入。

### T1：Jina 凭据入口

- Rust provider 清单与凭据命令支持 Jina。
- 新增仅抓取凭据编辑入口；不进入搜索源、搜索路由或搜索连接测试。
- `ProviderInfo.search` 能力字段及对应契约同步。
- 正式类型生成和定向验证完成。

### T2：抓取链可用性提示

- 仅 Exa/Tavily 要求 key；Jina/Firecrawl 允许匿名。
- 全链均确定缺少必需凭据或无法解密时阻止保存；有可用 fallback 时提示但不阻止。
- mount/refresh/save 前刷新凭据状态；已保存链失去 key 时显示提示。
- 不读取 secret；未知状态、状态接口失败、瞬时 cooldown 不当作永久缺 key。

### T3：上述版本全量回归

代理报告（这是后续 #5 修改之前的结果，不能用于证明当前整个工作树已通过）：
- Python unittest：Ran 793，OK，skipped=5。
- npm test：109/109。
- npm run typecheck：通过。
- cargo test：默认 target 首轮因运行中的桌面 exe 被占用而失败；改用临时 CARGO_TARGET_DIR 后通过。
- 首轮曾用 grep 管道导致错误显示 exit 0，后续执行必须保留真正的 cargo 退出码。
- 未做真实桌面 UI 人工验收，前端证据主要为模拟 DOM 测试。

## 已写代码、但未验证：任务 #5

T3 发现 Jina 结构化条目（例如 `{key, exhausted: true}`）在编辑保存时被摊平，导致元数据丢失、已排除的 key 重新进入轮换。

实现者报告已写：
- `credential.rs` 中 `merge_jina_metadata` 与 save：按完整 key 匹配原条目；未修改或仅重排保留所有字段；修改文本视为新字符串 key；删除移除条目；重复 key 按原顺序逐个匹配。
- 已存条目读取失败时拒绝保存，避免静默丢失元数据。
- `lib.rs`：native_editor_save 测试入口。
- `tests/credential_sources.rs`：内存后端保存回归及不可读时拒绝保存。
- `tests/sqlite_credentials.rs`：Rust 经编辑器写入临时 DPAPI SQLite，Python CredentialStore/jina_config_keys 读取，断言 exhausted 不进入轮换。
- `ui/credentials.js`：编辑语义说明。

以上文件相对路径均位于 `desktop/src-tauri/`（Rust）或 `desktop/`（ui）。具体当前差异需接手 Agent 读取确认。

**#5 的任何测试都没有执行成功启动，不得标记为已验证。** 这些文件与 T1 的已验证改动可能重叠，不能按整文件简单分为可提交/不可提交。

## 未完成：任务 #4

依赖 #5：
1. 对抗式复核元数据保留、修改/删除/重复 key 的语义。
2. 执行 Rust→DPAPI SQLite→Python 的跨语言测试。
3. 重跑 Python unittest、npm test、typecheck、完整 cargo test。
4. 正式生成器运行前后对比 `desktop/ui/types.d.ts` 哈希与 diff。
5. 报告真实 UI 验收覆盖限制，不把测试通过等同人工验收。

## 提交边界与建议

当前不能确认精确可提交集合：Git 无法运行，无法查看 index、diff、用户其他改动、当前分支或提交历史。

- 候选可提交范围：原抓取链功能、T1、T2，以及其此前已验证的测试与契约。
- 暂不作为已验证提交：#5 的元数据修复与新增跨语言测试。
- 最安全路径：先恢复执行环境，验证 #5，再完成 #4，检查完整 diff 后提交完整功能。
- 如必须先提交已验证部分：必须逐 hunk 区分 T1 与 #5 的重叠修改，保留 #5 工作区内容；不要 restore/reset --hard 丢弃未验证修改。提交前重新验证暂存版本。
- 本交接文档可纳入提交，但不要把真实凭据、运行数据库、node_modules、编译产物加入提交。

## 环境阻塞

Git Bash 在执行命令前初始化失败：

```
fatal error - add_item ("\\??\\C:\\Program Files\\Git", "/", ...) failed, errno 1
exit 5
```

主会话和各代理均复现，普通/非沙箱都失败。2026-10-22 用户要求提交后，主会话再次执行 git status/branch 仍在 shell 初始化阶段失败，未执行 Git。

根因尚未查明；不能断言 Git 安装损坏或进程过多。不应未经授权重启系统、杀其他会话或执行管理员修复。桌面工具按名称打开 PowerShell/Terminal 返回未在应用清单中找到。应由接手环境使用可用 shell 验证，而不是反复重试同一失败调用。

## 恢复后的命令参考

先执行 git status、git diff（包含 staged）、git log，核实分支和用户其他改动。以下命令由可用 shell 运行，按 shell 调整语法。

定向 Rust（临时 target 避免运行中的桌面 exe 占用）：

```bash
CARGO_TARGET_DIR=C:/Users/zhiyu_liu/AppData/Local/Temp/multi-search-jina-metadata-target cargo test --manifest-path C:/Users/zhiyu_liu/multi-search-scrape-integration/desktop/src-tauri/Cargo.toml --no-default-features --test credential_sources --test sqlite_credentials --lib
```

集成树根目录：

```bash
C:/Users/zhiyu_liu/multi-search-skill/.venv/Scripts/python.exe -m unittest discover -s tests -t .
```

集成树 desktop 目录：

```bash
npm test
npm run typecheck
```

完整 Rust 回归也使用临时 CARGO_TARGET_DIR，不关闭用户正在运行的应用。不要通过 grep 等管道丢失测试退出码。跨语言测试必须确认实际调用了 Python，而不是因找不到解释器跳过。

## 最终状态

- #1 completed：Jina 凭据支持与入口（#5 修改前已验证）。
- #2 completed：链可用性校验。
- #3 completed：第一轮全量复核，发现 #5 问题。
- #5 in_progress：修复和测试代码已写，尚未执行验证。
- #4 pending：最终复核及全量回归尚未开始。
- 提交：未执行成功，不能提供新 commit SHA。
