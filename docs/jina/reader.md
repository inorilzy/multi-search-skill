> Source: https://r.jina.ai/openapi.json (official OpenAPI document backing https://r.jina.ai/docs)
> Retrieved: 2026-10-31
> Covers: GET/POST https://r.jina.ai/ and GET/POST https://r.jina.ai/{url} (Reader read endpoints): request headers, query/body params, response envelope (FormattedPageDto), error responses, auth, rate limits

# Jina Reader API

Version: 0.5.0+9e23d86

Content below is rendered mechanically from the OpenAPI document; descriptions are verbatim. The full raw spec is saved alongside as `openapi.json`.

Turn any URL or search query into clean, LLM-friendly input.

## Capabilities

- **Read** — fetch a URL and get its main content back as markdown, HTML, text or a screenshot. JavaScript-heavy pages, PDFs and uploaded files are all handled.
- **Search** — search the web and get the top results back already read, each as LLM-friendly content rather than a snippet.

Behavior is driven by request headers (or the equivalent body fields): `X-Respond-With` selects the output format, `X-Engine` the fetching engine, `X-Respond-Timing` how long to wait for a page to settle. Send `Accept: application/json` for a structured response, or `Accept: text/event-stream` to stream it.

## Authentication

```
Authorization: Bearer jina_YOUR_API_KEY
```

Get one at [jina.ai/api-dashboard/key-manager](https://jina.ai/api-dashboard/key-manager). Reading a URL works without a key at a lower rate limit; web search on `s.jina.ai` requires one.

## Rate limits

Limits depend on whether a key is sent and on its plan; anything over a limit answers `429`. See [jina.ai/reader#pricing](https://jina.ai/reader#pricing) for the current numbers.


## Servers

- `https://r.jina.ai/`

## Security schemes

- `HTTPBearer`: type=http scheme=bearer — Your Jina API key. Get one at [jina.ai/api-dashboard/key-manager](https://jina.ai/api-dashboard/key-manager).

## `GET /`

operationId: `None`

Index of the service

### header parameters

#### `Authorization`

Schema: `{"anyOf": [{"type": "string", "format": "token"}]}`

Jina Token for authentication.

- Member of <JinaEmbeddingsAuthDTO>

- Authorization: Bearer {YOUR_JINA_TOKEN}

#### `Accept`

Schema: `{"type": "string"}`

Specifies your preference for the response format.

Supported formats: 
- text/event-stream
- application/json or text/json
- text/plain

#### `X-Cache-Tolerance`

Schema: `{"type": "string"}`

Sets internal cache tolerance in seconds if this header is specified with a integer.

#### `X-No-Cache`

Schema: `{"type": "string"}`

Ignores internal cache if this header is specified with a value.

Equivalent to X-Cache-Tolerance: 0

#### `X-Respond-With`

Schema: `{"type": "string"}`

Specifies the (non-default) form of the crawled data you prefer.

Supported formats: 
- markdown
- html
- text
- pageshot
- screenshot
- content
- frontmatter
- any combination of the above
- vlm
- jina-ocr-v1
- jina-ocr
- readerlm-v2


Default: content

#### `X-Wait-For-Selector`

Schema: `{"type": "string"}`

Specifies a CSS selector to wait for the appearance of such an element before returning.

Example: `X-Wait-For-Selector: .content-block`

#### `X-Target-Selector`

Schema: `{"type": "string"}`

Specifies a CSS selector for return target instead of the full html.

Implies `X-Wait-For-Selector: (same selector)`

#### `X-Remove-Selector`

Schema: `{"type": "string"}`

Specifies a CSS selector to remove elements from the full html.

Example `X-Remove-Selector: nav`

#### `X-Keep-Img-Data-Url`

Schema: `{"type": "string"}`

Keep data-url as it instead of transforming them to object-url. (Only applicable when targeting markdown format)

Example `X-Keep-Img-Data-Url: true`

#### `X-Proxy-Url`

Schema: `{"type": "string"}`

Specifies your custom proxy if you prefer to use one.

Supported protocols: 
- http
- https
- socks4
- socks5

For authentication, https://user:pass@host:port

#### `X-Proxy-Resources`

Schema: `{"type": "string"}`

Whether to load resources like image/style/scripts via the proxy server.

#### `X-Proxy`

Schema: `{"type": "string"}`

Use a proxy server provided by us.

Optionally specify two-letter country code.

#### `X-Robots-Txt`

Schema: `{"type": "string"}`

Load and conform to the respective robot.txt on the target origin.

Optionally specify a bot UA to check against.

#### `DNT`

Schema: `{"type": "string"}`

When set to 1, prevent the result of this request to be cached in the system.

#### `X-Set-Cookie`

Schema: `{"type": "string"}`

Sets cookie(s) to the headless browser for your request. 

Syntax is the same with standard Set-Cookie

#### `X-Export-Storage-State`

Schema: `{"type": "string"}`

Export the browser storage state (cookies and per-origin localStorage) accumulated during the crawl.

When enabled, the JSON response includes a `storageState` field whose shape mirrors the `storageState` request option, so it can be fed back into a subsequent request.

Requires the browser engine and disables caching.

#### `X-With-Generated-Alt`

Schema: `{"type": "string"}`

Enable automatic alt-text generating for images without an meaningful alt-text.

Note: Does not work when `X-Respond-With` is specified

#### `X-With-Images-Summary`

Schema: `{"type": "string"}`

Enable dedicated summary section for images on the page.

#### `X-With-links-Summary`

Schema: `{"type": "string"}`

Enable dedicated summary section for hyper links on the page.

#### `X-Retain-Links`

Schema: `{"type": "string"}`

Link retention modes.

Supported modes: 
- all: all links
- none: no links
- text: only link text
- gpt-oss: gpt-oss link citation format `【{id}†.*】`

#### `X-Retain-Images`

Schema: `{"type": "string"}`

Image retention modes.

Supported modes: 
- all: all images
- none: no images
- alt: only alt text
- all_p: all images and with generated alt text
- alt_p: only alt text and with generated alt

#### `X-Retain-Media`

Schema: `{"type": "string"}`

Media retention modes for video, audio, and embedded video iframes.

Supported modes: 
- none: no media
- text: plain label, e.g. `Video 1`
- link: markdown link, e.g. `[Video 1](url)` (default)
- image: markdown image syntax, e.g. `![Video 1](url)`
- html: original HTML with irrelevant attributes (class, id, style, data-*, aria-*) stripped

#### `X-Preset`

Schema: `{"type": "string"}`

Apply a preset configuration for common scenarios.

Supported presets:
- reader: optimized for display to human users
- index: optimized for semantic indexing
- research: optimized for academic/research AI agents
- agent: optimized for day-to-day AI agents
- spider: optimized for recursive site crawling

Preset values are applied only to options not explicitly set by the caller.

#### `X-With-Iframe`

Schema: `{"type": "string"}`

Enable filling iframe contents into main. (violates standards)

#### `X-With-Shadow-Dom`

Schema: `{"type": "string"}`

Enable filling shadow dom contents into main. (violates standards)

#### `X-Skip-Cert-Verification`

Schema: `{"type": "string"}`

Enable skipping SSL certificate verification. (violates security best practices)

#### `X-User-Agent`

Schema: `{"type": "string"}`

Override User-Agent.

Several special values: 
- browser: use the internal browser UA
- auto: pass-through your UA if it starts with `Mozilla/5.0`, otherwise use the internal browser UA
- inherit / pass-through: use the User-Agent from the request context if applicable
- bot: Use a pre-defined bot User-Agent from this service
- diversify: Use a diversified browser User-Agent

Or specify your own user agent string.

Note: anonymous users specifying a browser UA will have no effect and will fall back to the internal browser UA.

Default: browser

#### `X-Timeout`

Schema: `{"type": "string"}`

Specify timeout in seconds. Max 180.

#### `X-Locale`

Schema: `{"type": "string"}`

Specify browser locale for the page.

#### `X-Referer`

Schema: `{"type": "string"}`

Specify referer for the page.

#### `X-Token-Budget`

Schema: `{"type": "string"}`

Specify a budget in tokens.

If the resulting token cost exceeds the budget, the request is rejected.

Note this parameter is ignored for the search endpoint.

#### `X-Max-Tokens`

Schema: `{"type": "string"}`

Trim the response content at a maximum number of tokens.

#### `X-Assert-Status-Code`

Schema: `{"type": "string"}`

Assert the HTTP status code of the crawled page. If the actual status code does not match the asserted one, the request is rejected with 422 Unprocessable Entity.

#### `X-Respond-Timing`

Schema: `{"type": "string"}`

Explicitly specify the respond timing. One of the following:

- html: directly return unrendered HTML
- visible-content: return immediately when any content becomes available
- mutation-idle: wait for DOM mutations to settle and remain unchanged for at least 0.2s
- resource-idle: wait for no additional resources that would affect page logic and content has SUCCEEDED loading in 0.5s
- media-idle: wait for no additional resources, including media resources, has SUCCEEDED loading in 0.5s
- network-idle: wait for full load of webpage, also known as networkidle0.

#### `X-Engine`

Schema: `{"type": "string"}`

Specify the engine to use for crawling.

Supported: browser, direct, cf-browser-rendering

#### `X-Base`

Schema: `{"type": "string"}`

Select base modes of relative URLs.

Supported: initial, final

#### `X-Remove-Overlay`

Schema: `{"type": "string"}`

Specify whether to remove overlay elements from the page.

#### `X-Detach-Invisibles`

Schema: `{"type": "string"}`

Temporarily detach elements with computed `display:none` before snapshotting, then restore them.

Requires the browser engine and disables caching.

#### `X-Markdown-Chunking`

Schema: `{"type": "string"}`

Opt-in markdown chunking.

Supported values: 
- true
- h1
- h2
- h3
- h4
- h5
- structured
- s1
- s2
- s3
- s4
- s5

Note if you are expecting text return, the chunking is done by injecting character \u001D

#### `X-Md-Heading-Style`

Schema: `{"type": "string"}`

Heading style of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: setext, atx

#### `X-Md-Hr`

Schema: `{"type": "string"}`

Hr text of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

#### `X-Md-Bullet-List-Marker`

Schema: `{"type": "string"}`

Bullet list marker of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: -, +, *

#### `X-Md-Em-Delimiter`

Schema: `{"type": "string"}`

Em delimiter of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: _, *

#### `X-Md-Strong-Delimiter`

Schema: `{"type": "string"}`

Strong delimiter of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: **, __

#### `X-Md-Link-Style`

Schema: `{"type": "string"}`

Link style of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: inlined, referenced, discarded

#### `X-Md-Link-Reference-Style`

Schema: `{"type": "string"}`

Link reference style of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: full, collapsed, shortcut, discarded

#### `X-Page`

Schema: `{"type": "string"}`

Steer which page to return for uploaded files (PDF, DOC, XLS, PPT, etc.).

1-indexed, 0 is the same as 1. Accepts a page number, a list and/or ranges like `1,3,5-7`.

At most 35 pages can be selected. With multiple pages, DocLayout / OCR runs over each selected page.

Ignored when the target is not a document.

#### `X-Preload-Url`

Schema: `{"type": "string"}`

URL to preload before scraping.

Ignored when no URL is provided.

#### `X-No-Service-Worker`

Schema: `{"type": "string"}`

Disable service workers when running the browser.

Useful for bypassing service-worker-based caching or interception.

### query parameters

#### `url`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `preloadUrl`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `noServiceWorker`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `html`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `base`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x0d"}], "default": "final"}`

- Cast to: < **&quot;initial&quot; | &quot;final&quot;** >

- Member of <CrawlerOptions>

- Defaults to: &#39;final&#39;

#### `pdf`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/FancyFile@0x0e"}]}, {"type": "string"}], "summary": "Base64 encoded PDF."}`

Base64 encoded PDF.

- Cast to: < **FancyFile|string** >

- Member of <CrawlerOptions>

#### `file`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/FancyFile@0x0e"}]}, {"type": "string"}], "summary": "Base64 encoded file."}`

Base64 encoded file.

- Cast to: < **FancyFile|string** >

- Member of <CrawlerOptions>

#### `page`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PageSelection@0x0f"}], "summary": "Steer which page(s) to return for document files. See PageSelection."}`

Steer which page(s) to return for document files. See PageSelection.

- Cast to: < **PageSelection** >

- Member of <CrawlerOptions>

#### `respondWith`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/enum@0x10"}]}, {"type": "string"}], "default": "content"}`

- Cast to: < **&quot;content&quot; | &quot;markdown&quot; | &quot;html&quot; | &quot;text&quot; | &quot;pageshot&quot; | &quot;screenshot&quot; | &quot;vlm&quot; | &quot;readerlm-v2&quot; | &quot;frontmatter&quot; | &quot;readability&quot; | &quot;...|string** >

- Member of <CrawlerOptions>

- Defaults to: &#39;content&#39;

#### `withGeneratedAlt`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}`

- Cast to: < **PseudoBoolean** >

- Member of <CrawlerOptions>

#### `retainImages`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x12"}], "default": "all"}`

- Cast to: < **&quot;none&quot; | &quot;all&quot; | &quot;alt&quot; | &quot;all_p&quot; | &quot;alt_p&quot;** >

- Member of <CrawlerOptions>

- Defaults to: &#39;all&#39;

#### `retainMedia`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x13"}], "default": "link"}`

- Cast to: < **&quot;none&quot; | &quot;text&quot; | &quot;link&quot; | &quot;image&quot; | &quot;html&quot;** >

- Member of <CrawlerOptions>

- Defaults to: &#39;link&#39;

#### `preset`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x14"}]}`

- Cast to: < **&quot;reader&quot; | &quot;index&quot; | &quot;research&quot; | &quot;agent&quot; | &quot;spider&quot; | &quot;ocr&quot; | &quot;ocr+&quot; | &quot;ocr++&quot; | &quot;pdf&quot; | &quot;pdf+&quot; | &quot;pdf++&quot;** >

- Member of <CrawlerOptions>

#### `retainLinks`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x15"}], "default": "all"}`

- Cast to: < **&quot;none&quot; | &quot;all&quot; | &quot;text&quot; | &quot;gpt-oss&quot;** >

- Member of <CrawlerOptions>

- Defaults to: &#39;all&#39;

#### `withLinksSummary`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}, {"type": "string"}]}`

- Cast to: < **PseudoBoolean|string** >

- Member of <CrawlerOptions>

#### `withImagesSummary`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `noCache`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `removeOverlay`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `detachInvisibles`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `noGfm`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}, {"type": "string"}]}`

- Cast to: < **PseudoBoolean|string** >

- Member of <CrawlerOptions>

#### `cacheTolerance`

Schema: `{"type": "number"}`

- Cast to: < **number** >

- Member of <CrawlerOptions>

#### `targetSelector`

Schema: `{"type": "string"}`

- Cast to: < **Array<string>** >

- Member of <CrawlerOptions>

#### `waitForSelector`

Schema: `{"type": "string"}`

- Cast to: < **Array<string>** >

- Member of <CrawlerOptions>

#### `removeSelector`

Schema: `{"type": "string"}`

- Cast to: < **Array<string>** >

- Member of <CrawlerOptions>

#### `keepImgDataUrl`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `withIframe`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}, {"type": "string"}]}`

- Cast to: < **PseudoBoolean|string** >

- Member of <CrawlerOptions>

#### `withShadowDom`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `skipCertVerification`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `webBotAuth`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}, {"allOf": [{"$ref": "#/components/schemas/enum@0x16"}]}]}`

- Cast to: < **PseudoBoolean|&quot;authority&quot; | &quot;target-uri&quot;** >

- Member of <CrawlerOptions>

#### `setCookies`

Schema: `{"oneOf": [{"description": "Can be any value - string, number, boolean, array or object.", "nullable": true}, {"type": "string"}]}`

- Cast to: < **Array<object|string>** >

- Member of <CrawlerOptions>

#### `exportStorageState`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `proxyUrl`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `proxyResources`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `proxy`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `userAgent`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `engine`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/enum@0x1c"}]}, {"type": "string"}]}`

- Cast to: < **&quot;auto&quot; | &quot;browser&quot; | &quot;curl&quot; | &quot;cf-browser-rendering&quot;|string** >

- Member of <CrawlerOptions>

#### `injectPageScript`

Schema: `{"type": "string"}`

- Cast to: < **Array<string>** >

- Member of <CrawlerOptions>

#### `injectFrameScript`

Schema: `{"type": "string"}`

- Cast to: < **Array<string>** >

- Member of <CrawlerOptions>

#### `timeout`

Schema: `{"type": "number"}`

- Cast to: < **number** >

- Member of <CrawlerOptions>

- Some validators will be applied on value(s): (v) => v > 0 &amp;&amp; v <= 180

#### `locale`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `referer`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `tokenBudget`

Schema: `{"type": "number"}`

- Cast to: < **number** >

- Member of <CrawlerOptions>

#### `assertStatusCode`

Schema: `{"type": "number"}`

- Cast to: < **number** >

- Member of <CrawlerOptions>

#### `instruction`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `jsonSchema`

Schema: `{"nullable": true}`

Can be any value - string, number, boolean, array or object.

- Cast to: < **object** >

- Member of <CrawlerOptions>

#### `robotsTxt`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}, {"type": "string"}]}`

- Cast to: < **PseudoBoolean|string** >

- Member of <CrawlerOptions>

#### `zeroDataRetention`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `respondTiming`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x26"}]}`

- Cast to: < **&quot;html&quot; | &quot;visible-content&quot; | &quot;mutation-idle&quot; | &quot;resource-idle&quot; | &quot;media-idle&quot; | &quot;network-idle&quot;** >

- Member of <CrawlerOptions>

#### `markdownChunking`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/enum@0x27"}]}, {"type": "string"}]}`

- Cast to: < **&quot;true&quot; | &quot;h1&quot; | &quot;h2&quot; | &quot;h3&quot; | &quot;h4&quot; | &quot;h5&quot; | &quot;structured&quot; | &quot;s1&quot; | &quot;s2&quot; | &quot;s3&quot; | &quot;s4&quot; | &quot;s5&quot;|string** >

- Member of <CrawlerOptions>

#### `maxTokens`

Schema: `{"type": "number"}`

- Cast to: < **number** >

- Member of <CrawlerOptions>

- Some validators will be applied on value(s): (v) => v >= 500

### Responses

- `200` OK — application/json: None
- `400` Bad Request — application/json: ParamValidationError@0x29, DataStreamBrokenError@0x2a
- `401` Unauthorized — application/json: AuthenticationFailedError@0x2b, AuthenticationRequiredError@0x2c
- `402` Payment Required — application/json: TierFeatureConstraintError@0x2d, InsufficientBalanceError@0x2e
- `403` Forbidden — application/json: OperationNotAllowedError@0x2f, AbuseAlleviationError@0x30
- `409` Conflict — application/json: ResourcePolicyDenyError@0x31, BudgetExceededError@0x32
- `413` Payload Too Large — application/json: TargetFileTooLargeError@0x33
- `422` Unprocessable Entity — application/json: SubmittedDataMalformedError@0x34, DownstreamServiceFailureError@0x35, AssertionFailureError@0x36
- `429` Too Many Requests — application/json: RateLimitTriggeredError@0x37
- `451` Unavailable For Legal Reasons — application/json: HarmfulContentError@0x38
- `500` Internal Server Error — application/json: DownstreamServiceError@0x39
- `503` Service Unavailable — application/json: ServiceNodeResourceDrainError@0x3a

## `POST /`

operationId: `None`

Read a URL and get its content back in an LLM-friendly format.

### header parameters

#### `Authorization`

Schema: `{"anyOf": [{"type": "string", "format": "token"}]}`

Jina Token for authentication.

- Member of <JinaEmbeddingsAuthDTO>

- Authorization: Bearer {YOUR_JINA_TOKEN}

#### `Accept`

Schema: `{"type": "string"}`

Specifies your preference for the response format.

Supported formats: 
- text/event-stream
- application/json or text/json
- text/plain

#### `X-Cache-Tolerance`

Schema: `{"type": "string"}`

Sets internal cache tolerance in seconds if this header is specified with a integer.

#### `X-No-Cache`

Schema: `{"type": "string"}`

Ignores internal cache if this header is specified with a value.

Equivalent to X-Cache-Tolerance: 0

#### `X-Respond-With`

Schema: `{"type": "string"}`

Specifies the (non-default) form of the crawled data you prefer.

Supported formats: 
- markdown
- html
- text
- pageshot
- screenshot
- content
- frontmatter
- any combination of the above
- vlm
- jina-ocr-v1
- jina-ocr
- readerlm-v2


Default: content

#### `X-Wait-For-Selector`

Schema: `{"type": "string"}`

Specifies a CSS selector to wait for the appearance of such an element before returning.

Example: `X-Wait-For-Selector: .content-block`

#### `X-Target-Selector`

Schema: `{"type": "string"}`

Specifies a CSS selector for return target instead of the full html.

Implies `X-Wait-For-Selector: (same selector)`

#### `X-Remove-Selector`

Schema: `{"type": "string"}`

Specifies a CSS selector to remove elements from the full html.

Example `X-Remove-Selector: nav`

#### `X-Keep-Img-Data-Url`

Schema: `{"type": "string"}`

Keep data-url as it instead of transforming them to object-url. (Only applicable when targeting markdown format)

Example `X-Keep-Img-Data-Url: true`

#### `X-Proxy-Url`

Schema: `{"type": "string"}`

Specifies your custom proxy if you prefer to use one.

Supported protocols: 
- http
- https
- socks4
- socks5

For authentication, https://user:pass@host:port

#### `X-Proxy-Resources`

Schema: `{"type": "string"}`

Whether to load resources like image/style/scripts via the proxy server.

#### `X-Proxy`

Schema: `{"type": "string"}`

Use a proxy server provided by us.

Optionally specify two-letter country code.

#### `X-Robots-Txt`

Schema: `{"type": "string"}`

Load and conform to the respective robot.txt on the target origin.

Optionally specify a bot UA to check against.

#### `DNT`

Schema: `{"type": "string"}`

When set to 1, prevent the result of this request to be cached in the system.

#### `X-Set-Cookie`

Schema: `{"type": "string"}`

Sets cookie(s) to the headless browser for your request. 

Syntax is the same with standard Set-Cookie

#### `X-Export-Storage-State`

Schema: `{"type": "string"}`

Export the browser storage state (cookies and per-origin localStorage) accumulated during the crawl.

When enabled, the JSON response includes a `storageState` field whose shape mirrors the `storageState` request option, so it can be fed back into a subsequent request.

Requires the browser engine and disables caching.

#### `X-With-Generated-Alt`

Schema: `{"type": "string"}`

Enable automatic alt-text generating for images without an meaningful alt-text.

Note: Does not work when `X-Respond-With` is specified

#### `X-With-Images-Summary`

Schema: `{"type": "string"}`

Enable dedicated summary section for images on the page.

#### `X-With-links-Summary`

Schema: `{"type": "string"}`

Enable dedicated summary section for hyper links on the page.

#### `X-Retain-Links`

Schema: `{"type": "string"}`

Link retention modes.

Supported modes: 
- all: all links
- none: no links
- text: only link text
- gpt-oss: gpt-oss link citation format `【{id}†.*】`

#### `X-Retain-Images`

Schema: `{"type": "string"}`

Image retention modes.

Supported modes: 
- all: all images
- none: no images
- alt: only alt text
- all_p: all images and with generated alt text
- alt_p: only alt text and with generated alt

#### `X-Retain-Media`

Schema: `{"type": "string"}`

Media retention modes for video, audio, and embedded video iframes.

Supported modes: 
- none: no media
- text: plain label, e.g. `Video 1`
- link: markdown link, e.g. `[Video 1](url)` (default)
- image: markdown image syntax, e.g. `![Video 1](url)`
- html: original HTML with irrelevant attributes (class, id, style, data-*, aria-*) stripped

#### `X-Preset`

Schema: `{"type": "string"}`

Apply a preset configuration for common scenarios.

Supported presets:
- reader: optimized for display to human users
- index: optimized for semantic indexing
- research: optimized for academic/research AI agents
- agent: optimized for day-to-day AI agents
- spider: optimized for recursive site crawling

Preset values are applied only to options not explicitly set by the caller.

#### `X-With-Iframe`

Schema: `{"type": "string"}`

Enable filling iframe contents into main. (violates standards)

#### `X-With-Shadow-Dom`

Schema: `{"type": "string"}`

Enable filling shadow dom contents into main. (violates standards)

#### `X-Skip-Cert-Verification`

Schema: `{"type": "string"}`

Enable skipping SSL certificate verification. (violates security best practices)

#### `X-User-Agent`

Schema: `{"type": "string"}`

Override User-Agent.

Several special values: 
- browser: use the internal browser UA
- auto: pass-through your UA if it starts with `Mozilla/5.0`, otherwise use the internal browser UA
- inherit / pass-through: use the User-Agent from the request context if applicable
- bot: Use a pre-defined bot User-Agent from this service
- diversify: Use a diversified browser User-Agent

Or specify your own user agent string.

Note: anonymous users specifying a browser UA will have no effect and will fall back to the internal browser UA.

Default: browser

#### `X-Timeout`

Schema: `{"type": "string"}`

Specify timeout in seconds. Max 180.

#### `X-Locale`

Schema: `{"type": "string"}`

Specify browser locale for the page.

#### `X-Referer`

Schema: `{"type": "string"}`

Specify referer for the page.

#### `X-Token-Budget`

Schema: `{"type": "string"}`

Specify a budget in tokens.

If the resulting token cost exceeds the budget, the request is rejected.

Note this parameter is ignored for the search endpoint.

#### `X-Max-Tokens`

Schema: `{"type": "string"}`

Trim the response content at a maximum number of tokens.

#### `X-Assert-Status-Code`

Schema: `{"type": "string"}`

Assert the HTTP status code of the crawled page. If the actual status code does not match the asserted one, the request is rejected with 422 Unprocessable Entity.

#### `X-Respond-Timing`

Schema: `{"type": "string"}`

Explicitly specify the respond timing. One of the following:

- html: directly return unrendered HTML
- visible-content: return immediately when any content becomes available
- mutation-idle: wait for DOM mutations to settle and remain unchanged for at least 0.2s
- resource-idle: wait for no additional resources that would affect page logic and content has SUCCEEDED loading in 0.5s
- media-idle: wait for no additional resources, including media resources, has SUCCEEDED loading in 0.5s
- network-idle: wait for full load of webpage, also known as networkidle0.

#### `X-Engine`

Schema: `{"type": "string"}`

Specify the engine to use for crawling.

Supported: browser, direct, cf-browser-rendering

#### `X-Base`

Schema: `{"type": "string"}`

Select base modes of relative URLs.

Supported: initial, final

#### `X-Remove-Overlay`

Schema: `{"type": "string"}`

Specify whether to remove overlay elements from the page.

#### `X-Detach-Invisibles`

Schema: `{"type": "string"}`

Temporarily detach elements with computed `display:none` before snapshotting, then restore them.

Requires the browser engine and disables caching.

#### `X-Markdown-Chunking`

Schema: `{"type": "string"}`

Opt-in markdown chunking.

Supported values: 
- true
- h1
- h2
- h3
- h4
- h5
- structured
- s1
- s2
- s3
- s4
- s5

Note if you are expecting text return, the chunking is done by injecting character \u001D

#### `X-Md-Heading-Style`

Schema: `{"type": "string"}`

Heading style of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: setext, atx

#### `X-Md-Hr`

Schema: `{"type": "string"}`

Hr text of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

#### `X-Md-Bullet-List-Marker`

Schema: `{"type": "string"}`

Bullet list marker of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: -, +, *

#### `X-Md-Em-Delimiter`

Schema: `{"type": "string"}`

Em delimiter of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: _, *

#### `X-Md-Strong-Delimiter`

Schema: `{"type": "string"}`

Strong delimiter of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: **, __

#### `X-Md-Link-Style`

Schema: `{"type": "string"}`

Link style of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: inlined, referenced, discarded

#### `X-Md-Link-Reference-Style`

Schema: `{"type": "string"}`

Link reference style of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: full, collapsed, shortcut, discarded

#### `X-Page`

Schema: `{"type": "string"}`

Steer which page to return for uploaded files (PDF, DOC, XLS, PPT, etc.).

1-indexed, 0 is the same as 1. Accepts a page number, a list and/or ranges like `1,3,5-7`.

At most 35 pages can be selected. With multiple pages, DocLayout / OCR runs over each selected page.

Ignored when the target is not a document.

#### `X-Preload-Url`

Schema: `{"type": "string"}`

URL to preload before scraping.

Ignored when no URL is provided.

#### `X-No-Service-Worker`

Schema: `{"type": "string"}`

Disable service workers when running the browser.

Useful for bypassing service-worker-based caching or interception.

### query parameters

#### `url`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `preloadUrl`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `noServiceWorker`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `html`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `base`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x0d"}], "default": "final"}`

- Cast to: < **&quot;initial&quot; | &quot;final&quot;** >

- Member of <CrawlerOptions>

- Defaults to: &#39;final&#39;

#### `pdf`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/FancyFile@0x0e"}]}, {"type": "string"}], "summary": "Base64 encoded PDF."}`

Base64 encoded PDF.

- Cast to: < **FancyFile|string** >

- Member of <CrawlerOptions>

#### `file`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/FancyFile@0x0e"}]}, {"type": "string"}], "summary": "Base64 encoded file."}`

Base64 encoded file.

- Cast to: < **FancyFile|string** >

- Member of <CrawlerOptions>

#### `page`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PageSelection@0x0f"}], "summary": "Steer which page(s) to return for document files. See PageSelection."}`

Steer which page(s) to return for document files. See PageSelection.

- Cast to: < **PageSelection** >

- Member of <CrawlerOptions>

#### `respondWith`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/enum@0x10"}]}, {"type": "string"}], "default": "content"}`

- Cast to: < **&quot;content&quot; | &quot;markdown&quot; | &quot;html&quot; | &quot;text&quot; | &quot;pageshot&quot; | &quot;screenshot&quot; | &quot;vlm&quot; | &quot;readerlm-v2&quot; | &quot;frontmatter&quot; | &quot;readability&quot; | &quot;...|string** >

- Member of <CrawlerOptions>

- Defaults to: &#39;content&#39;

#### `withGeneratedAlt`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}`

- Cast to: < **PseudoBoolean** >

- Member of <CrawlerOptions>

#### `retainImages`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x12"}], "default": "all"}`

- Cast to: < **&quot;none&quot; | &quot;all&quot; | &quot;alt&quot; | &quot;all_p&quot; | &quot;alt_p&quot;** >

- Member of <CrawlerOptions>

- Defaults to: &#39;all&#39;

#### `retainMedia`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x13"}], "default": "link"}`

- Cast to: < **&quot;none&quot; | &quot;text&quot; | &quot;link&quot; | &quot;image&quot; | &quot;html&quot;** >

- Member of <CrawlerOptions>

- Defaults to: &#39;link&#39;

#### `preset`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x14"}]}`

- Cast to: < **&quot;reader&quot; | &quot;index&quot; | &quot;research&quot; | &quot;agent&quot; | &quot;spider&quot; | &quot;ocr&quot; | &quot;ocr+&quot; | &quot;ocr++&quot; | &quot;pdf&quot; | &quot;pdf+&quot; | &quot;pdf++&quot;** >

- Member of <CrawlerOptions>

#### `retainLinks`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x15"}], "default": "all"}`

- Cast to: < **&quot;none&quot; | &quot;all&quot; | &quot;text&quot; | &quot;gpt-oss&quot;** >

- Member of <CrawlerOptions>

- Defaults to: &#39;all&#39;

#### `withLinksSummary`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}, {"type": "string"}]}`

- Cast to: < **PseudoBoolean|string** >

- Member of <CrawlerOptions>

#### `withImagesSummary`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `noCache`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `removeOverlay`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `detachInvisibles`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `noGfm`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}, {"type": "string"}]}`

- Cast to: < **PseudoBoolean|string** >

- Member of <CrawlerOptions>

#### `cacheTolerance`

Schema: `{"type": "number"}`

- Cast to: < **number** >

- Member of <CrawlerOptions>

#### `targetSelector`

Schema: `{"type": "string"}`

- Cast to: < **Array<string>** >

- Member of <CrawlerOptions>

#### `waitForSelector`

Schema: `{"type": "string"}`

- Cast to: < **Array<string>** >

- Member of <CrawlerOptions>

#### `removeSelector`

Schema: `{"type": "string"}`

- Cast to: < **Array<string>** >

- Member of <CrawlerOptions>

#### `keepImgDataUrl`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `withIframe`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}, {"type": "string"}]}`

- Cast to: < **PseudoBoolean|string** >

- Member of <CrawlerOptions>

#### `withShadowDom`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `skipCertVerification`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `webBotAuth`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}, {"allOf": [{"$ref": "#/components/schemas/enum@0x16"}]}]}`

- Cast to: < **PseudoBoolean|&quot;authority&quot; | &quot;target-uri&quot;** >

- Member of <CrawlerOptions>

#### `setCookies`

Schema: `{"oneOf": [{"description": "Can be any value - string, number, boolean, array or object.", "nullable": true}, {"type": "string"}]}`

- Cast to: < **Array<object|string>** >

- Member of <CrawlerOptions>

#### `exportStorageState`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `proxyUrl`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `proxyResources`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `proxy`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `userAgent`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `engine`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/enum@0x1c"}]}, {"type": "string"}]}`

- Cast to: < **&quot;auto&quot; | &quot;browser&quot; | &quot;curl&quot; | &quot;cf-browser-rendering&quot;|string** >

- Member of <CrawlerOptions>

#### `injectPageScript`

Schema: `{"type": "string"}`

- Cast to: < **Array<string>** >

- Member of <CrawlerOptions>

#### `injectFrameScript`

Schema: `{"type": "string"}`

- Cast to: < **Array<string>** >

- Member of <CrawlerOptions>

#### `timeout`

Schema: `{"type": "number"}`

- Cast to: < **number** >

- Member of <CrawlerOptions>

- Some validators will be applied on value(s): (v) => v > 0 &amp;&amp; v <= 180

#### `locale`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `referer`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `tokenBudget`

Schema: `{"type": "number"}`

- Cast to: < **number** >

- Member of <CrawlerOptions>

#### `assertStatusCode`

Schema: `{"type": "number"}`

- Cast to: < **number** >

- Member of <CrawlerOptions>

#### `instruction`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `jsonSchema`

Schema: `{"nullable": true}`

Can be any value - string, number, boolean, array or object.

- Cast to: < **object** >

- Member of <CrawlerOptions>

#### `robotsTxt`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}, {"type": "string"}]}`

- Cast to: < **PseudoBoolean|string** >

- Member of <CrawlerOptions>

#### `zeroDataRetention`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `respondTiming`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x26"}]}`

- Cast to: < **&quot;html&quot; | &quot;visible-content&quot; | &quot;mutation-idle&quot; | &quot;resource-idle&quot; | &quot;media-idle&quot; | &quot;network-idle&quot;** >

- Member of <CrawlerOptions>

#### `markdownChunking`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/enum@0x27"}]}, {"type": "string"}]}`

- Cast to: < **&quot;true&quot; | &quot;h1&quot; | &quot;h2&quot; | &quot;h3&quot; | &quot;h4&quot; | &quot;h5&quot; | &quot;structured&quot; | &quot;s1&quot; | &quot;s2&quot; | &quot;s3&quot; | &quot;s4&quot; | &quot;s5&quot;|string** >

- Member of <CrawlerOptions>

#### `maxTokens`

Schema: `{"type": "number"}`

- Cast to: < **number** >

- Member of <CrawlerOptions>

- Some validators will be applied on value(s): (v) => v >= 500

### Request body

```json
{
 "content": {
  "application/json": {
   "schema": {
    "allOf": [
     {
      "$ref": "#/components/schemas/JinaEmbeddingsAuthDTO@0x0b"
     },
     {
      "$ref": "#/components/schemas/CrawlerOptionsHeaderOnly@0x3b"
     },
     {
      "$ref": "#/components/schemas/CrawlerOptions@0x28"
     }
    ]
   }
  },
  "multipart/form-data": {
   "schema": {
    "allOf": [
     {
      "$ref": "#/components/schemas/JinaEmbeddingsAuthDTO@0x0b"
     },
     {
      "$ref": "#/components/schemas/CrawlerOptionsHeaderOnly@0x3b"
     },
     {
      "$ref": "#/components/schemas/CrawlerOptions@0x28"
     }
    ]
   }
  },
  "application/x-www-form-urlencoded": {
   "schema": {
    "type": "object",
    "properties": {
     "url": {
      "type": "string",
      "description": "- Cast to: &lt; **string** &gt;\n\n- Member of &lt;CrawlerOptions&gt;"
     },
     "preloadUrl": {
      "type": "string",
      "description": "- Cast to: &lt; **string** &gt;\n\n- Member of &lt;CrawlerOptions&gt;"
     },
     "noServiceWorker": {
      "allOf": [
       {
        "$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"
       }
      ],
      "description": "- Cast to: &lt; **PseudoBooleanLoose** &gt;\n\n- Member of &lt;CrawlerOptions&gt;"
     },
     "html": {
      "type": "string",
      "description": "- Cast to: &lt; **string** &gt;\n\n- Member of &lt;CrawlerOptions&gt;"
     },
     "base": {
      "allOf": [
       {
        "$ref": "#/components/schemas/enum@0x0d"
       }
      ],
      "default": "final",
      "description": "- Cast to: &lt; **&quot;initial&quot; | &quot;final&quot;** &gt;\n\n- Member of &lt;CrawlerOptions&gt;\n\n- Defaults to: &#39;final&#39;"
     },
     "pdf": {
      "oneOf": [
       {
        "allOf": [
         {
          "$ref": "#/components/schemas/FancyFile@0x0e"
         }
        ]
       },
       {
        "type": "string"
       }
      ],
      "summary": "Base64 encoded PDF.",
      "description": "Base64 encoded PDF.\n\n- Cast to: &lt; **FancyFile|string** &gt;\n\n- Member of &lt;CrawlerOptions&gt;"
     },
     "file": {
      "oneOf": [
       {
        "allOf": [
         {
          "$ref": "#/components/schemas/FancyFile@0x0e"
         }
        ]
       },
       {
        "type": "string"
       }
      ],
      "summary": "Base64 encoded file.",
      "description": "Base64 encoded file.\n\n- Cast to: &lt; **FancyFile|string** &gt;\n\n- Member of &lt;CrawlerOptions&gt;"
     },
     "page": {
      "allOf": [
       {
        "$ref": "#/components/schemas/PageSelection@0x0f"
       }
      ],
      "summary": "Steer which page(s) to return for document files. See PageSelection.",
      "description": "Steer which page(s) to return for document files. See PageSelection.\n\n- Cast to: &lt; **PageSelection** &gt;\n\n- Member of &lt;CrawlerOptions&gt;"
     },
     "respondWith": {
      "oneOf": [
       {
        "allOf": [
         {
          "$ref": "#/components/schemas/enum@0x10"
         }
        ]
 
```

### Responses

- `200` OK — text/plain; charset=utf-8: string; application/json: ReaderEnvelopeWrappedFormattedPageDto; text/event-stream: OutputServerEventStream@0x44
- `400` Bad Request — application/json: ParamValidationError@0x29, DataStreamBrokenError@0x2a
- `401` Unauthorized — application/json: AuthenticationFailedError@0x2b, AuthenticationRequiredError@0x2c
- `402` Payment Required — application/json: TierFeatureConstraintError@0x2d, InsufficientBalanceError@0x2e
- `403` Forbidden — application/json: OperationNotAllowedError@0x2f, AbuseAlleviationError@0x30
- `409` Conflict — application/json: ResourcePolicyDenyError@0x31, BudgetExceededError@0x32
- `413` Payload Too Large — application/json: TargetFileTooLargeError@0x33
- `422` Unprocessable Entity — application/json: SubmittedDataMalformedError@0x34, DownstreamServiceFailureError@0x35, AssertionFailureError@0x36
- `429` Too Many Requests — application/json: RateLimitTriggeredError@0x37
- `451` Unavailable For Legal Reasons — application/json: HarmfulContentError@0x38
- `500` Internal Server Error — application/json: DownstreamServiceError@0x39
- `503` Service Unavailable — application/json: ServiceNodeResourceDrainError@0x3a

## `GET /{url}`

operationId: `None`

Read a URL and get its content back in an LLM-friendly format.

### path parameters

#### `url` (required)

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

### header parameters

#### `Authorization`

Schema: `{"anyOf": [{"type": "string", "format": "token"}]}`

Jina Token for authentication.

- Member of <JinaEmbeddingsAuthDTO>

- Authorization: Bearer {YOUR_JINA_TOKEN}

#### `Accept`

Schema: `{"type": "string"}`

Specifies your preference for the response format.

Supported formats: 
- text/event-stream
- application/json or text/json
- text/plain

#### `X-Cache-Tolerance`

Schema: `{"type": "string"}`

Sets internal cache tolerance in seconds if this header is specified with a integer.

#### `X-No-Cache`

Schema: `{"type": "string"}`

Ignores internal cache if this header is specified with a value.

Equivalent to X-Cache-Tolerance: 0

#### `X-Respond-With`

Schema: `{"type": "string"}`

Specifies the (non-default) form of the crawled data you prefer.

Supported formats: 
- markdown
- html
- text
- pageshot
- screenshot
- content
- frontmatter
- any combination of the above
- vlm
- jina-ocr-v1
- jina-ocr
- readerlm-v2


Default: content

#### `X-Wait-For-Selector`

Schema: `{"type": "string"}`

Specifies a CSS selector to wait for the appearance of such an element before returning.

Example: `X-Wait-For-Selector: .content-block`

#### `X-Target-Selector`

Schema: `{"type": "string"}`

Specifies a CSS selector for return target instead of the full html.

Implies `X-Wait-For-Selector: (same selector)`

#### `X-Remove-Selector`

Schema: `{"type": "string"}`

Specifies a CSS selector to remove elements from the full html.

Example `X-Remove-Selector: nav`

#### `X-Keep-Img-Data-Url`

Schema: `{"type": "string"}`

Keep data-url as it instead of transforming them to object-url. (Only applicable when targeting markdown format)

Example `X-Keep-Img-Data-Url: true`

#### `X-Proxy-Url`

Schema: `{"type": "string"}`

Specifies your custom proxy if you prefer to use one.

Supported protocols: 
- http
- https
- socks4
- socks5

For authentication, https://user:pass@host:port

#### `X-Proxy-Resources`

Schema: `{"type": "string"}`

Whether to load resources like image/style/scripts via the proxy server.

#### `X-Proxy`

Schema: `{"type": "string"}`

Use a proxy server provided by us.

Optionally specify two-letter country code.

#### `X-Robots-Txt`

Schema: `{"type": "string"}`

Load and conform to the respective robot.txt on the target origin.

Optionally specify a bot UA to check against.

#### `DNT`

Schema: `{"type": "string"}`

When set to 1, prevent the result of this request to be cached in the system.

#### `X-Set-Cookie`

Schema: `{"type": "string"}`

Sets cookie(s) to the headless browser for your request. 

Syntax is the same with standard Set-Cookie

#### `X-Export-Storage-State`

Schema: `{"type": "string"}`

Export the browser storage state (cookies and per-origin localStorage) accumulated during the crawl.

When enabled, the JSON response includes a `storageState` field whose shape mirrors the `storageState` request option, so it can be fed back into a subsequent request.

Requires the browser engine and disables caching.

#### `X-With-Generated-Alt`

Schema: `{"type": "string"}`

Enable automatic alt-text generating for images without an meaningful alt-text.

Note: Does not work when `X-Respond-With` is specified

#### `X-With-Images-Summary`

Schema: `{"type": "string"}`

Enable dedicated summary section for images on the page.

#### `X-With-links-Summary`

Schema: `{"type": "string"}`

Enable dedicated summary section for hyper links on the page.

#### `X-Retain-Links`

Schema: `{"type": "string"}`

Link retention modes.

Supported modes: 
- all: all links
- none: no links
- text: only link text
- gpt-oss: gpt-oss link citation format `【{id}†.*】`

#### `X-Retain-Images`

Schema: `{"type": "string"}`

Image retention modes.

Supported modes: 
- all: all images
- none: no images
- alt: only alt text
- all_p: all images and with generated alt text
- alt_p: only alt text and with generated alt

#### `X-Retain-Media`

Schema: `{"type": "string"}`

Media retention modes for video, audio, and embedded video iframes.

Supported modes: 
- none: no media
- text: plain label, e.g. `Video 1`
- link: markdown link, e.g. `[Video 1](url)` (default)
- image: markdown image syntax, e.g. `![Video 1](url)`
- html: original HTML with irrelevant attributes (class, id, style, data-*, aria-*) stripped

#### `X-Preset`

Schema: `{"type": "string"}`

Apply a preset configuration for common scenarios.

Supported presets:
- reader: optimized for display to human users
- index: optimized for semantic indexing
- research: optimized for academic/research AI agents
- agent: optimized for day-to-day AI agents
- spider: optimized for recursive site crawling

Preset values are applied only to options not explicitly set by the caller.

#### `X-With-Iframe`

Schema: `{"type": "string"}`

Enable filling iframe contents into main. (violates standards)

#### `X-With-Shadow-Dom`

Schema: `{"type": "string"}`

Enable filling shadow dom contents into main. (violates standards)

#### `X-Skip-Cert-Verification`

Schema: `{"type": "string"}`

Enable skipping SSL certificate verification. (violates security best practices)

#### `X-User-Agent`

Schema: `{"type": "string"}`

Override User-Agent.

Several special values: 
- browser: use the internal browser UA
- auto: pass-through your UA if it starts with `Mozilla/5.0`, otherwise use the internal browser UA
- inherit / pass-through: use the User-Agent from the request context if applicable
- bot: Use a pre-defined bot User-Agent from this service
- diversify: Use a diversified browser User-Agent

Or specify your own user agent string.

Note: anonymous users specifying a browser UA will have no effect and will fall back to the internal browser UA.

Default: browser

#### `X-Timeout`

Schema: `{"type": "string"}`

Specify timeout in seconds. Max 180.

#### `X-Locale`

Schema: `{"type": "string"}`

Specify browser locale for the page.

#### `X-Referer`

Schema: `{"type": "string"}`

Specify referer for the page.

#### `X-Token-Budget`

Schema: `{"type": "string"}`

Specify a budget in tokens.

If the resulting token cost exceeds the budget, the request is rejected.

Note this parameter is ignored for the search endpoint.

#### `X-Max-Tokens`

Schema: `{"type": "string"}`

Trim the response content at a maximum number of tokens.

#### `X-Assert-Status-Code`

Schema: `{"type": "string"}`

Assert the HTTP status code of the crawled page. If the actual status code does not match the asserted one, the request is rejected with 422 Unprocessable Entity.

#### `X-Respond-Timing`

Schema: `{"type": "string"}`

Explicitly specify the respond timing. One of the following:

- html: directly return unrendered HTML
- visible-content: return immediately when any content becomes available
- mutation-idle: wait for DOM mutations to settle and remain unchanged for at least 0.2s
- resource-idle: wait for no additional resources that would affect page logic and content has SUCCEEDED loading in 0.5s
- media-idle: wait for no additional resources, including media resources, has SUCCEEDED loading in 0.5s
- network-idle: wait for full load of webpage, also known as networkidle0.

#### `X-Engine`

Schema: `{"type": "string"}`

Specify the engine to use for crawling.

Supported: browser, direct, cf-browser-rendering

#### `X-Base`

Schema: `{"type": "string"}`

Select base modes of relative URLs.

Supported: initial, final

#### `X-Remove-Overlay`

Schema: `{"type": "string"}`

Specify whether to remove overlay elements from the page.

#### `X-Detach-Invisibles`

Schema: `{"type": "string"}`

Temporarily detach elements with computed `display:none` before snapshotting, then restore them.

Requires the browser engine and disables caching.

#### `X-Markdown-Chunking`

Schema: `{"type": "string"}`

Opt-in markdown chunking.

Supported values: 
- true
- h1
- h2
- h3
- h4
- h5
- structured
- s1
- s2
- s3
- s4
- s5

Note if you are expecting text return, the chunking is done by injecting character \u001D

#### `X-Md-Heading-Style`

Schema: `{"type": "string"}`

Heading style of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: setext, atx

#### `X-Md-Hr`

Schema: `{"type": "string"}`

Hr text of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

#### `X-Md-Bullet-List-Marker`

Schema: `{"type": "string"}`

Bullet list marker of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: -, +, *

#### `X-Md-Em-Delimiter`

Schema: `{"type": "string"}`

Em delimiter of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: _, *

#### `X-Md-Strong-Delimiter`

Schema: `{"type": "string"}`

Strong delimiter of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: **, __

#### `X-Md-Link-Style`

Schema: `{"type": "string"}`

Link style of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: inlined, referenced, discarded

#### `X-Md-Link-Reference-Style`

Schema: `{"type": "string"}`

Link reference style of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: full, collapsed, shortcut, discarded

#### `X-Page`

Schema: `{"type": "string"}`

Steer which page to return for uploaded files (PDF, DOC, XLS, PPT, etc.).

1-indexed, 0 is the same as 1. Accepts a page number, a list and/or ranges like `1,3,5-7`.

At most 35 pages can be selected. With multiple pages, DocLayout / OCR runs over each selected page.

Ignored when the target is not a document.

#### `X-Preload-Url`

Schema: `{"type": "string"}`

URL to preload before scraping.

Ignored when no URL is provided.

#### `X-No-Service-Worker`

Schema: `{"type": "string"}`

Disable service workers when running the browser.

Useful for bypassing service-worker-based caching or interception.

### query parameters

#### `preloadUrl`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `noServiceWorker`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `html`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `base`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x0d"}], "default": "final"}`

- Cast to: < **&quot;initial&quot; | &quot;final&quot;** >

- Member of <CrawlerOptions>

- Defaults to: &#39;final&#39;

#### `pdf`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/FancyFile@0x0e"}]}, {"type": "string"}], "summary": "Base64 encoded PDF."}`

Base64 encoded PDF.

- Cast to: < **FancyFile|string** >

- Member of <CrawlerOptions>

#### `file`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/FancyFile@0x0e"}]}, {"type": "string"}], "summary": "Base64 encoded file."}`

Base64 encoded file.

- Cast to: < **FancyFile|string** >

- Member of <CrawlerOptions>

#### `page`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PageSelection@0x0f"}], "summary": "Steer which page(s) to return for document files. See PageSelection."}`

Steer which page(s) to return for document files. See PageSelection.

- Cast to: < **PageSelection** >

- Member of <CrawlerOptions>

#### `respondWith`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/enum@0x10"}]}, {"type": "string"}], "default": "content"}`

- Cast to: < **&quot;content&quot; | &quot;markdown&quot; | &quot;html&quot; | &quot;text&quot; | &quot;pageshot&quot; | &quot;screenshot&quot; | &quot;vlm&quot; | &quot;readerlm-v2&quot; | &quot;frontmatter&quot; | &quot;readability&quot; | &quot;...|string** >

- Member of <CrawlerOptions>

- Defaults to: &#39;content&#39;

#### `withGeneratedAlt`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}`

- Cast to: < **PseudoBoolean** >

- Member of <CrawlerOptions>

#### `retainImages`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x12"}], "default": "all"}`

- Cast to: < **&quot;none&quot; | &quot;all&quot; | &quot;alt&quot; | &quot;all_p&quot; | &quot;alt_p&quot;** >

- Member of <CrawlerOptions>

- Defaults to: &#39;all&#39;

#### `retainMedia`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x13"}], "default": "link"}`

- Cast to: < **&quot;none&quot; | &quot;text&quot; | &quot;link&quot; | &quot;image&quot; | &quot;html&quot;** >

- Member of <CrawlerOptions>

- Defaults to: &#39;link&#39;

#### `preset`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x14"}]}`

- Cast to: < **&quot;reader&quot; | &quot;index&quot; | &quot;research&quot; | &quot;agent&quot; | &quot;spider&quot; | &quot;ocr&quot; | &quot;ocr+&quot; | &quot;ocr++&quot; | &quot;pdf&quot; | &quot;pdf+&quot; | &quot;pdf++&quot;** >

- Member of <CrawlerOptions>

#### `retainLinks`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x15"}], "default": "all"}`

- Cast to: < **&quot;none&quot; | &quot;all&quot; | &quot;text&quot; | &quot;gpt-oss&quot;** >

- Member of <CrawlerOptions>

- Defaults to: &#39;all&#39;

#### `withLinksSummary`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}, {"type": "string"}]}`

- Cast to: < **PseudoBoolean|string** >

- Member of <CrawlerOptions>

#### `withImagesSummary`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `noCache`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `removeOverlay`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `detachInvisibles`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `noGfm`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}, {"type": "string"}]}`

- Cast to: < **PseudoBoolean|string** >

- Member of <CrawlerOptions>

#### `cacheTolerance`

Schema: `{"type": "number"}`

- Cast to: < **number** >

- Member of <CrawlerOptions>

#### `targetSelector`

Schema: `{"type": "string"}`

- Cast to: < **Array<string>** >

- Member of <CrawlerOptions>

#### `waitForSelector`

Schema: `{"type": "string"}`

- Cast to: < **Array<string>** >

- Member of <CrawlerOptions>

#### `removeSelector`

Schema: `{"type": "string"}`

- Cast to: < **Array<string>** >

- Member of <CrawlerOptions>

#### `keepImgDataUrl`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `withIframe`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}, {"type": "string"}]}`

- Cast to: < **PseudoBoolean|string** >

- Member of <CrawlerOptions>

#### `withShadowDom`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `skipCertVerification`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `webBotAuth`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}, {"allOf": [{"$ref": "#/components/schemas/enum@0x16"}]}]}`

- Cast to: < **PseudoBoolean|&quot;authority&quot; | &quot;target-uri&quot;** >

- Member of <CrawlerOptions>

#### `setCookies`

Schema: `{"oneOf": [{"description": "Can be any value - string, number, boolean, array or object.", "nullable": true}, {"type": "string"}]}`

- Cast to: < **Array<object|string>** >

- Member of <CrawlerOptions>

#### `exportStorageState`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `proxyUrl`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `proxyResources`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `proxy`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `userAgent`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `engine`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/enum@0x1c"}]}, {"type": "string"}]}`

- Cast to: < **&quot;auto&quot; | &quot;browser&quot; | &quot;curl&quot; | &quot;cf-browser-rendering&quot;|string** >

- Member of <CrawlerOptions>

#### `injectPageScript`

Schema: `{"type": "string"}`

- Cast to: < **Array<string>** >

- Member of <CrawlerOptions>

#### `injectFrameScript`

Schema: `{"type": "string"}`

- Cast to: < **Array<string>** >

- Member of <CrawlerOptions>

#### `timeout`

Schema: `{"type": "number"}`

- Cast to: < **number** >

- Member of <CrawlerOptions>

- Some validators will be applied on value(s): (v) => v > 0 &amp;&amp; v <= 180

#### `locale`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `referer`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `tokenBudget`

Schema: `{"type": "number"}`

- Cast to: < **number** >

- Member of <CrawlerOptions>

#### `assertStatusCode`

Schema: `{"type": "number"}`

- Cast to: < **number** >

- Member of <CrawlerOptions>

#### `instruction`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `jsonSchema`

Schema: `{"nullable": true}`

Can be any value - string, number, boolean, array or object.

- Cast to: < **object** >

- Member of <CrawlerOptions>

#### `robotsTxt`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}, {"type": "string"}]}`

- Cast to: < **PseudoBoolean|string** >

- Member of <CrawlerOptions>

#### `zeroDataRetention`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `respondTiming`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x26"}]}`

- Cast to: < **&quot;html&quot; | &quot;visible-content&quot; | &quot;mutation-idle&quot; | &quot;resource-idle&quot; | &quot;media-idle&quot; | &quot;network-idle&quot;** >

- Member of <CrawlerOptions>

#### `markdownChunking`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/enum@0x27"}]}, {"type": "string"}]}`

- Cast to: < **&quot;true&quot; | &quot;h1&quot; | &quot;h2&quot; | &quot;h3&quot; | &quot;h4&quot; | &quot;h5&quot; | &quot;structured&quot; | &quot;s1&quot; | &quot;s2&quot; | &quot;s3&quot; | &quot;s4&quot; | &quot;s5&quot;|string** >

- Member of <CrawlerOptions>

#### `maxTokens`

Schema: `{"type": "number"}`

- Cast to: < **number** >

- Member of <CrawlerOptions>

- Some validators will be applied on value(s): (v) => v >= 500

### Responses

- `200` OK — text/plain; charset=utf-8: string; application/json: ReaderEnvelopeWrappedFormattedPageDto; text/event-stream: OutputServerEventStream@0x44
- `400` Bad Request — application/json: ParamValidationError@0x29, DataStreamBrokenError@0x2a
- `401` Unauthorized — application/json: AuthenticationFailedError@0x2b, AuthenticationRequiredError@0x2c
- `402` Payment Required — application/json: TierFeatureConstraintError@0x2d, InsufficientBalanceError@0x2e
- `403` Forbidden — application/json: OperationNotAllowedError@0x2f, AbuseAlleviationError@0x30
- `409` Conflict — application/json: ResourcePolicyDenyError@0x31, BudgetExceededError@0x32
- `413` Payload Too Large — application/json: TargetFileTooLargeError@0x33
- `422` Unprocessable Entity — application/json: SubmittedDataMalformedError@0x34, DownstreamServiceFailureError@0x35, AssertionFailureError@0x36
- `429` Too Many Requests — application/json: RateLimitTriggeredError@0x37
- `451` Unavailable For Legal Reasons — application/json: HarmfulContentError@0x38
- `500` Internal Server Error — application/json: DownstreamServiceError@0x39
- `503` Service Unavailable — application/json: ServiceNodeResourceDrainError@0x3a

#### 200 application/json envelope

```json
{
 "title": "ReaderEnvelopeWrappedFormattedPageDto",
 "type": "object",
 "properties": {
  "code": {
   "type": "number",
   "summary": "Envelope code.\n\nMirror of HTTP status code",
   "description": "[REQUIRED]\n\nEnvelope code.\n\nMirror of HTTP status code\n\n- Cast to: &lt; **number** &gt;\n\n- Member of &lt;ReaderEnvelope&gt;\n\n- Defaults to: 200",
   "default": 200
  },
  "status": {
   "type": "number",
   "summary": "Envelope status.\n\nIn extension to HTTP status code",
   "description": "[REQUIRED]\n\nEnvelope status.\n\nIn extension to HTTP status code\n\n- Cast to: &lt; **number** &gt;\n\n- Member of &lt;ReaderEnvelope&gt;\n\n- Defaults to: 20000",
   "default": 20000
  },
  "data": {
   "allOf": [
    {
     "$ref": "#/components/schemas/FormattedPageDto@0x43"
    }
   ],
   "summary": "The result payload you expect",
   "description": "The result payload you expect\n\n- Cast to: &lt; **FormattedPageDto** &gt;\n\n- Member of &lt;ReaderEnvelope&gt;"
  },
  "meta": {
   "description": "The metadata that the payload sometimes came with\n\n- Cast to: &lt; **object** &gt;\n\n- Member of &lt;ReaderEnvelope&gt;",
   "nullable": true,
   "summary": "The metadata that the payload sometimes came with"
  }
 },
 "required": [
  "code",
  "status"
 ],
 "primitive": true
}
```

## `POST /{url}`

operationId: `None`

Read a URL and get its content back in an LLM-friendly format.

### path parameters

#### `url` (required)

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

### header parameters

#### `Authorization`

Schema: `{"anyOf": [{"type": "string", "format": "token"}]}`

Jina Token for authentication.

- Member of <JinaEmbeddingsAuthDTO>

- Authorization: Bearer {YOUR_JINA_TOKEN}

#### `Accept`

Schema: `{"type": "string"}`

Specifies your preference for the response format.

Supported formats: 
- text/event-stream
- application/json or text/json
- text/plain

#### `X-Cache-Tolerance`

Schema: `{"type": "string"}`

Sets internal cache tolerance in seconds if this header is specified with a integer.

#### `X-No-Cache`

Schema: `{"type": "string"}`

Ignores internal cache if this header is specified with a value.

Equivalent to X-Cache-Tolerance: 0

#### `X-Respond-With`

Schema: `{"type": "string"}`

Specifies the (non-default) form of the crawled data you prefer.

Supported formats: 
- markdown
- html
- text
- pageshot
- screenshot
- content
- frontmatter
- any combination of the above
- vlm
- jina-ocr-v1
- jina-ocr
- readerlm-v2


Default: content

#### `X-Wait-For-Selector`

Schema: `{"type": "string"}`

Specifies a CSS selector to wait for the appearance of such an element before returning.

Example: `X-Wait-For-Selector: .content-block`

#### `X-Target-Selector`

Schema: `{"type": "string"}`

Specifies a CSS selector for return target instead of the full html.

Implies `X-Wait-For-Selector: (same selector)`

#### `X-Remove-Selector`

Schema: `{"type": "string"}`

Specifies a CSS selector to remove elements from the full html.

Example `X-Remove-Selector: nav`

#### `X-Keep-Img-Data-Url`

Schema: `{"type": "string"}`

Keep data-url as it instead of transforming them to object-url. (Only applicable when targeting markdown format)

Example `X-Keep-Img-Data-Url: true`

#### `X-Proxy-Url`

Schema: `{"type": "string"}`

Specifies your custom proxy if you prefer to use one.

Supported protocols: 
- http
- https
- socks4
- socks5

For authentication, https://user:pass@host:port

#### `X-Proxy-Resources`

Schema: `{"type": "string"}`

Whether to load resources like image/style/scripts via the proxy server.

#### `X-Proxy`

Schema: `{"type": "string"}`

Use a proxy server provided by us.

Optionally specify two-letter country code.

#### `X-Robots-Txt`

Schema: `{"type": "string"}`

Load and conform to the respective robot.txt on the target origin.

Optionally specify a bot UA to check against.

#### `DNT`

Schema: `{"type": "string"}`

When set to 1, prevent the result of this request to be cached in the system.

#### `X-Set-Cookie`

Schema: `{"type": "string"}`

Sets cookie(s) to the headless browser for your request. 

Syntax is the same with standard Set-Cookie

#### `X-Export-Storage-State`

Schema: `{"type": "string"}`

Export the browser storage state (cookies and per-origin localStorage) accumulated during the crawl.

When enabled, the JSON response includes a `storageState` field whose shape mirrors the `storageState` request option, so it can be fed back into a subsequent request.

Requires the browser engine and disables caching.

#### `X-With-Generated-Alt`

Schema: `{"type": "string"}`

Enable automatic alt-text generating for images without an meaningful alt-text.

Note: Does not work when `X-Respond-With` is specified

#### `X-With-Images-Summary`

Schema: `{"type": "string"}`

Enable dedicated summary section for images on the page.

#### `X-With-links-Summary`

Schema: `{"type": "string"}`

Enable dedicated summary section for hyper links on the page.

#### `X-Retain-Links`

Schema: `{"type": "string"}`

Link retention modes.

Supported modes: 
- all: all links
- none: no links
- text: only link text
- gpt-oss: gpt-oss link citation format `【{id}†.*】`

#### `X-Retain-Images`

Schema: `{"type": "string"}`

Image retention modes.

Supported modes: 
- all: all images
- none: no images
- alt: only alt text
- all_p: all images and with generated alt text
- alt_p: only alt text and with generated alt

#### `X-Retain-Media`

Schema: `{"type": "string"}`

Media retention modes for video, audio, and embedded video iframes.

Supported modes: 
- none: no media
- text: plain label, e.g. `Video 1`
- link: markdown link, e.g. `[Video 1](url)` (default)
- image: markdown image syntax, e.g. `![Video 1](url)`
- html: original HTML with irrelevant attributes (class, id, style, data-*, aria-*) stripped

#### `X-Preset`

Schema: `{"type": "string"}`

Apply a preset configuration for common scenarios.

Supported presets:
- reader: optimized for display to human users
- index: optimized for semantic indexing
- research: optimized for academic/research AI agents
- agent: optimized for day-to-day AI agents
- spider: optimized for recursive site crawling

Preset values are applied only to options not explicitly set by the caller.

#### `X-With-Iframe`

Schema: `{"type": "string"}`

Enable filling iframe contents into main. (violates standards)

#### `X-With-Shadow-Dom`

Schema: `{"type": "string"}`

Enable filling shadow dom contents into main. (violates standards)

#### `X-Skip-Cert-Verification`

Schema: `{"type": "string"}`

Enable skipping SSL certificate verification. (violates security best practices)

#### `X-User-Agent`

Schema: `{"type": "string"}`

Override User-Agent.

Several special values: 
- browser: use the internal browser UA
- auto: pass-through your UA if it starts with `Mozilla/5.0`, otherwise use the internal browser UA
- inherit / pass-through: use the User-Agent from the request context if applicable
- bot: Use a pre-defined bot User-Agent from this service
- diversify: Use a diversified browser User-Agent

Or specify your own user agent string.

Note: anonymous users specifying a browser UA will have no effect and will fall back to the internal browser UA.

Default: browser

#### `X-Timeout`

Schema: `{"type": "string"}`

Specify timeout in seconds. Max 180.

#### `X-Locale`

Schema: `{"type": "string"}`

Specify browser locale for the page.

#### `X-Referer`

Schema: `{"type": "string"}`

Specify referer for the page.

#### `X-Token-Budget`

Schema: `{"type": "string"}`

Specify a budget in tokens.

If the resulting token cost exceeds the budget, the request is rejected.

Note this parameter is ignored for the search endpoint.

#### `X-Max-Tokens`

Schema: `{"type": "string"}`

Trim the response content at a maximum number of tokens.

#### `X-Assert-Status-Code`

Schema: `{"type": "string"}`

Assert the HTTP status code of the crawled page. If the actual status code does not match the asserted one, the request is rejected with 422 Unprocessable Entity.

#### `X-Respond-Timing`

Schema: `{"type": "string"}`

Explicitly specify the respond timing. One of the following:

- html: directly return unrendered HTML
- visible-content: return immediately when any content becomes available
- mutation-idle: wait for DOM mutations to settle and remain unchanged for at least 0.2s
- resource-idle: wait for no additional resources that would affect page logic and content has SUCCEEDED loading in 0.5s
- media-idle: wait for no additional resources, including media resources, has SUCCEEDED loading in 0.5s
- network-idle: wait for full load of webpage, also known as networkidle0.

#### `X-Engine`

Schema: `{"type": "string"}`

Specify the engine to use for crawling.

Supported: browser, direct, cf-browser-rendering

#### `X-Base`

Schema: `{"type": "string"}`

Select base modes of relative URLs.

Supported: initial, final

#### `X-Remove-Overlay`

Schema: `{"type": "string"}`

Specify whether to remove overlay elements from the page.

#### `X-Detach-Invisibles`

Schema: `{"type": "string"}`

Temporarily detach elements with computed `display:none` before snapshotting, then restore them.

Requires the browser engine and disables caching.

#### `X-Markdown-Chunking`

Schema: `{"type": "string"}`

Opt-in markdown chunking.

Supported values: 
- true
- h1
- h2
- h3
- h4
- h5
- structured
- s1
- s2
- s3
- s4
- s5

Note if you are expecting text return, the chunking is done by injecting character \u001D

#### `X-Md-Heading-Style`

Schema: `{"type": "string"}`

Heading style of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: setext, atx

#### `X-Md-Hr`

Schema: `{"type": "string"}`

Hr text of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

#### `X-Md-Bullet-List-Marker`

Schema: `{"type": "string"}`

Bullet list marker of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: -, +, *

#### `X-Md-Em-Delimiter`

Schema: `{"type": "string"}`

Em delimiter of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: _, *

#### `X-Md-Strong-Delimiter`

Schema: `{"type": "string"}`

Strong delimiter of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: **, __

#### `X-Md-Link-Style`

Schema: `{"type": "string"}`

Link style of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: inlined, referenced, discarded

#### `X-Md-Link-Reference-Style`

Schema: `{"type": "string"}`

Link reference style of the generated markdown.

This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).

Supported: full, collapsed, shortcut, discarded

#### `X-Page`

Schema: `{"type": "string"}`

Steer which page to return for uploaded files (PDF, DOC, XLS, PPT, etc.).

1-indexed, 0 is the same as 1. Accepts a page number, a list and/or ranges like `1,3,5-7`.

At most 35 pages can be selected. With multiple pages, DocLayout / OCR runs over each selected page.

Ignored when the target is not a document.

#### `X-Preload-Url`

Schema: `{"type": "string"}`

URL to preload before scraping.

Ignored when no URL is provided.

#### `X-No-Service-Worker`

Schema: `{"type": "string"}`

Disable service workers when running the browser.

Useful for bypassing service-worker-based caching or interception.

### query parameters

#### `preloadUrl`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `noServiceWorker`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `html`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `base`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x0d"}], "default": "final"}`

- Cast to: < **&quot;initial&quot; | &quot;final&quot;** >

- Member of <CrawlerOptions>

- Defaults to: &#39;final&#39;

#### `pdf`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/FancyFile@0x0e"}]}, {"type": "string"}], "summary": "Base64 encoded PDF."}`

Base64 encoded PDF.

- Cast to: < **FancyFile|string** >

- Member of <CrawlerOptions>

#### `file`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/FancyFile@0x0e"}]}, {"type": "string"}], "summary": "Base64 encoded file."}`

Base64 encoded file.

- Cast to: < **FancyFile|string** >

- Member of <CrawlerOptions>

#### `page`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PageSelection@0x0f"}], "summary": "Steer which page(s) to return for document files. See PageSelection."}`

Steer which page(s) to return for document files. See PageSelection.

- Cast to: < **PageSelection** >

- Member of <CrawlerOptions>

#### `respondWith`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/enum@0x10"}]}, {"type": "string"}], "default": "content"}`

- Cast to: < **&quot;content&quot; | &quot;markdown&quot; | &quot;html&quot; | &quot;text&quot; | &quot;pageshot&quot; | &quot;screenshot&quot; | &quot;vlm&quot; | &quot;readerlm-v2&quot; | &quot;frontmatter&quot; | &quot;readability&quot; | &quot;...|string** >

- Member of <CrawlerOptions>

- Defaults to: &#39;content&#39;

#### `withGeneratedAlt`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}`

- Cast to: < **PseudoBoolean** >

- Member of <CrawlerOptions>

#### `retainImages`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x12"}], "default": "all"}`

- Cast to: < **&quot;none&quot; | &quot;all&quot; | &quot;alt&quot; | &quot;all_p&quot; | &quot;alt_p&quot;** >

- Member of <CrawlerOptions>

- Defaults to: &#39;all&#39;

#### `retainMedia`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x13"}], "default": "link"}`

- Cast to: < **&quot;none&quot; | &quot;text&quot; | &quot;link&quot; | &quot;image&quot; | &quot;html&quot;** >

- Member of <CrawlerOptions>

- Defaults to: &#39;link&#39;

#### `preset`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x14"}]}`

- Cast to: < **&quot;reader&quot; | &quot;index&quot; | &quot;research&quot; | &quot;agent&quot; | &quot;spider&quot; | &quot;ocr&quot; | &quot;ocr+&quot; | &quot;ocr++&quot; | &quot;pdf&quot; | &quot;pdf+&quot; | &quot;pdf++&quot;** >

- Member of <CrawlerOptions>

#### `retainLinks`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x15"}], "default": "all"}`

- Cast to: < **&quot;none&quot; | &quot;all&quot; | &quot;text&quot; | &quot;gpt-oss&quot;** >

- Member of <CrawlerOptions>

- Defaults to: &#39;all&#39;

#### `withLinksSummary`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}, {"type": "string"}]}`

- Cast to: < **PseudoBoolean|string** >

- Member of <CrawlerOptions>

#### `withImagesSummary`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `noCache`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `removeOverlay`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `detachInvisibles`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `noGfm`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}, {"type": "string"}]}`

- Cast to: < **PseudoBoolean|string** >

- Member of <CrawlerOptions>

#### `cacheTolerance`

Schema: `{"type": "number"}`

- Cast to: < **number** >

- Member of <CrawlerOptions>

#### `targetSelector`

Schema: `{"type": "string"}`

- Cast to: < **Array<string>** >

- Member of <CrawlerOptions>

#### `waitForSelector`

Schema: `{"type": "string"}`

- Cast to: < **Array<string>** >

- Member of <CrawlerOptions>

#### `removeSelector`

Schema: `{"type": "string"}`

- Cast to: < **Array<string>** >

- Member of <CrawlerOptions>

#### `keepImgDataUrl`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `withIframe`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}, {"type": "string"}]}`

- Cast to: < **PseudoBoolean|string** >

- Member of <CrawlerOptions>

#### `withShadowDom`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `skipCertVerification`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `webBotAuth`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}, {"allOf": [{"$ref": "#/components/schemas/enum@0x16"}]}]}`

- Cast to: < **PseudoBoolean|&quot;authority&quot; | &quot;target-uri&quot;** >

- Member of <CrawlerOptions>

#### `setCookies`

Schema: `{"oneOf": [{"description": "Can be any value - string, number, boolean, array or object.", "nullable": true}, {"type": "string"}]}`

- Cast to: < **Array<object|string>** >

- Member of <CrawlerOptions>

#### `exportStorageState`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `proxyUrl`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `proxyResources`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `proxy`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `userAgent`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `engine`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/enum@0x1c"}]}, {"type": "string"}]}`

- Cast to: < **&quot;auto&quot; | &quot;browser&quot; | &quot;curl&quot; | &quot;cf-browser-rendering&quot;|string** >

- Member of <CrawlerOptions>

#### `injectPageScript`

Schema: `{"type": "string"}`

- Cast to: < **Array<string>** >

- Member of <CrawlerOptions>

#### `injectFrameScript`

Schema: `{"type": "string"}`

- Cast to: < **Array<string>** >

- Member of <CrawlerOptions>

#### `timeout`

Schema: `{"type": "number"}`

- Cast to: < **number** >

- Member of <CrawlerOptions>

- Some validators will be applied on value(s): (v) => v > 0 &amp;&amp; v <= 180

#### `locale`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `referer`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `tokenBudget`

Schema: `{"type": "number"}`

- Cast to: < **number** >

- Member of <CrawlerOptions>

#### `assertStatusCode`

Schema: `{"type": "number"}`

- Cast to: < **number** >

- Member of <CrawlerOptions>

#### `instruction`

Schema: `{"type": "string"}`

- Cast to: < **string** >

- Member of <CrawlerOptions>

#### `jsonSchema`

Schema: `{"nullable": true}`

Can be any value - string, number, boolean, array or object.

- Cast to: < **object** >

- Member of <CrawlerOptions>

#### `robotsTxt`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/PseudoBoolean@0x11"}]}, {"type": "string"}]}`

- Cast to: < **PseudoBoolean|string** >

- Member of <CrawlerOptions>

#### `zeroDataRetention`

Schema: `{"allOf": [{"$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"}]}`

- Cast to: < **PseudoBooleanLoose** >

- Member of <CrawlerOptions>

#### `respondTiming`

Schema: `{"allOf": [{"$ref": "#/components/schemas/enum@0x26"}]}`

- Cast to: < **&quot;html&quot; | &quot;visible-content&quot; | &quot;mutation-idle&quot; | &quot;resource-idle&quot; | &quot;media-idle&quot; | &quot;network-idle&quot;** >

- Member of <CrawlerOptions>

#### `markdownChunking`

Schema: `{"oneOf": [{"allOf": [{"$ref": "#/components/schemas/enum@0x27"}]}, {"type": "string"}]}`

- Cast to: < **&quot;true&quot; | &quot;h1&quot; | &quot;h2&quot; | &quot;h3&quot; | &quot;h4&quot; | &quot;h5&quot; | &quot;structured&quot; | &quot;s1&quot; | &quot;s2&quot; | &quot;s3&quot; | &quot;s4&quot; | &quot;s5&quot;|string** >

- Member of <CrawlerOptions>

#### `maxTokens`

Schema: `{"type": "number"}`

- Cast to: < **number** >

- Member of <CrawlerOptions>

- Some validators will be applied on value(s): (v) => v >= 500

### Request body

```json
{
 "content": {
  "application/json": {
   "schema": {
    "allOf": [
     {
      "$ref": "#/components/schemas/JinaEmbeddingsAuthDTO@0x0b"
     },
     {
      "$ref": "#/components/schemas/CrawlerOptionsHeaderOnly@0x3b"
     },
     {
      "$ref": "#/components/schemas/CrawlerOptions@0x28"
     }
    ]
   }
  },
  "multipart/form-data": {
   "schema": {
    "allOf": [
     {
      "$ref": "#/components/schemas/JinaEmbeddingsAuthDTO@0x0b"
     },
     {
      "$ref": "#/components/schemas/CrawlerOptionsHeaderOnly@0x3b"
     },
     {
      "$ref": "#/components/schemas/CrawlerOptions@0x28"
     }
    ]
   }
  },
  "application/x-www-form-urlencoded": {
   "schema": {
    "type": "object",
    "properties": {
     "url": {
      "type": "string",
      "description": "- Cast to: &lt; **string** &gt;\n\n- Member of &lt;CrawlerOptions&gt;"
     },
     "preloadUrl": {
      "type": "string",
      "description": "- Cast to: &lt; **string** &gt;\n\n- Member of &lt;CrawlerOptions&gt;"
     },
     "noServiceWorker": {
      "allOf": [
       {
        "$ref": "#/components/schemas/PseudoBooleanLoose@0x0c"
       }
      ],
      "description": "- Cast to: &lt; **PseudoBooleanLoose** &gt;\n\n- Member of &lt;CrawlerOptions&gt;"
     },
     "html": {
      "type": "string",
      "description": "- Cast to: &lt; **string** &gt;\n\n- Member of &lt;CrawlerOptions&gt;"
     },
     "base": {
      "allOf": [
       {
        "$ref": "#/components/schemas/enum@0x0d"
       }
      ],
      "default": "final",
      "description": "- Cast to: &lt; **&quot;initial&quot; | &quot;final&quot;** &gt;\n\n- Member of &lt;CrawlerOptions&gt;\n\n- Defaults to: &#39;final&#39;"
     },
     "pdf": {
      "oneOf": [
       {
        "allOf": [
         {
          "$ref": "#/components/schemas/FancyFile@0x0e"
         }
        ]
       },
       {
        "type": "string"
       }
      ],
      "summary": "Base64 encoded PDF.",
      "description": "Base64 encoded PDF.\n\n- Cast to: &lt; **FancyFile|string** &gt;\n\n- Member of &lt;CrawlerOptions&gt;"
     },
     "file": {
      "oneOf": [
       {
        "allOf": [
         {
          "$ref": "#/components/schemas/FancyFile@0x0e"
         }
        ]
       },
       {
        "type": "string"
       }
      ],
      "summary": "Base64 encoded file.",
      "description": "Base64 encoded file.\n\n- Cast to: &lt; **FancyFile|string** &gt;\n\n- Member of &lt;CrawlerOptions&gt;"
     },
     "page": {
      "allOf": [
       {
        "$ref": "#/components/schemas/PageSelection@0x0f"
       }
      ],
      "summary": "Steer which page(s) to return for document files. See PageSelection.",
      "description": "Steer which page(s) to return for document files. See PageSelection.\n\n- Cast to: &lt; **PageSelection** &gt;\n\n- Member of &lt;CrawlerOptions&gt;"
     },
     "respondWith": {
      "oneOf": [
       {
        "allOf": [
         {
          "$ref": "#/components/schemas/enum@0x10"
         }
        ]
 
```

### Responses

- `200` OK — text/plain; charset=utf-8: string; application/json: ReaderEnvelopeWrappedFormattedPageDto; text/event-stream: OutputServerEventStream@0x44
- `400` Bad Request — application/json: ParamValidationError@0x29, DataStreamBrokenError@0x2a
- `401` Unauthorized — application/json: AuthenticationFailedError@0x2b, AuthenticationRequiredError@0x2c
- `402` Payment Required — application/json: TierFeatureConstraintError@0x2d, InsufficientBalanceError@0x2e
- `403` Forbidden — application/json: OperationNotAllowedError@0x2f, AbuseAlleviationError@0x30
- `409` Conflict — application/json: ResourcePolicyDenyError@0x31, BudgetExceededError@0x32
- `413` Payload Too Large — application/json: TargetFileTooLargeError@0x33
- `422` Unprocessable Entity — application/json: SubmittedDataMalformedError@0x34, DownstreamServiceFailureError@0x35, AssertionFailureError@0x36
- `429` Too Many Requests — application/json: RateLimitTriggeredError@0x37
- `451` Unavailable For Legal Reasons — application/json: HarmfulContentError@0x38
- `500` Internal Server Error — application/json: DownstreamServiceError@0x39
- `503` Service Unavailable — application/json: ServiceNodeResourceDrainError@0x3a

## Schemas

### FormattedPageDto@0x43

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `title` | False | string | - Cast to: < **string** >  - Member of <FormattedPageDto> |
| `description` | False | string | - Cast to: < **string** >  - Member of <FormattedPageDto> |
| `url` | True | string | [REQUIRED]  - Cast to: < **string** >  - Member of <FormattedPageDto> |
| `finalUrl` | False | string | - Cast to: < **string** >  - Member of <FormattedPageDto> |
| `content` | False | string | - Cast to: < **string** >  - Member of <FormattedPageDto> |
| `chunks` | False | Array<string>@0x3c | - Cast to: < **Array<string>** >  - Member of <FormattedPageDto> |
| `publishedTime` | False | string | - Cast to: < **string** >  - Member of <FormattedPageDto> |
| `html` | False | string | - Cast to: < **string** >  - Member of <FormattedPageDto> |
| `text` | False | string | - Cast to: < **string** >  - Member of <FormattedPageDto> |
| `screenshotUrl` | False | string | - Cast to: < **string** >  - Member of <FormattedPageDto> |
| `pageshotUrl` | False | string | - Cast to: < **string** >  - Member of <FormattedPageDto> |
| `numPages` | False | number | - Cast to: < **number** >  - Member of <FormattedPageDto> |
| `links` | False | ,, | - Cast to: < **object\|Record<string\|symbol, string>\|Array<string>** >  - Member of <FormattedPageDto> |
| `images` | False | ,, | - Cast to: < **object\|Record<string\|symbol, string>\|Array<string>** >  - Member of <FormattedPageDto> |
| `warning` | False | string | - Cast to: < **string** >  - Member of <FormattedPageDto> |
| `metadata` | False | , | - Cast to: < **object\|Record<string\|symbol, string>** >  - Member of <FormattedPageDto> |
| `external` | False | , | - Cast to: < **object\|Record<string\|symbol, Record<string\|symbol, Record<string\|symbol, string\|object>@0x08\|object>@0x09\|object>** >  - Member of <FormattedPageDto> |
| `httpStatus` | False | number | - Cast to: < **number** >  - Member of <FormattedPageDto> |
| `httpStatusText` | False | string | - Cast to: < **string** >  - Member of <FormattedPageDto> |
| `storageState` | False |  | Can be any value - string, number, boolean, array or object.  - Cast to: < **object** >  - Member of <FormattedPageDto> |

### RateLimitTriggeredError@0x37

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `retryAfter` | False | number | Retry after seconds  - Cast to: < **number** >  - Member of <RateLimitTriggeredError> |
| `retryAfterDate` | False | string | Retry after date  - Cast to: < **Date** >  - Member of <RateLimitTriggeredError> |
| `code` | True | number | [REQUIRED]  Expect HTTP response codes  - Cast to: < **number** >  - Member of <RateLimitTriggeredError>  - Defaults to: 429 |
| `status` | True | number | [REQUIRED]  Application status code for the error in extension to HTTP status codes  - Cast to: < **number** >  - Member of <RateLimitTriggeredError>  - Defaults to: 42903 |
| `message` | True | string | [REQUIRED]  - Cast to: < **string** >  - Member of <RateLimitTriggeredError> |
| `readableMessage` | False | string | - Cast to: < **string** >  - Member of <RateLimitTriggeredError> |

### InsufficientBalanceError@0x2e

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `code` | True | number | [REQUIRED]  Expect HTTP response codes  - Cast to: < **number** >  - Member of <InsufficientBalanceError>  - Defaults to: 402 |
| `status` | True | number | [REQUIRED]  Application status code for the error in extension to HTTP status codes  - Cast to: < **number** >  - Member of <InsufficientBalanceError>  - Defaults to: 40203 |
| `message` | True | string | [REQUIRED]  - Cast to: < **string** >  - Member of <InsufficientBalanceError> |
| `readableMessage` | False | string | - Cast to: < **string** >  - Member of <InsufficientBalanceError> |

### TierFeatureConstraintError@0x2d

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `code` | True | number | [REQUIRED]  Expect HTTP response codes  - Cast to: < **number** >  - Member of <TierFeatureConstraintError>  - Defaults to: 402 |
| `status` | True | number | [REQUIRED]  Application status code for the error in extension to HTTP status codes  - Cast to: < **number** >  - Member of <TierFeatureConstraintError>  - Defaults to: 40202 |
| `message` | True | string | [REQUIRED]  - Cast to: < **string** >  - Member of <TierFeatureConstraintError> |
| `readableMessage` | False | string | - Cast to: < **string** >  - Member of <TierFeatureConstraintError> |

### AuthenticationRequiredError@0x2c

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `code` | True | number | [REQUIRED]  Expect HTTP response codes  - Cast to: < **number** >  - Member of <AuthenticationRequiredError>  - Defaults to: 401 |
| `status` | True | number | [REQUIRED]  Application status code for the error in extension to HTTP status codes  - Cast to: < **number** >  - Member of <AuthenticationRequiredError>  - Defaults to: 40103 |
| `message` | True | string | [REQUIRED]  - Cast to: < **string** >  - Member of <AuthenticationRequiredError> |
| `readableMessage` | False | string | - Cast to: < **string** >  - Member of <AuthenticationRequiredError> |

### AuthenticationFailedError@0x2b

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `code` | True | number | [REQUIRED]  Expect HTTP response codes  - Cast to: < **number** >  - Member of <AuthenticationFailedError>  - Defaults to: 401 |
| `status` | True | number | [REQUIRED]  Application status code for the error in extension to HTTP status codes  - Cast to: < **number** >  - Member of <AuthenticationFailedError>  - Defaults to: 40102 |
| `message` | True | string | [REQUIRED]  - Cast to: < **string** >  - Member of <AuthenticationFailedError> |
| `readableMessage` | False | string | - Cast to: < **string** >  - Member of <AuthenticationFailedError> |

### ParamValidationError@0x29

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `code` | True | number | [REQUIRED]  Expect HTTP response codes  - Cast to: < **number** >  - Member of <ParamValidationError>  - Defaults to: 400 |
| `status` | True | number | [REQUIRED]  Application status code for the error in extension to HTTP status codes  - Cast to: < **number** >  - Member of <ParamValidationError>  - Defaults to: 40001 |
| `message` | True | string | [REQUIRED]  - Cast to: < **string** >  - Member of <ParamValidationError> |
| `readableMessage` | False | string | - Cast to: < **string** >  - Member of <ParamValidationError> |

### AssertionFailureError@0x36

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `code` | True | number | [REQUIRED]  Expect HTTP response codes  - Cast to: < **number** >  - Member of <AssertionFailureError>  - Defaults to: 422 |
| `status` | True | number | [REQUIRED]  Application status code for the error in extension to HTTP status codes  - Cast to: < **number** >  - Member of <AssertionFailureError>  - Defaults to: 42206 |
| `message` | True | string | [REQUIRED]  - Cast to: < **string** >  - Member of <AssertionFailureError> |
| `readableMessage` | False | string | - Cast to: < **string** >  - Member of <AssertionFailureError> |

### BudgetExceededError@0x32

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `code` | True | number | [REQUIRED]  Expect HTTP response codes  - Cast to: < **number** >  - Member of <BudgetExceededError>  - Defaults to: 409 |
| `status` | True | number | [REQUIRED]  Application status code for the error in extension to HTTP status codes  - Cast to: < **number** >  - Member of <BudgetExceededError>  - Defaults to: 40904 |
| `message` | True | string | [REQUIRED]  - Cast to: < **string** >  - Member of <BudgetExceededError> |
| `readableMessage` | False | string | - Cast to: < **string** >  - Member of <BudgetExceededError> |

### ServiceNodeResourceDrainError@0x3a

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `code` | True | number | [REQUIRED]  Expect HTTP response codes  - Cast to: < **number** >  - Member of <ServiceNodeResourceDrainError>  - Defaults to: 503 |
| `status` | True | number | [REQUIRED]  Application status code for the error in extension to HTTP status codes  - Cast to: < **number** >  - Member of <ServiceNodeResourceDrainError>  - Defaults to: 50303 |
| `message` | True | string | [REQUIRED]  - Cast to: < **string** >  - Member of <ServiceNodeResourceDrainError> |
| `readableMessage` | False | string | - Cast to: < **string** >  - Member of <ServiceNodeResourceDrainError> |

### DownstreamServiceFailureError@0x35

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `code` | True | number | [REQUIRED]  Expect HTTP response codes  - Cast to: < **number** >  - Member of <DownstreamServiceFailureError>  - Defaults to: 422 |
| `status` | True | number | [REQUIRED]  Application status code for the error in extension to HTTP status codes  - Cast to: < **number** >  - Member of <DownstreamServiceFailureError>  - Defaults to: 42205 |
| `message` | True | string | [REQUIRED]  - Cast to: < **string** >  - Member of <DownstreamServiceFailureError> |
| `readableMessage` | False | string | - Cast to: < **string** >  - Member of <DownstreamServiceFailureError> |

### DownstreamServiceError@0x39

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `code` | True | number | [REQUIRED]  Expect HTTP response codes  - Cast to: < **number** >  - Member of <DownstreamServiceError>  - Defaults to: 500 |
| `status` | True | number | [REQUIRED]  Application status code for the error in extension to HTTP status codes  - Cast to: < **number** >  - Member of <DownstreamServiceError>  - Defaults to: 50002 |
| `message` | True | string | [REQUIRED]  - Cast to: < **string** >  - Member of <DownstreamServiceError> |
| `readableMessage` | False | string | - Cast to: < **string** >  - Member of <DownstreamServiceError> |

### ResourcePolicyDenyError@0x31

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `code` | True | number | [REQUIRED]  Expect HTTP response codes  - Cast to: < **number** >  - Member of <ResourcePolicyDenyError>  - Defaults to: 409 |
| `status` | True | number | [REQUIRED]  Application status code for the error in extension to HTTP status codes  - Cast to: < **number** >  - Member of <ResourcePolicyDenyError>  - Defaults to: 40902 |
| `message` | True | string | [REQUIRED]  - Cast to: < **string** >  - Member of <ResourcePolicyDenyError> |
| `readableMessage` | False | string | - Cast to: < **string** >  - Member of <ResourcePolicyDenyError> |

### HarmfulContentError@0x38

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `code` | True | number | [REQUIRED]  Expect HTTP response codes  - Cast to: < **number** >  - Member of <HarmfulContentError>  - Defaults to: 451 |
| `status` | True | number | [REQUIRED]  Application status code for the error in extension to HTTP status codes  - Cast to: < **number** >  - Member of <HarmfulContentError>  - Defaults to: 45101 |
| `message` | True | string | [REQUIRED]  - Cast to: < **string** >  - Member of <HarmfulContentError> |
| `readableMessage` | False | string | - Cast to: < **string** >  - Member of <HarmfulContentError> |

### TargetFileTooLargeError@0x33

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `code` | True | number | [REQUIRED]  Expect HTTP response codes  - Cast to: < **number** >  - Member of <TargetFileTooLargeError>  - Defaults to: 413 |
| `status` | True | number | [REQUIRED]  Application status code for the error in extension to HTTP status codes  - Cast to: < **number** >  - Member of <TargetFileTooLargeError>  - Defaults to: 41302 |
| `message` | True | string | [REQUIRED]  - Cast to: < **string** >  - Member of <TargetFileTooLargeError> |
| `readableMessage` | False | string | - Cast to: < **string** >  - Member of <TargetFileTooLargeError> |

### OperationNotAllowedError@0x2f

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `code` | True | number | [REQUIRED]  Expect HTTP response codes  - Cast to: < **number** >  - Member of <OperationNotAllowedError>  - Defaults to: 403 |
| `status` | True | number | [REQUIRED]  Application status code for the error in extension to HTTP status codes  - Cast to: < **number** >  - Member of <OperationNotAllowedError>  - Defaults to: 40301 |
| `message` | True | string | [REQUIRED]  - Cast to: < **string** >  - Member of <OperationNotAllowedError> |
| `readableMessage` | False | string | - Cast to: < **string** >  - Member of <OperationNotAllowedError> |

### AbuseAlleviationError@0x30

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `code` | True | number | [REQUIRED]  Expect HTTP response codes  - Cast to: < **number** >  - Member of <AbuseAlleviationError>  - Defaults to: 403 |
| `status` | True | number | [REQUIRED]  Application status code for the error in extension to HTTP status codes  - Cast to: < **number** >  - Member of <AbuseAlleviationError>  - Defaults to: 40305 |
| `message` | True | string | [REQUIRED]  - Cast to: < **string** >  - Member of <AbuseAlleviationError> |
| `readableMessage` | False | string | - Cast to: < **string** >  - Member of <AbuseAlleviationError> |

### OutputServerEventStream@0x44

Binary data (stream)


### CrawlerOptions@0x28

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `url` | False | string | - Cast to: < **string** >  - Member of <CrawlerOptions> |
| `preloadUrl` | False | string | - Cast to: < **string** >  - Member of <CrawlerOptions> |
| `noServiceWorker` | False | PseudoBooleanLoose@0x0c | - Cast to: < **PseudoBooleanLoose** >  - Member of <CrawlerOptions> |
| `html` | False | string | - Cast to: < **string** >  - Member of <CrawlerOptions> |
| `base` | False | enum@0x0d | - Cast to: < **&quot;initial&quot; \| &quot;final&quot;** >  - Member of <CrawlerOptions>  - Defaults to: &#39;final&#39; |
| `pdf` | False | , | Base64 encoded PDF.  - Cast to: < **FancyFile\|string** >  - Member of <CrawlerOptions> |
| `file` | False | , | Base64 encoded file.  - Cast to: < **FancyFile\|string** >  - Member of <CrawlerOptions> |
| `page` | False | PageSelection@0x0f | Steer which page(s) to return for document files. See PageSelection.  - Cast to: < **PageSelection** >  - Member of <CrawlerOptions> |
| `respondWith` | False | , | - Cast to: < **&quot;content&quot; \| &quot;markdown&quot; \| &quot;html&quot; \| &quot;text&quot; \| &quot;pageshot&quot; \| &quot;screenshot&quot; \| &quot;vlm&quot; \| &quot;readerlm-v2&quot; \| &quot;frontmatter&quot; \| &quot;readability&quot; \| &quot;...\|string** >  - Member of <CrawlerOptions>  - Defaults to: &#39;content&#39; |
| `withGeneratedAlt` | False | PseudoBoolean@0x11 | - Cast to: < **PseudoBoolean** >  - Member of <CrawlerOptions> |
| `retainImages` | False | enum@0x12 | - Cast to: < **&quot;none&quot; \| &quot;all&quot; \| &quot;alt&quot; \| &quot;all_p&quot; \| &quot;alt_p&quot;** >  - Member of <CrawlerOptions>  - Defaults to: &#39;all&#39; |
| `retainMedia` | False | enum@0x13 | - Cast to: < **&quot;none&quot; \| &quot;text&quot; \| &quot;link&quot; \| &quot;image&quot; \| &quot;html&quot;** >  - Member of <CrawlerOptions>  - Defaults to: &#39;link&#39; |
| `preset` | False | enum@0x14 | - Cast to: < **&quot;reader&quot; \| &quot;index&quot; \| &quot;research&quot; \| &quot;agent&quot; \| &quot;spider&quot; \| &quot;ocr&quot; \| &quot;ocr+&quot; \| &quot;ocr++&quot; \| &quot;pdf&quot; \| &quot;pdf+&quot; \| &quot;pdf++&quot;** >  - Member of <CrawlerOptions> |
| `retainLinks` | False | enum@0x15 | - Cast to: < **&quot;none&quot; \| &quot;all&quot; \| &quot;text&quot; \| &quot;gpt-oss&quot;** >  - Member of <CrawlerOptions>  - Defaults to: &#39;all&#39; |
| `withLinksSummary` | False | , | - Cast to: < **PseudoBoolean\|string** >  - Member of <CrawlerOptions> |
| `withImagesSummary` | False | PseudoBooleanLoose@0x0c | - Cast to: < **PseudoBooleanLoose** >  - Member of <CrawlerOptions> |
| `noCache` | False | PseudoBooleanLoose@0x0c | - Cast to: < **PseudoBooleanLoose** >  - Member of <CrawlerOptions> |
| `removeOverlay` | False | PseudoBooleanLoose@0x0c | - Cast to: < **PseudoBooleanLoose** >  - Member of <CrawlerOptions> |
| `detachInvisibles` | False | PseudoBooleanLoose@0x0c | - Cast to: < **PseudoBooleanLoose** >  - Member of <CrawlerOptions> |
| `noGfm` | False | , | - Cast to: < **PseudoBoolean\|string** >  - Member of <CrawlerOptions> |
| `cacheTolerance` | False | number | - Cast to: < **number** >  - Member of <CrawlerOptions> |
| `targetSelector` | False | array | - Cast to: < **Array<string>** >  - Member of <CrawlerOptions> |
| `waitForSelector` | False | array | - Cast to: < **Array<string>** >  - Member of <CrawlerOptions> |
| `removeSelector` | False | array | - Cast to: < **Array<string>** >  - Member of <CrawlerOptions> |
| `keepImgDataUrl` | False | PseudoBooleanLoose@0x0c | - Cast to: < **PseudoBooleanLoose** >  - Member of <CrawlerOptions> |
| `withIframe` | False | , | - Cast to: < **PseudoBoolean\|string** >  - Member of <CrawlerOptions> |
| `withShadowDom` | False | PseudoBooleanLoose@0x0c | - Cast to: < **PseudoBooleanLoose** >  - Member of <CrawlerOptions> |
| `skipCertVerification` | False | PseudoBooleanLoose@0x0c | - Cast to: < **PseudoBooleanLoose** >  - Member of <CrawlerOptions> |
| `webBotAuth` | False | , | - Cast to: < **PseudoBoolean\|&quot;authority&quot; \| &quot;target-uri&quot;** >  - Member of <CrawlerOptions> |
| `setCookies` | False | array | - Cast to: < **Array<object\|string>** >  - Member of <CrawlerOptions> |
| `storageState` | False | StorageState@0x1b | - Cast to: < **StorageState** >  - Member of <CrawlerOptions> |
| `exportStorageState` | False | PseudoBooleanLoose@0x0c | - Cast to: < **PseudoBooleanLoose** >  - Member of <CrawlerOptions> |
| `proxyUrl` | False | string | - Cast to: < **string** >  - Member of <CrawlerOptions> |
| `proxyResources` | False | PseudoBooleanLoose@0x0c | - Cast to: < **PseudoBooleanLoose** >  - Member of <CrawlerOptions> |
| `proxy` | False | string | - Cast to: < **string** >  - Member of <CrawlerOptions> |
| `userAgent` | False | string | - Cast to: < **string** >  - Member of <CrawlerOptions> |
| `engine` | False | , | - Cast to: < **&quot;auto&quot; \| &quot;browser&quot; \| &quot;curl&quot; \| &quot;cf-browser-rendering&quot;\|string** >  - Member of <CrawlerOptions> |
| `injectPageScript` | False | array | - Cast to: < **Array<string>** >  - Member of <CrawlerOptions> |
| `injectFrameScript` | False | array | - Cast to: < **Array<string>** >  - Member of <CrawlerOptions> |
| `timeout` | False | number | - Cast to: < **number** >  - Member of <CrawlerOptions>  - Some validators will be applied on value(s): (v) => v > 0 &amp;&amp; v <= 180 |
| `locale` | False | string | - Cast to: < **string** >  - Member of <CrawlerOptions> |
| `referer` | False | string | - Cast to: < **string** >  - Member of <CrawlerOptions> |
| `tokenBudget` | False | number | - Cast to: < **number** >  - Member of <CrawlerOptions> |
| `assertStatusCode` | False | number | - Cast to: < **number** >  - Member of <CrawlerOptions> |
| `viewport` | False | Viewport@0x1d | - Cast to: < **Viewport** >  - Member of <CrawlerOptions> |
| `instruction` | False | string | - Cast to: < **string** >  - Member of <CrawlerOptions> |
| `jsonSchema` | False |  | Can be any value - string, number, boolean, array or object.  - Cast to: < **object** >  - Member of <CrawlerOptions> |
| `robotsTxt` | False | , | - Cast to: < **PseudoBoolean\|string** >  - Member of <CrawlerOptions> |
| `zeroDataRetention` | False | PseudoBooleanLoose@0x0c | - Cast to: < **PseudoBooleanLoose** >  - Member of <CrawlerOptions> |
| `markdown` | False | TurnDownTweakableOptions@0x24 | - Cast to: < **TurnDownTweakableOptions** >  - Member of <CrawlerOptions> |
| `ocr` | False | OCRPreferences@0x25 | - Cast to: < **OCRPreferences** >  - Member of <CrawlerOptions> |
| `respondTiming` | False | enum@0x26 | - Cast to: < **&quot;html&quot; \| &quot;visible-content&quot; \| &quot;mutation-idle&quot; \| &quot;resource-idle&quot; \| &quot;media-idle&quot; \| &quot;network-idle&quot;** >  - Member of <CrawlerOptions> |
| `markdownChunking` | False | , | - Cast to: < **&quot;true&quot; \| &quot;h1&quot; \| &quot;h2&quot; \| &quot;h3&quot; \| &quot;h4&quot; \| &quot;h5&quot; \| &quot;structured&quot; \| &quot;s1&quot; \| &quot;s2&quot; \| &quot;s3&quot; \| &quot;s4&quot; \| &quot;s5&quot;\|string** >  - Member of <CrawlerOptions> |
| `maxTokens` | False | number | - Cast to: < **number** >  - Member of <CrawlerOptions>  - Some validators will be applied on value(s): (v) => v >= 500 |
| `customHeader` | False | object | - Cast to: < **Record<string, string>** >  - Member of <CrawlerOptions> |

