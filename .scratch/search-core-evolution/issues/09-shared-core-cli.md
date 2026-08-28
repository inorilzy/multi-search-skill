# 09: 增加共享 Core 的薄 CLI

**What to build:** 提供一个可安装的 CLI，让终端、脚本和 Agent 可以执行 search、fetch、read、doctor 以及 key 状态管理；CLI 直接调用同一 Core，并与 MCP 共享配置、密钥文件、StateStore、轮换、冷却和错误分类，不形成第二套搜索实现。

**Blocked by:** 06: 交付扩展查询两级 RRF 与失败诊断; 08: 交付 read_source 局部读取.

**Status:** resolved

- [x] 安装后提供稳定 console entry，并包含 `search`、`fetch`、`read`、`doctor`、`keys status` 和 `keys reset`。
- [x] `search` 支持 Route 或显式 Sources，并与 MCP `search_web` 产生语义一致的 SearchHit、diagnostics 和 RRF 结果。
- [x] `fetch` 与 `read` 复用相同 Source Registry、Content Store、安全校验和正文限制。
- [x] CLI 直接调用 Core 请求接口，不通过 MCP 反向调用，也不解析 MCP 展示文本。
- [x] JSON 是稳定的自动化输出；可选 Markdown 面向人工阅读且不改变 JSON 契约。
- [x] CLI 与 MCP 使用相同的配置优先级、keys file、StateStore、Provider key 轮换、site memory 和错误分类。
- [x] `keys status/reset` 操作的是 MCP 同一份 key 健康状态，且所有输出都隐藏密钥值。
- [x] `doctor` 能诊断配置、依赖、Provider/key 可用性和状态路径，不访问真实搜索网络或泄露凭据。
- [x] 失败命令提供稳定的非零退出码，机器输出与人类诊断不会相互污染。
- [x] 命令级测试使用假的 Provider、临时配置和临时状态，验证 CLI 与 Core/MCP 的契约一致性。

## Answer

已在 `f6bb21e` 完成：交付共享 Core 的 `multi-search` CLI，包括 search/fetch/read/doctor/keys status/reset、稳定 JSON 和可选 human/Markdown 输出。

验证：Python 3.11、3.12、3.14 下全量 261 项测试通过；CLI/MCP smoke、compileall、pip check 与 Standards/Spec 两轴审查通过。
