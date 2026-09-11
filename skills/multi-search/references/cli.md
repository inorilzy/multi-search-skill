# CLI-only installation and workflow

Requires Python 3.10+, Git, and [uv](https://docs.astral.sh/uv/getting-started/installation/).
The CLI runs Core directly; no MCP server or MCP client configuration is needed.

## Install

Install the pinned release:

```sh
uv tool install "git+https://github.com/inorilzy/multi-search-skill.git@v0.3.3"
multi-search --help
```

From a local checkout, including uncommitted fixes, run at the repository root:

```sh
uv tool install --force .
multi-search --help
```

The GitHub command installs the pinned release. Replace `v0.3.3` with `main`
only when following development changes; unpublished local changes require
the local command. To update an existing installation to this release:

```sh
uv tool install --force --reinstall "git+https://github.com/inorilzy/multi-search-skill.git@v0.3.3"
```

If the command is absent from PATH, run `uv tool update-shell` and reopen the
terminal. Without uv, use a virtual environment and `python -m pip install .`
from the checkout, then `python -m multi_search_mcp.cli --help`.

API keys and cookies retain their existing environment / `~/.search-keys.json`
locations. No credentials belong in these commands. Non-secret configuration
resolves from `MULTI_SEARCH_CONFIG`, `~/.multi-search/multi-search-config.json`,
then the checkout default. An explicitly configured missing file is an error.

## Search, select, fetch, verify

In delegated mode, the search subagent runs the search commands and returns the
handoff from [subagents.md](subagents.md). The main Agent reviews the retained
original previews, makes the final selection, and fetches necessary bodies.

```sh
multi-search doctor --no-keys --format human
multi-search search "Python TaskGroup cancellation" --source hackernews --count 3 --format json
multi-search search "Python TaskGroup cancellation" --route dev --expand "TaskGroup ExceptionGroup" --expand "TaskGroup cancellation semantics" --format json
```

`--source` and `--expand` can repeat. `--count` controls each provider's recall;
Core ranks and fetches up to 15 final URLs. Keep configured timeouts unless the
user supplies a tighter budget. Inspect `results`, `scrapes` matched by
`source_id`, `provider_status`, and `errors`, then remove only clearly irrelevant
candidates. Retain all relevant or uncertain candidates without a count quota,
in original rank order, with original previews for the main Agent to review.
Search previews can start at a matching page title or a paragraph matching the
complete search snippet to skip leading navigation. Snippet matching requires
at least 32 non-space characters and allows only whitespace differences.
Their `preview_start` / `preview_end` are zero-based character offsets in the
unchanged acquired body; the end is exclusive. `truncated` also covers an omitted
prefix. A body that fits the preview budget is returned whole.
Replace `src_...` below with an actual returned identifier:

```sh
multi-search fetch src_... --full-content --format json
multi-search read src_... --keyword "TaskGroup" --limit 2000 --format json
multi-search fetch --url "https://docs.python.org/3/library/asyncio-task.html" --full-content --format json
```

`fetch --full-content` returns all acquired text, subject to acquisition and
retention limits. It does not prove the original page or discussion is complete.
`read` only reads cached passages; inspect `has_more` and `next_offset` for
paging. If content expired, fetch the source again. If the source reference
itself expired, fetch its previously observed URL and use the new source ID.

Exit codes: `0` for success (including zero matches or partial search coverage),
`1` for all search providers failing or another execution/diagnostic failure,
`2` for invalid CLI usage. JSON remains machine-readable on stdout, including
search failures; human/Markdown also show provider errors. Failures have a
short stderr explanation. Partial failures must still be reported by the Agent.
On Windows, redirected CLI stdout/stderr use UTF-8, including non-ASCII bodies;
console streams retain their existing encoding.

`doctor --network` probes the public Hacker News and GitHub APIs under a shared
5-second budget. `network_checked` records probe execution; `network_ok` and
`network_checks` record results. This checks those endpoints' connectivity,
not every provider's credentials, quota, or search quality.

Completion: the CLI runs, the search outcome is visible, and matching links are
identified or the bodies needed for the answer were read (or failures recorded).
Each claim about page contents cites inspected supporting material. Use the
parent Skill's delegation, evidence and stopping rules.
