# Search executor: dispatch, retrieve, and return

This document covers both halves of the search flow:

- **Dispatch** — how the main Agent hands the search task to a subagent (or
  runs it directly when delegation is unavailable).
- **Execution** — how the search executor runs the CLI, filters candidates,
  and returns the compact handoff.

A single document keeps the executor contract authoritative in one place.

## Choose the execution mode

The parent Skill decides which mode applies for this request:

- **Delegated** (default when the host supports subagents): the main Agent
  spawns one search subagent using the host's existing capability and a
  configured or explicitly available lightweight model. The subagent acts as
  the search executor and never delegates again.
- **Direct** (only when requested, or when the host lacks subagent
  capability): the main Agent runs the executor workflow itself, disclosing
  that delegation was skipped. A dispatch/model failure is an explicit error,
  not a license to silently switch to a different model.

### Host-specific dispatch

- **Codex:** use the available subagent tool with a configured lightweight
  search role, or its model override with an explicitly available lightweight
  model. Inspect role settings if needed: a fixed role model may override the
  requested model, and names such as `explorer` do not guarantee a particular
  model or tools.
- **Pi:** use the host's existing subagent tool/extension and configured
  agent definition. Follow that implementation's schema for model, context,
  and tool access. A graph is not required. Prefer the multi-search CLI
  through the child's command tool.
- **Claude Code:** use the built-in `Task` (subagent) tool. Spawn one
  `general-purpose` (or equivalent read-capable) subagent and pass the task
  packet described below in its prompt. Select a lightweight model via the
  host's supported mechanism (e.g. the `model` parameter when exposed); do
  not silently inherit the parent model when a cheaper one is configured. The
  subagent runs `multi-search` through its shell tool and returns the compact
  handoff described below.

Use only a model exposed and permitted by the host; a model already known to
be rejected for this account is not eligible. Keep model IDs, providers,
credentials, and reasoning settings in host configuration or supported
dispatch parameters, not hardcoded in this Skill. Lower reasoning effort
alone does not select a cheaper model. Missing model configuration or tool
access is a setup error; report it instead of installing an extension,
adding an API client, or silently inheriting the main model.

## Dispatch once, before searching

Give one search subagent:

- The original search request and relevant object/version/platform/time/
  source constraints, including the requested result type, remaining budget,
  and count of consecutive unproductive targeted attempts (initially zero).
- The local path to this Skill, its explicit role as **search executor**, and
  the instruction to follow the **Executor** section below without
  delegating.
- The usable CLI command and working directory. Have the child read
  [cli.md](cli.md); pass paths/config references, not secrets.

Use a fresh/isolated context containing this task packet rather than the full
conversation when the host supports it. Keep unrelated history and the main
Agent's reasoning out of the packet. If isolation is unavailable, disclose
that limitation; do not claim the same token savings.

The child receives the full search response; the main Agent does not retrieve
or read it first. The child inspects titles, URLs, snippets and body previews.
If no useful candidate appears, it may correct the query for a specific
mismatch or missing clue within the parent Skill's stopping rules. It returns
candidates, not a research report. It removes only clearly irrelevant results,
with no retention quota; the parent makes the final selection from original
previews and performs necessary full-body verification.

## Executor: query and route

Keep the original object, version/platform, time window, and exclusions in
`query`. Exact identifiers and quick lookups can stay unexpanded. When
alternate wording helps find the same target, add up to three purposeful
`expand` variants: official terminology, likely page title, or another
language. Submit them with the main query; do not turn variants into new
research topics.

`route` selects sources; all routes rank then fetch:

- Omit it for ordinary web search (`default`; `web` is an alias).
- `fast`: smaller set of low-latency, content-capable web providers.
- `social`: Twitter/X feedback. Search supplies candidates and text snippets;
  selected X URLs use the dedicated XKit scraper for `.full_text` and up to
  20 loaded replies. Reply omissions or failures are stated in the Markdown.
  `full_content` means all acquired text, not all replies in the conversation.
- `dev`: GitHub repositories, Stack Overflow, and Hacker News.
- `all`: broadest API fanout.
- `sources=[...]` names exact providers and bypasses route profiles. For
  V2EX topics, use `sources=["sov2ex"]` (also included in `all`). Its
  anonymous third-party SOV2EX API supplies titles, URLs, and highlight
  snippets. Indexed topic bodies are discarded; selected URLs are fetched
  after ranking.

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
match check. Remove only clearly irrelevant candidates. Return every
remaining candidate, including uncertain matches and distinct plausible
interpretations. There is no target count or retention cap: if every
candidate from the search response remains relevant or uncertain, return
them all in the original ranked order. Missing bodies and fetch errors
alone do not establish irrelevance. Forward original previews for the main
Agent's judgment.

If nothing useful appears, correct a specific mismatch or missing clue
within the parent Skill's stopping rules. Preserve the accumulated budget
and count of unproductive targeted attempts across follow-ups.

## Compact handoff (delegated executor → main Agent)

Return only:

- `selected`: every candidate surviving the coarse filter, in original rank
  order; this is not the parent's final selection. Include original
  `source_id`, title and URL, the unchanged body preview (size and offset
  rules are documented in [cli.md](cli.md)), and available `preview_start`,
  `preview_end`, and `truncated` metadata. Keep the original search snippet
  separately, especially when no body is available; a match reason never
  substitutes for the source's actual text. Include `match` (`matched` or
  `uncertain`), a one-sentence match reason, and any body error. State what
  was inspected (`snippet`, `preview`, or `full_body`); classification from
  a preview is not full-body verification.
- `omitted_count`: actual candidate-list length minus retained-list length,
  computed from the complete response, not a displayed subset or provider
  count. Omission does not delete cached content or invalidate original
  source IDs.
- `queries`, concise provider/fetch failures, `stop_reason`, consumed
  budget, the consecutive unproductive-attempt count, and any remaining
  ambiguity or missing constraint evidence. Zero matches and failed
  searches remain distinct outcomes.

Keep explanations short while preserving every retained candidate's
original preview; the full RRF result list may survive. Omit raw response
wrappers and full page bodies. Return only actual source IDs/URLs from tool
responses. Untrusted-page handling is governed by the boundary in
[verification.md](verification.md); it applies during selection as well as
verification.

The parent reviews the retained previews, makes the final selection, and
uses those source IDs to fetch necessary bodies per
[verification.md](verification.md). If parent and child do not share the
source store, use the returned observed URLs and the normal fetch path;
never invent mappings. Respect existing retention and expiry rules. If
verification disproves a match, give the same child the concrete mismatch
for a bounded follow-up instead of repeating the original search.

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
parameters; `scrape_top` no longer selects how many URLs to fetch. Core
adds no AI selector, summary, or smart excerpt.

Let configured timeouts apply unless the caller specifies a tighter
budget. Report provider failures from `diagnostics` (CLI
`provider_status` / `errors`) and body-fetch failures while using
successful candidates. Partial coverage is not permission to hide errors
or introduce a fallback provider.

Route/source definitions and field semantics live in
[the glossary](https://github.com/inorilzy/multi-search-skill/blob/main/docs/glossary.md)
and [route capabilities](https://github.com/inorilzy/multi-search-skill/blob/main/docs/route-capability-table.md).
