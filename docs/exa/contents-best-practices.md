> Source: https://exa.ai/docs/contents/quickstart.md
> Retrieved: 2026-10-31
> Covers: POST https://api.exa.ai/contents (guide)
> Note: https://exa.ai/docs/reference/contents-best-practices.md now redirects to the Contents quickstart; no separate Contents best-practices page exists in llms.txt

# Contents API

> Extract text, highlights, and summaries from any URL.

Exa Contents is a content extraction API that returns clean page content from URLs, handling JavaScript-rendered pages, PDFs, and complex layouts automatically.

All contents features are also available in [Exa Search](https://exa.ai/docs/search/quickstart.md) for returned URLs, at no extra charge up to 10 results per search (\$1/1000 pages afterwards). We recommend using Search in this way instead of Contents for web search tool use cases.

> [!TIP]
>
> For search results feeding AI context, request `contents: { highlights: true }` on `/search` —
> Exa sizes each result's excerpts to its relevance. See [Highlights](https://exa.ai/docs/search/highlights.md).

## Make your first request

Pass one or more URLs or document IDs and request highlights for the parts relevant to your task. In HTTP requests, provide them in `ids`:

```python Python theme={null}
from exa_py import Exa

exa = Exa()

result = exa.get_contents(
    ["https://exa.ai/blog/dynamic-highlights"],
    highlights={"query": "token efficiency and quality results"},
)

print(result.results[0].highlights)
```

```javascript JavaScript theme={null}
import Exa from "exa-js";

const exa = new Exa();

const result = await exa.getContents(
  ["https://exa.ai/blog/dynamic-highlights"],
  {
    highlights: {
      query: "token efficiency and quality results"
    }
  }
);

console.log(result.results[0].highlights);
```

```bash cURL theme={null}
curl -s -X POST "https://api.exa.ai/contents" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $EXA_API_KEY" \
  -d '{
    "ids": ["https://exa.ai/blog/dynamic-highlights"],
    "highlights": {
      "query": "token efficiency and quality results"
    }
  }'
```

> [accordion] Example response
>
> ```json theme={null}
> {
>   "requestId": "e492118ccdedcba5088bfc4357a8a125",
>   "results": [
>     {
>       "id": "https://exa.ai/blog/dynamic-highlights",
>       "title": "Dynamic Highlights",
>       "url": "https://exa.ai/blog/dynamic-highlights",
>       "highlights": [
>         "With a 12k character budget, relative to existing highlights, Dynamic Highlights achieves a 40% average token efficiency gain with a notable quality increase..."
>       ]
>     }
>   ],
>   "statuses": [
>     {
>       "id": "https://exa.ai/blog/dynamic-highlights",
>       "status": "success",
>       "source": "cached"
>     }
>   ],
>   "costDollars": {
>     "total": 0.001
>   }
> }
> ```

Each item in `results` includes page metadata and the content view you requested. Check `statuses` for the success or failure of every URL.

## Output shapes

> [tab] Highlights
>
> Highlights return relevant passages copied from the page. Start here for agents, RAG, and
> factual lookups because highlights keep context smaller than full text.
>
> Set `highlights: true` to enable highlights. An additional `query` parameter is recommended when using Contents to focus content extraction from the page:
>
> ```python Python theme={null}
> result = exa.get_contents(
>     ["https://example.com/research-paper"],
>     highlights={"query": "methodology and results"},
> )
> ```
>
> ```javascript JavaScript theme={null}
> const result = await exa.getContents(
>   ["https://example.com/research-paper"],
>   {
>     highlights: {
>       query: "methodology and results"
>     }
>   }
> );
> ```
>
> ```bash cURL theme={null}
> curl -s -X POST "https://api.exa.ai/contents" \
>   -H "Content-Type: application/json" \
>   -H "Authorization: Bearer $EXA_API_KEY" \
>   -d '{
>     "ids": ["https://example.com/research-paper"],
>     "highlights": {
>       "query": "methodology and results"
>     }
>   }'
> ```
>
> See [Highlights](https://exa.ai/docs/search/highlights.md) for Dynamic Highlights and guidance on allocating context
> across several pages.

> [tab] Full text
>
> Full text returns the clean page body as markdown. Use it when the task depends on broad context,
> document structure, or details that highlights may leave out.
>
> Full pages can be large, so use `maxCharacters` when you need a limit:
>
> ```python Python theme={null}
> result = exa.get_contents(
>     ["https://example.com/technical-report"],
>     text={"max_characters": 10000},
> )
> ```
>
> ```javascript JavaScript theme={null}
> const result = await exa.getContents(
>   ["https://example.com/technical-report"],
>   {
>     text: {
>       maxCharacters: 10000
>     }
>   }
> );
> ```
>
> ```bash cURL theme={null}
> curl -s -X POST "https://api.exa.ai/contents" \
>   -H "Content-Type: application/json" \
>   -H "Authorization: Bearer $EXA_API_KEY" \
>   -d '{
>     "ids": ["https://example.com/technical-report"],
>     "text": {
>       "maxCharacters": 10000
>     }
>   }'
> ```

> [tab] Summary
>
> Summary makes a language model call for each page. Use it when you need a generated overview or
> fields extracted into a JSON schema.
>
> ```python Python theme={null}
> result = exa.get_contents(
>     ["https://example.com/company"],
>     summary={"query": "Summarize the product, customers, and pricing"},
> )
> ```
>
> ```javascript JavaScript theme={null}
> const result = await exa.getContents(
>   ["https://example.com/company"],
>   {
>     summary: {
>       query: "Summarize the product, customers, and pricing"
>     }
>   }
> );
> ```
>
> ```bash cURL theme={null}
> curl -s -X POST "https://api.exa.ai/contents" \
>   -H "Content-Type: application/json" \
>   -H "Authorization: Bearer $EXA_API_KEY" \
>   -d '{
>     "ids": ["https://example.com/company"],
>     "summary": {
>       "query": "Summarize the product, customers, and pricing"
>     }
>   }'
> ```
>
> To extract fields instead of prose, pass a JSON schema in `summary.schema`. The summary comes
> back as a JSON string matching the schema; parse it to read the fields:
>
> ```json theme={null}
> {
>   "ids": ["https://example.com/company"],
>   "summary": {
>     "schema": {
>       "$schema": "https://json-schema.org/draft/2020-12/schema",
>       "title": "Company Information",
>       "type": "object",
>       "properties": {
>         "name": { "type": "string", "description": "The company name" },
>         "industry": { "type": "string", "description": "Primary industry" },
>         "foundedYear": { "type": "number", "description": "Year the company was founded" }
>       },
>       "required": ["name"]
>     }
>   }
> }
> ```

Pick one content view per request. Requesting highlights, text, and summary together returns and bills each view separately.

## Content freshness

`maxAgeHours` controls how fresh the extracted page content must be.

| Value | Behavior |
| - | - |
| Omit | Use cached content when available and fetch the page when needed |
| Positive integer | Use cached content if it is newer than this many hours, otherwise fetch the page |
| `0` | Always fetch fresh content |
| `-1` | Only use cached content |

Most requests should omit this field. Set it when stale page content would be unusable, such as for prices, availability, or frequently updated pages. Pair a low `maxAgeHours` with `livecrawlTimeout` (milliseconds) to cap how long a fresh fetch may take.

> [accordion] Migrate from the deprecated livecrawl parameter
>
> The `livecrawl` string parameter (`"always"`, `"preferred"`, `"fallback"`, `"never"`) is
> deprecated in favor of `maxAgeHours`:
>
> | Old `livecrawl` value | Equivalent |
> | - | - |
> | `"always"` | `maxAgeHours: 0` |
> | `"never"` | `maxAgeHours: -1` |
> | `"fallback"` | Omit `maxAgeHours` |
> | `"preferred"` | No direct equivalent; use a low value such as `maxAgeHours: 1` |

## Crawl subpages

Set `subpages` to follow links from each starting URL. Add `subpageTarget` when you want Exa to prioritize particular site sections:

```python Python theme={null}
result = exa.get_contents(
    ["https://docs.example.com"],
    subpages=10,
    subpage_target=["api", "reference", "guides"],
    highlights=True,
)
```

```javascript JavaScript theme={null}
const result = await exa.getContents(
  ["https://docs.example.com"],
  {
    subpages: 10,
    subpageTarget: ["api", "reference", "guides"],
    highlights: true
  }
);
```

```bash cURL theme={null}
curl -s -X POST "https://api.exa.ai/contents" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $EXA_API_KEY" \
  -d '{
    "ids": ["https://docs.example.com"],
    "subpages": 10,
    "subpageTarget": ["api", "reference", "guides"],
    "highlights": true
  }'
```

## Images and favicons

Set `extras.imageLinks` to the number of image URLs you want from each page. Results also include
the site's `favicon` and a representative `image` URL when available. On `/search`, this option
sits at `contents.extras.imageLinks`.

## Common mistakes

`/contents` shares most of its options with `/search` but places them differently, and requests copied from older examples often carry parameters this endpoint never had. The [API reference](https://exa.ai/docs/reference/get-contents.md) is the source of truth for the current schema.

| Instead of | Use |
| - | - |
| `contents: { text: ... }` | Top-level `text`, `highlights`, and `summary`. Unlike `/search`, `/contents` has no `contents` wrapper. |
| `useAutoprompt` | Nothing. There is no query to rewrite on `/contents`; remove the field. |
| `stream: true` | A normal request. `/contents` does not support streaming. |
| `numSentences`, `highlightsPerUrl` | `highlights: true`. Exa sizes highlights to each page; set `highlights.maxCharacters` only for a fixed excerpt limit. |
| `tokensNum` | `text.maxCharacters`. |
| `livecrawl: "always"` | `maxAgeHours: 0`. Do not send `livecrawl` and `maxAgeHours` together. |
| `crawledBeforeDate` | `snapshotAsOf`. |
| `context: true` | `highlights` or `text`; build the context string from `results[]`. |

A few behaviors that are easy to miss:

* `urls` and `ids` are interchangeable. Pass either the page URLs or the `id` values from a search response.
* A fresh fetch (`maxAgeHours: 0` or a low value) waits up to `livecrawlTimeout` milliseconds (default 10000). Raise it to 12000–15000 for slow sites, or lower it when latency matters more than freshness.
* The Python SDK uses snake\_case for every key: `exa.get_contents(urls, highlights=True, max_age_hours=24)`.
* To attribute a request to one of your end users, send `userIdentifier` at the top level, as on `/search`. See [Attribute requests to your end users](https://exa.ai/docs/search/best-practices.md#user-identifier).

## Next steps

> [card] [API reference](https://exa.ai/docs/reference/get-contents.md)
>
> See every request parameter and response field.

> [card] [Highlights](https://exa.ai/docs/search/highlights.md)
>
> Compare regular and Dynamic Highlights for agent and RAG context.

> [card] [Search API](https://exa.ai/docs/search/quickstart.md)
>
> Find relevant pages before extracting their content.

> [card] [SDKs](https://exa.ai/docs/sdks/quickstart.md)
>
> Use Exa from Python or JavaScript.
