# Multi-Search

搜索候选、摘要、正文、抓取和桌面端的概念定义。字段映射与运行规则见 [术语及接口说明](docs/glossary.md)，文档分类见 [文档索引](docs/README.md)。

## Language

**候选（SearchHit）**：指向一个来源的搜索结果，包含标题、链接和可选摘要。排序入选后可附带正文预览，摘要与正文各自保留。

**摘要（Snippet）**：帮助判断某个候选是否值得阅读的简短描述或原文片段。同一来源可以同时提供摘要和正文。

**正文（Body）**：后端为一个来源实际取得的网页文本，或平台帖子及其回复。正文的存在不以其字符数判断，也不包含仅有的搜索高亮片段。

**预览（Preview）**：本次响应为展示而截取的正文片段。缩短预览不应缩短已经取得并保留的正文。

**来源引用（Source reference）**：一次搜索响应中某个来源的短期身份，用于后续获取和阅读内容。它不同于该来源的永久身份。

## 路由

**路由（Route）**：按用途组织的一组搜索源，带有展示标签、可选的 `description`（何时使用）和组超时。路由发现以 `multi-search routes` 为准；按描述选择，无描述时参考标签与实际参与源，不传 `--route` 使用发现输出中的 `default_route`。设置结构与维护规则见 [路由文档](docs/route-capability-table.md#路由发现与设置维护)。

## 抓取

**抓取链（Scrape chain）**：通用网页抓取依次尝试的后端顺序（`jina`、`exa`、`tavily`、`firecrawl` 的有序子集），保存在设置的 `scrape_backends` 中。前一个后端失败才尝试下一个，最后一个也失败时返回错误；缺 key 的后端在运行时跳过。每个后端的一次调用最多等 `scrape_backend_timeout` 秒（默认 10），超时即换下一个。Twitter/X 按域名固定使用专用抓取器，不受抓取链影响。单次 `fetch --backend` 只覆盖本次调用，不改写设置。

**站点抓取记忆（Site memory）**：按站点键记录各抓取后端的成功、失败、冷却和手动偏好。手动固定的后端排到该站点最前，失败冷却只让该后端靠后；它在抓取链的顺序上做调整，不按历史成功率自动重排。可按单个站点或全部站点重置。

## 排序

**重排（Rerank）**：在两级 RRF 融合之后、正文抓取之前，用可选的外部模型给候选打相关性分数（`relevance_score`，[0,1]）并重新排序；默认关闭，排序完全由 RRF 决定且不产生任何模型调用。

**重排端点（Rerank endpoint）**：打分模型所在的 System One 服务，由 `ranking.base_url` 与 `ranking.model` 指定，请求发往 `{base_url}/systemone`；开启重排时两者都必填。API 密钥不属于设置，保存在 `~/.multi-search/keys.json` 的 `systemone` 条目，环境变量 `SYSTEMONE_API_KEY` 优先。

**重排回退（Rerank fallback）**：模型阶段出现任何失败（缺 key、超时、限流、鉴权或响应非法）时整体放弃重排，保留完整 RRF 顺序，响应标记 `mode_used="rrf"` 与无凭据的 `fallback_reason`，所有 `relevance_score` 为 `null`。

**相关性分数（Relevance score）**：重排模型对单条候选的归一化评分，只在模型实际打分成功时出现；未打分或纯 RRF 响应中恒为 `null`，不渲染为 0。

## 桌面端

**受管 CLI（Managed CLI）**：由桌面端从应用资源内的受控 bundle 安装，每个平台用自己的根目录和产物名：
Windows 是 `%LOCALAPPDATA%\MultiSearch\cli` 下的 `multi-search.exe`，macOS 是 `~/Library/Application Support/MultiSearch/cli` 下的 `bin/multi-search`。
两者的 bundle 都自带运行时：Windows 携带内置 CPython，macOS 携带 `runtime/bin/python3.12`，因此安装后不依赖仓库、开发虚拟环境或系统 Python。
`active.json` 记录当前生效版本；桌面端只运行受管目录或 PATH 中发现的 CLI，前端不能指定可执行路径。
Unix 上还要求产物与 `runtime/bin/*` 保持可执行位，权限被改动即判为不可验证，不再当作已安装。
旧版本保留为可回滚的引用；取消/关闭只结束本次受管执行及其子进程（Windows 用 Job Object 归属）。

**bundle 锚点（Bundle anchor）**：受控构建脚本对 bundle 的 `manifest.json` 原始字节计算的 SHA-256，编译进桌面二进制。安装或更新时先比对锚点，再解析 manifest 并逐文件核对大小与哈希；不匹配即拒绝，不覆盖未知安装。

**Key 文件（Keys file）**：桌面端与 CLI 共用的搜索 Key 存储，所有平台都是 `~/.multi-search/keys.json` 这一个明文 JSON 文件（Unix 上 0600，仅当前用户可读写）。Key 来源优先级是环境变量（`env`）> Key 文件（`keys_file`）。写入方（桌面端编辑器、Jina 软删除、System One 密钥）都原子替换、只改动自己的条目并保留其余内容；文件无法解析时视为错误，不会被覆盖。旧的 `~/.search-keys.json` 只在新文件不存在时被复制一次，旧文件不修改也不删除；早期 Windows 版本写在 `config.sqlite` 中的 DPAPI 加密条目不再读取。

**Twitter Cookie 导入（Twitter cookie import）**：Twitter/X 的 Cookie 只有文件模式，按 `TWITTER_COOKIES_PATH` > 设置中的 `twitter_cookies_path` > Key 文件的 `twitter` 条目读取。桌面端“Cookie 导入”把选定的 Cookie JSON 校验后复制到 `~/.multi-search/twitter-cookies.json`（0600）并写入 `twitter_cookies_path`；删除只移除这份副本。旧设置中的 `twitter_cookies_mode` 被忽略。协议见 [Cookie 协议](desktop/src-tauri/COOKIE-PROTOCOL.md)。

**受管 Skill（Managed Skill）**：桌面端安装到 `.claude/skills/multi-search` 的 Skill。仓库 `skills/multi-search/` 是唯一权威来源，桌面二进制在编译期原样打包其全部 5 个文件；`skill_version` 是打包内容的哈希，内容变化即提示更新。安装、更新和移除只触碰本工具写入并记录在 marker 中的文件。
