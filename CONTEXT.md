# Multi-Search

搜索候选、摘要、正文、抓取和桌面端的概念定义。字段映射与运行规则见 [术语及接口说明](docs/glossary.md)，文档分类见 [文档索引](docs/README.md)。

## Language

**候选（SearchHit）**：指向一个来源的搜索结果，包含标题、链接和可选摘要。排序入选后可附带正文预览，摘要与正文各自保留。

**摘要（Snippet）**：帮助判断某个候选是否值得阅读的简短描述或原文片段。同一来源可以同时提供摘要和正文。

**正文（Body）**：后端为一个来源实际取得的网页文本，或平台帖子及其回复。正文的存在不以其字符数判断，也不包含仅有的搜索高亮片段。

**预览（Preview）**：本次响应为展示而截取的正文片段。缩短预览不应缩短已经取得并保留的正文。

**来源引用（Source reference）**：一次搜索响应中某个来源的短期身份，用于后续获取和阅读内容。它不同于该来源的永久身份。

## 抓取

**抓取链（Scrape chain）**：通用网页抓取依次尝试的后端顺序（`jina`、`exa`、`tavily`、`firecrawl` 的有序子集），保存在设置的 `scrape_backends` 中。前一个后端失败才尝试下一个，最后一个也失败时返回错误；缺 key 的后端在运行时跳过。Reddit 与 Twitter/X 按域名固定使用专用抓取器，不受抓取链影响。单次 `fetch --backend` 只覆盖本次调用，不改写设置。

**站点抓取记忆（Site memory）**：按站点键记录各抓取后端的成功、失败、冷却和手动偏好。手动固定的后端排到该站点最前，失败冷却只让该后端靠后；它在抓取链的顺序上做调整，不按历史成功率自动重排。可按单个站点或全部站点重置。

## 桌面端

**受管 CLI（Managed CLI）**：由桌面端从应用资源内的受控 bundle 安装，每个平台用自己的根目录和产物名：
Windows 是 `%LOCALAPPDATA%\MultiSearch\cli` 下的 `multi-search.exe`，macOS 是 `~/Library/Application Support/MultiSearch/cli` 下的 `bin/multi-search`。
两者的 bundle 都自带运行时：Windows 携带内置 CPython，macOS 携带 `runtime/bin/python3.12`，因此安装后不依赖仓库、开发虚拟环境或系统 Python。
`active.json` 记录当前生效版本；桌面端只运行受管目录或 PATH 中发现的 CLI，前端不能指定可执行路径。
Unix 上还要求产物与 `runtime/bin/*` 保持可执行位，权限被改动即判为不可验证，不再当作已安装。
旧版本保留为可回滚的引用；取消/关闭只结束本次受管执行及其子进程（Windows 用 Job Object 归属）。

**bundle 锚点（Bundle anchor）**：受控构建脚本对 bundle 的 `manifest.json` 原始字节计算的 SHA-256，编译进桌面二进制。安装或更新时先比对锚点，再解析 manifest 并逐文件核对大小与哈希；不匹配即拒绝，不覆盖未知安装。

**Windows 凭据库（Credential store）**：桌面端与 CLI 共用的搜索 Key 存储，位于 `~/.multi-search/config.sqlite`（`MULTI_SEARCH_CONFIG_DB` 可为隔离运行改指路径），每个 provider 一行，值以当前 Windows 用户的 DPAPI 加密，非 Windows 不可用且没有明文回退。Key 来源优先级是环境变量（`env`）> 凭据库（`credential_store`）> `~/.search-keys.json`（`keys_file`）；凭据库条目损坏或无法解密时该 provider fail-closed，不回退明文文件。旧的 Windows 凭据管理器通用凭据 `multi-search/<provider>` 只作为显式迁移源读取，不再写入。

**Twitter Cookie 托管（Managed Twitter cookies）**：Twitter/X 的 Cookie 有两种模式。`file`（缺省）读取设置中的明文 Cookie 文件路径；`managed` 是用户在桌面端显式导入后，把 Cookie 以当前用户 DPAPI 加密存入凭据库，实际调用 X 时才解密，不写临时明文文件，也不进入 API-key 轮换。`managed` 缺失、损坏或在非 Windows 上一律 fail-closed，不回退旧文件。协议、存储校验与威胁边界见 [Cookie 协议](desktop/src-tauri/COOKIE-PROTOCOL.md)。

**受管 Skill（Managed Skill）**：桌面端安装到 `.claude/skills/multi-search` 的 Skill。仓库 `skills/multi-search/` 是唯一权威来源，桌面二进制在编译期原样打包其全部 5 个文件；`skill_version` 是打包内容的哈希，内容变化即提示更新。安装、更新和移除只触碰本工具写入并记录在 marker 中的文件。
