# Built-in provider plugin contract

The declarations in `builtin/<vendor>.py` own vendor membership, search calls,
channel metadata, auth methods and balance adapters. They perform no HTTP,
credential reads or discovery at import time. The registry supports built-ins
only; entry points and external plugin loading were rejected as out of scope.

- `builtin_plugins()` returns a tuple in the previous search registry order;
  GitHub contributes repos then code, and scrape-only Jina comes last.
  `get_plugin(id)` accepts exact credential-provider ids and raises `KeyError`
  for an unknown id, rather than silently accepting a misspelling. Stack
  Overflow belongs to `stackexchange`; Hacker News and SOV2EX have no key pool.
- `ProviderPlugin.search_sources` lists capability names. `search_specs()`
  returns fresh `ProviderSpec` objects, using the existing capability metadata
  helper. Vendor lambdas read `search.registry.search_*` at invocation time.
  Moving the function imports into plugins or caching specs was rejected:
  existing callers patch those historical symbols, even after registry creation.
- `scrape_backends` contains immutable `ScrapeBackendSpec` declarations. The
  public `scrape_channels` tuple is filled from them when omitted, including the
  historical `jina` and `firecrawl` names. Each channel declares its credential
  provider, required/anonymous flags, dispatcher name, and numeric `order`.
  `legacy_channels` marks a historical name and records its expansion order.
  Separate channel order was chosen because the existing scrape chain differs
  from search order. Both support constants and scrape tables consume these
  declarations; no second literal channel list is maintained.
- Dispatcher names resolve to the existing functions in `scrape.scrape`.
  Implementations remain there, including their late reads of `scrape_url_*`.
  Importing the scrape module from plugin declarations was rejected because
  support/backend imports need declarations before the dispatcher is loaded.
  The historical `scrape.scrape.ScrapeBackendSpec` import remains available.

## Balance and auth extensions

`AuthMethod(type, label, credential, purpose="search_key")` is a frozen
dataclass. `api` means stdin credential entry, including Twitter cookies, not
an HTTP auth scheme. Firecrawl also declares OAuth for its search key. Parallel
OAuth writes `parallel_account` for `balance_only`. Exa declares an additional
API credential `exa_admin` for `balance_only`. These declarations do not start
login flows.

`ProviderPlugin.balance` is either `None` or a callable with the contract
`(credential: str, ctx: BalanceContext) -> BalanceReport | list[BalanceReport]`.
Most adapters return one report; a list carries providers that expose several
independent quotas (Tavily key/account, GitHub search/code_search). All adapters
are left `None` in ticket 01. Later tickets can define the callback in their
vendor module and pass it into `PLUGIN`. The registry reads each module's current
`PLUGIN`, so replacing a frozen declaration also works without a stale registry
cache. `balance_credential` defaults to `key_provider`; an explicit empty string
means the credential is optional and the adapter falls back to an anonymous
query. Exa uses `exa_admin` and Parallel uses `parallel_account`.
`balance_ttl_seconds` defaults to 300; callers enforce caching, while adapters
only fetch/interpret their report.

`BalanceContext(timeout=10.0, deadline=None, http=...)` accepts a
`urlopen_retry`-compatible HTTP callable. `ctx.open(request, retries=2)` checks the
monotonic deadline, clamps the per-call timeout, and forwards timeout, retries
and deadline to that callable. It returns urllib's context-manager/read response
protocol. The default is the current `support.http.urlopen_retry`; tests inject
`http=fake` and never need external network. Returning a custom response wrapper
or adding a second retry implementation was rejected in favor of the existing
HTTP size, redirect and deadline protections.

`BalanceReport(provider, status, ...)` is a frozen dataclass whose `to_dict()`
includes every spec field, preserving unknown numbers as `None`. Scope defaults
to `key` and unit to `requests`; adapters set their actual scope/unit. Timestamps
are ISO8601 strings; `fetched_at` defaults to UTC now. Error kinds use the existing
`support.models.ERROR_KIND_*` strings. Adapters reuse `state.key_state.key_fingerprint`
and scrub messages before constructing reports: raw credentials and provider
response objects do not belong in this public data contract. Automatic HTTP or
secret processing in the dataclass was rejected to keep serialization pure.
