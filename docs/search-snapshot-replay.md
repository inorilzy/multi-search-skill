# 搜索快照与离线回放

维护入口只接受明确提供的评测问题；不会读取搜索历史。采集调用公开搜索也使用的 `_run_search_candidates` 召回与融合流程，通过 `ProviderSpec` 包装统计调用，通过 Core observer 冻结超时、重试处理后的逐查询结果与原始名次。采集只执行搜索召回，不继续联网抓取候选 URL 正文，以隔离排序评估。回放直接复用 `candidate.fuse_search_results`，不调用 provider、不联网。

当前快照格式为 `schema_version=2`，`fusion` 声明算法为 `two_level_rrf`、`rank_constant=40`、`rank_window=null`。所有有效 provider 名次进入融合，每个查询融合后的结果也不再按 15 条截断；最后统一取前 15 条。旧 schema 1 的窗口算法快照，以及算法声明缺失或不匹配的快照，会明确拒绝加载和回放，不能宣称在新算法下精确重放旧结果。

`execution.count` 和 `provider_counts` 记录搜索源召回数量，`execution.result_limit=15` 记录最终输出数量。默认回放按 `result_limit` 截取；离线 `replay`／`compare` 可显式传入 `--limit` 比较其他输出长度，不改变公开搜索的最终 15 条限制。

在仓库根目录执行；Python 环境须已安装项目依赖。以下 `.scratch` 目录须先存在。

```powershell
# 固定的手写合成数据：无真实搜索、无真实计费；生成带正常到期时间的快照。
.venv/Scripts/python.exe scripts/search_snapshot.py fixture --output .scratch/example-snapshot.json
.venv/Scripts/python.exe scripts/search_snapshot.py compare .scratch/example-snapshot.json --limit 2
.venv/Scripts/python.exe scripts/search_snapshot.py replay .scratch/example-snapshot.json --mode primary --limit 2
.venv/Scripts/python.exe scripts/search_snapshot.py compare .scratch/example-snapshot.json --omit-variant variant --limit 2

# 真实采集：会使用本机已有凭据调用明确指定的 provider。
.venv/Scripts/python.exe scripts/search_snapshot.py capture --query "Python asyncio cancellation" --variant "Python TaskGroup cancellation behavior" --source brave --count 10 --output .scratch/live-snapshot.json
# 明确禁止展开，覆盖本次采集配置中的 expand / expand_queries。
.venv/Scripts/python.exe scripts/search_snapshot.py capture --query "Python asyncio cancellation" --no-expand --source brave --count 10 --output .scratch/primary-snapshot.json
```

`capture` 必须选择 `--variant` 或 `--no-expand`。仅采集入口复制配置并覆盖这两个展开字段，既不更改全局配置文件，也不改变公开搜索接口的配置优先级。仅主查询基线从同一展开快照选择主查询数据，避免重复采集引入实时变化。逻辑查询去重和身份规则由共享 `query_plan` 决定。

`compare` 默认比较仅主查询与等权展开；指定 `--omit-variant` 后比较完整策略与删去该变体后的策略。两端使用相同 `--limit`，输出 `added`、`lost`、`rank_changes`。主查询不允许删除。上面的合成样例在 limit=2 时新增 `/added`、丢失 `/z`、`/shared` 从第 2 升到第 1；这是机制示例，不是质量结论。

加权实验复用同一入口并显式指定参数（权重不是经过评测选择的默认值）：

```powershell
.venv/Scripts/python.exe scripts/search_snapshot.py compare .scratch/example-snapshot.json --mode weighted --primary-weight 1 --variant-budget 0.9 --limit 2
```

快照只保留融合需要的候选字段和诊断；原始 provider payload、正文、配置中的未知字段与凭据不会写入。正文是否可用保留为布尔值。来源禁止保存搜索结果时排除该来源结果；禁止内容保存时排除摘要；这些受限查询的完整回放明确失败，不补造数据。凭据脱敏改变内容时也拒绝宣称精确回放。

Python API 的 `replay_snapshot` 和 `compare_snapshot` 默认 `fidelity="exact"`，继续拒绝任何带 `credentials_redacted=True` 的快照。对于公开文档摘要中的 `MYSQL_ROOT_PASSWORD=...` 等示例，新采集可以证明只有候选 `description`／`content` 文本被脱敏时，调用方可明确选择排序等价回放：

```python
from multi_search_mcp.src.search.snapshots import load_snapshot, replay_snapshot

snapshot = load_snapshot(".scratch/live-snapshot.json")
result = replay_snapshot(snapshot, fidelity="sanitized_content")
assert result["fidelity"] == "sanitized_content"
```

此模式只声称排序等价（rank-equivalent），不声称摘要或完整响应与原始搜索精确一致，也不证明搜索质量通过。采集时保守要求其余输入完全一致，摘要是否存在及其类型不变，并比较完整查询集和逐查询融合结果中除 `content` 以外的字段。标题参与代表行的平局处理，因此标题脱敏也拒绝；查询、URL、来源、原始名次、得分、日期、错误、状态或执行参数变化都不能获准。脱敏照常执行，不会因文本看起来是公开示例而保留疑似凭据。

新快照中的 `sanitized_content_proof` 记录版本和脱敏后快照的 SHA-256，绑定此次采集检查结果。它不保存脱敏前文本或凭据哈希，也不是抵抗恶意伪造的签名。旧快照只有 `credentials_redacted` 布尔值时不能补推证明；数据变化后不能沿用旧证明。TTL、缺失来源／候选／名次、内容留存限制等校验仍然生效。比较的两端传递相同 fidelity；当前命令行维护入口继续使用默认精确模式，此显式选择仅在 Python API 提供。

`expires_at` 使用各来源留存策略中最短 TTL，从采集开始计时。过期快照拒绝回放；`load_snapshot` 遇到过期文件会删除它。文件写入不会覆盖已有快照。命令结束后没有后台定时清理程序，因此维护者必须在到期前删除导出的快照及报告副本，不应提交真实快照。合成示例文件不包含真实来源数据，每次 `fixture` 都按正常 TTL 生成新的快照，未绕过留存校验。

`collection.elapsed_seconds` 是原始采集耗时；`provider_attempt_count` 包括实际发生的重试，`provider_attempts` 提供逐调用耗时，超时尚未完成时为 `null`。`offline_replay_seconds` 只测本次内存离线融合。合成 fixture 的调用耗时只针对注入函数，不能当成服务商时延。价格不可得时为 `null` / `unknown`；这些数值都不是完整工作流成本。缺失查询、候选行或原始名次会明确报错。

验证：`.venv/Scripts/python.exe -m unittest tests.test_search_snapshots -v`。
