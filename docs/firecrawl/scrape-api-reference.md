> Source: https://docs.firecrawl.dev/api-reference/endpoint/scrape.md
> Retrieved: 2026-10-31
> Covers: POST /v2/scrape (API reference / OpenAPI)


# Scrape

## Capabilities

[Capabilities](https://docs.firecrawl.dev/capabilities) is the single page listing what a scrape can do to a page, which of those capabilities run in a self-hosted deployment, and which endpoints accept a request with no API key.

## Interactions

For browser interactions (clicking, typing, navigating, extracting dynamic content), use the [Interact endpoint](https://docs.firecrawl.dev/features/interact.md). Scrape a page first, then call `POST /v2/scrape/{scrapeId}/interact` with a natural-language prompt or Playwright code to take actions on the page.

See the [Interact documentation](https://docs.firecrawl.dev/features/interact.md) for full details and examples.

Optionally you can also use the `actions` parameter, although it's not recommended to use it for complex interactions.

> Are you an AI agent that needs a Firecrawl API key? See [firecrawl.dev/agent-onboarding/SKILL.md](https://www.firecrawl.dev/agent-onboarding/SKILL.md) for automated onboarding instructions.


## OpenAPI

````yaml api-reference/v2-openapi.json POST /scrape
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
  /scrape:
    post:
      tags:
        - Scraping
      summary: Scrape a single URL and optionally extract information using an LLM
      operationId: scrapeAndExtractFromUrl
      requestBody:
        required: true
        content:
          application/json:
            schema:
              allOf:
                - type: object
                  properties:
                    url:
                      type: string
                      format: uri
                      description: The URL to scrape
                  required:
                    - url
                - $ref: '#/components/schemas/ScrapeOptions'
                - type: object
                  properties:
                    zeroDataRetention:
                      type: boolean
                      default: false
                      description: >-
                        If true, this will enable zero data retention for this
                        scrape. To enable this feature, please contact
                        help@firecrawl.dev
                - type: object
                  properties:
                    alexandria:
                      oneOf:
                        - $ref: '#/components/schemas/AlexandriaCall'
                        - type: array
                          minItems: 1
                          maxItems: 10
                          items:
                            $ref: '#/components/schemas/AlexandriaCall'
                      description: >-
                        Execute one or more catalogued provider tools instead of
                        scraping a URL. Cannot be combined with `url`,
                        `formats`, or other scrape options (400); the only
                        allowed sibling keys are `timeout`, `origin`, and
                        `integration`. Use the `x-request-id` request header as
                        a client-chosen idempotency key (1 to 128 characters of
                        letters, digits, `.`, `_`, `:`, `-`) — it is echoed
                        back, and a completed request with the same key replays
                        its original response and `scrape_id` instead of
                        re-executing. To browse the catalogue and read tool
                        contracts for free, call Find Tools: set `provider` to
                        `firecrawl`, `capability` to `find-tools`, and `options`
                        to a `FindToolsOptions` object. The result `data` is a
                        `FindToolsData` page.
                    domainTools:
                      type: boolean
                      default: false
                      description: >-
                        When true on an ordinary URL scrape, `data.tools` lists
                        tool contracts matched to the scraped page's domain
                        (same `DiscoveredTool` shape as search). Requires the
                        team's Alexandria access to be enabled and no zero data
                        retention (403 otherwise). Free.
                    toolDetail:
                      type: string
                      enum:
                        - compact
                        - summary
                        - full
                      description: >-
                        How much of each tool contract to return in `data.tools`
                        when `domainTools` is true. `compact` returns only
                        `provider`, `capability`, and `description`. `summary`
                        returns the full tool entry without `options` and
                        `response`. `full` also returns `options`, `response`,
                        and `examples`. If you omit it, tools are returned as
                        with `summary`.
            examples:
              scrapeUrl:
                summary: Scrape a URL
                value:
                  url: https://example.com
                  formats:
                    - markdown
              findTools:
                summary: 'Find Tools: browse the Alexandria catalogue (free)'
                description: >-
                  Calls the `firecrawl/find-tools` capability. It lists the
                  tools of the `particle` provider and does not execute them.
                  Follow an item's `next` call, or the page's `next` call, with
                  another `alexandria` request.
                value:
                  alexandria:
                    provider: firecrawl
                    capability: find-tools
                    options:
                      providers:
                        - particle
                      level: tools
                      expand:
                        - options
                        - response
                      limit: 2
      responses:
        '200':
          description: Successful response
          content:
            application/json:
              schema:
                oneOf:
                  - $ref: '#/components/schemas/ScrapeResponse'
                  - $ref: '#/components/schemas/AlexandriaScrapeResponse'
        '400':
          description: Bad request
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
                    example: >-
                      Bad request. `alexandria` cannot be combined with `url`,
                      `formats`, or other scrape options, and only recognizes
                      `provider`, `capability`, and `options`.
                  code:
                    type: string
                  chargeId:
                    type: string
        '402':
          description: >-
            Payment required. Also returned as `insufficient_credits` when the
            team lacks the credits to execute an `alexandria` request; in that
            case nothing is executed.
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
                    example: Payment required to access this resource.
                  code:
                    type: string
                    example: insufficient_credits
                  chargeId:
                    type: string
        '403':
          description: >-
            Forbidden. Returned when `alexandria` execution or `domainTools` is
            not enabled for the team, when zero data retention is active, or
            when third-party data terms have not been accepted
            (`THIRD_PARTY_DATA_TERMS_REQUIRED`, which includes
            `requiresAction`).
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
                  code:
                    type: string
                    example: THIRD_PARTY_DATA_TERMS_REQUIRED
                  requiresAction:
                    type: object
                    description: >-
                      Present with `THIRD_PARTY_DATA_TERMS_REQUIRED`. Tells you
                      which provider terms an organization admin must accept
                      before you retry this request.
                    properties:
                      type:
                        type: string
                        enum:
                          - accept_terms
                        description: The action to take. Always `accept_terms`.
                      terms:
                        type: string
                        description: The provider whose terms must be accepted.
                      version:
                        type: string
                        description: >-
                          The version of the provider's terms that must be
                          accepted.
                      url:
                        type: string
                        format: uri
                        description: >-
                          The dashboard page where a human (an organization
                          admin) accepts the terms. Send this URL to a person;
                          do not accept the terms automatically.
                    required:
                      - type
                      - terms
                      - version
                      - url
                  chargeId:
                    type: string
        '404':
          description: >-
            Not found. Returned as `unknown_provider` when an `alexandria` call
            references a provider or capability that does not exist; nothing is
            executed.
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
                  code:
                    type: string
                    example: unknown_provider
                  chargeId:
                    type: string
        '409':
          description: >-
            Conflict. Returned as `duplicate_request` or `request_in_flight`
            when the same `x-request-id` is reused while the original request is
            still being processed or was already completed with different
            parameters.
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
                  code:
                    type: string
                    example: duplicate_request
                  chargeId:
                    type: string
                    description: The charge ID of the in-flight or original request.
        '429':
          description: Too many requests
          content:
            application/json:
              schema:
                type: object
                properties:
                  error:
                    type: string
                    example: >-
                      Request rate limit exceeded. Please wait and try again
                      later.
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
        '503':
          description: >-
            Service unavailable. Returned as `request_unresolved` when the
            outcome of an in-flight `alexandria` request with this
            `x-request-id` could not be determined — keep the same
            `x-request-id` and retry rather than issuing a new request. Also
            returned as `billing_unavailable` when credits could not be charged.
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
                  code:
                    type: string
                    example: request_unresolved
                  chargeId:
                    type: string
                    description: >-
                      The charge ID of the unresolved request. Reuse the same
                      `x-request-id` to retry; do not create a new request.
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
    AlexandriaCall:
      type: object
      description: A single provider tool to execute from the Alexandria catalogue.
      properties:
        provider:
          type: string
          minLength: 1
          maxLength: 200
          description: The catalogued provider to call, e.g. `fred`.
        capability:
          type: string
          minLength: 1
          maxLength: 200
          description: >-
            The provider-relative capability to invoke, e.g.
            `series/observations`.
        options:
          type: object
          default: {}
          description: >-
            Capability-specific options passed through to the provider tool. For
            Find Tools (`provider: firecrawl`, `capability: find-tools`), use
            `FindToolsOptions`.
          anyOf:
            - $ref: '#/components/schemas/FindToolsOptions'
            - type: object
              title: Capability options
              description: Options for any other capability, as its contract defines them.
              additionalProperties: true
      required:
        - provider
        - capability
    ScrapeResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: object
          properties:
            markdown:
              type: string
            pages:
              type: array
              nullable: true
              description: >-
                Physical per-page markdown for PDFs. Present only when the
                request set the `pages` PDF parser option.
              items:
                type: object
                properties:
                  pageNumber:
                    type: integer
                    description: 1-based physical PDF page number.
                  markdown:
                    type: string
            blocks:
              type: array
              nullable: true
              description: >-
                Per-page typed layout blocks for PDFs. Present only when the
                request set the `blocks` PDF parser option.
              items:
                type: object
                properties:
                  pageNumber:
                    type: integer
                    description: 1-based physical PDF page number.
                  width:
                    type: number
                    nullable: true
                    description: >-
                      Page render width in px — the anchor for denormalizing
                      bbox coordinates. Null for pages that never rendered.
                  height:
                    type: number
                    nullable: true
                    description: >-
                      Page render height in px. Null for pages that never
                      rendered.
                  status:
                    type: string
                    description: 'Page-level rollup: ok | partial | failed.'
                  items:
                    type: array
                    items:
                      type: object
                      properties:
                        id:
                          type: string
                          description: >-
                            Stable within a response: p<page>.b<index in reading
                            order>.
                        type:
                          type: string
                          description: >-
                            Block type: title, section_header, text, table,
                            formula, figure, caption, page_number, page_header,
                            page_footer. New types may appear over time.
                        label:
                          type: string
                          nullable: true
                          description: >-
                            Raw layout-model label, passthrough for forward
                            compatibility.
                        bbox:
                          type: array
                          nullable: true
                          minItems: 4
                          maxItems: 4
                          items:
                            type: number
                          description: >-
                            [x0, y0, x1, y1] normalized 0-1 relative to the page
                            width/height. Multiply by the page width/height to
                            get pixel coordinates. Null when the page has no
                            known dimensions.
                        content:
                          type: string
                          description: >-
                            Markdown fragment this block contributed to the
                            document markdown.
                        markdownSpan:
                          type: array
                          nullable: true
                          minItems: 2
                          maxItems: 2
                          items:
                            type: integer
                          description: >-
                            [start, end) character offsets into the document
                            markdown covering this block's fragment. Null when a
                            post-processing transform rewrote the fragment.
                        readingOrder:
                          type: integer
                        source:
                          type: string
                          nullable: true
                          description: >-
                            Pipeline path that produced the block (for example
                            native_text, layout_ocr, tsr, formula_model,
                            full_page).
                        confidence:
                          type: object
                          properties:
                            layout:
                              type: number
                              nullable: true
                              description: >-
                                Layout-model detection score (0-1). Null when
                                the page bypassed layout analysis.
                            ocr:
                              type: number
                              nullable: true
                              description: >-
                                Text confidence when the source path provides
                                one; null otherwise.
            summary:
              type: string
              nullable: true
              description: Summary of the page if `summary` is in `formats`
            html:
              type: string
              nullable: true
              description: >-
                Cleaned HTML of the page if `html` is in `formats`. Removes
                `<script>`, `<style>`, `<noscript>`, `<meta>`, and `<head>`
                tags; converts relative URLs to absolute; resolves responsive
                image `srcset` to the largest version. Respects
                `onlyMainContent`, `includeTags`, and `excludeTags` filters.
            rawHtml:
              type: string
              nullable: true
              description: >-
                The exact, unmodified HTML as received from the page if
                `rawHtml` is in `formats`. No cleaning or filtering is applied.
            rawBase64:
              type: string
              nullable: true
              description: >-
                The Base64-encoded original HTTP response body if `rawBase64` is
                in `formats`. A bare Base64 string, not a data URI. The MIME
                type is in `metadata.contentType`.
            screenshot:
              type: string
              nullable: true
              description: >-
                Screenshot of the page if `screenshot` is in `formats`.
                Screenshots expire after 24 hours and can no longer be
                downloaded.
            audio:
              type: string
              nullable: true
              description: >-
                Signed URL to the extracted MP3 audio file if `audio` is in
                `formats`. The signed URL expires after 1 hour.
            video:
              type: string
              nullable: true
              description: >-
                Signed URL to the extracted video file if `video` is in
                `formats`. The signed URL expires after 1 hour.
            answer:
              type: string
              nullable: true
              description: >-
                Natural-language answer to the question supplied via the
                `question` format. Only present if a `question` format object
                was included in `formats`.
            highlights:
              type: string
              nullable: true
              description: >-
                Relevant source text selected by the `highlights` format. Only
                present if a `highlights` format object was included in
                `formats`.
            links:
              type: array
              items:
                type: string
              description: List of links on the page if `links` is in `formats`
            attributes:
              type: array
              description: >-
                Attribute values extracted by the `attributes` format. Only
                present if an `attributes` format object was included in
                `formats`.
              items:
                type: object
                properties:
                  selector:
                    type: string
                  attribute:
                    type: string
                  values:
                    type: array
                    items:
                      type: string
            actions:
              type: object
              nullable: true
              description: >-
                Results of the actions specified in the `actions` parameter.
                Only present if the `actions` parameter was provided in the
                request
              properties:
                screenshots:
                  type: array
                  description: >-
                    Screenshot URLs, in the same order as the screenshot actions
                    provided.
                  items:
                    type: string
                    format: url
                scrapes:
                  type: array
                  description: >-
                    Scrape contents, in the same order as the scrape actions
                    provided.
                  items:
                    type: object
                    properties:
                      url:
                        type: string
                      html:
                        type: string
                javascriptReturns:
                  type: array
                  description: >-
                    JavaScript return values, in the same order as the
                    executeJavascript actions provided.
                  items:
                    type: object
                    properties:
                      type:
                        type: string
                      value: {}
                pdfs:
                  type: array
                  description: >-
                    PDFs generated, in the same order as the pdf actions
                    provided.
                  items:
                    type: string
            metadata:
              type: object
              properties:
                title:
                  oneOf:
                    - type: string
                    - type: array
                      items:
                        type: string
                  description: >-
                    Title extracted from the page, can be a string or array of
                    strings
                description:
                  oneOf:
                    - type: string
                    - type: array
                      items:
                        type: string
                  description: >-
                    Description extracted from the page, can be a string or
                    array of strings
                language:
                  anyOf:
                    - type: string
                      nullable: true
                    - type: array
                      items:
                        type: string
                      nullable: true
                  description: >-
                    Language extracted from the page, can be a string or array
                    of strings
                sourceURL:
                  type: string
                  format: uri
                  description: >-
                    The original URL that was requested. May differ from the
                    page's final URL if redirects occurred.
                url:
                  type: string
                  format: uri
                  description: >-
                    The final URL of the page after all redirects have been
                    followed.
                keywords:
                  oneOf:
                    - type: string
                    - type: array
                      items:
                        type: string
                  description: >-
                    Keywords extracted from the page, can be a string or array
                    of strings
                ogLocaleAlternate:
                  type: array
                  items:
                    type: string
                  description: Alternative locales for the page
                '<any other metadata> ':
                  oneOf:
                    - type: string
                    - type: array
                      items:
                        type: string
                  description: >-
                    Other metadata extracted from HTML, can be a string or array
                    of strings
                statusCode:
                  type: integer
                  description: The status code of the page
                numPages:
                  type: integer
                  description: >-
                    For PDF inputs, the number of pages parsed (capped by the
                    parsers maxPages option).
                totalPages:
                  type: integer
                  description: >-
                    For PDF inputs, the document's true page count before any
                    maxPages capping. Omitted when it cannot be determined; a
                    totalPages greater than numPages indicates the result was
                    truncated.
                contentType:
                  type: string
                  description: >-
                    The content type (MIME type) of the page, e.g. text/html,
                    application/pdf
                error:
                  type: string
                  nullable: true
                  description: The error message of the page
                concurrencyLimited:
                  type: boolean
                  description: >-
                    Whether this scrape was throttled due to team concurrency
                    limits
                concurrencyQueueDurationMs:
                  type: number
                  description: >-
                    Time in milliseconds the request waited in the concurrency
                    queue. Only present when concurrencyLimited is true.
                provider:
                  type: object
                  description: Set when a third-party data provider served the URL.
                  properties:
                    id:
                      type: string
                      description: The provider that returned the data.
                    creditsCost:
                      type: integer
                      description: What that access cost, in credits.
                    steps:
                      type: array
                      description: Each provider tried, in order.
                      items:
                        type: object
                        properties:
                          provider:
                            type: string
                          status:
                            type: string
                            enum:
                              - matched
                              - not_found
                              - error
                          creditsCost:
                            type: integer
            warning:
              type: string
              nullable: true
              description: >-
                Can be displayed when using LLM Extraction. Warning message will
                let you know any issues with the extraction.
            changeTracking:
              type: object
              nullable: true
              description: >-
                Change tracking information if `changeTracking` is in `formats`.
                Only present when the `changeTracking` format is requested.
              properties:
                previousScrapeAt:
                  type: string
                  format: date-time
                  nullable: true
                  description: >-
                    The timestamp of the previous scrape that the current page
                    is being compared against. Null if no previous scrape
                    exists.
                changeStatus:
                  type: string
                  enum:
                    - new
                    - same
                    - changed
                    - removed
                  description: >-
                    The result of the comparison between the two page versions.
                    'new' means this page did not exist before, 'same' means
                    content has not changed, 'changed' means content has
                    changed, 'removed' means the page was removed.
                visibility:
                  type: string
                  enum:
                    - visible
                    - hidden
                  description: >-
                    The visibility of the current page/URL. 'visible' means the
                    URL was discovered through an organic route (links or
                    sitemap), 'hidden' means the URL was discovered through
                    memory from previous crawls.
                diff:
                  type: string
                  nullable: true
                  description: >-
                    Git-style diff of changes when using 'git-diff' mode. Only
                    present when the mode is set to 'git-diff'.
                json:
                  type: object
                  nullable: true
                  description: >-
                    JSON comparison results when using 'json' mode. Only present
                    when the mode is set to 'json'. This will emit a list of all
                    the keys and their values from the `previous` and `current`
                    scrapes based on the type defined in the `schema`. Example
                    [here](/features/change-tracking)
            branding:
              type: object
              nullable: true
              description: >-
                Branding information extracted from the page if `branding` is in
                `formats`. Includes colors, fonts, typography, spacing,
                components, and more.
              properties:
                colorScheme:
                  type: string
                  enum:
                    - light
                    - dark
                  description: The detected color scheme of the page.
                logo:
                  type: string
                  nullable: true
                  description: URL of the primary logo.
                colors:
                  type: object
                  nullable: true
                  description: Brand colors extracted from the page.
                  properties:
                    primary:
                      type: string
                      description: Primary brand color (hex).
                    secondary:
                      type: string
                      description: Secondary brand color (hex).
                    accent:
                      type: string
                      description: Accent color (hex).
                    background:
                      type: string
                      description: Background color (hex).
                    textPrimary:
                      type: string
                      description: Primary text color (hex).
                    textSecondary:
                      type: string
                      description: Secondary text color (hex).
                    link:
                      type: string
                      description: Link color (hex).
                    success:
                      type: string
                      description: Success/positive color (hex).
                    warning:
                      type: string
                      description: Warning color (hex).
                    error:
                      type: string
                      description: Error/danger color (hex).
                fonts:
                  type: array
                  nullable: true
                  description: Array of font families used on the page.
                  items:
                    type: object
                    properties:
                      family:
                        type: string
                        description: Font family name.
                typography:
                  type: object
                  nullable: true
                  description: Detailed typography information.
                  properties:
                    fontFamilies:
                      type: object
                      description: Font families by role.
                      properties:
                        primary:
                          type: string
                          description: Primary font family.
                        heading:
                          type: string
                          description: Heading font family.
                        code:
                          type: string
                          description: Code/monospace font family.
                    fontSizes:
                      type: object
                      description: Font sizes for different text levels.
                      properties:
                        h1:
                          type: string
                        h2:
                          type: string
                        h3:
                          type: string
                        body:
                          type: string
                    fontWeights:
                      type: object
                      description: Font weight definitions.
                      properties:
                        light:
                          type: integer
                        regular:
                          type: integer
                        medium:
                          type: integer
                        bold:
                          type: integer
                    lineHeights:
                      type: object
                      description: Line height values for different text types.
                      properties:
                        heading:
                          type: string
                        body:
                          type: string
                spacing:
                  type: object
                  nullable: true
                  description: Spacing and layout information.
                  properties:
                    baseUnit:
                      type: integer
                      description: Base spacing unit in pixels.
                    borderRadius:
                      type: string
                      description: Default border radius.
                    padding:
                      type: object
                      description: Padding values.
                    margins:
                      type: object
                      description: Margin values.
                components:
                  type: object
                  nullable: true
                  description: UI component styles.
                  properties:
                    buttonPrimary:
                      type: object
                      description: Primary button styles.
                      properties:
                        background:
                          type: string
                        textColor:
                          type: string
                        borderRadius:
                          type: string
                    buttonSecondary:
                      type: object
                      description: Secondary button styles.
                      properties:
                        background:
                          type: string
                        textColor:
                          type: string
                        borderColor:
                          type: string
                        borderRadius:
                          type: string
                    input:
                      type: object
                      description: Input field styles.
                icons:
                  type: object
                  nullable: true
                  description: Icon style information.
                images:
                  type: object
                  nullable: true
                  description: Brand images.
                  properties:
                    logo:
                      type: string
                      description: Logo image URL.
                    favicon:
                      type: string
                      description: Favicon URL.
                    ogImage:
                      type: string
                      description: Open Graph image URL.
                animations:
                  type: object
                  nullable: true
                  description: Animation and transition settings.
                layout:
                  type: object
                  nullable: true
                  description: Layout configuration (grid, header/footer heights).
                personality:
                  type: object
                  nullable: true
                  description: Brand personality traits (tone, energy, target audience).
            product:
              type: object
              nullable: true
              description: >-
                Product information extracted from the page if `product` is in
                `formats`. Includes title, brand, category, description, and
                variants. Pricing, availability, and images live on each
                variant.
              properties:
                title:
                  type: string
                  description: The product title.
                brand:
                  type: string
                  description: The product brand or manufacturer.
                category:
                  type: string
                  description: >-
                    The product category, optionally as a breadcrumb path (e.g.
                    'Electronics > Audio > Headphones').
                url:
                  type: string
                  description: The canonical URL of the product page.
                description:
                  type: string
                  description: The product description.
                variants:
                  type: array
                  description: Product variants (e.g. different colors or sizes).
                  items:
                    type: object
                    properties:
                      id:
                        type: string
                        description: The variant identifier.
                      sku:
                        type: string
                        description: The variant SKU.
                      title:
                        type: string
                        description: The variant title.
                      values:
                        type: object
                        description: 'The variant option values (e.g. { "color": "Black" }).'
                        additionalProperties:
                          type: string
                      price:
                        type: object
                        description: The current price of the variant.
                        properties:
                          amount:
                            type: number
                            description: The numeric price amount.
                          currency:
                            type: string
                            description: The ISO 4217 currency code (e.g. 'USD').
                          formatted:
                            type: string
                            description: The price formatted for display (e.g. '$199.99').
                        required:
                          - amount
                      sale:
                        type: object
                        description: >-
                          Sale/discount information for the variant, present
                          when the variant is discounted.
                        properties:
                          originalPrice:
                            type: object
                            description: The original (pre-discount) price of the variant.
                            properties:
                              amount:
                                type: number
                                description: The numeric price amount.
                              currency:
                                type: string
                                description: The ISO 4217 currency code (e.g. 'USD').
                              formatted:
                                type: string
                                description: >-
                                  The price formatted for display (e.g.
                                  '$249.99').
                            required:
                              - amount
                        required:
                          - originalPrice
                      availability:
                        type: object
                        description: >-
                          The availability of the variant. Always present on a
                          variant.
                        properties:
                          inStock:
                            type: boolean
                            description: Whether the variant is in stock.
                          text:
                            type: string
                            description: >-
                              Human-readable availability text (e.g. 'In
                              Stock').
                        required:
                          - inStock
                      images:
                        type: array
                        description: Variant images.
                        items:
                          type: object
                          properties:
                            url:
                              type: string
                              description: Image URL.
                            alt:
                              type: string
                              description: Alternative text for the image.
                          required:
                            - url
                    required:
                      - availability
              required:
                - title
                - url
                - variants
            menu:
              type: object
              nullable: true
              description: >-
                Menu information extracted from the page if `menu` is in
                `formats`. Includes the merchant, currency, and a list of
                sections, where each section carries items with description,
                images, price, availability, dietary tags, calories, and option
                groups.
              properties:
                isMenu:
                  type: boolean
                  description: Whether the page was identified as a menu.
                confidence:
                  type: number
                  description: A confidence score between 0 and 1 for the menu extraction.
                merchant:
                  type: object
                  description: The merchant the menu belongs to.
                  properties:
                    name:
                      type: string
                      description: The merchant name.
                    type:
                      type: string
                      description: The merchant type (e.g. 'restaurant').
                  required:
                    - name
                currency:
                  type: string
                  description: >-
                    The ISO 4217 currency code for the menu (e.g. 'USD'),
                    reported only when the page sources it.
                sections:
                  type: array
                  description: Menu sections (e.g. 'Appetizers', 'Entrees').
                  items:
                    type: object
                    properties:
                      id:
                        type: string
                        description: The section identifier.
                      name:
                        type: string
                        description: The section name.
                      description:
                        type: string
                        nullable: true
                        description: The section description.
                      items:
                        type: array
                        description: The items in the section.
                        items:
                          type: object
                          properties:
                            id:
                              type: string
                              description: The item identifier.
                            name:
                              type: string
                              description: The item name.
                            description:
                              type: string
                              nullable: true
                              description: The item description.
                            images:
                              type: array
                              description: Item images.
                              items:
                                type: object
                                properties:
                                  url:
                                    type: string
                                    description: Image URL.
                                  alt:
                                    type: string
                                    nullable: true
                                    description: Alternative text for the image.
                                required:
                                  - url
                            price:
                              type: object
                              description: The price of the item.
                              properties:
                                amount:
                                  type: number
                                  description: The numeric price amount.
                                currency:
                                  type: string
                                  description: The ISO 4217 currency code (e.g. 'USD').
                                formatted:
                                  type: string
                                  description: >-
                                    The price formatted for display (e.g.
                                    '$7.99').
                              required:
                                - amount
                            availability:
                              type: object
                              description: The availability of the item.
                              properties:
                                inStock:
                                  type: boolean
                                  description: Whether the item is available.
                                text:
                                  type: string
                                  nullable: true
                                  description: Human-readable availability text.
                              required:
                                - inStock
                            dietary:
                              type: array
                              description: Dietary tags for the item (e.g. ['vegetarian']).
                              items:
                                type: string
                            calories:
                              type: number
                              nullable: true
                              description: The item's calorie count.
                            optionGroups:
                              type: array
                              description: Option/modifier groups for the item.
                              items:
                                type: object
                            identifiers:
                              type: object
                              description: Merchant-specific identifiers for the item.
                              properties:
                                merchantItemId:
                                  type: string
                                  description: The merchant's own item ID.
                            url:
                              type: string
                              nullable: true
                              description: The canonical URL of the item.
                            sourceUrl:
                              type: string
                              nullable: true
                              description: The URL the item was extracted from.
                          required:
                            - name
                    required:
                      - name
                      - items
                sourceUrl:
                  type: string
                  nullable: true
                  description: The URL the menu was extracted from.
              required:
                - isMenu
                - sections
            tools:
              type: array
              nullable: true
              description: >-
                Tool contracts matched to the scraped page's domain. Present
                only when `domainTools` is `true` on the request. Requires
                Alexandria access and no zero data retention (403 otherwise);
                free.
              items:
                $ref: '#/components/schemas/DiscoveredTool'
    AlexandriaScrapeResponse:
      type: object
      description: >-
        Response returned when the request executed Alexandria provider tools
        instead of scraping a URL.
      properties:
        success:
          type: boolean
          example: true
        scrape_id:
          type: string
          description: >-
            Identifier for this request. A completed request replays the same
            response and `scrape_id` when retried with the same `x-request-id`.
        data:
          type: object
          properties:
            alexandria:
              type: array
              description: >-
                Results for each requested Alexandria call, in the same order as
                the request.
              items:
                $ref: '#/components/schemas/AlexandriaResult'
            creditsCost:
              type: integer
              description: Sum of `creditsCost` across successful items.
          required:
            - alexandria
            - creditsCost
      required:
        - success
        - scrape_id
        - data
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
    FindToolsOptions:
      type: object
      title: Find Tools options
      description: >-
        Options for the Find Tools capability (`provider: firecrawl`,
        `capability: find-tools`) in an `alexandria` call. Find Tools is free
        and does not execute the tools it returns. All fields are optional.
        Selectors narrow the results.
      properties:
        query:
          type: string
          description: >-
            Natural-language description of the data you need. Returns tools
            that match by meaning.
        urls:
          type: array
          description: >-
            Website URLs. Returns tools whose provider matches the domain of a
            URL.
          items:
            type: string
            format: uri
        providers:
          type: array
          description: Provider IDs to browse, e.g. `particle`.
          items:
            type: string
        categories:
          type: array
          description: Category IDs to browse.
          items:
            type: string
        groups:
          type: array
          description: Group IDs to browse.
          items:
            type: string
        capabilities:
          type: array
          description: Exact capability IDs to return.
          items:
            type: string
        level:
          type: string
          enum:
            - providers
            - groups
            - tools
          description: The catalogue level to list in `items`.
        expand:
          type: array
          description: >-
            Contract parts to include on each tool. Use `["options",
            "response"]` for inputs and output shape, add `examples` for example
            payloads, or use `[]` for compact results.
          items:
            type: string
            enum:
              - options
              - response
              - examples
        limit:
          type: integer
          minimum: 1
          description: Maximum number of items on the page.
        offset:
          type: integer
          minimum: 0
          description: Number of items to skip, for pagination.
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
    AlexandriaResult:
      type: object
      description: >-
        The outcome of one executed Alexandria call, returned in the same order
        as the request.
      oneOf:
        - type: object
          title: Success
          properties:
            provider:
              type: string
              description: The provider that was called.
            capability:
              type: string
              description: The capability that was invoked.
            creditsCost:
              type: integer
              minimum: 0
              description: Credits charged for this call.
            data:
              description: >-
                The provider's response payload. For Find Tools (`provider:
                firecrawl`, `capability: find-tools`), this is a `FindToolsData`
                page.
              anyOf:
                - $ref: '#/components/schemas/FindToolsData'
                - title: Capability response
                  description: >-
                    The response of any other capability, as its contract
                    defines it.
            records:
              type: integer
              description: Number of records returned, when applicable.
            upstreamStatus:
              type: integer
              description: >-
                HTTP status code returned by the upstream provider, when
                applicable.
          required:
            - provider
            - capability
            - creditsCost
            - data
        - type: object
          title: Error
          properties:
            provider:
              type: string
              description: The provider that was called.
            capability:
              type: string
              description: The capability that was invoked.
            creditsCost:
              type: integer
              default: 0
              description: Always 0 for a failed call.
            error:
              type: object
              properties:
                code:
                  type: string
                  description: Machine-readable error code for this call.
                message:
                  type: string
                  description: Human-readable error message for this call.
                status:
                  type: integer
                  description: >-
                    HTTP status code returned by the upstream provider, when
                    applicable.
              required:
                - code
                - message
          required:
            - error
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
    FindToolsData:
      type: object
      title: Find Tools result
      description: >-
        One page of the Alexandria catalogue, returned in
        `data.alexandria[].data` for a Find Tools call. The call costs 0
        credits.
      properties:
        level:
          type: string
          enum:
            - providers
            - groups
            - tools
          description: The catalogue level of the items on this page.
        items:
          type: array
          description: >-
            Catalogue entries at `level`. At the `tools` level, each item also
            has the tool fields of `DiscoveredTool` (`provider`, `capability`,
            `description`, `creditsCost`, `perRecord`), plus `options` and
            `response` when `expand` asks for them.
          items:
            type: object
            additionalProperties: true
            properties:
              id:
                type: string
                description: The entry's identifier.
              name:
                type: string
                description: Human-readable name of the entry.
              next:
                allOf:
                  - $ref: '#/components/schemas/AlexandriaCall'
                description: An `alexandria` call that returns more detail for this entry.
              execute:
                type: object
                description: >-
                  The `provider` and `capability` to put in an `alexandria` call
                  to execute this tool.
                properties:
                  provider:
                    type: string
                  capability:
                    type: string
                required:
                  - provider
                  - capability
            required:
              - id
              - name
        total:
          type: integer
          minimum: 0
          description: Total number of entries that match the selectors.
        next:
          allOf:
            - $ref: '#/components/schemas/AlexandriaCall'
          type: object
          nullable: true
          description: >-
            An `alexandria` call for the next page of this listing, or `null` on
            the last page.
      required:
        - level
        - items
        - total
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````

This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.
