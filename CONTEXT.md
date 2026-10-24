# Multi-Search

搜索候选、摘要、正文和桌面端的概念定义。字段映射与运行规则见 [术语及接口说明](docs/glossary.md)，文档分类见 [文档索引](docs/README.md)。

## Language

**候选（SearchHit）**：指向一个来源的搜索结果，包含标题、链接和可选摘要。排序入选后可附带正文预览，摘要与正文各自保留。

**摘要（Snippet）**：帮助判断某个候选是否值得阅读的简短描述或原文片段。同一来源可以同时提供摘要和正文。

**正文（Body）**：后端为一个来源实际取得的网页文本，或平台帖子及其回复。正文的存在不以其字符数判断，也不包含仅有的搜索高亮片段。

**预览（Preview）**：本次响应为展示而截取的正文片段。缩短预览不应缩短已经取得并保留的正文。

**来源引用（Source reference）**：一次搜索响应中某个来源的短期身份，用于后续获取和阅读内容。它不同于该来源的永久身份。

## 桌面端

**受管 CLI（Managed CLI）**：由桌面端从应用资源内的受控 bundle 安装到 `%LOCALAPPDATA%\MultiSearch\cli` 的 `multi-search.exe`。`active.json` 记录当前生效版本；桌面端只运行受管目录或 PATH 中发现的 CLI，前端不能指定可执行路径。旧版本保留为可回滚的引用，取消/关闭只结束本次 Job Object 归属的进程。

**bundle 锚点（Bundle anchor）**：受控构建脚本对 bundle 的 `manifest.json` 原始字节计算的 SHA-256，编译进桌面二进制。安装或更新时先比对锚点，再解析 manifest 并逐文件核对大小与哈希；不匹配即拒绝，不覆盖未知安装。

**Windows 凭据库（Credential store）**：桌面端保存单个搜索 Key 的位置，每个 provider 是一个通用凭据 `multi-search/<provider>`，内容是 UTF-8 JSON 的 `{"v":1,"key":…,"saved_at":…}`。CLI 与桌面端共用同一格式和读取规则；Key 来源优先级是环境变量 > 凭据库 > `~/.search-keys.json`，凭据库条目损坏时该 provider fail-closed，不回退明文文件。

**受管 Skill（Managed Skill）**：桌面端安装到 `.claude/skills/multi-search` 的 Skill。仓库 `skills/multi-search/` 是唯一权威来源，桌面二进制在编译期原样打包；`skill_version` 是打包内容的哈希，内容变化即提示更新。安装、更新和移除只触碰本工具写入并记录在 marker 中的文件。
