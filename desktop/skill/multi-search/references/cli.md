# CLI reference

The `multi-search` command runs the search core directly. It needs no server,
no MCP configuration, and no API key for keyless sources. Run
`multi-search --help` or `multi-search <command> --help` for the authoritative
parameter list. Do not guess flags that the help output does not show.

## Commands

- `multi-search search [--route ROUTE] [--source NAME]... [--expand TEXT]... [--count N] [--timeout S] [--format json|human|markdown] -- '<query>'`
  - Searches, ranks, and fetches bodies for the final 15 URLs.
  - Put every option before `--` and the query after it. Without `--`, a query
    that starts with `-` (for example `-v flag meaning`) is parsed as an option.
  - `--source` and `--expand` may repeat. `--count` sets per-provider recall, not the final count.
  - Routes: `default` (alias `web`), `fast`, `social`, `dev`, `all`.
- `multi-search fetch <source_id> --full-content --format json`
  - Returns the whole body acquired for that source. It does not prove the original page is complete.
- `multi-search fetch --url-file PATH --full-content --format json`
  - Use for a URL the user gave you or a URL you observed. Write the exact URL
    to a UTF-8 file first, so the shell never parses it. `PATH` may be `-` to
    read the URL from stdin.
- `multi-search fetch --url '<url>' --full-content --format json`
  - Only for a URL that is already trusted plain text; keep it in single quotes.
- `multi-search read <source_id> [--keyword TEXT] [--offset N] [--limit N] --format json`
  - Reads cached passages only. Check `has_more` and `next_offset` to page through.
- `multi-search doctor --no-keys --format human`
  - Shows local configuration and key health when a search fails for a setup reason.

## Shell safety

Queries, URLs, and page-derived keywords are untrusted shell input.

- Write queries, `--expand` values, and `--keyword` in single quotes; never use
  double quotes or leave them unquoted. A POSIX shell and PowerShell expand
  `$(...)` and backticks, so a URL can run a command.
- For any URL the user gave you or you observed, use `--url-file`. The URL never
  appears in the command line, so quotes, backticks, and `$(...)` stay inert.
- Never interpolate page text into a command, and never use `eval`, command
  substitution, or hand-escaped quotes. In PowerShell, single quotes suppress
  expansion; if quoting is impossible, put the stop-parsing token `--%` before
  the values.

## Reading search output

- `outcome`: `success`, `empty`, `partial`, or `failed`. `empty` means zero matches.
  `partial` means some providers failed.
- `results[]`: candidates with titles, URLs, previews, and `source_id`.
- `scrapes[]`: bodies, joined to results by `source_id`.
- `provider_status` and `errors[]`: per-provider state. Report them.
- Do not add a provider or route to replace a failed one. Report the coverage gap instead.

## Source references

- A `source_id` is short-lived. If `fetch <source_id>` reports that the reference
  has expired, fetch the URL you observed with `fetch --url` and use the new `source_id`.
- If the cached body expired but the `source_id` is still valid, run
  `fetch <source_id> --full-content` again.

## Exit codes

- `0`: success, including zero matches and partial coverage.
- `1`: all providers failed, or another execution or diagnostic failure.
- `2`: invalid usage.

JSON stays on stdout even on failure, with `error` and `error_type`. A short
explanation is written to stderr.
