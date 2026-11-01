> Source: https://api-dashboard.search.brave.com/api-reference/web/search/get/index.html.md
> Retrieved: 2026-10-31
> Covers: GET https://api.search.brave.com/res/v1/web/search (API reference: auth, query params, headers, response schema, errors)

# Search

`GET` `/v1/web/search`

Search the web from a large independent index of web pages.

**Base URL:** `https://api.search.brave.com/res`

## Authorization

| Name | Location | Type | Required | Constraints | Description |
|------|----------|------|----------|-------------|-------------|
| `x-subscription-token` | header | string | Yes |  | The subscription token that was generated for the product. |

## Query Parameters

| Name | Location | Type | Required | Constraints | Description |
|------|----------|------|----------|-------------|-------------|
| `q` | query | string | Yes |  | The user's search query term. Query can not be empty. Maximum of 600 characters and 75 words in the query. |
| `country` | query | string | No | `AR`, `AU`, `AT`, `BE`, `BR`, `CA`, `CL`, `DK`, `FI`, `FR`, `DE`, `GR`, `HK`, `IN`, `ID`, `IT`, `JP`, `KR`, `MY`, `MX`, `NL`, `NZ`, `NO`, `CN`, `PL`, `PT`, `PH`, `RU`, `SA`, `ZA`, `ES`, `SE`, `CH`, `TW`, `TR`, `GB`, `US`, `ALL`; default `US` | The 2 character country code where the search results come from. |
| `search_lang` | query | string | No | `ar`, `eu`, `bn`, `bg`, `ca`, `zh-hans`, `zh-hant`, `hr`, `cs`, `da`, `nl`, `en`, `en-gb`, `et`, `fi`, `fr`, `gl`, `de`, `el`, `gu`, `he`, `hi`, `hu`, `is`, `it`, `ja`, `jp`, `kn`, `ko`, `lv`, `lt`, `ms`, `ml`, `mr`, `nb`, `pl`, `pt-br`, `pt-pt`, `pa`, `ro`, `ru`, `sr`, `sk`, `sl`, `es`, `sv`, `ta`, `te`, `th`, `tr`, `uk`, `vi`; default `en` | The 2 or more character language code for which the search results are provided. |
| `ui_lang` | query | string | No | `es-AR`, `en-AU`, `de-AT`, `nl-BE`, `fr-BE`, `pt-BR`, `en-CA`, `fr-CA`, `es-CL`, `da-DK`, `fi-FI`, `fr-FR`, `de-DE`, `el-GR`, `zh-HK`, `en-IN`, `en-ID`, `it-IT`, `ja-JP`, `ko-KR`, `en-MY`, `es-MX`, `nl-NL`, `en-NZ`, `no-NO`, `zh-CN`, `pl-PL`, `en-PH`, `ru-RU`, `en-ZA`, `es-ES`, `sv-SE`, `fr-CH`, `de-CH`, `zh-TW`, `tr-TR`, `en-GB`, `en-US`, `es-US`; default `en-US` | User interface language preferred in response. Usually of the format <language_code>-<country_code>. For more, see [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html#name-accept-language). |
| `count` | query | integer | No | `1`-`20`; default `20` | The number of search results returned in response. The maximum is 20. The actual number delivered may be less than requested. Combine this parameter with offset to paginate search results. **NOTE:** Count only applies to web results. |
| `offset` | query | integer | No | `0`-`9`; default `0` | The zero based offset that indicates number of search result pages (count) to skip before returning the result. The default is 0 and the maximum is 9. The actual number delivered may be less than requested. Use this parameter along with the count parameter to page results. For example, if your user interface displays 10 search results per page, set count to 10 and offset to 0 to get the first page of results. For each subsequent page, increment offset by 1 (for example, 0, 1, 2). It is possible for multiple pages to include some overlap in results. |
| `safesearch` | query | string | No | `off`, `moderate`, `strict`; default `moderate` | Filters search results for adult content. The following values are supported: - **off** - No filtering is done. - **moderate** - Filters explicit content, like images and videos, but allows adult domains in the search results. - **strict** - Drops all adult content from search results. |
| `spellcheck` | query | boolean | No | default `true` | Whether to spell check provided query. If the spell checker is enabled, the modified query is always used for search. The modified query can be found in altered key from the query response model. |
| `freshness` | query | string | No | default `` | Filters search results by page age. The age of a page is determined by the most relevant date reported by the content, such as its published or last modified date. The following values are supported: - **pd** - Pages aged 24 hours or less. - **pw** - Pages aged 7 days or less. - **pm** - Pages aged 31 days or less. - **py** - Pages aged 365 days or less. - **YYYY-MM-DDtoYYYY-MM-DD** - A custom date range is also supported by specifying start and end dates e.g. `2022-04-01to2022-07-30`. |
| `text_decorations` | query | boolean | No | default `true` | Whether display strings (e.g. result snippets) should include decoration markers (e.g. highlighting characters). |
| `result_filter` | query | string | No |  | A comma delimited string of result types to include in the search response. Not specifying this parameter will return back all result types in search response where data is available and the plan has the corresponding option activated. The response always includes query and type to identify any query modifications and response type respectively. Available result filter values are: `discussions`, `faq`, `infobox`, `news`, `query`, `summarizer`, `videos`, `web`, `locations`. **NOTE:** count param only applies to web results. |
| `units` | query | string | No | `imperial`, `metric` | The measurement units. The following values are supported: - **metric** - The standardized measurement system (km, celcius..) - **imperial** - The British Imperial system of units (mile, fahrenheit..) |
| `goggles_id` | query | string | No |  | Goggles act as a custom re-ranking on top of Brave's search index. For more details, refer to the Goggles repository. This parameter is deprecated. Please use the goggles parameter. |
| `goggles` | query | string | No |  | Goggles act as a custom re-ranking on top of Brave's search index. The parameter supports both a url where the Goggle is hosted or the definition of the Goggle. For more details, see the [Goggles documentation](/documentation/resources/goggles). The parameter can be a single Goggle or a list of up to 3 Goggles. |
| `extra_snippets` | query | string | No |  | A snippet is an excerpt from a page you get as a result of the query, and extra_snippets allow you to get up to 5 additional, alternative excerpts. |
| `summary` | query | string | No |  | This parameter enables summary key generation in web search results. This is required for summarizer to be enabled. |
| `enable_rich_callback` | query | boolean | No | default `false` | Enable rich callback. Allows you to get real time rich results via a callback URL when they are relevant to your query. **NOTE**: Requires `Search` plan. |
| `include_fetch_metadata` | query | boolean | No | default `false` | Include fetch metadata. |
| `operators` | query | boolean | No | default `true` | Whether to apply search operators |

## Headers

| Name | Location | Type | Required | Constraints | Description |
|------|----------|------|----------|-------------|-------------|
| `x-loc-lat` | header | string | No | `-90`-`90` | The latitude of the client's geographical location in degrees, to provide relevant local results. The latitude must be greater than or equal to -90.0 degrees and less than or equal to +90.0 degrees. |
| `x-loc-long` | header | string | No | `-180`-`180` | The longitude of the client's geographical location in degrees, to provide relevant local results. The longitude must be greater than or equal to -180.0 and less than or equal to +180.0 degrees. |
| `x-loc-timezone` | header | string | No |  | The IANA timezone for the client's device. For complete list of IANA timezones and location mappings see [IANA Database](https://www.iana.org/time-zones) and [Geonames Database](https://download.geonames.org/export/dump/). |
| `x-loc-city` | header | string | No |  | The generic name of the client city. |
| `x-loc-state` | header | string | No |  | A code which could be up to three characters, that represent the client's state/region. The region is the first-level subdivision (the broadest or least specific) of the [ISO 3166-2](https://en.wikipedia.org/wiki/ISO_3166-2) code. |
| `x-loc-state-name` | header | string | No |  | The name of the client's state/region. The region is the first-level subdivision (the broadest or least specific) of the [ISO 3166-2](https://en.wikipedia.org/wiki/ISO_3166-2) code. |
| `x-loc-country` | header | string | No | `AD`, `AE`, `AF`, `AG`, `AI`, `AL`, `AM`, `AO`, `AQ`, `AR`, `AS`, `AT`, `AU`, `AW`, `AX`, `AZ`, `BA`, `BB`, `BD`, `BE`, `BF`, `BG`, `BH`, `BI`, `BJ`, `BL`, `BM`, `BN`, `BO`, `BQ`, `BR`, `BS`, `BT`, `BV`, `BW`, `BY`, `BZ`, `CA`, `CC`, `CD`, `CF`, `CG`, `CH`, `CI`, `CK`, `CL`, `CM`, `CN`, `CO`, `CR`, `CU`, `CV`, `CW`, `CX`, `CY`, `CZ`, `DE`, `DJ`, `DK`, `DM`, `DO`, `DZ`, `EC`, `EE`, `EG`, `EH`, `ER`, `ES`, `ET`, `FI`, `FJ`, `FK`, `FM`, `FO`, `FR`, `GA`, `GB`, `GD`, `GE`, `GF`, `GG`, `GH`, `GI`, `GL`, `GM`, `GN`, `GP`, `GQ`, `GR`, `GS`, `GT`, `GU`, `GW`, `GY`, `HK`, `HM`, `HN`, `HR`, `HT`, `HU`, `ID`, `IE`, `IL`, `IM`, `IN`, `IO`, `IQ`, `IR`, `IS`, `IT`, `JE`, `JM`, `JO`, `JP`, `KE`, `KG`, `KH`, `KI`, `KM`, `KN`, `KP`, `KR`, `KW`, `KY`, `KZ`, `LA`, `LB`, `LC`, `LI`, `LK`, `LR`, `LS`, `LT`, `LU`, `LV`, `LY`, `MA`, `MC`, `MD`, `ME`, `MF`, `MG`, `MH`, `MK`, `ML`, `MM`, `MN`, `MO`, `MP`, `MQ`, `MR`, `MS`, `MT`, `MU`, `MV`, `MW`, `MX`, `MY`, `MZ`, `NA`, `NC`, `NE`, `NF`, `NG`, `NI`, `NL`, `NO`, `NP`, `NR`, `NU`, `NZ`, `OM`, `PA`, `PE`, `PF`, `PG`, `PH`, `PK`, `PL`, `PM`, `PN`, `PR`, `PS`, `PT`, `PW`, `PY`, `QA`, `RE`, `RO`, `RS`, `RU`, `RW`, `SA`, `SB`, `SC`, `SD`, `SE`, `SG`, `SH`, `SI`, `SJ`, `SK`, `SL`, `SM`, `SN`, `SO`, `SR`, `SS`, `ST`, `SV`, `SX`, `SY`, `SZ`, `TC`, `TD`, `TF`, `TG`, `TH`, `TJ`, `TK`, `TL`, `TM`, `TN`, `TO`, `TR`, `TT`, `TV`, `TW`, `TZ`, `UA`, `UG`, `UM`, `US`, `UY`, `UZ`, `VA`, `VC`, `VE`, `VG`, `VI`, `VN`, `VU`, `WF`, `WS`, `YE`, `YT`, `ZA`, `ZM`, `ZW` | The two letter country code for the client's country. For a list of country codes, see [ISO 3166-1 alpha-2](https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2). |
| `x-loc-postal-code` | header | string | No |  | The client's postal code. |
| `api-version` | header | string | No |  | The API version to use. This is denoted by the format `YYYY-MM-DD`. Default is the latest that is available. Read more about [API versioning](/documentation/guides/versioning). |
| `accept` | header | string | No | `application/json`, `*/*`; default `application/json` | The default supported media type is application/json. |
| `cache-control` | header | string | No | `no-cache` | Brave Search will return cached content by default. To prevent caching set the Cache-Control header to `no-cache`. This is currently done as best effort. |
| `user-agent` | header | string | No |  | The user agent originating the request. Brave search can utilize the user agent to provide a different experience depending on the device as described by the string. The user agent should follow the commonly used browser agent strings on each platform. For more information on curating user agents, see [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html#name-user-agent). |

## Responses

### 200
Successful Response

| Field | Type | Description |
|-------|------|-------------|
| `type` | string? |  |
| `query` | object? | Search query string and its modifications that are used for search. |
| `query.original` | string | The original query that was requested. |
| `query.show_strict_warning` | bool? | Whether to show a warning that strict safesearch filtered results. |
| `query.altered` | string? | The altered query by the spellchecker. |
| `query.cleaned` | string? | The cleaned normalized query. |
| `query.safesearch` | bool? | Whether safesearch is active. |
| `query.is_navigational` | bool? | Whether the query is navigational (user wants to go to a specific site). |
| `query.is_geolocal` | bool? | Whether the query has local intent. |
| `query.local_decision` | string? | The local search decision for the query. |
| `query.local_locations_idx` | int? | Index of the local location result. |
| `query.is_trending` | bool? | Whether the query is a trending topic. |
| `query.is_news_breaking` | bool? | Whether the query is related to breaking news. |
| `query.ask_for_location` | bool? | Whether to prompt the user for their location. |
| `query.language` | object? | The detected language of the query. |
| `query.language.main` | string | The main language seen in the string. |
| `query.spellcheck_off` | bool? | Whether spellcheck is disabled for this query. |
| `query.country` | string? | The country code for the query. |
| `query.bad_results` | bool? | Whether the results are considered low quality. |
| `query.should_fallback` | bool? | Whether to fallback to alternative ranking. |
| `query.lat` | string? | The latitude for location-based queries. |
| `query.long` | string? | The longitude for location-based queries. |
| `query.postal_code` | string? | The postal code for location-based queries. |
| `query.city` | string? | The city for location-based queries. |
| `query.header_country` | string? | The country from request headers. |
| `query.more_results_available` | bool? | Whether more results are available for pagination. |
| `query.state` | string? | The state/region for location-based queries. |
| `query.custom_location_label` | string? | A custom label for the location. |
| `query.reddit_cluster` | string? | Reddit cluster identifier for discussion results. |
| `query.summary_key` | string? | Key to retrieve AI-generated summary for the query. |
| `query.search_operators` | object? | Search operators that were detected and applied to the query. |
| `query.search_operators.applied` | bool? | Whether search operators were applied to the query. |
| `query.search_operators.cleaned_query` | string? | The query after search operators have been processed. |
| `query.search_operators.sites` | string[]? | List of site domains extracted from site: operators. |
| `query.related_queries` | string[]? | Related queries for the query. |
| `discussions` | object? | Discussions clusters aggregated from forum posts that are relevant to the query. |
| `discussions.type` | string? | The type identifying a discussion cluster. Currently the value is always `search`. |
| `discussions.results` | object[] | A list of discussion results. |
| `discussions.results[].title` | string | The title of the web page. |
| `discussions.results[].url` | string | The URL where the page is served. |
| `discussions.results[].is_source_local` | bool? | Whether the result is from a local source. |
| `discussions.results[].is_source_both` | bool? | Whether the result is from both local and global sources. |
| `discussions.results[].description` | string? | A description for the web page. |
| `discussions.results[].page_age` | string? | The page's date, based on its published or last modified date. |
| `discussions.results[].page_fetched` | string? | A date representing when the web page was last fetched. |
| `discussions.results[].fetched_content_timestamp` | int? | The timestamp when the content was fetched. |
| `discussions.results[].profile` | object? | A profile associated with the web page. |
| `discussions.results[].profile.name` | string | The name of the profile. |
| `discussions.results[].profile.url` | string | The original URL where the profile is available. |
| `discussions.results[].profile.long_name` | string? | The long name of the profile. |
| `discussions.results[].profile.img` | string? | The served image URL representing the profile. |
| `discussions.results[].language` | string? | The main language on the web search result. |
| `discussions.results[].family_friendly` | bool? | Whether the web page is family friendly. |
| `discussions.results[].type` | string? | The discussion result type identifier. The value is always `discussion`. |
| `discussions.results[].subtype` | string? | A sub type identifying the web search result type. |
| `discussions.results[].is_live` | bool? | Whether the web search result is currently live. Default value is `false`. |
| `discussions.results[].deep_results` | object? | Gathered information on a web search result. |
| `discussions.results[].deep_results.news` | object[]? | A list of news results associated with the result. |
| `discussions.results[].deep_results.news[].title` | string | The title of the web page. |
| `discussions.results[].deep_results.news[].url` | string | The URL where the page is served. |
| `discussions.results[].deep_results.news[].is_source_local` | bool? | Whether the result is from a local source. |
| `discussions.results[].deep_results.news[].is_source_both` | bool? | Whether the result is from both local and global sources. |
| `discussions.results[].deep_results.news[].description` | string? | A description for the web page. |
| `discussions.results[].deep_results.news[].page_age` | string? | The page's date, based on its published or last modified date. |
| `discussions.results[].deep_results.news[].page_fetched` | string? | A date representing when the web page was last fetched. |
| `discussions.results[].deep_results.news[].fetched_content_timestamp` | int? | The timestamp when the content was fetched. |
| `discussions.results[].deep_results.news[].profile` | object? | A profile associated with the web page. |
| `discussions.results[].deep_results.news[].profile.name` | string | The name of the profile. |
| `discussions.results[].deep_results.news[].profile.url` | string | The original URL where the profile is available. |
| `discussions.results[].deep_results.news[].profile.long_name` | string? | The long name of the profile. |
| `discussions.results[].deep_results.news[].profile.img` | string? | The served image URL representing the profile. |
| `discussions.results[].deep_results.news[].language` | string? | A language classification for the web page. |
| `discussions.results[].deep_results.news[].family_friendly` | bool? | Whether the web page is family friendly. |
| `discussions.results[].deep_results.news[].meta_url` | object? | The aggregated information on the URL representing a news result. |
| `discussions.results[].deep_results.news[].source` | string? | The source of the news. |
| `discussions.results[].deep_results.news[].breaking` | bool? | Whether the news result is currently a breaking news. |
| `discussions.results[].deep_results.news[].is_live` | bool? | Whether the news result is currently live. |
| `discussions.results[].deep_results.news[].thumbnail` | object? | The thumbnail associated with the news result. |
| `discussions.results[].deep_results.news[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].deep_results.news[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].deep_results.news[].thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].deep_results.news[].thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].deep_results.news[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].deep_results.news[].thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].deep_results.news[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].deep_results.news[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].deep_results.news[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].deep_results.news[].age` | string? | A human-readable representation of the news article's age. For example, `2 days ago`. |
| `discussions.results[].deep_results.news[].extra_snippets` | string[]? | A list of extra alternate snippets for the news search result. |
| `discussions.results[].deep_results.news[].icons` | object[]? | Icons associated with the news result. |
| `discussions.results[].deep_results.news[].icons[].href` | string |  |
| `discussions.results[].deep_results.news[].icons[].sizes` | string? |  |
| `discussions.results[].deep_results.news[].icons[].rel` | string? |  |
| `discussions.results[].deep_results.news[].icons[].type` | string? |  |
| `discussions.results[].deep_results.news[].icons[].ext` | string? |  |
| `discussions.results[].deep_results.buttons` | object[]? | A list of buttoned results associated with the result. |
| `discussions.results[].deep_results.buttons[].type` | string? | A type identifying button result. The value is always `button_result`. |
| `discussions.results[].deep_results.buttons[].title` | string | The title of the result. |
| `discussions.results[].deep_results.buttons[].url` | string | The URL for the button result. |
| `discussions.results[].deep_results.videos` | object[]? | Videos associated with the result. |
| `discussions.results[].deep_results.videos[].title` | string | The title of the web page. |
| `discussions.results[].deep_results.videos[].url` | string | The URL where the page is served. |
| `discussions.results[].deep_results.videos[].is_source_local` | bool? | Whether the result is from a local source. |
| `discussions.results[].deep_results.videos[].is_source_both` | bool? | Whether the result is from both local and global sources. |
| `discussions.results[].deep_results.videos[].description` | string? | A description for the web page. |
| `discussions.results[].deep_results.videos[].page_age` | string? | The page's date, based on its published or last modified date. |
| `discussions.results[].deep_results.videos[].page_fetched` | string? | A date representing when the web page was last fetched. |
| `discussions.results[].deep_results.videos[].fetched_content_timestamp` | int? | The timestamp when the content was fetched. |
| `discussions.results[].deep_results.videos[].profile` | object? | A profile associated with the web page. |
| `discussions.results[].deep_results.videos[].profile.name` | string | The name of the profile. |
| `discussions.results[].deep_results.videos[].profile.url` | string | The original URL where the profile is available. |
| `discussions.results[].deep_results.videos[].profile.long_name` | string? | The long name of the profile. |
| `discussions.results[].deep_results.videos[].profile.img` | string? | The served image URL representing the profile. |
| `discussions.results[].deep_results.videos[].language` | string? | A language classification for the web page. |
| `discussions.results[].deep_results.videos[].family_friendly` | bool? | Whether the web page is family friendly. |
| `discussions.results[].deep_results.videos[].type` | string? | The type identifying the video result. The value is always `video_result`. |
| `discussions.results[].deep_results.videos[].video` | object | Meta data for the video. |
| `discussions.results[].deep_results.videos[].video.duration` | string? | A time string representing the duration of the video. The format can be HH:MM:SS or MM:SS. |
| `discussions.results[].deep_results.videos[].video.views` | string? | The number of views of the video. |
| `discussions.results[].deep_results.videos[].video.creator` | string? | The creator of the video. |
| `discussions.results[].deep_results.videos[].video.publisher` | string? | The publisher of the video. |
| `discussions.results[].deep_results.videos[].video.thumbnail` | object? | A thumbnail associated with the video. |
| `discussions.results[].deep_results.videos[].video.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].deep_results.videos[].video.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].deep_results.videos[].video.thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].deep_results.videos[].video.thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].deep_results.videos[].video.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].deep_results.videos[].video.thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].deep_results.videos[].video.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].deep_results.videos[].video.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].deep_results.videos[].video.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].deep_results.videos[].video.tags` | string[]? | A list of tags associated with the video. |
| `discussions.results[].deep_results.videos[].video.author` | object? | Author of the video. |
| `discussions.results[].deep_results.videos[].video.author.name` | string | The name of the profile. |
| `discussions.results[].deep_results.videos[].video.author.url` | string | The original URL where the profile is available. |
| `discussions.results[].deep_results.videos[].video.author.long_name` | string? | The long name of the profile. |
| `discussions.results[].deep_results.videos[].video.author.img` | string? | The served image URL representing the profile. |
| `discussions.results[].deep_results.videos[].video.requires_subscription` | bool? | Whether the video requires a subscription to watch. |
| `discussions.results[].deep_results.videos[].meta_url` | object? | Aggregated information on the URL. |
| `discussions.results[].deep_results.videos[].meta_url.scheme` | string | The protocol scheme extracted from the URL. |
| `discussions.results[].deep_results.videos[].meta_url.netloc` | string | The network location part extracted from the URL. |
| `discussions.results[].deep_results.videos[].meta_url.hostname` | string? | The lowercased domain name extracted from the URL. |
| `discussions.results[].deep_results.videos[].meta_url.favicon` | string | The favicon used for the URL. |
| `discussions.results[].deep_results.videos[].meta_url.path` | string | The hierarchical path of the URL useful as a display string. |
| `discussions.results[].deep_results.videos[].thumbnail` | object? | The thumbnail of the video. |
| `discussions.results[].deep_results.videos[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].deep_results.videos[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].deep_results.videos[].thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].deep_results.videos[].thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].deep_results.videos[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].deep_results.videos[].thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].deep_results.videos[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].deep_results.videos[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].deep_results.videos[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].deep_results.videos[].age` | string? | A human-readable representation of the video's age. For example, `2 days ago`. |
| `discussions.results[].deep_results.videos[].publisher` | string? | The publisher of the video. |
| `discussions.results[].deep_results.images` | object[]? | Images associated with the result. |
| `discussions.results[].deep_results.images[].thumbnail` | object | The thumbnail associated with the image. |
| `discussions.results[].deep_results.images[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].deep_results.images[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].deep_results.images[].thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].deep_results.images[].thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].deep_results.images[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].deep_results.images[].thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].deep_results.images[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].deep_results.images[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].deep_results.images[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].deep_results.images[].url` | string? | The URL of the image. |
| `discussions.results[].deep_results.images[].properties` | object? | Metadata on the image. |
| `discussions.results[].deep_results.images[].properties.url` | string | The original image URL. |
| `discussions.results[].deep_results.images[].properties.resized` | string | The URL for a better quality resized image. |
| `discussions.results[].deep_results.images[].properties.placeholder` | string | The placeholder image URL. |
| `discussions.results[].deep_results.images[].properties.height` | int? | The image height. |
| `discussions.results[].deep_results.images[].properties.width` | int? | The image width. |
| `discussions.results[].deep_results.images[].properties.format` | string? | The image format. |
| `discussions.results[].deep_results.images[].properties.content_size` | string? | The image size. |
| `discussions.results[].schemas` | any[]? | A list of schemas (structured data) extracted from the page. The schemas try to follow schema.org and will return anything we can extract from the HTML that can fit into these models. |
| `discussions.results[].meta_url` | object? | Aggregated information on the URL associated with the web search result. |
| `discussions.results[].thumbnail` | object? | The thumbnail of the web search result. |
| `discussions.results[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].age` | string? | A human-readable representation of the web search result's age. For example, `2 days ago`. |
| `discussions.results[].location` | object? | The location details if the query relates to a restaurant. |
| `discussions.results[].location.title` | string | The title of the web page. |
| `discussions.results[].location.url` | string | The URL where the page is served. |
| `discussions.results[].location.is_source_local` | bool? | Whether the result is from a local source. |
| `discussions.results[].location.is_source_both` | bool? | Whether the result is from both local and global sources. |
| `discussions.results[].location.description` | string? | A description for the web page. |
| `discussions.results[].location.page_age` | string? | The page's date, based on its published or last modified date. |
| `discussions.results[].location.page_fetched` | string? | A date representing when the web page was last fetched. |
| `discussions.results[].location.fetched_content_timestamp` | int? | The timestamp when the content was fetched. |
| `discussions.results[].location.profile` | object? | A profile associated with the web page. |
| `discussions.results[].location.profile.name` | string | The name of the profile. |
| `discussions.results[].location.profile.url` | string | The original URL where the profile is available. |
| `discussions.results[].location.profile.long_name` | string? | The long name of the profile. |
| `discussions.results[].location.profile.img` | string? | The served image URL representing the profile. |
| `discussions.results[].location.language` | string? | A language classification for the web page. |
| `discussions.results[].location.family_friendly` | bool? | Whether the web page is family friendly. |
| `discussions.results[].location.type` | string? | Location result type identifier. The value is always `location_result`. |
| `discussions.results[].location.provider_url` | string | The complete URL of the provider. |
| `discussions.results[].location.coordinates` | array? | A list of coordinates associated with the location. This is a lat long represented as a floating point. |
| `discussions.results[].location.zoom_level` | int? | The zoom level on the map. |
| `discussions.results[].location.thumbnail` | object? | The thumbnail associated with the location. |
| `discussions.results[].location.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].location.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].location.thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].location.thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].location.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].location.thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].location.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].location.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].location.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].location.postal_address` | object? | The postal address associated with the location. |
| `discussions.results[].location.postal_address.type` | string? | The type identifying a postal address. The value is always `PostalAddress`. |
| `discussions.results[].location.postal_address.country` | string? | The country associated with the location. |
| `discussions.results[].location.postal_address.postalCode` | string? | The postal code associated with the location. |
| `discussions.results[].location.postal_address.streetAddress` | string? | The street address associated with the location. |
| `discussions.results[].location.postal_address.addressRegion` | string? | The region associated with the location. This is usually a state. |
| `discussions.results[].location.postal_address.addressLocality` | string? | The address locality or subregion associated with the location. |
| `discussions.results[].location.postal_address.displayAddress` | string | The displayed address string. |
| `discussions.results[].location.opening_hours` | object? | The opening hours, if it is a business, associated with the location. |
| `discussions.results[].location.opening_hours.current_day` | object[]? | The current day opening hours. Can have two sets of opening hours. |
| `discussions.results[].location.opening_hours.current_day[].abbr_name` | string | A short string representing the day of the week. |
| `discussions.results[].location.opening_hours.current_day[].full_name` | string | A full string representing the day of the week. |
| `discussions.results[].location.opening_hours.current_day[].opens` | string | A 24 hr clock time string for the opening time of the business on a particular day. |
| `discussions.results[].location.opening_hours.current_day[].closes` | string | A 24 hr clock time string for the closing time of the business on a particular day. |
| `discussions.results[].location.opening_hours.days` | object[][]? | The opening hours for the whole week. |
| `discussions.results[].location.contact` | object? | The contact of the business associated with the location. |
| `discussions.results[].location.contact.email` | string? | The email address. |
| `discussions.results[].location.contact.telephone` | string? | The telephone number. |
| `discussions.results[].location.price_range` | string? | A display string used to show the price classification for the business. |
| `discussions.results[].location.rating` | object? | The ratings of the business. |
| `discussions.results[].location.rating.ratingValue` | number | The current value of the rating. |
| `discussions.results[].location.rating.bestRating` | number | Best rating received. |
| `discussions.results[].location.rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `discussions.results[].location.rating.profile` | object? | The profile associated with the rating. |
| `discussions.results[].location.rating.profile.name` | string | The name of the profile. |
| `discussions.results[].location.rating.profile.url` | string | The original URL where the profile is available. |
| `discussions.results[].location.rating.profile.long_name` | string? | The long name of the profile. |
| `discussions.results[].location.rating.profile.img` | string? | The served image URL representing the profile. |
| `discussions.results[].location.rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `discussions.results[].location.distance` | object? | The distance of the location from the client. |
| `discussions.results[].location.distance.value` | number | The quantity of the unit. |
| `discussions.results[].location.distance.units` | string | The name of the unit associated with the quantity. |
| `discussions.results[].location.profiles` | object[]? | Profiles associated with the business. |
| `discussions.results[].location.profiles[].type` | string? | The type representing the source of data. This is usually `external`. |
| `discussions.results[].location.profiles[].name` | string | The name of the data provider. This can be a domain. |
| `discussions.results[].location.profiles[].url` | string | The URL where the information is coming from. |
| `discussions.results[].location.profiles[].long_name` | string? | The long name for the data provider. |
| `discussions.results[].location.profiles[].img` | string? | The served URL for the image data. |
| `discussions.results[].location.reviews` | object? | Aggregated reviews from various sources relevant to the business. |
| `discussions.results[].location.reviews.results` | object[] | A list of trip advisor reviews for the entity. |
| `discussions.results[].location.reviews.results[].title` | string | The title of the review. |
| `discussions.results[].location.reviews.results[].description` | string | A description seen in the review. |
| `discussions.results[].location.reviews.results[].date` | string | The date when the review was published. |
| `discussions.results[].location.reviews.results[].rating` | object | A rating given by the reviewer. |
| `discussions.results[].location.reviews.results[].rating.ratingValue` | number | The current value of the rating. |
| `discussions.results[].location.reviews.results[].rating.bestRating` | number | Best rating received. |
| `discussions.results[].location.reviews.results[].rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `discussions.results[].location.reviews.results[].rating.profile` | object? | The profile associated with the rating. |
| `discussions.results[].location.reviews.results[].rating.profile.name` | string | The name of the profile. |
| `discussions.results[].location.reviews.results[].rating.profile.url` | string | The original URL where the profile is available. |
| `discussions.results[].location.reviews.results[].rating.profile.long_name` | string? | The long name of the profile. |
| `discussions.results[].location.reviews.results[].rating.profile.img` | string? | The served image URL representing the profile. |
| `discussions.results[].location.reviews.results[].rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `discussions.results[].location.reviews.results[].author` | object | The author of the review. |
| `discussions.results[].location.reviews.results[].author.type` | string? | A type identifying a person. The value is always `person`. |
| `discussions.results[].location.reviews.results[].author.name` | string | The name of the thing. |
| `discussions.results[].location.reviews.results[].author.url` | string? | A URL for the thing. |
| `discussions.results[].location.reviews.results[].author.thumbnail` | object? | Thumbnail associated with the thing. |
| `discussions.results[].location.reviews.results[].author.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].location.reviews.results[].author.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].location.reviews.results[].author.thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].location.reviews.results[].author.thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].location.reviews.results[].author.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].location.reviews.results[].author.thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].location.reviews.results[].author.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].location.reviews.results[].author.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].location.reviews.results[].author.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].location.reviews.results[].author.email` | string? | Email address of the person. |
| `discussions.results[].location.reviews.results[].review_url` | string | A URL link to the page where the review can be found. |
| `discussions.results[].location.reviews.results[].language` | string | The language of the review. |
| `discussions.results[].location.reviews.viewMoreUrl` | string | A URL to a web page where more information on the result can be seen. |
| `discussions.results[].location.reviews.reviews_in_foreign_language` | bool | Any reviews available in a foreign language. |
| `discussions.results[].location.pictures` | object? | A bunch of pictures associated with the business. |
| `discussions.results[].location.pictures.viewMoreUrl` | string? | A URL to view more pictures. |
| `discussions.results[].location.pictures.results` | object[] | A list of thumbnail results. |
| `discussions.results[].location.pictures.results[].src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].location.pictures.results[].alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].location.pictures.results[].height` | int? | The height of the thumbnail. |
| `discussions.results[].location.pictures.results[].width` | int? | The width of the thumbnail. |
| `discussions.results[].location.pictures.results[].bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].location.pictures.results[].original` | string? | The original URL of the image. |
| `discussions.results[].location.pictures.results[].logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].location.pictures.results[].duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].location.pictures.results[].theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].location.action` | object? | An action to be taken. |
| `discussions.results[].location.action.type` | string | The type representing the action. |
| `discussions.results[].location.action.url` | string | A URL representing the action to be taken. |
| `discussions.results[].location.serves_cuisine` | string[]? | A list of cuisine categories served. |
| `discussions.results[].location.categories` | string[]? | A list of categories. |
| `discussions.results[].location.icon_category` | string? | An icon category. |
| `discussions.results[].location.timezone` | string? | IANA timezone identifier. |
| `discussions.results[].location.timezone_offset` | int? | The UTC offset of the timezone. |
| `discussions.results[].location.id` | string? | A temporary id associated with this result, which can be used to retrieve extra information about the location. It remains valid for 8 hours. |
| `discussions.results[].location.results` | object[]? | Web results related to this location. |
| `discussions.results[].location.results[].title` | string | The title of the web page. |
| `discussions.results[].location.results[].url` | string | The URL where the page is served. |
| `discussions.results[].location.results[].is_source_local` | bool? | Whether the result is from a local source. |
| `discussions.results[].location.results[].is_source_both` | bool? | Whether the result is from both local and global sources. |
| `discussions.results[].location.results[].description` | string? | A description for the web page. |
| `discussions.results[].location.results[].page_age` | string? | The page's date, based on its published or last modified date. |
| `discussions.results[].location.results[].page_fetched` | string? | A date representing when the web page was last fetched. |
| `discussions.results[].location.results[].fetched_content_timestamp` | int? | The timestamp when the content was fetched. |
| `discussions.results[].location.results[].profile` | object? | A profile associated with the web page. |
| `discussions.results[].location.results[].profile.name` | string | The name of the profile. |
| `discussions.results[].location.results[].profile.url` | string | The original URL where the profile is available. |
| `discussions.results[].location.results[].profile.long_name` | string? | The long name of the profile. |
| `discussions.results[].location.results[].profile.img` | string? | The served image URL representing the profile. |
| `discussions.results[].location.results[].language` | string? | A language classification for the web page. |
| `discussions.results[].location.results[].family_friendly` | bool? | Whether the web page is family friendly. |
| `discussions.results[].location.results[].meta_url` | object | Aggregated information about the URL. |
| `discussions.results[].location.results[].meta_url.scheme` | string | The protocol scheme extracted from the URL. |
| `discussions.results[].location.results[].meta_url.netloc` | string | The network location part extracted from the URL. |
| `discussions.results[].location.results[].meta_url.hostname` | string? | The lowercased domain name extracted from the URL. |
| `discussions.results[].location.results[].meta_url.favicon` | string | The favicon used for the URL. |
| `discussions.results[].location.results[].meta_url.path` | string | The hierarchical path of the URL useful as a display string. |
| `discussions.results[].restaurant` | object? | Deprecated. Use `location` instead. |
| `discussions.results[].restaurant.title` | string | The title of the web page. |
| `discussions.results[].restaurant.url` | string | The URL where the page is served. |
| `discussions.results[].restaurant.is_source_local` | bool? | Whether the result is from a local source. |
| `discussions.results[].restaurant.is_source_both` | bool? | Whether the result is from both local and global sources. |
| `discussions.results[].restaurant.description` | string? | A description for the web page. |
| `discussions.results[].restaurant.page_age` | string? | The page's date, based on its published or last modified date. |
| `discussions.results[].restaurant.page_fetched` | string? | A date representing when the web page was last fetched. |
| `discussions.results[].restaurant.fetched_content_timestamp` | int? | The timestamp when the content was fetched. |
| `discussions.results[].restaurant.profile` | object? | A profile associated with the web page. |
| `discussions.results[].restaurant.profile.name` | string | The name of the profile. |
| `discussions.results[].restaurant.profile.url` | string | The original URL where the profile is available. |
| `discussions.results[].restaurant.profile.long_name` | string? | The long name of the profile. |
| `discussions.results[].restaurant.profile.img` | string? | The served image URL representing the profile. |
| `discussions.results[].restaurant.language` | string? | A language classification for the web page. |
| `discussions.results[].restaurant.family_friendly` | bool? | Whether the web page is family friendly. |
| `discussions.results[].restaurant.type` | string? | Location result type identifier. The value is always `location_result`. |
| `discussions.results[].restaurant.provider_url` | string | The complete URL of the provider. |
| `discussions.results[].restaurant.coordinates` | array? | A list of coordinates associated with the location. This is a lat long represented as a floating point. |
| `discussions.results[].restaurant.zoom_level` | int? | The zoom level on the map. |
| `discussions.results[].restaurant.thumbnail` | object? | The thumbnail associated with the location. |
| `discussions.results[].restaurant.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].restaurant.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].restaurant.thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].restaurant.thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].restaurant.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].restaurant.thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].restaurant.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].restaurant.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].restaurant.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].restaurant.postal_address` | object? | The postal address associated with the location. |
| `discussions.results[].restaurant.postal_address.type` | string? | The type identifying a postal address. The value is always `PostalAddress`. |
| `discussions.results[].restaurant.postal_address.country` | string? | The country associated with the location. |
| `discussions.results[].restaurant.postal_address.postalCode` | string? | The postal code associated with the location. |
| `discussions.results[].restaurant.postal_address.streetAddress` | string? | The street address associated with the location. |
| `discussions.results[].restaurant.postal_address.addressRegion` | string? | The region associated with the location. This is usually a state. |
| `discussions.results[].restaurant.postal_address.addressLocality` | string? | The address locality or subregion associated with the location. |
| `discussions.results[].restaurant.postal_address.displayAddress` | string | The displayed address string. |
| `discussions.results[].restaurant.opening_hours` | object? | The opening hours, if it is a business, associated with the location. |
| `discussions.results[].restaurant.opening_hours.current_day` | object[]? | The current day opening hours. Can have two sets of opening hours. |
| `discussions.results[].restaurant.opening_hours.current_day[].abbr_name` | string | A short string representing the day of the week. |
| `discussions.results[].restaurant.opening_hours.current_day[].full_name` | string | A full string representing the day of the week. |
| `discussions.results[].restaurant.opening_hours.current_day[].opens` | string | A 24 hr clock time string for the opening time of the business on a particular day. |
| `discussions.results[].restaurant.opening_hours.current_day[].closes` | string | A 24 hr clock time string for the closing time of the business on a particular day. |
| `discussions.results[].restaurant.opening_hours.days` | object[][]? | The opening hours for the whole week. |
| `discussions.results[].restaurant.contact` | object? | The contact of the business associated with the location. |
| `discussions.results[].restaurant.contact.email` | string? | The email address. |
| `discussions.results[].restaurant.contact.telephone` | string? | The telephone number. |
| `discussions.results[].restaurant.price_range` | string? | A display string used to show the price classification for the business. |
| `discussions.results[].restaurant.rating` | object? | The ratings of the business. |
| `discussions.results[].restaurant.rating.ratingValue` | number | The current value of the rating. |
| `discussions.results[].restaurant.rating.bestRating` | number | Best rating received. |
| `discussions.results[].restaurant.rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `discussions.results[].restaurant.rating.profile` | object? | The profile associated with the rating. |
| `discussions.results[].restaurant.rating.profile.name` | string | The name of the profile. |
| `discussions.results[].restaurant.rating.profile.url` | string | The original URL where the profile is available. |
| `discussions.results[].restaurant.rating.profile.long_name` | string? | The long name of the profile. |
| `discussions.results[].restaurant.rating.profile.img` | string? | The served image URL representing the profile. |
| `discussions.results[].restaurant.rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `discussions.results[].restaurant.distance` | object? | The distance of the location from the client. |
| `discussions.results[].restaurant.distance.value` | number | The quantity of the unit. |
| `discussions.results[].restaurant.distance.units` | string | The name of the unit associated with the quantity. |
| `discussions.results[].restaurant.profiles` | object[]? | Profiles associated with the business. |
| `discussions.results[].restaurant.profiles[].type` | string? | The type representing the source of data. This is usually `external`. |
| `discussions.results[].restaurant.profiles[].name` | string | The name of the data provider. This can be a domain. |
| `discussions.results[].restaurant.profiles[].url` | string | The URL where the information is coming from. |
| `discussions.results[].restaurant.profiles[].long_name` | string? | The long name for the data provider. |
| `discussions.results[].restaurant.profiles[].img` | string? | The served URL for the image data. |
| `discussions.results[].restaurant.reviews` | object? | Aggregated reviews from various sources relevant to the business. |
| `discussions.results[].restaurant.reviews.results` | object[] | A list of trip advisor reviews for the entity. |
| `discussions.results[].restaurant.reviews.results[].title` | string | The title of the review. |
| `discussions.results[].restaurant.reviews.results[].description` | string | A description seen in the review. |
| `discussions.results[].restaurant.reviews.results[].date` | string | The date when the review was published. |
| `discussions.results[].restaurant.reviews.results[].rating` | object | A rating given by the reviewer. |
| `discussions.results[].restaurant.reviews.results[].rating.ratingValue` | number | The current value of the rating. |
| `discussions.results[].restaurant.reviews.results[].rating.bestRating` | number | Best rating received. |
| `discussions.results[].restaurant.reviews.results[].rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `discussions.results[].restaurant.reviews.results[].rating.profile` | object? | The profile associated with the rating. |
| `discussions.results[].restaurant.reviews.results[].rating.profile.name` | string | The name of the profile. |
| `discussions.results[].restaurant.reviews.results[].rating.profile.url` | string | The original URL where the profile is available. |
| `discussions.results[].restaurant.reviews.results[].rating.profile.long_name` | string? | The long name of the profile. |
| `discussions.results[].restaurant.reviews.results[].rating.profile.img` | string? | The served image URL representing the profile. |
| `discussions.results[].restaurant.reviews.results[].rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `discussions.results[].restaurant.reviews.results[].author` | object | The author of the review. |
| `discussions.results[].restaurant.reviews.results[].author.type` | string? | A type identifying a person. The value is always `person`. |
| `discussions.results[].restaurant.reviews.results[].author.name` | string | The name of the thing. |
| `discussions.results[].restaurant.reviews.results[].author.url` | string? | A URL for the thing. |
| `discussions.results[].restaurant.reviews.results[].author.thumbnail` | object? | Thumbnail associated with the thing. |
| `discussions.results[].restaurant.reviews.results[].author.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].restaurant.reviews.results[].author.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].restaurant.reviews.results[].author.thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].restaurant.reviews.results[].author.thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].restaurant.reviews.results[].author.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].restaurant.reviews.results[].author.thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].restaurant.reviews.results[].author.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].restaurant.reviews.results[].author.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].restaurant.reviews.results[].author.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].restaurant.reviews.results[].author.email` | string? | Email address of the person. |
| `discussions.results[].restaurant.reviews.results[].review_url` | string | A URL link to the page where the review can be found. |
| `discussions.results[].restaurant.reviews.results[].language` | string | The language of the review. |
| `discussions.results[].restaurant.reviews.viewMoreUrl` | string | A URL to a web page where more information on the result can be seen. |
| `discussions.results[].restaurant.reviews.reviews_in_foreign_language` | bool | Any reviews available in a foreign language. |
| `discussions.results[].restaurant.pictures` | object? | A bunch of pictures associated with the business. |
| `discussions.results[].restaurant.pictures.viewMoreUrl` | string? | A URL to view more pictures. |
| `discussions.results[].restaurant.pictures.results` | object[] | A list of thumbnail results. |
| `discussions.results[].restaurant.pictures.results[].src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].restaurant.pictures.results[].alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].restaurant.pictures.results[].height` | int? | The height of the thumbnail. |
| `discussions.results[].restaurant.pictures.results[].width` | int? | The width of the thumbnail. |
| `discussions.results[].restaurant.pictures.results[].bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].restaurant.pictures.results[].original` | string? | The original URL of the image. |
| `discussions.results[].restaurant.pictures.results[].logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].restaurant.pictures.results[].duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].restaurant.pictures.results[].theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].restaurant.action` | object? | An action to be taken. |
| `discussions.results[].restaurant.action.type` | string | The type representing the action. |
| `discussions.results[].restaurant.action.url` | string | A URL representing the action to be taken. |
| `discussions.results[].restaurant.serves_cuisine` | string[]? | A list of cuisine categories served. |
| `discussions.results[].restaurant.categories` | string[]? | A list of categories. |
| `discussions.results[].restaurant.icon_category` | string? | An icon category. |
| `discussions.results[].restaurant.timezone` | string? | IANA timezone identifier. |
| `discussions.results[].restaurant.timezone_offset` | int? | The UTC offset of the timezone. |
| `discussions.results[].restaurant.id` | string? | A temporary id associated with this result, which can be used to retrieve extra information about the location. It remains valid for 8 hours. |
| `discussions.results[].restaurant.results` | object[]? | Web results related to this location. |
| `discussions.results[].restaurant.results[].title` | string | The title of the web page. |
| `discussions.results[].restaurant.results[].url` | string | The URL where the page is served. |
| `discussions.results[].restaurant.results[].is_source_local` | bool? | Whether the result is from a local source. |
| `discussions.results[].restaurant.results[].is_source_both` | bool? | Whether the result is from both local and global sources. |
| `discussions.results[].restaurant.results[].description` | string? | A description for the web page. |
| `discussions.results[].restaurant.results[].page_age` | string? | The page's date, based on its published or last modified date. |
| `discussions.results[].restaurant.results[].page_fetched` | string? | A date representing when the web page was last fetched. |
| `discussions.results[].restaurant.results[].fetched_content_timestamp` | int? | The timestamp when the content was fetched. |
| `discussions.results[].restaurant.results[].profile` | object? | A profile associated with the web page. |
| `discussions.results[].restaurant.results[].profile.name` | string | The name of the profile. |
| `discussions.results[].restaurant.results[].profile.url` | string | The original URL where the profile is available. |
| `discussions.results[].restaurant.results[].profile.long_name` | string? | The long name of the profile. |
| `discussions.results[].restaurant.results[].profile.img` | string? | The served image URL representing the profile. |
| `discussions.results[].restaurant.results[].language` | string? | A language classification for the web page. |
| `discussions.results[].restaurant.results[].family_friendly` | bool? | Whether the web page is family friendly. |
| `discussions.results[].restaurant.results[].meta_url` | object | Aggregated information about the URL. |
| `discussions.results[].restaurant.results[].meta_url.scheme` | string | The protocol scheme extracted from the URL. |
| `discussions.results[].restaurant.results[].meta_url.netloc` | string | The network location part extracted from the URL. |
| `discussions.results[].restaurant.results[].meta_url.hostname` | string? | The lowercased domain name extracted from the URL. |
| `discussions.results[].restaurant.results[].meta_url.favicon` | string | The favicon used for the URL. |
| `discussions.results[].restaurant.results[].meta_url.path` | string | The hierarchical path of the URL useful as a display string. |
| `discussions.results[].video` | object? | The video associated with the web search result. |
| `discussions.results[].video.duration` | string? | A time string representing the duration of the video. The format can be HH:MM:SS or MM:SS. |
| `discussions.results[].video.views` | string? | The number of views of the video. |
| `discussions.results[].video.creator` | string? | The creator of the video. |
| `discussions.results[].video.publisher` | string? | The publisher of the video. |
| `discussions.results[].video.thumbnail` | object? | A thumbnail associated with the video. |
| `discussions.results[].video.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].video.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].video.thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].video.thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].video.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].video.thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].video.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].video.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].video.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].video.tags` | string[]? | A list of tags associated with the video. |
| `discussions.results[].video.author` | object? | Author of the video. |
| `discussions.results[].video.author.name` | string | The name of the profile. |
| `discussions.results[].video.author.url` | string | The original URL where the profile is available. |
| `discussions.results[].video.author.long_name` | string? | The long name of the profile. |
| `discussions.results[].video.author.img` | string? | The served image URL representing the profile. |
| `discussions.results[].video.requires_subscription` | bool? | Whether the video requires a subscription to watch. |
| `discussions.results[].movie` | object? | The movie associated with the web search result. |
| `discussions.results[].movie.name` | string? | Name of the movie. |
| `discussions.results[].movie.description` | string? | A short plot summary for the movie. |
| `discussions.results[].movie.url` | string? | A URL serving a movie profile page. |
| `discussions.results[].movie.thumbnail` | object? | A thumbnail for a movie poster. |
| `discussions.results[].movie.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].movie.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].movie.thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].movie.thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].movie.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].movie.thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].movie.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].movie.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].movie.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].movie.release` | string? | The release date for the movie. |
| `discussions.results[].movie.directors` | object[]? | A list of people responsible for directing the movie. |
| `discussions.results[].movie.directors[].type` | string? | A type identifying a person. The value is always `person`. |
| `discussions.results[].movie.directors[].name` | string | The name of the thing. |
| `discussions.results[].movie.directors[].url` | string? | A URL for the thing. |
| `discussions.results[].movie.directors[].thumbnail` | object? | Thumbnail associated with the thing. |
| `discussions.results[].movie.directors[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].movie.directors[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].movie.directors[].thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].movie.directors[].thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].movie.directors[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].movie.directors[].thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].movie.directors[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].movie.directors[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].movie.directors[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].movie.directors[].email` | string? | Email address of the person. |
| `discussions.results[].movie.actors` | object[]? | A list of actors in the movie. |
| `discussions.results[].movie.actors[].type` | string? | A type identifying a person. The value is always `person`. |
| `discussions.results[].movie.actors[].name` | string | The name of the thing. |
| `discussions.results[].movie.actors[].url` | string? | A URL for the thing. |
| `discussions.results[].movie.actors[].thumbnail` | object? | Thumbnail associated with the thing. |
| `discussions.results[].movie.actors[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].movie.actors[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].movie.actors[].thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].movie.actors[].thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].movie.actors[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].movie.actors[].thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].movie.actors[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].movie.actors[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].movie.actors[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].movie.actors[].email` | string? | Email address of the person. |
| `discussions.results[].movie.rating` | object? | Rating provided to the movie from various sources. |
| `discussions.results[].movie.rating.ratingValue` | number | The current value of the rating. |
| `discussions.results[].movie.rating.bestRating` | number | Best rating received. |
| `discussions.results[].movie.rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `discussions.results[].movie.rating.profile` | object? | The profile associated with the rating. |
| `discussions.results[].movie.rating.profile.name` | string | The name of the profile. |
| `discussions.results[].movie.rating.profile.url` | string | The original URL where the profile is available. |
| `discussions.results[].movie.rating.profile.long_name` | string? | The long name of the profile. |
| `discussions.results[].movie.rating.profile.img` | string? | The served image URL representing the profile. |
| `discussions.results[].movie.rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `discussions.results[].movie.duration` | string? | The runtime of the movie. The format is HH:MM:SS. |
| `discussions.results[].movie.genre` | string[]? | List of genres in which the movie can be classified. |
| `discussions.results[].movie.query` | string? | The query that resulted in the movie result. |
| `discussions.results[].faq` | object? | Any frequently asked questions associated with the web search result. |
| `discussions.results[].faq.items` | object[] | A list of question/answer pairs. |
| `discussions.results[].faq.items[].question` | string | The question being asked. |
| `discussions.results[].faq.items[].answer` | string | The answer to the question. |
| `discussions.results[].faq.items[].title` | string | The title of the post. |
| `discussions.results[].faq.items[].url` | string | The URL pointing to the post. |
| `discussions.results[].faq.items[].meta_url` | object? | Aggregated information about the URL. |
| `discussions.results[].faq.items[].meta_url.scheme` | string | The protocol scheme extracted from the URL. |
| `discussions.results[].faq.items[].meta_url.netloc` | string | The network location part extracted from the URL. |
| `discussions.results[].faq.items[].meta_url.hostname` | string? | The lowercased domain name extracted from the URL. |
| `discussions.results[].faq.items[].meta_url.favicon` | string | The favicon used for the URL. |
| `discussions.results[].faq.items[].meta_url.path` | string | The hierarchical path of the URL useful as a display string. |
| `discussions.results[].qa` | object? | Any question answer information associated with the web search result page. |
| `discussions.results[].qa.question` | string | The question that is being asked. |
| `discussions.results[].qa.answer` | object | An answer to the question. |
| `discussions.results[].qa.answer.text` | string | The main content of the answer. |
| `discussions.results[].qa.answer.author` | string? | The name of the author of the answer. |
| `discussions.results[].qa.answer.upvoteCount` | int? | Number of upvotes on the answer. |
| `discussions.results[].qa.answer.downvoteCount` | int? | The number of downvotes on the answer. |
| `discussions.results[].book` | object? | Any book information associated with the web search result page. |
| `discussions.results[].book.title` | string | The title of the book. |
| `discussions.results[].book.author` | object[] | The author of the book. |
| `discussions.results[].book.author[].type` | string? | A type identifying a person. The value is always `person`. |
| `discussions.results[].book.author[].name` | string | The name of the thing. |
| `discussions.results[].book.author[].url` | string? | A URL for the thing. |
| `discussions.results[].book.author[].thumbnail` | object? | Thumbnail associated with the thing. |
| `discussions.results[].book.author[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].book.author[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].book.author[].thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].book.author[].thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].book.author[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].book.author[].thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].book.author[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].book.author[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].book.author[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].book.author[].email` | string? | Email address of the person. |
| `discussions.results[].book.date` | string? | The publishing date of the book. |
| `discussions.results[].book.price` | object? | The price of the book. |
| `discussions.results[].book.price.price` | string | The price value in a given currency. |
| `discussions.results[].book.price.priceCurrency` | string | The currency of the price value. |
| `discussions.results[].book.pages` | int? | The number of pages in the book. |
| `discussions.results[].book.publisher` | object? | The publisher of the book. |
| `discussions.results[].book.publisher.type` | string? | A type identifying a person. The value is always `person`. |
| `discussions.results[].book.publisher.name` | string | The name of the thing. |
| `discussions.results[].book.publisher.url` | string? | A URL for the thing. |
| `discussions.results[].book.publisher.thumbnail` | object? | Thumbnail associated with the thing. |
| `discussions.results[].book.publisher.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].book.publisher.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].book.publisher.thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].book.publisher.thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].book.publisher.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].book.publisher.thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].book.publisher.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].book.publisher.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].book.publisher.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].book.publisher.email` | string? | Email address of the person. |
| `discussions.results[].book.rating` | object? | A gathered rating from different sources associated with the book. |
| `discussions.results[].book.rating.ratingValue` | number | The current value of the rating. |
| `discussions.results[].book.rating.bestRating` | number | Best rating received. |
| `discussions.results[].book.rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `discussions.results[].book.rating.profile` | object? | The profile associated with the rating. |
| `discussions.results[].book.rating.profile.name` | string | The name of the profile. |
| `discussions.results[].book.rating.profile.url` | string | The original URL where the profile is available. |
| `discussions.results[].book.rating.profile.long_name` | string? | The long name of the profile. |
| `discussions.results[].book.rating.profile.img` | string? | The served image URL representing the profile. |
| `discussions.results[].book.rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `discussions.results[].rating` | object? | Rating found for the web search result page. |
| `discussions.results[].rating.ratingValue` | number | The current value of the rating. |
| `discussions.results[].rating.bestRating` | number | Best rating received. |
| `discussions.results[].rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `discussions.results[].rating.profile` | object? | The profile associated with the rating. |
| `discussions.results[].rating.profile.name` | string | The name of the profile. |
| `discussions.results[].rating.profile.url` | string | The original URL where the profile is available. |
| `discussions.results[].rating.profile.long_name` | string? | The long name of the profile. |
| `discussions.results[].rating.profile.img` | string? | The served image URL representing the profile. |
| `discussions.results[].rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `discussions.results[].article` | object? | An article found for the web search result page. |
| `discussions.results[].article.author` | object[]? | The author of the article. |
| `discussions.results[].article.author[].type` | string? | A type identifying a person. The value is always `person`. |
| `discussions.results[].article.author[].name` | string | The name of the thing. |
| `discussions.results[].article.author[].url` | string? | A URL for the thing. |
| `discussions.results[].article.author[].thumbnail` | object? | Thumbnail associated with the thing. |
| `discussions.results[].article.author[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].article.author[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].article.author[].thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].article.author[].thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].article.author[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].article.author[].thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].article.author[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].article.author[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].article.author[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].article.author[].email` | string? | Email address of the person. |
| `discussions.results[].article.date` | string? | The date when the article was published. |
| `discussions.results[].article.publisher` | object? | The name of the publisher for the article. |
| `discussions.results[].article.publisher.type` | string? | A type string identifying an organization. The value is always `organization`. |
| `discussions.results[].article.publisher.name` | string | The name of the thing. |
| `discussions.results[].article.publisher.url` | string? | A URL for the thing. |
| `discussions.results[].article.publisher.thumbnail` | object? | Thumbnail associated with the thing. |
| `discussions.results[].article.publisher.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].article.publisher.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].article.publisher.thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].article.publisher.thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].article.publisher.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].article.publisher.thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].article.publisher.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].article.publisher.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].article.publisher.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].article.publisher.contact_points` | object[]? | A list of contact points for the organization. |
| `discussions.results[].article.publisher.contact_points[].type` | string? | A type string identifying a contact point. The value is always `contact_point`. |
| `discussions.results[].article.publisher.contact_points[].name` | string | The name of the thing. |
| `discussions.results[].article.publisher.contact_points[].url` | string? | A URL for the thing. |
| `discussions.results[].article.publisher.contact_points[].thumbnail` | object? | Thumbnail associated with the thing. |
| `discussions.results[].article.publisher.contact_points[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].article.publisher.contact_points[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].article.publisher.contact_points[].thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].article.publisher.contact_points[].thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].article.publisher.contact_points[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].article.publisher.contact_points[].thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].article.publisher.contact_points[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].article.publisher.contact_points[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].article.publisher.contact_points[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].article.publisher.contact_points[].telephone` | string? | The telephone number of the entity. |
| `discussions.results[].article.publisher.contact_points[].email` | string? | The email address of the entity. |
| `discussions.results[].article.thumbnail` | object? | A thumbnail associated with the article. |
| `discussions.results[].article.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].article.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].article.thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].article.thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].article.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].article.thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].article.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].article.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].article.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].article.isAccessibleForFree` | bool? | Whether the article is free to read or is behind a paywall. |
| `discussions.results[].product` | any? | The main product and a review that is found on the web search result page. |
| `discussions.results[].product.type` | string? | A string representing a product type. The value is always `Product`. |
| `discussions.results[].product.name` | string | The name of the product. |
| `discussions.results[].product.url` | string? | The URL of the product page. |
| `discussions.results[].product.category` | string? | The category of the product. |
| `discussions.results[].product.price` | string | The price of the product. |
| `discussions.results[].product.thumbnail` | object | A thumbnail associated with the product. |
| `discussions.results[].product.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].product.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].product.thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].product.thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].product.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].product.thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].product.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].product.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].product.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].product.description` | string? | The description of the product. |
| `discussions.results[].product.offers` | object[]? | A list of offers available on the product. |
| `discussions.results[].product.offers[].url` | string | The URL where the offer can be found. |
| `discussions.results[].product.offers[].priceCurrency` | string | The currency in which the offer is made. |
| `discussions.results[].product.offers[].price` | string | The price of the product currently on offer. |
| `discussions.results[].product.rating` | object? | A rating associated with the product. |
| `discussions.results[].product.rating.ratingValue` | number | The current value of the rating. |
| `discussions.results[].product.rating.bestRating` | number | Best rating received. |
| `discussions.results[].product.rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `discussions.results[].product.rating.profile` | object? | The profile associated with the rating. |
| `discussions.results[].product.rating.profile.name` | string | The name of the profile. |
| `discussions.results[].product.rating.profile.url` | string | The original URL where the profile is available. |
| `discussions.results[].product.rating.profile.long_name` | string? | The long name of the profile. |
| `discussions.results[].product.rating.profile.img` | string? | The served image URL representing the profile. |
| `discussions.results[].product.rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `discussions.results[].product.gtin` | string? | A Global Trade Item Number (GTIN) for the product. |
| `discussions.results[].product.gtin8` | string? | The GTIN-8 (EAN/UCC-8) code of the product. |
| `discussions.results[].product.gtin12` | string? | The GTIN-12 (UPC) code of the product. |
| `discussions.results[].product.gtin13` | string? | The GTIN-13 (EAN/ISBN-13) code of the product. |
| `discussions.results[].product.gtin14` | string? | The GTIN-14 code of the product. |
| `discussions.results[].product_cluster` | any[]? | A list of products and reviews that are found on the web search result page. |
| `discussions.results[].product_cluster[].type` | string? | A string representing a product type. The value is always `Product`. |
| `discussions.results[].product_cluster[].name` | string | The name of the product. |
| `discussions.results[].product_cluster[].url` | string? | The URL of the product page. |
| `discussions.results[].product_cluster[].category` | string? | The category of the product. |
| `discussions.results[].product_cluster[].price` | string | The price of the product. |
| `discussions.results[].product_cluster[].thumbnail` | object | A thumbnail associated with the product. |
| `discussions.results[].product_cluster[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].product_cluster[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].product_cluster[].thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].product_cluster[].thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].product_cluster[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].product_cluster[].thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].product_cluster[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].product_cluster[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].product_cluster[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].product_cluster[].description` | string? | The description of the product. |
| `discussions.results[].product_cluster[].offers` | object[]? | A list of offers available on the product. |
| `discussions.results[].product_cluster[].offers[].url` | string | The URL where the offer can be found. |
| `discussions.results[].product_cluster[].offers[].priceCurrency` | string | The currency in which the offer is made. |
| `discussions.results[].product_cluster[].offers[].price` | string | The price of the product currently on offer. |
| `discussions.results[].product_cluster[].rating` | object? | A rating associated with the product. |
| `discussions.results[].product_cluster[].rating.ratingValue` | number | The current value of the rating. |
| `discussions.results[].product_cluster[].rating.bestRating` | number | Best rating received. |
| `discussions.results[].product_cluster[].rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `discussions.results[].product_cluster[].rating.profile` | object? | The profile associated with the rating. |
| `discussions.results[].product_cluster[].rating.profile.name` | string | The name of the profile. |
| `discussions.results[].product_cluster[].rating.profile.url` | string | The original URL where the profile is available. |
| `discussions.results[].product_cluster[].rating.profile.long_name` | string? | The long name of the profile. |
| `discussions.results[].product_cluster[].rating.profile.img` | string? | The served image URL representing the profile. |
| `discussions.results[].product_cluster[].rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `discussions.results[].product_cluster[].gtin` | string? | A Global Trade Item Number (GTIN) for the product. |
| `discussions.results[].product_cluster[].gtin8` | string? | The GTIN-8 (EAN/UCC-8) code of the product. |
| `discussions.results[].product_cluster[].gtin12` | string? | The GTIN-12 (UPC) code of the product. |
| `discussions.results[].product_cluster[].gtin13` | string? | The GTIN-13 (EAN/ISBN-13) code of the product. |
| `discussions.results[].product_cluster[].gtin14` | string? | The GTIN-14 code of the product. |
| `discussions.results[].cluster_type` | string? | A type representing a cluster. The value can be product_cluster. |
| `discussions.results[].cluster` | object[]? | A list of web search results. |
| `discussions.results[].cluster[].title` | string | The title of the web page. |
| `discussions.results[].cluster[].url` | string | The URL where the page is served. |
| `discussions.results[].cluster[].is_source_local` | bool? | Whether the result is from a local source. |
| `discussions.results[].cluster[].is_source_both` | bool? | Whether the result is from both local and global sources. |
| `discussions.results[].cluster[].description` | string? | A description for the web page. |
| `discussions.results[].cluster[].page_age` | string? | The page's date, based on its published or last modified date. |
| `discussions.results[].cluster[].page_fetched` | string? | A date representing when the web page was last fetched. |
| `discussions.results[].cluster[].fetched_content_timestamp` | int? | The timestamp when the content was fetched. |
| `discussions.results[].cluster[].profile` | object? | A profile associated with the web page. |
| `discussions.results[].cluster[].profile.name` | string | The name of the profile. |
| `discussions.results[].cluster[].profile.url` | string | The original URL where the profile is available. |
| `discussions.results[].cluster[].profile.long_name` | string? | The long name of the profile. |
| `discussions.results[].cluster[].profile.img` | string? | The served image URL representing the profile. |
| `discussions.results[].cluster[].language` | string? | A language classification for the web page. |
| `discussions.results[].cluster[].family_friendly` | bool? | Whether the web page is family friendly. |
| `discussions.results[].creative_work` | object? | Aggregated information on the creative work found on the web search result. |
| `discussions.results[].creative_work.name` | string | The name of the creative work. |
| `discussions.results[].creative_work.rating` | object? | A rating that is given to the creative work. |
| `discussions.results[].creative_work.rating.ratingValue` | number | The current value of the rating. |
| `discussions.results[].creative_work.rating.bestRating` | number | Best rating received. |
| `discussions.results[].creative_work.rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `discussions.results[].creative_work.rating.profile` | object? | The profile associated with the rating. |
| `discussions.results[].creative_work.rating.profile.name` | string | The name of the profile. |
| `discussions.results[].creative_work.rating.profile.url` | string | The original URL where the profile is available. |
| `discussions.results[].creative_work.rating.profile.long_name` | string? | The long name of the profile. |
| `discussions.results[].creative_work.rating.profile.img` | string? | The served image URL representing the profile. |
| `discussions.results[].creative_work.rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `discussions.results[].creative_work.thumbnail` | object | A thumbnail associated with the creative work. |
| `discussions.results[].creative_work.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].creative_work.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].creative_work.thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].creative_work.thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].creative_work.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].creative_work.thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].creative_work.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].creative_work.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].creative_work.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].music_recording` | object? | Aggregated information on music recording found on the web search result. |
| `discussions.results[].music_recording.name` | string | The name of the song or album. |
| `discussions.results[].music_recording.rating` | object? | The rating of the music. |
| `discussions.results[].music_recording.rating.ratingValue` | number | The current value of the rating. |
| `discussions.results[].music_recording.rating.bestRating` | number | Best rating received. |
| `discussions.results[].music_recording.rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `discussions.results[].music_recording.rating.profile` | object? | The profile associated with the rating. |
| `discussions.results[].music_recording.rating.profile.name` | string | The name of the profile. |
| `discussions.results[].music_recording.rating.profile.url` | string | The original URL where the profile is available. |
| `discussions.results[].music_recording.rating.profile.long_name` | string? | The long name of the profile. |
| `discussions.results[].music_recording.rating.profile.img` | string? | The served image URL representing the profile. |
| `discussions.results[].music_recording.rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `discussions.results[].music_recording.thumbnail` | object? | A thumbnail associated with the music. |
| `discussions.results[].music_recording.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].music_recording.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].music_recording.thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].music_recording.thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].music_recording.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].music_recording.thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].music_recording.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].music_recording.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].music_recording.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].review` | object? | Aggregated information on the review found on the web search result. |
| `discussions.results[].review.type` | string? | A string representing review type. This is always `Review`. |
| `discussions.results[].review.name` | string | The review title for the review. |
| `discussions.results[].review.thumbnail` | object | The thumbnail associated with the reviewer. |
| `discussions.results[].review.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].review.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].review.thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].review.thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].review.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].review.thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].review.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].review.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].review.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].review.description` | string | A description of the review (the text of the review itself). |
| `discussions.results[].review.rating` | object | The ratings associated with the review. |
| `discussions.results[].review.rating.ratingValue` | number | The current value of the rating. |
| `discussions.results[].review.rating.bestRating` | number | Best rating received. |
| `discussions.results[].review.rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `discussions.results[].review.rating.profile` | object? | The profile associated with the rating. |
| `discussions.results[].review.rating.profile.name` | string | The name of the profile. |
| `discussions.results[].review.rating.profile.url` | string | The original URL where the profile is available. |
| `discussions.results[].review.rating.profile.long_name` | string? | The long name of the profile. |
| `discussions.results[].review.rating.profile.img` | string? | The served image URL representing the profile. |
| `discussions.results[].review.rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `discussions.results[].recipe` | object? | Aggregated information on a recipe found on the web search result page. |
| `discussions.results[].recipe.title` | string | The title of the recipe. |
| `discussions.results[].recipe.description` | string | The description of the recipe. |
| `discussions.results[].recipe.thumbnail` | object | A thumbnail associated with the recipe. |
| `discussions.results[].recipe.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].recipe.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].recipe.thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].recipe.thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].recipe.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].recipe.thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].recipe.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].recipe.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].recipe.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].recipe.url` | string | The URL of the web page where the recipe was found. |
| `discussions.results[].recipe.domain` | string | The domain of the web page where the recipe was found. |
| `discussions.results[].recipe.favicon` | string | The URL for the favicon of the web page where the recipe was found. |
| `discussions.results[].recipe.time` | string? | The total time required to cook the recipe. |
| `discussions.results[].recipe.prep_time` | string? | The preparation time for the recipe. |
| `discussions.results[].recipe.cook_time` | string? | The cooking time for the recipe. |
| `discussions.results[].recipe.ingredients` | string? | Ingredients required for the recipe. |
| `discussions.results[].recipe.instructions` | object[]? | List of instructions for the recipe. |
| `discussions.results[].recipe.instructions[].text` | string | The how to text. |
| `discussions.results[].recipe.instructions[].name` | string? | A name for the how to. |
| `discussions.results[].recipe.instructions[].url` | string? | A URL associated with the how to. |
| `discussions.results[].recipe.instructions[].image` | string[]? | A list of image URLs associated with the how to. |
| `discussions.results[].recipe.servings` | int? | How many people the recipe serves. |
| `discussions.results[].recipe.calories` | int? | Calorie count for the recipe. |
| `discussions.results[].recipe.publisher` | string? | The publisher of the recipe. |
| `discussions.results[].recipe.rating` | object? | Aggregated information on the ratings associated with the recipe. |
| `discussions.results[].recipe.rating.ratingValue` | number | The current value of the rating. |
| `discussions.results[].recipe.rating.bestRating` | number | Best rating received. |
| `discussions.results[].recipe.rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `discussions.results[].recipe.rating.profile` | object? | The profile associated with the rating. |
| `discussions.results[].recipe.rating.profile.name` | string | The name of the profile. |
| `discussions.results[].recipe.rating.profile.url` | string | The original URL where the profile is available. |
| `discussions.results[].recipe.rating.profile.long_name` | string? | The long name of the profile. |
| `discussions.results[].recipe.rating.profile.img` | string? | The served image URL representing the profile. |
| `discussions.results[].recipe.rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `discussions.results[].recipe.recipeCategory` | string? | The category of the recipe. |
| `discussions.results[].recipe.recipeCuisine` | string? | The cuisine classification for the recipe. |
| `discussions.results[].recipe.video` | object? | Aggregated information on the cooking video associated with the recipe. |
| `discussions.results[].recipe.video.duration` | string? | A time string representing the duration of the video. The format can be HH:MM:SS or MM:SS. |
| `discussions.results[].recipe.video.views` | string? | The number of views of the video. |
| `discussions.results[].recipe.video.creator` | string? | The creator of the video. |
| `discussions.results[].recipe.video.publisher` | string? | The publisher of the video. |
| `discussions.results[].recipe.video.thumbnail` | object? | A thumbnail associated with the video. |
| `discussions.results[].recipe.video.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].recipe.video.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].recipe.video.thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].recipe.video.thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].recipe.video.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].recipe.video.thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].recipe.video.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].recipe.video.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].recipe.video.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].recipe.video.tags` | string[]? | A list of tags associated with the video. |
| `discussions.results[].recipe.video.author` | object? | Author of the video. |
| `discussions.results[].recipe.video.author.name` | string | The name of the profile. |
| `discussions.results[].recipe.video.author.url` | string | The original URL where the profile is available. |
| `discussions.results[].recipe.video.author.long_name` | string? | The long name of the profile. |
| `discussions.results[].recipe.video.author.img` | string? | The served image URL representing the profile. |
| `discussions.results[].recipe.video.requires_subscription` | bool? | Whether the video requires a subscription to watch. |
| `discussions.results[].software` | object? | Aggregated information on a software product found on the web search result page. |
| `discussions.results[].software.name` | string? | The name of the software product. |
| `discussions.results[].software.author` | string? | The author of software product. |
| `discussions.results[].software.version` | string? | The latest version of the software product. |
| `discussions.results[].software.codeRepository` | string? | The code repository where the software product is currently available or maintained. |
| `discussions.results[].software.homepage` | string? | The home page of the software product. |
| `discussions.results[].software.datePublished` | string? | The date when the software product was published. |
| `discussions.results[].software.is_npm` | bool? | Whether the software product is available on npm. |
| `discussions.results[].software.is_pypi` | bool? | Whether the software product is available on pypi. |
| `discussions.results[].software.stars` | int? | The number of stars on the repository. |
| `discussions.results[].software.forks` | int? | The numbers of forks of the repository. |
| `discussions.results[].software.programmingLanguage` | string? | The programming language spread on the software product. |
| `discussions.results[].organization` | object? | Aggregated information on a organization found on the web search result page. |
| `discussions.results[].organization.type` | string? | A type string identifying an organization. The value is always `organization`. |
| `discussions.results[].organization.name` | string | The name of the thing. |
| `discussions.results[].organization.url` | string? | A URL for the thing. |
| `discussions.results[].organization.thumbnail` | object? | Thumbnail associated with the thing. |
| `discussions.results[].organization.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].organization.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].organization.thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].organization.thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].organization.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].organization.thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].organization.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].organization.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].organization.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].organization.contact_points` | object[]? | A list of contact points for the organization. |
| `discussions.results[].organization.contact_points[].type` | string? | A type string identifying a contact point. The value is always `contact_point`. |
| `discussions.results[].organization.contact_points[].name` | string | The name of the thing. |
| `discussions.results[].organization.contact_points[].url` | string? | A URL for the thing. |
| `discussions.results[].organization.contact_points[].thumbnail` | object? | Thumbnail associated with the thing. |
| `discussions.results[].organization.contact_points[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `discussions.results[].organization.contact_points[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `discussions.results[].organization.contact_points[].thumbnail.height` | int? | The height of the thumbnail. |
| `discussions.results[].organization.contact_points[].thumbnail.width` | int? | The width of the thumbnail. |
| `discussions.results[].organization.contact_points[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `discussions.results[].organization.contact_points[].thumbnail.original` | string? | The original URL of the image. |
| `discussions.results[].organization.contact_points[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `discussions.results[].organization.contact_points[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `discussions.results[].organization.contact_points[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `discussions.results[].organization.contact_points[].telephone` | string? | The telephone number of the entity. |
| `discussions.results[].organization.contact_points[].email` | string? | The email address of the entity. |
| `discussions.results[].content_type` | string? | The content type associated with the search result page. |
| `discussions.results[].extra_snippets` | string[]? | A list of extra alternate snippets for the web search result. |
| `discussions.results[].icons` | object[]? | Icons associated with the search result. |
| `discussions.results[].icons[].href` | string |  |
| `discussions.results[].icons[].sizes` | string? |  |
| `discussions.results[].icons[].rel` | string? |  |
| `discussions.results[].icons[].type` | string? |  |
| `discussions.results[].icons[].ext` | string? |  |
| `discussions.results[].data` | object? | The enriched aggregated data for the relevant forum post. |
| `discussions.results[].data.forum_name` | string | The name of the forum. |
| `discussions.results[].data.num_answers` | int? | The number of answers to the post. |
| `discussions.results[].data.score` | string? | The score of the post on the forum. |
| `discussions.results[].data.title` | string? | The title of the post on the forum. |
| `discussions.results[].data.question` | string? | The question asked in the forum post. |
| `discussions.results[].data.top_comment` | string? | The top-rated comment under the forum post. |
| `discussions.mutated_by_goggles` | bool? | Whether the discussion results are changed by Goggles. The value is `false` by default. |
| `faq` | object? | Frequently asked questions that are relevant to the search query. |
| `faq.type` | string? | The FAQ result type identifier. The value is always `faq`. |
| `faq.results` | object[] | A list of aggregated question answer results relevant to the query. |
| `faq.results[].question` | string | The question being asked. |
| `faq.results[].answer` | string | The answer to the question. |
| `faq.results[].title` | string | The title of the post. |
| `faq.results[].url` | string | The URL pointing to the post. |
| `faq.results[].meta_url` | object? | Aggregated information about the URL. |
| `faq.results[].meta_url.scheme` | string | The protocol scheme extracted from the URL. |
| `faq.results[].meta_url.netloc` | string | The network location part extracted from the URL. |
| `faq.results[].meta_url.hostname` | string? | The lowercased domain name extracted from the URL. |
| `faq.results[].meta_url.favicon` | string | The favicon used for the URL. |
| `faq.results[].meta_url.path` | string | The hierarchical path of the URL useful as a display string. |
| `infobox` | object? | Aggregated information on an entity showable as an infobox. |
| `infobox.type` | string? | The type identifier for infoboxes. The value is always `graph`. |
| `infobox.results` | any[] | A list of infoboxes associated with the query. |
| `infobox.results[].title` | string | The title of the web page. |
| `infobox.results[].url` | string | The URL where the page is served. |
| `infobox.results[].is_source_local` | bool? | Whether the result is from a local source. |
| `infobox.results[].is_source_both` | bool? | Whether the result is from both local and global sources. |
| `infobox.results[].description` | string? | A description for the web page. |
| `infobox.results[].page_age` | string? | The page's date, based on its published or last modified date. |
| `infobox.results[].page_fetched` | string? | A date representing when the web page was last fetched. |
| `infobox.results[].fetched_content_timestamp` | int? | The timestamp when the content was fetched. |
| `infobox.results[].profile` | object? | A profile associated with the web page. |
| `infobox.results[].profile.name` | string | The name of the profile. |
| `infobox.results[].profile.url` | string | The original URL where the profile is available. |
| `infobox.results[].profile.long_name` | string? | The long name of the profile. |
| `infobox.results[].profile.img` | string? | The served image URL representing the profile. |
| `infobox.results[].language` | string? | A language classification for the web page. |
| `infobox.results[].family_friendly` | bool? | Whether the web page is family friendly. |
| `infobox.results[].type` | string? | The infobox result type identifier. The value is always `infobox`. |
| `infobox.results[].position` | int | The position on a search result page. |
| `infobox.results[].label` | string? | Any label associated with the entity. |
| `infobox.results[].category` | string? | Category classification for the entity. |
| `infobox.results[].long_desc` | string? | A longer description for the entity. |
| `infobox.results[].thumbnail` | object? | The thumbnail associated with the entity. |
| `infobox.results[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `infobox.results[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `infobox.results[].thumbnail.height` | int? | The height of the thumbnail. |
| `infobox.results[].thumbnail.width` | int? | The width of the thumbnail. |
| `infobox.results[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `infobox.results[].thumbnail.original` | string? | The original URL of the image. |
| `infobox.results[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `infobox.results[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `infobox.results[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `infobox.results[].attributes` | string[][]? | A list of attributes about the entity. |
| `infobox.results[].profiles` | any? | The profiles associated with the entity. |
| `infobox.results[].profiles[].name` | string | The name of the profile. |
| `infobox.results[].profiles[].url` | string | The original URL where the profile is available. |
| `infobox.results[].profiles[].long_name` | string? | The long name of the profile. |
| `infobox.results[].profiles[].img` | string? | The served image URL representing the profile. |
| `infobox.results[].website_url` | string? | The official website pertaining to the entity. |
| `infobox.results[].ratings` | object[]? | Any ratings given to the entity. |
| `infobox.results[].ratings[].ratingValue` | number | The current value of the rating. |
| `infobox.results[].ratings[].bestRating` | number | Best rating received. |
| `infobox.results[].ratings[].reviewCount` | int? | The number of reviews associated with the rating. |
| `infobox.results[].ratings[].profile` | object? | The profile associated with the rating. |
| `infobox.results[].ratings[].profile.name` | string | The name of the profile. |
| `infobox.results[].ratings[].profile.url` | string | The original URL where the profile is available. |
| `infobox.results[].ratings[].profile.long_name` | string? | The long name of the profile. |
| `infobox.results[].ratings[].profile.img` | string? | The served image URL representing the profile. |
| `infobox.results[].ratings[].is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `infobox.results[].providers` | object[]? | A list of data sources for the entity. |
| `infobox.results[].providers[].type` | string? | The type representing the source of data. This is usually `external`. |
| `infobox.results[].providers[].name` | string | The name of the data provider. This can be a domain. |
| `infobox.results[].providers[].url` | string | The URL where the information is coming from. |
| `infobox.results[].providers[].long_name` | string? | The long name for the data provider. |
| `infobox.results[].providers[].img` | string? | The served URL for the image data. |
| `infobox.results[].distance` | object? | A unit representing quantity relevant to the entity. |
| `infobox.results[].distance.value` | number | The quantity of the unit. |
| `infobox.results[].distance.units` | string | The name of the unit associated with the quantity. |
| `infobox.results[].images` | object[]? | A list of images relevant to the entity. |
| `infobox.results[].images[].src` | string | The served URL of the picture thumbnail. |
| `infobox.results[].images[].alt` | string? | The alt text for the thumbnail image. |
| `infobox.results[].images[].height` | int? | The height of the thumbnail. |
| `infobox.results[].images[].width` | int? | The width of the thumbnail. |
| `infobox.results[].images[].bg_color` | string? | The background color of the thumbnail. |
| `infobox.results[].images[].original` | string? | The original URL of the image. |
| `infobox.results[].images[].logo` | bool? | Whether the thumbnail is a logo. |
| `infobox.results[].images[].duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `infobox.results[].images[].theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `infobox.results[].movie` | object? | Any movie data relevant to the entity. Appears only when the result is a movie. |
| `infobox.results[].movie.name` | string? | Name of the movie. |
| `infobox.results[].movie.description` | string? | A short plot summary for the movie. |
| `infobox.results[].movie.url` | string? | A URL serving a movie profile page. |
| `infobox.results[].movie.thumbnail` | object? | A thumbnail for a movie poster. |
| `infobox.results[].movie.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `infobox.results[].movie.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `infobox.results[].movie.thumbnail.height` | int? | The height of the thumbnail. |
| `infobox.results[].movie.thumbnail.width` | int? | The width of the thumbnail. |
| `infobox.results[].movie.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `infobox.results[].movie.thumbnail.original` | string? | The original URL of the image. |
| `infobox.results[].movie.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `infobox.results[].movie.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `infobox.results[].movie.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `infobox.results[].movie.release` | string? | The release date for the movie. |
| `infobox.results[].movie.directors` | object[]? | A list of people responsible for directing the movie. |
| `infobox.results[].movie.directors[].type` | string? | A type identifying a person. The value is always `person`. |
| `infobox.results[].movie.directors[].name` | string | The name of the thing. |
| `infobox.results[].movie.directors[].url` | string? | A URL for the thing. |
| `infobox.results[].movie.directors[].thumbnail` | object? | Thumbnail associated with the thing. |
| `infobox.results[].movie.directors[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `infobox.results[].movie.directors[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `infobox.results[].movie.directors[].thumbnail.height` | int? | The height of the thumbnail. |
| `infobox.results[].movie.directors[].thumbnail.width` | int? | The width of the thumbnail. |
| `infobox.results[].movie.directors[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `infobox.results[].movie.directors[].thumbnail.original` | string? | The original URL of the image. |
| `infobox.results[].movie.directors[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `infobox.results[].movie.directors[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `infobox.results[].movie.directors[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `infobox.results[].movie.directors[].email` | string? | Email address of the person. |
| `infobox.results[].movie.actors` | object[]? | A list of actors in the movie. |
| `infobox.results[].movie.actors[].type` | string? | A type identifying a person. The value is always `person`. |
| `infobox.results[].movie.actors[].name` | string | The name of the thing. |
| `infobox.results[].movie.actors[].url` | string? | A URL for the thing. |
| `infobox.results[].movie.actors[].thumbnail` | object? | Thumbnail associated with the thing. |
| `infobox.results[].movie.actors[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `infobox.results[].movie.actors[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `infobox.results[].movie.actors[].thumbnail.height` | int? | The height of the thumbnail. |
| `infobox.results[].movie.actors[].thumbnail.width` | int? | The width of the thumbnail. |
| `infobox.results[].movie.actors[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `infobox.results[].movie.actors[].thumbnail.original` | string? | The original URL of the image. |
| `infobox.results[].movie.actors[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `infobox.results[].movie.actors[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `infobox.results[].movie.actors[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `infobox.results[].movie.actors[].email` | string? | Email address of the person. |
| `infobox.results[].movie.rating` | object? | Rating provided to the movie from various sources. |
| `infobox.results[].movie.rating.ratingValue` | number | The current value of the rating. |
| `infobox.results[].movie.rating.bestRating` | number | Best rating received. |
| `infobox.results[].movie.rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `infobox.results[].movie.rating.profile` | object? | The profile associated with the rating. |
| `infobox.results[].movie.rating.profile.name` | string | The name of the profile. |
| `infobox.results[].movie.rating.profile.url` | string | The original URL where the profile is available. |
| `infobox.results[].movie.rating.profile.long_name` | string? | The long name of the profile. |
| `infobox.results[].movie.rating.profile.img` | string? | The served image URL representing the profile. |
| `infobox.results[].movie.rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `infobox.results[].movie.duration` | string? | The runtime of the movie. The format is HH:MM:SS. |
| `infobox.results[].movie.genre` | string[]? | List of genres in which the movie can be classified. |
| `infobox.results[].movie.query` | string? | The query that resulted in the movie result. |
| `infobox.results[].subtype` | string? | The infobox subtype identifier. The value is always `generic`. |
| `infobox.results[].found_in_urls` | string[]? | List of URLs where the entity was found. |
| `locations` | object? | Places of interest (POIs) relevant to location sensitive queries. |
| `locations.type` | string? | Location type identifier. The value is always `locations`. |
| `locations.results` | object[] | An aggregated list of location sensitive results. |
| `locations.results[].title` | string | The title of the web page. |
| `locations.results[].url` | string | The URL where the page is served. |
| `locations.results[].is_source_local` | bool? | Whether the result is from a local source. |
| `locations.results[].is_source_both` | bool? | Whether the result is from both local and global sources. |
| `locations.results[].description` | string? | A description for the web page. |
| `locations.results[].page_age` | string? | The page's date, based on its published or last modified date. |
| `locations.results[].page_fetched` | string? | A date representing when the web page was last fetched. |
| `locations.results[].fetched_content_timestamp` | int? | The timestamp when the content was fetched. |
| `locations.results[].profile` | object? | A profile associated with the web page. |
| `locations.results[].profile.name` | string | The name of the profile. |
| `locations.results[].profile.url` | string | The original URL where the profile is available. |
| `locations.results[].profile.long_name` | string? | The long name of the profile. |
| `locations.results[].profile.img` | string? | The served image URL representing the profile. |
| `locations.results[].language` | string? | A language classification for the web page. |
| `locations.results[].family_friendly` | bool? | Whether the web page is family friendly. |
| `locations.results[].type` | string? | Location result type identifier. The value is always `location_result`. |
| `locations.results[].provider_url` | string | The complete URL of the provider. |
| `locations.results[].coordinates` | array? | A list of coordinates associated with the location. This is a lat long represented as a floating point. |
| `locations.results[].zoom_level` | int? | The zoom level on the map. |
| `locations.results[].thumbnail` | object? | The thumbnail associated with the location. |
| `locations.results[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `locations.results[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `locations.results[].thumbnail.height` | int? | The height of the thumbnail. |
| `locations.results[].thumbnail.width` | int? | The width of the thumbnail. |
| `locations.results[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `locations.results[].thumbnail.original` | string? | The original URL of the image. |
| `locations.results[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `locations.results[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `locations.results[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `locations.results[].postal_address` | object? | The postal address associated with the location. |
| `locations.results[].postal_address.type` | string? | The type identifying a postal address. The value is always `PostalAddress`. |
| `locations.results[].postal_address.country` | string? | The country associated with the location. |
| `locations.results[].postal_address.postalCode` | string? | The postal code associated with the location. |
| `locations.results[].postal_address.streetAddress` | string? | The street address associated with the location. |
| `locations.results[].postal_address.addressRegion` | string? | The region associated with the location. This is usually a state. |
| `locations.results[].postal_address.addressLocality` | string? | The address locality or subregion associated with the location. |
| `locations.results[].postal_address.displayAddress` | string | The displayed address string. |
| `locations.results[].opening_hours` | object? | The opening hours, if it is a business, associated with the location. |
| `locations.results[].opening_hours.current_day` | object[]? | The current day opening hours. Can have two sets of opening hours. |
| `locations.results[].opening_hours.current_day[].abbr_name` | string | A short string representing the day of the week. |
| `locations.results[].opening_hours.current_day[].full_name` | string | A full string representing the day of the week. |
| `locations.results[].opening_hours.current_day[].opens` | string | A 24 hr clock time string for the opening time of the business on a particular day. |
| `locations.results[].opening_hours.current_day[].closes` | string | A 24 hr clock time string for the closing time of the business on a particular day. |
| `locations.results[].opening_hours.days` | object[][]? | The opening hours for the whole week. |
| `locations.results[].contact` | object? | The contact of the business associated with the location. |
| `locations.results[].contact.email` | string? | The email address. |
| `locations.results[].contact.telephone` | string? | The telephone number. |
| `locations.results[].price_range` | string? | A display string used to show the price classification for the business. |
| `locations.results[].rating` | object? | The ratings of the business. |
| `locations.results[].rating.ratingValue` | number | The current value of the rating. |
| `locations.results[].rating.bestRating` | number | Best rating received. |
| `locations.results[].rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `locations.results[].rating.profile` | object? | The profile associated with the rating. |
| `locations.results[].rating.profile.name` | string | The name of the profile. |
| `locations.results[].rating.profile.url` | string | The original URL where the profile is available. |
| `locations.results[].rating.profile.long_name` | string? | The long name of the profile. |
| `locations.results[].rating.profile.img` | string? | The served image URL representing the profile. |
| `locations.results[].rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `locations.results[].distance` | object? | The distance of the location from the client. |
| `locations.results[].distance.value` | number | The quantity of the unit. |
| `locations.results[].distance.units` | string | The name of the unit associated with the quantity. |
| `locations.results[].profiles` | object[]? | Profiles associated with the business. |
| `locations.results[].profiles[].type` | string? | The type representing the source of data. This is usually `external`. |
| `locations.results[].profiles[].name` | string | The name of the data provider. This can be a domain. |
| `locations.results[].profiles[].url` | string | The URL where the information is coming from. |
| `locations.results[].profiles[].long_name` | string? | The long name for the data provider. |
| `locations.results[].profiles[].img` | string? | The served URL for the image data. |
| `locations.results[].reviews` | object? | Aggregated reviews from various sources relevant to the business. |
| `locations.results[].reviews.results` | object[] | A list of trip advisor reviews for the entity. |
| `locations.results[].reviews.results[].title` | string | The title of the review. |
| `locations.results[].reviews.results[].description` | string | A description seen in the review. |
| `locations.results[].reviews.results[].date` | string | The date when the review was published. |
| `locations.results[].reviews.results[].rating` | object | A rating given by the reviewer. |
| `locations.results[].reviews.results[].rating.ratingValue` | number | The current value of the rating. |
| `locations.results[].reviews.results[].rating.bestRating` | number | Best rating received. |
| `locations.results[].reviews.results[].rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `locations.results[].reviews.results[].rating.profile` | object? | The profile associated with the rating. |
| `locations.results[].reviews.results[].rating.profile.name` | string | The name of the profile. |
| `locations.results[].reviews.results[].rating.profile.url` | string | The original URL where the profile is available. |
| `locations.results[].reviews.results[].rating.profile.long_name` | string? | The long name of the profile. |
| `locations.results[].reviews.results[].rating.profile.img` | string? | The served image URL representing the profile. |
| `locations.results[].reviews.results[].rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `locations.results[].reviews.results[].author` | object | The author of the review. |
| `locations.results[].reviews.results[].author.type` | string? | A type identifying a person. The value is always `person`. |
| `locations.results[].reviews.results[].author.name` | string | The name of the thing. |
| `locations.results[].reviews.results[].author.url` | string? | A URL for the thing. |
| `locations.results[].reviews.results[].author.thumbnail` | object? | Thumbnail associated with the thing. |
| `locations.results[].reviews.results[].author.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `locations.results[].reviews.results[].author.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `locations.results[].reviews.results[].author.thumbnail.height` | int? | The height of the thumbnail. |
| `locations.results[].reviews.results[].author.thumbnail.width` | int? | The width of the thumbnail. |
| `locations.results[].reviews.results[].author.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `locations.results[].reviews.results[].author.thumbnail.original` | string? | The original URL of the image. |
| `locations.results[].reviews.results[].author.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `locations.results[].reviews.results[].author.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `locations.results[].reviews.results[].author.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `locations.results[].reviews.results[].author.email` | string? | Email address of the person. |
| `locations.results[].reviews.results[].review_url` | string | A URL link to the page where the review can be found. |
| `locations.results[].reviews.results[].language` | string | The language of the review. |
| `locations.results[].reviews.viewMoreUrl` | string | A URL to a web page where more information on the result can be seen. |
| `locations.results[].reviews.reviews_in_foreign_language` | bool | Any reviews available in a foreign language. |
| `locations.results[].pictures` | object? | A bunch of pictures associated with the business. |
| `locations.results[].pictures.viewMoreUrl` | string? | A URL to view more pictures. |
| `locations.results[].pictures.results` | object[] | A list of thumbnail results. |
| `locations.results[].pictures.results[].src` | string | The served URL of the picture thumbnail. |
| `locations.results[].pictures.results[].alt` | string? | The alt text for the thumbnail image. |
| `locations.results[].pictures.results[].height` | int? | The height of the thumbnail. |
| `locations.results[].pictures.results[].width` | int? | The width of the thumbnail. |
| `locations.results[].pictures.results[].bg_color` | string? | The background color of the thumbnail. |
| `locations.results[].pictures.results[].original` | string? | The original URL of the image. |
| `locations.results[].pictures.results[].logo` | bool? | Whether the thumbnail is a logo. |
| `locations.results[].pictures.results[].duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `locations.results[].pictures.results[].theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `locations.results[].action` | object? | An action to be taken. |
| `locations.results[].action.type` | string | The type representing the action. |
| `locations.results[].action.url` | string | A URL representing the action to be taken. |
| `locations.results[].serves_cuisine` | string[]? | A list of cuisine categories served. |
| `locations.results[].categories` | string[]? | A list of categories. |
| `locations.results[].icon_category` | string? | An icon category. |
| `locations.results[].timezone` | string? | IANA timezone identifier. |
| `locations.results[].timezone_offset` | int? | The UTC offset of the timezone. |
| `locations.results[].id` | string? | A temporary id associated with this result, which can be used to retrieve extra information about the location. It remains valid for 8 hours. |
| `locations.results[].results` | object[]? | Web results related to this location. |
| `locations.results[].results[].title` | string | The title of the web page. |
| `locations.results[].results[].url` | string | The URL where the page is served. |
| `locations.results[].results[].is_source_local` | bool? | Whether the result is from a local source. |
| `locations.results[].results[].is_source_both` | bool? | Whether the result is from both local and global sources. |
| `locations.results[].results[].description` | string? | A description for the web page. |
| `locations.results[].results[].page_age` | string? | The page's date, based on its published or last modified date. |
| `locations.results[].results[].page_fetched` | string? | A date representing when the web page was last fetched. |
| `locations.results[].results[].fetched_content_timestamp` | int? | The timestamp when the content was fetched. |
| `locations.results[].results[].profile` | object? | A profile associated with the web page. |
| `locations.results[].results[].profile.name` | string | The name of the profile. |
| `locations.results[].results[].profile.url` | string | The original URL where the profile is available. |
| `locations.results[].results[].profile.long_name` | string? | The long name of the profile. |
| `locations.results[].results[].profile.img` | string? | The served image URL representing the profile. |
| `locations.results[].results[].language` | string? | A language classification for the web page. |
| `locations.results[].results[].family_friendly` | bool? | Whether the web page is family friendly. |
| `locations.results[].results[].meta_url` | object | Aggregated information about the URL. |
| `locations.results[].results[].meta_url.scheme` | string | The protocol scheme extracted from the URL. |
| `locations.results[].results[].meta_url.netloc` | string | The network location part extracted from the URL. |
| `locations.results[].results[].meta_url.hostname` | string? | The lowercased domain name extracted from the URL. |
| `locations.results[].results[].meta_url.favicon` | string | The favicon used for the URL. |
| `locations.results[].results[].meta_url.path` | string | The hierarchical path of the URL useful as a display string. |
| `locations.provider` | object? | The provider of the location data. |
| `mixed` | object? | Preferred ranked order of search results. |
| `mixed.type` | string? | The type representing the model mixed. The value is always `mixed`. |
| `mixed.main` | object[]? | The ranking order for the main section of the search result page. |
| `mixed.main[].type` | string | The type of the result. |
| `mixed.main[].index` | int? | The 0th based index where the result should be placed. |
| `mixed.main[].all` | bool? | Whether to put all the results from the type at specific position. |
| `mixed.top` | object[]? | The ranking order for the top section of the search result page. |
| `mixed.top[].type` | string | The type of the result. |
| `mixed.top[].index` | int? | The 0th based index where the result should be placed. |
| `mixed.top[].all` | bool? | Whether to put all the results from the type at specific position. |
| `mixed.side` | object[]? | The ranking order for the side section of the search result page. |
| `mixed.side[].type` | string | The type of the result. |
| `mixed.side[].index` | int? | The 0th based index where the result should be placed. |
| `mixed.side[].all` | bool? | Whether to put all the results from the type at specific position. |
| `news` | object? | News results relevant to the query. |
| `news.type` | string? | The type of API result. The value is always `news`. |
| `news.results` | object[] | The list of news results. |
| `news.results[].title` | string | The title of the web page. |
| `news.results[].url` | string | The URL where the page is served. |
| `news.results[].is_source_local` | bool? | Whether the result is from a local source. |
| `news.results[].is_source_both` | bool? | Whether the result is from both local and global sources. |
| `news.results[].description` | string? | A description for the web page. |
| `news.results[].page_age` | string? | The page's date, based on its published or last modified date. |
| `news.results[].page_fetched` | string? | A date representing when the web page was last fetched. |
| `news.results[].fetched_content_timestamp` | int? | The timestamp when the content was fetched. |
| `news.results[].profile` | object? | A profile associated with the web page. |
| `news.results[].profile.name` | string | The name of the profile. |
| `news.results[].profile.url` | string | The original URL where the profile is available. |
| `news.results[].profile.long_name` | string? | The long name of the profile. |
| `news.results[].profile.img` | string? | The served image URL representing the profile. |
| `news.results[].language` | string? | A language classification for the web page. |
| `news.results[].family_friendly` | bool? | Whether the web page is family friendly. |
| `news.results[].meta_url` | object? | The aggregated information on the URL representing a news result. |
| `news.results[].source` | string? | The source of the news. |
| `news.results[].breaking` | bool? | Whether the news result is currently a breaking news. |
| `news.results[].is_live` | bool? | Whether the news result is currently live. |
| `news.results[].thumbnail` | object? | The thumbnail associated with the news result. |
| `news.results[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `news.results[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `news.results[].thumbnail.height` | int? | The height of the thumbnail. |
| `news.results[].thumbnail.width` | int? | The width of the thumbnail. |
| `news.results[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `news.results[].thumbnail.original` | string? | The original URL of the image. |
| `news.results[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `news.results[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `news.results[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `news.results[].age` | string? | A human-readable representation of the news article's age. For example, `2 days ago`. |
| `news.results[].extra_snippets` | string[]? | A list of extra alternate snippets for the news search result. |
| `news.results[].icons` | object[]? | Icons associated with the news result. |
| `news.results[].icons[].href` | string |  |
| `news.results[].icons[].sizes` | string? |  |
| `news.results[].icons[].rel` | string? |  |
| `news.results[].icons[].type` | string? |  |
| `news.results[].icons[].ext` | string? |  |
| `news.mutated_by_goggles` | bool? | Whether the results are mutated by a goggle. |
| `videos` | object? | Videos results relevant to the query. |
| `videos.type` | string? | The type of API result. The value is always `videos`. |
| `videos.results` | object[] | The list of video results. |
| `videos.results[].type` | string? | The type of video search API result. The value is always `video_result`. |
| `videos.results[].url` | string | The source URL of the video. |
| `videos.results[].title` | string | The title of the video. |
| `videos.results[].description` | string? | The description for the video. |
| `videos.results[].age` | string? | A human-readable representation of the video's age. For example, `2 days ago`. |
| `videos.results[].page_age` | string? | The page's date, based on its published or last modified date. |
| `videos.results[].page_fetched` | string? | The ISO date time when the page was last fetched. The format is `YYYY-MM-DDTHH:MM:SSZ`. |
| `videos.results[].fetched_content_timestamp` | int? | The timestamp when the content was fetched. |
| `videos.results[].video` | object? | Metadata for the video. |
| `videos.results[].video.duration` | string? | A time string representing the duration of the video. |
| `videos.results[].video.views` | int? | The number of views of the video. |
| `videos.results[].video.creator` | string? | The creator of the video. |
| `videos.results[].video.publisher` | string? | The publisher of the video. |
| `videos.results[].video.requires_subscription` | bool? | Whether the video requires a subscription. |
| `videos.results[].video.tags` | string[]? | A list of tags relevant to the video. |
| `videos.results[].video.author` | object? | A profile associated with the video. |
| `videos.results[].video.author.name` | string | The name of the profile. |
| `videos.results[].video.author.url` | string | The original URL where the profile is available. |
| `videos.results[].video.author.long_name` | string? | The long name of the profile. |
| `videos.results[].video.author.img` | string? | The served image URL representing the profile. |
| `videos.results[].meta_url` | object? | Aggregated information on the URL associated with the video search result. |
| `videos.results[].meta_url.scheme` | string? | The protocol scheme extracted from the URL. |
| `videos.results[].meta_url.netloc` | string? | The network location part extracted from the URL. |
| `videos.results[].meta_url.hostname` | string? | The lowercased domain name extracted from the URL. |
| `videos.results[].meta_url.favicon` | string? | The favicon used for the URL. |
| `videos.results[].meta_url.path` | string? | The hierarchical path of the URL useful as a display string. |
| `videos.results[].thumbnail` | object? | The thumbnail for the video. |
| `videos.results[].thumbnail.src` | string | The served URL of the thumbnail associated with the video. |
| `videos.results[].thumbnail.original` | string? | The original URL of the thumbnail associated with the video. |
| `videos.mutated_by_goggles` | bool? | Whether the results are mutated by a goggle. |
| `web` | object? | Web results relevant to the query. |
| `web.type` | string? | A type identifying web search results. The value is always `search`. |
| `web.results` | object[] | A list of search results. |
| `web.results[].title` | string | The title of the web page. |
| `web.results[].url` | string | The URL where the page is served. |
| `web.results[].is_source_local` | bool? | Whether the result is from a local source. |
| `web.results[].is_source_both` | bool? | Whether the result is from both local and global sources. |
| `web.results[].description` | string? | A description for the web page. |
| `web.results[].page_age` | string? | The page's date, based on its published or last modified date. |
| `web.results[].page_fetched` | string? | A date representing when the web page was last fetched. |
| `web.results[].fetched_content_timestamp` | int? | The timestamp when the content was fetched. |
| `web.results[].profile` | object? | A profile associated with the web page. |
| `web.results[].profile.name` | string | The name of the profile. |
| `web.results[].profile.url` | string | The original URL where the profile is available. |
| `web.results[].profile.long_name` | string? | The long name of the profile. |
| `web.results[].profile.img` | string? | The served image URL representing the profile. |
| `web.results[].language` | string? | The main language on the web search result. |
| `web.results[].family_friendly` | bool? | Whether the web page is family friendly. |
| `web.results[].type` | string? | A type identifying a web search result. The value is always `search_result`. |
| `web.results[].subtype` | string? | A sub type identifying the web search result type. |
| `web.results[].is_live` | bool? | Whether the web search result is currently live. Default value is `false`. |
| `web.results[].deep_results` | object? | Gathered information on a web search result. |
| `web.results[].deep_results.news` | object[]? | A list of news results associated with the result. |
| `web.results[].deep_results.news[].title` | string | The title of the web page. |
| `web.results[].deep_results.news[].url` | string | The URL where the page is served. |
| `web.results[].deep_results.news[].is_source_local` | bool? | Whether the result is from a local source. |
| `web.results[].deep_results.news[].is_source_both` | bool? | Whether the result is from both local and global sources. |
| `web.results[].deep_results.news[].description` | string? | A description for the web page. |
| `web.results[].deep_results.news[].page_age` | string? | The page's date, based on its published or last modified date. |
| `web.results[].deep_results.news[].page_fetched` | string? | A date representing when the web page was last fetched. |
| `web.results[].deep_results.news[].fetched_content_timestamp` | int? | The timestamp when the content was fetched. |
| `web.results[].deep_results.news[].profile` | object? | A profile associated with the web page. |
| `web.results[].deep_results.news[].profile.name` | string | The name of the profile. |
| `web.results[].deep_results.news[].profile.url` | string | The original URL where the profile is available. |
| `web.results[].deep_results.news[].profile.long_name` | string? | The long name of the profile. |
| `web.results[].deep_results.news[].profile.img` | string? | The served image URL representing the profile. |
| `web.results[].deep_results.news[].language` | string? | A language classification for the web page. |
| `web.results[].deep_results.news[].family_friendly` | bool? | Whether the web page is family friendly. |
| `web.results[].deep_results.news[].meta_url` | object? | The aggregated information on the URL representing a news result. |
| `web.results[].deep_results.news[].source` | string? | The source of the news. |
| `web.results[].deep_results.news[].breaking` | bool? | Whether the news result is currently a breaking news. |
| `web.results[].deep_results.news[].is_live` | bool? | Whether the news result is currently live. |
| `web.results[].deep_results.news[].thumbnail` | object? | The thumbnail associated with the news result. |
| `web.results[].deep_results.news[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].deep_results.news[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].deep_results.news[].thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].deep_results.news[].thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].deep_results.news[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].deep_results.news[].thumbnail.original` | string? | The original URL of the image. |
| `web.results[].deep_results.news[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].deep_results.news[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].deep_results.news[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].deep_results.news[].age` | string? | A human-readable representation of the news article's age. For example, `2 days ago`. |
| `web.results[].deep_results.news[].extra_snippets` | string[]? | A list of extra alternate snippets for the news search result. |
| `web.results[].deep_results.news[].icons` | object[]? | Icons associated with the news result. |
| `web.results[].deep_results.news[].icons[].href` | string |  |
| `web.results[].deep_results.news[].icons[].sizes` | string? |  |
| `web.results[].deep_results.news[].icons[].rel` | string? |  |
| `web.results[].deep_results.news[].icons[].type` | string? |  |
| `web.results[].deep_results.news[].icons[].ext` | string? |  |
| `web.results[].deep_results.buttons` | object[]? | A list of buttoned results associated with the result. |
| `web.results[].deep_results.buttons[].type` | string? | A type identifying button result. The value is always `button_result`. |
| `web.results[].deep_results.buttons[].title` | string | The title of the result. |
| `web.results[].deep_results.buttons[].url` | string | The URL for the button result. |
| `web.results[].deep_results.videos` | object[]? | Videos associated with the result. |
| `web.results[].deep_results.videos[].title` | string | The title of the web page. |
| `web.results[].deep_results.videos[].url` | string | The URL where the page is served. |
| `web.results[].deep_results.videos[].is_source_local` | bool? | Whether the result is from a local source. |
| `web.results[].deep_results.videos[].is_source_both` | bool? | Whether the result is from both local and global sources. |
| `web.results[].deep_results.videos[].description` | string? | A description for the web page. |
| `web.results[].deep_results.videos[].page_age` | string? | The page's date, based on its published or last modified date. |
| `web.results[].deep_results.videos[].page_fetched` | string? | A date representing when the web page was last fetched. |
| `web.results[].deep_results.videos[].fetched_content_timestamp` | int? | The timestamp when the content was fetched. |
| `web.results[].deep_results.videos[].profile` | object? | A profile associated with the web page. |
| `web.results[].deep_results.videos[].profile.name` | string | The name of the profile. |
| `web.results[].deep_results.videos[].profile.url` | string | The original URL where the profile is available. |
| `web.results[].deep_results.videos[].profile.long_name` | string? | The long name of the profile. |
| `web.results[].deep_results.videos[].profile.img` | string? | The served image URL representing the profile. |
| `web.results[].deep_results.videos[].language` | string? | A language classification for the web page. |
| `web.results[].deep_results.videos[].family_friendly` | bool? | Whether the web page is family friendly. |
| `web.results[].deep_results.videos[].type` | string? | The type identifying the video result. The value is always `video_result`. |
| `web.results[].deep_results.videos[].video` | object | Meta data for the video. |
| `web.results[].deep_results.videos[].video.duration` | string? | A time string representing the duration of the video. The format can be HH:MM:SS or MM:SS. |
| `web.results[].deep_results.videos[].video.views` | string? | The number of views of the video. |
| `web.results[].deep_results.videos[].video.creator` | string? | The creator of the video. |
| `web.results[].deep_results.videos[].video.publisher` | string? | The publisher of the video. |
| `web.results[].deep_results.videos[].video.thumbnail` | object? | A thumbnail associated with the video. |
| `web.results[].deep_results.videos[].video.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].deep_results.videos[].video.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].deep_results.videos[].video.thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].deep_results.videos[].video.thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].deep_results.videos[].video.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].deep_results.videos[].video.thumbnail.original` | string? | The original URL of the image. |
| `web.results[].deep_results.videos[].video.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].deep_results.videos[].video.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].deep_results.videos[].video.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].deep_results.videos[].video.tags` | string[]? | A list of tags associated with the video. |
| `web.results[].deep_results.videos[].video.author` | object? | Author of the video. |
| `web.results[].deep_results.videos[].video.author.name` | string | The name of the profile. |
| `web.results[].deep_results.videos[].video.author.url` | string | The original URL where the profile is available. |
| `web.results[].deep_results.videos[].video.author.long_name` | string? | The long name of the profile. |
| `web.results[].deep_results.videos[].video.author.img` | string? | The served image URL representing the profile. |
| `web.results[].deep_results.videos[].video.requires_subscription` | bool? | Whether the video requires a subscription to watch. |
| `web.results[].deep_results.videos[].meta_url` | object? | Aggregated information on the URL. |
| `web.results[].deep_results.videos[].meta_url.scheme` | string | The protocol scheme extracted from the URL. |
| `web.results[].deep_results.videos[].meta_url.netloc` | string | The network location part extracted from the URL. |
| `web.results[].deep_results.videos[].meta_url.hostname` | string? | The lowercased domain name extracted from the URL. |
| `web.results[].deep_results.videos[].meta_url.favicon` | string | The favicon used for the URL. |
| `web.results[].deep_results.videos[].meta_url.path` | string | The hierarchical path of the URL useful as a display string. |
| `web.results[].deep_results.videos[].thumbnail` | object? | The thumbnail of the video. |
| `web.results[].deep_results.videos[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].deep_results.videos[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].deep_results.videos[].thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].deep_results.videos[].thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].deep_results.videos[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].deep_results.videos[].thumbnail.original` | string? | The original URL of the image. |
| `web.results[].deep_results.videos[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].deep_results.videos[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].deep_results.videos[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].deep_results.videos[].age` | string? | A human-readable representation of the video's age. For example, `2 days ago`. |
| `web.results[].deep_results.videos[].publisher` | string? | The publisher of the video. |
| `web.results[].deep_results.images` | object[]? | Images associated with the result. |
| `web.results[].deep_results.images[].thumbnail` | object | The thumbnail associated with the image. |
| `web.results[].deep_results.images[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].deep_results.images[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].deep_results.images[].thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].deep_results.images[].thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].deep_results.images[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].deep_results.images[].thumbnail.original` | string? | The original URL of the image. |
| `web.results[].deep_results.images[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].deep_results.images[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].deep_results.images[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].deep_results.images[].url` | string? | The URL of the image. |
| `web.results[].deep_results.images[].properties` | object? | Metadata on the image. |
| `web.results[].deep_results.images[].properties.url` | string | The original image URL. |
| `web.results[].deep_results.images[].properties.resized` | string | The URL for a better quality resized image. |
| `web.results[].deep_results.images[].properties.placeholder` | string | The placeholder image URL. |
| `web.results[].deep_results.images[].properties.height` | int? | The image height. |
| `web.results[].deep_results.images[].properties.width` | int? | The image width. |
| `web.results[].deep_results.images[].properties.format` | string? | The image format. |
| `web.results[].deep_results.images[].properties.content_size` | string? | The image size. |
| `web.results[].schemas` | any[]? | A list of schemas (structured data) extracted from the page. The schemas try to follow schema.org and will return anything we can extract from the HTML that can fit into these models. |
| `web.results[].meta_url` | object? | Aggregated information on the URL associated with the web search result. |
| `web.results[].thumbnail` | object? | The thumbnail of the web search result. |
| `web.results[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].thumbnail.original` | string? | The original URL of the image. |
| `web.results[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].age` | string? | A human-readable representation of the web search result's age. For example, `2 days ago`. |
| `web.results[].location` | object? | The location details if the query relates to a restaurant. |
| `web.results[].location.title` | string | The title of the web page. |
| `web.results[].location.url` | string | The URL where the page is served. |
| `web.results[].location.is_source_local` | bool? | Whether the result is from a local source. |
| `web.results[].location.is_source_both` | bool? | Whether the result is from both local and global sources. |
| `web.results[].location.description` | string? | A description for the web page. |
| `web.results[].location.page_age` | string? | The page's date, based on its published or last modified date. |
| `web.results[].location.page_fetched` | string? | A date representing when the web page was last fetched. |
| `web.results[].location.fetched_content_timestamp` | int? | The timestamp when the content was fetched. |
| `web.results[].location.profile` | object? | A profile associated with the web page. |
| `web.results[].location.profile.name` | string | The name of the profile. |
| `web.results[].location.profile.url` | string | The original URL where the profile is available. |
| `web.results[].location.profile.long_name` | string? | The long name of the profile. |
| `web.results[].location.profile.img` | string? | The served image URL representing the profile. |
| `web.results[].location.language` | string? | A language classification for the web page. |
| `web.results[].location.family_friendly` | bool? | Whether the web page is family friendly. |
| `web.results[].location.type` | string? | Location result type identifier. The value is always `location_result`. |
| `web.results[].location.provider_url` | string | The complete URL of the provider. |
| `web.results[].location.coordinates` | array? | A list of coordinates associated with the location. This is a lat long represented as a floating point. |
| `web.results[].location.zoom_level` | int? | The zoom level on the map. |
| `web.results[].location.thumbnail` | object? | The thumbnail associated with the location. |
| `web.results[].location.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].location.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].location.thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].location.thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].location.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].location.thumbnail.original` | string? | The original URL of the image. |
| `web.results[].location.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].location.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].location.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].location.postal_address` | object? | The postal address associated with the location. |
| `web.results[].location.postal_address.type` | string? | The type identifying a postal address. The value is always `PostalAddress`. |
| `web.results[].location.postal_address.country` | string? | The country associated with the location. |
| `web.results[].location.postal_address.postalCode` | string? | The postal code associated with the location. |
| `web.results[].location.postal_address.streetAddress` | string? | The street address associated with the location. |
| `web.results[].location.postal_address.addressRegion` | string? | The region associated with the location. This is usually a state. |
| `web.results[].location.postal_address.addressLocality` | string? | The address locality or subregion associated with the location. |
| `web.results[].location.postal_address.displayAddress` | string | The displayed address string. |
| `web.results[].location.opening_hours` | object? | The opening hours, if it is a business, associated with the location. |
| `web.results[].location.opening_hours.current_day` | object[]? | The current day opening hours. Can have two sets of opening hours. |
| `web.results[].location.opening_hours.current_day[].abbr_name` | string | A short string representing the day of the week. |
| `web.results[].location.opening_hours.current_day[].full_name` | string | A full string representing the day of the week. |
| `web.results[].location.opening_hours.current_day[].opens` | string | A 24 hr clock time string for the opening time of the business on a particular day. |
| `web.results[].location.opening_hours.current_day[].closes` | string | A 24 hr clock time string for the closing time of the business on a particular day. |
| `web.results[].location.opening_hours.days` | object[][]? | The opening hours for the whole week. |
| `web.results[].location.contact` | object? | The contact of the business associated with the location. |
| `web.results[].location.contact.email` | string? | The email address. |
| `web.results[].location.contact.telephone` | string? | The telephone number. |
| `web.results[].location.price_range` | string? | A display string used to show the price classification for the business. |
| `web.results[].location.rating` | object? | The ratings of the business. |
| `web.results[].location.rating.ratingValue` | number | The current value of the rating. |
| `web.results[].location.rating.bestRating` | number | Best rating received. |
| `web.results[].location.rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `web.results[].location.rating.profile` | object? | The profile associated with the rating. |
| `web.results[].location.rating.profile.name` | string | The name of the profile. |
| `web.results[].location.rating.profile.url` | string | The original URL where the profile is available. |
| `web.results[].location.rating.profile.long_name` | string? | The long name of the profile. |
| `web.results[].location.rating.profile.img` | string? | The served image URL representing the profile. |
| `web.results[].location.rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `web.results[].location.distance` | object? | The distance of the location from the client. |
| `web.results[].location.distance.value` | number | The quantity of the unit. |
| `web.results[].location.distance.units` | string | The name of the unit associated with the quantity. |
| `web.results[].location.profiles` | object[]? | Profiles associated with the business. |
| `web.results[].location.profiles[].type` | string? | The type representing the source of data. This is usually `external`. |
| `web.results[].location.profiles[].name` | string | The name of the data provider. This can be a domain. |
| `web.results[].location.profiles[].url` | string | The URL where the information is coming from. |
| `web.results[].location.profiles[].long_name` | string? | The long name for the data provider. |
| `web.results[].location.profiles[].img` | string? | The served URL for the image data. |
| `web.results[].location.reviews` | object? | Aggregated reviews from various sources relevant to the business. |
| `web.results[].location.reviews.results` | object[] | A list of trip advisor reviews for the entity. |
| `web.results[].location.reviews.results[].title` | string | The title of the review. |
| `web.results[].location.reviews.results[].description` | string | A description seen in the review. |
| `web.results[].location.reviews.results[].date` | string | The date when the review was published. |
| `web.results[].location.reviews.results[].rating` | object | A rating given by the reviewer. |
| `web.results[].location.reviews.results[].rating.ratingValue` | number | The current value of the rating. |
| `web.results[].location.reviews.results[].rating.bestRating` | number | Best rating received. |
| `web.results[].location.reviews.results[].rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `web.results[].location.reviews.results[].rating.profile` | object? | The profile associated with the rating. |
| `web.results[].location.reviews.results[].rating.profile.name` | string | The name of the profile. |
| `web.results[].location.reviews.results[].rating.profile.url` | string | The original URL where the profile is available. |
| `web.results[].location.reviews.results[].rating.profile.long_name` | string? | The long name of the profile. |
| `web.results[].location.reviews.results[].rating.profile.img` | string? | The served image URL representing the profile. |
| `web.results[].location.reviews.results[].rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `web.results[].location.reviews.results[].author` | object | The author of the review. |
| `web.results[].location.reviews.results[].author.type` | string? | A type identifying a person. The value is always `person`. |
| `web.results[].location.reviews.results[].author.name` | string | The name of the thing. |
| `web.results[].location.reviews.results[].author.url` | string? | A URL for the thing. |
| `web.results[].location.reviews.results[].author.thumbnail` | object? | Thumbnail associated with the thing. |
| `web.results[].location.reviews.results[].author.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].location.reviews.results[].author.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].location.reviews.results[].author.thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].location.reviews.results[].author.thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].location.reviews.results[].author.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].location.reviews.results[].author.thumbnail.original` | string? | The original URL of the image. |
| `web.results[].location.reviews.results[].author.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].location.reviews.results[].author.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].location.reviews.results[].author.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].location.reviews.results[].author.email` | string? | Email address of the person. |
| `web.results[].location.reviews.results[].review_url` | string | A URL link to the page where the review can be found. |
| `web.results[].location.reviews.results[].language` | string | The language of the review. |
| `web.results[].location.reviews.viewMoreUrl` | string | A URL to a web page where more information on the result can be seen. |
| `web.results[].location.reviews.reviews_in_foreign_language` | bool | Any reviews available in a foreign language. |
| `web.results[].location.pictures` | object? | A bunch of pictures associated with the business. |
| `web.results[].location.pictures.viewMoreUrl` | string? | A URL to view more pictures. |
| `web.results[].location.pictures.results` | object[] | A list of thumbnail results. |
| `web.results[].location.pictures.results[].src` | string | The served URL of the picture thumbnail. |
| `web.results[].location.pictures.results[].alt` | string? | The alt text for the thumbnail image. |
| `web.results[].location.pictures.results[].height` | int? | The height of the thumbnail. |
| `web.results[].location.pictures.results[].width` | int? | The width of the thumbnail. |
| `web.results[].location.pictures.results[].bg_color` | string? | The background color of the thumbnail. |
| `web.results[].location.pictures.results[].original` | string? | The original URL of the image. |
| `web.results[].location.pictures.results[].logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].location.pictures.results[].duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].location.pictures.results[].theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].location.action` | object? | An action to be taken. |
| `web.results[].location.action.type` | string | The type representing the action. |
| `web.results[].location.action.url` | string | A URL representing the action to be taken. |
| `web.results[].location.serves_cuisine` | string[]? | A list of cuisine categories served. |
| `web.results[].location.categories` | string[]? | A list of categories. |
| `web.results[].location.icon_category` | string? | An icon category. |
| `web.results[].location.timezone` | string? | IANA timezone identifier. |
| `web.results[].location.timezone_offset` | int? | The UTC offset of the timezone. |
| `web.results[].location.id` | string? | A temporary id associated with this result, which can be used to retrieve extra information about the location. It remains valid for 8 hours. |
| `web.results[].location.results` | object[]? | Web results related to this location. |
| `web.results[].location.results[].title` | string | The title of the web page. |
| `web.results[].location.results[].url` | string | The URL where the page is served. |
| `web.results[].location.results[].is_source_local` | bool? | Whether the result is from a local source. |
| `web.results[].location.results[].is_source_both` | bool? | Whether the result is from both local and global sources. |
| `web.results[].location.results[].description` | string? | A description for the web page. |
| `web.results[].location.results[].page_age` | string? | The page's date, based on its published or last modified date. |
| `web.results[].location.results[].page_fetched` | string? | A date representing when the web page was last fetched. |
| `web.results[].location.results[].fetched_content_timestamp` | int? | The timestamp when the content was fetched. |
| `web.results[].location.results[].profile` | object? | A profile associated with the web page. |
| `web.results[].location.results[].profile.name` | string | The name of the profile. |
| `web.results[].location.results[].profile.url` | string | The original URL where the profile is available. |
| `web.results[].location.results[].profile.long_name` | string? | The long name of the profile. |
| `web.results[].location.results[].profile.img` | string? | The served image URL representing the profile. |
| `web.results[].location.results[].language` | string? | A language classification for the web page. |
| `web.results[].location.results[].family_friendly` | bool? | Whether the web page is family friendly. |
| `web.results[].location.results[].meta_url` | object | Aggregated information about the URL. |
| `web.results[].location.results[].meta_url.scheme` | string | The protocol scheme extracted from the URL. |
| `web.results[].location.results[].meta_url.netloc` | string | The network location part extracted from the URL. |
| `web.results[].location.results[].meta_url.hostname` | string? | The lowercased domain name extracted from the URL. |
| `web.results[].location.results[].meta_url.favicon` | string | The favicon used for the URL. |
| `web.results[].location.results[].meta_url.path` | string | The hierarchical path of the URL useful as a display string. |
| `web.results[].restaurant` | object? | Deprecated. Use `location` instead. |
| `web.results[].restaurant.title` | string | The title of the web page. |
| `web.results[].restaurant.url` | string | The URL where the page is served. |
| `web.results[].restaurant.is_source_local` | bool? | Whether the result is from a local source. |
| `web.results[].restaurant.is_source_both` | bool? | Whether the result is from both local and global sources. |
| `web.results[].restaurant.description` | string? | A description for the web page. |
| `web.results[].restaurant.page_age` | string? | The page's date, based on its published or last modified date. |
| `web.results[].restaurant.page_fetched` | string? | A date representing when the web page was last fetched. |
| `web.results[].restaurant.fetched_content_timestamp` | int? | The timestamp when the content was fetched. |
| `web.results[].restaurant.profile` | object? | A profile associated with the web page. |
| `web.results[].restaurant.profile.name` | string | The name of the profile. |
| `web.results[].restaurant.profile.url` | string | The original URL where the profile is available. |
| `web.results[].restaurant.profile.long_name` | string? | The long name of the profile. |
| `web.results[].restaurant.profile.img` | string? | The served image URL representing the profile. |
| `web.results[].restaurant.language` | string? | A language classification for the web page. |
| `web.results[].restaurant.family_friendly` | bool? | Whether the web page is family friendly. |
| `web.results[].restaurant.type` | string? | Location result type identifier. The value is always `location_result`. |
| `web.results[].restaurant.provider_url` | string | The complete URL of the provider. |
| `web.results[].restaurant.coordinates` | array? | A list of coordinates associated with the location. This is a lat long represented as a floating point. |
| `web.results[].restaurant.zoom_level` | int? | The zoom level on the map. |
| `web.results[].restaurant.thumbnail` | object? | The thumbnail associated with the location. |
| `web.results[].restaurant.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].restaurant.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].restaurant.thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].restaurant.thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].restaurant.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].restaurant.thumbnail.original` | string? | The original URL of the image. |
| `web.results[].restaurant.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].restaurant.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].restaurant.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].restaurant.postal_address` | object? | The postal address associated with the location. |
| `web.results[].restaurant.postal_address.type` | string? | The type identifying a postal address. The value is always `PostalAddress`. |
| `web.results[].restaurant.postal_address.country` | string? | The country associated with the location. |
| `web.results[].restaurant.postal_address.postalCode` | string? | The postal code associated with the location. |
| `web.results[].restaurant.postal_address.streetAddress` | string? | The street address associated with the location. |
| `web.results[].restaurant.postal_address.addressRegion` | string? | The region associated with the location. This is usually a state. |
| `web.results[].restaurant.postal_address.addressLocality` | string? | The address locality or subregion associated with the location. |
| `web.results[].restaurant.postal_address.displayAddress` | string | The displayed address string. |
| `web.results[].restaurant.opening_hours` | object? | The opening hours, if it is a business, associated with the location. |
| `web.results[].restaurant.opening_hours.current_day` | object[]? | The current day opening hours. Can have two sets of opening hours. |
| `web.results[].restaurant.opening_hours.current_day[].abbr_name` | string | A short string representing the day of the week. |
| `web.results[].restaurant.opening_hours.current_day[].full_name` | string | A full string representing the day of the week. |
| `web.results[].restaurant.opening_hours.current_day[].opens` | string | A 24 hr clock time string for the opening time of the business on a particular day. |
| `web.results[].restaurant.opening_hours.current_day[].closes` | string | A 24 hr clock time string for the closing time of the business on a particular day. |
| `web.results[].restaurant.opening_hours.days` | object[][]? | The opening hours for the whole week. |
| `web.results[].restaurant.contact` | object? | The contact of the business associated with the location. |
| `web.results[].restaurant.contact.email` | string? | The email address. |
| `web.results[].restaurant.contact.telephone` | string? | The telephone number. |
| `web.results[].restaurant.price_range` | string? | A display string used to show the price classification for the business. |
| `web.results[].restaurant.rating` | object? | The ratings of the business. |
| `web.results[].restaurant.rating.ratingValue` | number | The current value of the rating. |
| `web.results[].restaurant.rating.bestRating` | number | Best rating received. |
| `web.results[].restaurant.rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `web.results[].restaurant.rating.profile` | object? | The profile associated with the rating. |
| `web.results[].restaurant.rating.profile.name` | string | The name of the profile. |
| `web.results[].restaurant.rating.profile.url` | string | The original URL where the profile is available. |
| `web.results[].restaurant.rating.profile.long_name` | string? | The long name of the profile. |
| `web.results[].restaurant.rating.profile.img` | string? | The served image URL representing the profile. |
| `web.results[].restaurant.rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `web.results[].restaurant.distance` | object? | The distance of the location from the client. |
| `web.results[].restaurant.distance.value` | number | The quantity of the unit. |
| `web.results[].restaurant.distance.units` | string | The name of the unit associated with the quantity. |
| `web.results[].restaurant.profiles` | object[]? | Profiles associated with the business. |
| `web.results[].restaurant.profiles[].type` | string? | The type representing the source of data. This is usually `external`. |
| `web.results[].restaurant.profiles[].name` | string | The name of the data provider. This can be a domain. |
| `web.results[].restaurant.profiles[].url` | string | The URL where the information is coming from. |
| `web.results[].restaurant.profiles[].long_name` | string? | The long name for the data provider. |
| `web.results[].restaurant.profiles[].img` | string? | The served URL for the image data. |
| `web.results[].restaurant.reviews` | object? | Aggregated reviews from various sources relevant to the business. |
| `web.results[].restaurant.reviews.results` | object[] | A list of trip advisor reviews for the entity. |
| `web.results[].restaurant.reviews.results[].title` | string | The title of the review. |
| `web.results[].restaurant.reviews.results[].description` | string | A description seen in the review. |
| `web.results[].restaurant.reviews.results[].date` | string | The date when the review was published. |
| `web.results[].restaurant.reviews.results[].rating` | object | A rating given by the reviewer. |
| `web.results[].restaurant.reviews.results[].rating.ratingValue` | number | The current value of the rating. |
| `web.results[].restaurant.reviews.results[].rating.bestRating` | number | Best rating received. |
| `web.results[].restaurant.reviews.results[].rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `web.results[].restaurant.reviews.results[].rating.profile` | object? | The profile associated with the rating. |
| `web.results[].restaurant.reviews.results[].rating.profile.name` | string | The name of the profile. |
| `web.results[].restaurant.reviews.results[].rating.profile.url` | string | The original URL where the profile is available. |
| `web.results[].restaurant.reviews.results[].rating.profile.long_name` | string? | The long name of the profile. |
| `web.results[].restaurant.reviews.results[].rating.profile.img` | string? | The served image URL representing the profile. |
| `web.results[].restaurant.reviews.results[].rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `web.results[].restaurant.reviews.results[].author` | object | The author of the review. |
| `web.results[].restaurant.reviews.results[].author.type` | string? | A type identifying a person. The value is always `person`. |
| `web.results[].restaurant.reviews.results[].author.name` | string | The name of the thing. |
| `web.results[].restaurant.reviews.results[].author.url` | string? | A URL for the thing. |
| `web.results[].restaurant.reviews.results[].author.thumbnail` | object? | Thumbnail associated with the thing. |
| `web.results[].restaurant.reviews.results[].author.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].restaurant.reviews.results[].author.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].restaurant.reviews.results[].author.thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].restaurant.reviews.results[].author.thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].restaurant.reviews.results[].author.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].restaurant.reviews.results[].author.thumbnail.original` | string? | The original URL of the image. |
| `web.results[].restaurant.reviews.results[].author.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].restaurant.reviews.results[].author.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].restaurant.reviews.results[].author.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].restaurant.reviews.results[].author.email` | string? | Email address of the person. |
| `web.results[].restaurant.reviews.results[].review_url` | string | A URL link to the page where the review can be found. |
| `web.results[].restaurant.reviews.results[].language` | string | The language of the review. |
| `web.results[].restaurant.reviews.viewMoreUrl` | string | A URL to a web page where more information on the result can be seen. |
| `web.results[].restaurant.reviews.reviews_in_foreign_language` | bool | Any reviews available in a foreign language. |
| `web.results[].restaurant.pictures` | object? | A bunch of pictures associated with the business. |
| `web.results[].restaurant.pictures.viewMoreUrl` | string? | A URL to view more pictures. |
| `web.results[].restaurant.pictures.results` | object[] | A list of thumbnail results. |
| `web.results[].restaurant.pictures.results[].src` | string | The served URL of the picture thumbnail. |
| `web.results[].restaurant.pictures.results[].alt` | string? | The alt text for the thumbnail image. |
| `web.results[].restaurant.pictures.results[].height` | int? | The height of the thumbnail. |
| `web.results[].restaurant.pictures.results[].width` | int? | The width of the thumbnail. |
| `web.results[].restaurant.pictures.results[].bg_color` | string? | The background color of the thumbnail. |
| `web.results[].restaurant.pictures.results[].original` | string? | The original URL of the image. |
| `web.results[].restaurant.pictures.results[].logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].restaurant.pictures.results[].duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].restaurant.pictures.results[].theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].restaurant.action` | object? | An action to be taken. |
| `web.results[].restaurant.action.type` | string | The type representing the action. |
| `web.results[].restaurant.action.url` | string | A URL representing the action to be taken. |
| `web.results[].restaurant.serves_cuisine` | string[]? | A list of cuisine categories served. |
| `web.results[].restaurant.categories` | string[]? | A list of categories. |
| `web.results[].restaurant.icon_category` | string? | An icon category. |
| `web.results[].restaurant.timezone` | string? | IANA timezone identifier. |
| `web.results[].restaurant.timezone_offset` | int? | The UTC offset of the timezone. |
| `web.results[].restaurant.id` | string? | A temporary id associated with this result, which can be used to retrieve extra information about the location. It remains valid for 8 hours. |
| `web.results[].restaurant.results` | object[]? | Web results related to this location. |
| `web.results[].restaurant.results[].title` | string | The title of the web page. |
| `web.results[].restaurant.results[].url` | string | The URL where the page is served. |
| `web.results[].restaurant.results[].is_source_local` | bool? | Whether the result is from a local source. |
| `web.results[].restaurant.results[].is_source_both` | bool? | Whether the result is from both local and global sources. |
| `web.results[].restaurant.results[].description` | string? | A description for the web page. |
| `web.results[].restaurant.results[].page_age` | string? | The page's date, based on its published or last modified date. |
| `web.results[].restaurant.results[].page_fetched` | string? | A date representing when the web page was last fetched. |
| `web.results[].restaurant.results[].fetched_content_timestamp` | int? | The timestamp when the content was fetched. |
| `web.results[].restaurant.results[].profile` | object? | A profile associated with the web page. |
| `web.results[].restaurant.results[].profile.name` | string | The name of the profile. |
| `web.results[].restaurant.results[].profile.url` | string | The original URL where the profile is available. |
| `web.results[].restaurant.results[].profile.long_name` | string? | The long name of the profile. |
| `web.results[].restaurant.results[].profile.img` | string? | The served image URL representing the profile. |
| `web.results[].restaurant.results[].language` | string? | A language classification for the web page. |
| `web.results[].restaurant.results[].family_friendly` | bool? | Whether the web page is family friendly. |
| `web.results[].restaurant.results[].meta_url` | object | Aggregated information about the URL. |
| `web.results[].restaurant.results[].meta_url.scheme` | string | The protocol scheme extracted from the URL. |
| `web.results[].restaurant.results[].meta_url.netloc` | string | The network location part extracted from the URL. |
| `web.results[].restaurant.results[].meta_url.hostname` | string? | The lowercased domain name extracted from the URL. |
| `web.results[].restaurant.results[].meta_url.favicon` | string | The favicon used for the URL. |
| `web.results[].restaurant.results[].meta_url.path` | string | The hierarchical path of the URL useful as a display string. |
| `web.results[].video` | object? | The video associated with the web search result. |
| `web.results[].video.duration` | string? | A time string representing the duration of the video. The format can be HH:MM:SS or MM:SS. |
| `web.results[].video.views` | string? | The number of views of the video. |
| `web.results[].video.creator` | string? | The creator of the video. |
| `web.results[].video.publisher` | string? | The publisher of the video. |
| `web.results[].video.thumbnail` | object? | A thumbnail associated with the video. |
| `web.results[].video.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].video.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].video.thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].video.thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].video.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].video.thumbnail.original` | string? | The original URL of the image. |
| `web.results[].video.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].video.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].video.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].video.tags` | string[]? | A list of tags associated with the video. |
| `web.results[].video.author` | object? | Author of the video. |
| `web.results[].video.author.name` | string | The name of the profile. |
| `web.results[].video.author.url` | string | The original URL where the profile is available. |
| `web.results[].video.author.long_name` | string? | The long name of the profile. |
| `web.results[].video.author.img` | string? | The served image URL representing the profile. |
| `web.results[].video.requires_subscription` | bool? | Whether the video requires a subscription to watch. |
| `web.results[].movie` | object? | The movie associated with the web search result. |
| `web.results[].movie.name` | string? | Name of the movie. |
| `web.results[].movie.description` | string? | A short plot summary for the movie. |
| `web.results[].movie.url` | string? | A URL serving a movie profile page. |
| `web.results[].movie.thumbnail` | object? | A thumbnail for a movie poster. |
| `web.results[].movie.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].movie.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].movie.thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].movie.thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].movie.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].movie.thumbnail.original` | string? | The original URL of the image. |
| `web.results[].movie.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].movie.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].movie.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].movie.release` | string? | The release date for the movie. |
| `web.results[].movie.directors` | object[]? | A list of people responsible for directing the movie. |
| `web.results[].movie.directors[].type` | string? | A type identifying a person. The value is always `person`. |
| `web.results[].movie.directors[].name` | string | The name of the thing. |
| `web.results[].movie.directors[].url` | string? | A URL for the thing. |
| `web.results[].movie.directors[].thumbnail` | object? | Thumbnail associated with the thing. |
| `web.results[].movie.directors[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].movie.directors[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].movie.directors[].thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].movie.directors[].thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].movie.directors[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].movie.directors[].thumbnail.original` | string? | The original URL of the image. |
| `web.results[].movie.directors[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].movie.directors[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].movie.directors[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].movie.directors[].email` | string? | Email address of the person. |
| `web.results[].movie.actors` | object[]? | A list of actors in the movie. |
| `web.results[].movie.actors[].type` | string? | A type identifying a person. The value is always `person`. |
| `web.results[].movie.actors[].name` | string | The name of the thing. |
| `web.results[].movie.actors[].url` | string? | A URL for the thing. |
| `web.results[].movie.actors[].thumbnail` | object? | Thumbnail associated with the thing. |
| `web.results[].movie.actors[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].movie.actors[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].movie.actors[].thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].movie.actors[].thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].movie.actors[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].movie.actors[].thumbnail.original` | string? | The original URL of the image. |
| `web.results[].movie.actors[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].movie.actors[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].movie.actors[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].movie.actors[].email` | string? | Email address of the person. |
| `web.results[].movie.rating` | object? | Rating provided to the movie from various sources. |
| `web.results[].movie.rating.ratingValue` | number | The current value of the rating. |
| `web.results[].movie.rating.bestRating` | number | Best rating received. |
| `web.results[].movie.rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `web.results[].movie.rating.profile` | object? | The profile associated with the rating. |
| `web.results[].movie.rating.profile.name` | string | The name of the profile. |
| `web.results[].movie.rating.profile.url` | string | The original URL where the profile is available. |
| `web.results[].movie.rating.profile.long_name` | string? | The long name of the profile. |
| `web.results[].movie.rating.profile.img` | string? | The served image URL representing the profile. |
| `web.results[].movie.rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `web.results[].movie.duration` | string? | The runtime of the movie. The format is HH:MM:SS. |
| `web.results[].movie.genre` | string[]? | List of genres in which the movie can be classified. |
| `web.results[].movie.query` | string? | The query that resulted in the movie result. |
| `web.results[].faq` | object? | Any frequently asked questions associated with the web search result. |
| `web.results[].faq.items` | object[] | A list of question/answer pairs. |
| `web.results[].faq.items[].question` | string | The question being asked. |
| `web.results[].faq.items[].answer` | string | The answer to the question. |
| `web.results[].faq.items[].title` | string | The title of the post. |
| `web.results[].faq.items[].url` | string | The URL pointing to the post. |
| `web.results[].faq.items[].meta_url` | object? | Aggregated information about the URL. |
| `web.results[].faq.items[].meta_url.scheme` | string | The protocol scheme extracted from the URL. |
| `web.results[].faq.items[].meta_url.netloc` | string | The network location part extracted from the URL. |
| `web.results[].faq.items[].meta_url.hostname` | string? | The lowercased domain name extracted from the URL. |
| `web.results[].faq.items[].meta_url.favicon` | string | The favicon used for the URL. |
| `web.results[].faq.items[].meta_url.path` | string | The hierarchical path of the URL useful as a display string. |
| `web.results[].qa` | object? | Any question answer information associated with the web search result page. |
| `web.results[].qa.question` | string | The question that is being asked. |
| `web.results[].qa.answer` | object | An answer to the question. |
| `web.results[].qa.answer.text` | string | The main content of the answer. |
| `web.results[].qa.answer.author` | string? | The name of the author of the answer. |
| `web.results[].qa.answer.upvoteCount` | int? | Number of upvotes on the answer. |
| `web.results[].qa.answer.downvoteCount` | int? | The number of downvotes on the answer. |
| `web.results[].book` | object? | Any book information associated with the web search result page. |
| `web.results[].book.title` | string | The title of the book. |
| `web.results[].book.author` | object[] | The author of the book. |
| `web.results[].book.author[].type` | string? | A type identifying a person. The value is always `person`. |
| `web.results[].book.author[].name` | string | The name of the thing. |
| `web.results[].book.author[].url` | string? | A URL for the thing. |
| `web.results[].book.author[].thumbnail` | object? | Thumbnail associated with the thing. |
| `web.results[].book.author[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].book.author[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].book.author[].thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].book.author[].thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].book.author[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].book.author[].thumbnail.original` | string? | The original URL of the image. |
| `web.results[].book.author[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].book.author[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].book.author[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].book.author[].email` | string? | Email address of the person. |
| `web.results[].book.date` | string? | The publishing date of the book. |
| `web.results[].book.price` | object? | The price of the book. |
| `web.results[].book.price.price` | string | The price value in a given currency. |
| `web.results[].book.price.priceCurrency` | string | The currency of the price value. |
| `web.results[].book.pages` | int? | The number of pages in the book. |
| `web.results[].book.publisher` | object? | The publisher of the book. |
| `web.results[].book.publisher.type` | string? | A type identifying a person. The value is always `person`. |
| `web.results[].book.publisher.name` | string | The name of the thing. |
| `web.results[].book.publisher.url` | string? | A URL for the thing. |
| `web.results[].book.publisher.thumbnail` | object? | Thumbnail associated with the thing. |
| `web.results[].book.publisher.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].book.publisher.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].book.publisher.thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].book.publisher.thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].book.publisher.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].book.publisher.thumbnail.original` | string? | The original URL of the image. |
| `web.results[].book.publisher.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].book.publisher.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].book.publisher.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].book.publisher.email` | string? | Email address of the person. |
| `web.results[].book.rating` | object? | A gathered rating from different sources associated with the book. |
| `web.results[].book.rating.ratingValue` | number | The current value of the rating. |
| `web.results[].book.rating.bestRating` | number | Best rating received. |
| `web.results[].book.rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `web.results[].book.rating.profile` | object? | The profile associated with the rating. |
| `web.results[].book.rating.profile.name` | string | The name of the profile. |
| `web.results[].book.rating.profile.url` | string | The original URL where the profile is available. |
| `web.results[].book.rating.profile.long_name` | string? | The long name of the profile. |
| `web.results[].book.rating.profile.img` | string? | The served image URL representing the profile. |
| `web.results[].book.rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `web.results[].rating` | object? | Rating found for the web search result page. |
| `web.results[].rating.ratingValue` | number | The current value of the rating. |
| `web.results[].rating.bestRating` | number | Best rating received. |
| `web.results[].rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `web.results[].rating.profile` | object? | The profile associated with the rating. |
| `web.results[].rating.profile.name` | string | The name of the profile. |
| `web.results[].rating.profile.url` | string | The original URL where the profile is available. |
| `web.results[].rating.profile.long_name` | string? | The long name of the profile. |
| `web.results[].rating.profile.img` | string? | The served image URL representing the profile. |
| `web.results[].rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `web.results[].article` | object? | An article found for the web search result page. |
| `web.results[].article.author` | object[]? | The author of the article. |
| `web.results[].article.author[].type` | string? | A type identifying a person. The value is always `person`. |
| `web.results[].article.author[].name` | string | The name of the thing. |
| `web.results[].article.author[].url` | string? | A URL for the thing. |
| `web.results[].article.author[].thumbnail` | object? | Thumbnail associated with the thing. |
| `web.results[].article.author[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].article.author[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].article.author[].thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].article.author[].thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].article.author[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].article.author[].thumbnail.original` | string? | The original URL of the image. |
| `web.results[].article.author[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].article.author[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].article.author[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].article.author[].email` | string? | Email address of the person. |
| `web.results[].article.date` | string? | The date when the article was published. |
| `web.results[].article.publisher` | object? | The name of the publisher for the article. |
| `web.results[].article.publisher.type` | string? | A type string identifying an organization. The value is always `organization`. |
| `web.results[].article.publisher.name` | string | The name of the thing. |
| `web.results[].article.publisher.url` | string? | A URL for the thing. |
| `web.results[].article.publisher.thumbnail` | object? | Thumbnail associated with the thing. |
| `web.results[].article.publisher.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].article.publisher.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].article.publisher.thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].article.publisher.thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].article.publisher.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].article.publisher.thumbnail.original` | string? | The original URL of the image. |
| `web.results[].article.publisher.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].article.publisher.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].article.publisher.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].article.publisher.contact_points` | object[]? | A list of contact points for the organization. |
| `web.results[].article.publisher.contact_points[].type` | string? | A type string identifying a contact point. The value is always `contact_point`. |
| `web.results[].article.publisher.contact_points[].name` | string | The name of the thing. |
| `web.results[].article.publisher.contact_points[].url` | string? | A URL for the thing. |
| `web.results[].article.publisher.contact_points[].thumbnail` | object? | Thumbnail associated with the thing. |
| `web.results[].article.publisher.contact_points[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].article.publisher.contact_points[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].article.publisher.contact_points[].thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].article.publisher.contact_points[].thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].article.publisher.contact_points[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].article.publisher.contact_points[].thumbnail.original` | string? | The original URL of the image. |
| `web.results[].article.publisher.contact_points[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].article.publisher.contact_points[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].article.publisher.contact_points[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].article.publisher.contact_points[].telephone` | string? | The telephone number of the entity. |
| `web.results[].article.publisher.contact_points[].email` | string? | The email address of the entity. |
| `web.results[].article.thumbnail` | object? | A thumbnail associated with the article. |
| `web.results[].article.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].article.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].article.thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].article.thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].article.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].article.thumbnail.original` | string? | The original URL of the image. |
| `web.results[].article.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].article.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].article.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].article.isAccessibleForFree` | bool? | Whether the article is free to read or is behind a paywall. |
| `web.results[].product` | any? | The main product and a review that is found on the web search result page. |
| `web.results[].product.type` | string? | A string representing a product type. The value is always `Product`. |
| `web.results[].product.name` | string | The name of the product. |
| `web.results[].product.url` | string? | The URL of the product page. |
| `web.results[].product.category` | string? | The category of the product. |
| `web.results[].product.price` | string | The price of the product. |
| `web.results[].product.thumbnail` | object | A thumbnail associated with the product. |
| `web.results[].product.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].product.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].product.thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].product.thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].product.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].product.thumbnail.original` | string? | The original URL of the image. |
| `web.results[].product.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].product.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].product.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].product.description` | string? | The description of the product. |
| `web.results[].product.offers` | object[]? | A list of offers available on the product. |
| `web.results[].product.offers[].url` | string | The URL where the offer can be found. |
| `web.results[].product.offers[].priceCurrency` | string | The currency in which the offer is made. |
| `web.results[].product.offers[].price` | string | The price of the product currently on offer. |
| `web.results[].product.rating` | object? | A rating associated with the product. |
| `web.results[].product.rating.ratingValue` | number | The current value of the rating. |
| `web.results[].product.rating.bestRating` | number | Best rating received. |
| `web.results[].product.rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `web.results[].product.rating.profile` | object? | The profile associated with the rating. |
| `web.results[].product.rating.profile.name` | string | The name of the profile. |
| `web.results[].product.rating.profile.url` | string | The original URL where the profile is available. |
| `web.results[].product.rating.profile.long_name` | string? | The long name of the profile. |
| `web.results[].product.rating.profile.img` | string? | The served image URL representing the profile. |
| `web.results[].product.rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `web.results[].product.gtin` | string? | A Global Trade Item Number (GTIN) for the product. |
| `web.results[].product.gtin8` | string? | The GTIN-8 (EAN/UCC-8) code of the product. |
| `web.results[].product.gtin12` | string? | The GTIN-12 (UPC) code of the product. |
| `web.results[].product.gtin13` | string? | The GTIN-13 (EAN/ISBN-13) code of the product. |
| `web.results[].product.gtin14` | string? | The GTIN-14 code of the product. |
| `web.results[].product_cluster` | any[]? | A list of products and reviews that are found on the web search result page. |
| `web.results[].product_cluster[].type` | string? | A string representing a product type. The value is always `Product`. |
| `web.results[].product_cluster[].name` | string | The name of the product. |
| `web.results[].product_cluster[].url` | string? | The URL of the product page. |
| `web.results[].product_cluster[].category` | string? | The category of the product. |
| `web.results[].product_cluster[].price` | string | The price of the product. |
| `web.results[].product_cluster[].thumbnail` | object | A thumbnail associated with the product. |
| `web.results[].product_cluster[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].product_cluster[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].product_cluster[].thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].product_cluster[].thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].product_cluster[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].product_cluster[].thumbnail.original` | string? | The original URL of the image. |
| `web.results[].product_cluster[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].product_cluster[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].product_cluster[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].product_cluster[].description` | string? | The description of the product. |
| `web.results[].product_cluster[].offers` | object[]? | A list of offers available on the product. |
| `web.results[].product_cluster[].offers[].url` | string | The URL where the offer can be found. |
| `web.results[].product_cluster[].offers[].priceCurrency` | string | The currency in which the offer is made. |
| `web.results[].product_cluster[].offers[].price` | string | The price of the product currently on offer. |
| `web.results[].product_cluster[].rating` | object? | A rating associated with the product. |
| `web.results[].product_cluster[].rating.ratingValue` | number | The current value of the rating. |
| `web.results[].product_cluster[].rating.bestRating` | number | Best rating received. |
| `web.results[].product_cluster[].rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `web.results[].product_cluster[].rating.profile` | object? | The profile associated with the rating. |
| `web.results[].product_cluster[].rating.profile.name` | string | The name of the profile. |
| `web.results[].product_cluster[].rating.profile.url` | string | The original URL where the profile is available. |
| `web.results[].product_cluster[].rating.profile.long_name` | string? | The long name of the profile. |
| `web.results[].product_cluster[].rating.profile.img` | string? | The served image URL representing the profile. |
| `web.results[].product_cluster[].rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `web.results[].product_cluster[].gtin` | string? | A Global Trade Item Number (GTIN) for the product. |
| `web.results[].product_cluster[].gtin8` | string? | The GTIN-8 (EAN/UCC-8) code of the product. |
| `web.results[].product_cluster[].gtin12` | string? | The GTIN-12 (UPC) code of the product. |
| `web.results[].product_cluster[].gtin13` | string? | The GTIN-13 (EAN/ISBN-13) code of the product. |
| `web.results[].product_cluster[].gtin14` | string? | The GTIN-14 code of the product. |
| `web.results[].cluster_type` | string? | A type representing a cluster. The value can be product_cluster. |
| `web.results[].cluster` | object[]? | A list of web search results. |
| `web.results[].cluster[].title` | string | The title of the web page. |
| `web.results[].cluster[].url` | string | The URL where the page is served. |
| `web.results[].cluster[].is_source_local` | bool? | Whether the result is from a local source. |
| `web.results[].cluster[].is_source_both` | bool? | Whether the result is from both local and global sources. |
| `web.results[].cluster[].description` | string? | A description for the web page. |
| `web.results[].cluster[].page_age` | string? | The page's date, based on its published or last modified date. |
| `web.results[].cluster[].page_fetched` | string? | A date representing when the web page was last fetched. |
| `web.results[].cluster[].fetched_content_timestamp` | int? | The timestamp when the content was fetched. |
| `web.results[].cluster[].profile` | object? | A profile associated with the web page. |
| `web.results[].cluster[].profile.name` | string | The name of the profile. |
| `web.results[].cluster[].profile.url` | string | The original URL where the profile is available. |
| `web.results[].cluster[].profile.long_name` | string? | The long name of the profile. |
| `web.results[].cluster[].profile.img` | string? | The served image URL representing the profile. |
| `web.results[].cluster[].language` | string? | A language classification for the web page. |
| `web.results[].cluster[].family_friendly` | bool? | Whether the web page is family friendly. |
| `web.results[].creative_work` | object? | Aggregated information on the creative work found on the web search result. |
| `web.results[].creative_work.name` | string | The name of the creative work. |
| `web.results[].creative_work.rating` | object? | A rating that is given to the creative work. |
| `web.results[].creative_work.rating.ratingValue` | number | The current value of the rating. |
| `web.results[].creative_work.rating.bestRating` | number | Best rating received. |
| `web.results[].creative_work.rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `web.results[].creative_work.rating.profile` | object? | The profile associated with the rating. |
| `web.results[].creative_work.rating.profile.name` | string | The name of the profile. |
| `web.results[].creative_work.rating.profile.url` | string | The original URL where the profile is available. |
| `web.results[].creative_work.rating.profile.long_name` | string? | The long name of the profile. |
| `web.results[].creative_work.rating.profile.img` | string? | The served image URL representing the profile. |
| `web.results[].creative_work.rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `web.results[].creative_work.thumbnail` | object | A thumbnail associated with the creative work. |
| `web.results[].creative_work.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].creative_work.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].creative_work.thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].creative_work.thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].creative_work.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].creative_work.thumbnail.original` | string? | The original URL of the image. |
| `web.results[].creative_work.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].creative_work.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].creative_work.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].music_recording` | object? | Aggregated information on music recording found on the web search result. |
| `web.results[].music_recording.name` | string | The name of the song or album. |
| `web.results[].music_recording.rating` | object? | The rating of the music. |
| `web.results[].music_recording.rating.ratingValue` | number | The current value of the rating. |
| `web.results[].music_recording.rating.bestRating` | number | Best rating received. |
| `web.results[].music_recording.rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `web.results[].music_recording.rating.profile` | object? | The profile associated with the rating. |
| `web.results[].music_recording.rating.profile.name` | string | The name of the profile. |
| `web.results[].music_recording.rating.profile.url` | string | The original URL where the profile is available. |
| `web.results[].music_recording.rating.profile.long_name` | string? | The long name of the profile. |
| `web.results[].music_recording.rating.profile.img` | string? | The served image URL representing the profile. |
| `web.results[].music_recording.rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `web.results[].music_recording.thumbnail` | object? | A thumbnail associated with the music. |
| `web.results[].music_recording.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].music_recording.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].music_recording.thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].music_recording.thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].music_recording.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].music_recording.thumbnail.original` | string? | The original URL of the image. |
| `web.results[].music_recording.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].music_recording.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].music_recording.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].review` | object? | Aggregated information on the review found on the web search result. |
| `web.results[].review.type` | string? | A string representing review type. This is always `Review`. |
| `web.results[].review.name` | string | The review title for the review. |
| `web.results[].review.thumbnail` | object | The thumbnail associated with the reviewer. |
| `web.results[].review.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].review.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].review.thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].review.thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].review.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].review.thumbnail.original` | string? | The original URL of the image. |
| `web.results[].review.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].review.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].review.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].review.description` | string | A description of the review (the text of the review itself). |
| `web.results[].review.rating` | object | The ratings associated with the review. |
| `web.results[].review.rating.ratingValue` | number | The current value of the rating. |
| `web.results[].review.rating.bestRating` | number | Best rating received. |
| `web.results[].review.rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `web.results[].review.rating.profile` | object? | The profile associated with the rating. |
| `web.results[].review.rating.profile.name` | string | The name of the profile. |
| `web.results[].review.rating.profile.url` | string | The original URL where the profile is available. |
| `web.results[].review.rating.profile.long_name` | string? | The long name of the profile. |
| `web.results[].review.rating.profile.img` | string? | The served image URL representing the profile. |
| `web.results[].review.rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `web.results[].recipe` | object? | Aggregated information on a recipe found on the web search result page. |
| `web.results[].recipe.title` | string | The title of the recipe. |
| `web.results[].recipe.description` | string | The description of the recipe. |
| `web.results[].recipe.thumbnail` | object | A thumbnail associated with the recipe. |
| `web.results[].recipe.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].recipe.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].recipe.thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].recipe.thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].recipe.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].recipe.thumbnail.original` | string? | The original URL of the image. |
| `web.results[].recipe.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].recipe.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].recipe.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].recipe.url` | string | The URL of the web page where the recipe was found. |
| `web.results[].recipe.domain` | string | The domain of the web page where the recipe was found. |
| `web.results[].recipe.favicon` | string | The URL for the favicon of the web page where the recipe was found. |
| `web.results[].recipe.time` | string? | The total time required to cook the recipe. |
| `web.results[].recipe.prep_time` | string? | The preparation time for the recipe. |
| `web.results[].recipe.cook_time` | string? | The cooking time for the recipe. |
| `web.results[].recipe.ingredients` | string? | Ingredients required for the recipe. |
| `web.results[].recipe.instructions` | object[]? | List of instructions for the recipe. |
| `web.results[].recipe.instructions[].text` | string | The how to text. |
| `web.results[].recipe.instructions[].name` | string? | A name for the how to. |
| `web.results[].recipe.instructions[].url` | string? | A URL associated with the how to. |
| `web.results[].recipe.instructions[].image` | string[]? | A list of image URLs associated with the how to. |
| `web.results[].recipe.servings` | int? | How many people the recipe serves. |
| `web.results[].recipe.calories` | int? | Calorie count for the recipe. |
| `web.results[].recipe.publisher` | string? | The publisher of the recipe. |
| `web.results[].recipe.rating` | object? | Aggregated information on the ratings associated with the recipe. |
| `web.results[].recipe.rating.ratingValue` | number | The current value of the rating. |
| `web.results[].recipe.rating.bestRating` | number | Best rating received. |
| `web.results[].recipe.rating.reviewCount` | int? | The number of reviews associated with the rating. |
| `web.results[].recipe.rating.profile` | object? | The profile associated with the rating. |
| `web.results[].recipe.rating.profile.name` | string | The name of the profile. |
| `web.results[].recipe.rating.profile.url` | string | The original URL where the profile is available. |
| `web.results[].recipe.rating.profile.long_name` | string? | The long name of the profile. |
| `web.results[].recipe.rating.profile.img` | string? | The served image URL representing the profile. |
| `web.results[].recipe.rating.is_tripadvisor` | bool? | Whether the rating is coming from Tripadvisor. |
| `web.results[].recipe.recipeCategory` | string? | The category of the recipe. |
| `web.results[].recipe.recipeCuisine` | string? | The cuisine classification for the recipe. |
| `web.results[].recipe.video` | object? | Aggregated information on the cooking video associated with the recipe. |
| `web.results[].recipe.video.duration` | string? | A time string representing the duration of the video. The format can be HH:MM:SS or MM:SS. |
| `web.results[].recipe.video.views` | string? | The number of views of the video. |
| `web.results[].recipe.video.creator` | string? | The creator of the video. |
| `web.results[].recipe.video.publisher` | string? | The publisher of the video. |
| `web.results[].recipe.video.thumbnail` | object? | A thumbnail associated with the video. |
| `web.results[].recipe.video.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].recipe.video.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].recipe.video.thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].recipe.video.thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].recipe.video.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].recipe.video.thumbnail.original` | string? | The original URL of the image. |
| `web.results[].recipe.video.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].recipe.video.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].recipe.video.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].recipe.video.tags` | string[]? | A list of tags associated with the video. |
| `web.results[].recipe.video.author` | object? | Author of the video. |
| `web.results[].recipe.video.author.name` | string | The name of the profile. |
| `web.results[].recipe.video.author.url` | string | The original URL where the profile is available. |
| `web.results[].recipe.video.author.long_name` | string? | The long name of the profile. |
| `web.results[].recipe.video.author.img` | string? | The served image URL representing the profile. |
| `web.results[].recipe.video.requires_subscription` | bool? | Whether the video requires a subscription to watch. |
| `web.results[].software` | object? | Aggregated information on a software product found on the web search result page. |
| `web.results[].software.name` | string? | The name of the software product. |
| `web.results[].software.author` | string? | The author of software product. |
| `web.results[].software.version` | string? | The latest version of the software product. |
| `web.results[].software.codeRepository` | string? | The code repository where the software product is currently available or maintained. |
| `web.results[].software.homepage` | string? | The home page of the software product. |
| `web.results[].software.datePublished` | string? | The date when the software product was published. |
| `web.results[].software.is_npm` | bool? | Whether the software product is available on npm. |
| `web.results[].software.is_pypi` | bool? | Whether the software product is available on pypi. |
| `web.results[].software.stars` | int? | The number of stars on the repository. |
| `web.results[].software.forks` | int? | The numbers of forks of the repository. |
| `web.results[].software.programmingLanguage` | string? | The programming language spread on the software product. |
| `web.results[].organization` | object? | Aggregated information on a organization found on the web search result page. |
| `web.results[].organization.type` | string? | A type string identifying an organization. The value is always `organization`. |
| `web.results[].organization.name` | string | The name of the thing. |
| `web.results[].organization.url` | string? | A URL for the thing. |
| `web.results[].organization.thumbnail` | object? | Thumbnail associated with the thing. |
| `web.results[].organization.thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].organization.thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].organization.thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].organization.thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].organization.thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].organization.thumbnail.original` | string? | The original URL of the image. |
| `web.results[].organization.thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].organization.thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].organization.thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].organization.contact_points` | object[]? | A list of contact points for the organization. |
| `web.results[].organization.contact_points[].type` | string? | A type string identifying a contact point. The value is always `contact_point`. |
| `web.results[].organization.contact_points[].name` | string | The name of the thing. |
| `web.results[].organization.contact_points[].url` | string? | A URL for the thing. |
| `web.results[].organization.contact_points[].thumbnail` | object? | Thumbnail associated with the thing. |
| `web.results[].organization.contact_points[].thumbnail.src` | string | The served URL of the picture thumbnail. |
| `web.results[].organization.contact_points[].thumbnail.alt` | string? | The alt text for the thumbnail image. |
| `web.results[].organization.contact_points[].thumbnail.height` | int? | The height of the thumbnail. |
| `web.results[].organization.contact_points[].thumbnail.width` | int? | The width of the thumbnail. |
| `web.results[].organization.contact_points[].thumbnail.bg_color` | string? | The background color of the thumbnail. |
| `web.results[].organization.contact_points[].thumbnail.original` | string? | The original URL of the image. |
| `web.results[].organization.contact_points[].thumbnail.logo` | bool? | Whether the thumbnail is a logo. |
| `web.results[].organization.contact_points[].thumbnail.duplicated` | bool? | Whether the thumbnail is a duplicate. |
| `web.results[].organization.contact_points[].thumbnail.theme` | string? | The theme of the thumbnail (e.g., light or dark). |
| `web.results[].organization.contact_points[].telephone` | string? | The telephone number of the entity. |
| `web.results[].organization.contact_points[].email` | string? | The email address of the entity. |
| `web.results[].content_type` | string? | The content type associated with the search result page. |
| `web.results[].extra_snippets` | string[]? | A list of extra alternate snippets for the web search result. |
| `web.results[].icons` | object[]? | Icons associated with the search result. |
| `web.results[].icons[].href` | string |  |
| `web.results[].icons[].sizes` | string? |  |
| `web.results[].icons[].rel` | string? |  |
| `web.results[].icons[].type` | string? |  |
| `web.results[].icons[].ext` | string? |  |
| `web.family_friendly` | bool? | Whether the results are family friendly. |
| `summarizer` | object? | Summary key to get summary results for the query. |
| `summarizer.type` | string? | The type of result. The value is always `summarizer`. |
| `summarizer.key` | string | The key to retrieve the full summary results. |
| `rich` | object? | Callback information to retrieve rich results. |
| `rich.type` | string? |  |
| `rich.hint` | object? |  |
| `rich.hint.vertical` | string | The vertical associated with the callback. For the full list of verticals supported see the Rich Vertical list. |
| `rich.hint.callback_key` | string | The unique key for the callback. |

### 404
Not Found

| Field | Type | Description |
|-------|------|-------------|
| `type` | string? |  |
| `error` | object |  |
| `error.id` | string | A unique identifier for this particular occurrence of the problem. |
| `error.status` | int | The HTTP status code applicable to this problem, expressed as a string value. |
| `error.detail` | string? | Explanation specific to this occurrence of the problem. Like title, this field's value can be localized. |
| `error.meta` | object? | A meta object containing non-standard meta-information about the error. |
| `error.code` | string | An application-specific error code, expressed as a string value. |
| `time` | int? |  |

### 422
Unprocessable Entity

| Field | Type | Description |
|-------|------|-------------|
| `type` | string? |  |
| `error` | object |  |
| `error.id` | string | A unique identifier for this particular occurrence of the problem. |
| `error.status` | int | The HTTP status code applicable to this problem, expressed as a string value. |
| `error.detail` | string? | Explanation specific to this occurrence of the problem. Like title, this field's value can be localized. |
| `error.meta` | object? | A meta object containing non-standard meta-information about the error. |
| `error.code` | string | An application-specific error code, expressed as a string value. |
| `time` | int? |  |

### 429
Too Many Requests

| Field | Type | Description |
|-------|------|-------------|
| `type` | string? |  |
| `error` | object |  |
| `error.id` | string | A unique identifier for this particular occurrence of the problem. |
| `error.status` | int | The HTTP status code applicable to this problem, expressed as a string value. |
| `error.detail` | string? | Explanation specific to this occurrence of the problem. Like title, this field's value can be localized. |
| `error.meta` | object? | A meta object containing non-standard meta-information about the error. |
| `error.code` | string | An application-specific error code, expressed as a string value. |
| `time` | int? |  |

## Code Samples

### cURL

```bash
curl "https://api.search.brave.com/res/v1/web/search?q=brave+search" \
  -H "Accept: application/json" \ 
  -H "Accept-Encoding: gzip" \ 
  -H "X-Subscription-Token: <YOUR_API_KEY>"
```

### Python

```python
import requests

url = "https://api.search.brave.com/res/v1/web/search"

params = {
    "q": "brave search"
}

headers = {
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
    "X-Subscription-Token": "<YOUR_API_KEY>"
}

response = requests.get(url, params=params, headers=headers)
print(response.json())
```