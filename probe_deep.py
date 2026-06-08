#!/usr/bin/env python3
"""深入探测 Brave/SerpAPI/Tavily 的实际返回上限。

WARNING: manual diagnostics only. This script calls live APIs and consumes real
provider quota/credits.
"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from search import load_keys, search_brave, search_serpapi, search_tavily
from scripts.keys import pick_key

keys = load_keys()
brave_key = pick_key(keys.get("brave"))
tavily_key = pick_key(keys.get("tavily"))
serpapi_key = pick_key(keys.get("serpapi"))

def show(label, results):
    ok = [x for x in results if "error" not in x]
    err = [x for x in results if "error" in x]
    msg = f"{len(ok)} results"
    if err:
        msg += f"  ERROR: {err[0]['error'][:100]}"
    print(f"  {label}: {msg}")

# Brave: count=10, 15, 20 (API 文档 max=20)
print("=== Brave ===")
if brave_key:
    for n in [10, 15, 20]:
        r = search_brave("python async programming", brave_key, n)
        show(f"count={n}", r)
        time.sleep(0.5)
else:
    print("  NO KEY")

# SerpAPI: count=10, 20, 50
print("\n=== SerpAPI (careful with quota) ===")
if serpapi_key:
    for n in [10, 20, 50]:
        r = search_serpapi("python async programming", serpapi_key, n)
        show(f"count={n}", r)
        time.sleep(2)
else:
    print("  NO KEY")

# Tavily: count=10, 20 各跑 3 次
print("\n=== Tavily (3 rounds each) ===")
if tavily_key:
    for n in [10, 20]:
        counts = []
        for _ in range(3):
            r = search_tavily("python async programming", tavily_key, n)
            ok = [x for x in r if "error" not in x]
            counts.append(len(ok))
            time.sleep(0.8)
        print(f"  max_results={n}: {counts}  (min={min(counts)}, max={max(counts)})")
else:
    print("  NO KEY")
