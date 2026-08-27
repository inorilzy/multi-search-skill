# 搜索核心演进：紧凑搜索、RRF 融合、按需正文与共享 CLI

Type: enhancement
Status: ready-for-agent

## Problem Statement

当前项目已经具备可复用 Core、MCP 工具、多个 source、独立 scrape backend、StateStore 与统一 key 状态管理，不需要重写整体架构。但普通搜索仍把“发现候选 URL”和“读取网页正文”耦合在一次调用中：仓库开发配置会把 `scrape_top` 覆盖为 30，导致本应快速或候选优先的 route 也可能进入批量 scrape。

搜索结果契约仍以松散字典为主，`content`、highlight、excerpt 与 `body / full_content` 的语义没有被运行时严格区分。部分 source 会把 highlight 写成 `scraped_content`，ScrapePlanner 再通过字符长度推断它是否足以代替正文。这使 source 自带摘要可能阻止后续正文抓取，也使能力表、Provider Adapter 和实际 scrape 行为发生漂移。

多 source 结果当前会被并发完成顺序影响。系统没有保留每个 provider 内部的原始 rank，也没有执行 RRF；最终排序主要依据是否带正文、跨源重复数量、正文长度和少量平台指标。因此，一个更快返回或正文更长的 source 可能获得不合理的排序优势。

响应还可能把同一正文同时放入搜索结果、正文别名、scrapes 视图和 Markdown，增加 Agent 上下文、延迟和传输体积。项目虽然已有独立 `scrape_url`，但没有稳定的 `response_id`、`source_id`、短期正文缓存和局部读取接口，Agent 无法先接收紧凑候选，再按需读取少量证据。

最后，当前唯一正式安装入口是 MCP server。用户希望可以采用 CLI + Skill，同时保留 MCP 兼容，并继续共享现有 config、keys file、StateStore、key 轮换和错误状态，而不是维护第二套业务实现。

## Solution

在保留现有 `multi_search` 和 `scrape_url` 兼容行为的前提下，增加一条候选优先的搜索路径：

- `search_web` 只负责选择 route/source、并发搜索、结果标准化、URL 去重、RRF 融合和紧凑输出，不批量 scrape 网页正文。
- 每次搜索生成 `response_id`，每条候选生成稳定的 `source_id`。
- `fetch_source` 按 `source_id` 或显式 URL 抓取一条正文，并按 provider 留存策略写入短期 Content Store。
- `read_source` 按 `source_id`、关键词、offset 和 limit 局部读取已抓取正文，避免整页反复进入模型上下文。
- Skill 对普通联网查询默认采用 `search_web → fetch_source/read_source`；现有重型 `multi_search` 继续作为显式“召回并抓取”兼容入口。
- CLI 和 MCP 都作为薄入口调用同一 Core。CLI 不拥有 provider 调度、key 状态或 scrape 逻辑。

同时补齐结果语义和排序：

- Provider Adapter 输出显式的 `content_kind`，至少区分 metadata、content、excerpt、body 和 answer。
- SearchRunner 保留每个 provider 内部 rank；跨 provider 使用等权 RRF，不直接比较 provider 原生 score。
- expanded query 采用两级 RRF：先融合同一 query 的 provider 列表，再融合不同 query 的结果列表。
- 相同 provider 的多个 key 只是失败切换或调度资源，不能在 RRF 中增加票数。
- SearchHit 只返回紧凑字段和正文可用性，不返回 body 本身。

## User Stories

1. 作为使用 Skill 的 Agent，我希望普通联网搜索先返回紧凑候选，以便快速判断哪些页面值得继续读取。
2. 作为使用 Skill 的 Agent，我希望可以按 `source_id` 抓取某一条结果，以便避免无条件抓取几十个网页。
3. 作为使用 Skill 的 Agent，我希望可以按关键词和分页参数局部读取正文，以便只把相关证据放入上下文。
4. 作为使用 Skill 的 Agent，我希望搜索结果包含稳定 URL、标题、content 和 source 信息，以便生成可验证引用。
5. 作为使用 Skill 的 Agent，我希望搜索结果说明命中了哪些 provider 及其原始 rank，以便判断结果共识来自哪里。
6. 作为使用 Skill 的 Agent，我希望 provider 部分失败时仍得到其他 provider 的结果，以便单一外部故障不阻断任务。
7. 作为使用 Skill 的 Agent，我希望 provider 失败在 diagnostics 中明确出现，以便不把部分成功误认为完整覆盖。
8. 作为使用 Skill 的 Agent，我希望普通搜索不会偷偷进入批量 scrape，以便延迟和额度行为可预测。
9. 作为进行深度调研的 Agent，我希望仍能显式使用现有召回并抓取流程，以便一次获得较多正文。
10. 作为进行多角度调研的 Agent，我希望 expanded query 的结果按两级 RRF 融合，以便不同措辞形成独立共识而不是简单混在一起。
11. 作为关注结果质量的用户，我希望排序不受 provider 响应先后影响，以便同一输入得到稳定结果。
12. 作为关注结果质量的用户，我希望多个 provider 同时命中的 URL 获得合理提升，以便优先看到跨源共识。
13. 作为关注结果质量的用户，我希望正文更长不会自动等价于结果更相关，以便避免内容长度主导排序。
14. 作为关注结果质量的用户，我希望 provider 原生 score 只用于诊断而不被直接横向比较，以便避免不同评分尺度造成错误融合。
15. 作为使用 Exa 等内容型 source 的用户，我希望 highlight 被标记为 excerpt 而不是 body，以便系统仍能在需要时抓取完整正文。
16. 作为使用 Tavily、Firecrawl 或 Baidu 的用户，我希望真正的预取正文被标记为 body，以便系统不重复 scrape。
17. 作为使用平台型 source 的用户，我希望帖子文本、社交正文和普通网页正文具有明确类型，以便 ScrapePlanner 不靠字符数猜测。
18. 作为调用 MCP 的现有用户，我希望原有 `multi_search` 和 `scrape_url` 参数及主要返回字段继续工作，以便升级不会破坏现有客户端。
19. 作为调用 MCP 的新用户，我希望使用更小、更明确的 `search_web`、`fetch_source` 和 `read_source` 接口，以便工具选择更可靠。
20. 作为 CLI 用户，我希望通过一个命令执行搜索并输出稳定 JSON，以便在终端、脚本和 Agent 中复用。
21. 作为 CLI 用户，我希望可以选择 route 或显式 sources，以便 CLI 与 MCP 的选源能力一致。
22. 作为 CLI 用户，我希望可以执行 fetch/read 操作，以便不用启动 MCP 客户端也能复现正文问题。
23. 作为 CLI 用户，我希望可以运行 doctor 和 key 状态命令，以便排查配置、依赖、额度和冷却问题。
24. 作为运维者，我希望 CLI 与 MCP 使用同一个 StateStore，以便同一 key 的 cooldown、quota_exhausted 和 invalid 状态不会分叉。
25. 作为运维者，我希望 CLI 与 MCP 使用同一 config 解析优先级，以便行为不会因入口不同而漂移。
26. 作为运维者，我希望 CLI 与 MCP 使用同一 keys file 和环境变量解析，以便无需复制或迁移现有 key。
27. 作为运维者，我希望每次 search/fetch 都有 response/source 标识，以便日志可以关联搜索与正文读取。
28. 作为运维者，我希望短期 Content Store 有 TTL、单对象大小和总容量限制，以便正文缓存不会无限增长。
29. 作为运维者，我希望可以清理过期或指定 source 的缓存，以便处理敏感内容和磁盘占用。
30. 作为维护者，我希望 route 继续表达 source 选择，以便现有 glossary 和调用习惯保持清晰。
31. 作为维护者，我希望搜索深度由工具操作显式表达，以便 route 不再同时承担“去哪里搜”和“是否抓正文”两种责任。
32. 作为维护者，我希望 Provider Capability 参与运行时内容分类和 scrape 决策，以便能力表不再只是说明文档。
33. 作为维护者，我希望新增 source 时只需实现统一 Provider Adapter 契约并注册能力，以便减少多处硬编码接线。
34. 作为维护者，我希望新增 source 的原始结果在统一归一化层转换为 SearchHit，以便 provider 私有字段不会泄漏为公共契约。
35. 作为维护者，我希望 URL canonicalization 采用保守规则，以便不会把实际上不同的 HTTP/HTTPS 页面或业务参数错误合并。
36. 作为维护者，我希望同一 provider 内重复 URL 只贡献一次 RRF 票，以便重复结果不会人为放大权重。
37. 作为维护者，我希望多个 key 的 failover 仍只产生一个 provider 排名列表，以便账号数量不会改变融合结果。
38. 作为测试维护者，我希望通过 Core 的搜索接口替换 Provider Adapter，以便不访问真实网络也能验证完整搜索行为。
39. 作为测试维护者，我希望通过临时 StateStore 验证 source/cache/key 状态，以便测试彼此隔离且可重复。
40. 作为安全维护者，我希望 fetch 只接受经过统一校验的 HTTP/HTTPS 目标，以便阻止危险协议和无效地址。
41. 作为安全维护者，我希望未来本地直抓或 HTTP 服务拒绝 loopback、private、link-local、reserved 和重定向后的危险地址，以便避免 SSRF。
42. 作为安全维护者，我希望网页正文始终被标记为不可信数据，以便页面内容不能覆盖 Agent 或系统指令。
43. 作为合规维护者，我希望每个 provider 可以声明搜索结果、content 和 body 的留存策略，以便不假设所有 provider 都允许长期缓存。
44. 作为合规维护者，我希望无法持久化的 provider 内容仍能在当前调用内短暂使用，以便兼顾功能和留存限制。
45. 作为发布维护者，我希望新能力以兼容性新增方式上线，以便可以分阶段迁移 Skill 和调用方。

## Implementation Decisions

- 现有 Core 继续作为唯一业务实现。MCP、CLI 和 Skill 不复制搜索、scrape、融合、key 轮换或状态逻辑。
- 保留现有 `multi_search` 与 `scrape_url` 作为兼容接口；新增 `search_web`、`fetch_source` 和 `read_source` 作为候选优先接口。
- `search_web` 默认不运行 scrape stage。它允许 route、sources、count、timeout 和 expand，但不通过隐式默认值批量抓正文。
- route 继续负责 source 选择；正文读取由 `fetch_source` / `read_source` 显式表达。现有 route 名称和 source 别名不在本规格中重命名。
- 仓库共享示例 config 不再用全局 `scrape_top=30` 覆盖所有 route；未显式配置时使用 route_meta。用户级 config 与请求显式值仍保持现有优先级。
- 新增稳定 SearchHit 公共投影。最小字段包括 `source_id`、`title`、`url`、`canonical_url`、`content`、发布时间、provider ranks、RRF score、body availability 和 content reference。
- 现有 `description` 继续作为兼容字段，但新公共投影使用 glossary 中的 `content` 语义；现有 `scraped_content` 继续作为兼容字段，但新逻辑使用显式 body 语义。
- 新增 `content_kind` 领域概念，并同步更新 glossary。至少支持 metadata、content、excerpt、body 和 answer。
- Provider Adapter 对返回内容进行 provider-specific 解析，统一归一化层负责生成 SearchHit。Provider 私有原始字段可保留在 diagnostics，但不得成为新公共接口的必需知识。
- Provider Capability 从说明性元数据升级为运行时决策输入。ScrapePlanner 根据 capability 和 `content_kind` 判断正文是否已存在，不再仅依赖 source 名硬编码和 300 字符阈值。
- SearchRunner 在每个 provider 返回结果后立即附加 provider rank。provider 原生 score 保留为可选诊断字段。
- 融合采用等权 RRF，初始 rank constant 为 40，rank window 为 15。没有评测数据前不配置主观 provider 权重。
- expanded query 采用两级 RRF：每个 query 先做 provider 融合，再对 query 融合结果做第二次 RRF。
- 相同 provider 的多个 key 属于同一个 provider 调度域；key failover 成功后只产生一个 provider 结果列表。
- URL canonicalization 采用保守规则：规范 scheme/host 大小写、默认端口、fragment、已知跟踪参数和 query 顺序，但不强制把 HTTP 转成 HTTPS，也不删除未知业务参数。
- `response_id` 标识一次搜索响应，`source_id` 标识该响应中的稳定候选。相同 canonical URL 在同一次响应中只保留一个 source，并保存所有 provider ranks。
- Content Store 复用本地 StateStore 的生命周期与配置入口，但正文可以使用独立表或受控文件存储，避免把大文本塞进 key/site 状态表。
- Content Store 首版只需要短期 TTL、最大对象大小、总容量限制、LRU 清理、按 source 删除和内容 hash 去重；不实现版本化历史。
- `fetch_source` 优先返回已存在且未过期的 body；没有可用 body 时调用现有 scrape backend 链，并记录实际 backend。
- `read_source` 只读取 Content Store，不隐式访问网络。缓存不存在或已过期时明确报错，并提示调用 `fetch_source`。
- `read_source` 支持关键词定位、offset 和 limit；所有返回均有硬字符上限。
- `search_web` 不返回 body。即使 provider 在搜索阶段内联 body，也只暴露 `body_available=true` 和 content reference，并按留存策略决定是否短期保存。
- 旧 `multi_search` 的响应保持兼容，但应避免继续增加 body 别名。新调用方不得依赖同一正文同时存在于多个字段。
- 新 CLI 作为单独 console entry，至少包含 search、fetch、read、doctor、keys status 和 keys reset。JSON 为自动化稳定输出，Markdown 为面向人工的可选输出。
- CLI 直接调用 Core 请求对象，不通过 MCP 反向调用，也不解析 MCP 返回文本。
- MCP 工具和 CLI 都使用现有 config、keys file、StateStore、key 轮换、site memory 和错误分类。
- 统一 URL 安全校验位于 fetch seam，而不是复制到每个 scraper。当前固定远程 scraper 继续使用，但未来本地直抓或 HTTP 暴露必须复用同一校验。
- Provider retention policy 至少表达 search result、content、body 是否可持久化以及最大 TTL。未知策略默认采用短期、最小留存。
- Skill 默认使用候选优先流程；只有用户明确要求深度调研、批量阅读或一次性正文聚合时，才调用兼容的重型入口。
- 实施按兼容性分阶段推进：先增加 SearchHit/RRF 和紧凑接口，再增加 CLI，再增加 Content Store 与 fetch/read，最后切换 Skill 默认流程。

## Testing Decisions

- 主要测试 seam 是 Core 的候选搜索接口。测试通过注入或替换 Provider Adapter，断言最终 SearchHit、diagnostics 和 provider status，不断言内部函数调用顺序。
- 第二个测试 seam 是 Core 的 fetch/read 接口。测试使用临时 StateStore 和假的 scrape backend，断言正文缓存、TTL、字符限制和错误行为。
- MCP 与 CLI 只做薄入口契约测试：相同请求应产生语义一致的 Core 输出，并共享同一状态路径。
- 保留现有 `multi_search` 和 `scrape_url` 回归测试，证明新接口没有删除或重命名旧参数和关键返回字段。
- 增加配置优先级测试，覆盖请求显式值、用户 config、route_meta 和默认值；仓库共享 config 不应意外覆盖所有 route。
- 增加候选模式测试，证明 `search_web` 不调用 scrape backend，且响应中不存在 body、full_content 或 scraped_content 大文本。
- 增加响应大小测试，使用超长 provider excerpt 和 body，证明 SearchHit content、fetch 结果和 read 分页都有明确上限。
- 增加内容分类契约测试，覆盖 metadata、content、excerpt、body 和 answer；excerpt 不得阻止显式正文抓取。
- 增加 Exa 风格 highlights 测试，证明 highlights 归类为 excerpt，而不是 body。
- 增加正文预取测试，证明真正 body 可被 Content Store 复用，且不会触发重复 scrape。
- 增加 capability 驱动测试，证明 Provider Capability 的内容和 scrape 声明与运行时 planner 一致；新增 source 漂移时测试应失败。
- 增加 RRF 确定性测试：改变 provider 完成顺序，不改变最终排序。
- 增加 RRF 共识测试：多个 provider 命中的同一 URL 应高于仅由一个 provider 低位命中的 URL。
- 增加 RRF 去重测试：同一 provider 内重复 URL 只能贡献一次。
- 增加多 key 测试：provider 从第二把 key 成功时仍只贡献一份 provider rank。
- 增加两级 RRF 测试：expanded query 的 provider 共识与 query 角度共识分别计算，不直接平铺所有列表。
- 增加 URL canonicalization 测试，覆盖 fragment、默认端口、跟踪参数、query 排序、业务参数保留以及 HTTP/HTTPS 不强制合并。
- 增加 source identity 测试，证明同一 response 中 canonical URL 稳定映射到一个 source_id，并保留多个 provider ranks。
- 增加 Content Store TTL 和 LRU 测试，使用可控时钟，不依赖真实等待。
- 增加 `read_source` 测试，覆盖关键词命中、关键词缺失、offset、limit、缓存不存在和缓存过期。
- 增加留存策略测试，证明禁止持久化的 provider 不会把 content/body 写入长期存储。
- 增加安全校验测试，覆盖非 HTTP(S)、loopback、private、link-local、reserved、危险重定向和 DNS 解析到危险地址。
- 增加不可信正文测试，证明网页中的指令只作为正文返回，不会改变工具参数、配置、key 或系统行为。
- 优先复用现有 service、provider metadata、runtime seam 和超时回归测试的写法；算法级纯函数测试只用于 RRF 和 URL canonicalization 这类稳定规则。
- 测试不访问真实 provider、不读取用户真实 keys file、不写入用户默认 StateStore。

## Out of Scope

- 删除 MCP 或把 CLI 变成唯一入口。
- 重写现有 Core、把所有模块迁移到新包层级，或复制一套 Search Gateway 项目。
- 一次性把所有松散字典迁移为 Pydantic 模型。
- 引入 FastAPI、Streamable HTTP、PostgreSQL、Redis、对象存储或分布式锁。
- 完整 Account、Team、Subscription、Project 多层 quota 模型。
- 原子额度预留、成本账本、预算告警和复杂账号打分。
- 基于主观印象配置 provider 权重。
- CrossEncoder、Embedding Reranker、MMR 或语义近似重复聚类。
- 自动生成事实 Claim、逐条事实验证或段落级 grounding。
- Hosted Search 的第二次大模型综合层。
- 通用浏览器自动化平台、登录墙绕过或付费墙绕过。
- 永久保存全部搜索结果或网页正文。
- 当前 route/source 的大规模重命名或删除。
- 把 keys file 强制迁移到 Keyring、Vault 或 KMS。

## Further Notes

- 当前代码基线的全量测试为 183 项通过；本规格描述的是架构演进，不是对现有 Parallel Adapter 的回归修复。
- 当前最直接的行为问题是仓库共享 config 的全局 `scrape_top` 覆盖。实施紧凑入口前也应先让 route_meta 恢复实际控制权。
- `content_kind` 是新领域词汇，实施时必须先更新 glossary，再在代码和文档中使用，避免继续用 summary/content/body 的近义词混写。
- 第一阶段完成标准是：候选搜索结果稳定、紧凑、可排序、无隐式 scrape，且现有 MCP 调用不破坏。
- 第二阶段完成标准是：CLI 与 MCP 共享 Core 和 StateStore，并能复现相同搜索结果与 key 状态。
- 第三阶段完成标准是：Agent 可以通过 source_id 按需抓取和局部读取正文，搜索响应不再携带重复大文本。
- 任何缓存落地前都需要重新核对各 provider 当前条款；本规格只规定系统必须支持 provider-specific retention policy，不替代合同或法律判断。
