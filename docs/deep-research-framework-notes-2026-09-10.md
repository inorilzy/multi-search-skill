# GPT Researcher / DeerFlow 借鉴笔记

核验日期：2026-09-10（美国太平洋时间）。仅阅读官方文档、固定提交源码；没有安装、运行上游或做效果评测。以下“建议”是针对 multi-search-skill 的设计判断，不是上游效果保证。

## 版本与边界

| 项目 | 本次固定版本 | 许可证与注意事项 |
|---|---|---|
| GPT Researcher | [`6f998577d547b1e54ec662dac63583aa11e3b84b`](https://github.com/assafelovic/gpt-researcher/commit/6f998577d547b1e54ec662dac63583aa11e3b84b)，提交日期 2026-08-23；包元数据 0.14.7 | 根 [LICENSE](https://github.com/assafelovic/gpt-researcher/blob/6f998577d547b1e54ec662dac63583aa11e3b84b/LICENSE) 是 Apache-2.0，但 [pyproject.toml](https://github.com/assafelovic/gpt-researcher/blob/6f998577d547b1e54ec662dac63583aa11e3b84b/pyproject.toml#L1-L28) 写 MIT，存在元数据冲突；不应直接按 MIT 复制。 |
| DeerFlow 当前主线 | [`452d09b96b0dfdf00f53b8655e41c64232612dc3`](https://github.com/bytedance/deer-flow/commit/452d09b96b0dfdf00f53b8655e41c64232612dc3)，提交日期 2026-09-10；harness 包元数据 [2.1.0](https://github.com/bytedance/deer-flow/blob/452d09b96b0dfdf00f53b8655e41c64232612dc3/backend/packages/harness/pyproject.toml#L1-L5) | [MIT](https://github.com/bytedance/deer-flow/blob/452d09b96b0dfdf00f53b8655e41c64232612dc3/LICENSE)。README 的“2.0”指重写后的架构代际，不是本次包版本。 |
| DeerFlow 1.x | `main-1.x` 固定于 [`2ab28765803d4d9582aaa8f2f3355137d154e273`](https://github.com/bytedance/deer-flow/commit/2ab28765803d4d9582aaa8f2f3355137d154e273) | 仅用来核实旧版研究流程，不把它混入当前主线说明。 |

DeerFlow 官方明确说明 2.0 从头重写，与 v1 不共享代码；原研究框架保留在 `main-1.x`。[官方版本说明](https://github.com/bytedance/deer-flow/blob/452d09b96b0dfdf00f53b8655e41c64232612dc3/README.md#L1-L17)

## 最值得借鉴的三点

### 1. 把搜索目的、已有发现和下一步问题连接起来

GPT Researcher 的查询对象带 `query` 和 `researchGoal`；读完结果提取 `learnings`、`sourceUrl`、`followUpQuestions`；下一层查询由研究目标与追问构成。借鉴点是明确研究状态，而不是“递归越深越好”。[查询与提取结构](https://github.com/assafelovic/gpt-researcher/blob/6f998577d547b1e54ec662dac63583aa11e3b84b/gpt_researcher/skills/deep_research.py#L259-L378)、[递归与汇总](https://github.com/assafelovic/gpt-researcher/blob/6f998577d547b1e54ec662dac63583aa11e3b84b/gpt_researcher/skills/deep_research.py#L516-L577)

**本项目建议：**在现有 targeted follow-up / stop 规则之上，先补一个 Skill 层可检查的研究记录：`question → finding → source reference → remaining gap → next query / stop reason`。不必把 LLM、规划器或报告生成塞进搜索 Core。引用应关联本项目已有内容引用与来源轨迹；URL 本身不能证明发现被正文支持。

**上游局限：**GPTR 的引文是 `learning → URL` 字典，允许没有引文的 learning；这里没有片段位置、内容版本或逐条支持性验证。可借鉴关联结构，不能把它称为完整证据系统。[解析器](https://github.com/assafelovic/gpt-researcher/blob/6f998577d547b1e54ec662dac63583aa11e3b84b/gpt_researcher/skills/deep_research.py#L143-L172)、[最终上下文组装](https://github.com/assafelovic/gpt-researcher/blob/6f998577d547b1e54ec662dac63583aa11e3b84b/gpt_researcher/skills/deep_research.py#L613-L635)

### 2. 原始正文、工作上下文、可恢复状态分别处理

DeerFlow 2 的工具输出中间件把超大结果存为文件，对模型返回结构化预览和文件引用；durable context 记录任务委派、技能引用、摘要，并把来源于用户/工具/模型的状态作为低权限数据重新注入。其重点是避免长工具输出反复进入上下文和 checkpoint。[工具输出预算](https://github.com/bytedance/deer-flow/blob/452d09b96b0dfdf00f53b8655e41c64232612dc3/backend/packages/harness/deerflow/agents/middlewares/tool_output_budget_middleware.py#L334-L475)、[上下文权限分离](https://github.com/bytedance/deer-flow/blob/452d09b96b0dfdf00f53b8655e41c64232612dc3/backend/packages/harness/deerflow/agents/middlewares/durable_context_middleware.py#L1-L70)

**本项目建议：**复用现有内容存储与引用，研究记录保存状态和必要元信息，不再复制完整正文。压缩摘要与原文证据分开，恢复时能知道哪些问题完成、哪些来源需要重新取回。内容的 TTL、provider retention、存储策略仍然有效，写进研究笔记不能绕过这些约束；引用过期需要明确失效。

**不照搬：**DeerFlow 的存储失败路径会截断输出；本项目应沿用明确失败及现有内容语义。也无需为了几轮搜索引入整套 sandbox、持久消息图和通用 agent runtime。[输出配置明确的降级语义](https://github.com/bytedance/deer-flow/blob/452d09b96b0dfdf00f53b8655e41c64232612dc3/backend/packages/harness/deerflow/config/tool_output_config.py#L12-L18)

### 3. 将停止条件与未完成状态显式化

GPTR 提供深度、宽度和并发限制，下一层宽度减半但最少为 2；全分支失败停止下降。其成本是在执行后记录，不能等同于总费用硬预算。DeerFlow 1.x 用 `current_plan`、步骤结果、`plan_iterations` 驱动研究，另有计划轮数和步骤上限。[GPTR 默认配置](https://github.com/assafelovic/gpt-researcher/blob/6f998577d547b1e54ec662dac63583aa11e3b84b/gpt_researcher/config/variables/default.py#L39-L41)、[失败停止与递归](https://github.com/assafelovic/gpt-researcher/blob/6f998577d547b1e54ec662dac63583aa11e3b84b/gpt_researcher/skills/deep_research.py#L496-L554)、[成本记录](https://github.com/assafelovic/gpt-researcher/blob/6f998577d547b1e54ec662dac63583aa11e3b84b/gpt_researcher/skills/deep_research.py#L580-L611)、[1.x 状态图](https://github.com/bytedance/deer-flow/blob/2ab28765803d4d9582aaa8f2f3355137d154e273/src/graph/builder.py#L23-L81)、[1.x 限制](https://github.com/bytedance/deer-flow/blob/2ab28765803d4d9582aaa8f2f3355137d154e273/src/config/configuration.py#L45-L49)

**本项目建议：**在已有停止规则上记录“停止原因 + 未解决问题”，区分证据已足够、预算耗尽、来源失败、没有新增信息。先由上层 Skill 控制研究轮次、查询数、正文读取量和总耗时；只有实际需要跨进程恢复时再添加持久任务状态。

## 不值得照搬的部分

- **DeerFlow 2 的全套平台。**当前 deep-research 能力有相当一部分是 Skill 的广搜、精读、验证和综合检查；其中“任何研究至少 3–5 个角度”等硬规则容易给简单问题增加成本。方法可参考，固定次数不宜移植。[当前 deep-research Skill](https://github.com/bytedance/deer-flow/blob/452d09b96b0dfdf00f53b8655e41c64232612dc3/skills/public/deep-research/SKILL.md#L33-L106)
- **把 checkpoint 当证据保存保证。**DeerFlow 当前 checkpoint retention 合约仍标为 draft，重点是保护恢复目标和父链；这解决运行恢复，不证明引用内容真实、有效或可长期保留。[合约状态与受保护状态](https://github.com/bytedance/deer-flow/blob/452d09b96b0dfdf00f53b8655e41c64232612dc3/backend/docs/checkpoint-retention-contract.md#L1-L60)
- **GPTR 按最新内容保留的字数裁剪。**它按逆序保留上下文并以空白分词计数，不是依据研究问题覆盖率或真实模型 token 预算；本项目不应直接把这段压缩逻辑移植到中文研究。[裁剪代码](https://github.com/assafelovic/gpt-researcher/blob/6f998577d547b1e54ec662dac63583aa11e3b84b/gpt_researcher/skills/deep_research.py#L207-L231)

推荐先做研究记录和停止原因的小试验，比较相同题目下遗漏问题、无依据结论、重复查询、读取量及耗时；这比先换框架更能证明实际收益。
