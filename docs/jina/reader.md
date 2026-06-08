# Jina Reader API

Source: https://r.jina.ai/docs
OpenAPI source: https://r.jina.ai/openapi.json

This Markdown file is generated from the OpenAPI document and keeps endpoint, parameter, response, and schema details available locally.

## API Info

- Title: Jina Reader API
- Version: N/A
- Description: Jina Reader API openapi document

## Servers

- `https://r.jina.ai/`

## Endpoints

### `/`

#### `GET /`

Summary: getIndex

| Name | In | Required | Type | Description |
| --- | --- | --- | --- | --- |
| `url` | query | False | string |  |
| `html` | query | False | string |  |
| `base` | query | False |  |  |
| `pdf` | query | False | oneOf=, string |  |
| `file` | query | False | oneOf=, string |  |
| `page` | query | False | number |  |
| `respondWith` | query | False | oneOf=, string |  |
| `withGeneratedAlt` | query | False |  |  |
| `retainImages` | query | False |  |  |
| `retainMedia` | query | False |  |  |
| `preset` | query | False |  |  |
| `retainLinks` | query | False |  |  |
| `withLinksSummary` | query | False | oneOf=, string |  |
| `withImagesSummary` | query | False |  |  |
| `noCache` | query | False |  |  |
| `removeOverlay` | query | False |  |  |
| `detachInvisibles` | query | False |  |  |
| `noGfm` | query | False | oneOf=, string |  |
| `cacheTolerance` | query | False | number |  |
| `targetSelector` | query | False | string |  |
| `waitForSelector` | query | False | string |  |
| `removeSelector` | query | False | string |  |
| `keepImgDataUrl` | query | False |  |  |
| `withIframe` | query | False | oneOf=, string |  |
| `withShadowDom` | query | False |  |  |
| `setCookies` | query | False | oneOf=, string |  |
| `proxyUrl` | query | False | string |  |
| `proxy` | query | False | string |  |
| `userAgent` | query | False | string |  |
| `engine` | query | False | oneOf=, string |  |
| `injectPageScript` | query | False | string |  |
| `injectFrameScript` | query | False | string |  |
| `timeout` | query | False | number |  |
| `locale` | query | False | string |  |
| `referer` | query | False | string |  |
| `tokenBudget` | query | False | number |  |
| `assertStatusCode` | query | False | number |  |
| `instruction` | query | False | string |  |
| `jsonSchema` | query | False |  |  |
| `robotsTxt` | query | False | string |  |
| `doNotTrack` | query | False |  |  |
| `respondTiming` | query | False |  |  |
| `markdownChunking` | query | False | oneOf=, string |  |
| `maxTokens` | query | False | number |  |
| `Authorization` | header | False | anyOf=string; format=token | Jina Token for authentication.<br><br>- Member of &lt;JinaEmbeddingsAuthDTO&gt;<br><br>- Authorization: Bearer {YOUR_JINA_TOKEN} |
| `Accept` | header | False | string | Specifies your preference for the response format.<br><br>Supported formats: <br>- text/event-stream<br>- application/json or text/json<br>- text/plain |
| `X-Cache-Tolerance` | header | False | string | Sets internal cache tolerance in seconds if this header is specified with a integer. |
| `X-No-Cache` | header | False | string | Ignores internal cache if this header is specified with a value.<br><br>Equivalent to X-Cache-Tolerance: 0 |
| `X-Respond-With` | header | False | string | Specifies the (non-default) form of the crawled data you prefer.<br><br>Supported formats: <br>- markdown<br>- html<br>- text<br>- pageshot<br>- screenshot<br>- content<br>- frontmatter<br>- any combination of the above<br>- readerlm-v2<br>- vlm<br><br>Default: content |
| `X-Wait-For-Selector` | header | False | string | Specifies a CSS selector to wait for the appearance of such an element before returning.<br><br>Example: `X-Wait-For-Selector: .content-block` |
| `X-Target-Selector` | header | False | string | Specifies a CSS selector for return target instead of the full html.<br><br>Implies `X-Wait-For-Selector: (same selector)` |
| `X-Remove-Selector` | header | False | string | Specifies a CSS selector to remove elements from the full html.<br><br>Example `X-Remove-Selector: nav` |
| `X-Keep-Img-Data-Url` | header | False | string | Keep data-url as it instead of transforming them to object-url. (Only applicable when targeting markdown format)<br><br>Example `X-Keep-Img-Data-Url: true` |
| `X-Proxy-Url` | header | False | string | Specifies your custom proxy if you prefer to use one.<br><br>Supported protocols: <br>- http<br>- https<br>- socks4<br>- socks5<br><br>For authentication, https://user:pass@host:port |
| `X-Proxy` | header | False | string | Use a proxy server provided by us.<br><br>Optionally specify two-letter country code. |
| `X-Robots-Txt` | header | False | string | Load and conform to the respective robot.txt on the target origin.<br><br>Optionally specify a bot UA to check against. |
| `DNT` | header | False | string | When set to 1, prevent the result of this request to be cached in the system. |
| `X-Set-Cookie` | header | False | string | Sets cookie(s) to the headless browser for your request. <br><br>Syntax is the same with standard Set-Cookie |
| `X-With-Generated-Alt` | header | False | string | Enable automatic alt-text generating for images without an meaningful alt-text.<br><br>Note: Does not work when `X-Respond-With` is specified |
| `X-With-Images-Summary` | header | False | string | Enable dedicated summary section for images on the page. |
| `X-With-links-Summary` | header | False | string | Enable dedicated summary section for hyper links on the page. |
| `X-Retain-Links` | header | False | string | Link retention modes.<br><br>Supported modes: <br>- all: all links<br>- none: no links<br>- text: only link text<br>- gpt-oss: gpt-oss link citation format `【{id}†.*】` |
| `X-Retain-Images` | header | False | string | Image retention modes.<br><br>Supported modes: <br>- all: all images<br>- none: no images<br>- alt: only alt text<br>- all_p: all images and with generated alt text<br>- alt_p: only alt text and with generated alt |
| `X-Retain-Media` | header | False | string | Media retention modes for video, audio, and embedded video iframes.<br><br>Supported modes: <br>- none: no media<br>- text: plain label, e.g. `Video 1`<br>- link: markdown link, e.g. `[Video 1](url)` (default)<br>- image: markdown image syntax, e.g. `![Video 1](url)`<br>- html: original HTML with irrelevant attributes (class, id, style, data-*, aria-*) stripped |
| `X-Preset` | header | False | string | Apply a preset configuration for common scenarios.<br><br>Supported presets:<br>- reader: optimized for display to human users<br>- index: optimized for semantic indexing<br>- research: optimized for academic/research AI agents<br>- agent: optimized for day-to-day AI agents<br>- spider: optimized for recursive site crawling<br><br>Preset values are applied only to options not explicitly set by the caller. |
| `X-With-Iframe` | header | False | string | Enable filling iframe contents into main. (violates standards) |
| `X-With-Shadow-Dom` | header | False | string | Enable filling shadow dom contents into main. (violates standards) |
| `X-User-Agent` | header | False | string | Override User-Agent. |
| `X-Timeout` | header | False | string | Specify timeout in seconds. Max 180. |
| `X-Locale` | header | False | string | Specify browser locale for the page. |
| `X-Referer` | header | False | string | Specify referer for the page. |
| `X-Token-Budget` | header | False | string | Specify a budget in tokens.<br><br>If the resulting token cost exceeds the budget, the request is rejected.<br><br>Note this parameter is ignored for the search endpoint. |
| `X-Max-Tokens` | header | False | string | Trim the response content at a maximum number of tokens. |
| `X-Assert-Status-Code` | header | False | string | Assert the HTTP status code of the crawled page. If the actual status code does not match the asserted one, the request is rejected with 422 Unprocessable Entity. |
| `X-Respond-Timing` | header | False | string | Explicitly specify the respond timing. One of the following:<br><br>- html: directly return unrendered HTML<br>- visible-content: return immediately when any content becomes available<br>- mutation-idle: wait for DOM mutations to settle and remain unchanged for at least 0.2s<br>- resource-idle: wait for no additional resources that would affect page logic and content has SUCCEEDED loading in 0.5s<br>- media-idle: wait for no additional resources, including media resources, has SUCCEEDED loading in 0.5s<br>- network-idle: wait for full load of webpage, also known as networkidle0. |
| `X-Engine` | header | False | string | Specify the engine to use for crawling.<br><br>Supported: browser, direct, cf-browser-rendering |
| `X-Base` | header | False | string | Select base modes of relative URLs.<br><br>Supported: initial, final |
| `X-Remove-Overlay` | header | False | string | Specify whether to remove overlay elements from the page. |
| `X-Detach-Invisibles` | header | False | string | Temporarily detach elements with computed `display:none` before snapshotting, then restore them.<br><br>Requires the browser engine and disables caching. |
| `X-Markdown-Chunking` | header | False | string | Opt-in markdown chunking.<br><br>Supported values: <br>- true<br>- h1<br>- h2<br>- h3<br>- h4<br>- h5<br>- structured<br>- s1<br>- s2<br>- s3<br>- s4<br>- s5<br><br>Note if you are expecting text return, the chunking is done by injecting character \u001D |
| `X-Md-Heading-Style` | header | False | string | Heading style of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: setext, atx |
| `X-Md-Hr` | header | False | string | Hr text of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options). |
| `X-Md-Bullet-List-Marker` | header | False | string | Bullet list marker of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: -, +, * |
| `X-Md-Em-Delimiter` | header | False | string | Em delimiter of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: _, * |
| `X-Md-Strong-Delimiter` | header | False | string | Strong delimiter of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: **, __ |
| `X-Md-Link-Style` | header | False | string | Link style of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: inlined, referenced, discarded |
| `X-Md-Link-Reference-Style` | header | False | string | Link reference style of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: full, collapsed, shortcut, discarded |
| `X-Page` | header | False | string | Steer which page to return for uploaded files (PDF, DOC, XLS, PPT, etc.).<br><br>1-indexed; ignored when no file/PDF is uploaded. |

Responses:

| Status | Description | Content Types |
| --- | --- | --- |
| `200` | OK | application/json |

#### `POST /`

Summary: crawlByPostingToIndex

| Name | In | Required | Type | Description |
| --- | --- | --- | --- | --- |
| `url` | query | False | string |  |
| `html` | query | False | string |  |
| `base` | query | False |  |  |
| `pdf` | query | False | oneOf=, string |  |
| `file` | query | False | oneOf=, string |  |
| `page` | query | False | number |  |
| `respondWith` | query | False | oneOf=, string |  |
| `withGeneratedAlt` | query | False |  |  |
| `retainImages` | query | False |  |  |
| `retainMedia` | query | False |  |  |
| `preset` | query | False |  |  |
| `retainLinks` | query | False |  |  |
| `withLinksSummary` | query | False | oneOf=, string |  |
| `withImagesSummary` | query | False |  |  |
| `noCache` | query | False |  |  |
| `removeOverlay` | query | False |  |  |
| `detachInvisibles` | query | False |  |  |
| `noGfm` | query | False | oneOf=, string |  |
| `cacheTolerance` | query | False | number |  |
| `targetSelector` | query | False | string |  |
| `waitForSelector` | query | False | string |  |
| `removeSelector` | query | False | string |  |
| `keepImgDataUrl` | query | False |  |  |
| `withIframe` | query | False | oneOf=, string |  |
| `withShadowDom` | query | False |  |  |
| `setCookies` | query | False | oneOf=, string |  |
| `proxyUrl` | query | False | string |  |
| `proxy` | query | False | string |  |
| `userAgent` | query | False | string |  |
| `engine` | query | False | oneOf=, string |  |
| `injectPageScript` | query | False | string |  |
| `injectFrameScript` | query | False | string |  |
| `timeout` | query | False | number |  |
| `locale` | query | False | string |  |
| `referer` | query | False | string |  |
| `tokenBudget` | query | False | number |  |
| `assertStatusCode` | query | False | number |  |
| `instruction` | query | False | string |  |
| `jsonSchema` | query | False |  |  |
| `robotsTxt` | query | False | string |  |
| `doNotTrack` | query | False |  |  |
| `respondTiming` | query | False |  |  |
| `markdownChunking` | query | False | oneOf=, string |  |
| `maxTokens` | query | False | number |  |
| `Authorization` | header | False | anyOf=string; format=token | Jina Token for authentication.<br><br>- Member of &lt;JinaEmbeddingsAuthDTO&gt;<br><br>- Authorization: Bearer {YOUR_JINA_TOKEN} |
| `Accept` | header | False | string | Specifies your preference for the response format.<br><br>Supported formats: <br>- text/event-stream<br>- application/json or text/json<br>- text/plain |
| `X-Cache-Tolerance` | header | False | string | Sets internal cache tolerance in seconds if this header is specified with a integer. |
| `X-No-Cache` | header | False | string | Ignores internal cache if this header is specified with a value.<br><br>Equivalent to X-Cache-Tolerance: 0 |
| `X-Respond-With` | header | False | string | Specifies the (non-default) form of the crawled data you prefer.<br><br>Supported formats: <br>- markdown<br>- html<br>- text<br>- pageshot<br>- screenshot<br>- content<br>- frontmatter<br>- any combination of the above<br>- readerlm-v2<br>- vlm<br><br>Default: content |
| `X-Wait-For-Selector` | header | False | string | Specifies a CSS selector to wait for the appearance of such an element before returning.<br><br>Example: `X-Wait-For-Selector: .content-block` |
| `X-Target-Selector` | header | False | string | Specifies a CSS selector for return target instead of the full html.<br><br>Implies `X-Wait-For-Selector: (same selector)` |
| `X-Remove-Selector` | header | False | string | Specifies a CSS selector to remove elements from the full html.<br><br>Example `X-Remove-Selector: nav` |
| `X-Keep-Img-Data-Url` | header | False | string | Keep data-url as it instead of transforming them to object-url. (Only applicable when targeting markdown format)<br><br>Example `X-Keep-Img-Data-Url: true` |
| `X-Proxy-Url` | header | False | string | Specifies your custom proxy if you prefer to use one.<br><br>Supported protocols: <br>- http<br>- https<br>- socks4<br>- socks5<br><br>For authentication, https://user:pass@host:port |
| `X-Proxy` | header | False | string | Use a proxy server provided by us.<br><br>Optionally specify two-letter country code. |
| `X-Robots-Txt` | header | False | string | Load and conform to the respective robot.txt on the target origin.<br><br>Optionally specify a bot UA to check against. |
| `DNT` | header | False | string | When set to 1, prevent the result of this request to be cached in the system. |
| `X-Set-Cookie` | header | False | string | Sets cookie(s) to the headless browser for your request. <br><br>Syntax is the same with standard Set-Cookie |
| `X-With-Generated-Alt` | header | False | string | Enable automatic alt-text generating for images without an meaningful alt-text.<br><br>Note: Does not work when `X-Respond-With` is specified |
| `X-With-Images-Summary` | header | False | string | Enable dedicated summary section for images on the page. |
| `X-With-links-Summary` | header | False | string | Enable dedicated summary section for hyper links on the page. |
| `X-Retain-Links` | header | False | string | Link retention modes.<br><br>Supported modes: <br>- all: all links<br>- none: no links<br>- text: only link text<br>- gpt-oss: gpt-oss link citation format `【{id}†.*】` |
| `X-Retain-Images` | header | False | string | Image retention modes.<br><br>Supported modes: <br>- all: all images<br>- none: no images<br>- alt: only alt text<br>- all_p: all images and with generated alt text<br>- alt_p: only alt text and with generated alt |
| `X-Retain-Media` | header | False | string | Media retention modes for video, audio, and embedded video iframes.<br><br>Supported modes: <br>- none: no media<br>- text: plain label, e.g. `Video 1`<br>- link: markdown link, e.g. `[Video 1](url)` (default)<br>- image: markdown image syntax, e.g. `![Video 1](url)`<br>- html: original HTML with irrelevant attributes (class, id, style, data-*, aria-*) stripped |
| `X-Preset` | header | False | string | Apply a preset configuration for common scenarios.<br><br>Supported presets:<br>- reader: optimized for display to human users<br>- index: optimized for semantic indexing<br>- research: optimized for academic/research AI agents<br>- agent: optimized for day-to-day AI agents<br>- spider: optimized for recursive site crawling<br><br>Preset values are applied only to options not explicitly set by the caller. |
| `X-With-Iframe` | header | False | string | Enable filling iframe contents into main. (violates standards) |
| `X-With-Shadow-Dom` | header | False | string | Enable filling shadow dom contents into main. (violates standards) |
| `X-User-Agent` | header | False | string | Override User-Agent. |
| `X-Timeout` | header | False | string | Specify timeout in seconds. Max 180. |
| `X-Locale` | header | False | string | Specify browser locale for the page. |
| `X-Referer` | header | False | string | Specify referer for the page. |
| `X-Token-Budget` | header | False | string | Specify a budget in tokens.<br><br>If the resulting token cost exceeds the budget, the request is rejected.<br><br>Note this parameter is ignored for the search endpoint. |
| `X-Max-Tokens` | header | False | string | Trim the response content at a maximum number of tokens. |
| `X-Assert-Status-Code` | header | False | string | Assert the HTTP status code of the crawled page. If the actual status code does not match the asserted one, the request is rejected with 422 Unprocessable Entity. |
| `X-Respond-Timing` | header | False | string | Explicitly specify the respond timing. One of the following:<br><br>- html: directly return unrendered HTML<br>- visible-content: return immediately when any content becomes available<br>- mutation-idle: wait for DOM mutations to settle and remain unchanged for at least 0.2s<br>- resource-idle: wait for no additional resources that would affect page logic and content has SUCCEEDED loading in 0.5s<br>- media-idle: wait for no additional resources, including media resources, has SUCCEEDED loading in 0.5s<br>- network-idle: wait for full load of webpage, also known as networkidle0. |
| `X-Engine` | header | False | string | Specify the engine to use for crawling.<br><br>Supported: browser, direct, cf-browser-rendering |
| `X-Base` | header | False | string | Select base modes of relative URLs.<br><br>Supported: initial, final |
| `X-Remove-Overlay` | header | False | string | Specify whether to remove overlay elements from the page. |
| `X-Detach-Invisibles` | header | False | string | Temporarily detach elements with computed `display:none` before snapshotting, then restore them.<br><br>Requires the browser engine and disables caching. |
| `X-Markdown-Chunking` | header | False | string | Opt-in markdown chunking.<br><br>Supported values: <br>- true<br>- h1<br>- h2<br>- h3<br>- h4<br>- h5<br>- structured<br>- s1<br>- s2<br>- s3<br>- s4<br>- s5<br><br>Note if you are expecting text return, the chunking is done by injecting character \u001D |
| `X-Md-Heading-Style` | header | False | string | Heading style of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: setext, atx |
| `X-Md-Hr` | header | False | string | Hr text of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options). |
| `X-Md-Bullet-List-Marker` | header | False | string | Bullet list marker of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: -, +, * |
| `X-Md-Em-Delimiter` | header | False | string | Em delimiter of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: _, * |
| `X-Md-Strong-Delimiter` | header | False | string | Strong delimiter of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: **, __ |
| `X-Md-Link-Style` | header | False | string | Link style of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: inlined, referenced, discarded |
| `X-Md-Link-Reference-Style` | header | False | string | Link reference style of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: full, collapsed, shortcut, discarded |
| `X-Page` | header | False | string | Steer which page to return for uploaded files (PDF, DOC, XLS, PPT, etc.).<br><br>1-indexed; ignored when no file/PDF is uploaded. |

Request body:

- Required: False
- Content-Type: `application/json`
- Content-Type: `multipart/form-data`
- Content-Type: `application/x-www-form-urlencoded`
  Schema: `object`

Responses:

| Status | Description | Content Types |
| --- | --- | --- |
| `200` | OK | text/plain; charset=utf-8, application/json, text/event-stream |

### `/{url}`

#### `GET /{url}`

Summary: crawl

| Name | In | Required | Type | Description |
| --- | --- | --- | --- | --- |
| `url` | path | True | string |  |
| `html` | query | False | string |  |
| `base` | query | False |  |  |
| `pdf` | query | False | oneOf=, string |  |
| `file` | query | False | oneOf=, string |  |
| `page` | query | False | number |  |
| `respondWith` | query | False | oneOf=, string |  |
| `withGeneratedAlt` | query | False |  |  |
| `retainImages` | query | False |  |  |
| `retainMedia` | query | False |  |  |
| `preset` | query | False |  |  |
| `retainLinks` | query | False |  |  |
| `withLinksSummary` | query | False | oneOf=, string |  |
| `withImagesSummary` | query | False |  |  |
| `noCache` | query | False |  |  |
| `removeOverlay` | query | False |  |  |
| `detachInvisibles` | query | False |  |  |
| `noGfm` | query | False | oneOf=, string |  |
| `cacheTolerance` | query | False | number |  |
| `targetSelector` | query | False | string |  |
| `waitForSelector` | query | False | string |  |
| `removeSelector` | query | False | string |  |
| `keepImgDataUrl` | query | False |  |  |
| `withIframe` | query | False | oneOf=, string |  |
| `withShadowDom` | query | False |  |  |
| `setCookies` | query | False | oneOf=, string |  |
| `proxyUrl` | query | False | string |  |
| `proxy` | query | False | string |  |
| `userAgent` | query | False | string |  |
| `engine` | query | False | oneOf=, string |  |
| `injectPageScript` | query | False | string |  |
| `injectFrameScript` | query | False | string |  |
| `timeout` | query | False | number |  |
| `locale` | query | False | string |  |
| `referer` | query | False | string |  |
| `tokenBudget` | query | False | number |  |
| `assertStatusCode` | query | False | number |  |
| `instruction` | query | False | string |  |
| `jsonSchema` | query | False |  |  |
| `robotsTxt` | query | False | string |  |
| `doNotTrack` | query | False |  |  |
| `respondTiming` | query | False |  |  |
| `markdownChunking` | query | False | oneOf=, string |  |
| `maxTokens` | query | False | number |  |
| `Authorization` | header | False | anyOf=string; format=token | Jina Token for authentication.<br><br>- Member of &lt;JinaEmbeddingsAuthDTO&gt;<br><br>- Authorization: Bearer {YOUR_JINA_TOKEN} |
| `Accept` | header | False | string | Specifies your preference for the response format.<br><br>Supported formats: <br>- text/event-stream<br>- application/json or text/json<br>- text/plain |
| `X-Cache-Tolerance` | header | False | string | Sets internal cache tolerance in seconds if this header is specified with a integer. |
| `X-No-Cache` | header | False | string | Ignores internal cache if this header is specified with a value.<br><br>Equivalent to X-Cache-Tolerance: 0 |
| `X-Respond-With` | header | False | string | Specifies the (non-default) form of the crawled data you prefer.<br><br>Supported formats: <br>- markdown<br>- html<br>- text<br>- pageshot<br>- screenshot<br>- content<br>- frontmatter<br>- any combination of the above<br>- readerlm-v2<br>- vlm<br><br>Default: content |
| `X-Wait-For-Selector` | header | False | string | Specifies a CSS selector to wait for the appearance of such an element before returning.<br><br>Example: `X-Wait-For-Selector: .content-block` |
| `X-Target-Selector` | header | False | string | Specifies a CSS selector for return target instead of the full html.<br><br>Implies `X-Wait-For-Selector: (same selector)` |
| `X-Remove-Selector` | header | False | string | Specifies a CSS selector to remove elements from the full html.<br><br>Example `X-Remove-Selector: nav` |
| `X-Keep-Img-Data-Url` | header | False | string | Keep data-url as it instead of transforming them to object-url. (Only applicable when targeting markdown format)<br><br>Example `X-Keep-Img-Data-Url: true` |
| `X-Proxy-Url` | header | False | string | Specifies your custom proxy if you prefer to use one.<br><br>Supported protocols: <br>- http<br>- https<br>- socks4<br>- socks5<br><br>For authentication, https://user:pass@host:port |
| `X-Proxy` | header | False | string | Use a proxy server provided by us.<br><br>Optionally specify two-letter country code. |
| `X-Robots-Txt` | header | False | string | Load and conform to the respective robot.txt on the target origin.<br><br>Optionally specify a bot UA to check against. |
| `DNT` | header | False | string | When set to 1, prevent the result of this request to be cached in the system. |
| `X-Set-Cookie` | header | False | string | Sets cookie(s) to the headless browser for your request. <br><br>Syntax is the same with standard Set-Cookie |
| `X-With-Generated-Alt` | header | False | string | Enable automatic alt-text generating for images without an meaningful alt-text.<br><br>Note: Does not work when `X-Respond-With` is specified |
| `X-With-Images-Summary` | header | False | string | Enable dedicated summary section for images on the page. |
| `X-With-links-Summary` | header | False | string | Enable dedicated summary section for hyper links on the page. |
| `X-Retain-Links` | header | False | string | Link retention modes.<br><br>Supported modes: <br>- all: all links<br>- none: no links<br>- text: only link text<br>- gpt-oss: gpt-oss link citation format `【{id}†.*】` |
| `X-Retain-Images` | header | False | string | Image retention modes.<br><br>Supported modes: <br>- all: all images<br>- none: no images<br>- alt: only alt text<br>- all_p: all images and with generated alt text<br>- alt_p: only alt text and with generated alt |
| `X-Retain-Media` | header | False | string | Media retention modes for video, audio, and embedded video iframes.<br><br>Supported modes: <br>- none: no media<br>- text: plain label, e.g. `Video 1`<br>- link: markdown link, e.g. `[Video 1](url)` (default)<br>- image: markdown image syntax, e.g. `![Video 1](url)`<br>- html: original HTML with irrelevant attributes (class, id, style, data-*, aria-*) stripped |
| `X-Preset` | header | False | string | Apply a preset configuration for common scenarios.<br><br>Supported presets:<br>- reader: optimized for display to human users<br>- index: optimized for semantic indexing<br>- research: optimized for academic/research AI agents<br>- agent: optimized for day-to-day AI agents<br>- spider: optimized for recursive site crawling<br><br>Preset values are applied only to options not explicitly set by the caller. |
| `X-With-Iframe` | header | False | string | Enable filling iframe contents into main. (violates standards) |
| `X-With-Shadow-Dom` | header | False | string | Enable filling shadow dom contents into main. (violates standards) |
| `X-User-Agent` | header | False | string | Override User-Agent. |
| `X-Timeout` | header | False | string | Specify timeout in seconds. Max 180. |
| `X-Locale` | header | False | string | Specify browser locale for the page. |
| `X-Referer` | header | False | string | Specify referer for the page. |
| `X-Token-Budget` | header | False | string | Specify a budget in tokens.<br><br>If the resulting token cost exceeds the budget, the request is rejected.<br><br>Note this parameter is ignored for the search endpoint. |
| `X-Max-Tokens` | header | False | string | Trim the response content at a maximum number of tokens. |
| `X-Assert-Status-Code` | header | False | string | Assert the HTTP status code of the crawled page. If the actual status code does not match the asserted one, the request is rejected with 422 Unprocessable Entity. |
| `X-Respond-Timing` | header | False | string | Explicitly specify the respond timing. One of the following:<br><br>- html: directly return unrendered HTML<br>- visible-content: return immediately when any content becomes available<br>- mutation-idle: wait for DOM mutations to settle and remain unchanged for at least 0.2s<br>- resource-idle: wait for no additional resources that would affect page logic and content has SUCCEEDED loading in 0.5s<br>- media-idle: wait for no additional resources, including media resources, has SUCCEEDED loading in 0.5s<br>- network-idle: wait for full load of webpage, also known as networkidle0. |
| `X-Engine` | header | False | string | Specify the engine to use for crawling.<br><br>Supported: browser, direct, cf-browser-rendering |
| `X-Base` | header | False | string | Select base modes of relative URLs.<br><br>Supported: initial, final |
| `X-Remove-Overlay` | header | False | string | Specify whether to remove overlay elements from the page. |
| `X-Detach-Invisibles` | header | False | string | Temporarily detach elements with computed `display:none` before snapshotting, then restore them.<br><br>Requires the browser engine and disables caching. |
| `X-Markdown-Chunking` | header | False | string | Opt-in markdown chunking.<br><br>Supported values: <br>- true<br>- h1<br>- h2<br>- h3<br>- h4<br>- h5<br>- structured<br>- s1<br>- s2<br>- s3<br>- s4<br>- s5<br><br>Note if you are expecting text return, the chunking is done by injecting character \u001D |
| `X-Md-Heading-Style` | header | False | string | Heading style of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: setext, atx |
| `X-Md-Hr` | header | False | string | Hr text of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options). |
| `X-Md-Bullet-List-Marker` | header | False | string | Bullet list marker of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: -, +, * |
| `X-Md-Em-Delimiter` | header | False | string | Em delimiter of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: _, * |
| `X-Md-Strong-Delimiter` | header | False | string | Strong delimiter of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: **, __ |
| `X-Md-Link-Style` | header | False | string | Link style of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: inlined, referenced, discarded |
| `X-Md-Link-Reference-Style` | header | False | string | Link reference style of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: full, collapsed, shortcut, discarded |
| `X-Page` | header | False | string | Steer which page to return for uploaded files (PDF, DOC, XLS, PPT, etc.).<br><br>1-indexed; ignored when no file/PDF is uploaded. |

Responses:

| Status | Description | Content Types |
| --- | --- | --- |
| `200` | OK | text/plain; charset=utf-8, application/json, text/event-stream |

#### `POST /{url}`

Summary: crawl

| Name | In | Required | Type | Description |
| --- | --- | --- | --- | --- |
| `url` | path | True | string |  |
| `html` | query | False | string |  |
| `base` | query | False |  |  |
| `pdf` | query | False | oneOf=, string |  |
| `file` | query | False | oneOf=, string |  |
| `page` | query | False | number |  |
| `respondWith` | query | False | oneOf=, string |  |
| `withGeneratedAlt` | query | False |  |  |
| `retainImages` | query | False |  |  |
| `retainMedia` | query | False |  |  |
| `preset` | query | False |  |  |
| `retainLinks` | query | False |  |  |
| `withLinksSummary` | query | False | oneOf=, string |  |
| `withImagesSummary` | query | False |  |  |
| `noCache` | query | False |  |  |
| `removeOverlay` | query | False |  |  |
| `detachInvisibles` | query | False |  |  |
| `noGfm` | query | False | oneOf=, string |  |
| `cacheTolerance` | query | False | number |  |
| `targetSelector` | query | False | string |  |
| `waitForSelector` | query | False | string |  |
| `removeSelector` | query | False | string |  |
| `keepImgDataUrl` | query | False |  |  |
| `withIframe` | query | False | oneOf=, string |  |
| `withShadowDom` | query | False |  |  |
| `setCookies` | query | False | oneOf=, string |  |
| `proxyUrl` | query | False | string |  |
| `proxy` | query | False | string |  |
| `userAgent` | query | False | string |  |
| `engine` | query | False | oneOf=, string |  |
| `injectPageScript` | query | False | string |  |
| `injectFrameScript` | query | False | string |  |
| `timeout` | query | False | number |  |
| `locale` | query | False | string |  |
| `referer` | query | False | string |  |
| `tokenBudget` | query | False | number |  |
| `assertStatusCode` | query | False | number |  |
| `instruction` | query | False | string |  |
| `jsonSchema` | query | False |  |  |
| `robotsTxt` | query | False | string |  |
| `doNotTrack` | query | False |  |  |
| `respondTiming` | query | False |  |  |
| `markdownChunking` | query | False | oneOf=, string |  |
| `maxTokens` | query | False | number |  |
| `Authorization` | header | False | anyOf=string; format=token | Jina Token for authentication.<br><br>- Member of &lt;JinaEmbeddingsAuthDTO&gt;<br><br>- Authorization: Bearer {YOUR_JINA_TOKEN} |
| `Accept` | header | False | string | Specifies your preference for the response format.<br><br>Supported formats: <br>- text/event-stream<br>- application/json or text/json<br>- text/plain |
| `X-Cache-Tolerance` | header | False | string | Sets internal cache tolerance in seconds if this header is specified with a integer. |
| `X-No-Cache` | header | False | string | Ignores internal cache if this header is specified with a value.<br><br>Equivalent to X-Cache-Tolerance: 0 |
| `X-Respond-With` | header | False | string | Specifies the (non-default) form of the crawled data you prefer.<br><br>Supported formats: <br>- markdown<br>- html<br>- text<br>- pageshot<br>- screenshot<br>- content<br>- frontmatter<br>- any combination of the above<br>- readerlm-v2<br>- vlm<br><br>Default: content |
| `X-Wait-For-Selector` | header | False | string | Specifies a CSS selector to wait for the appearance of such an element before returning.<br><br>Example: `X-Wait-For-Selector: .content-block` |
| `X-Target-Selector` | header | False | string | Specifies a CSS selector for return target instead of the full html.<br><br>Implies `X-Wait-For-Selector: (same selector)` |
| `X-Remove-Selector` | header | False | string | Specifies a CSS selector to remove elements from the full html.<br><br>Example `X-Remove-Selector: nav` |
| `X-Keep-Img-Data-Url` | header | False | string | Keep data-url as it instead of transforming them to object-url. (Only applicable when targeting markdown format)<br><br>Example `X-Keep-Img-Data-Url: true` |
| `X-Proxy-Url` | header | False | string | Specifies your custom proxy if you prefer to use one.<br><br>Supported protocols: <br>- http<br>- https<br>- socks4<br>- socks5<br><br>For authentication, https://user:pass@host:port |
| `X-Proxy` | header | False | string | Use a proxy server provided by us.<br><br>Optionally specify two-letter country code. |
| `X-Robots-Txt` | header | False | string | Load and conform to the respective robot.txt on the target origin.<br><br>Optionally specify a bot UA to check against. |
| `DNT` | header | False | string | When set to 1, prevent the result of this request to be cached in the system. |
| `X-Set-Cookie` | header | False | string | Sets cookie(s) to the headless browser for your request. <br><br>Syntax is the same with standard Set-Cookie |
| `X-With-Generated-Alt` | header | False | string | Enable automatic alt-text generating for images without an meaningful alt-text.<br><br>Note: Does not work when `X-Respond-With` is specified |
| `X-With-Images-Summary` | header | False | string | Enable dedicated summary section for images on the page. |
| `X-With-links-Summary` | header | False | string | Enable dedicated summary section for hyper links on the page. |
| `X-Retain-Links` | header | False | string | Link retention modes.<br><br>Supported modes: <br>- all: all links<br>- none: no links<br>- text: only link text<br>- gpt-oss: gpt-oss link citation format `【{id}†.*】` |
| `X-Retain-Images` | header | False | string | Image retention modes.<br><br>Supported modes: <br>- all: all images<br>- none: no images<br>- alt: only alt text<br>- all_p: all images and with generated alt text<br>- alt_p: only alt text and with generated alt |
| `X-Retain-Media` | header | False | string | Media retention modes for video, audio, and embedded video iframes.<br><br>Supported modes: <br>- none: no media<br>- text: plain label, e.g. `Video 1`<br>- link: markdown link, e.g. `[Video 1](url)` (default)<br>- image: markdown image syntax, e.g. `![Video 1](url)`<br>- html: original HTML with irrelevant attributes (class, id, style, data-*, aria-*) stripped |
| `X-Preset` | header | False | string | Apply a preset configuration for common scenarios.<br><br>Supported presets:<br>- reader: optimized for display to human users<br>- index: optimized for semantic indexing<br>- research: optimized for academic/research AI agents<br>- agent: optimized for day-to-day AI agents<br>- spider: optimized for recursive site crawling<br><br>Preset values are applied only to options not explicitly set by the caller. |
| `X-With-Iframe` | header | False | string | Enable filling iframe contents into main. (violates standards) |
| `X-With-Shadow-Dom` | header | False | string | Enable filling shadow dom contents into main. (violates standards) |
| `X-User-Agent` | header | False | string | Override User-Agent. |
| `X-Timeout` | header | False | string | Specify timeout in seconds. Max 180. |
| `X-Locale` | header | False | string | Specify browser locale for the page. |
| `X-Referer` | header | False | string | Specify referer for the page. |
| `X-Token-Budget` | header | False | string | Specify a budget in tokens.<br><br>If the resulting token cost exceeds the budget, the request is rejected.<br><br>Note this parameter is ignored for the search endpoint. |
| `X-Max-Tokens` | header | False | string | Trim the response content at a maximum number of tokens. |
| `X-Assert-Status-Code` | header | False | string | Assert the HTTP status code of the crawled page. If the actual status code does not match the asserted one, the request is rejected with 422 Unprocessable Entity. |
| `X-Respond-Timing` | header | False | string | Explicitly specify the respond timing. One of the following:<br><br>- html: directly return unrendered HTML<br>- visible-content: return immediately when any content becomes available<br>- mutation-idle: wait for DOM mutations to settle and remain unchanged for at least 0.2s<br>- resource-idle: wait for no additional resources that would affect page logic and content has SUCCEEDED loading in 0.5s<br>- media-idle: wait for no additional resources, including media resources, has SUCCEEDED loading in 0.5s<br>- network-idle: wait for full load of webpage, also known as networkidle0. |
| `X-Engine` | header | False | string | Specify the engine to use for crawling.<br><br>Supported: browser, direct, cf-browser-rendering |
| `X-Base` | header | False | string | Select base modes of relative URLs.<br><br>Supported: initial, final |
| `X-Remove-Overlay` | header | False | string | Specify whether to remove overlay elements from the page. |
| `X-Detach-Invisibles` | header | False | string | Temporarily detach elements with computed `display:none` before snapshotting, then restore them.<br><br>Requires the browser engine and disables caching. |
| `X-Markdown-Chunking` | header | False | string | Opt-in markdown chunking.<br><br>Supported values: <br>- true<br>- h1<br>- h2<br>- h3<br>- h4<br>- h5<br>- structured<br>- s1<br>- s2<br>- s3<br>- s4<br>- s5<br><br>Note if you are expecting text return, the chunking is done by injecting character \u001D |
| `X-Md-Heading-Style` | header | False | string | Heading style of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: setext, atx |
| `X-Md-Hr` | header | False | string | Hr text of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options). |
| `X-Md-Bullet-List-Marker` | header | False | string | Bullet list marker of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: -, +, * |
| `X-Md-Em-Delimiter` | header | False | string | Em delimiter of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: _, * |
| `X-Md-Strong-Delimiter` | header | False | string | Strong delimiter of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: **, __ |
| `X-Md-Link-Style` | header | False | string | Link style of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: inlined, referenced, discarded |
| `X-Md-Link-Reference-Style` | header | False | string | Link reference style of the generated markdown.<br><br>This is an option passed through to [Turndown](https://github.com/mixmark-io/turndown?tab=readme-ov-file#options).<br><br>Supported: full, collapsed, shortcut, discarded |
| `X-Page` | header | False | string | Steer which page to return for uploaded files (PDF, DOC, XLS, PPT, etc.).<br><br>1-indexed; ignored when no file/PDF is uploaded. |

Request body:

- Required: False
- Content-Type: `application/json`
- Content-Type: `multipart/form-data`
- Content-Type: `application/x-www-form-urlencoded`
  Schema: `object`

Responses:

| Status | Description | Content Types |
| --- | --- | --- |
| `200` | OK | text/plain; charset=utf-8, application/json, text/event-stream |

## Schemas

### `JinaEmbeddingsAuthDTO@0x0b`

### `CrawlerOptions@0x20`

Type: `object`

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `url` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `html` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `base` |  | False | - Cast to: &lt; **&quot;initial&quot; \| &quot;final&quot;** &gt;<br><br>- Member of &lt;CrawlerOptions&gt;<br><br>- Defaults to: &#39;initial&#39; |
| `pdf` | oneOf=, string | False | Base64 encoded PDF.<br><br>- Cast to: &lt; **FancyFile\|string** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `file` | oneOf=, string | False | Base64 encoded file.<br><br>- Cast to: &lt; **FancyFile\|string** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `page` | number | False | Steer which page to return for uploaded files (1-indexed). Ignored when no file/PDF is uploaded.<br><br>- Cast to: &lt; **number** &gt;<br><br>- Member of &lt;CrawlerOptions&gt;<br><br>- Some validators will be applied on value(s): (v) =&gt; Number.isInteger(v) &amp;&amp; v &gt;= 1 |
| `respondWith` | oneOf=, string | False | - Cast to: &lt; **&quot;content&quot; \| &quot;markdown&quot; \| &quot;html&quot; \| &quot;text&quot; \| &quot;pageshot&quot; \| &quot;screenshot&quot; \| &quot;vlm&quot; \| &quot;readerlm-v2&quot; \| &quot;frontmatter&quot;\|string** &gt;<br><br>- Member of &lt;CrawlerOptions&gt;<br><br>- Defaults to: &#39;content&#39; |
| `withGeneratedAlt` |  | False | - Cast to: &lt; **PseudoBoolean** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `retainImages` |  | False | - Cast to: &lt; **&quot;none&quot; \| &quot;all&quot; \| &quot;alt&quot; \| &quot;all_p&quot; \| &quot;alt_p&quot;** &gt;<br><br>- Member of &lt;CrawlerOptions&gt;<br><br>- Defaults to: &#39;all&#39; |
| `retainMedia` |  | False | - Cast to: &lt; **&quot;none&quot; \| &quot;text&quot; \| &quot;link&quot; \| &quot;image&quot; \| &quot;html&quot;** &gt;<br><br>- Member of &lt;CrawlerOptions&gt;<br><br>- Defaults to: &#39;link&#39; |
| `preset` |  | False | - Cast to: &lt; **&quot;reader&quot; \| &quot;index&quot; \| &quot;research&quot; \| &quot;agent&quot; \| &quot;spider&quot;** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `retainLinks` |  | False | - Cast to: &lt; **&quot;none&quot; \| &quot;all&quot; \| &quot;text&quot; \| &quot;gpt-oss&quot;** &gt;<br><br>- Member of &lt;CrawlerOptions&gt;<br><br>- Defaults to: &#39;all&#39; |
| `withLinksSummary` | oneOf=, string | False | - Cast to: &lt; **PseudoBoolean\|string** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `withImagesSummary` |  | False | - Cast to: &lt; **PseudoBooleanLoose** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `noCache` |  | False | - Cast to: &lt; **PseudoBooleanLoose** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `removeOverlay` |  | False | - Cast to: &lt; **PseudoBooleanLoose** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `detachInvisibles` |  | False | - Cast to: &lt; **PseudoBooleanLoose** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `noGfm` | oneOf=, string | False | - Cast to: &lt; **PseudoBoolean\|string** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `cacheTolerance` | number | False | - Cast to: &lt; **number** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `targetSelector` | array; items=string | False | - Cast to: &lt; **Array&lt;string&gt;** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `waitForSelector` | array; items=string | False | - Cast to: &lt; **Array&lt;string&gt;** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `removeSelector` | array; items=string | False | - Cast to: &lt; **Array&lt;string&gt;** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `keepImgDataUrl` |  | False | - Cast to: &lt; **PseudoBooleanLoose** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `withIframe` | oneOf=, string | False | - Cast to: &lt; **PseudoBoolean\|string** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `withShadowDom` |  | False | - Cast to: &lt; **PseudoBooleanLoose** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `setCookies` | array; items=oneOf=, string | False | - Cast to: &lt; **Array&lt;object\|string&gt;** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `proxyUrl` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `proxy` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `userAgent` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `engine` | oneOf=, string | False | - Cast to: &lt; **&quot;auto&quot; \| &quot;browser&quot; \| &quot;curl&quot; \| &quot;cf-browser-rendering&quot;\|string** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `injectPageScript` | array; items=string | False | - Cast to: &lt; **Array&lt;string&gt;** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `injectFrameScript` | array; items=string | False | - Cast to: &lt; **Array&lt;string&gt;** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `timeout` | number | False | - Cast to: &lt; **number** &gt;<br><br>- Member of &lt;CrawlerOptions&gt;<br><br>- Some validators will be applied on value(s): (v) =&gt; v &gt; 0 &amp;&amp; v &lt;= 180 |
| `locale` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `referer` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `tokenBudget` | number | False | - Cast to: &lt; **number** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `assertStatusCode` | number | False | - Cast to: &lt; **number** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `viewport` |  | False | - Cast to: &lt; **Viewport** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `instruction` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `jsonSchema` |  | False | Can be any value - string, number, boolean, array or object.<br><br>- Cast to: &lt; **object** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `robotsTxt` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `doNotTrack` |  | False | Can be any value - string, number, boolean, array or object.<br><br>- Cast to: &lt; **object** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `markdown` |  | False | - Cast to: &lt; **TurnDownTweakableOptions** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `respondTiming` |  | False | - Cast to: &lt; **&quot;html&quot; \| &quot;visible-content&quot; \| &quot;mutation-idle&quot; \| &quot;resource-idle&quot; \| &quot;media-idle&quot; \| &quot;network-idle&quot;** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `markdownChunking` | oneOf=, string | False | - Cast to: &lt; **&quot;true&quot; \| &quot;h1&quot; \| &quot;h2&quot; \| &quot;h3&quot; \| &quot;h4&quot; \| &quot;h5&quot; \| &quot;structured&quot; \| &quot;s1&quot; \| &quot;s2&quot; \| &quot;s3&quot; \| &quot;s4&quot; \| &quot;s5&quot;\|string** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |
| `maxTokens` | number | False | - Cast to: &lt; **number** &gt;<br><br>- Member of &lt;CrawlerOptions&gt;<br><br>- Some validators will be applied on value(s): (v) =&gt; v &gt;= 500 |
| `customHeader` | object | False | - Cast to: &lt; **Record&lt;string, string&gt;** &gt;<br><br>- Member of &lt;CrawlerOptions&gt; |

### `enum@0x0c`

Enum<"initial" | "final">

Type: `string; enum=initial, final`

Enum values:
- `initial`
- `final`

### `FancyFile@0x0d`

Type: `string; format=binary`

### `enum@0x0e`

Enum<"content" | "markdown" | "html" | "text" | "pageshot" | "screenshot" | "vlm" | "readerlm-v2" | "frontmatter">

Type: `string; enum=content, markdown, html, text, pageshot, screenshot, vlm, readerlm-v2, frontmatter`

Enum values:
- `content`
- `markdown`
- `html`
- `text`
- `pageshot`
- `screenshot`
- `vlm`
- `readerlm-v2`
- `frontmatter`

### `PseudoBoolean@0x0f`

### `enum@0x10`

Enum<"none" | "all" | "alt" | "all_p" | "alt_p">

Type: `string; enum=none, all, alt, all_p, alt_p`

Enum values:
- `none`
- `all`
- `alt`
- `all_p`
- `alt_p`

### `enum@0x11`

Enum<"none" | "text" | "link" | "image" | "html">

Type: `string; enum=none, text, link, image, html`

Enum values:
- `none`
- `text`
- `link`
- `image`
- `html`

### `enum@0x12`

Enum<"reader" | "index" | "research" | "agent" | "spider">

Type: `string; enum=reader, index, research, agent, spider`

Enum values:
- `reader`
- `index`
- `research`
- `agent`
- `spider`

### `enum@0x13`

Enum<"none" | "all" | "text" | "gpt-oss">

Type: `string; enum=none, all, text, gpt-oss`

Enum values:
- `none`
- `all`
- `text`
- `gpt-oss`

### `PseudoBooleanLoose@0x14`

### `enum@0x15`

Enum<"auto" | "browser" | "curl" | "cf-browser-rendering">

Type: `string; enum=auto, browser, curl, cf-browser-rendering`

Enum values:
- `auto`
- `browser`
- `curl`
- `cf-browser-rendering`

### `Viewport@0x16`

Type: `object`

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `width` | number | False | - Cast to: &lt; **number** &gt;<br><br>- Member of &lt;Viewport&gt;<br><br>- Defaults to: 1280 |
| `height` | number | False | - Cast to: &lt; **number** &gt;<br><br>- Member of &lt;Viewport&gt;<br><br>- Defaults to: 1280 |
| `deviceScaleFactor` | number | False | - Cast to: &lt; **number** &gt;<br><br>- Member of &lt;Viewport&gt; |
| `isMobile` | boolean | False | - Cast to: &lt; **boolean** &gt;<br><br>- Member of &lt;Viewport&gt; |
| `isLandscape` | boolean | False | - Cast to: &lt; **boolean** &gt;<br><br>- Member of &lt;Viewport&gt; |
| `hasTouch` | boolean | False | - Cast to: &lt; **boolean** &gt;<br><br>- Member of &lt;Viewport&gt; |

### `TurnDownTweakableOptions@0x1d`

Type: `object`

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `headingStyle` |  | False | Turndown options > headingStyle<br><br>- Cast to: &lt; **&quot;setext&quot; \| &quot;atx&quot;** &gt;<br><br>- Member of &lt;TurnDownTweakableOptions&gt; |
| `hr` | string | False | Turndown options > hr<br><br>- Cast to: &lt; **string** &gt;<br><br>- Member of &lt;TurnDownTweakableOptions&gt;<br><br>- Some validators will be applied on value(s): (v) =&gt; v.length &gt; 0 &amp;&amp; v.length &lt;= 128 |
| `bulletListMarker` |  | False | Turndown options > bulletListMarker<br><br>- Cast to: &lt; **&quot;-&quot; \| &quot;+&quot; \| &quot;*&quot;** &gt;<br><br>- Member of &lt;TurnDownTweakableOptions&gt; |
| `emDelimiter` |  | False | Turndown options > emDelimiter<br><br>- Cast to: &lt; **&quot;_&quot; \| &quot;*&quot;** &gt;<br><br>- Member of &lt;TurnDownTweakableOptions&gt; |
| `strongDelimiter` |  | False | Turndown options > strongDelimiter<br><br>- Cast to: &lt; **&quot;__&quot; \| &quot;**&quot;** &gt;<br><br>- Member of &lt;TurnDownTweakableOptions&gt; |
| `linkStyle` |  | False | Turndown options > linkStyle<br><br>- Cast to: &lt; **&quot;inlined&quot; \| &quot;referenced&quot; \| &quot;discarded&quot;** &gt;<br><br>- Member of &lt;TurnDownTweakableOptions&gt; |
| `linkReferenceStyle` |  | False | Turndown options > linkReferenceStyle<br><br>- Cast to: &lt; **&quot;full&quot; \| &quot;collapsed&quot; \| &quot;shortcut&quot; \| &quot;discarded&quot;** &gt;<br><br>- Member of &lt;TurnDownTweakableOptions&gt; |

### `enum@0x17`

Enum<"setext" | "atx">

Type: `string; enum=setext, atx`

Enum values:
- `setext`
- `atx`

### `enum@0x18`

Enum<"-" | "+" | "*">

Type: `string; enum=-, +, *`

Enum values:
- `-`
- `+`
- `*`

### `enum@0x19`

Enum<"_" | "*">

Type: `string; enum=_, *`

Enum values:
- `_`
- `*`

### `enum@0x1a`

Enum<"__" | "**">

Type: `string; enum=__, **`

Enum values:
- `__`
- `**`

### `enum@0x1b`

Enum<"inlined" | "referenced" | "discarded">

Type: `string; enum=inlined, referenced, discarded`

Enum values:
- `inlined`
- `referenced`
- `discarded`

### `enum@0x1c`

Enum<"full" | "collapsed" | "shortcut" | "discarded">

Type: `string; enum=full, collapsed, shortcut, discarded`

Enum values:
- `full`
- `collapsed`
- `shortcut`
- `discarded`

### `enum@0x1e`

Enum<"html" | "visible-content" | "mutation-idle" | "resource-idle" | "media-idle" | "network-idle">

Type: `string; enum=html, visible-content, mutation-idle, resource-idle, media-idle, network-idle`

Enum values:
- `html`
- `visible-content`
- `mutation-idle`
- `resource-idle`
- `media-idle`
- `network-idle`

### `enum@0x1f`

Enum<"true" | "h1" | "h2" | "h3" | "h4" | "h5" | "structured" | "s1" | "s2" | "s3" | "s4" | "s5">

Type: `string; enum=true, h1, h2, h3, h4, h5, structured, s1, s2, s3, s4, s5`

Enum values:
- `true`
- `h1`
- `h2`
- `h3`
- `h4`
- `h5`
- `structured`
- `s1`
- `s2`
- `s3`
- `s4`
- `s5`

### `CrawlerOptionsHeaderOnly@0x21`

Type: `object`

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `url` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `html` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `base` |  | False | - Cast to: &lt; **&quot;initial&quot; \| &quot;final&quot;** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt;<br><br>- Defaults to: &#39;initial&#39; |
| `pdf` | oneOf=, string | False | Base64 encoded PDF.<br><br>- Cast to: &lt; **FancyFile\|string** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `file` | oneOf=, string | False | Base64 encoded file.<br><br>- Cast to: &lt; **FancyFile\|string** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `page` | number | False | Steer which page to return for uploaded files (1-indexed). Ignored when no file/PDF is uploaded.<br><br>- Cast to: &lt; **number** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt;<br><br>- Some validators will be applied on value(s): (v) =&gt; Number.isInteger(v) &amp;&amp; v &gt;= 1 |
| `respondWith` | oneOf=, string | False | - Cast to: &lt; **&quot;content&quot; \| &quot;markdown&quot; \| &quot;html&quot; \| &quot;text&quot; \| &quot;pageshot&quot; \| &quot;screenshot&quot; \| &quot;vlm&quot; \| &quot;readerlm-v2&quot; \| &quot;frontmatter&quot;\|string** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt;<br><br>- Defaults to: &#39;content&#39; |
| `withGeneratedAlt` |  | False | - Cast to: &lt; **PseudoBoolean** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `retainImages` |  | False | - Cast to: &lt; **&quot;none&quot; \| &quot;all&quot; \| &quot;alt&quot; \| &quot;all_p&quot; \| &quot;alt_p&quot;** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt;<br><br>- Defaults to: &#39;all&#39; |
| `retainMedia` |  | False | - Cast to: &lt; **&quot;none&quot; \| &quot;text&quot; \| &quot;link&quot; \| &quot;image&quot; \| &quot;html&quot;** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt;<br><br>- Defaults to: &#39;link&#39; |
| `preset` |  | False | - Cast to: &lt; **&quot;reader&quot; \| &quot;index&quot; \| &quot;research&quot; \| &quot;agent&quot; \| &quot;spider&quot;** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `retainLinks` |  | False | - Cast to: &lt; **&quot;none&quot; \| &quot;all&quot; \| &quot;text&quot; \| &quot;gpt-oss&quot;** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt;<br><br>- Defaults to: &#39;all&#39; |
| `withLinksSummary` | oneOf=, string | False | - Cast to: &lt; **PseudoBoolean\|string** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `withImagesSummary` |  | False | - Cast to: &lt; **PseudoBooleanLoose** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `noCache` |  | False | - Cast to: &lt; **PseudoBooleanLoose** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `removeOverlay` |  | False | - Cast to: &lt; **PseudoBooleanLoose** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `detachInvisibles` |  | False | - Cast to: &lt; **PseudoBooleanLoose** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `noGfm` | oneOf=, string | False | - Cast to: &lt; **PseudoBoolean\|string** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `cacheTolerance` | number | False | - Cast to: &lt; **number** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `targetSelector` | array; items=string | False | - Cast to: &lt; **Array&lt;string&gt;** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `waitForSelector` | array; items=string | False | - Cast to: &lt; **Array&lt;string&gt;** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `removeSelector` | array; items=string | False | - Cast to: &lt; **Array&lt;string&gt;** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `keepImgDataUrl` |  | False | - Cast to: &lt; **PseudoBooleanLoose** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `withIframe` | oneOf=, string | False | - Cast to: &lt; **PseudoBoolean\|string** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `withShadowDom` |  | False | - Cast to: &lt; **PseudoBooleanLoose** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `setCookies` | array; items=oneOf=, string | False | - Cast to: &lt; **Array&lt;object\|string&gt;** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `proxyUrl` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `proxy` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `userAgent` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `engine` | oneOf=, string | False | - Cast to: &lt; **&quot;auto&quot; \| &quot;browser&quot; \| &quot;curl&quot; \| &quot;cf-browser-rendering&quot;\|string** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `injectPageScript` | array; items=string | False | - Cast to: &lt; **Array&lt;string&gt;** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `injectFrameScript` | array; items=string | False | - Cast to: &lt; **Array&lt;string&gt;** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `timeout` | number | False | - Cast to: &lt; **number** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt;<br><br>- Some validators will be applied on value(s): (v) =&gt; v &gt; 0 &amp;&amp; v &lt;= 180 |
| `locale` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `referer` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `tokenBudget` | number | False | - Cast to: &lt; **number** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `assertStatusCode` | number | False | - Cast to: &lt; **number** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `viewport` |  | False | - Cast to: &lt; **Viewport** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `instruction` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `jsonSchema` |  | False | Can be any value - string, number, boolean, array or object.<br><br>- Cast to: &lt; **object** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `robotsTxt` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `doNotTrack` |  | False | Can be any value - string, number, boolean, array or object.<br><br>- Cast to: &lt; **object** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `markdown` |  | False | - Cast to: &lt; **TurnDownTweakableOptions** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `respondTiming` |  | False | - Cast to: &lt; **&quot;html&quot; \| &quot;visible-content&quot; \| &quot;mutation-idle&quot; \| &quot;resource-idle&quot; \| &quot;media-idle&quot; \| &quot;network-idle&quot;** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `markdownChunking` | oneOf=, string | False | - Cast to: &lt; **&quot;true&quot; \| &quot;h1&quot; \| &quot;h2&quot; \| &quot;h3&quot; \| &quot;h4&quot; \| &quot;h5&quot; \| &quot;structured&quot; \| &quot;s1&quot; \| &quot;s2&quot; \| &quot;s3&quot; \| &quot;s4&quot; \| &quot;s5&quot;\|string** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |
| `maxTokens` | number | False | - Cast to: &lt; **number** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt;<br><br>- Some validators will be applied on value(s): (v) =&gt; v &gt;= 500 |
| `customHeader` | object | False | - Cast to: &lt; **Record&lt;string, string&gt;** &gt;<br><br>- Member of &lt;CrawlerOptionsHeaderOnly&gt; |

### `FormattedPageDto@0x29`

Type: `object`

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `title` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;FormattedPageDto&gt; |
| `description` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;FormattedPageDto&gt; |
| `url` | string | True | [REQUIRED]<br><br>- Cast to: &lt; **string** &gt;<br><br>- Member of &lt;FormattedPageDto&gt; |
| `content` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;FormattedPageDto&gt; |
| `chunks` |  | False | - Cast to: &lt; **Array&lt;string&gt;** &gt;<br><br>- Member of &lt;FormattedPageDto&gt; |
| `publishedTime` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;FormattedPageDto&gt; |
| `html` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;FormattedPageDto&gt; |
| `text` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;FormattedPageDto&gt; |
| `screenshotUrl` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;FormattedPageDto&gt; |
| `pageshotUrl` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;FormattedPageDto&gt; |
| `numPages` | number | False | - Cast to: &lt; **number** &gt;<br><br>- Member of &lt;FormattedPageDto&gt; |
| `links` | oneOf=, ,  | False | - Cast to: &lt; **object\|Record&lt;string\|symbol, string&gt;\|Array&lt;string&gt;** &gt;<br><br>- Member of &lt;FormattedPageDto&gt; |
| `images` | oneOf=, ,  | False | - Cast to: &lt; **object\|Record&lt;string\|symbol, string&gt;\|Array&lt;string&gt;** &gt;<br><br>- Member of &lt;FormattedPageDto&gt; |
| `warning` | string | False | - Cast to: &lt; **string** &gt;<br><br>- Member of &lt;FormattedPageDto&gt; |
| `metadata` | oneOf=,  | False | - Cast to: &lt; **object\|Record&lt;string\|symbol, string&gt;** &gt;<br><br>- Member of &lt;FormattedPageDto&gt; |
| `external` | oneOf=,  | False | - Cast to: &lt; **object\|Record&lt;string\|symbol, Record&lt;string\|symbol, Record&lt;string\|symbol, string\|object&gt;@0x08\|object&gt;@0x09\|object&gt;** &gt;<br><br>- Member of &lt;FormattedPageDto&gt; |

### `Array<string>@0x22`

Type: `array; items=string`

### `Record<string|symbol, string>@0x23`

Type: `object`

### `Array<string>@0x24`

Type: `array; items=string`

### `Record<string|symbol, string>@0x25`

Type: `object`

### `Array<string>@0x26`

Type: `array; items=string`

### `Record<string|symbol, string>@0x27`

Type: `object`

### `Record<string|symbol, Record<string|symbol, Record<string|symbol, string|object>@0x08|object>@0x09|object>@0x28`

Type: `object`

### `Record<string|symbol, Record<string|symbol, string|object>@0x08|object>@0x09`

Type: `object`

### `Record<string|symbol, string|object>@0x08`

Type: `object`

### `OutputServerEventStream@0x2a`

Binary data (stream)

Type: `string; format=binary`
