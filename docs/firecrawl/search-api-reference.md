> Source: https://docs.firecrawl.dev/api-reference/endpoint/search.md
> Retrieved: 2026-10-31
> Covers: POST /v2/search (API reference / OpenAPI)


# Search

The search endpoint combines web search with Firecrawl's scraping capabilities to return full page content for any query.

Include `scrapeOptions` with `formats: [{"type": "markdown"}]` to get complete markdown content for each search result otherwise you will default to getting the results (url, title, description). You can also use other formats like `{"type": "summary"}` for condensed content.

## Supported query operators

We support a variety of query operators that allow you to filter your searches better.

| Operator | Functionality | Examples |
| - | - | - |
| `""` | Non-fuzzy matches a string of text | `"Firecrawl"` |
| `-` | Excludes certain keywords or negates other operators | `-bad`, `-site:firecrawl.dev` |
| `site:` | Only returns results from a specified website | `site:firecrawl.dev` |
| `filetype:` | Only returns results with a specific file extension | `filetype:pdf`, `-filetype:pdf` |
| `inurl:` | Only returns results that include a word in the URL | `inurl:firecrawl` |
| `allinurl:` | Only returns results that include multiple words in the URL | `allinurl:git firecrawl` |
| `intitle:` | Only returns results that include a word in the title of the page | `intitle:Firecrawl` |
| `allintitle:` | Only returns results that include multiple words in the title of the page | `allintitle:firecrawl playground` |
| `related:` | Only returns results that are related to a specific domain | `related:firecrawl.dev` |
| `imagesize:` | Only returns images with exact dimensions | `imagesize:1920x1080` |
| `larger:` | Only returns images larger than specified dimensions | `larger:1920x1080` |

## Location Parameter

Use the `location` parameter to get geo-targeted search results. Format: `"string"`. Examples: `"Germany"`, `"San Francisco,California,United States"`.

See the [complete list of supported locations](https://firecrawl.dev/search_locations.json) for all available countries and languages.

## Country Parameter

Use the `country` parameter to specify the country for search results using ISO country codes. Default: `"US"`.

Examples: `"US"`, `"DE"`, `"FR"`, `"JP"`, `"UK"`, `"CA"`.

```json theme={null}
{
  "query": "restaurants",
  "country": "DE"
}
```

## Categories Parameter

Filter search results by specific categories using the `categories` parameter:

* **`research`**: Restrict web search to academic and research websites (arxiv.org, nature.com, pubmed.ncbi.nlm.nih.gov, and similar). Changes on 2026-11-16 to search the [Research Index](https://docs.firecrawl.dev/features/research.md) and return paper records, see the warning below
* **`pdf`**: Search for PDFs
* **`developer`**: Search the [Developer Index](https://docs.firecrawl.dev/features/developer.md) — issues, merged pull requests, and READMEs from public code repositories, alongside curated documentation sites
* **`gov`**: Search the [Firecrawl Government Index](https://docs.firecrawl.dev/features/gov.md) — statutes, regulations, codes, court opinions, and other government publications. Cannot be combined with other categories and takes no filters; use [`/search/gov`](https://docs.firecrawl.dev/api-reference/endpoint/gov-search#filters) to filter

> [!WARNING]
>
> **The `research` category changes on 2026-11-16.** It will search the [Research Index](https://docs.firecrawl.dev/features/research.md) (PubMed, bioRxiv, medRxiv, arXiv) instead of filtering web results to 14 academic websites. Results will move from `data.web` to `data.research` and come back as paper records: `paperId`, `primaryId`, `ids`, `title`, `abstract`, `score`. Until then every response that uses it carries a `warnings` entry.
>
> If you want paper records, update your parsing before that date or call [`GET /search/research/papers`](https://docs.firecrawl.dev/api-reference/endpoint/research-search-papers) today. If you want web pages from academic sites, switch to [`includeDomains`](#domain-filters).

### Example Usage

```json theme={null}
{
  "query": "machine learning",
  "categories": ["research", "pdf"],
  "limit": 10
}
```

## Domain Filters

Use `includeDomains` to restrict results to specific domains, or `excludeDomains` to remove specific domains from the search. Domains should be hostnames only, without protocol or path.

`includeDomains` and `excludeDomains` are mutually exclusive.

### Include Domains Example

```json theme={null}
{
  "query": "web scraping",
  "includeDomains": ["firecrawl.dev", "docs.firecrawl.dev"],
  "limit": 10
}
```

### Exclude Domains Example

```json theme={null}
{
  "query": "web scraping tools",
  "excludeDomains": ["example.com"],
  "limit": 10
}
```

### Category Response

Each result includes a `category` field indicating its source:

```json theme={null}
{
  "success": true,
  "data": {
    "web": [
      {
        "url": "https://arxiv.org/abs/2024.12345",
        "title": "ML Research Paper",
        "description": "Latest advances in machine learning",
        "category": "research"
      },
      {
        "url": "https://example.com/ml-survey.pdf",
        "title": "ML Survey",
        "description": "A survey of machine learning methods",
        "category": "pdf"
      }
    ]
  }
}
```

## Time-Based Search

Use the `tbs` parameter to filter results by time periods, including custom date ranges. See the [Search Feature documentation](https://docs.firecrawl.dev/features/search.md#time-based-search) for detailed examples and supported formats.

> Are you an AI agent that needs a Firecrawl API key? See [firecrawl.dev/agent-onboarding/SKILL.md](https://www.firecrawl.dev/agent-onboarding/SKILL.md) for automated onboarding instructions.


## OpenAPI

````yaml api-reference/v2-openapi.json POST /search
openapi: 3.0.0
info:
  title: Firecrawl API
  version: v2
  description: >-
    API for interacting with Firecrawl services to perform web scraping and
    crawling tasks.
  contact:
    name: Firecrawl Support
    url: https://firecrawl.dev/support
    email: support@firecrawl.dev
servers:
  - url: https://api.firecrawl.dev/v2
security:
  - bearerAuth: []
paths:
  /search:
    post:
      tags:
        - Search
      summary: Search and optionally scrape search results
      operationId: searchAndScrape
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                query:
                  type: string
                  description: The search query
                  maxLength: 500
                limit:
                  type: integer
                  description: >-
                    Maximum number of results to return (per source type when
                    using multiple sources)
                  default: 10
                  maximum: 100
                  minimum: 1
                sources:
                  type: array
                  items:
                    oneOf:
                      - type: object
                        title: Web
                        properties:
                          type:
                            type: string
                            enum:
                              - web
                          tbs:
                            type: string
                            description: >-
                              Time-based search parameter. Supports predefined
                              time ranges (`qdr:h`, `qdr:d`, `qdr:w`, `qdr:m`,
                              `qdr:y`), custom date ranges
                              (`cdr:1,cd_min:MM/DD/YYYY,cd_max:MM/DD/YYYY`), and
                              sort by date (`sbd:1`). Values can be combined,
                              e.g. `sbd:1,qdr:w`.
                          location:
                            type: string
                            description: Location parameter for search results
                        required:
                          - type
                      - type: object
                        title: Images
                        properties:
                          type:
                            type: string
                            enum:
                              - images
                        required:
                          - type
                      - type: object
                        title: News
                        properties:
                          type:
                            type: string
                            enum:
                              - news
                        required:
                          - type
                      - type: object
                        title: Alexandria
                        properties:
                          type:
                            type: string
                            enum:
                              - alexandria
                        required:
                          - type
                        additionalProperties: false
                  description: >-
                    Sources to search. Will determine the arrays available in
                    the response. Defaults to ['web']. The plain string form
                    (e.g. `["web", "alexandria"]`) is also accepted. The
                    `alexandria` source returns tool contracts discovered from
                    the Alexandria catalogue in `data.tools` instead of search
                    results; it is free and is never counted in `creditsUsed`.
                    Requires the team's Alexandria access to be enabled (403
                    otherwise).
                  default:
                    - type: web
                domainTools:
                  type: boolean
                  description: >-
                    Include tool contracts whose provider matches the domains of
                    the returned web results. Defaults to on when `alexandria`
                    is among the sources; set `false` to disable, or `true`
                    alone to add domain-matched tools beside ordinary web
                    results. Free.
                toolDetail:
                  type: string
                  enum:
                    - compact
                    - summary
                    - full
                  default: compact
                  description: >-
                    How much of each tool contract to return in `data.tools`.
                    `compact` returns only `provider`, `capability`, and
                    `description`. `summary` returns the full tool entry without
                    `options` and `response`. `full` also returns `options`,
                    `response`, and `examples`.
                categories:
                  type: array
                  items:
                    oneOf:
                      - type: object
                        title: Developer
                        properties:
                          type:
                            type: string
                            enum:
                              - developer
                        required:
                          - type
                      - type: object
                        title: Gov
                        properties:
                          type:
                            type: string
                            enum:
                              - gov
                        required:
                          - type
                      - type: object
                        title: Research
                        properties:
                          type:
                            type: string
                            enum:
                              - research
                        required:
                          - type
                      - type: object
                        title: PDF
                        properties:
                          type:
                            type: string
                            enum:
                              - pdf
                        required:
                          - type
                  description: >-
                    Categories to filter results by. Defaults to [], which means
                    results will not be filtered by any categories.
                includeDomains:
                  type: array
                  items:
                    type: string
                    format: hostname
                  description: >-
                    Restricts search results to the specified domains. Domains
                    should be hostnames only, without protocol or path. Cannot
                    be used with excludeDomains.
                excludeDomains:
                  type: array
                  items:
                    type: string
                    format: hostname
                  description: >-
                    Excludes search results from the specified domains. Domains
                    should be hostnames only, without protocol or path. Cannot
                    be used with includeDomains.
                tbs:
                  type: string
                  description: >-
                    Time-based search parameter. Supports predefined time ranges
                    (`qdr:h`, `qdr:d`, `qdr:w`, `qdr:m`, `qdr:y`), custom date
                    ranges (`cdr:1,cd_min:MM/DD/YYYY,cd_max:MM/DD/YYYY`), and
                    sort by date (`sbd:1`). Values can be combined, e.g.
                    `sbd:1,qdr:w`.
                location:
                  type: string
                  description: >-
                    Location parameter for search results (e.g. `San
                    Francisco,California,United States`). For best results, set
                    both this and the `country` parameter.
                country:
                  type: string
                  description: >-
                    ISO country code for geo-targeting search results (e.g.
                    `US`). For best results, set both this and the `location`
                    parameter.
                  default: US
                safe:
                  type: boolean
                  description: >-
                    When `true`, filters explicit content from search results
                    (SafeSearch). Omit to keep the default behavior, which does
                    not apply the filter.
                timeout:
                  type: integer
                  description: Timeout in milliseconds
                  default: 60000
                ignoreInvalidURLs:
                  type: boolean
                  description: >-
                    Excludes URLs from the search results that are invalid for
                    other Firecrawl endpoints. This helps reduce errors if you
                    are piping data from search into other Firecrawl API
                    endpoints.
                  default: false
                highlights:
                  type: boolean
                  description: >-
                    Generate query-relevant highlights for search results. Set
                    to false to return provider descriptions or snippets without
                    highlighting.
                  default: true
                enterprise:
                  type: array
                  items:
                    type: string
                    enum:
                      - anon
                      - zdr
                  description: >-
                    Enterprise search options for Zero Data Retention (ZDR). Use
                    `["zdr"]` for end-to-end ZDR (10 credits / 10 results) or
                    `["anon"]` for anonymized ZDR (2 credits / 10 results). Must
                    be enabled for your team.
                scrapeOptions:
                  allOf:
                    - $ref: '#/components/schemas/ScrapeOptions'
                  description: Options for scraping search results
                  default: {}
                threatProtection:
                  $ref: '#/components/schemas/ThreatProtectionOverride'
              required:
                - query
      responses:
        '200':
          description: Successful response
          content:
            application/json:
              schema:
                type: object
                properties:
                  success:
                    type: boolean
                  data:
                    type: object
                    properties:
                      web:
                        type: array
                        items:
                          type: object
                          properties:
                            title:
                              type: string
                              description: Title from search result
                            description:
                              type: string
                              description: Description from search result
                            url:
                              type: string
                              description: URL of the search result
                            markdown:
                              type: string
                              nullable: true
                              description: Markdown content if scraping was requested
                            html:
                              type: string
                              nullable: true
                              description: HTML content if requested in formats
                            rawHtml:
                              type: string
                              nullable: true
                              description: Raw HTML content if requested in formats
                            links:
                              type: array
                              items:
                                type: string
                              description: Links found if requested in formats
                            screenshot:
                              type: string
                              nullable: true
                              description: >-
                                Screenshot URL if requested in formats.
                                Screenshots expire after 24 hours and can no
                                longer be downloaded.
                            audio:
                              type: string
                              nullable: true
                              description: >-
                                Signed URL to the extracted MP3 audio file if
                                `audio` is in `formats`. The signed URL expires
                                after 1 hour.
                            video:
                              type: string
                              nullable: true
                              description: >-
                                Signed URL to the extracted video file if
                                `video` is in `formats`. The signed URL expires
                                after 1 hour.
                            metadata:
                              type: object
                              properties:
                                title:
                                  type: string
                                description:
                                  type: string
                                sourceURL:
                                  type: string
                                  description: >-
                                    The original URL that was requested. May
                                    differ from the page's final URL if
                                    redirects occurred.
                                url:
                                  type: string
                                  description: >-
                                    The final URL of the page after all
                                    redirects have been followed.
                                statusCode:
                                  type: integer
                                numPages:
                                  type: integer
                                  description: >-
                                    For PDF inputs, the number of pages parsed
                                    (capped by the parsers maxPages option).
                                totalPages:
                                  type: integer
                                  description: >-
                                    For PDF inputs, the document's true page
                                    count before any maxPages capping. Omitted
                                    when it cannot be determined; a totalPages
                                    greater than numPages indicates the result
                                    was truncated.
                                error:
                                  type: string
                                  nullable: true
                      images:
                        type: array
                        items:
                          type: object
                          properties:
                            title:
                              type: string
                              description: Title from search result
                            imageUrl:
                              type: string
                              description: URL of the image
                            imageWidth:
                              type: integer
                              description: Width of the image
                            imageHeight:
                              type: integer
                              description: Height of the image
                            url:
                              type: string
                              description: URL of the search result
                            position:
                              type: integer
                              description: Position of the search result
                      news:
                        type: array
                        items:
                          type: object
                          properties:
                            title:
                              type: string
                              description: Title of the article
                            snippet:
                              type: string
                              description: Snippet from the article
                            url:
                              type: string
                              description: URL of the article
                            date:
                              type: string
                              description: Date of the article
                            imageUrl:
                              type: string
                              description: Image URL of the article
                            position:
                              type: integer
                              description: Position of the article
                            markdown:
                              type: string
                              nullable: true
                              description: Markdown content if scraping was requested
                            html:
                              type: string
                              nullable: true
                              description: HTML content if requested in formats
                            rawHtml:
                              type: string
                              nullable: true
                              description: Raw HTML content if requested in formats
                            links:
                              type: array
                              items:
                                type: string
                              description: Links found if requested in formats
                            screenshot:
                              type: string
                              nullable: true
                              description: >-
                                Screenshot URL if requested in formats.
                                Screenshots expire after 24 hours and can no
                                longer be downloaded.
                            audio:
                              type: string
                              nullable: true
                              description: >-
                                Signed URL to the extracted MP3 audio file if
                                `audio` is in `formats`. The signed URL expires
                                after 1 hour.
                            video:
                              type: string
                              nullable: true
                              description: >-
                                Signed URL to the extracted video file if
                                `video` is in `formats`. The signed URL expires
                                after 1 hour.
                            metadata:
                              type: object
                              properties:
                                title:
                                  type: string
                                description:
                                  type: string
                                sourceURL:
                                  type: string
                                  description: >-
                                    The original URL that was requested. May
                                    differ from the page's final URL if
                                    redirects occurred.
                                url:
                                  type: string
                                  description: >-
                                    The final URL of the page after all
                                    redirects have been followed.
                                statusCode:
                                  type: integer
                                numPages:
                                  type: integer
                                  description: >-
                                    For PDF inputs, the number of pages parsed
                                    (capped by the parsers maxPages option).
                                totalPages:
                                  type: integer
                                  description: >-
                                    For PDF inputs, the document's true page
                                    count before any maxPages capping. Omitted
                                    when it cannot be determined; a totalPages
                                    greater than numPages indicates the result
                                    was truncated.
                                error:
                                  type: string
                                  nullable: true
                      tools:
                        type: array
                        description: >-
                          Tool contracts discovered from the Alexandria
                          catalogue. Present when `alexandria` is among the
                          sources or when `domainTools` was requested; up to
                          `limit` results per discovery source (semantic matches
                          from the `alexandria` source, domain matches from
                          `domainTools`).
                        items:
                          $ref: '#/components/schemas/DiscoveredTool'
                    description: >-
                      The search results. The arrays available will depend on
                      the sources you specified in the request. By default, the
                      `web` array will be returned.
                  warning:
                    type: string
                    nullable: true
                    description: >-
                      Warning message if any issues occurred. Includes `Some
                      tool discovery results are unavailable.` when Alexandria
                      or domain tool discovery partially failed.
                  id:
                    type: string
                    description: The ID of the search job
                  creditsUsed:
                    type: integer
                    description: The number of credits used for the search
        '408':
          description: Request timeout
          content:
            application/json:
              schema:
                type: object
                properties:
                  success:
                    type: boolean
                    example: false
                  error:
                    type: string
                    example: Request timed out
        '500':
          description: Server error
          content:
            application/json:
              schema:
                type: object
                properties:
                  success:
                    type: boolean
                    example: false
                  code:
                    type: string
                    example: UNKNOWN_ERROR
                  error:
                    type: string
                    example: An unexpected error occurred on the server.
      security:
        - bearerAuth: []
components:
  schemas:
    ScrapeOptions:
      type: object
      properties:
        formats:
          $ref: '#/components/schemas/Formats'
        onlyMainContent:
          type: boolean
          description: >-
            Only return the main content of the page excluding headers, navs,
            footers, etc. This is a deterministic HTML-level filter applied
            before markdown is generated; no LLM is involved.
          default: true
        onlyCleanContent:
          type: boolean
          description: >-
            Beta. Run an additional LLM-based pass over the generated markdown
            to remove residual boilerplate that `onlyMainContent` can miss
            (cookie banners, ad blocks, social share widgets, breadcrumbs,
            newsletter signups, comment sections, related-article lists).
            Headings, lists, tables, code blocks, image references, and inline
            links are preserved. Can be combined with `onlyMainContent` (the
            most common setup) or used on its own. Skipped with a warning when
            the markdown exceeds the cleaning model's output token limit (the
            original markdown is preserved). Not supported on
            zero-data-retention requests.
          default: false
        includeTags:
          type: array
          items:
            type: string
          description: Tags to include in the output.
        excludeTags:
          type: array
          items:
            type: string
          description: Tags to exclude from the output.
        maxAge:
          type: integer
          description: >-
            Returns a cached version of the page if it is younger than this age
            in milliseconds. If a cached version of the page is older than this
            value, the page will be scraped. If you do not need extremely fresh
            data, enabling this can speed up your scrapes by 500%. Defaults to 2
            days.
          default: 172800000
        minAge:
          type: integer
          description: >-
            When set, the request only checks the cache and never triggers a
            fresh scrape. The value is in milliseconds and specifies the minimum
            age the cached data must be. If matching cached data exists, it is
            returned instantly. If no cached data is found, a 404 with error
            code SCRAPE_NO_CACHED_DATA is returned. Set to 1 to accept any
            cached data regardless of age.
        headers:
          type: object
          description: >-
            Headers to send with the request. Can be used to send cookies,
            user-agent, etc.
        waitFor:
          type: integer
          description: >-
            Specify a delay in milliseconds before fetching the content,
            allowing the page sufficient time to load. This waiting time is in
            addition to Firecrawl's smart wait feature.
          default: 0
          maximum: 60000
        mobile:
          type: boolean
          description: >-
            Set to true if you want to emulate scraping from a mobile device.
            Useful for testing responsive pages and taking mobile screenshots.
          default: false
        skipTlsVerification:
          type: boolean
          description: Skip TLS certificate verification when making requests.
          default: true
        timeout:
          type: integer
          description: >-
            Timeout in milliseconds for the request. Minimum is 1000 (1 second).
            Default is 60000 (60 seconds). Maximum is 300000 (300 seconds).
          default: 60000
          minimum: 1000
          maximum: 300000
        parsers:
          type: array
          description: >-
            Controls how files are processed during scraping. Each item is a
            parser name (`"pdf"` or `"image"`) or a parser object. Both parsers
            are on by default.

             - **pdf**: PDF content is extracted and converted to markdown format, with billing based on the number of pages (1 credit per page).
             - **image**: Raster images (PNG, JPEG, JPEG 2000, TIFF, GIF, BMP, WebP, AVIF) are OCR'd as one-page documents and converted to markdown. SVG and HEIC are not supported.

            If you pass a list, parsers that are not in the list are off. For
            example, `["pdf"]` turns off image OCR, so image URLs fail as
            unsupported files. When an empty array is passed, the PDF file is
            returned in base64 encoding with a flat rate of 1 credit for the
            entire PDF.
          items:
            oneOf:
              - title: Parser name
                type: string
                enum:
                  - pdf
                  - image
                description: >-
                  Shorthand for a parser object with default options. `"pdf"` is
                  the same as `{ "type": "pdf" }`.
              - title: PDF
                type: object
                properties:
                  type:
                    type: string
                    enum:
                      - pdf
                  mode:
                    type: string
                    enum:
                      - fast
                      - auto
                      - ocr
                    default: auto
                    description: >-
                      PDF parsing mode. "fast": text-based extraction only
                      (embedded text, fastest). "auto" (default): attempts fast
                      extraction first, falls back to OCR if needed. "ocr":
                      forces OCR parsing on every page.
                  maxPages:
                    type: integer
                    minimum: 1
                    maximum: 10000
                    description: >-
                      Maximum number of pages to parse from the PDF. Must be a
                      positive integer up to 10000.
                  pages:
                    type: boolean
                    default: false
                    description: >-
                      Include physical per-page markdown alongside the document
                      markdown. Populates the `pages` field on the document as
                      an array of { pageNumber, markdown }. No additional cost.
                  blocks:
                    type: boolean
                    default: false
                    description: >-
                      Include per-page typed layout blocks alongside the
                      document markdown. Populates the `blocks` field on the
                      document: typed blocks (title, section_header, text,
                      table, formula, figure, caption, ...) with normalized
                      bounding boxes, reading order, character-span links into
                      the markdown, and per-block confidence. No additional
                      cost.
                  pageMarkers:
                    type: boolean
                    default: false
                    description: >-
                      Annotate page breaks in the document markdown: pages are
                      joined with `\n\n---\n\n<!-- page N -->\n\n`, where N is
                      the 1-based physical page of the content that follows.
                      Markers appear between pages only (no leading marker for
                      page 1), and numbering may skip pages merged across a page
                      break — use `pages: true` when every physical page is
                      needed. No new response field; no additional cost.
                required:
                  - type
                additionalProperties: false
              - title: Image
                type: object
                description: >-
                  Image OCR parser. It has no options. The PDF options (`mode`,
                  `maxPages`, `pages`, `blocks`, `pageMarkers`) do not apply to
                  images.
                properties:
                  type:
                    type: string
                    enum:
                      - image
                required:
                  - type
                additionalProperties: false
          default:
            - pdf
            - image
        actions:
          type: array
          description: Actions to perform on the page before grabbing the content
          items:
            oneOf:
              - title: Wait
                oneOf:
                  - type: object
                    title: Wait by Duration
                    properties:
                      type:
                        type: string
                        enum:
                          - wait
                        description: Wait for a specified amount of milliseconds
                      milliseconds:
                        type: integer
                        minimum: 1
                        description: Number of milliseconds to wait
                    required:
                      - type
                      - milliseconds
                    additionalProperties: false
                  - type: object
                    title: Wait for Element
                    properties:
                      type:
                        type: string
                        enum:
                          - wait
                        description: Wait for a specific element to appear
                      selector:
                        type: string
                        description: CSS selector to wait for
                        example: '#my-element'
                    required:
                      - type
                      - selector
                    additionalProperties: false
              - type: object
                title: Screenshot
                properties:
                  type:
                    type: string
                    enum:
                      - screenshot
                    description: >-
                      Take a screenshot. The links will be in the response's
                      `actions.screenshots` array.
                  fullPage:
                    type: boolean
                    description: >-
                      Whether to capture a full-page screenshot (ignores
                      viewport.height) or limit to the current viewport.
                    default: false
                  quality:
                    type: integer
                    description: >-
                      The quality of the screenshot, from 1 to 100. 100 is the
                      highest quality.
                  viewport:
                    type: object
                    properties:
                      width:
                        type: integer
                        description: The width of the viewport in pixels
                      height:
                        type: integer
                        description: The height of the viewport in pixels
                    required:
                      - width
                      - height
                required:
                  - type
              - type: object
                title: Click
                properties:
                  type:
                    type: string
                    enum:
                      - click
                    description: Click on an element
                  selector:
                    type: string
                    description: Query selector to find the element by
                    example: '#load-more-button'
                  all:
                    type: boolean
                    description: >-
                      Clicks all elements matched by the selector, not just the
                      first one. Does not throw an error if no elements match
                      the selector.
                    default: false
                required:
                  - type
                  - selector
              - type: object
                title: Write text
                properties:
                  type:
                    type: string
                    enum:
                      - write
                    description: >-
                      Write text into an input field, text area, or
                      contenteditable element. Note: You must first focus the
                      element using a 'click' action before writing. The text
                      will be typed character by character to simulate keyboard
                      input.
                  text:
                    type: string
                    description: Text to type
                    example: Hello, world!
                required:
                  - type
                  - text
              - type: object
                title: Press a key
                description: >-
                  Press a key on the page. See
                  https://asawicki.info/nosense/doc/devices/keyboard/key_codes.html
                  for key codes.
                properties:
                  type:
                    type: string
                    enum:
                      - press
                    description: Press a key on the page
                  key:
                    type: string
                    description: Key to press
                    example: Enter
                required:
                  - type
                  - key
              - type: object
                title: Scroll
                properties:
                  type:
                    type: string
                    enum:
                      - scroll
                    description: Scroll the page or a specific element
                  direction:
                    type: string
                    enum:
                      - up
                      - down
                    description: Direction to scroll
                    default: down
                  selector:
                    type: string
                    description: Query selector for the element to scroll
                    example: '#my-element'
                required:
                  - type
              - type: object
                title: Scrape
                properties:
                  type:
                    type: string
                    enum:
                      - scrape
                    description: >-
                      Scrape the current page content, returns the url and the
                      html.
                required:
                  - type
              - type: object
                title: Execute JavaScript
                properties:
                  type:
                    type: string
                    enum:
                      - executeJavascript
                    description: Execute JavaScript code on the page
                  script:
                    type: string
                    description: JavaScript code to execute
                    example: document.querySelector('.button').click();
                required:
                  - type
                  - script
              - type: object
                title: Generate PDF
                properties:
                  type:
                    type: string
                    enum:
                      - pdf
                    description: >-
                      Generate a PDF of the current page. The PDF will be
                      returned in the `actions.pdfs` array of the response.
                  format:
                    type: string
                    enum:
                      - A0
                      - A1
                      - A2
                      - A3
                      - A4
                      - A5
                      - A6
                      - Letter
                      - Legal
                      - Tabloid
                      - Ledger
                    description: The page size of the resulting PDF
                    default: Letter
                  landscape:
                    type: boolean
                    description: Whether to generate the PDF in landscape orientation
                    default: false
                  scale:
                    type: number
                    description: The scale multiplier of the resulting PDF
                    default: 1
                required:
                  - type
        location:
          type: object
          description: >-
            Location settings for the request. When specified, this will use an
            appropriate proxy if available and emulate the corresponding
            language and timezone settings. Defaults to 'US' if not specified.
          properties:
            country:
              type: string
              description: ISO 3166-1 alpha-2 country code (e.g., 'US', 'AU', 'DE', 'JP')
              pattern: ^[A-Z]{2}$
              default: US
            languages:
              type: array
              description: >-
                Preferred languages and locales for the request in order of
                priority. Defaults to the language of the specified location.
                See
                https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Accept-Language
              items:
                type: string
                example: en-US
        removeBase64Images:
          type: boolean
          description: >-
            Removes all base 64 images from the markdown output, which may be
            overwhelmingly long. This does not affect html or rawHtml formats.
            The image's alt text remains in the output, but the URL is replaced
            with a placeholder.
          default: true
        blockAds:
          type: boolean
          description: Enables ad-blocking and cookie popup blocking.
          default: true
        proxy:
          type: string
          enum:
            - basic
            - enhanced
            - auto
          description: |-
            Specifies the type of proxy to use.

             - **basic**: Proxies for scraping sites with none to basic anti-bot solutions. Fast and usually works.
             - **enhanced**: Enhanced proxies for scraping sites with advanced anti-bot solutions. Slower, but more reliable on certain sites. Billed at the same credit cost as basic.
             - **auto**: Firecrawl will automatically retry scraping with enhanced proxies if the basic proxy fails. Enhanced proxies carry no credit surcharge, so either way only the regular cost is billed.
          default: auto
        storeInCache:
          type: boolean
          description: >-
            If true, the page will be stored in the Firecrawl index and cache.
            Setting this to false is useful if your scraping activity may have
            data protection concerns. Using some parameters associated with
            sensitive scraping (e.g. actions, headers) will force this parameter
            to be false.
          default: true
        lockdown:
          type: boolean
          description: >-
            If true, serves the request from Firecrawl's cache only and never
            makes an outbound request to the target URL. Designed for
            compliance-constrained or air-gapped environments where the scrape
            request itself could leak sensitive information. On cache miss,
            returns a 404 with error code SCRAPE_LOCKDOWN_CACHE_MISS (the URL is
            never logged on miss). Lockdown requests are treated as zero data
            retention. Default maxAge is extended to 2 years so existing cached
            pages remain eligible. Billed at 5 credits on hit, 1 credit on cache
            miss.
          default: false
        checkPromptInjection:
          type: boolean
          description: >-
            When enabled, scans the page content for prompt injection attempts
            before any LLM-backed format (such as json, summary or question)
            runs. Works with any format except rawBase64. If an injection is
            detected, the request fails with a 403 and error code
            SCRAPE_PROMPT_INJECTION_DETECTED. Adds 4 credits when the check
            runs. If the check cannot scan all of the content, the scrape
            continues with a warning and the check is not billed.
          default: false
        redactPII:
          oneOf:
            - type: boolean
            - $ref: '#/components/schemas/RedactPIIOptions'
          default: false
          description: >-
            Redact personally identifiable information from returned markdown.
            Pass `true` to use defaults, or an object to tune mode, entities,
            and replacement style.
        profile:
          type: object
          description: >-
            Enable persistent browser storage across scrape and interact
            sessions. Pass a profile when scraping to preserve cookies,
            localStorage, and session data. Sessions with the same profile name
            share browser state.
          properties:
            name:
              type: string
              minLength: 1
              maxLength: 128
              description: >-
                A name for the profile. Scrapes with the same name share browser
                state (cookies, localStorage, sessions).
            saveChanges:
              type: boolean
              default: true
              description: >-
                When true, browser state is saved back to the profile when the
                interact session stops. Set to false to load existing data
                without writing. Only one saving session is allowed at a time.
          required:
            - name
        threatProtection:
          $ref: '#/components/schemas/ThreatProtectionOverride'
        auditMetadata:
          $ref: '#/components/schemas/AuditMetadata'
    ThreatProtectionOverride:
      type: object
      title: Threat Protection Override
      description: >-
        Per-request [Threat
        Protection](https://docs.firecrawl.dev/features/threat-protection)
        override. Fields you provide replace the corresponding fields of your
        organization's policy for this request only; omitted fields keep their
        organization-level values. Requires Threat Protection to be enabled for
        your team (enterprise feature) — otherwise the request is rejected with
        a 403. If your organization has disabled request overrides, any request
        that includes this object is rejected with a 403. If Threat Protection
        is enforced for your team, `mode` may not be set to `off`.
      properties:
        mode:
          type: string
          enum:
            - 'off'
            - normal
          description: >-
            URL scanning mode for this request. `normal` checks URLs against
            Google Web Risk (+2 credits per URL scanned).
        riskScoreThreshold:
          type: integer
          minimum: 0
          maximum: 100
          description: >-
            Normalized risk score (0–100) at or above which a classifier verdict
            blocks the URL. Lower is stricter.
          example: 75
        blacklist:
          type: array
          maxItems: 1000
          items:
            type: string
          description: >-
            Domains to always block, as plain domains (`example.com`) or
            wildcard globs (`*.example.com`). No protocol, path, or port.
        whitelist:
          type: array
          maxItems: 1000
          items:
            type: string
          description: >-
            Domains to always allow, as plain domains or wildcard globs. Wins
            over every other rule.
        blockedTlds:
          type: array
          maxItems: 1000
          items:
            type: string
          description: >-
            Top-level domains to block outright, lowercase without the leading
            dot (e.g. `zip`).
        failurePolicy:
          type: string
          enum:
            - open
            - closed
          description: >-
            What to do when the classifier can't be reached: `closed` blocks the
            request, `open` allows it.
    DiscoveredTool:
      type: object
      description: >-
        A catalogued provider tool discovered via Alexandria, semantic search,
        or domain matching. The `toolDetail` request parameter sets which fields
        appear: `compact` returns only `provider`, `capability`, and
        `description`; `summary` adds the other fields except `options` and
        `response`; `full` also adds `options`, `response`, and `examples`.
      additionalProperties: true
      properties:
        id:
          type: string
          description: >-
            The tool's identifier, formatted as `provider/capability`. Omitted
            when `toolDetail` is `compact`.
        provider:
          type: string
          description: The catalogued provider.
        capability:
          type: string
          description: The provider-relative capability.
        name:
          type: string
          description: >-
            Human-readable name of the tool. Omitted when `toolDetail` is
            `compact`.
        description:
          type: string
          description: Human-readable description of what the tool does.
        creditsCost:
          type: integer
          minimum: 0
          description: >-
            Credits charged per execution of this tool. Omitted when
            `toolDetail` is `compact`.
        perRecord:
          type: boolean
          description: >-
            Whether `creditsCost` is charged per record returned rather than per
            call. Omitted when `toolDetail` is `compact`.
        options:
          type: array
          description: >-
            The capability's accepted options. Present only when `toolDetail` is
            `full`.
          items:
            type: object
            additionalProperties: true
            properties:
              name:
                type: string
                description: The option name.
              type:
                type: string
                description: The option's data type.
        response:
          type: object
          additionalProperties: true
          description: >-
            Description of the shape of a successful response's `data`. Present
            only when `toolDetail` is `full`.
          properties:
            about:
              type: string
              description: Human-readable description of the response payload.
            key:
              type: string
              description: >-
                The key under which the primary payload is returned, when
                applicable.
            fields:
              type: array
              description: The response's documented fields.
              items:
                type: object
                additionalProperties: true
        matchedBy:
          type: array
          description: Why this tool was surfaced. Omitted when `toolDetail` is `compact`.
          items:
            type: string
            enum:
              - semantic
              - domain
        matchedUrls:
          type: array
          description: >-
            URLs whose domain matched this tool, when matched by domain. Omitted
            when `toolDetail` is `compact`.
          items:
            type: string
      required:
        - provider
        - capability
        - description
    Formats:
      type: array
      items:
        oneOf:
          - type: object
            title: Markdown
            properties:
              type:
                type: string
                enum:
                  - markdown
            required:
              - type
          - type: object
            title: Summary
            properties:
              type:
                type: string
                enum:
                  - summary
            required:
              - type
          - type: object
            title: HTML
            properties:
              type:
                type: string
                enum:
                  - html
            required:
              - type
          - type: object
            title: Raw HTML
            properties:
              type:
                type: string
                enum:
                  - rawHtml
            required:
              - type
          - type: object
            title: Raw Base64
            properties:
              type:
                type: string
                enum:
                  - rawBase64
            required:
              - type
          - type: object
            title: Links
            properties:
              type:
                type: string
                enum:
                  - links
            required:
              - type
          - type: object
            title: Images
            properties:
              type:
                type: string
                enum:
                  - images
            required:
              - type
          - type: object
            title: Attributes
            description: >-
              Extract attribute values from the elements that match CSS
              selectors. Returns the values in the response `attributes` field.
            properties:
              type:
                type: string
                enum:
                  - attributes
              selectors:
                type: array
                description: The elements and attributes to extract.
                items:
                  type: object
                  properties:
                    selector:
                      type: string
                      description: CSS selector to find elements.
                    attribute:
                      type: string
                      description: >-
                        Attribute name to extract (for example
                        `data-vehicle-name` or `id`).
                  required:
                    - selector
                    - attribute
                  additionalProperties: false
            required:
              - type
              - selectors
          - type: object
            title: Screenshot
            properties:
              type:
                type: string
                enum:
                  - screenshot
              fullPage:
                type: boolean
                description: >-
                  Whether to capture a full-page screenshot (ignores
                  viewport.height) or limit to the current viewport.
                default: false
              quality:
                type: integer
                description: >-
                  The quality of the screenshot, from 1 to 100. 100 is the
                  highest quality.
              viewport:
                type: object
                properties:
                  width:
                    type: integer
                    description: The width of the viewport in pixels
                  height:
                    type: integer
                    description: The height of the viewport in pixels
                required:
                  - width
                  - height
            required:
              - type
          - type: object
            title: JSON
            properties:
              type:
                type: string
                enum:
                  - json
              schema:
                type: object
                description: >-
                  The schema to use for the JSON output. Must conform to [JSON
                  Schema](https://json-schema.org/).
              prompt:
                type: string
                description: The prompt to use for the JSON output
              checkPromptInjection:
                type: boolean
                deprecated: true
                description: >-
                  Deprecated: use the top-level `checkPromptInjection` scrape
                  option, which this value is merged into. Defaults to false.
                default: false
            required:
              - type
          - type: object
            title: Change Tracking
            properties:
              type:
                type: string
                enum:
                  - changeTracking
              modes:
                type: array
                items:
                  type: string
                  enum:
                    - git-diff
                    - json
                description: >-
                  The mode to use for change tracking. 'git-diff' provides a
                  detailed diff, and 'json' compares extracted JSON data.
              schema:
                type: object
                description: >-
                  Schema for JSON extraction when using 'json' mode. Defines the
                  structure of data to extract and compare. Must conform to
                  [JSON Schema](https://json-schema.org/).
              prompt:
                type: string
                description: >-
                  Prompt to use for change tracking when using 'json' mode. If
                  not provided, the default prompt will be used.
              tag:
                type: string
                nullable: true
                default: null
                description: >-
                  Tag to use for change tracking. Tags can separate change
                  tracking history into separate "branches", where change
                  tracking with a specific tagwill only compare to scrapes made
                  in the same tag. If not provided, the default tag (null) will
                  be used.
            required:
              - type
          - type: object
            title: Branding
            properties:
              type:
                type: string
                enum:
                  - branding
            required:
              - type
          - type: object
            title: Product
            properties:
              type:
                type: string
                enum:
                  - product
            required:
              - type
          - type: object
            title: Menu
            properties:
              type:
                type: string
                enum:
                  - menu
            required:
              - type
          - type: object
            title: Audio
            description: >-
              Extract audio (MP3) from supported video URLs, e.g. YouTube.
              Returns a signed GCS URL.
            properties:
              type:
                type: string
                enum:
                  - audio
            required:
              - type
          - type: object
            title: Video
            description: >-
              Extract best-quality video from supported video URLs, e.g.
              YouTube. Returns a signed GCS URL.
            properties:
              type:
                type: string
                enum:
                  - video
            required:
              - type
          - type: object
            title: Question
            description: >-
              Ask a natural-language question about the page. Returns the answer
              in the response `answer` field.
            properties:
              type:
                type: string
                enum:
                  - question
              question:
                type: string
                maxLength: 10000
                description: >-
                  The question to answer about the page. Maximum 10,000
                  characters.
            required:
              - type
              - question
          - type: object
            title: Highlights
            description: >-
              Find relevant source text from the page. Returns the selected text
              in the response `highlights` field.
            properties:
              type:
                type: string
                enum:
                  - highlights
              query:
                type: string
                maxLength: 10000
                description: >-
                  The text-selection query to run against the page. Maximum
                  10,000 characters.
            required:
              - type
              - query
      description: >-
        Output formats to include in the response. You can specify one or more
        formats, either as strings (e.g., `'markdown'`) or as objects with
        additional options (e.g., `{ type: 'json', schema: {...} }`). Some
        formats require specific options to be set. Example: `['markdown', {
        type: 'json', schema: {...} }]`.
      default:
        - type: markdown
    RedactPIIOptions:
      type: object
      description: Tuning options for PII redaction.
      properties:
        mode:
          type: string
          enum:
            - accurate
            - aggressive
            - fast
          default: accurate
          description: >-
            Redaction strategy. `accurate` is model-only and optimized for
            precision, `aggressive` increases recall with additional heuristics,
            and `fast` uses heuristics without the model call.
        entities:
          type: array
          description: >-
            Restrict redaction to these entity buckets. If omitted, all
            supported entities are redacted.
          items:
            $ref: '#/components/schemas/RedactPIIEntity'
        replaceStyle:
          type: string
          enum:
            - tag
            - mask
            - remove
          default: tag
          description: >-
            `tag` replaces spans with placeholders like `<EMAIL>`, `mask`
            replaces characters with `*`, and `remove` deletes the span text.
      additionalProperties: false
    AuditMetadata:
      type: object
      description: >-
        User attribution included with SIEM logging events when SIEM Logging is
        enabled for the organization.
      additionalProperties: false
      required:
        - username
      properties:
        username:
          type: string
          maxLength: 1024
          description: The username associated with the request.
    RedactPIIEntity:
      type: string
      enum:
        - PERSON
        - EMAIL
        - PHONE
        - LOCATION
        - FINANCIAL
        - SECRET
      description: Public PII entity buckets supported by Firecrawl redaction.
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````

This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.
