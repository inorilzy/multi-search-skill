> ## Documentation Index
> Fetch the complete documentation index at: https://exa.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Contents API

> Extract clean, LLM-ready web content.

<div className="callout-box not-prose">
  <p className="callout-title">Just want working code?</p>

  <p className="callout-body">
    Stop reading. Visit [contents coding agent reference](/reference/contents-api-guide-for-coding-agents)
    and copy paste to your agent.
  </p>
</div>

## What it is

`/contents` returns clean, structured content from any URL, handling JavaScript-rendered pages, PDFs, and complex layouts automatically. You pass in URLs and get back full page text, targeted highlights, LLM-generated summaries, or all three. It can also be used to crawl linked subpages to pull content from entire site sections in a single request.

All contents features are also available in `/search` for returned URLs, at no extra charge up to 10 results per search (\$1/1000 pages afterwards). We recommend using `/search` in this way instead of `/contents` for web search tool use cases.

<Info>
  Use `/contents` when you already know the URLs. If you are starting from a query and want Exa to
  find the pages first, start with [Search](/reference/search-api-guide).
</Info>

## Key Capabilities

### Content Modes

Choose how you receive content, or combine them in a single request:

| Mode           | What You Get                        | Best For                                                |
| -------------- | ----------------------------------- | ------------------------------------------------------- |
| **Text**       | Full page content as clean markdown | Deep analysis, full context research                    |
| **Highlights** | Key excerpts relevant to your query | Agent workflows, factual lookups (10x fewer tokens)     |
| **Summary**    | LLM-generated abstract              | Quick overviews, structured extraction with JSON schema |

### Subpage crawling

Automatically discover and extract content from linked pages within a site. Pass `subpages: 10` and optionally `subpageTarget: ["docs", "about"]` to focus on relevant sections.

### Content freshness

Control whether results come from cache or are freshly crawled with `maxAgeHours`:

| Setting        | Behavior                                          |
| -------------- | ------------------------------------------------- |
| Omit (default) | Livecrawl only when no cache exists               |
| `24`           | Use cache if \< 24 hours old, otherwise livecrawl |
| `0`            | Always livecrawl (slowest, freshest)              |
| `-1`           | Cache only (fastest, may be stale)                |

## Common use cases

<Accordion title="Token-efficient info from an article">
  Get the most relevant excerpts without needing the full page.

  ```python theme={null}
  result = exa.get_contents(
    ["https://example.com/research-paper"],
    highlights={"query": "methodology and results"}
  )
  ```
</Accordion>

<Accordion title="Structured outputs using summaries">
  Extract specific fields from any page using a JSON schema.

  ```python theme={null}
  result = exa.get_contents(
    ["https://example.com/company-page"],
    summary={
      "query": "Extract company information",
      "schema": {
        "type": "object",
        "properties": {
          "name": {"type": "string"},
          "industry": {"type": "string"},
          "founded": {"type": "number"}
        },
        "required": ["name", "industry"]
      }
    }
  )
  ```
</Accordion>

<Accordion title="Crawl many pages from a website">
  Pull content from a docs site, targeting specific sections.

  ```python theme={null}
  result = exa.get_contents(
    ["https://docs.example.com"],
    subpages=15,
    subpage_target=["api", "models", "embeddings"],
    max_age_hours=24,
    text={"max_characters": 5000}
  )
  ```
</Accordion>

## Human Quickstart

Get your API key from the [Exa Dashboard](https://dashboard.exa.ai/api-keys).

<Tabs>
  <Tab title="Python">
    ```bash theme={null}
    pip install exa-py
    ```

    ```python theme={null}
    from exa_py import Exa

    exa = Exa(api_key="your-api-key")

    result = exa.get_contents(
      ["https://example.com/article"],
      highlights=True
    )
    ```
  </Tab>

  <Tab title="JavaScript">
    ```bash theme={null}
    npm install exa-js
    ```

    ```javascript theme={null}
    import Exa from "exa-js";

    const exa = new Exa("your-api-key");

    const result = await exa.getContents(
      ["https://example.com/article"],
      {
        highlights: true
      }
    );
    ```
  </Tab>

  <Tab title="cURL">
    ```bash theme={null}
    curl -X POST "https://api.exa.ai/contents" \
      -H "Content-Type: application/json" \
      -H "x-api-key: YOUR_API_KEY" \
      -d '{
        "urls": ["https://example.com/article"],
        "highlights": true
      }'
    ```
  </Tab>
</Tabs>

## Next

* [**Search API**](/reference/search-api-guide) - Find content on the web with natural language
* [**Contents API Reference**](/reference/get-contents) - Full API reference with all parameters
* [**MCP Setup**](/reference/exa-mcp) - Connect your AI assistant to Exa
* [**SDKs**](/sdks/python-sdk) - Python and JavaScript SDK docs
