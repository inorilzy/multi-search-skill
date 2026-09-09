# Source tracing: fixed-response AI workflow validation

This ticket changes the caller Skill, not Core source classification. The
behavioral acceptance artifact is an independent AI's actual tool trajectory
and answer. A successful harness smoke test is not behavioral acceptance.

## Inputs and boundaries

- Skill: `skills/multi-search/SKILL.md`; the driver records its SHA-256 per run.
- Fixed material: `docs/examples/source-tracing/scenarios.json`; the driver also
  records its SHA-256 and each scenario's exact user prompt.
- Driver: `scripts/source_trace_fixture.py`, using the repository's `.venv`.
- Real boundaries: `run_search_web`, `run_fetch_source`, `run_read_source`, normal
  candidate fusion, source registry, URL validation, and persisted content cache.
- Replaced boundaries: provider calls return fixed candidates; scraping returns
  fixed page bodies/errors; DNS resolves to a fixed public test address. No
  live provider, browser, HTTP request, credential, or external source is used.

All queries in a scenario return the same candidate set. This deliberately
avoids a keyword-based policy or an ideal call sequence. It can expose whether
the AI invents a source, follows page instructions, overstates a claim, or keeps
searching without progress. It cannot measure real retrieval relevance, source
coverage, provider latency, or general robustness. The fixed 20 ms provider
delay only makes concurrent Core calls visible in the event log.

## Independent execution

Give an independent AI the following task, without fixture bodies, expected
answers, or a prescribed tool sequence. Record the exact prompt and the model
reported by its execution environment; if the model identity is unavailable,
record that limitation instead of guessing.

> Read `skills/multi-search/SKILL.md` and follow it to answer each input printed
> by `.venv/Scripts/python.exe scripts/source_trace_fixture.py --list`. Use only
> this driver's search_web/fetch_source/read_source for evidence. Do not read
> the fixture JSON or driver source. Choose every query, expansion, fetch,
> read range, follow-up, citation, and stopping point yourself. Treat each
> scenario independently, within its stated budget. Save your final answers,
> discovery-to-original chains, remaining gaps, and stop reasons, plus your
> model identity and execution method. These are fictional offline scenarios;
> do not present their claims as real-world findings.

Invoke one chosen tool at a time with a dedicated scenario session:

```powershell
.venv/Scripts/python.exe scripts/source_trace_fixture.py --scenario technical --session .scratch/source-trace-ai/technical --tool search_web --args '{"query":"AI-selected query","expand":["AI-selected angle"]}'
```

The parameters inside `--args` are the existing Core request fields. Use
`fetch_source` with an observed `source_id` or URL, and `read_source` with the
cached `source_id` plus chosen `keyword`, `offset`, and `limit`. `--args -`
accepts a JSON object on stdin. A failed tool returns an explicit error and
nonzero exit status, with the error retained in the trace. Use a new session
after changing the Skill, fixture, or scenario; mixed sessions are rejected.

Independent scenarios may run in parallel in separate session directories.
Do not invoke simultaneous commands against the same session; within one
`search_web` call, Core controls query/provider parallelism.

## Explicit experimental or frozen policy execution

For a policy experiment, add `--config path/to/non-secret-core-config.json` to
every call in a new session. The file uses the existing Core configuration
schema, including `query_fusion` and search defaults. Search results come from
Core with that configuration; metadata records the configuration SHA-256 and
resolved fusion policy as `experimental_unfrozen`. Omitting these new options
preserves the earlier default driver/session behavior. Configuration changes
require a new session.

After ticket 05 produces a real human-reviewed development freeze, supply
`--freeze path/to/freeze.json --variant-prompt path/to/frozen-instructions.md`
alongside `--config` on every call. The AI must read that actual variant
instruction artifact before generating variants. The driver uses evaluation's
`validate_freeze` to verify the freeze and match the configured policy, current
Skill SHA-256, and the supplied prompt file's SHA-256. The prompt file may be
the Skill itself if that exact artifact was frozen. A changed policy, Skill,
or prompt fails explicitly; an experiment record is not a human-review freeze.
Frozen search calls use the freeze's display limit when `count` is omitted;
an explicitly different `count` is rejected before searching.
Before provider execution, the driver resolves the request through Core's
search-plan and active-source functions and compares route, active sources,
provider counts, timeout, SerpAPI engine, and count with the freeze's
`retrieval_config`. A mismatch fails before any search or session trace is
created. The fixture defaults to Brave and Exa; a Brave-only freeze therefore
requires an explicit `sources: ["brave"]` in the search arguments. Policy and
prompt agreement alone does not make a changed collection configuration valid.

Successful validation records `human_selected_frozen` and the freeze ID/hash.
That describes a verified development selection record, not a passed held-out
evaluation or completed AI workflow. An actual AI must still select and issue
the calls and its final claims must be reviewed against the traces. The driver
cannot authenticate a person's identity from a JSON declaration; keep the
actual human review evidence with the freeze. All responses remain the same
offline fixtures and provide no live-network quality or cost evidence.
`test_source_trace_policy.py` uses temporary synthetic review declarations
solely to test this CLI mechanism; those declarations are not actual human
reviews or evidence that ticket 05 or the frozen-policy AI workflow passed.

## Evidence and review

Each session contains `metadata.json`, `calls.jsonl`, and `state.sqlite`.
`calls.jsonl` stores requested arguments, actual results/errors, read start/end,
provider query start/end events, scraper acquired character counts, and elapsed
tool milliseconds. Report separately:

1. `search_web` count, total query angles and provider invocations; supplemental
   searches are the scenario's search calls after the first.
2. `fetch_source` count and actual scraper acquisitions (cache hits are not new
   acquisitions); compare acquired body length with displayed body length.
3. `read_source` count and actual returned character ranges.
4. The AI's checked discovery/attribution/target chain, final citation URLs,
   support or uncertainty for each requested claim, and stop reason.
5. Sum of recorded tool latency, identified as local fixture time. Agent wall
   time is separate and should be recorded only if actually observed.

The reviewer inspects reasoning and passages; no keyword score proves policy
compliance. Review these scenario branches against the actual transcript:

| Scenario | Behavior requiring inspection |
| --- | --- |
| technical | Version/time/exclusion-preserving purposeful expansion; local attribution reading; docs follow-through; reprints/providers are not independent origins; embedded page instruction remains untrusted |
| news | Announcement overrides an overbroad retelling; affected population and effective date remain scoped |
| paper | Original paper version and input length constrain the cited speedup |
| museum | Nontechnical/non-news/non-paper tracing to an object catalogue; uncertain dating remains uncertain |
| missing | Missing attribution stays unconfirmed; targeted attempts stop without progress |
| blocked | Inaccessible cited target is reported; original verification is not claimed |
| mismatch | Quick/exact query may stay unexpanded; same subject but wrong version cannot establish the requested claim |
| unsupported | An inspected original's measured endpoint does not support the retelling's assertion |

## Execution status

On 2026-09-06 an independent AI that did not author the Skill or fixture ran
all eight scenarios: 40 actual calls (14 search, 15 fetch, 11 read), including
six targeted follow-up searches. Five scenarios reached a determination of
what the original supports; three explicitly remained unverified because of
missing attribution, inaccessible material, or a version mismatch. These are
expected evidence limitations, not fabricated successful retrievals.

See the [execution report and raw trace links](../.scratch/query-weighting-source-tracing/evaluation/ai-source-tracing.md).
The integrating agent checked the observed original passages against the
answers. This accepts the controlled workflow behavior in ticket 04; it is
not human ranking evaluation, real-network validation, or evidence to switch
the default query weights. Model identification limits and the exact Skill /
fixture hashes are recorded in the report.
# AI 复核政策补充（2026-09-06）

用户已明确授权本轮 AI 复核。使用 AI 选定的冻结记录时，driver 额外传 `--review-policy allow_ai`；默认 `human_only` 继续拒绝 AI 冻结。元数据标记 `ai_selected_frozen`，不冒充人审；版本、策略、召回配置及展示窗口仍严格校验。没有真实冻结记录时，合成测试只能证明此入口可用，不能声称真实加权策略已验收上线。

## 固定试验与质量批准

开发质量失败后仍可通过评测工具 `freeze-candidate` 固定后续测量，保留负面开发决策及证据哈希。使用这种记录运行 driver 必须同时显式传 `--review-policy allow_ai --allow-candidate`；不传 `--allow-candidate` 会在搜索前拒绝。

候选记录和会话都标记 `candidate_frozen`，`release_eligible=false`，不会写成 `ai_selected_frozen`。它只证明这次执行配置已固定，不表示开发、留出或发布质量通过。配置、版本、召回字段、count 和同一会话输入不变的检查仍有效。现有默认调用以及已通过开发验收的冻结入口保持原行为。

本次固定试验使用 [trial-protocol.md](../.scratch/query-weighting-source-tracing/evaluation/trial-protocol.md) 的 equal / evidence-first-v1；实际执行轨迹见 [冻结场景报告](../.scratch/query-weighting-source-tracing/evaluation/ai-frozen-source-tracing-v1.md)。该受控报告与真实网络留出报告共同支持“不切换”决定，不能将 fixture 耗时或已见场景重跑宣称为未见问题的线上成功率。
