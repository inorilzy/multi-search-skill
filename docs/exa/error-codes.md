> Source: https://exa.ai/docs/admin/error-codes.md
> Retrieved: 2026-10-31
> Covers: Error envelope and tags for /search and /contents

# Error Codes

> Reference for common error codes used by the Exa API

Exa APIs signal failures with standard HTTP status codes and a JSON error body.

## HTTP status codes

| Code | Meaning | What to do |
| - | - | - |
| `400` Bad Request | The body, query parameters, headers, or combination of options is invalid. | Correct the request using the returned message. |
| `401` Unauthorized | The API key is missing or invalid. | Verify the authentication header and API key. |
| `402` Payment Required | Credits are exhausted or a spending budget was exceeded. | [Top up credits](https://dashboard.exa.ai/home?utm_source=docs\&utm_medium=docs\&utm_campaign=admin_error_codes) or contact your team administrator. |
| `403` Forbidden | The API key does not have access to the requested feature, or the request was blocked by policy. | Check the returned message and your plan's feature access. |
| `404` Not Found | The route or requested resource does not exist. | Verify the endpoint and resource ID. |
| `409` Conflict | The request conflicts with existing state — for example, a Webset with the same `externalId` already exists. | Fetch the existing resource or use a different identifier. |
| `422` Unprocessable Entity | A Websets preview query could not be decomposed into a valid entity and criteria. | Rephrase the preview query. |
| `429` Too Many Requests | Your API key, team, or network exceeded a rate or concurrency limit. | Reduce your request rate; wait for `Retry-After` seconds when present, otherwise use exponential backoff. |
| `500` Internal Server Error | An unexpected server error occurred. | Retry after a brief delay. Contact support if it persists. |
| `503` Service Unavailable | Exa is temporarily over capacity (`SERVICE_OVERLOADED`) or unavailable. The request was not processed and is not billed. | Retry with exponential backoff. This is independent of your request rate, so reducing it does not help — retrying does. |
| `504` Gateway Timeout | The request exceeded its processing deadline. | Retry the request or reduce its scope. |

> [!NOTE]
>
> URL-level failures from `/contents` are reported in the `statuses` field of a successful `200` response, not as request-level errors. See [Content fetch status tags](#content-fetch-status-tags).

## Error response structure

Error responses return a `requestId`, a human-readable `error` message, and a machine-readable `tag`:

```json theme={null}
{
  "requestId": "67207943fab9832d162b5317f4cca830",
  "error": "Invalid request body | Validation error: Invalid value for type",
  "tag": "INVALID_REQUEST_BODY"
}
```

> [!NOTE]
>
> Include the `requestId` when contacting support for faster troubleshooting.

The set of tags is open-ended and tag names are self-explanatory. Branch on the HTTP status code first and treat unrecognized tags as additional detail rather than parse failures.

## Common error tags

### Account, billing, and access

| Tag | HTTP code | Description |
| - | - | - |
| `INVALID_API_KEY` | `401` | The API key is missing, empty, or invalid. |
| `NO_MORE_CREDITS` | `402` | The account has no remaining credits — top up at [dashboard.exa.ai](https://dashboard.exa.ai/home?utm_source=docs\&utm_medium=docs\&utm_campaign=admin_error_codes). |
| `API_KEY_BUDGET_EXCEEDED` | `402` | The API key exceeded its spending budget for the current billing period — contact your team administrator. |
| `TEAM_BUDGET_EXCEEDED` | `402` | The team exceeded its spending budget for the current billing period. |
| `FEATURE_DISABLED` | `403` | The requested endpoint, search type, or option is not enabled for your plan. |
| `PROHIBITED_CONTENT` | `403` | The request was rejected by content safety moderation. |
| `CONTENT_FILTER_ERROR` | `403` | Content was rejected by a safety policy during processing. |
| `RATE_LIMIT_EXCEEDED` | `429` | Your API key, team, or network exceeded its own rate limit — reduce your request rate. |
| `SERVICE_OVERLOADED` | `503` | Exa is temporarily over capacity and shed the request before processing it — retry with exponential backoff. |

### Request validation

| Tag | HTTP code | Description |
| - | - | - |
| `INVALID_REQUEST_BODY` | `400` | The JSON body failed schema validation. |
| `INVALID_REQUEST` | `400` | Options conflict with each other, or a beta feature was used without its `Exa-Beta` header. |
| `INVALID_NUM_RESULTS` | `400` | `numResults` must be ≤ 100 when highlights are requested. |
| `NUM_RESULTS_EXCEEDED` | `400` | The requested result count exceeds your plan's limit. |
| `INVALID_JSON_SCHEMA` | `400` | The provided output schema is invalid. |
| `SUBPAGES_LIMIT_EXCEEDED` | `400` | `/contents` allows at most 100 subpages per request. |

### Payment protocols

Requests paid through x402 or MPP can also return:

| Tag | HTTP code | Description |
| - | - | - |
| `X402_PAYMENT_REQUIRED` | `402` | Payment is required. |
| `X402_INVALID_SIGNATURE` | `400` | The x402 payment signature is invalid. |
| `X402_VERIFICATION_FAILED` | `402` | The x402 payment could not be verified. |
| `MPP_VERIFICATION_FAILED` | `402` | The MPP payment could not be verified. |
| `X402_TOO_MANY_UNPAID` | `429` | Too many x402 requests are awaiting payment. |
| `X402_WALLET_RATE_LIMITED` | `429` | The x402 wallet exceeded its rate limit. |
| `X402_INTERNAL_ERROR` | `500` | Exa could not create x402 payment requirements. |

## Content fetch status tags

When `/contents` receives multiple URLs, one URL can fail while the others succeed. URL-level failures are returned in the `statuses` field and do not fail the request:

```json theme={null}
{
  "results": [],
  "statuses": [
    {
      "id": "https://example.com",
      "status": "error",
      "error": {
        "tag": "CRAWL_NOT_FOUND",
        "httpStatusCode": 404
      }
    }
  ]
}
```

`httpStatusCode` describes the target page, not the `/contents` response.

| Tag | Description | How to handle |
| - | - | - |
| `CRAWL_NOT_FOUND` | The target page was not found. | Verify the URL is correct and accessible. |
| `CRAWL_HTTP_{status}` | The target returned an HTTP error, such as `CRAWL_HTTP_403`. | Handle the embedded target status. |
| `CRAWL_TIMEOUT` | The crawl timed out while fetching the target page. | Retry the request or try again later. |
| `CRAWL_LIVECRAWL_TIMEOUT` | Live retrieval exceeded your requested `livecrawlTimeout`. | Increase `livecrawlTimeout` or adjust `maxAgeHours`. |
| `SOURCE_NOT_AVAILABLE` | Access to the source is forbidden or the source is unavailable. | Check whether the source requires authentication or is restricted. |
| `UNSUPPORTED_URL` | The URL scheme is not supported for content fetching. | Use a standard HTTP or HTTPS URL. |
| `CRAWL_UNKNOWN_ERROR` | The crawl failed for another reason. | Retry the request; contact support if persistent. |

These status tags are specific to `/contents`; `/search` does not return a `statuses` field.

A `/search` request that succeeds can still return `warnings` about the request and `notices` about how the results were produced. [Warnings and notices](https://exa.ai/docs/search/best-practices.md#warnings-and-notices) explains what each one means and what to do with it.

## Getting help

* Check [Exa Status](https://exa.ai/docs/admin/status.md) when `500`, `503`, or `504` errors persist.
* Check [Rate Limits](https://exa.ai/docs/admin/billing.md#rate-limits) for current limits.
* Review the endpoint's [API reference](https://exa.ai/docs/reference/search.md) for request requirements.
* Contact [support@exa.ai](mailto:support@exa.ai) with the response status, error body, and `requestId`.
