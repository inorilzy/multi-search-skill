> Source: https://docs.firecrawl.dev/features/scrape.md
> Retrieved: 2026-10-31
> Covers: POST /v2/scrape (feature guide)


# Scrape

> Turn any URL into clean Markdown or structured data

Scrape turns any URL into clean Markdown or structured data for AI agents, including JS-heavy pages and dynamic apps.

* It manages complexities: proxies, caching, rate limits, js-blocked content
* Handles dynamic content: dynamic websites, js-rendered sites, PDFs, images
* Outputs clean markdown, structured data, screenshots or html.

For details, see the [Scrape Endpoint API Reference](https://docs.firecrawl.dev/api-reference/endpoint/scrape.md).

> [card] [Try it in the Playground](https://www.firecrawl.dev/playground?endpoint=scrape)
>
> Test scraping in the interactive playground — no code required.

Scraping a document at a URL, or parsing one from disk? This walks through when to use Scrape and when to use [Parse](https://docs.firecrawl.dev/features/parse.md):

[Firecrawl Parse vs Scrape Explained in 5 Minutes](https://www.youtube.com/embed/119uEEBQRrA)

> [!NOTE]
>
> If a request fails, see [Errors](https://docs.firecrawl.dev/api-reference/errors.md) for the full catalog of error codes, causes, remedies, and retry guidance.

## Scraping a URL with Firecrawl

### /scrape endpoint

Used to scrape a URL and get its content.

### Installation

```python Python theme={null}
# pip install firecrawl

from firecrawl import Firecrawl

firecrawl = Firecrawl(
  # No API key needed to get started — add one for higher rate limits:
  # api_key="fc-YOUR-API-KEY",
)
```

```js Node theme={null}
// npm install firecrawl

import { Firecrawl } from 'firecrawl';

const firecrawl = new Firecrawl({
  // No API key needed to get started — add one for higher rate limits:
  // apiKey: "fc-YOUR-API-KEY",
});
```

```bash CLI theme={null}
# Install globally with npm
npm install -g firecrawl

# Authenticate (one-time setup)
firecrawl login
```

### Usage

```python Python theme={null}
from firecrawl import Firecrawl

firecrawl = Firecrawl(
  # No API key needed to get started — add one for higher rate limits:
  # api_key="fc-YOUR-API-KEY",
)

# Scrape a website:
doc = firecrawl.scrape("https://firecrawl.dev", formats=["markdown", "html"])
print(doc)
```

```js Node theme={null}
import { Firecrawl } from 'firecrawl';

const firecrawl = new Firecrawl({
  // No API key needed to get started — add one for higher rate limits:
  // apiKey: "fc-YOUR-API-KEY",
});

// Scrape a website:
const doc = await firecrawl.scrape('https://firecrawl.dev', { formats: ['markdown', 'html'] });
console.log(doc);
```

```bash cURL theme={null}
# No API key needed to get started — add -H "Authorization: Bearer $FIRECRAWL_API_KEY" for higher rate limits:
curl -s -X POST "https://api.firecrawl.dev/v2/scrape" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://firecrawl.dev",
    "formats": ["markdown", "html"]
  }'
```

```bash CLI theme={null}
# Scrape a URL and get markdown
firecrawl https://firecrawl.dev

# With multiple formats (returns JSON)
firecrawl https://firecrawl.dev --format markdown,html,links --pretty
```

For more details about the parameters, refer to the [API Reference](https://docs.firecrawl.dev/api-reference/endpoint/scrape.md).

> [!TIP]
>
> **PDFs and documents:** `/scrape` auto-detects PDFs, DOCX, and other document types from URLs. Pass a PDF URL the same way you would any webpage -- Firecrawl parses it and returns clean markdown. For local files that are not accessible by URL, use [`/parse`](https://docs.firecrawl.dev/features/parse) instead.
>
> ```python Python theme={null}
> doc = firecrawl.scrape("https://example.com/report.pdf", formats=["markdown"])
> print(doc.markdown)
> ```

> [!NOTE]
>
> Each scrape consumes 1 credit. Additional credits apply for certain options: JSON mode costs 4 additional credits per page, question and highlights formats cost 4 additional credits per page per format, PII redaction costs 4 additional credits per page, PDF parsing costs 1 credit per PDF page, and audio or video extraction costs 4 additional credits per page.

### Response

SDKs will return the data object directly. cURL will return the payload exactly as shown below.

```json theme={null}
{
  "success": true,
  "data" : {
    "markdown": "Launch Week I is here! [See our Day 2 Release 🚀](https://www.firecrawl.dev/blog/launch-week-i-day-2-doubled-rate-limits)[💥 Get 2 months free...",
    "html": "<!DOCTYPE html><html lang=\"en\" class=\"light\" style=\"color-scheme: light;\"><body class=\"__variable_36bd41 __variable_d7dc5d font-inter ...",
    "metadata": {
      "title": "Home - Firecrawl",
      "description": "Firecrawl crawls and converts any website into clean markdown.",
      "language": "en",
      "keywords": "Firecrawl,Markdown,Data,Mendable,Langchain",
      "robots": "follow, index",
      "ogTitle": "Firecrawl",
      "ogDescription": "The API to search, scrape, and interact with the web at scale.",
      "ogUrl": "https://www.firecrawl.dev/",
      "ogImage": "https://www.firecrawl.dev/og.png?123",
      "ogLocaleAlternate": [],
      "ogSiteName": "Firecrawl",
      "sourceURL": "https://firecrawl.dev",
      "statusCode": 200,
      "contentType": "text/html"
    }
  }
}
```

### Response metadata and status codes

There are two separate status layers in a scrape response, and it helps to keep them apart:

* **API request status**: the HTTP status of the Firecrawl API call itself, alongside the `success` boolean in the response body. An accepted and processed request returns HTTP `200` with `success: true`, even if the target page underneath returned a non-2xx code.
* **Page status** (`data.metadata.statusCode`): the HTTP status the target website returned for that page (e.g. `200`, `301`, `404`, `403`, `500`). This is what tells you how the page itself responded.

So the reliable pattern is: first confirm the request succeeded (HTTP `200` + `success: true`), then check `data.metadata.statusCode` for the actual page outcome. Firecrawl treats a `statusCode` of 2xx or `304` as a clean page load; anything else means the page did not load cleanly. When a page returns an error status, `data.metadata.error` may carry additional detail.

`data.metadata.provider` is set when a third-party data provider served the URL (see [Provider-routed URLs](#provider-routed-urls)): `id` is the provider that returned the data, `creditsCost` is what that access cost, and `steps` lists each provider tried, in order, with its status (`matched`, `not_found`, `error`) and credits.

## Scrape Formats

You can now choose what formats you want your output in. You can specify multiple output formats. Supported formats are:

* Markdown (`markdown`)
* Summary (`summary`)
* HTML (`html`) - cleaned version of the page's HTML
* Raw HTML (`rawHtml`) - unmodified HTML as received from the page
* Raw Base64 (`rawBase64`) - Base64-encoded original HTTP response body; must be the only format in the request
* Screenshot (`screenshot`, with options like `fullPage`, `quality`, `viewport`) — screenshot URLs expire after 24 hours
* Links (`links`)
* JSON (`json`) - structured output
* Images (`images`) - extract all image URLs from the page
* Branding (`branding`) - extract brand identity and design system
* Product (`product`) - extract a structured product (title, price, availability, variants) from product pages
* Audio (`audio`) - extract MP3 audio from supported video URLs, e.g. YouTube (returns a signed GCS URL, expires after 1 hour)
* Video (`video`) - extract best-quality video from supported video URLs, e.g. YouTube (returns a signed GCS URL, expires after 1 hour)
* Query (`query`, with `prompt` and optional `mode`) - ask a natural-language question about the page; the answer is returned in the `answer` field

Output keys will match the format you choose.

The `rawBase64` format returns the original HTTP response body, encoded as Base64. The `rawBase64` field holds a bare Base64 string, not a data URI. Read the MIME type from `metadata.contentType`. Request `rawBase64` alone, because the API rejects it together with any other format. The response has no `markdown`, `html`, or `rawHtml` field, and it holds only the one file at that URL, not CSS, images, or other sub-resources.

## Extract structured data

### /scrape (with json) endpoint

Used to extract structured data from scraped pages.

> [!TIP]
>
> Extracting products? For product pages, the [`product` format](#extract-product-data) returns structured product fields (title, price, availability, variants) deterministically — no LLM call and no schema to define. Reach for `json` when you need custom fields or non-product pages.

```python Python theme={null}
from firecrawl import Firecrawl
from pydantic import BaseModel

app = Firecrawl(
  # No API key needed to get started — add one for higher rate limits:
  # api_key="fc-YOUR-API-KEY",
)

class CompanyInfo(BaseModel):
    company_mission: str
    supports_sso: bool
    is_open_source: bool
    is_in_yc: bool

result = app.scrape(
    'https://firecrawl.dev',
    formats=[{
      "type": "json",
      "schema": CompanyInfo.model_json_schema()
    }],
    only_main_content=False,
    timeout=120000
)

print(result)
```

```js Node theme={null}
import { Firecrawl } from "firecrawl";
import { z } from "zod";

const app = new Firecrawl({
  // No API key needed to get started — add one for higher rate limits:
  // apiKey: "fc-YOUR_API_KEY",
});

// Define schema to extract contents into
const schema = z.object({
  company_mission: z.string(),
  supports_sso: z.boolean(),
  is_open_source: z.boolean(),
  is_in_yc: z.boolean()
});

const result = await app.scrape("https://firecrawl.dev", {
  formats: [{
    type: "json",
    schema: schema
  }],
});

console.log(result);
```

```bash cURL theme={null}
# No API key needed to get started — add -H "Authorization: Bearer YOUR_API_KEY" for higher rate limits:
curl -X POST https://api.firecrawl.dev/v2/scrape \
    -H 'Content-Type: application/json' \
    -d '{
      "url": "https://firecrawl.dev",
      "formats": [ {
        "type": "json",
        "schema": {
          "type": "object",
          "properties": {
            "company_mission": {
                      "type": "string"
            },
            "supports_sso": {
                      "type": "boolean"
            },
            "is_open_source": {
                      "type": "boolean"
            },
            "is_in_yc": {
                      "type": "boolean"
            }
          },
          "required": [
            "company_mission",
            "supports_sso",
            "is_open_source",
            "is_in_yc"
          ]
        }
      } ]
    }'
```

Output:

```json JSON theme={null}
{
    "success": true,
    "data": {
      "json": {
        "company_mission": "AI-powered web scraping and data extraction",
        "supports_sso": true,
        "is_open_source": true,
        "is_in_yc": true
      },
      "metadata": {
        "title": "Firecrawl",
        "description": "AI-powered web scraping and data extraction",
        "robots": "follow, index",
        "ogTitle": "Firecrawl",
        "ogDescription": "AI-powered web scraping and data extraction",
        "ogUrl": "https://firecrawl.dev/",
        "ogImage": "https://firecrawl.dev/og.png",
        "ogLocaleAlternate": [],
        "ogSiteName": "Firecrawl",
        "sourceURL": "https://firecrawl.dev/"
      },
    }
}
```

### Extracting without schema

You can now extract without a schema by just passing a `prompt` to the endpoint. The llm chooses the structure of the data.

```python Python theme={null}
from firecrawl import Firecrawl

app = Firecrawl(
  # No API key needed to get started — add one for higher rate limits:
  # api_key="fc-YOUR-API-KEY",
)

result = app.scrape(
    'https://firecrawl.dev',
    formats=[{
      "type": "json",
      "prompt": "Extract the company mission from the page."
    }],
    only_main_content=False,
    timeout=120000
)

print(result)
```

```js Node theme={null}
import { Firecrawl } from "firecrawl";

const app = new Firecrawl({
  // No API key needed to get started — add one for higher rate limits:
  // apiKey: "fc-YOUR_API_KEY",
});

const result = await app.scrape("https://firecrawl.dev", {
  formats: [{
    type: "json",
    prompt: "Extract the company mission from the page."
  }]
});

console.log(result);
```

```bash cURL theme={null}
# No API key needed to get started — add -H "Authorization: Bearer YOUR_API_KEY" for higher rate limits:
curl -X POST https://api.firecrawl.dev/v2/scrape \
    -H 'Content-Type: application/json' \
    -d '{
      "url": "https://firecrawl.dev",
      "formats": [{
        "type": "json",
        "prompt": "Extract the company mission from the page."
      }]
    }'
```

Output:

```json JSON theme={null}
{
    "success": true,
    "data": {
      "json": {
        "company_mission": "AI-powered web scraping and data extraction",
      },
      "metadata": {
        "title": "Firecrawl",
        "description": "AI-powered web scraping and data extraction",
        "robots": "follow, index",
        "ogTitle": "Firecrawl",
        "ogDescription": "AI-powered web scraping and data extraction",
        "ogUrl": "https://firecrawl.dev/",
        "ogImage": "https://firecrawl.dev/og.png",
        "ogLocaleAlternate": [],
        "ogSiteName": "Firecrawl",
        "sourceURL": "https://firecrawl.dev/"
      },
    }
}
```

### JSON format options

When using the `json` format, pass an object inside `formats` with the following parameters:

* `schema`: JSON Schema for the structured output.
* `prompt`: Optional prompt to help guide extraction when a schema is present or when you prefer light guidance.

## Extract brand identity

### /scrape (with branding) endpoint

The branding format extracts comprehensive brand identity information from a webpage, including colors, fonts, typography, spacing, UI components, and more. This is useful for design system analysis, brand monitoring, or building tools that need to understand a website's visual identity.

```python Python theme={null}
from firecrawl import Firecrawl

firecrawl = Firecrawl(
  # No API key needed to get started — add one for higher rate limits:
  # api_key='fc-YOUR_API_KEY',
)

result = firecrawl.scrape(
    url='https://firecrawl.dev',
    formats=['branding']
)

print(result['branding'])
```

```js Node theme={null}
import { Firecrawl } from 'firecrawl';

const firecrawl = new Firecrawl({
  // No API key needed to get started — add one for higher rate limits:
  // apiKey: "fc-YOUR-API-KEY",
});

const result = await firecrawl.scrape('https://firecrawl.dev', {
    formats: ['branding']
});

console.log(result.branding);
```

```bash cURL theme={null}
# No API key needed to get started — add -H "Authorization: Bearer $FIRECRAWL_API_KEY" for higher rate limits:
curl -s -X POST "https://api.firecrawl.dev/v2/scrape" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://firecrawl.dev",
    "formats": ["branding"]
  }'
```

### Response

The branding format returns a comprehensive `BrandingProfile` object with the following structure:

```json Output theme={null}
{
  "success": true,
  "data": {
    "branding": {
      "colorScheme": "dark",
      "logo": "https://firecrawl.dev/logo.svg",
      "colors": {
        "primary": "#FF6B35",
        "secondary": "#004E89",
        "accent": "#F77F00",
        "background": "#1A1A1A",
        "textPrimary": "#FFFFFF",
        "textSecondary": "#B0B0B0"
      },
      "fonts": [
        {
          "family": "Inter"
        },
        {
          "family": "Roboto Mono"
        }
      ],
      "typography": {
        "fontFamilies": {
          "primary": "Inter",
          "heading": "Inter",
          "code": "Roboto Mono"
        },
        "fontSizes": {
          "h1": "48px",
          "h2": "36px",
          "h3": "24px",
          "body": "16px"
        },
        "fontWeights": {
          "regular": 400,
          "medium": 500,
          "bold": 700
        }
      },
      "spacing": {
        "baseUnit": 8,
        "borderRadius": "8px"
      },
      "components": {
        "buttonPrimary": {
          "background": "#FF6B35",
          "textColor": "#FFFFFF",
          "borderRadius": "8px"
        },
        "buttonSecondary": {
          "background": "transparent",
          "textColor": "#FF6B35",
          "borderColor": "#FF6B35",
          "borderRadius": "8px"
        }
      },
      "images": {
        "logo": "https://firecrawl.dev/logo.svg",
        "favicon": "https://firecrawl.dev/favicon.ico",
        "ogImage": "https://firecrawl.dev/og-image.png"
      }
    }
  }
}
```

### Branding Profile Structure

The `branding` object contains the following properties:

* `colorScheme`: The detected color scheme (`"light"` or `"dark"`)
* `logo`: URL of the primary logo
* `colors`: Object containing brand colors:
  * `primary`, `secondary`, `accent`: Main brand colors
  * `background`, `textPrimary`, `textSecondary`: UI colors
  * `link`, `success`, `warning`, `error`: Semantic colors
* `fonts`: Array of font families used on the page
* `typography`: Detailed typography information:
  * `fontFamilies`: Primary, heading, and code font families
  * `fontSizes`: Size definitions for headings and body text
  * `fontWeights`: Weight definitions (light, regular, medium, bold)
  * `lineHeights`: Line height values for different text types
* `spacing`: Spacing and layout information:
  * `baseUnit`: Base spacing unit in pixels
  * `borderRadius`: Default border radius
  * `padding`, `margins`: Spacing values
* `components`: UI component styles:
  * `buttonPrimary`, `buttonSecondary`: Button styles
  * `input`: Input field styles
* `icons`: Icon style information
* `images`: Brand images (logo, favicon, og:image)
* `animations`: Animation and transition settings
* `layout`: Layout configuration (grid, header/footer heights)
* `personality`: Brand personality traits (tone, energy, target audience)

### Combining with other formats

You can combine the branding format with other formats to get comprehensive page data:

```python Python theme={null}
from firecrawl import Firecrawl

firecrawl = Firecrawl(
  # No API key needed to get started — add one for higher rate limits:
  # api_key='fc-YOUR_API_KEY',
)

result = firecrawl.scrape(
    url='https://firecrawl.dev',
    formats=['markdown', 'branding', 'screenshot']
)

print(result['markdown'])
print(result['branding'])
print(result['screenshot'])
```

```js Node theme={null}
import { Firecrawl } from 'firecrawl';

const firecrawl = new Firecrawl({
  // No API key needed to get started — add one for higher rate limits:
  // apiKey: "fc-YOUR-API-KEY",
});

const result = await firecrawl.scrape('https://firecrawl.dev', {
    formats: ['markdown', 'branding', 'screenshot']
});

console.log(result.markdown);
console.log(result.branding);
console.log(result.screenshot);
```

```bash cURL theme={null}
# No API key needed to get started — add -H "Authorization: Bearer $FIRECRAWL_API_KEY" for higher rate limits:
curl -s -X POST "https://api.firecrawl.dev/v2/scrape" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://firecrawl.dev",
    "formats": ["markdown", "branding", "screenshot"]
  }'
```

## Extract product data

The `product` format extracts a structured product **deterministically** — the same kind of structured output as the [`json` format](#extract-structured-data), but without an LLM call or a schema you define, purpose-built for product pages. If you've been pulling product fields with a `json` schema, use `formats: ["product"]` instead — it's faster and cheaper, just limited to products.

It returns a `product` object with title, brand, category, description, and variants — where each variant carries price, original price, availability, and images — useful for price monitoring, catalog ingestion, or comparison-shopping tools.

### /scrape (with product) endpoint

```python Python theme={null}
from firecrawl import Firecrawl

firecrawl = Firecrawl(
  # No API key needed to get started — add one for higher rate limits:
  # api_key='fc-YOUR_API_KEY',
)

result = firecrawl.scrape(
    url='https://example.com/products/wireless-headphones',
    formats=['product']
)

print(result['product'])
```

```js Node theme={null}
import { Firecrawl } from 'firecrawl';

const firecrawl = new Firecrawl({
  // No API key needed to get started — add one for higher rate limits:
  // apiKey: "fc-YOUR-API-KEY",
});

const result = await firecrawl.scrape('https://example.com/products/wireless-headphones', {
    formats: ['product']
});

console.log(result.product);
```

```bash cURL theme={null}
# No API key needed to get started — add -H "Authorization: Bearer $FIRECRAWL_API_KEY" for higher rate limits:
curl -s -X POST "https://api.firecrawl.dev/v2/scrape" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/products/wireless-headphones",
    "formats": ["product"]
  }'
```

### Response

The product format returns a `product` object with the following structure:

```json Output theme={null}
{
  "success": true,
  "data": {
    "product": {
      "title": "Wireless Noise-Cancelling Headphones",
      "brand": "Acme",
      "category": "Electronics > Audio > Headphones",
      "url": "https://example.com/products/wireless-headphones",
      "description": "Over-ear wireless headphones with active noise cancellation, 30-hour battery life, and plush memory-foam ear cushions for all-day comfort.",
      "variants": [
        {
          "id": "wireless-headphones-black",
          "sku": "ACME-WH-BLACK",
          "title": "Wireless Noise-Cancelling Headphones — Black",
          "values": {
            "color": "Black"
          },
          "price": {
            "amount": 199.99,
            "currency": "USD",
            "formatted": "$199.99"
          },
          "sale": {
            "originalPrice": {
              "amount": 249.99,
              "currency": "USD",
              "formatted": "$249.99"
            }
          },
          "availability": {
            "inStock": true,
            "text": "In Stock"
          },
          "images": [
            {
              "url": "https://example.com/images/headphones-black.jpg",
              "alt": "Wireless Noise-Cancelling Headphones — Black"
            }
          ]
        }
      ]
    }
  }
}
```

### Product object structure

The `product` object contains the following properties:

* `title`: The product name
* `brand`: The product brand (optional)
* `category`: The product category (optional)
* `url`: The canonical URL of the product
* `description`: The product description (optional)
* `variants`: Array of product variants. Pricing, availability, and images live on each variant — a single-SKU product still returns exactly one variant carrying these. Each variant has:
  * `id`, `sku`, `title`: variant identifiers and label (all optional)
  * `values`: a map of option name to value, e.g. `{ "color": "Charcoal" }` (optional)
  * `price`: the current price object (optional):
    * `amount`: The numeric price value
    * `currency`: The currency code, reported only when the page sources it (optional)
    * `formatted`: The price as displayed on the page (optional)
  * `sale`: present only when the variant is discounted (optional). Contains:
    * `originalPrice`: The original (pre-discount) price, same shape as `price`
  * `availability`: availability information, always present on a variant:
    * `inStock`: Whether the variant is in stock
    * `text`: The raw availability text from the page (optional)
  * `images`: array of variant images, each with a `url` and optional `alt` text (optional)

### How product extraction works

The product format extracts the product deterministically from on-page structured data — no LLM is involved. It merges multiple sources by priority: **JSON-LD > schema.org microdata > RDFa > embedded state (`__NEXT_DATA__`/Nuxt/Apollo/Redux/Remix) > AliExpress `runParams` > GA4 `dataLayer` > OpenGraph/`<meta>`**. The merge is identity-aware, so fields from different products are never combined. Currency is reported only when the page sources it.

> [!NOTE]
>
> Product extraction is fail-closed: ambiguous pages yield no product, and weaker sources such as OpenGraph only contribute when a price is present. On a page with no extractable product, the response omits the `product` object and adds a `warning` (e.g. "No product found...").

> [!NOTE]
>
> **Self-hosting:** the `product` format is backed by a dedicated product-extraction service. On Firecrawl Cloud it works out of the box. If you self-host, set `PRODUCT_EXTRACTION_SERVICE_URL` to point at that service — when it is unset, requesting the `product` format returns a warning and no product (the same pattern the audio/video formats use for their service).

### Combining with other formats

You can combine the product format with other formats to get comprehensive page data:

```python Python theme={null}
from firecrawl import Firecrawl

firecrawl = Firecrawl(
  # No API key needed to get started — add one for higher rate limits:
  # api_key='fc-YOUR_API_KEY',
)

result = firecrawl.scrape(
    url='https://example.com/products/wireless-headphones',
    formats=['markdown', 'product']
)

print(result['markdown'])
print(result['product'])
```

```js Node theme={null}
import { Firecrawl } from 'firecrawl';

const firecrawl = new Firecrawl({
  // No API key needed to get started — add one for higher rate limits:
  // apiKey: "fc-YOUR-API-KEY",
});

const result = await firecrawl.scrape('https://example.com/products/wireless-headphones', {
    formats: ['markdown', 'product']
});

console.log(result.markdown);
console.log(result.product);
```

```bash cURL theme={null}
# No API key needed to get started — add -H "Authorization: Bearer $FIRECRAWL_API_KEY" for higher rate limits:
curl -s -X POST "https://api.firecrawl.dev/v2/scrape" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/products/wireless-headphones",
    "formats": ["markdown", "product"]
  }'
```

## Audio extraction

The `audio` format extracts audio from supported websites (e.g. YouTube) as MP3 files and returns a signed Google Cloud Storage URL. This is useful for building audio processing pipelines, transcription services, or podcast tools.

> [!NOTE]
>
> Audio extraction costs 5 credits per page (1 base + 4 additional).

```python Python theme={null}
from firecrawl import Firecrawl

firecrawl = Firecrawl(
  # No API key needed to get started — add one for higher rate limits:
  # api_key="fc-YOUR-API-KEY",
)

doc = firecrawl.scrape("https://www.youtube.com/watch?v=dQw4w9WgXcQ", formats=["audio"])
print(doc.audio)  # Signed GCS URL to the MP3 file
```

```js Node theme={null}
import { Firecrawl } from 'firecrawl';

const firecrawl = new Firecrawl({
  // No API key needed to get started — add one for higher rate limits:
  // apiKey: "fc-YOUR-API-KEY",
});

const doc = await firecrawl.scrape('https://www.youtube.com/watch?v=dQw4w9WgXcQ', {
  formats: ['audio']
});

console.log(doc.audio); // Signed GCS URL to the MP3 file
```

```bash cURL theme={null}
# No API key needed to get started — add -H "Authorization: Bearer $FIRECRAWL_API_KEY" for higher rate limits:
curl -s -X POST "https://api.firecrawl.dev/v2/scrape" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "formats": ["audio"]
  }'
```

## Video extraction

The `video` format extracts best-quality video from supported websites (e.g. YouTube) and returns a signed Google Cloud Storage URL. This is useful for building video processing pipelines, moderation tools, or media archiving workflows.

> [!NOTE]
>
> Video extraction costs 5 credits per page (1 base + 4 additional).

```python Python theme={null}
from firecrawl import Firecrawl

firecrawl = Firecrawl(
  # No API key needed to get started — add one for higher rate limits:
  # api_key="fc-YOUR-API-KEY",
)

doc = firecrawl.scrape("https://www.youtube.com/watch?v=dQw4w9WgXcQ", formats=["video"])
print(doc.video)  # Signed GCS URL to the video file
```

```js Node theme={null}
import { Firecrawl } from 'firecrawl';

const firecrawl = new Firecrawl({
  // No API key needed to get started — add one for higher rate limits:
  // apiKey: "fc-YOUR-API-KEY",
});

const doc = await firecrawl.scrape('https://www.youtube.com/watch?v=dQw4w9WgXcQ', {
  formats: ['video']
});

console.log(doc.video); // Signed GCS URL to the video file
```

```bash cURL theme={null}
# No API key needed to get started — add -H "Authorization: Bearer $FIRECRAWL_API_KEY" for higher rate limits:
curl -s -X POST "https://api.firecrawl.dev/v2/scrape" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "formats": ["video"]
  }'
```

## Question format

Use the `question` format to ask a natural-language question about the page. Firecrawl returns the answer in the response's `answer` field.

> [!NOTE]
>
> The `question` format costs 5 credits per page (1 base + 4 additional for the LLM call).

Options inside the format object:

* `question` (required for `type: "question"`): the question to answer. Maximum 10,000 characters.

You can combine `question` with other formats — for example, request `markdown` and `question` together to get page content and an answer in a single call.

```python Python theme={null}
from firecrawl import Firecrawl

firecrawl = Firecrawl(
  # No API key needed to get started — add one for higher rate limits:
  # api_key="fc-YOUR-API-KEY",
)

doc = firecrawl.scrape(
    "https://firecrawl.dev",
    formats=[{"type": "question", "question": "What is Firecrawl?"}],
)
print(doc.answer)
```

```js Node theme={null}
import { Firecrawl } from 'firecrawl';

const firecrawl = new Firecrawl({
  // No API key needed to get started — add one for higher rate limits:
  // apiKey: "fc-YOUR-API-KEY",
});

const doc = await firecrawl.scrape('https://firecrawl.dev', {
  formats: [{ type: 'question', question: 'What is Firecrawl?' }],
});

console.log(doc.answer);
```

```bash cURL theme={null}
# No API key needed to get started — add -H "Authorization: Bearer $FIRECRAWL_API_KEY" for higher rate limits:
curl -s -X POST "https://api.firecrawl.dev/v2/scrape" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://firecrawl.dev",
    "formats": [
      { "type": "question", "question": "What is Firecrawl?" }
    ]
  }'
```

The `question` format is also available in `/search` via `scrapeOptions`, which runs the same extraction across each search result.

## Highlights format

Use the `highlights` format to find relevant source text from the page. Firecrawl returns the selected text in the response's `highlights` field.

> [!NOTE]
>
> The `highlights` format costs 5 credits per page (1 base + 4 additional for the LLM call).

Options inside the format object:

* `query` (required for `type: "highlights"`): the source-text selection request. Maximum 10,000 characters.

You can combine `highlights` with other formats — for example, request `markdown` and `highlights` together to get page content and source text in a single call.

```python Python theme={null}
from firecrawl import Firecrawl

firecrawl = Firecrawl(
  # No API key needed to get started — add one for higher rate limits:
  # api_key="fc-YOUR-API-KEY",
)

doc = firecrawl.scrape(
    "https://firecrawl.dev",
    formats=[{"type": "highlights", "query": "What is Firecrawl?"}],
)
print(doc.highlights)
```

```js Node theme={null}
import { Firecrawl } from 'firecrawl';

const firecrawl = new Firecrawl({
  // No API key needed to get started — add one for higher rate limits:
  // apiKey: "fc-YOUR-API-KEY",
});

const doc = await firecrawl.scrape('https://firecrawl.dev', {
  formats: [{ type: 'highlights', query: 'What is Firecrawl?' }],
});

console.log(doc.highlights);
```

```bash cURL theme={null}
# No API key needed to get started — add -H "Authorization: Bearer $FIRECRAWL_API_KEY" for higher rate limits:
curl -s -X POST "https://api.firecrawl.dev/v2/scrape" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://firecrawl.dev",
    "formats": [
      { "type": "highlights", "query": "What is Firecrawl?" }
    ]
  }'
```

The `highlights` format is also available in `/search` via `scrapeOptions`, which runs the same extraction across each search result.

## PII redaction

Set `redactPII: true` to redact personally identifiable information from returned markdown. The `markdown` field contains the redacted result.

See [PII Redaction](https://docs.firecrawl.dev/features/pii-redaction.md) for SDK, cURL, CLI, and MCP examples.

## Interacting with the page with Actions

Firecrawl allows you to perform various actions on a web page before scraping its content. This is particularly useful for interacting with dynamic content, navigating through pages, or accessing content that requires user interaction.

> [!TIP]
>
> **We recommend [Interact](https://docs.firecrawl.dev/features/interact.md) over actions: our newer, more powerful way to interact with scraped pages.**
>
> Interact runs as a stateful browser session that stays alive across calls, so you can drive a page turn-by-turn with either:
>
> * **Natural language** for flexible, non-deterministic flows. e.g. *“search for ‘wireless headphones’, filter to 4+ stars under \$200, and return the results”*.
> * **Playwright or agent-browser code** for deterministic steps. e.g. `await page.click('#export')`.
>
> Interact also supports profiles, persistent sessions, and a live embeddable browser view (with an interactive mode where end users can drive the browser themselves).

Here is an example of how to use actions to navigate to google.com, search for Firecrawl, click on the first result, and take a screenshot.

It is important to almost always use the `wait` action before/after executing other actions to give enough time for the page to load.

### Example

```python Python theme={null}
from firecrawl import Firecrawl

firecrawl = Firecrawl(
  # No API key needed to get started — add one for higher rate limits:
  # api_key="fc-YOUR-API-KEY",
)

doc = firecrawl.scrape(
    url="https://example.com/login",
    formats=["markdown"],
    actions=[
        {"type": "write", "text": "john@example.com"},
        {"type": "press", "key": "Tab"},
        {"type": "write", "text": "secret"},
        {"type": "click", "selector": 'button[type="submit"]'},
        {"type": "wait", "milliseconds": 1500},
        {"type": "screenshot", "full_page": True},
    ],
)

print(doc.markdown, doc.screenshot)
```

```js Node theme={null}
import { Firecrawl } from 'firecrawl';

const firecrawl = new Firecrawl({
  // No API key needed to get started — add one for higher rate limits:
  // apiKey: "fc-YOUR-API-KEY",
});

const doc = await firecrawl.scrape('https://example.com/login', {
  formats: ['markdown'],
  actions: [
    { type: 'write', text: 'john@example.com' },
    { type: 'press', key: 'Tab' },
    { type: 'write', text: 'secret' },
    { type: 'click', selector: 'button[type="submit"]' },
    { type: 'wait', milliseconds: 1500 },
    { type: 'screenshot', fullPage: true },
  ],
});

console.log(doc.markdown, doc.screenshot);
```

```bash cURL theme={null}
# No API key needed to get started — add -H "Authorization: Bearer YOUR_API_KEY" for higher rate limits:
curl -X POST https://api.firecrawl.dev/v2/scrape \
    -H 'Content-Type: application/json' \
    -d '{
      "url": "https://example.com/login",
      "formats": ["markdown"],
      "actions": [
        { "type": "write", "text": "john@example.com" },
        { "type": "press", "key": "Tab" },
        { "type": "write", "text": "secret" },
        { "type": "click", "selector": "button[type=\"submit\"]" },
        { "type": "wait", "milliseconds": 1500 },
        { "type": "screenshot", "fullPage": true },
      ],
  }'
```

### Output

```json JSON theme={null}
{
  "success": true,
  "data": {
    "markdown": "Our first Launch Week is over! [See the recap 🚀](blog/firecrawl-launch-week-1-recap)...",
    "actions": {
      "screenshots": [
        "https://alttmdsdujxrfnakrkyi.supabase.co/storage/v1/object/public/media/screenshot-75ef2d87-31e0-4349-a478-fb432a29e241.png"
      ],
      "scrapes": [
        {
          "url": "https://www.firecrawl.dev/",
          "html": "<html><body><h1>Firecrawl</h1></body></html>"
        }
      ]
    },
    "metadata": {
      "title": "Home - Firecrawl",
      "description": "Firecrawl crawls and converts any website into clean markdown.",
      "language": "en",
      "keywords": "Firecrawl,Markdown,Data,Mendable,Langchain",
      "robots": "follow, index",
      "ogTitle": "Firecrawl",
      "ogDescription": "The API to search, scrape, and interact with the web at scale.",
      "ogUrl": "https://www.firecrawl.dev/",
      "ogImage": "https://www.firecrawl.dev/og.png?123",
      "ogLocaleAlternate": [],
      "ogSiteName": "Firecrawl",
      "sourceURL": "http://google.com",
      "statusCode": 200
    }
  }
}
```

For workflows that require richer browser control after scraping, such as authenticated sessions, multi-step navigation, or a live view of the page, we recommend [Interact](https://docs.firecrawl.dev/features/interact.md) over extending the actions array.

## Location and Language

Specify country and preferred languages to get relevant content based on your target location and language preferences.

### How it works

When you specify the location settings, Firecrawl will use an appropriate proxy if available and emulate the corresponding language and timezone settings. By default, the location is set to 'US' if not specified.

### Usage

To use the location and language settings, include the `location` object in your request body with the following properties:

* `country`: ISO 3166-1 alpha-2 country code (e.g., 'US', 'AU', 'DE', 'JP'). Defaults to 'US'.
* `languages`: An array of preferred languages and locales for the request in order of priority. Defaults to the language of the specified location.

```python Python theme={null}
from firecrawl import Firecrawl

firecrawl = Firecrawl(
  # No API key needed to get started — add one for higher rate limits:
  # api_key="fc-YOUR-API-KEY",
)

doc = firecrawl.scrape('https://example.com',
    formats=['markdown'],
    location={
        'country': 'US',
        'languages': ['en']
    }
)

print(doc)
```

```js Node theme={null}
import { Firecrawl } from 'firecrawl';

const firecrawl = new Firecrawl({
  // No API key needed to get started — add one for higher rate limits:
  // apiKey: "fc-YOUR-API-KEY",
});

const doc = await firecrawl.scrape('https://example.com', {
  formats: ['markdown'],
  location: { country: 'US', languages: ['en'] },
});

console.log(doc.metadata);
```

```bash cURL theme={null}
# No API key needed to get started — add -H "Authorization: Bearer $FIRECRAWL_API_KEY" for higher rate limits:
curl -X POST "https://api.firecrawl.dev/v2/scrape" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "formats": ["markdown"],
    "location": { "country": "US", "languages": ["en"] }
  }'
```

For more details about supported locations, refer to the [Proxies documentation](https://docs.firecrawl.dev/features/proxies.md).

## Caching and maxAge

To make requests faster, Firecrawl serves results from cache by default when a recent copy is available.

* **Default freshness window**: `maxAge = 172800000` ms (2 days). If a cached page is newer than this, it’s returned instantly; otherwise, the page is scraped and then cached.
* **Performance**: This can speed up scrapes by up to 5x when data doesn’t need to be ultra-fresh.
* **Always fetch fresh**: Set `maxAge` to `0`. Note that this bypasses the cache entirely, so every request goes through the full scraping pipeline, meaning that the request will take longer to complete and is more likely to fail. Use a non-zero `maxAge` if freshness on every request is not critical.
* **Avoid storing**: Set `storeInCache` to `false` if you don’t want Firecrawl to cache/store results for this request.
* **Cache-only lookup**: Set `minAge` to perform a cache-only lookup without triggering a fresh scrape. The value is in milliseconds and specifies the minimum age the cached data must be. If no cached data is found, a `404` with error code `SCRAPE_NO_CACHED_DATA` is returned. Set `minAge` to `1` to accept any cached data regardless of age.
* **Change tracking**: Requests that include `changeTracking` bypass the cache, so `maxAge` is ignored.
* **Credits**: Cached results still cost 1 credit per page. Caching improves speed, not credit usage.

Example (force fresh content):

```python Python theme={null}
from firecrawl import Firecrawl
firecrawl = Firecrawl(api_key='fc-YOUR_API_KEY')

doc = firecrawl.scrape(url='https://example.com', max_age=0, formats=['markdown'])
print(doc)
```

```js Node theme={null}
import { Firecrawl } from 'firecrawl';

const firecrawl = new Firecrawl({ apiKey: "fc-YOUR-API-KEY" });

const doc = await firecrawl.scrape('https://example.com', { maxAge: 0, formats: ['markdown'] });
console.log(doc);
```

```bash cURL theme={null}
curl -s -X POST "https://api.firecrawl.dev/v2/scrape" \
  -H "Authorization: Bearer $FIRECRAWL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "maxAge": 0,
    "formats": ["markdown"]
  }'
```

Example (use a 10-minute cache window):

```python Python theme={null}
from firecrawl import Firecrawl
firecrawl = Firecrawl(api_key='fc-YOUR_API_KEY')

doc = firecrawl.scrape(url='https://example.com', max_age=600000, formats=['markdown', 'html'])
print(doc)
```

```js Node theme={null}

const firecrawl = new Firecrawl({ apiKey: "fc-YOUR-API-KEY" });

const doc = await firecrawl.scrape('https://example.com', { maxAge: 600000, formats: ['markdown', 'html'] });
console.log(doc);
```

```bash cURL theme={null}
curl -s -X POST "https://api.firecrawl.dev/v2/scrape" \
  -H "Authorization: Bearer $FIRECRAWL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "maxAge": 600000,
    "formats": ["markdown", "html"]
  }'
```

### Freshness and item status

`maxAge` controls whether Firecrawl may return a cached copy; it does not tell you whether the state represented by a page is current. When freshness matters, use `maxAge: 0` to skip the cache, then inspect the returned content and any redirect or source-specific status signals. A successful response alone is not proof of current state.

See [Verifying Freshness and Liveness](https://docs.firecrawl.dev/developer-guides/usage-guides/verifying-freshness-and-liveness.md) for a checklist and examples.

## Alexandria data tools

Scrape can also run a data tool from [Alexandria](https://docs.firecrawl.dev/features/alexandria.md), the Firecrawl catalogue of third-party data providers. Send an `alexandria` object with `provider`, `capability`, and `options` instead of a `url`. Get these values from [Search](https://docs.firecrawl.dev/features/search.md#alexandria-tools) or [Find Tools](https://docs.firecrawl.dev/features/alexandria.md#find-tools).

```python Python theme={null}
result = firecrawl.scrape(
    alexandria={
        "provider": "particle",
        "capability": "podcasts/episodes/search",
        "options": {"semantic_search": "AI agents", "limit": 2},
    },
)

print(result.alexandria[0].data)
```

```js Node theme={null}
const result = await firecrawl.scrape({
  alexandria: {
    provider: "particle",
    capability: "podcasts/episodes/search",
    options: { semantic_search: "AI agents", limit: 2 },
  },
});

console.log(result.alexandria[0].data);
```

```bash cURL theme={null}
curl -X POST https://api.firecrawl.dev/v2/scrape \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer fc-YOUR_API_KEY" \
  -d '{
    "alexandria": {
      "provider": "particle",
      "capability": "podcasts/episodes/search",
      "options": { "semantic_search": "AI agents", "limit": 2 }
    }
  }'
```

* The response has one item for each call in `data.alexandria`. Each item has `data` or an `error`. Examine each item, because one call can fail when the request succeeds.
* Send an array of up to 10 calls to run them in one request. You cannot use `alexandria` together with `url` or other scrape options.
* Each call costs the price listed on its tool. `data.creditsCost` shows the total.
* To retry, send the same `x-request-id` header with the same body. A completed request replays its result and does not run again. Without this header, a retry is a new charge. This replay applies to `alexandria` calls only. A URL scrape that a third-party data provider serves (for example, a LinkedIn URL) is charged on every request, so a retry pays the full cost of its provider steps again: 30 credits when Apollo is first in your order and has the record.
* Some providers need an org admin to accept their terms first. Then the request fails with [`THIRD_PARTY_DATA_TERMS_REQUIRED`](https://docs.firecrawl.dev/api-reference/errors).

To find tools for the page that you scrape, add `domainTools: true` to an ordinary URL scrape. Matching tools come back in `data.tools`. See [Alexandria](https://docs.firecrawl.dev/features/alexandria.md#pricing-and-access) for pricing and access.

## Provider-routed URLs

Firecrawl doesn't scrape LinkedIn. Instead, a scrape of a LinkedIn person profile (`linkedin.com/in/<handle>`) or company page (`linkedin.com/company/<slug>`) is answered by third-party data providers. Country and mobile subdomains such as `uk.linkedin.com` and `m.linkedin.com` route the same way. The response is an ordinary scrape document: `markdown` holds the provider's record, and [`data.metadata.provider`](#response-metadata-and-status-codes) names the provider that served it. Batch scrape routes these URLs the same way.

* **Setup**: an org admin turns on enrichment and chooses providers, in order, in the dashboard's enrichment settings. Some providers also need their terms accepted first ([`THIRD_PARTY_DATA_TERMS_REQUIRED`](https://docs.firecrawl.dev/api-reference/errors)).
* **First match wins**: providers are tried in the saved order. The first one that returns a record answers the request, and the rest don't run. A provider with no record for the URL passes to the next one. When none has a record, the request fails with `THIRD_PARTY_DATA_NOT_FOUND` (404).
* **Only the page itself**: a profile or company root page is served, not the pages under it. A company's `/company/<slug>/about` page is served as the company record. Other sub-pages such as `/in/<handle>/details/experience` or `/company/<slug>/jobs` fail with `THIRD_PARTY_DATA_UNSUPPORTED_URL` (400).
* **Options that turn routing off**: these URLs can't be served with `actions`, `profile`, `minAge`, `zeroDataRetention`, `lockdown`, `redactPII`, or any format other than `markdown`, `html`, `rawHtml`, `links`, `images`, `json`, `summary`, `question`, `highlights` and `query`. Such a request fails with `THIRD_PARTY_DATA_UNSUPPORTED_OPTION` (400), and `error` names the option. Remove it and send the request again. If your team's policy enforces zero data retention, these URLs can't be served. Page rendering options such as `headers`, `waitFor`, `mobile`, `location`, `proxy`, `includeTags` and `excludeTags` are ignored for these URLs.
* **Billing**: the request costs the sum of the credits its provider steps charged (`metadata.provider.creditsCost`, broken down in `steps`), in place of the 1-credit scrape base. A provider with no record charges nothing, so a request normally costs the price of the provider that matched. Format surcharges such as `json` still apply. Every request is charged, because `x-request-id` doesn't replay URL scrapes. See [Billing](https://docs.firecrawl.dev/billing.md#provider-routed-urls) for prices.

If enrichment is off, or none of the saved providers can serve the URL, the request fails with `THIRD_PARTY_DATA_ENRICHMENT_NOT_ENABLED` (403). See [Errors](https://docs.firecrawl.dev/api-reference/errors.md) for every code.

## Batch scraping multiple URLs

You can now batch scrape multiple URLs at the same time. It takes the starting URLs and optional parameters as arguments. The params argument allows you to specify additional options for the batch scrape job, such as the output formats.

### How it works

It is very similar to how the `/crawl` endpoint works. It submits a batch scrape job and returns a job ID to check the status of the batch scrape.

The sdk provides 2 methods, synchronous and asynchronous. The synchronous method will return the results of the batch scrape job, while the asynchronous method will return a job ID that you can use to check the status of the batch scrape.

### Usage

```python Python theme={null}
from firecrawl import Firecrawl

firecrawl = Firecrawl(api_key="fc-YOUR-API-KEY")

job = firecrawl.batch_scrape([
    "https://firecrawl.dev",
    "https://docs.firecrawl.dev",
], formats=["markdown"], poll_interval=2, wait_timeout=120)

print(job)
```

```js Node theme={null}
import { Firecrawl } from 'firecrawl';

const firecrawl = new Firecrawl({ apiKey: "fc-YOUR-API-KEY" });

const job = await firecrawl.batchScrape([
  'https://firecrawl.dev',
  'https://docs.firecrawl.dev',
], { options: { formats: ['markdown'] }, pollInterval: 2, timeout: 120 });

console.log(job);
```

```bash cURL theme={null}
curl -s -X POST "https://api.firecrawl.dev/v2/batch/scrape" \
  -H "Authorization: Bearer $FIRECRAWL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "urls": ["https://firecrawl.dev", "https://docs.firecrawl.dev"],
    "formats": ["markdown"]
  }'
```

### Response

If you’re using the sync methods from the SDKs, it will return the results of the batch scrape job. Otherwise, it will return a job ID that you can use to check the status of the batch scrape.

#### Synchronous

```json Completed theme={null}
{
  "status": "completed",
  "total": 36,
  "completed": 36,
  "creditsUsed": 36,
  "expiresAt": "2024-00-00T00:00:00.000Z",
  "next": "https://api.firecrawl.dev/v2/batch/scrape/123-456-789?skip=26",
  "data": [
    {
      "markdown": "[Firecrawl Docs home page![light logo](https://mintlify.s3-us-west-1.amazonaws.com/firecrawl/logo/light.svg)!...",
      "html": "<!DOCTYPE html><html lang=\"en\" class=\"js-focus-visible lg:[--scroll-mt:9.5rem]\" data-js-focus-visible=\"\">...",
      "metadata": {
        "title": "Build a 'Chat with website' using Groq Llama 3 | Firecrawl",
        "language": "en",
        "sourceURL": "https://docs.firecrawl.dev/learn/rag-llama3",
        "description": "Learn how to use Firecrawl, Groq Llama 3, and Langchain to build a 'Chat with your website' bot.",
        "ogLocaleAlternate": [],
        "statusCode": 200
      }
    },
    ...
  ]
}
```

#### Asynchronous

You can then use the job ID to check the status of the batch scrape by calling the `/batch/scrape/{id}` endpoint. This endpoint is meant to be used while the job is still running or right after it has completed **as batch scrape jobs expire after 24 hours**.

```json theme={null}
{
  "success": true,
  "id": "123-456-789",
  "url": "https://api.firecrawl.dev/v2/batch/scrape/123-456-789"
}
```

## Enhanced Mode

For complex websites, Firecrawl offers enhanced mode that provides better success rates while maintaining privacy.

Learn more about [Enhanced Mode](https://docs.firecrawl.dev/features/enhanced-mode.md).

## Zero Data Retention (ZDR)

Firecrawl supports Zero Data Retention (ZDR) for teams with strict data handling requirements. When enabled, Firecrawl will not persist any page content or extracted data beyond the lifetime of the request.

To enable ZDR, set `zeroDataRetention: true` in your request:

```bash cURL theme={null}
curl -X POST https://api.firecrawl.dev/v2/scrape \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer fc-YOUR_API_KEY" \
  -d '{
    "url": "https://example.com",
    "formats": ["markdown"],
    "zeroDataRetention": true
  }'
```

ZDR is available on Enterprise plans and must be enabled for your team. Visit [firecrawl.dev/enterprise](https://www.firecrawl.dev/enterprise) to get started.

ZDR adds **1 additional credit per page** on top of the base scrape cost.

> [!NOTE]
>
> Screenshots are not available in ZDR mode. Because screenshots require uploading to persistent storage, they are incompatible with the ZDR guarantee. Requests that include both `zeroDataRetention: true` and a `screenshot` format will return an error.

> Are you an AI agent that needs a Firecrawl API key? See [firecrawl.dev/agent-onboarding/SKILL.md](https://www.firecrawl.dev/agent-onboarding/SKILL.md) for automated onboarding instructions.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.
