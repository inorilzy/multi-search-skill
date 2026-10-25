# CLI-only installation and workflow

Requires Python 3.10+, Git, and [uv](https://docs.astral.sh/uv/getting-started/installation/).
The CLI runs Core directly; no MCP server or MCP client configuration is needed.

## Install

This MCP-free migration is currently a local candidate, not a new published
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
there is no MCP entrypoint, dependency, client configuration, or persistent service.

If the command is absent from PATH, run `uv tool update-shell` and reopen the
terminal. Without uv, use a virtual environment and `python -m pip install .`
from the checkout, then `python -m multi_search_mcp.cli --help`.

Provider keys resolve once per provider: environment variables, then the
credential store, then `~/.search-keys.json`. The credential store is the
shared `~/.multi-search/config.sqlite` database written by the desktop app;
values are encrypted with the current Windows user's DPAPI (no plaintext
fallback elsewhere), and `MULTI_SEARCH_CONFIG_DB` selects an alternate database
only for an explicitly isolated runtime. An unreadable store entry fails that
provider closed instead of falling back to the plaintext file. No credentials
belong in these commands. Non-secret configuration resolves from
`MULTI_SEARCH_CONFIG`, the `config.sqlite` settings record when present,
`~/.multi-search/multi-search-config.json`, then the checkout default. An
explicitly configured missing file is an error.

Twitter/X cookies use `file` mode by default (a plaintext cookie file named by
`TWITTER_COOKIES_PATH` or the saved `twitter_cookies_path`). After an explicit
desktop import they use `managed` mode: a DPAPI-encrypted store entry decrypted
only for X calls. Managed mode never falls back to the file and fails closed on
a missing or unreadable entry or outside Windows.

The `xkit-py` dependency for Twitter/X is currently commented out in
`pyproject.toml` (its repository is private), so Twitter/X search and post
fetching return an explicit "install xkit" error while every other source works.
When it is re-enabled, CLI installations include `xkit-py` automatically, from
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

## Shell safety for untrusted values

Queries, URLs, and page-derived keywords are untrusted data. Never paste one
into a command line unquoted or inside double quotes: a POSIX shell expands
`$(...)` and backticks in unquoted text, and PowerShell expands them in
double-quoted strings, so a URL can run a command.

- Write queries, `--expand` values, and `--keyword` in single quotes. Do not
  interpolate page text into a command; choose a short literal fragment.
- For a URL the user supplied or you observed, write the exact URL to a UTF-8
  file with your file-writing tool and pass the path:

  ```sh
  multi-search fetch --url-file /tmp/multi-search-url.txt --full-content --format json
  ```

  `--url-file -` reads the URL from stdin. Use `--url` only for plain text you
  already trust, in single quotes.
- In PowerShell, single quotes suppress expansion; if quoting is impossible, put
  the stop-parsing token `--%` before the values. Never use double quotes for
  untrusted text.
- Never use `eval`, command substitution, or hand-escaped quotes to pass page
  content. If a value contains a single quote, keep it out of the command line
  (`--url-file`) or shorten it instead of escaping by hand.

## Search, select, fetch, verify

In delegated mode, the search subagent runs the search commands and returns the
handoff from [executor.md](executor.md). The main Agent reviews the retained
original previews, makes the final selection, and fetches necessary bodies.

```sh
multi-search doctor --no-keys --format human
multi-search search --source hackernews --count 3 --format json -- 'Python TaskGroup cancellation'
multi-search search --route dev --expand 'TaskGroup ExceptionGroup' --expand 'TaskGroup cancellation semantics' --format json -- 'Python TaskGroup cancellation'
```

Put options first and the query after `--` (`multi-search search [options] -- '<query>'`).
Without `--`, a query that starts with `-` is parsed as an option and the
command fails with a usage error (exit 2) or, worse, changes the search.

`--route` selects a configured route-group id. `--source` and `--expand` can
repeat; explicit sources replace the selected group's source list for that
request, while globally disabled sources are still filtered. Route groups live
in the settings record as a complete `routes` map (shown in its JSON shape):

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
as an alias for `default`. For an id beginning with `-`, use the equals form,
for example `--route=-focus`. Labels are trimmed to 1-80 characters. Sources use
the twelve canonical search ids (legacy aliases such as `github` and `v2ex` are
normalized and duplicates removed), and each group needs at least one. Group
timeout is `null`/omitted to inherit or an integer from 1 through 60. An
explicit `routes` map is authoritative: deleted built-ins are not restored.
When `routes` is absent, the five built-in groups are supplied. Timeout
precedence is command `--timeout`, group timeout, global config timeout, then
the built-in route behavior. The configured `type` must name an existing group.

`--no-fetch` returns fused, ranked candidates only: no page bodies are fetched
and nothing is written to the body cache; every result still carries a
`source_id` for a later `fetch`. `--no-state` skips SQLite key rotation, the
content cache, and site memory for clean test or debug runs.

`--count` controls each provider's recall; Core ranks and fetches up to 15 final URLs. Keep configured timeouts unless the
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
multi-search read src_... --keyword 'TaskGroup' --limit 2000 --format json
multi-search fetch --url-file /tmp/multi-search-url.txt --full-content --format json
```

The last form keeps an observed or user-supplied URL out of the shell; see
[Shell safety](#shell-safety-for-untrusted-values).

`fetch --full-content` returns all acquired text, subject to acquisition and
retention limits. It does not prove the original page or discussion is complete.
`read` only reads cached passages; inspect `has_more` and `next_offset` for
paging. If content expired, fetch the source again. If the source reference
itself expired, write its previously observed URL to a file, fetch it with
`--url-file`, and use the new source ID.

The generic scrape backend chain is configured once per settings record in the
top-level `scrape_backends` array (siblings: `scrape_chars`, `scrape_timeout`).
Its order is the fallback priority: when a backend cannot fetch the page, the
next one is tried. Allowed values are `jina`, `exa`, `tavily`, and `firecrawl`;
duplicates are ignored after their first position. Omitted or `null` keeps the
default order `["jina", "exa", "tavily", "firecrawl"]`. An explicit empty array
or an unknown name is a configuration error. Key-requiring backends (Exa and
Tavily) without a configured key are skipped at runtime; Jina and Firecrawl
allow anonymous scraping, so the default chain still starts with anonymous Jina.
`--backend` only overrides the chain for that single `fetch` call and is not
saved to settings. Reddit and Twitter/X URLs always use their dedicated
scrapers. Site memory then adjusts the order per site: a pinned backend
(`site set-preference`) moves first and a cooling backend moves last; success
counts never reorder the chain.

A body larger than the cache's per-object UTF-8 byte limit is still returned in
full for that call but is not stored: the response has `persisted: false` and a
`persist_error`, so `read` and later fetches of that `source_id` cannot reuse it.

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

Maintenance commands share the same Core state: `multi-search keys status` /
`keys reset`, `multi-search sources --key-status --scraper-stats`, and
`multi-search site stats [site]`, `site set-preference <site> <scraper>
[--priority N] [--note TEXT]`, `site reset [site]`. `multi-search migrate-legacy plan --keys-file <path>`
and `migrate-legacy apply --keys-file <path> --request <json>` move single-key
entries from a legacy keys file into the credential store after a masked
preview and explicit per-provider approval; the legacy file is never deleted.
Prefer these over the legacy Python adapter module, which only forwards to Core.

Completion: the CLI runs, the search outcome is visible, and matching links are
identified or the bodies needed for the answer were read (or failures recorded).
Each claim about page contents cites inspected supporting material. Use the
parent Skill's delegation, evidence and stopping rules.
