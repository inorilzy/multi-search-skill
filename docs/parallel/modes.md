> Source: https://docs.parallel.ai/search/modes.md
> Retrieved: 2026-10-31
> Covers: POST /v1/search mode values


# Search Modes

> Configure the Search API mode for your use case

For AI agents: a documentation index is available at [https://docs.parallel.ai/llms.txt](https://docs.parallel.ai/llms.txt). The full text of all docs is at [https://docs.parallel.ai/llms-full.txt](https://docs.parallel.ai/llms-full.txt). You may also fetch any page as Markdown by appending `.md` to its URL or sending `Accept: text/markdown`.

For Search and Extract, use `/v1/search` and `/v1/extract` for all new integrations and agent tool calls. Use `/v1beta/search` and `/v1beta/extract` only when maintaining an existing integration that already uses them. The request bodies changed too: on `/v1/extract`, `full_content`, `fetch_policy` and `excerpt_settings` go inside `advanced_settings`, and sending the v1beta top-level `excerpts`, `full_content` and `fetch_policy` to `/v1/extract` returns a 422. Do not substitute `/v1` for the documented FindAll or Ingest endpoint paths.

Search offers four modes, in order of latency. Use `turbo` for the lowest latency and cost in real-time, high-volume workloads; `fast` for high-quality, sub-second search across most agent workloads; `basic` for quick retrieval with extended snippets per result; and `advanced` for the highest-quality, multi-hop results. If `mode` isn't set, requests default to `advanced`.

> [!NOTE]
>
> Not sure which mode to pick? Start with `fast`. It delivers high-quality results in around 700ms and is the right choice for most agents. Reach for `turbo` when latency and cost matter most for simple, high-volume lookups, `basic` when you want extended snippets and can spend around a second per call, and `advanced` when result quality matters more than latency.

## Available modes

| Mode | What it does | Latency | Cost | Best for |
| - | - | - | - | - |
| `turbo` | Lowest latency and cost; built to ground every call. | \~200ms | \$1 per 1,000 requests | Latency-sensitive, high-volume workloads (e.g. voice, chat, web search tools, RAG pre-filtering, high-volume lookups) |
| `fast` | High-quality search with sub-second latency. Recommended default for most agents. | \~700ms | \$1 per 1,000 requests | Most agents: interactive assistants, tool-calling loops, and any workload that needs quality results without multi-second latency |
| `basic` | Returns extended snippets per result for richer per-call context. Works best with 2-3 high-quality `search_queries`. | \~1s | \$5 per 1,000 requests | Agents that benefit from longer excerpts per source in a single call |
| `advanced` (default) | Uses a more advanced retrieval and compression pipeline for higher-quality results. | \~3s | \$5 per 1,000 requests | Multi-hop background agents that can tolerate extra latency for better depth and cost-efficiency (e.g., code review agents, deep research) |

> [!NOTE]
>
> Turbo currently supports English and Japanese-language queries. For broader multilingual coverage, use `basic` or `advanced`.

> [!NOTE]
>
> The EU endpoint at `https://eu.parallel.ai` supports only `basic` mode. See [EU Data Residency](https://docs.parallel.ai/resources/eu-data-residency.md).

## Example

Switching modes is a single parameter change. The rest of your request stays the same:

```json theme={"system"}
{
  "mode": "fast",
  "objective": "What is the current price of NVIDIA stock?",
  "search_queries": ["NVIDIA stock price", "NVDA quote today"]
}
```
