> Source: https://docs.parallel.ai/getting-started/rate-limits.md
> Retrieved: 2026-10-31
> Covers: Rate limits incl. POST /v1/search


# API Rate Limits

> Default API rate limits for Search, Image Search, Extract, Decisions, Tasks, Chat, FindAll, and Monitor endpoints

For AI agents: a documentation index is available at [https://docs.parallel.ai/llms.txt](https://docs.parallel.ai/llms.txt). The full text of all docs is at [https://docs.parallel.ai/llms-full.txt](https://docs.parallel.ai/llms-full.txt). You may also fetch any page as Markdown by appending `.md` to its URL or sending `Accept: text/markdown`.

For Search and Extract, use `/v1/search` and `/v1/extract` for all new integrations and agent tool calls. Use `/v1beta/search` and `/v1beta/extract` only when maintaining an existing integration that already uses them. The request bodies changed too: on `/v1/extract`, `full_content`, `fetch_policy` and `excerpt_settings` go inside `advanced_settings`, and sending the v1beta top-level `excerpts`, `full_content` and `fetch_policy` to `/v1/extract` returns a 422. Do not substitute `/v1` for the documented FindAll or Ingest endpoint paths.

The following table shows the default rate limits for each Parallel API product:

| Product | Default Quota | What Counts as a Request |
| - | - | - |
| Search | 600 per min | Each POST to `/v1/search` |
| Image Search | 600 per min | Each POST to `/v1/images/search` |
| Extract | 600 per min | Each POST to `/v1/extract` |
| Decisions | 600 per min | Each POST to `/v1/decisions` |
| Tasks/TaskGroups | 2,000 per min | Each Task Run created through `/v1/tasks/runs` or `/v1/tasks/groups/{taskgroup_id}/runs` |
| Chat | 300 per min | Each POST to `/v1beta/chat/completions` |
| FindAll | 300 per hour | Each POST to `/v1beta/findall/runs` (creating a generator) |
| Entity Search | 600 per min | Each POST to `/v1beta/findall/entity-search` |
| Monitor | 300 per min | Each POST to `/v1alpha/monitors` |

> [!NOTE]
>
> **Rate limits apply to POST requests that create new resources.** GET requests
> (retrieving results, checking status) do not count against these limits. For
> example, polling a task's status with `GET /v1/tasks/runs/{run_id}` does not
> consume your Tasks rate limit—only creating new tasks does. In a Task Group
> request, each item in `inputs` creates a run and counts toward the Tasks quota.

## Pricing

Rate limits are separate from pricing. For cost information, see [Pricing](https://docs.parallel.ai/getting-started/pricing.md).

## Need higher limits?

If you need to expand your rate limits, please contact **[support@parallel.ai](mailto:support@parallel.ai)** with your use case and requirements.
