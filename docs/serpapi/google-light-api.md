> Source: https://serpapi.com/google-light-api.md
> Retrieved: 2026-10-31
> Covers: GET https://serpapi.com/search (engine=google_light) request params + response example

---
title: "Google Light Search API"
description: "Access the world's fastest Google Search API. Scrape Google search results in JSON format automatically using custom parameters. Search for keywords by location with SerpApi."
url: https://serpapi.com/google-light-api
site: "SerpApi – Real-time search engine results API"
signup: https://serpapi.com/users/sign_up
engine: "google_light"
docs:
  pricing: https://serpapi.com/pricing.md
  integrations: https://serpapi.com/integrations.md
---

# Google Light Search API

Access the world's fastest Google Search API. Scrape Google search results in JSON format automatically using custom parameters. Search for keywords by location with SerpApi.

## Example Request

```
GET https://serpapi.com/search?api_key=YOUR_API_KEY&engine=google_light&q=QUERY
```

## API parameters

### Search Query

| Parameter | Required | Description |
|-----------|----------|-------------|
| `q` | **Yes** | Parameter defines the query you want to search. You can use anything that you would use in a regular Google search. e.g. `inurl:`, `site:`, `intitle:`. We also support advanced search query parameters such as `as_dt` and `as_eq`. See the [full list](https://serpapi.com/advanced-google-query-parameters) of supported advanced search query parameters. |

### Geographic location

| Parameter | Required | Description |
|-----------|----------|-------------|
| `location` | No | Parameter defines from where you want the search to originate. If several locations match the location requested, we'll pick the most popular one. Head to the [/locations.json API](https://serpapi.com/locations-api) if you need more precise control. The `location` and `uule` parameters can't be used together. It is recommended to specify `location` at the city level in order to simulate a real user’s search. If `location` is omitted, the search may take on the location of the proxy. |
| `uule` | No | Parameter is the Google encoded location you want to use for the search.  `uule` and `location` parameters can't be used together. For consistent results with coordinates-based `uule` parameter, a matching `gl` parameter is required. Head to [UULE Generator](https://serpapi.com/tools/uule-generator) if you need to convert a location or GPS coordinates to `uule` parameter, and vice versa. |

### Localization

| Parameter | Required | Description |
|-----------|----------|-------------|
| `google_domain` | No | Parameter defines the Google domain to use. It defaults to `google.com`. Head to the [Google domains page](https://serpapi.com/google-domains) for a full list of supported Google domains. |
| `gl` | No | Parameter defines the country to use for the Google search. It's a two-letter country code. (e.g., `us` for the United States, `uk` for United Kingdom, or `fr` for France). Head to the [Google countries page](https://serpapi.com/google-countries) for a full list of supported Google countries. |
| `hl` | No | Parameter defines the language to use for the Google search. It's a two or three-letter language code. (e.g., `en` for English, `es` for Spanish, or `fr` for French), optionally followed by a two-letter or three-digit region code (e.g., `en-gb` for British English, or `es-419` for Latin American Spanish). Head to the [Google languages page](https://serpapi.com/google-languages) for a full list of supported Google languages. |
| `lr` | No | Parameter defines one or multiple languages to limit the search to. It uses `lang_{two-letter language code}` to specify languages and `|` as a delimiter. (e.g., `lang_fr|lang_de` will only search French and German pages). Head to the [Google lr languages page](https://serpapi.com/google-lr-languages) for a full list of supported languages. |

### Advanced filters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `safe` | No | Parameter defines the level of filtering for adult content. It can be set to `active` or `off`, by default Google will blur explicit content. |
| `nfpr` | No | Parameter defines the exclusion of results from an auto-corrected query when the original query is spelled wrong. It can be set to `1` to exclude these results, or `0` to include them (default). Note that this parameter may not prevent Google from returning results for an auto-corrected query if no other results are available. |
| `filter` | No | Parameter defines if the filters for 'Similar Results' and 'Omitted Results' are on or off. It can be set to `1` (default) to enable these filters, or `0` to disable these filters. |

### Pagination

| Parameter | Required | Description |
|-----------|----------|-------------|
| `start` | No | Parameter defines the result offset. It skips the given number of results. It's used for pagination. (e.g., `0` (default) is the first page of results, `10` is the 2nd page of results, `20` is the 3rd page of results, etc.). |

### SerpApi parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `engine` | **Yes** | Set parameter to `google_light` to use the Google Light API engine. |
| `device` | No | Parameter defines the device to use to get the results. It can be set to `desktop` (default) to use a regular browser, `tablet` to use a tablet browser (currently using iPads), or `mobile` to use a mobile browser. |
| `no_cache` | No | Parameter will force SerpApi to fetch the Google Light results even if a cached version is already present. A cache is served only if the query and all parameters are exactly the same. Cache expires after 1h. Cached searches are free, and are not counted towards your searches per month. It can be set to `false` (default) to allow results from the cache, or `true` to disallow results from the cache. `no_cache` and `async` parameters should not be used together. |
| `async` | No | Parameter defines the way you want to submit your search to SerpApi. It can be set to `false` (default) to open an HTTP connection and keep it open until you got your search results, or `true` to just submit your search to SerpApi and retrieve them later. In this case, you'll need to use our [Searches Archive API](https://serpapi.com/search-archive-api) to retrieve your results. `async` and `no_cache` parameters should not be used together. `async` should not be used on accounts with [Ludicrous Speed](https://serpapi.com/plan) enabled. |
| `zero_trace` | No | Enterprise only. Parameter enables [ZeroTrace mode](https://serpapi.com/zero-trace-mode). It can be set to `false` (default) or `true`. Enable this mode to skip storing search parameters, search files, and search metadata on our servers. This may make debugging more difficult. |
| `api_key` | **Yes** | Parameter defines the SerpApi private key to use. |
| `output` | No | Parameter defines the format of the result. It can be set to `json` (default) to get a structured JSON of the results, `html` to get the raw HTML retrieved, or `md` to get a Markdown-formatted version optimized for LLMs and AI agents. |
| `json_restrictor` | No | Parameter defines the fields you want to include in the output, reducing payload size for faster response. See the [JSON Restrictor documentation](https://serpapi.com/json-restrictor) for more details. |

## Response Example

Truncated sample response. URLs are illustrative and not accessible.

```json
{
  "search_information": {
    "query_displayed": "Coffee",
    "organic_results_state": "Results for exact spelling"
  },
  "organic_results": [
    {
      "position": 1,
      "title": "Coffee - Wikipedia",
      "link": "https://en.wikipedia.org/wiki/Coffee",
      "displayed_link": "en.wikipedia.org › wiki › Coffee",
      "snippet": "Coffee is a beverage brewed from roasted, ground coffee beans. Darkly colored, bitter, and slight...",
      "sitelinks": {
        "inline": [
          {
            "title": "History of coffee",
            "link": "https://en.wikipedia.org/wiki/History_of_coffee"
          }
        ]
      }
    }
  ],
  "related_questions": [
    {
      "question": "What is the 80/20 rule for coffee?",
      "snippet": "The 80/20 rule for coffee states that 20% of the brewing variables contribute to 80% of the final...",
      "snippet_highlighted_words": [
        "20% of the brewing variables contribute to 80% of the final flavour quality"
      ],
      "title": "What Is The 80/20 Rule For Coffee?",
      "link": "https://www.tankcoffee.com/what-is-the-80-20-rule-for-coffee/",
      "displayed_link": "www.tankcoffee.com › what-is-the-80-20-rule-for-coffee",
      "more_results_link": "https://www.google.com/search?sca_esv=82729a62&gbv=1&ei=tSZZaZSBKbfQ5NoPvrWtqAw&q=What+is+the+80/..."
    }
  ],
  "related_searches": [
    {
      "query": "Coffee nearby",
      "link": "https://www.google.com/search?sca_esv=82729a62&gbv=1&q=Coffee+nearby&sa=X&ved=2ahUKEwjUr6a3ye-RAx...",
      "serpapi_link": "https://serpapi.com/search.json?device=desktop&engine=google_light&google_domain=google.com&locat..."
    }
  ],
  "serpapi_pagination": {
    "current": 1,
    "next": "https://serpapi.com/search.json?device=desktop&engine=google_light&google_domain=google.com&locat..."
  }
}
```

