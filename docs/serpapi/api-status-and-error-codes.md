> Source: https://serpapi.com/api-status-and-error-codes
> Retrieved: 2026-10-31
> Covers: GET https://serpapi.com/search HTTP status codes and error JSON

# Status and Error Codes

SerpApi uses conventional HTTP response codes to indicate the success or failure of an API request. In general, a `200` code indicates success. Codes in the `4xx` range usually indicate an error that failed given the information provided (e.g., a required parameter was omitted, ran out of searches, etc.). Codes in the `5xx` range usually indicate an error with SerpApi's servers.   
  
 Please refer to the [Search API Status and Errors](https://serpapi.com/api-status-and-error-codes#search-api-status-and-errors) section for guidance on how to handle errors in the Search API.

| HTTP status codes |
| --- |
| `200` | OK | Everything worked as expected. |
| `400` | Bad Request | We were unable to process the request. The request may be missing a required parameter. |
| `401` | Unauthorized | No valid API key provided. |
| `403` | Forbidden | The account associated with this API key doesn't have permission to perform the request. This usually happens if the account has been deleted. |
| `404` | Not Found | The requested resource doesn't exist. |
| `410` | Gone | The search expired and has been deleted from the archive. |
| `429` | Too Many Requests | The number of requests sent using this API key exceeds the hourly throughput limit _OR_ your account has run out of searches. |
| `500`, `503` | Server Error | Something went wrong on SerpApi's end. Please contact support@serpapi.com for assistance. |

### [](https://serpapi.com/api-status-and-error-codes#api-examples-json-structure-overview) JSON structure overview

```json
{
  "error": "String - A human-readable message about the error."
}
```

## [](https://serpapi.com/api-status-and-error-codes#api-examples)Examples

### [](https://serpapi.com/api-status-and-error-codes#api-examples-error-for-invalid-api-key) Error for invalid API key

HTTP Status: `401` (Unauthorized)

GET

*    
```url
https://serpapi.com/search.json?
```

  

Code to integrate

cURL CLI Ruby Python JavaScript Go PHP Java Rust C++.NET Swift Google Sheets

*   [](https://github.com/serpapi/serpapi-ruby)[](https://rubygems.org/gems/serpapi) 
```ruby
require "serpapi" 

client = SerpApi::Client.new(
  api_key: "secret_api_key"
)

results = client.search
```

  

JSON Example

[](https://serpapi.com/playground?)

```json
{
  "error": "Invalid API key. Your API key should be here: https://serpapi.com/manage-api-key"
}
```

### [](https://serpapi.com/api-status-and-error-codes#api-examples-error-for-no-searches-remaining) Error for no searches remaining

HTTP Status: `429` (Too Many Requests)

GET

*    
```url
https://serpapi.com/search.json?
```

  

Code to integrate

cURL CLI Ruby Python JavaScript Go PHP Java Rust C++.NET Swift Google Sheets

*   [](https://github.com/serpapi/serpapi-ruby)[](https://rubygems.org/gems/serpapi) 
```ruby
require "serpapi" 

client = SerpApi::Client.new(
  api_key: "secret_api_key"
)

results = client.search
```

  

JSON Example

[](https://serpapi.com/playground?)

```json
{
  "error": "Your account has run out of searches."
}
```

### [](https://serpapi.com/api-status-and-error-codes#api-examples-error-for-missing-parameter-in-google-search-api) Error for missing parameter in[Google Search API](https://serpapi.com/search-api)

HTTP Status: `400` (Bad Request)

GET

*    
```url
https://serpapi.com/search.json?
```

  

Code to integrate

cURL CLI Ruby Python JavaScript Go PHP Java Rust C++.NET Swift Google Sheets

*   [](https://github.com/serpapi/serpapi-ruby)[](https://rubygems.org/gems/serpapi) 
```ruby
require "serpapi" 

client = SerpApi::Client.new(
  api_key: "secret_api_key"
)

results = client.search
```

  

JSON Example

[](https://serpapi.com/playground?)

```json
{
  "error": "Missing query `q` parameter."
}
```

## Search API Status and Errors

All of our Search APIs use the same error response structure. This includes all of our APIs except for the Extra APIs (Location API, Account API, Search Archive API etc.).   
  
 A search status is accessible through the `search_metadata.status` key. A search `status` begins as `Processing`, then resolves to either `Success` or `Error`. If a search has failed or contains empty results, the top level `error` key will contain an error message.   
  
 Note that if a search returns empty results due to no results returned by the search engine, it is still considered successful from SerpApi's perspective and will have a `status` value of `Success`.

| Search Status | Description |
| --- | --- |
| `Success` | Search request is successfully processed (It might include empty results). |
| `Processing` | Search request is processing. |
| `Queued` | Search request is queued for process. |
| `Error` | Search process encountered an error before it could be completed (e.g. Proxy timeout, internal errors, etc). |

### [](https://serpapi.com/api-status-and-error-codes#api-examples-json-structure-overview) JSON structure overview

```json
{
  "search_information": {
    "organic_results_state": "String - The result state for organic results (e.g. Fully Empty, Results for exact spelling). The key may not always be present if the search returns results. The key name varies by engine to reflect result type, i.e  'local_results_state', or 'finance_results_state', but always ending in '_state'",
  },
  "error": "String - A human-readable message about the error."
}
```

## [](https://serpapi.com/api-status-and-error-codes#search-api-error-examples)Examples

### [](https://serpapi.com/api-status-and-error-codes#api-examples-status-error) Status: `Error`

HTTP Status: `503` (Service Unavailable)

GET

*    
```url
https://serpapi.com/search.json?
```

  

Code to integrate

cURL CLI Ruby Python JavaScript Go PHP Java Rust C++.NET Swift Google Sheets

*   [](https://github.com/serpapi/serpapi-ruby)[](https://rubygems.org/gems/serpapi) 
```ruby
require "serpapi" 

client = SerpApi::Client.new(
  api_key: "secret_api_key"
)

results = client.search
```

  

JSON Example

[](https://serpapi.com/playground?)

```json
{
  "search_metadata": {
    "id": "64c32cfeb68f8bc186aaa013",
    "status": "Error",
    "json_endpoint": "https://serpapi.com/searches/d46c933a4a843289/64c32cfeb68f8bc186aaa013.json",
    ...
  },
  ...
  "error": "We couldn't get valid results for this search. Please try again later.",
}
```

### [](https://serpapi.com/api-status-and-error-codes#api-examples-status-success-with-empty-organic-results-in-google-search-api) Status: `Success` with empty organic results in[Google Search API](https://serpapi.com/search-api)

HTTP Status: `200` (OK)

GET

*    
```url
https://serpapi.com/search.json?
```

  

Code to integrate

cURL CLI Ruby Python JavaScript Go PHP Java Rust C++.NET Swift Google Sheets

*   [](https://github.com/serpapi/serpapi-ruby)[](https://rubygems.org/gems/serpapi) 
```ruby
require "serpapi" 

client = SerpApi::Client.new(
  api_key: "secret_api_key"
)

results = client.search
```

  

JSON Example

[](https://serpapi.com/playground?)

```json
{
  "search_metadata": {
    "id": "6540ac26b68f8b2910019dd5",
    "status": "Success",
    "json_endpoint": "https://serpapi.com/searches/d1add70d119063c8/6540ac26b68f8b2910019dd5.json",
    ...
  },
  ...
  "search_information": {
    "organic_results_state": "Fully empty"
  },
  "error": "Google hasn't returned any results for this query."
}
```

### [](https://serpapi.com/api-status-and-error-codes#api-examples-status-success-with-spelling-fixes-in-google-search-api) Status: `Success` with spelling fixes in[Google Search API](https://serpapi.com/search-api)

HTTP Status: `200` (OK).  
  
`error` key is not present in this case because valid results are returned.

GET

*    
```url
https://serpapi.com/search.json?
```

  

Code to integrate

cURL CLI Ruby Python JavaScript Go PHP Java Rust C++.NET Swift Google Sheets

*   [](https://github.com/serpapi/serpapi-ruby)[](https://rubygems.org/gems/serpapi) 
```ruby
require "serpapi" 

client = SerpApi::Client.new(
  api_key: "secret_api_key"
)

results = client.search
```

  

JSON Example

[](https://serpapi.com/playground?)

```json
{
  "search_metadata": {
    "id": "6540ac26b68d3b2910019dd5",
    "status": "Success",
    "json_endpoint": "https://serpapi.com/searches/d3add74d149063c9/6540ac26b68d3b2910019dd5.json",
    ...
  },
  ...
  "search_information": {
    "query_displayed": "Coffe",
    "organic_results_state": "Some results for exact spelling but showing fixed spelling",
    "spelling_fix": "Coffee"
  },
  ...
}
```

### [](https://serpapi.com/api-status-and-error-codes#api-examples-status-success-with-empty-local-results-in-google-maps-api) Status: `Success` with empty local results in[Google Maps API](https://serpapi.com/google-maps-api)

HTTP Status: `200` (OK)

GET

*    
```url
https://serpapi.com/search.json?
```

  

Code to integrate

cURL CLI Ruby Python JavaScript Go PHP Java Rust C++.NET Swift Google Sheets

*   [](https://github.com/serpapi/serpapi-ruby)[](https://rubygems.org/gems/serpapi) 
```ruby
require "serpapi" 

client = SerpApi::Client.new(
  api_key: "secret_api_key"
)

results = client.search
```

  

JSON Example

[](https://serpapi.com/playground?)

```json
{
  "search_metadata": {
    "id": "6540af0b66440aef3efcbdd0",
    "status": "Success",
    "json_endpoint": "https://serpapi.com/searches/268f774b7d0b7072/6540af0b66440aef3efcbdd0.json",
    ...
  },
  ...
  "search_information": {
    "local_results_state": "Fully empty"
  },
  "error": "Google hasn't returned any results for this query."
}
```

### [](https://serpapi.com/api-status-and-error-codes#api-examples-status-success-with-query-feedback-in-google-search-api) Status: `Success` with `query_feedback` in[Google Search API](https://serpapi.com/search-api)

HTTP Status: `200` (OK)  
  
`error` key is not present in this case because at least one valid result is returned.

GET

*    
```url
https://serpapi.com/search.json?
```

  

Code to integrate

cURL CLI Ruby Python JavaScript Go PHP Java Rust C++.NET Swift Google Sheets

*   [](https://github.com/serpapi/serpapi-ruby)[](https://rubygems.org/gems/serpapi) 
```ruby
require "serpapi" 

client = SerpApi::Client.new(
  api_key: "secret_api_key"
)

results = client.search
```

  

JSON Example

[](https://serpapi.com/playground?)

```json
{
  "search_metadata": {
    "id": "6540af0b66440aef3efcbdd0",
    "status": "Success",
    "json_endpoint": "https://serpapi.com/searches/268f774b7d0b7072/6540af0b66440aef3efcbdd0.json",
    ...
  },
  ...
  "search_information": {
    "query_feedback": {
      "title": "It looks like there aren't many great matches for your search",
      "description": "Try using words that might appear on the page you’re looking for. For example, \"cake recipes\" instead of \"how to make a cake.\""
    },
  },
}
```

### [](https://serpapi.com/api-status-and-error-codes#api-examples-status-success-with-results-for-in-google-search-api) Status: `Success` with `results_for` in[Google Search API](https://serpapi.com/search-api)

HTTP Status: `200` (OK)  
  
`error` key is not present in this case because valid results are returned.

GET

*    
```url
https://serpapi.com/search.json?
```

  

Code to integrate

cURL CLI Ruby Python JavaScript Go PHP Java Rust C++.NET Swift Google Sheets

*   [](https://github.com/serpapi/serpapi-ruby)[](https://rubygems.org/gems/serpapi) 
```ruby
require "serpapi" 

client = SerpApi::Client.new(
  api_key: "secret_api_key"
)

results = client.search
```

  

JSON Example

[](https://serpapi.com/playground?)

```json
{
  "search_metadata": {
    "id": "6540af0b66440aef3efcbdd0",
    "status": "Success",
    "json_endpoint": "https://serpapi.com/searches/268f774b7d0b7072/6540af0b66440aef3efcbdd0.json",
    ...
  },
  ...
  "search_parameters": {
    "engine": "google",
    "q": "ny hurricane",
    "location_requested": "Austin, Texas, United States",
    "location_used": "Austin,Texas,United States",
    "google_domain": "google.com",
    "hl": "en",
    "gl": "us",
    "device": "desktop"
  },
  "search_information": {
    "query_displayed": "ny hurricane",
    "total_results": 231000000,
    "time_taken_displayed": 0.3,
    "organic_results_state": "Results for exact spelling",
    "results_for": "New York, NY"
  },
}
```

### **SerpApi** results for ""

[×](javascript:void(0) "Clear search box")

Custom Search

Sort by

Relevance

Date