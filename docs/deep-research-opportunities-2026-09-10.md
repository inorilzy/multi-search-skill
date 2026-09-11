# Deep Research 项目对 multi-search 的借鉴价值

> 范围已收敛：用户随后明确目标是找到搜索内容，不建设研究工作流。本文保留为上游调查记录；实际拟实施范围以[搜索优化计划](search-focused-improvement-plan-2026-09-10.md)为准，不执行下文的研究状态/台账建议。

核对日期：2026-09-10（America/Los_Angeles）。本地基线：`358e04414e5564c2658eee394d19b10111849458`，版本 0.3.1。范围来自用户引用对话中的四个 Deep Research 项目；不含 AutoResearch 和 AI Scientist。

结论：值得借鉴。收益最大的方向是增强调用方的研究状态和证据组织，让下一次搜索由已读材料中的缺口驱动。当前 Core 已能承担检索和正文获取；第一步宜在 Skill 层试验，不需要引入第二套模型运行时或修改默认搜索接口。

## 四个项目各取什么

| 项目 | 已核对的机制 | 对本项目的价值 | 建议 |
|---|---|---|---|
| [dzhng/deep-research](https://github.com/dzhng/deep-research/tree/1f8f3e285bbc23e80b98a66a64effab9069f3ad4) | 查询携带 researchGoal，读后产生 learnings 和 followUpQuestions，递归缩小 breadth | 最容易看清“已知什么 → 下一步查什么”的最小循环 | 优先读核心函数，借鉴控制流；不直接搬 TypeScript/Firecrawl 实现 |
| [langchain-ai/open_deep_research](https://github.com/langchain-ai/open_deep_research/tree/1b7d2e80db9faa586165c60e09096dbbfd483a64) | research brief、研究调度、局部研究、压缩、最终报告分阶段；分别限制调度轮数和局部工具迭代 | 把零散搜索变成可管理任务；区分原始笔记与压缩结果 | 优先借鉴研究状态、预算、带引用的笔记；独立服务需求明确后再考虑复用框架 |
| [assafelovic/gpt-researcher](https://github.com/assafelovic/gpt-researcher) | 深入研究时把 learnings 与 sourceUrl 关联，再产生后续问题 | 改善结论和来源的对应关系；已有搜索能力可作为底层供给 | 看 deep research 的数据结构，不重复移植搜索器和报告产品层 |
| [bytedance/deer-flow](https://github.com/bytedance/deer-flow) | 2.x 是通用 Agent harness；研究由 Skill 驱动，并有工具结果外置、上下文压缩后的状态保留 | 长任务减少上下文丢失和重复阅读 | 借鉴工作产物与恢复状态，暂不引入整套沙箱、前后端和任务框架 |

前两项源码：[dzhng 核心循环](https://github.com/dzhng/deep-research/blob/1f8f3e285bbc23e80b98a66a64effab9069f3ad4/src/deep-research.ts#L37-L111)、[递归部分](https://github.com/dzhng/deep-research/blob/1f8f3e285bbc23e80b98a66a64effab9069f3ad4/src/deep-research.ts#L166-L278)、[Open Deep Research 主流程](https://github.com/langchain-ai/open_deep_research/blob/1b7d2e80db9faa586165c60e09096dbbfd483a64/src/open_deep_research/deep_researcher.py)、[状态定义](https://github.com/langchain-ai/open_deep_research/blob/1b7d2e80db9faa586165c60e09096dbbfd483a64/src/open_deep_research/state.py)。后两项的固定版本、具体源码与许可证细节见[框架核对笔记](deep-research-framework-notes-2026-09-10.md)。

## 0.3.1 基线已经有的能力

不能把已有功能重新包装成“新增 Deep Research”：

- 当时的 [Skill](../skills/multi-search/SKILL.md) 要求最多三个有目的的 expand、选读 3–5 篇全文、追溯原始材料、按具体缺口补搜，以及证据充分／连续两次无新增／预算耗尽时停止。后续版本已取消固定选读数量，本条仅记录 0.3.1 基线。
- [query_plan.py](../multi_search_mcp/src/search/query_plan.py) 和 [candidate.py](../multi_search_mcp/src/search/candidate.py) 已做单次查询计划去重、跨 provider/query 的两级 RRF 和最终 15 条选取。
- [service.py](../multi_search_mcp/src/service.py) 已统一正文获取、显式失败、缓存复用；搜索批次使用共享 deadline。
- [source_registry.py](../multi_search_mcp/src/state/source_registry.py) 与 [content_store.py](../multi_search_mcp/src/state/content_store.py) 已把来源引用与正文对象分开保存。
- [来源追溯验证](source-tracing-validation.md)和[查询融合评测](query-fusion-evaluation.md)已有固定材料、行为轨迹和相关性复核基础。

主要差距是：以上策略多靠当前对话维持，尚未形成统一的“研究问题 → 结论 → 证据 → 缺口 → 下一次动作”任务记录。单次 expand 是提前拟定角度；研究循环还需要根据阅读结果修改下一轮问题。

## 优先补三件事

### 1. 用子问题及缺口管理进度

研究开始时列出少量真正影响结论的子问题；每个子问题保存当前判断、支持材料、反证和未解决点。每次补搜必须注明要解决哪个缺口。简单查询沿用现在的流程，不强制进入研究模式。

例如本次“这些框架能否复用”：发现某项目支持 MCP 后，不立即认定可接入，而是形成“支持哪种 transport”的缺口，直接读加载器；发现 HTTP/stdio 不一致后，再评估适配成本。这种顺着证据推进的动作比继续搜索十篇项目介绍更有价值。

借鉴起点：[Open Deep Research 的 brief 与 supervisor](https://github.com/langchain-ai/open_deep_research/blob/1b7d2e80db9faa586165c60e09096dbbfd483a64/src/open_deep_research/deep_researcher.py#L111-L253)。本项目不必为此新增 think MCP 工具；上层 Agent 用简短结构化记录即可。

### 2. 压缩时保留结论和证据的关系

建议先采用一份 Markdown 表格，而不是新建证据数据库：

| 子问题 | 判断及适用范围 | 支持／反驳证据 | 已检查位置 | 剩余缺口 |
|---|---|---|---|---|
| 当前 ODR 能否直接接本地 MCP | 默认加载路径需要适配 | 上游加载器用 streamable_http；本地入口默认 stdio | 固定 commit 的函数／行号 | 具体适配实现未试运行 |

每条证据保留 URL、版本或检查时间、段落定位；`source_id` 只作为本次工具访问引用。需要精确片段时，应绑定当时正文哈希和位置，不能把不同版本页面的偏移混用。

这个区分来自本地实现：`make_source_id` 的输入包含 response_id，所以相同 URL 在不同响应中可以有不同 ID；缓存还有 TTL 和容量限制。研究任务不能用 `source_id` 充当永久来源身份，也不能凭 URL 相同就断言页面内容未变。

压缩笔记只能是导航和推论摘要，关键断言仍须能回查来源。保存 provider 派生摘要或正文摘录时，继承现有 retention/TTL 约束，不能通过另写文件绕过缓存规则；过期后重新获取并核对版本，不宣称恢复到了原始证据快照。

借鉴起点：[ODR 的 compressed_research 与 raw_notes](https://github.com/langchain-ai/open_deep_research/blob/1b7d2e80db9faa586165c60e09096dbbfd483a64/src/open_deep_research/state.py#L56-L84)、[压缩阶段的引用要求](https://github.com/langchain-ai/open_deep_research/blob/1b7d2e80db9faa586165c60e09096dbbfd483a64/src/open_deep_research/prompts.py#L161-L192)。这些提示词要求不等于程序已验证引用正确。

### 3. 研究预算覆盖整项任务

现有单次 timeout 继续保留，上层额外统计搜索批次、实际展开查询、已读页面、总耗时及停止原因。原型可先由 Agent 维护记录；它属于软约束。只有确实需要无人值守执行时，才值得实现不可绕过的任务级预算。

预算应考虑多源放大：假设 7 个源都活动，主查询加 3 个 expand，每批约有 28 个 query-provider 调用（未计重试）；5 个研究单元各发一批就约 140 个。每个批次还会获取最终最多 15 个正文。此为按当前调用结构的估算，不是本轮实测用量。补搜已知链接优先直接 fetch，具体平台问题显式选源，避免每个子问题重复广撒网。

ODR 的限制区分 supervisor 和 researcher，但 `max_react_tool_calls` 实际检查的是工具调用迭代轮数，一轮仍可并发执行多个工具，不能直接视为总 API 请求上限。[配置](https://github.com/langchain-ai/open_deep_research/blob/1b7d2e80db9faa586165c60e09096dbbfd483a64/src/open_deep_research/configuration.py#L61-L115)、[执行代码](https://github.com/langchain-ai/open_deep_research/blob/1b7d2e80db9faa586165c60e09096dbbfd483a64/src/open_deep_research/deep_researcher.py#L418-L489)。

## 不值得照搬的部分

- **按深度机械递归。** 缺口解决就停，不能因为还有 depth 就继续搜。dzhng 的递归模式适合教学，但并不自动保证信息增益。
- **结论与 URL 分离。** dzhng 的 `ResearchResult` 使用两个独立数组，报告末尾统一附 visitedUrls；没有逐条结构化绑定证据。其异常分支返回空数组，调用方也拿不到结构化失败。保留本项目已有来源追溯和显式错误。[源码](https://github.com/dzhng/deep-research/blob/1f8f3e285bbc23e80b98a66a64effab9069f3ad4/src/deep-research.ts)。
- **仅因原框架有就增加模型和运行时。** 当前调用方 Agent 已能规划、阅读和写作。把 LLM 再塞进 Core 会新增密钥、费用、超时和不可重复行为；目前没有证据证明这能提高本项目效果。
- **把缓存当知识库，或把 URL 去重当独立证据核验。** 两者分别解决短期复用和候选身份，不解决长期研究恢复及原始材料归属。
- **把“支持 MCP”当作零成本接入。** ODR 当前加载器拼接 `/mcp`，配置 `streamable_http`；本地 `server.py` 调用 `mcp.run()`，已核对本地安装库默认 stdio。复用 ODR 需改接入层支持本地 stdio，或另行提供 HTTP 入口；本轮未接通验证。[上游加载器](https://github.com/langchain-ai/open_deep_research/blob/1b7d2e80db9faa586165c60e09096dbbfd483a64/src/open_deep_research/utils.py#L422-L496)。

## 最小落地与验证路径

建议先为复杂调研增加一个按需读取的 Skill reference，描述上述研究记录和结束条件，并从现有 Skill 简短链接。复用 `search_web → fetch_source → read_source`，不改变普通查询的工具接口、RRF、15 条获取及正文读取约定。此次只记录建议，未实施这些行为修改。

```mermaid
flowchart LR
    Q[用户问题与约束] --> P[子问题和证据缺口]
    P --> S[现有 multi-search Core]
    S --> R[Agent 选读与原始来源核对]
    R --> N[更新结论、证据和未决项]
    N --> D{证据是否充分}
    D -->|仍有具体缺口且有预算| P
    D -->|充分或达到停止条件| O[带引用结论与剩余缺口]
```

先拿一小批真实技术选型、版本变化、相互矛盾来源的问题，对比当前 Skill 和新增流程，固定模型、问题约束及预算。重点看：关键子问题覆盖、引用实际支持率、重复原始材料比例、补搜是否带来新证据、总调用和耗时。来源不足必须允许未决；报告长度不计为质量。

复用现有来源追溯 fixture 检查“是否乱引、是否追错版本、是否无进展继续搜”；但该 fixture 对所有查询返回同一候选集合，不能证明新流程提高了真实召回。排序快照只能证明排序行为；质量增益仍需独立的实际阅读复核和新问题检验。暂不宣称改进已有实测收益。

## 核验范围

- 已读四个项目官方材料及关键实现，核对本地 Skill、service、查询身份、来源/正文存储、评测边界和 MCP transport 默认值。
- dzhng 与 ODR 根 LICENSE 均为 MIT；GPTR 与 DeerFlow 细节见配套笔记。若未来复制代码，应按目标文件及上游许可保留声明；本轮未复制上游实现。
- 未安装或运行四个上游项目，未进行模型质量、端到端成本或接入兼容性实测。上游 git clone 连接被重置，源码核对通过官方 raw 文件完成。
- 本轮仅新增调研文档，不修改代码、依赖、配置或已安装的个人 Skill。
