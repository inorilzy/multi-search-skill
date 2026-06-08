> ## Documentation Index
> Fetch the complete documentation index at: https://exa.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Search Best Practices

> Best practices for using Exa's Search API

Exa's Search API returns a list of webpages and their contents based on a natural language search query. Results are optimized for LLM consumption, enabling higher-quality completions with clean, token efficient data.

**Recommended:** Try our [Coding Agent Quickstart](https://dashboard.exa.ai/onboarding) — get a working search call in under a minute, then come back here for the full reference.

## Key Benefits

* **Token efficient**: Use `highlights` to get key excerpts relevant to your query, reducing token usage by 10x compared to full text, without adding latency.
* **Specialized index coverage**: State of the art search performance on [people](https://exa.ai/blog/people-search-benchmark), [company](https://exa.ai/blog/company-search-benchmarks), and code using Exa's in-house search indexes.
* **Incredible speed**: From `auto` (default) to `fast` for sub-second latency to `instant` for sub-200ms latency, Exa provides the fastest search available without compromising on quality, enabling real-time workflows like autocomplete and live suggestions.

## Request Fields

The `query` parameter is required for all search requests. The remaining fields are optional. See the [API Reference](/reference/search) for complete parameter details.

| Field        | Type     | Notes                                                                                                                                                     | Example                                               |
| ------------ | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| query        | string   | The search query. Supports long, semantically rich descriptions for finding niche content.                                                                | "blog post about embeddings and vector search"        |
| type         | string   | Search method: `auto` (default balance of speed and quality), `fast` (low latency), `instant` (lowest latency), `deep-lite`, `deep`, or `deep-reasoning`. | "auto"                                                |
| systemPrompt | string   | Instructions that guide synthesized output and, for deep-search variants, search planning.                                                                | "Prefer official sources and avoid duplicate results" |
| outputSchema | object   | JSON schema that controls `output.content`. When set, `/search` returns `output` for any search type.                                                     | `{ "type": "text", "description": "one sentence" }`   |
| stream       | boolean  | If true, `/search` streams OpenAI-compatible chat completion chunks over SSE instead of returning one JSON payload.                                       | `true`                                                |
| numResults   | int      | Number of results to return (1-100). Defaults to 10.                                                                                                      | 10                                                    |
| highlights   | bool/obj | Return token-efficient excerpts most relevant to your query. You can also request full text if needed—see the [API Reference](/reference/search).         | `true`                                                |
| maxAgeHours  | int      | Maximum age of indexed content in hours. If older, fetches with livecrawl. `0` = always livecrawl, `-1` = never livecrawl (cache only).                   | 24                                                    |
| category     | string   | Target specific content types: `company`, `people`, `news`                                                                                                | "company"                                             |

## Search Types

The `type` parameter selects the search method:

* **`auto`** (default): Exa's default search. Start here unless you have a specific latency target or need a deeper synthesized mode.

* **`fast`**: Low latency search using optimized versions of the search models. A good middle ground when you need speed without sacrificing too much quality.

* **`instant`**: Lowest latency search optimized for real-time applications like autocomplete or live suggestions.

* **`deep-lite`**: Lightweight synthesized search output with lower latency than the deeper research modes.

* **`deep`**: Deep web research with structured outputs. Best for complicated queries that require multi steps of search, reasoning, and structured json outputs.

* **`deep-reasoning`**: More deliberate deep-search mode when you want more reasoning than `deep`.

<Note>
  Some older docs and payloads still use legacy search-type names. For new integrations, prefer the search types above.
</Note>

## Token Efficiency

Choosing the right content mode can significantly reduce token usage while maintaining answer quality.

| Mode       | Best For                                                          |
| ---------- | ----------------------------------------------------------------- |
| text       | Deep analysis, when you need full context, comprehensive research |
| highlights | Factual questions, specific lookups, multi-step agent workflows   |

**Use highlights for agentic workflows**: When building multi-step agents that make repeated search calls, highlights provide the most relevant excerpts without flooding context windows.

```json theme={null}
{
  "query": "What is the current Fed interest rate?",
  "contents": {
    "highlights": true
  }
}
```

**Use full text for deep research**: When the task requires comprehensive understanding or when you're unsure which parts of the page matter, request full text. Use `maxCharacters` to cap token usage.

```json theme={null}
{
  "query": "detailed analysis of transformer architecture innovations",
  "contents": {
    "text": { "maxCharacters": 15000 }
  },
  "numResults": 5
}
```

**Combine modes strategically**: You can request both highlights and text together—use highlights for quick answers and fall back to full text only when needed.

## Content Freshness

Control whether results come from Exa's index or are freshly crawled using `maxAgeHours`:

* **`maxAgeHours: 24`**: Use cache if less than 24 hours old, otherwise livecrawl. Good for daily-fresh content.
* **`maxAgeHours: 0`**: Always livecrawl (ignore cache). Use when cached data is unacceptable.
* **`maxAgeHours: -1`**: Never livecrawl (cache only). Maximum speed, historical/static content.
* **Omit** *(recommended)*: Default behavior — livecrawl as fallback if no cache exists.

```json theme={null}
{
  "query": "latest announcements from OpenAI",
  "includeDomains": ["openai.com"],
  "maxAgeHours": 72,
  "contents": {
    "highlights": true
  }
}
```

## Output Schema

For any search type, you can pass `outputSchema` (or `output_schema` in Python SDK) to control `output.content` format.

* `type: "text"`: return plain text output (optionally guided with a `description`)
* `type: "object"`: return structured JSON output

<Note>
  Do not include citation or confidence fields in `outputSchema`/`output_schema`. `/search` already
  returns grounding and citations automatically in `output.grounding`.
</Note>

Including citations/confidence inside your schema is usually worse:

* **Redundant:** duplicates data that is already returned, increasing tokens and latency.
* **Less reliable:** model-generated citation fields inside `output.content` are generally less reliable than built-in grounding.

Simpler schemas perform better. Defining clear primitive/object/array fields works best, while string properties that try to embed JSON blobs usually perform poorly.

```json theme={null}
{
  "query": "what's the fastest web search api",
  "type": "deep",
  "outputSchema": {
    "type": "text",
    "description": "Short one to two sentence answer"
  }
}
```

```json theme={null}
{
  "query": "top aerospace companies",
  "type": "deep",
  "outputSchema": {
    "type": "object",
    "required": ["companies"],
    "properties": {
      "companies": {
        "type": "array",
        "description": "A list of aerospace companies",
        "items": {
          "type": "object",
          "required": ["company_name", "ceo_name", "stock_price"],
          "properties": {
            "company_name": {
              "type": "string",
              "description": "The name of the aerospace company"
            },
            "ceo_name": {
              "type": "string",
              "description": "The name of the company's CEO"
            },
            "stock_price": {
              "type": "number",
              "description": "Current stock price of the company"
            }
          }
        }
      }
    }
  }
}
```

Object schema limits:

* Maximum nesting depth: `2`
* Maximum total properties: `10`

## System Prompt

For any search type, you can also pass `systemPrompt` (or `system_prompt` in Python SDK) to guide how the endpoint synthesizes the final returned result. On deep-search variants, it also guides search planning.

Use this for instructions like:

* prefer official or primary sources
* emphasize novelty or avoid duplicate findings
* keep the answer concise or highly structured

Use `outputSchema`/`output_schema` for shape, and `systemPrompt`/`system_prompt` for behavior.

```json theme={null}
{
  "query": "compare the latest frontier AI model releases",
  "type": "deep-reasoning",
  "systemPrompt": "Prefer official sources and avoid duplicate results",
  "outputSchema": {
    "type": "object",
    "required": ["models"],
    "properties": {
      "models": {
        "type": "array",
        "items": {
          "type": "object",
          "required": ["name", "notable_claims"],
          "properties": {
            "name": { "type": "string" },
            "notable_claims": { "type": "array", "items": { "type": "string" } }
          }
        }
      }
    }
  }
}
```

## Streaming

Set `stream: true` to receive `text/event-stream` responses from `/search`. Each SSE frame contains an OpenAI-compatible chat completion chunk, so you should read partial text from `choices[0].delta.content` instead of expecting a single JSON body.

## Category Filters

Use `category` to target specific content types where Exa has specialized coverage:

| Category           | Best For                                       | Restrictions                                                                                                                                                      |
| ------------------ | ---------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `company`          | Company pages, LinkedIn company profiles       | Does not support `startPublishedDate`, `endPublishedDate`, `startCrawlDate`, `endCrawlDate`, or `excludeDomains`.                                                 |
| `people`           | Multi-source data on people, LinkedIn profiles | Does not support `startPublishedDate`, `endPublishedDate`, `startCrawlDate`, `endCrawlDate`, or `excludeDomains`; `includeDomains` only accepts LinkedIn domains. |
| `research paper`   | Academic papers, arXiv, peer-reviewed research | —                                                                                                                                                                 |
| `news`             | Current events, journalism                     | —                                                                                                                                                                 |
| `personal site`    | Blogs, personal pages (Exa's unique strength)  | —                                                                                                                                                                 |
| `financial report` | SEC filings, earnings reports                  | —                                                                                                                                                                 |

```json theme={null}
{
  "query": "agtech companies in the US that have raised series A",
  "type": "auto",
  "category": "company",
  "numResults": 10,
  "contents": {
    "highlights": true
  }
}
```
