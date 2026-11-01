> Source: https://docs.parallel.ai/search/advanced-search-settings.md
> Retrieved: 2026-10-31
> Covers: POST /v1/search advanced_settings (source_policy, fetch_policy, excerpt_settings, location, max_results)


# Advanced Search Settings

> Advanced configuration for source policy, fetch policy, excerpt settings, location, and result count

For AI agents: a documentation index is available at [https://docs.parallel.ai/llms.txt](https://docs.parallel.ai/llms.txt). The full text of all docs is at [https://docs.parallel.ai/llms-full.txt](https://docs.parallel.ai/llms-full.txt). You may also fetch any page as Markdown by appending `.md` to its URL or sending `Accept: text/markdown`.

For Search and Extract, use `/v1/search` and `/v1/extract` for all new integrations and agent tool calls. Use `/v1beta/search` and `/v1beta/extract` only when maintaining an existing integration that already uses them. The request bodies changed too: on `/v1/extract`, `full_content`, `fetch_policy` and `excerpt_settings` go inside `advanced_settings`, and sending the v1beta top-level `excerpts`, `full_content` and `fetch_policy` to `/v1/extract` returns a 422. Do not substitute `/v1` for the documented FindAll or Ingest endpoint paths.

Use the `advanced_settings` object on the Search API to tune source selection, freshness, excerpt sizing, geo-targeting, and result count. The defaults suit most requests. Additional settings can reduce quality or increase latency.

For a coding agent that reads documentation from the existing index, see [Search indexed web content for coding agents](https://docs.parallel.ai/search/indexed-content-for-agents.md).

## Fields

| Field | Type | Notes | Example |
| - | - | - | - |
| source\_policy | [SourcePolicy](https://docs.parallel.ai/resources/source-policy.md) | Controls your sources: include/exclude domains or domain/path prefixes and optionally set a start date for freshness control via `after_date`. Search does not support path prefixes in `turbo` mode. Source filters can reduce result quality by excluding relevant pages, so use them only when your request needs them. See [Using include\_domains](#using-include_domains) below. | [Source policy example](https://docs.parallel.ai/resources/source-policy.md#example) |
| fetch\_policy | object | Controls when to return indexed content (faster) vs fetching live content (fresher). Default is to use cached content from the index. Enabling live fetch significantly increases latency. For more info including field details, see [Fetch Policy](https://docs.parallel.ai/extract/advanced-extract-settings.md#fetch-policy). | `{"max_age_seconds": 3600}` |
| excerpt\_settings | object | Controls excerpt sizes. Provide `max_chars_per_result` for fine-grained control, or omit to use defaults. | `{"max_chars_per_result": 10000}` |
| location | string | ISO 3166-1 alpha-2 country code for geo-targeted search results. See [Supported locations](#supported-locations) for the complete list. | `"us"`, `"gb"`, `"de"`, `"jp"` |
| max\_results | int | Upper bound on the number of results to return. Must be greater than 0 and defaults to 10. Public Search modes currently cap results at 20; higher requested values are reduced to 20 with an input validation warning. The API may return fewer results. | 10 |

## Supported locations

Set `advanced_settings.location` to one of the following ISO 3166-1 alpha-2 country codes. Codes are case-insensitive and normalized to lowercase.

| Country | Code |
| - | - |
| Argentina | `ar` |
| Australia | `au` |
| Austria | `at` |
| Belgium | `be` |
| Brazil | `br` |
| Canada | `ca` |
| Chile | `cl` |
| China | `cn` |
| Denmark | `dk` |
| Finland | `fi` |
| France | `fr` |
| Germany | `de` |
| Greece | `gr` |
| Hong Kong | `hk` |
| India | `in` |
| Indonesia | `id` |
| Italy | `it` |
| Japan | `jp` |
| Malaysia | `my` |
| Mexico | `mx` |
| Netherlands | `nl` |
| New Zealand | `nz` |
| Norway | `no` |
| Philippines | `ph` |
| Poland | `pl` |
| Portugal | `pt` |
| Russia | `ru` |
| Saudi Arabia | `sa` |
| South Africa | `za` |
| South Korea | `kr` |
| Spain | `es` |
| Sweden | `se` |
| Switzerland | `ch` |
| Taiwan | `tw` |
| Turkey | `tr` |
| United Kingdom | `gb` |
| United States | `us` |

For example:

```json theme={"system"}
{
  "search_queries": ["latest electric vehicle incentives"],
  "advanced_settings": {
    "location": "gb"
  }
}
```

> [!NOTE]
>
> Use `"gb"` for the United Kingdom, not `"uk"`. Invalid or unsupported values are ignored, and the response includes an input validation warning.

## Using include\_domains

> [!WARNING]
>
> Source policies can reduce result quality by excluding relevant pages from retrieval. Use `include_domains` and `exclude_domains` for compliance-bound corpora, tasks that require a single known publisher or section of a site, or requests that must block specific sources.

[`include_domains`](https://docs.parallel.ai/resources/source-policy) restricts retrieval to matching domains or domain/path prefixes. Search excludes the rest of the web. Treat this field as a hard allow list.

**Best practice:** Set `include_domains` only when answers must come **exclusively** from those domains or paths (for example, internal or compliance-bound corpora, or when the task truly requires a single known publisher). If the model or user might still need the open web, avoid `include_domains` and instead steer sources in the **`objective`** (e.g. "prefer official documentation") or use **`exclude_domains`** when you only need to block specific sites or paths. Full parameter details: [Source policy](https://docs.parallel.ai/resources/source-policy.md).
