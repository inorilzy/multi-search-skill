import search

keys = search.load_keys()
q = "python fastapi tutorial"

def show(name, results, fields):
    print(f"=== {name} ({len(results)} results) ===")
    for x in results[:3]:
        url = (x.get("url") or "")[:70]
        sc = ""
        used = None
        for f in fields:
            v = x.get(f) or ""
            if v and len(v) > len(sc):
                sc, used = v, f
        print(f"  URL: {url}")
        print(f"    field={used}  len={len(sc)}")
        print(f"    preview: {sc[:220]!r}")
    print()

show("Tavily", search.search_tavily(q, keys.get("tavily", ""), max_results=3),
     ["scraped_content", "raw_content", "content"])
show("Exa", search.search_exa(q, keys.get("exa", ""), count=3),
     ["scraped_content", "text", "summary", "content"])
show("Firecrawl", search.search_firecrawl(q, keys.get("firecrawl", ""), count=3),
     ["scraped_content", "markdown", "description"])
