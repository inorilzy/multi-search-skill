> Source: https://api-dashboard.search.brave.com/documentation/guides/authentication/index.html.md
> Retrieved: 2026-10-31
> Covers: Authentication (X-Subscription-Token) for all endpoints

# Authentication

Learn how to authenticate your requests to the Brave Search API using API keys

## Overview

The Brave Search API uses API key authentication to secure requests. Every API request must include an API key in the request header to authenticate and authorize access.

AI agents that pay with stablecoin micropayments need no API key. See [Agent payments](/documentation/guides/agent-payments).

Your API key is confidential and should be kept secure. Never expose it in client-side code, public repositories, or any public location.

## Obtaining Your API Key

To get started with the Brave Search API, you'll need an API key:

1. **Activate a plan** — Go to [Plans](/app/subscriptions/subscribe) page and choose a plan that fits your needs
2. **Create an API key** — Once activated, navigate to the [API Keys section](/app/keys) in the dashboard and create a new key
3. **Copy your token** — Your API key will be displayed. Copy it to use in your requests

## Authentication Method

All requests to the Brave Search API must include an API key in the `X-Subscription-Token` HTTP header.

### Header Format

```
X-Subscription-Token: YOUR_API_KEY
```

## Code Examples

Here are examples of how to authenticate your search queries:

```bash
curl "https://api.search.brave.com/res/v1/llm/context?q=brave+search" \
  -H "X-Subscription-Token: YOUR_API_KEY"
```

```python
import requests

url = "https://api.search.brave.com/res/v1/llm/context"
headers = {
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
    "X-Subscription-Token": "YOUR_API_KEY"
}
params = {
    "q": "brave search"
}

response = requests.get(url, headers=headers, params=params)
data = response.json()
print(data)
```

```js
const url = new URL("https://api.search.brave.com/res/v1/llm/context");
url.searchParams.append("q", "brave search");

const response = await fetch(url, {
  headers: {
    Accept: "application/json",
    "Accept-Encoding": "gzip",
    "X-Subscription-Token": "YOUR_API_KEY",
  },
});
const data = await response.json();
console.log(data);
```

## Best Practices

### Secure Storage

Never hardcode your API key directly in your source code. Instead, use environment variables or secure configuration management:

```python
import os

api_key = os.environ.get('BRAVE_API_KEY')
headers = {
    'X-Subscription-Token': api_key
}
```

```javascript
const apiKey = process.env.BRAVE_API_KEY;
const headers = {
  "X-Subscription-Token": apiKey,
};
```

```bash
export BRAVE_API_KEY="your_actual_api_key_here"
```

### Key Rotation

Regularly rotate your API keys as a security best practice. You can generate new and revoke old keys from the [dashboard](/app/keys).

If you suspect your API key has been compromised, immediately revoke it from your dashboard and generate a new one.

### More

To learn more about best practises, see [OWASP Cheat Sheet for Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html).

## Next Steps

### API Overview

Learn about available endpoints and features

### API Reference

Explore detailed API documentation