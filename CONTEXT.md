# Multi-Search

搜索候选、摘要、正文、抓取和桌面端的概念定义。字段映射与运行规则见 [术语及接口说明](docs/glossary.md)，文档分类见 [文档索引](docs/README.md)。

## Language

**候选（SearchHit）**：指向一个来源的搜索结果，包含标题、链接和可选摘要。排序入选后可附带正文预览，摘要与正文各自保留。

**摘要（Snippet）**：帮助判断某个候选是否值得阅读的简短描述或原文片段。同一来源可以同时提供摘要和正文。

**正文（Body）**：后端为一个来源实际取得的网页文本，或平台帖子及其回复。正文的存在不以其字符数判断，也不包含仅有的搜索高亮片段。

**预览（Preview）**：本次响应为展示而截取的正文片段。缩短预览不应缩短已经取得并保留的正文。

**来源引用（Source reference）**：一次搜索响应中某个来源的短期身份，用于后续获取和阅读内容。它不同于该来源的永久身份。

**插件（Provider plugin）**：一个服务商的声明单元，统一给出 id、展示名、Key 提供者、负责的搜索源与抓取通道、登录方式和余额查询能力。插件 id 与 Key 文件的条目名一致；内置插件固定随程序加载，不支持第三方或外部插件。搜索源和抓取通道都由插件声明生成，同一服务商的不同能力归入同一个插件。

**余额（Balance report）**：某个服务商某个凭据的额度报告。状态区分正常、不支持、需要凭据和查询失败；数值按 Key、团队或账户三个作用域之一给出，并带单位、重置时间和查询时间。未知数值留空而不是填 0；一家服务商查询失败不影响其他服务商。成功结果按插件声明的时长缓存，刷新可跳过缓存。

**登录方式（Auth method：api / oauth）**：插件声明的一种凭据取得方式。`api` 从标准输入读取 Key（不经过命令行参数）并写入 Key 文件；`oauth` 用浏览器授权或设备码换到凭据，其中 Firecrawl 换到的 API Key 存入 Key 文件，Parallel 的账户令牌存入独立的 OAuth 文件。一个插件可以同时声明多种登录方式，`login` / `logout` 只操作已声明的凭据条目。

**管理凭据（Balance-only credential）**：只用于查询余额、不用于搜索的独立凭据条目，例如 Exa 的 `exa_admin`（Team Management service key）和 Parallel 的 `parallel_account`（设备码登录得到的 Account API 令牌）。它与搜索 Key 分开保存；缺失时余额显示「需要凭据」，登录或退出只影响余额查询。

## 路由

**路由（Route）**：按用途组织的一组搜索源，带有展示标签、可选的 `description`（何时使用）和组超时。路由发现以 `multi-search routes` 为准；按描述选择，无描述时参考标签与实际参与源，不传 `--route` 使用发现输出中的 `default_route`。设置结构与维护规则见 [路由文档](docs/route-capability-table.md#路由发现与设置维护)。

## 抓取

**抓取链（Scrape chain）**：通用网页抓取依次尝试的通道顺序，保存在设置的 `scrape_backends` 中。通道是「服务 + 用法」：Jina 和 Firecrawl 各有 Key 通道和匿名通道（`jina_key`、`jina_anon`、`firecrawl_key`、`firecrawl_anon`），Exa、Tavily 只有 Key 通道；出厂顺序先用 Jina Key。旧的 `jina`、`firecrawl` 仍按原行为生效。前一个通道失败才尝试下一个，最后一个也失败时返回错误；没有可用 key 的 Key 通道在运行时跳过。每个通道的一次调用最多等 `scrape_backend_timeout` 秒（默认 10），超时即换下一个。Twitter/X 按域名固定使用专用抓取器，不受抓取链影响。单次 `fetch --backend` 只覆盖本次调用，不改写设置。

**站点抓取记忆（Site memory）**：按站点键记录各抓取后端的成功、失败、冷却和手动偏好。手动固定的后端排到该站点最前，失败冷却只让该后端靠后；只有目标网站自身的失败（被拦截、目标超时、目标 4xx/5xx）会写入冷却，抓取服务自己的鉴权失败和整批时限耗尽只计统计，内容很短但抓取成功的页面计为成功。它在抓取链的顺序上做调整，不按历史成功率自动重排。可按单个站点或全部站点重置；按网址操作时会先规整成同一个站点键。

## 排序

**重排（Rerank）**：在两级 RRF 融合之后、正文抓取之前，用可选的外部模型给候选打相关性分数（`relevance_score`，[0,1]），再与 RRF 分数按权重综合后重新排序；默认关闭，排序完全由 RRF 决定且不产生任何模型调用。

**综合排序（Blended rerank）**：模型分和 RRF 分先各自在本次被打分的候选里按最高、最低值缩放到 0–1，再按 `ranking.model_weight`（模型的份额，默认 0.5，其余给 RRF）加权求和，按这个综合分排序；归一化让权重不受两边原始数值大小影响。`model_weight=1` 只看模型，`0` 保持 RRF 顺序。`relevance_score` 始终是模型自己的分数，综合分只出现在过程数据里。

**同站上限（Per-site cap）**：最终 15 条里同一网站（去掉 `www.` 的主机名）最多保留 `max_results_per_site` 条（默认 3，1–15，15 即不限）；超出的页面排到其他网站之后，其他网站候选不够时才补回。它在重排或 RRF 之后执行，所以重排名次靠前的页面也可能因所在网站已满而不在最终结果里。

**重排端点（Rerank endpoint）**：打分模型所在的 System One 服务，由 `ranking.base_url` 与 `ranking.model` 指定，请求发往 `{base_url}/systemone`；开启重排时两者都必填。API 密钥不属于设置，保存在 `~/.multi-search/keys.json` 的 `systemone` 条目，环境变量 `SYSTEMONE_API_KEY` 优先。

**重排回退（Rerank fallback）**：模型阶段出现任何失败（缺 key、超时、限流、鉴权或响应非法）时整体放弃重排，保留完整 RRF 顺序，响应标记 `mode_used="rrf"` 与无凭据的 `fallback_reason`，所有 `relevance_score` 为 `null`。

**相关性分数（Relevance score）**：重排模型对单条候选的归一化评分，只在模型实际打分成功时出现；未打分或纯 RRF 响应中恒为 `null`，不渲染为 0。

## 用量

**用量（Usage）**：本机的用量视图，按服务商汇总余额、余额历史、配速与本机调用统计，供 `multi-search usage` 与桌面端「05 用量」页展示。它只读本机数据：不加 `--refresh` 时不发任何网络请求，加 `--refresh` 时按 `balance` 的规则（含各插件缓存时长）查询一次余额。数值未知一律显示为「未知」，不填 0。

**余额历史（Balance history）**：每次真正向服务商查询（非缓存命中）得到成功（`ok`）余额报告时，在本机追加一条记录；缓存命中和非 `ok` 报告不写。记录按 Key 指纹、作用域、单位与查询时间去重，保留最近 30 天，过期记录随每次写入顺带清理。

**本机调用统计（Local call counts）**：按本地日历天、服务商（插件 id）与用途（搜索 / 抓取）累计本机实际发出的调用次数和失败次数，保留 30 天。它统计的是**本机统计**，即本机发出的调用，不等于服务商侧的计费次数（服务商内部重试、一次请求扣多个积分等都不会反映在这里）。`--no-state` 的搜索不写统计；写入失败只被忽略，不影响搜索结果和退出码。

**配速（Quota pace）**：根据当前周期内的余额历史点推算的消耗速度，用「每天消耗多少额度」表示，并给出预计用完时间与「能否撑到重置」。至少需要两个点且时间跨度至少 1 小时才计算，否则显示「数据不足」；剩余量变大（充值或重置）视为新的起点。计算在 Core 中完成，CLI 与桌面端共用同一结论。

## 桌面端

**受管 CLI（Managed CLI）**：由桌面端从应用资源内的受控 bundle 安装，每个平台用自己的根目录和产物名：
Windows 是 `%LOCALAPPDATA%\MultiSearch\cli` 下的 `multi-search.exe`，macOS 是 `~/Library/Application Support/MultiSearch/cli` 下的 `bin/multi-search`，Linux 是 `$XDG_DATA_HOME/MultiSearch/cli`（否则 `~/.local/share/MultiSearch/cli`）下的 `bin/multi-search`。
各平台的 bundle 都自带运行时：Windows 携带内置 CPython，macOS 与 Linux 携带 `runtime/bin/python3.12`，因此安装后不依赖仓库、开发虚拟环境或系统 Python。
`active.json` 记录当前生效版本；桌面端只运行受管目录或 PATH 中发现的 CLI，前端不能指定可执行路径。Linux 没有用户 PATH 注册后端，用户 PATH 存储读取失败时发现逻辑回退到进程 PATH，已安装的受管 CLI 仍可用于 Skill 安装、更新和测试搜索。
Unix 上还要求产物与 `runtime/bin/*` 保持可执行位，权限被改动即判为不可验证，不再当作已安装。
旧版本保留为可回滚的引用；取消/关闭只结束本次受管执行及其子进程（Windows 用 Job Object 归属）。

**bundle 锚点（Bundle anchor）**：受控构建脚本对 bundle 的 `manifest.json` 原始字节计算的 SHA-256，编译进桌面二进制。安装或更新时先比对锚点，再解析 manifest 并逐文件核对大小与哈希；不匹配即拒绝，不覆盖未知安装。

**Key 文件（Keys file）**：桌面端与 CLI 共用的搜索 Key 存储，所有平台都是 `~/.multi-search/keys.json` 这一个明文 JSON 文件（Unix 上 0600，仅当前用户可读写）。Key 来源优先级是环境变量（`env`）> Key 文件（`keys_file`）。写入方（桌面端编辑器、Jina 软删除、System One 密钥）都原子替换、只改动自己的条目并保留其余内容；文件无法解析时视为错误，不会被覆盖。旧的 `~/.search-keys.json` 只在新文件不存在时被复制一次，旧文件不修改也不删除；早期 Windows 版本写在 `config.sqlite` 中的 DPAPI 加密条目不再读取。

**Twitter Cookie 导入（Twitter cookie import）**：Twitter/X 的 Cookie 只有文件模式，按 `TWITTER_COOKIES_PATH` > 设置中的 `twitter_cookies_path` > Key 文件的 `twitter` 条目读取。桌面端“Cookie 导入”把选定的 Cookie JSON 校验后复制到 `~/.multi-search/twitter-cookies.json`（0600）并写入 `twitter_cookies_path`；删除只移除这份副本。旧设置中的 `twitter_cookies_mode` 被忽略。协议见 [Cookie 协议](desktop/src-tauri/COOKIE-PROTOCOL.md)。

**受管 Skill（Managed Skill）**：桌面端安装到 `.claude/skills/multi-search` 的 Skill。仓库 `skills/multi-search/` 是唯一权威来源，桌面二进制在编译期原样打包其全部 5 个文件；`skill_version` 是打包内容的哈希，内容变化即提示更新。安装、更新和移除只触碰本工具写入并记录在 marker 中的文件。
