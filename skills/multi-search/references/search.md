# Search executor: retrieve and select

Use this workflow as the delegated search executor or in explicitly chosen
direct mode. Return candidates, not a research plan or report. Do not delegate.

## Query and route

Keep the original object, version/platform, time window, and exclusions in
`query`. Exact identifiers and quick lookups can stay unexpanded. When alternate
wording helps find the same target, add up to three purposeful `expand` variants:
official terminology, likely page title, or another language. Submit them with
the main query; do not turn variants into new research topics.

`route` selects sources; all routes rank then fetch:

- Omit it for ordinary web search (`default`; `web` is an alias).
- `fast`: smaller set of low-latency, content-capable web providers.
- `social`: Twitter/X feedback. Search supplies candidates and text snippets;
  selected X URLs use the dedicated XKit scraper for `.full_text` and up to
  20 loaded replies. Reply omissions or failures are stated in the Markdown.
  `full_content` means all acquired text, not all replies in the conversation.
- `dev`: GitHub repositories, Stack Overflow, and Hacker News.
- `all`: broadest API fanout.
- `sources=[...]` names exact providers and bypasses route profiles.
  For V2EX topics, use `sources=["sov2ex"]` (also included in `all`). Its anonymous
  third-party SOV2EX API supplies titles, URLs, and highlight snippets. Indexed
  topic bodies are discarded; selected URLs are fetched after ranking.

## Inspect and select

Join `results[].content` and `scrapes[].markdown` by `source_id`; inspect titles,
URLs, snippets, and acquired body previews. Legacy `multi_search` may put bodies
once in top-level `markdown`, with source references in each section.

Check the target, version/platform, content type, and direct relevance. Classify
promising candidates as `matched` or `uncertain`. Missing detail in a preview
is uncertainty, not proof of irrelevance. RRF agreement is not a match check.
Remove only clearly irrelevant candidates. Return every remaining candidate,
including uncertain matches and distinct plausible interpretations. There is no
target count or retention cap: if all 15 remain relevant or uncertain, return all
15 in the original ranked order. Missing bodies and fetch errors alone do not
establish irrelevance. Forward original previews for the main Agent's judgment.

If nothing useful appears, correct a specific mismatch or missing clue within
the parent Skill's stopping rules. Preserve the accumulated budget and count
of unproductive targeted attempts across follow-ups.

Delegated executor: return the [compact handoff](subagents.md#compact-handoff)
and stop. The parent reviews previews, makes the final selection, and verifies
necessary full bodies. Direct executor: return matching
links with inspection levels, or follow [verification.md](verification.md) when
match confirmation or claims about contents need bodies.

## Response semantics

MCP `search_web`, CLI `search`, and legacy `multi_search` share RRF order and
fetch up to 15 final URLs. `count` controls each provider's recall, not the
final result count. Expanded queries fuse in two stages: provider consensus
within each query, then consensus across query angles. No intermediate 15-result
cut occurs; only the final fused list is limited to 15. Agreement across
providers or reposts does not establish independent evidence.

Search returns up to 1200 characters per acquired body by default. A bounded
preview starts at an exact matching page H1, or a paragraph matching the
complete search snippet (at least 32 non-space characters; whitespace differences
only). Otherwise it starts at the beginning. `preview_start` / `preview_end`
identify the unchanged body's character range. A preview is not a full read.

`multi_search` retains its compatibility output and preview/timeout parameters;
`scrape_top` no longer selects how many URLs to fetch. Core adds no AI selector,
summary, or smart excerpt.

Let configured timeouts apply unless the caller specifies a tighter budget.
Report provider failures from `diagnostics` (CLI `provider_status` / `errors`)
and body-fetch failures while using successful candidates. Partial coverage is
not permission to hide errors or introduce a fallback provider.

Route/source definitions and field semantics live in
[the glossary](https://github.com/inorilzy/multi-search-skill/blob/main/docs/glossary.md)
and [route capabilities](https://github.com/inorilzy/multi-search-skill/blob/main/docs/route-capability-table.md).
