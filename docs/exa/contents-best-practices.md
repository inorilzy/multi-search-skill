> ## Documentation Index
> Fetch the complete documentation index at: https://exa.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Contents Best Practices

> Best practices for using Exa's Contents API

The Contents API extracts clean, LLM-ready content from any URL—handling JavaScript-rendered pages, PDFs, and complex layouts automatically. Get full page text, targeted highlights, structured summaries, or crawl entire site sections in a single request.

**Recommended:** Try our [Coding Agent Quickstart](https://dashboard.exa.ai/onboarding) — get a working contents call in under a minute, then come back here for the full reference.

## Key Benefits

* **Clean markdown extraction**: Automatically filters out navigation, ads, and boilerplate to return only the main content, formatted as clean markdown.
* **Flexible content modes**: Choose between full text, query-relevant highlights, or LLM-generated summaries—or combine them in one request.
* **Subpage crawling**: Automatically discover and extract content from linked pages within a site, with targeted filtering to focus on specific sections.

## Request Fields

The `ids` parameter (list of URLs) is required. All other fields are optional. See the [API Reference](/reference/get-contents) for complete parameter specifications.

| Field            | Type      | Notes                                                                                                                                   | Example                                                         |
| ---------------- | --------- | --------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| ids              | string\[] | List of URLs to extract content from.                                                                                                   | \["[https://example.com/article](https://example.com/article)"] |
| text             | bool/obj  | Return full page text as markdown. Can specify `maxCharacters` and `includeHtmlTags`.                                                   | `true` or `{"maxCharacters": 5000}`                             |
| highlights       | bool/obj  | Return key excerpts most relevant to a query. Pass `true` for the highest-quality default, or supply a custom `query`.                  | `true` or `{"query": "main findings"}`                          |
| maxAgeHours      | int       | Maximum age of indexed content in hours. If older, fetches with livecrawl. `0` = always livecrawl, `-1` = never livecrawl (cache only). | 24                                                              |
| livecrawlTimeout | int       | Timeout in milliseconds for live crawling. Recommended: 10000-15000.                                                                    | 12000                                                           |
| subpages         | int       | Maximum number of subpages to crawl from each URL.                                                                                      | 5                                                               |
| subpageTarget    | string\[] | Keywords to prioritize when selecting subpages.                                                                                         | \["docs", "about", "pricing"]                                   |
| summary          | bool/obj  | Return LLM-generated summary. Can specify custom `query` and JSON `schema` for structured extraction.                                   | `{"query": "Key takeaways"}`                                    |

## Content Extraction Options

### Text

Returns the full page content as clean markdown.

```json theme={null}
{
  "ids": ["https://arxiv.org/abs/2301.07041"],
  "text": true
}
```

With character limit and HTML preservation:

```json theme={null}
{
  "ids": ["https://arxiv.org/abs/2301.07041"],
  "text": {
    "maxCharacters": 8000,
    "includeHtmlTags": true
  }
}
```

### Highlights

Returns key excerpts from the page that are most relevant to your query. These are extractive (pulled directly from the source), not generated.

```json theme={null}
{
  "ids": ["https://example.com/research-paper"],
  "highlights": {
    "query": "methodology and results"
  }
}
```

### Summary

Returns an LLM-generated abstract tailored to your specific query. Supports JSON schema for structured extraction.

```json theme={null}
{
  "ids": ["https://example.com/company-page"],
  "summary": {
    "query": "Extract company information",
    "schema": {
      "type": "object",
      "properties": {
        "name": { "type": "string" },
        "industry": { "type": "string" },
        "founded": { "type": "number" }
      },
      "required": ["name", "industry"]
    }
  }
}
```

## Token Efficiency

Choosing the right content mode can significantly reduce token usage while maintaining answer quality.

| Mode       | Best For                                                          |
| ---------- | ----------------------------------------------------------------- |
| text       | Deep analysis, when you need full context, comprehensive research |
| highlights | Factual questions, specific lookups, multi-step agent workflows   |

**Use highlights for agentic workflows**: When building multi-step agents that make repeated content extraction calls, highlights provide the most relevant excerpts without flooding context windows. Pass `highlights: true` for the highest-quality default, or supply a custom `query` when you want to steer selection.

```json theme={null}
{
  "ids": ["https://example.com/article"],
  "highlights": {
    "query": "key findings"
  }
}
```

**Use full text for deep analysis**: When the task requires comprehensive understanding or when you're unsure which parts of the page matter, request full text. Use `maxCharacters` to cap token usage.

```json theme={null}
{
  "ids": ["https://arxiv.org/abs/2301.07041"],
  "text": { "maxCharacters": 20000 }
}
```

**Combine modes strategically**: You can request multiple content types together—use highlights for quick answers and include full text only when deeper analysis is needed.

## Content Freshness

Control whether to return cached content (faster) or fetch fresh content from the source using `maxAgeHours`.

| Value    | Behavior                                                    | Best For                                        |
| -------- | ----------------------------------------------------------- | ----------------------------------------------- |
| `24`     | Use cache if less than 24 hours old, otherwise livecrawl    | Daily-fresh content                             |
| `1`      | Use cache if less than 1 hour old, otherwise livecrawl      | Near real-time data                             |
| `0`      | Always livecrawl (ignore cache entirely)                    | Real-time data where cached content is unusable |
| `-1`     | Never livecrawl (cache only)                                | Maximum speed, historical/static content        |
| *(omit)* | Default behavior (livecrawl as fallback if no cache exists) | **Recommended** — balanced speed and freshness  |

Most use cases work well with the default (omit `maxAgeHours`). Only set it when you have specific freshness requirements. If you do, pair with an explicit `livecrawlTimeout` (10000-15000ms).

```json theme={null}
{
  "ids": ["https://www.apple.com/newsroom/"],
  "maxAgeHours": 24,
  "livecrawlTimeout": 6000,
  "highlights": true
}
```

## Subpage Crawling

Automatically discover and extract content from linked pages within a website.

```json theme={null}
{
  "ids": ["https://docs.example.com"],
  "subpages": 10,
  "subpageTarget": ["api", "reference", "guide"],
  "highlights": true
}
```

**Parameters**:

* `subpages`: Maximum number of subpages to crawl per URL
* `subpageTarget`: Keywords to prioritize when selecting which subpages to crawl

**Best practices**:

1. Start with a smaller `subpages` value (5-10) and increase if needed
2. Use specific `subpageTarget` terms to focus on relevant sections
3. Combine with `maxAgeHours` for fresh results

### Example: Documentation Crawling

```json theme={null}
{
  "ids": ["https://platform.openai.com/docs"],
  "subpages": 15,
  "subpageTarget": ["api", "models", "embeddings"],
  "maxAgeHours": 24,
  "livecrawlTimeout": 15000,
  "text": { "maxCharacters": 5000 }
}
```

### Example: Company Research

```json theme={null}
{
  "ids": ["https://stripe.com"],
  "subpages": 8,
  "subpageTarget": ["about", "careers", "press", "blog"],
  "summary": { "query": "Company overview, culture, and recent news" }
}
```

## Error Handling

The Contents API returns detailed status information for each URL in the `statuses` field. The endpoint only returns an error for internal issues—individual URL failures are reported per-URL.

```json theme={null}
{
  "results": [...],
  "statuses": [
    {
      "id": "https://example.com",
      "status": "success"
    },
    {
      "id": "https://example.com/broken",
      "status": "error",
      "error": {
        "tag": "CRAWL_NOT_FOUND",
        "httpStatusCode": 404
      }
    }
  ]
}
```

**Error tags**:

* `CRAWL_NOT_FOUND`: Content not found (404)
* `CRAWL_TIMEOUT`: The crawl timed out while fetching content (504)
* `CRAWL_LIVECRAWL_TIMEOUT`: Content could not be retrieved within your requested `livecrawlTimeout` (504)
* `SOURCE_NOT_AVAILABLE`: Access forbidden (403)
* `CRAWL_UNKNOWN_ERROR`: Other errors (500+)

Always check the `statuses` array to handle failures gracefully:

```python theme={null}
result = exa.get_contents(["https://example.com", "https://example.com/maybe-broken"])
for status in result.statuses:
    if status.status == "error":
        print(f"Failed: {status.id} - {status.error.tag}")
```
