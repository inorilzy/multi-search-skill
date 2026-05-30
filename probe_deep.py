#!/usr/bin/env python3
"""深入探测 Brave/SerpAPI/Tavily 的实际返回上限。"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from search import load_keys, search_brave, search_serpapi, search_tavily

keys = load_keys()

def show(label, results):
    ok = [x for x in results if "error" not in x]
    err = [x for x in results if "error" in x]
    msg = f"{len(ok)} results"
    if err:
        msg += f"  ERROR: {err[0]['error'][:100]}"
    print(f"  {label}: {msg}")

# Brave: count=10, 15, 20 (API 文档 max=20)
print("=== Brave ===")
for n in [10, 15, 20]:
    r = search_brave("python async programming", keys["brave"], n)
    show(f"count={n}", r)
    time.sleep(0.5)

# SerpAPI: count=10, 20, 50
print("\n=== SerpAPI (careful with quota) ===")
for n in [10, 20, 50]:
    r = search_serpapi("python async programming", keys["serpapi"], n)
    show(f"count={n}", r)
    time.sleep(2)

# Tavily: count=5, 10, 20, 30 各跑 2 次
print("\n=== Tavily (3 rounds each) ===")
for n in [10, 20]:
    counts = []
    for _ in range(3):
        r = search_tavily("python async programming", keys["tavily"], n)
        ok = [x for x in r if "error" not in x]
        counts.append(len(ok))
        time.sleep(0.8)
    print(f"  max_results={n}: {counts}  (min={min(counts)}, max={max(counts)})")
