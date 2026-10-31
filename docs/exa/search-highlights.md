> Source: https://exa.ai/docs/search/highlights.md
> Retrieved: 2026-10-31
> Covers: contents.highlights on /search and /contents

# Highlights

> Return query-relevant excerpts from Exa Search results while controlling context size and latency.

Highlights return extractive passages from each result that are relevant to your query. Use them when your application needs evidence from the page without the token cost of full text.

Each result returns its selected passages in `results[].highlights`.

## Why highlights instead of full text

Highlights come from Exa's in-house extraction model. The model reads each result against your query on every request and returns only the passages that answer it. You keep a fraction of the tokens of full page text with equal or better downstream answer quality.

| Evaluation | Result |
| - | - |
| Accuracy (SimpleQA) | 500 characters of highlights match the accuracy of the first 8,000 characters of page text, with 16x fewer tokens |
| Quality at larger budgets | 4,000 characters of highlights outscore 32,000 characters of full text |
| Long technical docs | At a 500-character budget, highlights reach 60% accuracy on API references, SDK docs, specs, and papers; full text reaches 6% |
| Search token usage | Highlights cut search tokens by 5x on average |

The savings matter most in agent loops, where every round of search results competes with reasoning traces for context.

> [!TIP]
>
> Read [Exa Highlights: Quality, Token-Efficient Search](https://exa.ai/blog/highlights-for-agents)
> for the methodology and full results.

## Add highlights to Search

Use `highlights: true` inside `contents` as the recommended default. Exa chooses how much text to return from each result based on its relevance to your query, so there is no character budget to tune. Set `maxCharacters` only when your application requires a fixed per-page limit.

```python Python theme={null}
result = exa.search(
    "How are inference providers reducing transformer latency?",
    contents={"highlights": True},
)
```

```javascript JavaScript theme={null}
const result = await exa.search(
  "How are inference providers reducing transformer latency?",
  { contents: { highlights: true } }
);
```

```bash cURL theme={null}
curl -s -X POST "https://api.exa.ai/search" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $EXA_API_KEY" \
  -d '{
    "query": "How are inference providers reducing transformer latency?",
    "contents": {
      "highlights": true
    }
  }'
```

## Dynamic Highlights

Dynamic Highlights adjusts how much text it selects from each result based on what is most useful for your query. It can take more from strong sources and less from repetitive or irrelevant ones, reducing the total tokens returned.

Use it when several results will feed the same agent or context window. Keep regular `highlights: true` when every page needs its own excerpt or a predictable per-page limit.

In Exa's evaluations, Dynamic Highlights cut tokens by an average of 95% compared to full page content. At a 12,000-character budget it beat regular highlights with a 40% average token-efficiency gain and a 3.8% quality increase. Inside Exa Agent, it cut total agent token usage by 30% with a 2.1% average quality gain on benchmarks including BrowseComp and WideSearch.

> [!TIP]
>
> Read [Dynamic Highlights](https://exa.ai/blog/dynamic-highlights) for the evaluation results and
> design behind cross-result highlight selection.

Enable it with `dynamic: true`:

```python Python theme={null}
from exa_py.api import DYNAMIC_HIGHLIGHTS_BETA

result = exa.search(
    "How did US household solar installation costs change over the past five years?",
    contents={
        "highlights": {
            "dynamic": True,
        }
    },
    betas=[DYNAMIC_HIGHLIGHTS_BETA],
)
```

```javascript JavaScript theme={null}
import Exa, { DYNAMIC_HIGHLIGHTS_BETA } from "exa-js";

const result = await exa.search(
  "How did US household solar installation costs change over the past five years?",
  {
    contents: {
      highlights: {
        dynamic: true
      }
    },
    betas: [DYNAMIC_HIGHLIGHTS_BETA]
  }
);
```

```bash cURL theme={null}
curl -s -X POST "https://api.exa.ai/search" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $EXA_API_KEY" \
  -H "Exa-Beta: dynamic-highlights-2026-08-28" \
  -d '{
    "query": "How did US household solar installation costs change over the past five years?",
    "contents": {
      "highlights": {
        "dynamic": true
      }
    }
  }'
```

> [!NOTE]
>
> Dynamic Highlights is a research preview and requires the
> `Exa-Beta: dynamic-highlights-2026-08-28` request header. The SDKs send it when you pass
> `betas=[DYNAMIC_HIGHLIGHTS_BETA]` (Python) or `betas: [DYNAMIC_HIGHLIGHTS_BETA]` (JavaScript).
>
> The response uses the same
> `results[].highlights` shape as regular highlights.

## Next steps

> [card] [Search API guide](https://exa.ai/docs/search/quickstart.md)
>
> Build a Search request and choose the right output shape.

> [card] [Search best practices](https://exa.ai/docs/search/best-practices.md)
>
> Tune retrieval quality, latency, freshness, and context size.
