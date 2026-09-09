# 查询融合开发集与留出评测

这些工具准备盲评材料并检查复核记录，不自动生成相关性判断，不修改搜索默认策略。默认 `review_policy="human_only"` 保持人工流程；用户明确授权 AI 复核时，调用方须显式传 `review_policy="allow_ai"`。AI 标签填写 `reviewer_kind="ai"`，不能伪装成 human。`human_reviewed`／`ai_reviewed` 表示记录满足必要字段，不是身份或事实认证。

每题 JSON 包含 `id`、`question`、`topic_group`、`category`、`prompts`。例如 `prompts.p1={"variants":["明确角度一","明确角度二"],"reason":"各角度用途"}`。快照用所有 prompt 变体的去重并集采集；工具再从同一批结果选择当前 prompt 的查询集合。主题组须由维护者保守划分：同主题、同实体或近似改写不能跨开发／留出集。代码检查组别隔离，不能自动判断语义近似。

`policy-specs.json` 是显式实验列表，例如：

```json
[{"id":"w07","primary_weight":1.0,"variant_budget":0.7},{"id":"w09","primary_weight":1.0,"variant_budget":0.9},{"id":"w11","primary_weight":1.0,"variant_budget":1.1}]
```

这些比例没有被选为默认。`prepare_review` 自动加入仅主查询、等权展开，所有策略最终展示 10 条，汇报前 5／前 10 条。逐变体移除复用 `replay_snapshot`；消融后违反主次权重约束的组合记录 `invalid_policy`。采集缺失、过期、受限快照直接失败，不补造结果。默认 `fidelity="exact"` 也拒绝经过脱敏的快照。

显式 `prepare_review(..., fidelity="sanitized_content")` 或 CLI `prepare --fidelity sanitized_content` 可使用采集阶段证明仅 `content`／`description` 改变的脱敏快照。该证明要求查询、URL、标题、provider 排名、候选资格及融合的非文本结果不变；身份字段发生脱敏、证明缺失或内容被事后修改仍失败。旧包仅有 `credentials_redacted` 标志不能补造证明，需重新采集。所有策略、消融和展示使用同一保真度，blind／private／report 均记录 `fidelity`；脱敏摘要不是原始文本精确回放，缺失证据仍须标 pending。TTL 不变，凭证不写入快照。

```powershell
.venv/Scripts/python.exe scripts/evaluate_query_fusion.py prepare .scratch/snapshot.json --question .scratch/question.json --prompt-id p1 --policy-specs .scratch/policy-specs.json --blind .scratch/blind.json --private .scratch/private.json --markdown .scratch/worksheet.md
.venv/Scripts/python.exe scripts/evaluate_query_fusion.py summarize .scratch/private.json .scratch/review.json --output .scratch/report.json
```

把 blind JSON 复制为 review JSON，交给复核者填写；授权 AI 复核时由独立 AI 检查已提供的证据并说明局限。保留 `packet_id`、`question_id`、候选 ID／URL，不向标注者提供 private 文件。候选跨同题不同 prompt 的 ID 稳定，只按 seed 随机排列；可把候选按 ID 合并一次标注，将全部原 `packet_id` 放入 `packet_ids`，summary 允许同题候选超集。

- `reviewer_kind="human"` 或显式允许的 `"ai"`、非空 `reviewer`、带时区 ISO `reviewed_at`。AI 的 reviewer 应记录实际可确认的执行者／模型信息，不猜测未知模型版本。
- 每条 `label`：`direct`、`partial`、`irrelevant`、`constraint_violation`、`pending`。
- 每条非空 `rationale`，及 `checked_evidence=[{"url":"实际检查地址","note":"检查段落／范围和判断依据"}]`。信息不足保留 pending，不把候选摘要当已读正文。
- 核实实际材料身份后填写 `original_material_id`。转载填写相同材料 ID，可用 `repost_of` 指向另一候选 ID；不可仅按域名或多 provider 命中推断独立证据。

任何未决、缺标签、缺复核记录／实际理由的评测都尚未通过。题干与原始 URL／title／snippet 不允许改写；同题跨 prompt 的展示字段取完整快照 Core 等权回放的一致代表。指标分别列出各标签数量；`variant_only_valid` 只计主查询全部有效 provider 召回窗口中从未出现的 `direct` 页面，`new_in_top10` 单独统计相比主查询前 10 条新进入的有效页面。主查询第 11 名晋升不算变体独有召回。原始材料／重复证据也只统计 `direct` 且已填材料身份的候选。报告保留题目类别、具体失败候选 ID 和逐变体消融，未标材料身份不能被算成已核实原始材料。采集调用数／时延来自快照，离线回放耗时不能代表实际网络成本或追溯成功率。价格不可得保持 unknown。

开发集所有题目和所有 prompt 都须完成所选政策允许的复核，才可调用 `freeze_development`。冻结输入为：

- `selection`：`prompt_id`、`policy_id`、实际 `query_fusion`，以及实际选择者 `selected_by`、`selection_reason`。仅主查询只作比较基线，不可冻成展开策略。
- `versions`：实际文件的 `skill_sha256`、`variant_prompt_sha256`；可附其他代码／模型版本。prompt hash 应覆盖完整生成提示词，题目里 variants/reason 的 hash 单独保存。
- `thresholds`：事先明确的非负整数 `min_direct_at5`、`max_violations_at10`、`min_variant_only_valid`，逐题检查，不用总体均值掩盖退化。
- `question_set`：`{"development":[题目对象...],"heldout":[题目对象...]}`。冻结保存完整题集、提示词、配置与规则的 hash、复核报告 hash，以及默认仍不切换的状态。

CLI `freeze --report ... --selection ... --versions ... --thresholds ... --question-set ... --output ...` 支持多个 `--report`。缺少所选政策允许的复核证据或缺题会明确拒绝。`summarize`、`freeze`、`heldout` 均提供 `--review-policy human_only|allow_ai`，默认 human_only。

```powershell
.venv/Scripts/python.exe scripts/evaluate_query_fusion.py summarize .scratch/private.json .scratch/ai-review.json --review-policy allow_ai --output .scratch/ai-report.json
```

AI 参与开发选择时冻结状态为 `ai_selected`；纯人工选择保留 `human_selected`。报告／冻结记录保存 `review_policy`、`reviewer_kind`，混合复核明确标为 mixed 并保留 reviewer_kinds。`validate_freeze` 和 `evaluate_heldout` 必须显式传与冻结一致的 review_policy，不能在冻结后改变复核政策。读取／写入工件保留其已有政策，不把 AI 记录升级为人工记录。

开发质量未通过后，如明确决定继续固定试验，可用独立入口 `freeze_candidate(development_decision, selection, versions, thresholds, question_set, retrieval_config, review_policy="allow_ai")`。它要求已有 `ai_review_completed_no_switch` 负面聚合决策：质量未过、未切默认、未选发布策略、有效时间、与开发题集相符的已评／缺失题计数、标签计数和证据哈希；空对象或成功结论不能代替。决策来自已完成评审的长期聚合记录，不读取旧的过期候选，也不延长其 TTL。冻结仅保留决策哈希、聚合标签和缺失题 ID。

试验状态为 `candidate_frozen`，`release_eligible=false`、`development_quality="not_passed"`。它固定相同的选择、Skill／完整提示词版本、题集、展示窗口和完整召回配置，但不声称已通过开发门槛。`versions` 可额外包含 `trial_protocol_sha256`、`heldout_manifest_sha256`，以固定完整试验规则、回放保真度及首次使用清单；额外字段同样参与版本精确匹配。`freeze_development` 的门槛保持不变，不能把失败的开发报告改成已通过来运行它。

```powershell
.venv/Scripts/python.exe scripts/evaluate_query_fusion.py freeze-candidate --development-decision .scratch/ai-review-decision.json --selection .scratch/selection.json --versions .scratch/versions.json --thresholds .scratch/thresholds.json --question-set .scratch/questions.json --retrieval-config .scratch/retrieval.json --review-policy allow_ai --output .scratch/candidate-freeze.json
.venv/Scripts/python.exe scripts/evaluate_query_fusion.py heldout .scratch/candidate-freeze.json --report .scratch/heldout-report.json --versions .scratch/versions.json --question-set .scratch/questions.json --review-policy allow_ai --allow-candidate --output .scratch/heldout-result.json
```

使用候选冻结验收时，`validate_freeze`／`evaluate_heldout` 还必须显式传 `allow_candidate=True`；CLI 对应 `heldout --allow-candidate`。默认拒绝候选冻结。工件读写仅保留类型，不授予验收权限。版本、配置、复核政策、题集和冻结后采集检查仍执行。即使留出指标达到门槛，结果也保留 `freeze_status="candidate_frozen"`、开发未通过及不可发布标志，不自动升级为 `ai_selected`。ticket 06 可检查同一试验版本的实际联通情况，联通通过不等于排序质量或默认切换获准。机制测试使用明确标记的合成决策，不是实际 AI 或人工质量证据。

`evaluate_heldout`／CLI `heldout` 要求版本、配置、题目／提示词和采集时间符合冻结记录；留出采集须晚于冻结，须覆盖每个留出问题一次。冻结同时固定影响召回的 route、active_sources、provider_counts、timeout、serpapi_engine、count；题目各自的 expand 不当作全局配置。任何失败或复核未决报告 `not_passed`。全部满足仅报告 `heldout_thresholds_met`，仍需 ticket 06 的实际工作流验收，工具不会自动推荐切换。代码无法阻止人在别处预览或反复使用留出材料，没有声称强制一次性验收；维护者必须保存首次使用记录，不能调参后再次把相同留出集声称为独立验收。

blind、private、review、报告及 Markdown 副本继承快照 TTL，过期加载明确拒绝；维护者负责到期前删除全部副本，工具不启动后台服务。冻结记录只含配置、版本、题集／报告摘要 hash 和复核选择信息，不复制候选或正文。所有写入拒绝覆盖既有文件。

验证：`.venv/Scripts/python.exe -m unittest test_query_evaluation -v`。
