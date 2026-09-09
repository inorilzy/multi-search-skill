# 查询融合实验与当前默认

当前默认仍是两级等权 RRF。`search_web` 先融合每个查询内的 provider 排名，再融合不同查询；provider 层、排名常数 40 和窗口 15 均保持不变。

本次修正重复查询：变体只去两端空白，完全重复的变体和与主查询相同的变体只执行、计分一次，空白变体不执行。主查询文本保持原样；大小写、内部空白、版本、URL 和标识符不做语义归并。去重诊断为 `diagnostics.duplicate_query_count`、`diagnostics.discarded_blank_query_count`，主查询身份在 `diagnostics.primary_query`。原有参数和配置优先级不变。

## 显式实验

在现有 JSON 配置入口中设置 `query_fusion` 可试验加权。MCP、CLI 和直接 Core 都读同一配置；不用向公共工具传权重向量。

```json
{
  "query_fusion": {
    "mode": "weighted",
    "primary_weight": 1.0,
    "variant_budget": 0.9
  }
}
```

这组数值只用于固定行为测试，**没有通过开发集与留出质量验收，不是新默认或推荐最优值**。省略 `query_fusion` 或设为 `{"mode":"equal"}` 使用当前默认。非法模式、非有限／非正权重、未知字段或不满足主查询优先的配置在请求 provider 前明确失败。

执行前按去重后的查询集合分配预算：主查询使用 `primary_weight`，每条变体使用 `variant_budget / 变体数`，主查询权重须高于每条变体。增加变体不能增加变体组总预算；失败、超时、空结果和重试不会重新分配权重。某候选的查询层贡献是 `实际权重 / (40 + 该查询融合名次)`，总分为实际命中查询的贡献之和。provider 的原始评分不参与权重分配。

只有主查询时仍只运行 provider 层融合，结果、评分、截断及候选字段保持原单查询语义。此时诊断的 `applied_stage` 为 `provider`，权重标记为 1；配置中的实验值不改变单查询评分。

## 诊断与边界

- `diagnostics.query_fusion`：请求策略、实际应用层、全部预分配权重、主查询 `ok|partial|failed|empty` 状态。
- 加权多查询结果的 `query_ranks`：每条命中查询的名次、权重、贡献与 `is_primary`。
- `primary_query_hit`、`variant_support_count`：是否由主查询命中、支持该候选的不同变体数量；它们不是相关性或独立原始信源标签。

固定测试中，主查询已有 15 个候选时，1 / 0.9 允许多个变体发现的原始材料进入前 15；0.6 / 0.4 在该例中会排除新增材料。另一固定反例表明，多个偏题变体仍可能把错误版本推入结果。因此代码通过不等于排序质量通过，也不能据此切换默认。

正文流程仍为紧凑候选 → 显式少量获取 → 缓存局部读取。Skill 沿实际引用关系核实原始材料；检索 provider、规范化 URL 与原始材料身份分别处理，只引用实际检查过的材料，缺证据才补搜，明确停止。

同数据三模式比较与逐变体移除见[快照回放](search-snapshot-replay.md)。评测题已按用户要求本地生成，AI 承担复核；开发失败后以 `candidate_frozen` 固定 equal / evidence-first-v1，继续执行首次留出及同配置 Core 工作流，见[当前验收入口](../.scratch/query-weighting-source-tracing/evaluation/README.md)。固定试验不等于质量批准；默认仍为 equal，未部署、推送或安装到个人 Skill 目录。
