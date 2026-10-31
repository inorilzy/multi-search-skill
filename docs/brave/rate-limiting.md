> Source: https://api-dashboard.search.brave.com/documentation/guides/rate-limiting/index.html.md
> Retrieved: 2026-10-31
> Covers: Rate limiting (429, X-RateLimit-* headers) for all endpoints

# Rate Limiting

Understand how rate limiting works and best practices for staying within your quota

## Overview

The API implements rate limiting to ensure fair usage and system stability. Rate limits are enforced using a **1-second sliding window** to count requests per plan. This means your request count is evaluated in real-time over the most recent second.

When you exceed your rate limit, the API will return a **429 status code** and your request will fail. Monitor the rate limit headers to avoid hitting these limits.

## Rate Limit Response Headers

Every API response includes headers that help you track and manage your rate limits. Use these headers to implement proper rate limiting logic in your application.

| Header | Description | Example |
| ----------------------- | ------------------------------------------------ | -------------------------------------------------------------------------- |
| `X-RateLimit-Limit` | Rate limits associated with your plan | `1, 15000` (1 request/second, 15000 requests/month) |
| `X-RateLimit-Policy` | Rate limit policies with window sizes in seconds | `1;w=1, 15000;w=2592000` (1 req per 1s window, 15000 req per month window) |
| `X-RateLimit-Remaining` | Remaining quota for each limit window | `1, 1000` (1 request left this second, 1000 left this month) |
| `X-RateLimit-Reset` | Seconds until each quota resets | `1, 1419704` (resets in 1 second and 1419704 seconds) |

## Understanding the Headers

### X-RateLimit-Limit

Shows the maximum number of requests allowed for each time window in your plan.

**Example**: `X-RateLimit-Limit: 1, 15000`

- **1 request per second** - Burst rate limit
- **15,000 requests per month** - Monthly quota (**0** for unlimited)

### X-RateLimit-Policy

Provides the complete policy specification including window sizes. Windows are always expressed in seconds.

**Example**: `X-RateLimit-Policy: 1;w=1, 15000;w=2592000`

- `1;w=1` - Limit of 1 request over a 1-second window
- `15000;w=2592000` - Limit of 15,000 requests over a 2,592,000-second window (30 days)

### X-RateLimit-Remaining

Indicates how many requests you can still make within each time window before hitting the limit.

**Example**: `X-RateLimit-Remaining: 1, 1000`

- **1 request** available in the current second
- **1,000 requests** remaining in the current month

**Important**: Only successful requests (non-error responses) are counted against your quota and billed.

### X-RateLimit-Reset

Shows when each quota window will reset, expressed in seconds from now.

**Example**: `X-RateLimit-Reset: 1, 1419704`

- **1 second** until you can make another request (per-second limit resets)
- **1,419,704 seconds** until your monthly quota fully resets (≈16.4 days)

## Best Practices

### Implement Retry Logic

When you receive a 429 status code, check the `X-RateLimit-Reset` header to determine how long to wait before retrying. Implement exponential backoff for additional resilience.

```python
import time
import requests

def make_request_with_retry(url, headers, max_retries=3):
    for attempt in range(max_retries + 1):
        response = requests.get(url, headers=headers)

        if response.status_code != 429 or attempt == max_retries:
            return response

        wait_time = 2 ** attempt  # 1s, 2s, 4s...
        time.sleep(wait_time)

    return response
```

### Monitor Remaining Quota

Check `X-RateLimit-Remaining` before making subsequent requests. This helps you avoid hitting limits unexpectedly.

```javascript
const remaining = response.headers.get('X-RateLimit-Remaining');
const [perSecond, perMonth] = remaining
  .split(',')
  .map(n => parseInt(n.trim()));

if (perSecond < 1) {
    // Wait before next request
    await new Promise(resolve => setTimeout(resolve, 1000));
}
```

### Distribute Requests Evenly

Instead of bursting all requests at once, distribute them evenly throughout your time window to maximize throughput and avoid hitting the per-second limit.

### Handle Multiple Windows

Your plan may have multiple limit windows (per-second, quota). Track all to ensure you don't exceed either limit.

## Key Insights

- **Real-time tracking**: The 1-second window slides continuously, so your request count is always calculated for the most recent second.
- **Counted on arrival**: The request count is increased when request is received. The processing time does not affect the rate-limit.
- **Multiple limits**: Most plans have both burst limits (per-second) and quota limits (per-month) that must be respected simultaneously
- **Successful requests only**: Failed requests don't count against your quota, so you're only charged for successful API calls
- **Predictable resets**: Use the `X-RateLimit-Reset` header to calculate exactly when you can safely retry

## Example Response Headers

Here's what you might see in a typical API response:

```http
HTTP/1.1 200 OK
X-RateLimit-Limit: 1, 15000
X-RateLimit-Policy: 1;w=1, 15000;w=2592000
X-RateLimit-Remaining: 0, 14523
X-RateLimit-Reset: 1, 1234567
```

**Interpretation**:

- You've used your 1 request for this second (`Remaining: 0`)
- You have 14,523 requests left this month (`Remaining: 14523`)
- You can make another request in 1 second
- Your monthly quota resets in 1,234,567 seconds (≈14.3 days)