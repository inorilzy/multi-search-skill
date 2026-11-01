> Source: https://docs.parallel.ai/search/search-migration-guide.md
> Retrieved: 2026-10-31
> Covers: /v1beta/search -> /v1/search migration


# Upgrade from Beta to GA

> Migrate from Beta to GA (V1) Search API

For AI agents: a documentation index is available at [https://docs.parallel.ai/llms.txt](https://docs.parallel.ai/llms.txt). The full text of all docs is at [https://docs.parallel.ai/llms-full.txt](https://docs.parallel.ai/llms-full.txt). You may also fetch any page as Markdown by appending `.md` to its URL or sending `Accept: text/markdown`.

For Search and Extract, use `/v1/search` and `/v1/extract` for all new integrations and agent tool calls. Use `/v1beta/search` and `/v1beta/extract` only when maintaining an existing integration that already uses them. The request bodies changed too: on `/v1/extract`, `full_content`, `fetch_policy` and `excerpt_settings` go inside `advanced_settings`, and sending the v1beta top-level `excerpts`, `full_content` and `fetch_policy` to `/v1/extract` returns a 422. Do not substitute `/v1` for the documented FindAll or Ingest endpoint paths.

This guide helps you migrate from the Beta Search API (`/v1beta`) to the GA version (`/v1`).

> [!NOTE]
>
> The V1 Search API is generally available and recommended for all new integrations. This guide explains how to migrate existing Beta integrations to V1's current modes and request fields.

## Highlights

1. **`search_queries` is now required** — At least one non-empty query must be provided. In Beta, only one of `objective` or `search_queries` was required.

2. **Settings reorganized under `advanced_settings`** — `source_policy`, `fetch_policy`, excerpt settings, and `max_results` are now nested under a single new `advanced_settings` object (previously top-level fields). See [Advanced Settings](https://docs.parallel.ai/search/advanced-search-settings.md) for more details.

3. **New `location` field** — Set `advanced_settings.location` to an ISO 3166-1 alpha-2 country code (e.g., `"us"`, `"gb"`, `"de"`, `"jp"`) to geo-target search results. Only a subset of countries are currently supported; unsupported or invalid values are ignored with a warning.

4. **Updated modes** — V1 has four modes (`turbo`, `fast`, `basic`, `advanced`), with `advanced` as the new default. For most use cases, map both `fast` and `one-shot` to `fast`, and map `agentic` to `advanced`. V1 `fast` delivers high-quality results in around 700ms and is the recommended default. V1 `basic` remains available if you want longer excerpts similar to the old `one-shot` output.
   * **`fast`**: The suggested replacement for Beta `fast` and `one-shot`, and the recommended default for most agents. It delivers high-quality results in around 700ms.
   * **`basic`**: Returns extended snippets per result and works best with 2-3 high-quality search\_queries. Choose it when you want longer excerpts per source in a single call, similar to the old `one-shot`-style output.
   * **`advanced`** (default): The V1 equivalent of Beta `agentic`. Provides higher quality with more advanced retrieval and compression. Best for complex queries where result quality matters more than latency.
   * **`turbo`** (new in V1): A lower-latency, lower-cost mode for real-time, high-volume grounding, with no Beta equivalent. It typically returns results in around 200ms. See [Search Modes](https://docs.parallel.ai/search/modes.md).

## Overview of Changes

| Component | Beta | V1 |
| - | - | - |
| **Endpoint** | `/v1beta/search` | `/v1/search` |
| **Modes** | `fast`, `one-shot`, `agentic` (default `one-shot`) | `turbo`, `fast`, `basic`, `advanced` (default `advanced`). Beta `fast` and `one-shot` map to `fast`; `agentic` maps to `advanced`. Choose `basic` for longer excerpts similar to the old `one-shot`-style output. |
| **SDK method** | `client.beta.search()` (`parallel-web` before 1.0) | `client.search()` (`parallel-web` 1.0+) |
| **`search_queries`** | Optional (one of `objective` or `search_queries` required) | Required (at least one non-empty query) |
| **`objective`** | Required if `search_queries` omitted | Optional |
| **`max_chars_total`** | Inside `excerpts` object | Promoted to top-level request field |
| **`client_model`** (new) | — | Top-level field for model-specific optimizations |
| **`location`** (new) | — | `advanced_settings.location` — ISO 3166-1 alpha-2 country code for geo-targeted results |
| **`advanced_settings`** (new) | — | New object nesting `source_policy`, `fetch_policy`, `excerpt_settings`, `max_results`, and `location` |

If your integration uses `client.beta.search()`, upgrade to the latest `parallel-web` release and replace it with `client.search()`.

## Migration Example

### Before (Beta)

```bash cURL theme={"system"}
curl https://api.parallel.ai/v1beta/search \
  -H "Content-Type: application/json" \
  -H "x-api-key: $PARALLEL_API_KEY" \
  -d '{
    "objective": "Find latest information about Parallel Web Systems. Focus on new product releases, benchmarks, or company announcements.",
    "search_queries": ["Parallel Web Systems products", "Parallel Web Systems announcements"],
    "mode": "fast",
    "excerpts": {
      "max_chars_per_result": 10000,
      "max_chars_total": 50000
    }
  }'
```

### After (V1)

```bash cURL theme={"system"}
curl https://api.parallel.ai/v1/search \
  -H "Content-Type: application/json" \
  -H "x-api-key: $PARALLEL_API_KEY" \
  -d '{
    "objective": "Find latest information about Parallel Web Systems. Focus on new product releases, benchmarks, or company announcements.",
    "search_queries": ["Parallel Web Systems products", "Parallel Web Systems announcements"],
    "mode": "fast",
    "max_chars_total": 50000,
    "advanced_settings": {
      "excerpt_settings": {
        "max_chars_per_result": 10000
      }
    }
  }'
```

```python Python theme={"system"}
from parallel import Parallel
import os

client = Parallel(api_key=os.environ["PARALLEL_API_KEY"])

search = client.search(
    objective="Find latest information about Parallel Web Systems. Focus on new product releases, benchmarks, or company announcements.",
    search_queries=["Parallel Web Systems products", "Parallel Web Systems announcements"],
    mode="fast",
    max_chars_total=50000,
    advanced_settings={"excerpt_settings": {"max_chars_per_result": 10000}},
)

print(search.results)
```

```typescript TypeScript theme={"system"}
import Parallel from "parallel-web";

const client = new Parallel({ apiKey: process.env.PARALLEL_API_KEY });

const search = await client.search({
    objective: "Find latest information about Parallel Web Systems. Focus on new product releases, benchmarks, or company announcements.",
    search_queries: ["Parallel Web Systems products", "Parallel Web Systems announcements"],
    mode: "fast",
    max_chars_total: 50000,
    advanced_settings: { excerpt_settings: { max_chars_per_result: 10000 } },
});

console.log(search.results);
```

## Additional Resources

* [Search Quickstart](https://docs.parallel.ai/search/search-quickstart.md) - Get started with the Search API
* [Best Practices](https://docs.parallel.ai/search/best-practices.md) - Optimize your search requests
* [Parallel MCP](https://docs.parallel.ai/integrations/mcp/quickstart.md) - Use Search via Model Context Protocol
* [API Reference](https://docs.parallel.ai/api-reference/search/search.md) - Complete parameter specifications

Questions? Contact [support@parallel.ai](mailto:support@parallel.ai).
