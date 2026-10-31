# Search executor: dispatch, retrieve, and return

This document covers both halves of the search flow:

- **Dispatch**: how the main Agent hands retrieval to an explore subagent (or
  runs it directly when delegation is unavailable).
- **Execution**: how the search executor runs the CLI, reads bodies, extracts
  evidence, and returns the compact handoff.

The executor keeps page bodies out of the main Agent's context. Search
responses and full bodies are large; the executor, on a cheaper model, reads
them and returns verbatim excerpts with their positions. The main Agent
judges those excerpts and spot-checks the important ones.

## Choose the execution mode

The parent Skill decides which mode applies for this request:

- **Delegated** (default when the host supports subagents): the main Agent
  spawns one explore subagent on a configured or explicitly available
  lightweight model. The subagent acts as the search executor and never
  delegates again. This covers new searches and reading the body of a known
  URL or `source_id`.
- **Direct** (only when requested, or when the host lacks subagent
  capability): the main Agent runs the executor workflow itself, disclosing
  that delegation was skipped and that bodies enter its own context. A
  dispatch/model failure is an explicit error, not a license to silently
  switch to a different model.

### Host-specific dispatch

The executor needs a shell tool that can run `multi-search`. It does not need
to write files: the main Agent writes the `--url-file` file for a known URL.

- **Claude Code:** prefer the built-in `Explore` subagent type when it can run
  `multi-search` through its shell tool in this installation; otherwise spawn
  a `general-purpose` subagent. Select a lightweight model through the host's
  supported mechanism (for example the `model` parameter when exposed); do not
  silently inherit the parent model when a cheaper one is configured.
- **Agent Teams:** give the retrieval task to an explore or researcher member
  running a lightweight model, or add one with a model override. The member
  returns the handoff below as its task output or message.
- **Codex:** use the available subagent tool with a configured lightweight
  search role, or its model override with an explicitly available lightweight
  model. Inspect role settings if needed: a fixed role model may override the
  requested model.
- **Pi:** use the host's existing subagent tool/extension and configured
  agent definition. Follow that implementation's schema for model, context,
  and tool access. A graph is not required. Prefer the multi-search CLI
  through the child's command tool.

A subagent name such as `Explore` or `explorer` does not guarantee a cheap
model or particular tools; check what the host actually uses. Use only a model
exposed and permitted by the host; a model already known to be rejected for
this account is not eligible. Keep model IDs, providers, credentials, and
reasoning settings in host configuration or supported dispatch parameters, not
hardcoded in this Skill. Lower reasoning effort alone does not select a
cheaper model. Missing model configuration or tool access is a setup error;
report it instead of installing an extension, adding an API client, or
silently inheriting the main model.

## Dispatch once, before retrieving

Give one explore subagent:

- The original request and relevant object/version/platform/time/source
  constraints, the requested result type (links only, or evidence for an
  answer), remaining budget, and the count of consecutive unproductive
  targeted attempts (initially zero).
- Any known `source_id`, or the path of the URL file the main Agent wrote for
  a known URL. Keep the URL itself out of command lines.
- The local path to this Skill, its explicit role as **search executor**, and
  the instruction to follow the **Executor** sections below without
  delegating.
- The usable CLI command and working directory. Have the child read
  [cli.md](cli.md), including its shell-safety rules for untrusted values;
  pass paths/config references, not secrets.

Use a fresh/isolated context containing this task packet rather than the full
conversation when the host supports it. Keep unrelated history and the main
Agent's reasoning out of the packet. If isolation is unavailable, disclose
that limitation; do not claim the same token savings.

The child receives the full search response and full bodies; the main Agent
does not retrieve or read them first. The child returns evidence, not a
research report or a final answer.

## Executor: query and route

Keep the original object, version/platform, time window, and exclusions in
`query`. Exact identifiers and quick lookups can stay unexpanded. When
alternate wording helps find the same target, add up to three purposeful
`expand` variants: official terminology, likely page title, or another
language. Submit them with the main query; do not turn variants into new
research topics.

Choose the route before searching. Run `multi-search routes --format json`
and pick the route whose `description` fits the request. When a route has no
`description`, use its `label` and `sources`. Omit `--route` to use the
`default_route` from that output. The route list comes from the current
settings, so do not assume any fixed set of route ids.

- User names a platform: use `--source <id>`. An explicit source list replaces
  the route's sources for that request. Globally disabled sources are still
  filtered out.
- Source-specific notes follow the source, not the route. The `sources` command
  describes each source.
- X posts (`twitter`): selected X URLs use the dedicated XKit scraper for
  `.full_text` and up to 20 loaded replies. Reply omissions or failures are
  stated in the Markdown. `full_content` means all acquired text, not all
  replies in the conversation.
- V2EX topics (`sov2ex`): use `--source sov2ex`. Its anonymous third-party
  SOV2EX API supplies titles, URLs, and highlight snippets. Indexed topic
  bodies are discarded; selected URLs are fetched after ranking.

The RRF cap, preview size, and per-field contracts are documented once in
[cli.md](cli.md); this file describes workflow, not parameter limits.

## Executor: inspect and select

Join `results[].content` and `scrapes[].markdown` by `source_id`; inspect
titles, URLs, snippets, and acquired body previews. Legacy `multi_search`
may put bodies once in top-level `markdown`, with source references in each
section.

Check the target, version/platform, content type, and direct relevance.
Classify promising candidates as `matched` or `uncertain`. Missing detail in
a preview is uncertainty, not proof of irrelevance. RRF agreement is not a
match check. Remove only clearly irrelevant candidates; there is no target
count or retention cap. Missing bodies and fetch errors alone do not
establish irrelevance.

If nothing useful appears, correct a specific mismatch or missing clue
within the parent Skill's stopping rules. Preserve the accumulated budget
and count of unproductive targeted attempts across follow-ups.

## Executor: read bodies and extract evidence

For links-only requests, read bodies only when a preview cannot settle whether
a candidate matches.

For each `matched` or `uncertain` candidate the answer may rely on, run
`multi-search fetch <source_id> --full-content --format json` and read the
whole `body`. Independent fetches may run in parallel. Record `body_error`
and each fetch failure. For a known URL, fetch with the URL file the main
Agent supplied, and use the returned `source_id` from then on.

Find the passages that state, contradict, or qualify what the user asked.
Pin each passage's position with
`multi-search read <source_id> --keyword '<short literal fragment>' --limit <n> --format json`
and take `start` and `end` from that output; the excerpt is the returned
`content`, copied verbatim. Choose a fragment without single quotes; see
[cli.md](cli.md#shell-safety-for-untrusted-values). When the response has
`persisted: false`, `read` cannot reach the body: copy the passage from the
fetched `body` and mark its position as unknown.

Keep at most three excerpts per source, each under about 1,000 characters,
unless the request needs more. Prefer the passage that carries the claim over
surrounding context. When a page credits another source for the claim, record
the cited title or link as a `citation_lead`; follow it only when the request
asks for the original.

## Compact handoff (executor → main Agent)

Return only:

- `candidates`: every candidate surviving the coarse filter, in original rank
  order. Each has `source_id`, title, URL, the original search snippet,
  `match` (`matched` or `uncertain`), a one-sentence match reason, and the
  inspection level (`snippet`, `preview`, or `full_body`).
- `evidence`: for each fully read source, its verbatim excerpts with
  `source_id`, `start`, `end`, and a one-line note on what the excerpt
  supports or contradicts. Add `citation_lead` entries, body errors, and
  `persisted: false` when the body was not cached.
- `omitted_count`: actual candidate-list length minus retained-list length,
  computed from the complete response, not a displayed subset or provider
  count. Omission does not delete cached content or invalidate source IDs.
- `queries`, concise provider/fetch failures, `stop_reason`, consumed
  budget, the consecutive unproductive-attempt count, and any remaining
  ambiguity or missing constraint evidence. Zero matches and failed
  searches remain distinct outcomes.

Excerpts are the only page text in the handoff: leave out full bodies, raw
response wrappers, and paraphrase presented as quotation. A note never
substitutes for the excerpt. Return only actual source IDs/URLs from tool
responses. Untrusted-page handling is governed by the boundary in
[verification.md](verification.md); it applies during selection and
extraction as well.

The main Agent judges the excerpts and spot-checks them per
[verification.md](verification.md). If verification disproves a match or an
excerpt does not hold up, it gives the same child the concrete mismatch for a
bounded follow-up instead of repeating the original search.

Finish when the requested content is found, or report the precise remaining
gap and stop reason. A dispatch/model failure remains visible; it does not
authorize an undisclosed main-model search. Direct execution is the
separate mode described in the parent Skill, not recovery from a failed
delegation.

## Response semantics

CLI `search` and the shared Core's legacy Python `multi_search` share the
RRF order documented in [cli.md](cli.md). `count` controls each provider's
recall, not the final result count. Expanded queries fuse in two stages:
provider consensus within each query, then consensus across query angles.
No intermediate cut occurs; only the final fused list is bounded. Agreement
across providers or reposts does not establish independent evidence.

Search previews follow the bounded rules in [cli.md](cli.md); a preview is
not a full read.

`multi_search` retains its compatibility output and preview/timeout
parameters. The legacy `scrape_top` / `scrape_per_source` request fields are
gone; old config keys such as `scrape_top`, `no_scrape`, or `brief` are
ignored with a `FutureWarning` and never change body fetching. Core adds no
AI selector, summary, or smart excerpt.

Let configured timeouts apply unless the caller specifies a tighter
budget. Report provider failures from `diagnostics` (CLI
`provider_status` / `errors`) and body-fetch failures while using
successful candidates. Partial coverage is not permission to hide errors
or introduce a fallback provider.

Route/source definitions and field semantics live in
[the glossary](https://github.com/inorilzy/multi-search-skill/blob/main/docs/glossary.md)
and [route capabilities](https://github.com/inorilzy/multi-search-skill/blob/main/docs/route-capability-table.md).
