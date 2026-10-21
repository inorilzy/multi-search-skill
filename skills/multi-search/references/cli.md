# CLI installation and workflow

Requires Python 3.10+, Git, and [uv](https://docs.astral.sh/uv/getting-started/installation/).
The `multi-search` command runs the shared Core directly. There is no server,
no daemon, and no agent-tool adapter to configure.

## Install

This build is currently a local candidate, not a new published
release. The historical `v0.4.0` tag does not include these changes. From the
verified local checkout, run at the repository root:

```sh
uv tool install --force .
multi-search --help
```

To reinstall the same local candidate use `uv tool install --force --reinstall .`.
Do not substitute guessed remote tags or URLs for the verified local artifact.
The historical distribution/module name `multi-search-mcp` / `multi_search_mcp`
is retained for compatibility; the only product command is `multi-search` and
there is no remote service, daemon, or per-agent adapter to configure.

If the command is absent from PATH, run `uv tool update-shell` and reopen the
terminal. Without uv, use a virtual environment and `python -m pip install .`
from the checkout, then `python -m multi_search_mcp.cli --help`.

The CLI reads settings and provider credentials from the shared SQLite database
at `~/.multi-search/config.sqlite`; credential values are protected with DPAPI.
`MULTI_SEARCH_CONFIG_DB` selects an alternate database for an explicitly isolated
runtime. Legacy provider environment variables and JSON settings files are not
implicit runtime inputs. `~/.search-keys.json` is read only by an explicit
one-time migration helper; it is not consulted during normal search. The saved
Twitter cookie path is a non-secret settings reference; cookie contents and
provider keys do not belong in these commands.

CLI installations include `xkit-py` for Twitter/X automatically, from
the GitHub commit pinned in the project dependencies. The PyPI 2.6.3 archives
omit the client subpackage, so installing `xkit-py` separately is insufficient.
The pinned repository is private: installation requires Git credentials with
read access, including in CI. For an authorized GitHub CLI account, run
`gh auth login` and `gh auth setup-git` if working Git credentials are absent;
do not put credentials in dependency URLs. In a
checkout, `uv sync --locked` installs all dependencies and removes the retired
`twikit-ng` distribution. Both distributions own the `twikit` module directory;
when upgrading an existing pip environment, uninstall `twikit-ng` before
installing the project. XKit uses saved cookies and initializes its X web
session on the first request; no browser installation or separate setup command
is needed. Installation success does not verify X connectivity or authentication.

## Commands and flags

`multi-search --help` and `multi-search <command> --help` are authoritative; do
not guess flags the help does not show. The full surface shipped by this CLI:

- `multi-search search "<query>" [--route ROUTE] [--source NAME]... [--expand TEXT]... [--count N] [--timeout S] [--no-scrape] [--format json|human|markdown]`
  - Searches the configured or selected sources, ranks the union by RRF, and
    fetches bodies for the final 15 URLs. `--source` and `--expand` may repeat.
    `--count` sets per-provider recall, not the final count. `--no-scrape`
    skips the body-fetch stage for this call only; results still carry
    `source_id` so a later `fetch` can read them.
- `multi-search fetch [<source_id> | --url "<url>"] [--full-content] [--backend NAME]... [--max-chars N] [--timeout S] [--format ...]`
  - Exactly one of `source_id` or `--url` is required. `--backend` may repeat
    to restrict the scraper chain for this call. `--max-chars` caps the body
    preview (default 20000); `--full-content` overrides it and returns every
    acquired character, subject to acquisition/retention limits.
- `multi-search read <source_id> [--keyword TEXT] [--offset N] [--limit N] [--format ...]`
  - Reads cached passages only; never touches the network. `limit` is clamped
    to 8000 characters per call. Inspect `has_more` and `next_offset` to page
    through.
- `multi-search doctor [--network] [--no-keys] [--format ...]`
  - `--no-keys` skips key health; `--network` probes public Hacker News and
    GitHub APIs under a shared 5-second budget. Reports configuration and key
    state read from `config.sqlite`.
- `multi-search keys status [--provider NAME] [--format ...]`
  - Lists per-key health rows (provider, key id, current status) from the
    SQLite key manager. Useful to confirm rotation is healthy or to spot a
    key stuck in `cooldown` / `invalid` / `quota_exhausted`.
- `multi-search keys reset [--provider NAME] [--key-id ID] [--format ...]`
  - Clears key-health rows so a previously disabled or invalid key can rejoin
    rotation. With no flags, resets every row. Use sparingly; resetting a key
    that genuinely fails will only re-trigger the same failure on next use.

## Search, select, fetch, verify

In delegated mode, the search subagent runs the search commands and returns the
handoff from [executor.md](executor.md). The main Agent reviews the retained
original previews, makes the final selection, and fetches necessary bodies.

```sh
multi-search doctor --no-keys --format human
multi-search search "Python TaskGroup cancellation" --source hackernews --count 3 --format json
multi-search search "Python TaskGroup cancellation" --route dev --expand "TaskGroup ExceptionGroup" --expand "TaskGroup cancellation semantics" --format json
```

`--route` selects a configured route-group id. `--source` and `--expand` can
repeat; explicit sources replace the selected group's source list for that
request, while globally disabled sources are still filtered. Route groups live
in the SQLite settings record as a complete `routes` map (shown below in its
JSON value shape):

```json
{
  "type": "research",
  "routes": {
    "research": {
      "label": "Research",
      "sources": ["hackernews", "github_repos", "stackoverflow"],
      "timeout": 30
    }
  }
}
```

Each id is 1-64 ASCII lowercase letters, digits, `_`, or `-`; `web` is reserved
as an alias for `default`. For an id beginning with `-`, pass the explicit CLI
selection in equals form, for example `--route=-focus`. Labels are trimmed to
1-80 characters. Sources use
the twelve canonical search ids (legacy aliases such as `github` and `v2ex`
are normalized and duplicates removed), and each group needs at least one.
Group timeout is `null`/omitted to inherit or an integer from 1 through 60.
An explicit `routes` map is authoritative: deleted built-ins are not restored.
When `routes` is absent, the five legacy groups are supplied for compatibility.
Timeout precedence is command `--timeout`, group timeout, global config timeout,
then the built-in route behavior. The configured `type` must name an existing
group.

`--count` controls each provider's recall; it does not change the final
RRF-cut size documented above under `search`. Keep configured timeouts unless
the user supplies a tighter budget.
Inspect `results`, `scrapes` matched by
`source_id`, `provider_status`, and `errors`, then remove only clearly irrelevant
candidates. Retain all relevant or uncertain candidates without a count quota,
in original rank order, with original previews for the main Agent to review.
Search returns up to 1200 characters per acquired body by default. A bounded
preview starts at an exact matching page title or a paragraph matching the
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
search failures and execution errors (`error` / `error_type`); human/Markdown
also show provider errors. Search JSON includes `outcome`: `success`, `empty`,
`partial`, or `failed`. These distinguish zero matches from incomplete coverage
and total provider failure without discarding per-provider errors. Failures have a
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
