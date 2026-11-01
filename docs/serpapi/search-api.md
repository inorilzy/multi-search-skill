> Source: https://serpapi.com/search-api.md
> Retrieved: 2026-10-31
> Covers: GET https://serpapi.com/search (engine=google) request params + response example

---
title: "Google Search Engine Results API"
description: "Scrape Google search results in JSON format automatically using custom parameters. Search for keywords by location, date and more with SerpApi."
url: https://serpapi.com/search-api
site: "SerpApi – Real-time search engine results API"
signup: https://serpapi.com/users/sign_up
engine: "google"
docs:
  pricing: https://serpapi.com/pricing.md
  integrations: https://serpapi.com/integrations.md
---

# Google Search Engine Results API

Scrape Google search results in JSON format automatically using custom parameters. Search for keywords by location, date and more with SerpApi.

## Example Request

```
GET https://serpapi.com/search?api_key=YOUR_API_KEY&engine=google&q=QUERY
```

## API parameters

### Search Query

| Parameter | Required | Description |
|-----------|----------|-------------|
| `q` | **Yes** | Parameter defines the query you want to search. You can use anything that you would use in a regular Google search. e.g. `inurl:`, `site:`, `intitle:`. We also support advanced search query parameters such as `as_dt` and `as_eq`. See the [full list](https://serpapi.com/advanced-google-query-parameters) of supported advanced search query parameters.  `site:` can't be used with `tbm` set to `nws`. |

### Geographic location

| Parameter | Required | Description |
|-----------|----------|-------------|
| `location` | No | Parameter defines from where you want the search to originate. If several locations match the location requested, we'll pick the most popular one. Head to the [/locations.json API](https://serpapi.com/locations-api) if you need more precise control. It is recommended to specify `location` at the city level in order to simulate a real user’s search. If `location` is omitted, the search may take on the location of the proxy.   When only the `location` parameter is set, Google may still take into account the proxy’s country, which can influence some results. For more consistent country-specific filtering, use the `gl` parameter alongside `location`. Parameter can't be used together with `uule`, `lat`, and `lon` parameters. |
| `uule` | No | Parameter is the Google encoded location you want to use for the search.  `uule` and `location` parameters can't be used together. For consistent results with coordinates-based `uule` parameter, a matching `gl` parameter is required. Head to [UULE Generator](https://serpapi.com/tools/uule-generator) if you need to convert a location or GPS coordinates to `uule` parameter, and vice versa. |
| `lat` | No | Parameter defines a GPS latitude for the search origin.  Parameter is required when using `lon` parameter. For consistent results, a matching `gl` parameter is required. Parameter can't be used together with `location` and `uule` parameters. |
| `lon` | No | Parameter defines a GPS longitude for the search origin.  Parameter is required when using `lat` parameter. For consistent results, a matching `gl` parameter is required. Parameter can't be used together with `location` and `uule` parameters. |
| `radius` | No | Parameter defines the distance (in meters) within which to bias the search results. Results inside of this region will be ranked higher than results outside of it. However, prominent results from outside of the search radius may still be included.  Value range per `device`: - Desktop: `1..199` - Tablet: `1..1000` - Mobile: `1..1000`  Parameter can be used alongside `location` or `lat`/`lon` parameters. When parameter is paired with `location`, its center point coordinates are used for the search. |

### Advanced parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `ludocid` | No | Parameter defines the Google CID (customer identifier) of a place. This parameter can be found in [Google Search API](https://serpapi.com/search-api) and [Google Local API](https://serpapi.com/google-local-api) local results under the name of `place_id`, as well as in [Google Maps API](https://serpapi.com/google-maps-api) local results under the name of `data_cid`. You can also acquire it using [Google's CID converter](https://pleper.com/index.php?do=tools&sdo=cid_converter). |
| `lsig` | No | Parameter that you might have to use to force the knowledge graph map view to show up. You can find the `lsig` ID by using our [Local Pack API](https://serpapi.com/local-pack) or [Google Local API](https://serpapi.com/google-local-api). `lsig` ID is also available via a redirect Google uses within [Google My Business](https://www.google.com/business/). |
| `kgmid` | No | Parameter defines the id (`KGMID`) of the Google Knowledge Graph listing you want to scrape. Also known as Google Knowledge Graph ID. Searches with `kgmid` parameter will return results for the originally encrypted search parameters. For some searches, `kgmid` may override all other parameters except `start` parameter. |
| `si` | No | Parameter defines the cached search parameters of the Google Search you want to scrape. Searches with `si` parameter will return results for the originally encrypted search parameters. For some searches, `si` may override all other parameters except `startsi` can be used to scrape Google Knowledge Graph Tabs. |
| `ibp` | No | Parameter is responsible for rendering layouts and expansions for some elements (e.g., `gwp;0,7` to expand searches with `ludocid` for expanded knowledge graph). |
| `uds` | No | Parameter enables to filter search. It's a string provided by Google as a filter. `uds` values are provided under the section: `filters` with `uds`, `q` and `serpapi_link` values provided for each filter. |
| `color_scheme` | No | Parameter forces the selected color scheme to be used on the results page. If the parameter is not set, a random color scheme will be returned.  Options:  `light` - Light `dark` - Dark |

### Localization

| Parameter | Required | Description |
|-----------|----------|-------------|
| `google_domain` | No | Parameter defines the Google domain to use. It defaults to `google.com`. Head to the [Google domains page](https://serpapi.com/google-domains) for a full list of supported Google domains. |
| `gl` | No | Parameter defines the country to use for the Google search. It's a two-letter country code. (e.g., `us` for the United States, `uk` for United Kingdom, or `fr` for France). Head to the [Google countries page](https://serpapi.com/google-countries) for a full list of supported Google countries. |
| `hl` | No | Parameter defines the language to use for the Google search. It's a two or three-letter language code. (e.g., `en` for English, `es` for Spanish, or `fr` for French), optionally followed by a two-letter or three-digit region code (e.g., `en-gb` for British English, or `es-419` for Latin American Spanish). Head to the [Google languages page](https://serpapi.com/google-languages) for a full list of supported Google languages. |
| `cr` | No | Parameter defines one or multiple countries to limit the search to. It uses `country{two-letter upper-case country code}` to specify countries and `|` as a delimiter. (e.g., `countryFR|countryDE` will only search French and German pages). Head to the [Google cr countries page](https://serpapi.com/google-cr-countries) for a full list of supported countries. |
| `lr` | No | Parameter defines one or multiple languages to limit the search to. It uses `lang_{two-letter language code}` to specify languages and `|` as a delimiter. (e.g., `lang_fr|lang_de` will only search French and German pages). Head to the [Google lr languages page](https://serpapi.com/google-lr-languages) for a full list of supported languages. |

### Advanced filters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `tbs` | No | (to be searched) parameter defines advanced search parameters that aren't possible in the regular query field. (e.g., advanced search for patents, dates, news, videos, images, apps, or text contents). |
| `safe` | No | Parameter defines the level of filtering for adult content. It can be set to `active` or `off`, by default Google will blur explicit content. |
| `nfpr` | No | Parameter defines the exclusion of results from an auto-corrected query when the original query is spelled wrong. It can be set to `1` to exclude these results, or `0` to include them (default). Note that this parameter may not prevent Google from returning results for an auto-corrected query if no other results are available. |
| `filter` | No | Parameter defines if the filters for 'Similar Results' and 'Omitted Results' are on or off. It can be set to `1` (default) to enable these filters, or `0` to disable these filters. |

### Search type

| Parameter | Required | Description |
|-----------|----------|-------------|
| `tbm` | No | (to be matched) parameter defines the type of search you want to do.  It can be set to: `(no tbm parameter)`: regular Google Search, `isch`: [Google Images API](https://serpapi.com/images-results), `lcl`: [Google Local API](https://serpapi.com/local-results), `vid`: [Google Videos API](https://serpapi.com/videos-results), `nws`: [Google News API](https://serpapi.com/news-results), `shop`: [Google Shopping API](https://serpapi.com/shopping-results), `pts`: [Google Patents API](https://serpapi.com/google-patents-api), `bks`: [Google Books API](https://serpapi.com/google-books-api), or any other Google service. |

### Pagination

| Parameter | Required | Description |
|-----------|----------|-------------|
| `start` | No | Parameter defines the result offset. It skips the given number of results. It's used for pagination. (e.g., `0` (default) is the first page of results, `10` is the 2nd page of results, `20` is the 3rd page of results, etc.). |

### SerpApi parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `engine` | No | Set parameter to `google` (default) to use the Google API engine. |
| `device` | No | Parameter defines the device to use to get the results. It can be set to `desktop` (default) to use a regular browser, `tablet` to use a tablet browser (currently using iPads), or `mobile` to use a mobile browser. |
| `no_cache` | No | Parameter will force SerpApi to fetch the Google results even if a cached version is already present. A cache is served only if the query and all parameters are exactly the same. Cache expires after 1h. Cached searches are free, and are not counted towards your searches per month. It can be set to `false` (default) to allow results from the cache, or `true` to disallow results from the cache. `no_cache` and `async` parameters should not be used together. |
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
    "total_results": 3140000000,
    "time_taken_displayed": 0.34,
    "organic_results_state": "Results for exact spelling",
    "results_for": "Austin, TX"
  },
  "local_map": {
    "link": "https://www.google.com/search?q=Coffee&sca_esv=82729a62&udm=1&lsack=kyVZaaXZMJixqtsPiOfE0AY&sa=X&...",
    "image": "https://serpapi.com/searches/69592590/images/876a39b5.png",
    "gps_coordinates": {
      "latitude": 30.27196615,
      "longitude": -97.74716377
    }
  },
  "local_results": {
    "places": [
      {
        "position": 1,
        "rating": 4.5,
        "reviews": 1200,
        "reviews_original": "(1.2K)",
        "price": "$1–10",
        "description": "Cozy hangout for carefully sourced brews",
        "lsig": "AB86z5Vdw6C2pJpM0xQ6JUx2KONU",
        "thumbnail": "https://serpapi.com/searches/69592590/images/3755275d.jpeg",
        "place_id": "11265938",
        "place_id_search": "https://serpapi.com/search.json?device=desktop&engine=google&google_domain=google.com&location=Au...",
        "gps_coordinates": {
          "latitude": 30.266216,
          "longitude": -97.743065
        },
        "title": "Houndstooth Coffee",
        "type": "Coffee shop",
        "address": "401 Congress Ave. #100c"
      }
    ],
    "more_locations_link": "https://www.google.com/search?q=Coffee&sca_esv=82729a62&udm=1&lsack=kyVZaaXZMJixqtsPiOfE0AY&sa=X&..."
  },
  "knowledge_graph": {
    "title": "Coffee",
    "type": "Beverages",
    "kgmid": "/m/02vqfm",
    "knowledge_graph_search_link": "https://www.google.com/search?kgmid=/m/02vqfm&hl=en-US&q=Coffee",
    "serpapi_knowledge_graph_search_link": "https://serpapi.com/search.json?device=desktop&engine=google&google_domain=google.com&hl=en-US&kg...",
    "header_images": [
      {
        "image": "https://serpapi.com/searches/69592590/images/7349ceb5.webp",
        "source": "https://en.wikipedia.org/wiki/Coffee_bean"
      }
    ],
    "description": "Coffee is a beverage brewed from roasted, ground coffee beans. Darkly colored, bitter, and slight...",
    "source": {
      "name": " Wikipedia",
      "link": "https://en.wikipedia.org/wiki/Coffee"
    },
    "sources_include": "USDA Coffee 1 Calories - 1 cup (8 fl oz) (237 g)",
    "sources_include_links": [
      {
        "text": "USDA",
        "link": "https://fdc.nal.usda.gov/food-details/171890/nutrients"
      }
    ]
  },
  "immersive_products": [
    {
      "category": "Popular products",
      "thumbnail": "https://serpapi.com/searches/69592590/images/54273230.webp",
      "source_logo": "https://serpapi.com/searches/69592590/images/54273230.png",
      "source": "Walmart",
      "title": "Folgers Classic Roast Ground Coffee",
      "rating": 4.6,
      "reviews": 16000,
      "price": "$13.86",
      "extracted_price": 13.86,
      "original_price": "$21",
      "extracted_original_price": 21,
      "location": "Nearby, 12 mi",
      "extensions": [
        "34% OFF"
      ]
    }
  ],
  "related_questions": [
    {
      "question": "What is the 80/20 rule for coffee?",
      "type": "featured_snippet",
      "snippet": "The 80/20 rule for coffee states that 20% of the brewing variables contribute to 80% of the final...",
      "title": "What Is The 80/20 Rule For Coffee?",
      "date": "2 days ago",
      "link": "https://www.tankcoffee.com/what-is-the-80-20-rule-for-coffee/#:~:text=The%2080%2F20%20rule%20for%...",
      "displayed_link": "https://www.tankcoffee.com › what-is-the-80-20-rule-for...",
      "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQYzqCdQE-_hdkz9ru9LNUGNWF-4lEfDH8gtBxdOr2F1A&s",
      "source_logo": "https://serpapi.com/searches/69592590/images/4d5c4b17.jpeg",
      "next_page_token": "...",
      "serpapi_link": "https://serpapi.com/search.json?device=desktop&engine=google_related_questions&google_domain=goog..."
    }
  ],
  "organic_results": [
    {
      "position": 1,
      "title": "Coffee",
      "link": "https://en.wikipedia.org/wiki/Coffee",
      "redirect_link": "https://www.google.com/url?sa=t&source=web&rct=j&opi=89978449&url=https://en.wikipedia.org/wiki/C...",
      "displayed_link": "https://en.wikipedia.org › wiki › Coffee",
      "thumbnail": "https://serpapi.com/searches/69592590/images/1ce1314c.jpeg",
      "favicon": "https://serpapi.com/searches/69592590/images/1ce1314c.png",
      "snippet": "Coffee is a beverage brewed from roasted, ground coffee beans. Darkly colored, bitter, and slight...",
      "snippet_highlighted_words": [
        "a beverage brewed from roasted, ground coffee beans"
      ],
      "sitelinks": {
        "inline": [
          {
            "title": "History of coffee",
            "link": "https://en.wikipedia.org/wiki/History_of_coffee"
          }
        ]
      },
      "source": "Wikipedia"
    }
  ],
  "perspectives": [
    {
      "author": "Lance Hedrick",
      "author_description": "Coffee enthusiast & content creator",
      "source": "YouTube",
      "extensions": [
        "89.2K+ views "
      ],
      "thumbnails": [
        "https://img.youtube.com/vi/vhdk2KuWVbc/hqdefault.jpg"
      ],
      "title": "I Changed My Mind About Coffee (Here's Why)",
      "link": "https://www.youtube.com/watch?v=vhdk2KuWVbc",
      "date": "4 days ago",
      "video": "https://encrypted-vtbn0.gstatic.com/video?q=tbn:ANd9GcS506sh4Ki7OL8DP_Z4D6oqemuKpXdvI2o2Gg"
    }
  ],
  "related_searches": [
    {
      "block_position": 1,
      "query": "Coffee nearby",
      "link": "https://www.google.com/search?sca_esv=82729a62&q=Coffee+nearby&sa=X&ved=2ahUKEwjl7omtyO-RAxWYmGoF...",
      "serpapi_link": "https://serpapi.com/search.json?device=desktop&engine=google&google_domain=google.com&location=Au..."
    }
  ],
  "refine_this_search": [
    {
      "query": "Nearby",
      "link": "https://www.google.com/search?q=Coffee+nearby&shoprs=GAMqBmNvZmZlZTIMCAMSBk5lYXJieRgCWLfLH2AB&sa=...",
      "serpapi_link": "https://serpapi.com/search.json?device=desktop&engine=google&google_domain=google.com&location=Au..."
    }
  ],
  "refine_search_filters": [
    {
      "type": "Product Rating",
      "options": [
        {
          "title": "",
          "link": "https://www.google.com/search?q=Coffee&shoprs=EgViAwiQAxgeKgZjb2ZmZWUyFQgeEgg0IGFuZCB1cCIFYgMIkAN...",
          "serpapi_link": "https://serpapi.com/search.json?device=desktop&engine=google&google_domain=google.com&location=Au..."
        }
      ]
    }
  ],
  "things_to_know": {
    "buttons": [
      {
        "text": "Health Benefits",
        "title": "9 Health Benefits of Coffee: What the Science Says - Healthline",
        "link": "https://www.healthline.com/nutrition/top-evidence-based-health-benefits-of-coffee#:~:text=Some%20...",
        "displayed_link": "https://www.healthline.com › nutrition › top-evidence-ba...",
        "date": "Feb 23, 2023",
        "snippet": "Some research shows that drinking coffee may benefit heart health. In fact, one review found that...",
        "favicon": "https://serpapi.com/searches/69592590/images/801f2675.png",
        "source": "healthline.com",
        "search_link": "https://www.google.com/search?sca_esv=82729a62&q=health+benefits+of+coffee&sa=X&ved=2ahUKEwjl7omt...",
        "serpapi_search_link": "https://serpapi.com/search.json?device=desktop&engine=google&google_domain=google.com&location=Au..."
      }
    ]
  },
  "pagination": {
    "current": 1,
    "next": "https://www.google.com/search?q=Coffee&sca_esv=82729a62&ei=kyVZaaXZMJixqtsPiOfE0AY&start=10&sa=N&...",
    "other_pages": {
      "2": "https://www.google.com/search?q=Coffee&sca_esv=82729a62&ei=kyVZaaXZMJixqtsPiOfE0AY&start=10&sa=N&...",
      "3": "https://www.google.com/search?q=Coffee&sca_esv=82729a62&ei=kyVZaaXZMJixqtsPiOfE0AY&start=20&sa=N&...",
      "4": "https://www.google.com/search?q=Coffee&sca_esv=82729a62&ei=kyVZaaXZMJixqtsPiOfE0AY&start=30&sa=N&...",
      "...": "..."
    }
  },
  "serpapi_pagination": {
    "current": 1,
    "next_link": "https://serpapi.com/search.json?device=desktop&engine=google&google_domain=google.com&location=Au...",
    "next": "https://serpapi.com/search.json?device=desktop&engine=google&google_domain=google.com&location=Au...",
    "other_pages": {
      "2": "https://serpapi.com/search.json?device=desktop&engine=google&google_domain=google.com&location=Au...",
      "3": "https://serpapi.com/search.json?device=desktop&engine=google&google_domain=google.com&location=Au...",
      "4": "https://serpapi.com/search.json?device=desktop&engine=google&google_domain=google.com&location=Au...",
      "...": "..."
    }
  }
}
```

