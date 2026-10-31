> Source: https://exa.ai/docs/admin/billing.md
> Retrieved: 2026-10-31
> Covers: Rate limits (QPS) for /search and /contents

# Billing and Rate Limits

> Manage Exa credits, invoices, and API rate limits.

Exa offers a Free tier, pay-as-you-go billing, and custom Enterprise plans. API usage draws from your team's credit balance, while rate limits control how quickly the team can make requests.

> [card] [Billing dashboard](https://dashboard.exa.ai/billing?utm_source=docs\&utm_medium=docs\&utm_campaign=admin_billing)
>
> Add credits, configure auto recharge, and view invoices.

> [card] [API keys](https://dashboard.exa.ai/api-keys?utm_source=docs\&utm_medium=docs\&utm_campaign=admin_billing)
>
> Review usage and set a lower limit for an individual key.

> [card] [Pricing](https://exa.ai/docs/admin/pricing.md)
>
> Compare current rates across Exa products.

## Plans at a glance

| Plan | Billing | Rate limit | Agent concurrency |
| - | - | - | - |
| **Free** | \$10 in credits every month, plus a one-time \$10 onboarding bonus (see [Free tier credits](#free-tier-credits)) | 10 QPS | 50 active runs |
| **Pay as you go** | Prepaid credits with no subscription or minimum spend | 10 QPS, [up to 25 QPS](#25-qps-on-pay-as-you-go) | 50 active runs |
| **Enterprise** | Custom volume pricing and optional postpaid invoicing | Custom | Custom |

The Free tier does not include [Exa Snapshot](https://exa.ai/docs/search/snapshot.md). Add a card and buy credits on the [Billing dashboard](https://dashboard.exa.ai/billing?utm_source=docs\&utm_medium=docs\&utm_campaign=admin_billing) to move to a pay-as-you-go plan.

> [card] [Contact Us](https://exa.ai/contact/sales)
>
> We'll advise on the best set up to handle latency, scale, ZDR, and more.

## Billing basics

Requests are charged against prepaid credits at the rates in [Pricing](https://exa.ai/docs/admin/pricing.md) or under your Enterprise contract. Team owners can add credits from the [Billing dashboard](https://dashboard.exa.ai/billing?utm_source=docs\&utm_medium=docs\&utm_campaign=admin_billing); payments are processed through Stripe.

If your team exhausts its credits, requests return `402 Payment Required`. An API key that reaches its assigned budget also returns `402`. Add credits or ask a team administrator to adjust the key's budget. See [Error codes](https://exa.ai/docs/admin/error-codes.md).

### Free tier credits

Every new team starts on the Free tier with \$10 in credits, available in full the day you sign up regardless of the date. Your free balance then resets to \$10 on the first day of every calendar month. The grant does not accumulate: unused free credits from one month do not carry into the next, so this grant never holds more than \$10 at a time. Only a user's first team receives the monthly grant.

A user's first team also earns a one-time \$10 bonus when that user completes onboarding in the dashboard. The bonus does not expire.

Free credits spend on API calls at the standard rates and are never paid out or refunded.

For historical usage by API key, use [Get API key usage](https://exa.ai/docs/reference/team-management/get-api-key-usage.md).

## Rate limits

Rate limits are measured in queries per second (QPS) and apply to your team as a whole, across all of its API keys. You can give an individual key a lower limit from the [API Keys](https://dashboard.exa.ai/api-keys?utm_source=docs\&utm_medium=docs\&utm_campaign=admin_billing) page, but its traffic still counts toward the team limit.

| Endpoint | Default limit |
| - | - |
| `/search`, `/answer`, `/chat/completions` | 10 QPS |
| `/search` with `type` `deep-lite`, `deep`, or `deep-reasoning` | 5 QPS |
| `/contents` | 100 QPS |
| `/agent/runs`, `/responses` | 5 QPS and 50 active runs |
| `/websets/*` | 20 QPS |

Some endpoints share rate limit capacity. Limits are subject to change and can vary by plan; Websets searches also have plan-based concurrency limits, which you can check with [Get Team Info](https://exa.ai/docs/websets/api/teams/get-team-info.md).

When you exceed a limit, requests return `429 Too Many Requests`. Wait for the `Retry-After` header when present, or retry with exponential backoff. See [Error codes](https://exa.ai/docs/admin/error-codes.md).

### Agent limits

Agent limits are two separate controls: how many runs can be in progress at once, and how fast you can start new ones.

* **Concurrency**: 50 Agent runs can be in progress at a time. This limit is separate from your QPS and does not change when your QPS is raised. Starting a run past the limit returns `429` with error code `CONCURRENCY_LIMIT_REACHED`; wait for a run to finish or contact us to raise your concurrency limit.
* **Starting runs**: `POST /agent/runs` draws from your account QPS, and each run start counts as two requests. You can start runs at half your QPS, so an account with the default 10 QPS can start 5 runs per second, and 25 QPS allows 12 per second.
* **Polling**: `GET` requests for run status, events, and run lists do not count against your QPS and never block dispatch, so poll running Agents independently of how fast you start new ones.

### 25 QPS on pay as you go

Add \$1,000 in credits within any 30-day window and your team's rate limit rises to **25 QPS for 90 days**, automatically. The threshold counts credits you purchase, not credits you spend, and requalifying resets the 90 days. Track your progress on the [Billing dashboard](https://dashboard.exa.ai/billing?utm_source=docs\&utm_medium=docs\&utm_campaign=admin_billing).

Need more than 25 QPS? [Talk to sales](https://exa.ai/contact/sales).

## Auto recharge

Auto recharge purchases credits when your balance reaches a threshold you choose. Configure it from the [Billing dashboard](https://dashboard.exa.ai/billing?utm_source=docs\&utm_medium=docs\&utm_campaign=admin_billing).

| Setting | Description |
| - | - |
| **Recharge amount** | Credits purchased each time auto recharge triggers, from \$5 to \$10,000. |
| **Recharge threshold** | The balance at which the recharge triggers. |
| **Monthly maximum** | Optional cap on auto-recharge purchases during the billing cycle. Set it to \$0 or leave it blank for no cap. |

For example, a \$100 recharge amount, \$10 threshold, and \$500 monthly maximum purchases \$100 whenever the balance reaches \$10, up to \$500 in automatic purchases during the cycle.

For an upcoming launch or other high-volume workload, add enough credits in advance and set an auto-recharge amount that avoids many small payment attempts.

## Receipts and invoices

Exa emails receipts for credit purchases and auto recharges from [billing@exa.ai](mailto:billing@exa.ai). Add the address to your allow list if needed. Your full invoice history is available in the [Billing dashboard](https://dashboard.exa.ai/billing?utm_source=docs\&utm_medium=docs\&utm_campaign=admin_billing).

Postpaid invoice billing is available with an Enterprise plan.

## Get help

> [card] [Increase your limits](https://exa.ai/contact/sales)
>
> Request more than 25 QPS, custom concurrency, volume pricing, or postpaid billing.

> [card] [Billing support](mailto:billing@exa.ai)
>
> Get help with payments, credits, invoices, or account billing questions.
