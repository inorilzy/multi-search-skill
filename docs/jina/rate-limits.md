> Source: https://jina.ai/reader (section "Rate limit", text extracted from HTML)
> Retrieved: 2026-10-31
> Covers: rate limits for https://r.jina.ai (Reader read) and https://s.jina.ai

```text
Rate limit
Rate limits are tracked in two ways: 
RPM
 (requests per minute) and 
TPM
 (tokens per minute). Limits are enforced per IP/API key and will be triggered when either the RPM or TPM threshold is reached first. When you provide an API key in the request header, we track rate limits by key rather than IP address.
Columns
arrow_drop_down
fullscreen
Product
API Endpoint
Description
arrow_upward
w/o API Key
key_off
w/ Free API Key
key
w/ Paid API Key
key
w/ Premium API Key
key
Average latency
Token Usage Counting
Allowed Request
Reader API
https://r.jina.ai
Converts a URL to LLM-friendly text
20 RPM
500 RPM
500 RPM
trending_up
5000 RPM
7.9s
Count the number of tokens in the output response.
GET/POST
Reader API
https://s.jina.ai
Search the web and convert results to LLM-friendly text
block
100 RPM
100 RPM
trending_up
1000 RPM
2.5s
Every request costs a fixed number of tokens, starting from 10,000 tokens
GET/POST
Embedding API
https://api.jina.ai/v1/embeddings
Convert text/images to fixed-length vectors
block
100 RPM & 100,000 TPM
500 RPM & 2,000,000 TPM
trending_up
5,000 RPM & 50,000,000 TPM
ssid_chart
depends on the input size
help
Count the number of tokens in the input request.
POST
Reranker API
https://api.jina.ai/v1/rerank
Rank documents by query
block
100 RPM & 100,000 TPM
500 RPM & 2,000,000 TPM
trending_up
5,000 RPM & 50,000,000 TPM
ssid_chart
depends on the input size
help
Count the number of tokens in the input request.
POST
```
