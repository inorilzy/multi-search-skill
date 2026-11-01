> Source: https://docs.parallel.ai/search/best-practices.md
> Retrieved: 2026-10-31
> Covers: POST /v1/search request field limits (objective, search_queries)


# Search API Best Practices

> Configure objectives and search queries for the Parallel Search API and tool-calling agents

For AI agents: a documentation index is available at [https://docs.parallel.ai/llms.txt](https://docs.parallel.ai/llms.txt). The full text of all docs is at [https://docs.parallel.ai/llms-full.txt](https://docs.parallel.ai/llms-full.txt). You may also fetch any page as Markdown by appending `.md` to its URL or sending `Accept: text/markdown`.

For Search and Extract, use `/v1/search` and `/v1/extract` for all new integrations and agent tool calls. Use `/v1beta/search` and `/v1beta/extract` only when maintaining an existing integration that already uses them. The request bodies changed too: on `/v1/extract`, `full_content`, `fetch_policy` and `excerpt_settings` go inside `advanced_settings`, and sending the v1beta top-level `excerpts`, `full_content` and `fetch_policy` to `/v1/extract` returns a 422. Do not substitute `/v1` for the documented FindAll or Ingest endpoint paths.

> [!TIP]
>
> Running an evaluation? Start with [How to Eval](https://docs.parallel.ai/search/evaluating-search.md) for end-to-end eval design before you benchmark.

Send the Search API a natural-language objective, keyword queries, or both. Search ranks
and compresses the results, then returns excerpts that you can pass to a model. One
request can cover several related topics and reduce the number of calls in an agent
workflow.

The same guidance applies to direct API requests and function calls where a model fills
**`objective`** and **`search_queries`**. You can copy the [Search Tool
Definition](#search-tool-definition) into your agent.

## Key Benefits

* **Context engineering for token efficiency**: The API ranks and compresses web results based on reasoning utility rather than human engagement, delivering the most relevant tokens for each agent's specific objective. Because those excerpts are dense and relevant, your model spends fewer input tokens to reason over them. On a typical call, better retrieval routinely saves more in downstream inference than the search call itself costs.
* **Single-hop resolution of complex queries**: Where traditional search forces agents to make multiple sequential calls, accumulating latency and costs, Parallel resolves complex multi-topic queries in a single request.
* **Multi-hop efficiency**: For deep research workflows requiring multiple reasoning steps, agents using Parallel complete tasks in fewer tool calls while achieving higher accuracy and lower end-to-end latency.

## Request Fields

`search_queries` requires at least one non-empty query. All other fields are optional.
See the [API Reference](https://docs.parallel.ai/api-reference/search/search.md) for the full parameter definitions.

| Field | Type | Notes | Example |
| - | - | - | - |
| search\_queries | string\[] | One to five keyword queries, each 3-6 words and no more than 200 characters. Use 2-3 queries when the task benefits from multiple angles. The API drops queries after the fifth and returns an input validation warning. | `["Parallel Web Systems products", "Parallel Web Systems announcements"]` |
| objective | string | A natural-language description of the research goal. Include relevant context and any source or freshness requirements. Maximum 5000 characters. | "Find latest information about Parallel Web Systems. Focus on new product releases, benchmarks, or company announcements." |
| mode | string | Choose a mode based on latency, cost, and result quality. Defaults to `advanced`. See [Modes](https://docs.parallel.ai/search/modes.md). | `"turbo"` |
| max\_chars\_total | int | Maximum number of characters across all result excerpts. The default depends on `search_queries`, `objective`, and `client_model`. | 50000 |
| client\_model | string | The model that creates the request and consumes the results. Search uses this value to tune its output for the model. | `"claude-opus-5"`, `"gpt-6-astra"`, `"gemini-3.8-flash"` |
| session\_id | string | A string that groups calls for one task. Reuse it across related Search and Extract calls. Start each task with a new value. See [Session Identifiers](#session-identifiers). | `"session_<uuid>"` or `"company_search_<uuid>"` |
| advanced\_settings | object | Controls source policy, fetch policy, excerpts, location, and result count. Restrictive settings can reduce coverage and quality, so use them when the task requires them. See [Advanced Settings](https://docs.parallel.ai/search/advanced-search-settings.md). | See [Advanced Settings](https://docs.parallel.ai/search/advanced-search-settings.md) |

Send `objective` and `search_queries` together.

### Examples

```json theme={"system"}
{
  "objective": "What EV tax credits and rebates apply to small businesses in California, and how do they differ for leasing vs buying?",
  "search_queries": ["EV tax credit business", "California EV rebate lease", "federal EV incentive purchase vs lease"]
}
```

```json theme={"system"}
{
  "objective": "What has the Federal Reserve and SEC announced about digital asset regulations and crypto-banking partnerships in the past 3 months?",
  "search_queries": ["Federal Reserve crypto guidance 2026", "SEC digital asset policy", "bank crypto partnership regulations"]
}
```

```json theme={"system"}
{
  "objective": "How do transformer attention mechanisms work in PyTorch and Hugging Face, based on their official documentation?",
  "search_queries": ["transformer attention mechanism", "PyTorch attention documentation", "Hugging Face transformer guide"]
}
```

```json theme={"system"}
{
  "objective": "What clinical trial results on amyloid-beta therapies for Alzheimer's have been published in the past 2 years?",
  "search_queries": ["amyloid beta clinical trials", "Alzheimer's treatment research 2024-2026", "monoclonal antibody AD trials"]
}
```

## Session Identifiers

Use one `session_id` for Search and Extract calls that belong to the same task. Start each
new task with another ID.

Every Search and Extract response includes a `session_id`. The API returns the value you
provide or generates one when you omit it. The value can contain up to 1000 characters.
Use a descriptive string or a UUID, such as
`"company_search_cd812136-9f81-484e-ab92-2ba0cb8b9ea8"`.

## Search Tool Definition

Add one of these definitions to your agent's tool list. Each tab uses the same schema with
a wrapper for OpenAI, Anthropic, or Gemini.

> [!NOTE]
>
> [MCP](https://docs.parallel.ai/integrations/mcp/quickstart.md) supplies the tool definition, so MCP clients can skip
> this section.

> [tab] OpenAI
>
> ```json theme={"system"}
> {
>   "type": "function",
>   "function": {
>     "name": "search_web",
>     "description": "Search the web and return result titles, URLs, and excerpts.",
>     "parameters": {
>       "type": "object",
>       "properties": {
>         "objective": {
>           "type": "string",
>           "description": "Describe the search goal in a concise, standalone sentence. Name the key entity or topic."
>         },
>         "search_queries": {
>           "type": "array",
>           "description": "Provide 1-3 keyword queries of 3-6 words each. Include the key entity or topic in every query. For multiple queries, vary names, synonyms, or angles. Do not use sentences, instructions, or site: operators.",
>           "items": { "type": "string" },
>           "minItems": 1,
>           "maxItems": 3
>         }
>       },
>       "required": ["objective", "search_queries"]
>     }
>   }
> }
> ```

> [tab] Anthropic
>
> ```json theme={"system"}
> {
>   "name": "search_web",
>   "description": "Search the web and return result titles, URLs, and excerpts.",
>   "input_schema": {
>     "type": "object",
>     "properties": {
>       "objective": {
>         "type": "string",
>         "description": "Describe the search goal in a concise, standalone sentence. Name the key entity or topic."
>       },
>       "search_queries": {
>         "type": "array",
>         "description": "Provide 1-3 keyword queries of 3-6 words each. Include the key entity or topic in every query. For multiple queries, vary names, synonyms, or angles. Do not use sentences, instructions, or site: operators.",
>         "items": { "type": "string" },
>         "minItems": 1,
>         "maxItems": 3
>       }
>     },
>     "required": ["objective", "search_queries"]
>   }
> }
> ```

> [tab] Gemini
>
> ```python theme={"system"}
> import google.generativeai as genai
>
> SEARCH_WEB_SCHEMA = {
>     "name": "search_web",
>     "description": "Search the web and return result titles, URLs, and excerpts.",
>     "parameters": {
>         "type": "object",
>         "properties": {
>             "objective": {
>                 "type": "string",
>                 "description": "Describe the search goal in a concise, standalone sentence. Name the key entity or topic.",
>             },
>             "search_queries": {
>                 "type": "array",
>                 "description": "Provide 1-3 keyword queries of 3-6 words each. Include the key entity or topic in every query. For multiple queries, vary names, synonyms, or angles. Do not use sentences, instructions, or site: operators.",
>                 "items": {"type": "string"},
>                 "minItems": 1,
>                 "maxItems": 3,
>             },
>         },
>         "required": ["objective", "search_queries"],
>     },
> }
>
> genai.types.FunctionDeclaration(
>     name=SEARCH_WEB_SCHEMA["name"],
>     description=SEARCH_WEB_SCHEMA["description"],
>     parameters=SEARCH_WEB_SCHEMA["parameters"],
> )
>
> ```
