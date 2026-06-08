#!/usr/bin/env python3
"""测试各搜索源的实际返回条数上限和稳定性。运行 2 轮，对比结果。

WARNING: manual diagnostics only. This script calls live APIs and consumes real
provider quota/credits.
"""

import sys
import time
from pathlib import Path

# 导入 search.py 里的函数
sys.path.insert(0, str(Path(__file__).parent))
from search import (
    load_keys,
    search_brave,
    search_tavily,
    search_exa,
    search_firecrawl,
    search_serpapi,
    search_github_repos,
)
from scripts.keys import pick_key

QUERY = "python async programming"
PROBE_COUNTS = {
    "brave": 20,
    "tavily": 20,
    "exa": 50,
    "firecrawl": 10,
    "serpapi": 50,
    "github": 50,
}

keys = load_keys()

def test_source(name, fn, *args, rounds=2, pause=1):
    """运行 N 次，返回 (每轮结果数, errors)。"""
    results = []
    errors = []
    for i in range(rounds):
        try:
            t0 = time.time()
            r = fn(*args)
            elapsed = time.time() - t0
            ok = [x for x in r if "error" not in x]
            err = [x for x in r if "error" in x]
            results.append(len(ok))
            if err:
                errors.append(f"Round{i+1}: {err[0]['error'][:80]}")
            print(f"  [{name}] Round {i+1}: {len(ok)} results ({elapsed:.1f}s)")
        except Exception as e:
            results.append(0)
            errors.append(f"Round{i+1}: {e}")
            print(f"  [{name}] Round {i+1}: ERROR - {e}")
        if i < rounds - 1:
            time.sleep(pause)  # 避免过快触发限流
    return results, errors

print(f"\n=== 搜索源上限测试 (query='{QUERY}') ===\n")

report = []

# Brave
brave_key = pick_key(keys.get("brave"))
if brave_key:
    print("🔍 Brave Search (free tier: 1,000/mo, API count max=20)")
    r, e = test_source("brave", search_brave, QUERY, brave_key, PROBE_COUNTS["brave"])
    report.append({"source": "brave", "r1": r[0], "r2": r[1] if len(r)>1 else "?", "errors": e, "api_limit": "20/req"})
else:
    print("🔍 Brave: NO KEY")

print()

# Tavily
tvly_key = pick_key(keys.get("tavily"))
if tvly_key:
    print("🌐 Tavily (free tier: 1000/mo, max_results)")
    r, e = test_source("tavily", search_tavily, QUERY, tvly_key, PROBE_COUNTS["tavily"])
    report.append({"source": "tavily", "r1": r[0], "r2": r[1] if len(r)>1 else "?", "errors": e, "api_limit": "20/req"})
else:
    print("🌐 Tavily: NO KEY")

print()

# Exa
exa_key = pick_key(keys.get("exa"))
if exa_key:
    print("✨ Exa (free tier: 1000/mo)")
    r, e = test_source("exa", search_exa, QUERY, exa_key, PROBE_COUNTS["exa"])
    report.append({"source": "exa", "r1": r[0], "r2": r[1] if len(r)>1 else "?", "errors": e, "api_limit": "100/req"})
else:
    print("✨ Exa: NO KEY")

print()

# Firecrawl
firecrawl_key = pick_key(keys.get("firecrawl"))
if firecrawl_key:
    print("🔥 Firecrawl (metadata search only in this skill)")
    r, e = test_source("firecrawl", search_firecrawl, QUERY, firecrawl_key, PROBE_COUNTS["firecrawl"])
    report.append({"source": "firecrawl", "r1": r[0], "r2": r[1] if len(r)>1 else "?", "errors": e, "api_limit": "local 10"})
else:
    print("🔥 Firecrawl: NO KEY")

print()

# SerpAPI (careful - limited free quota)
serpapi_key = pick_key(keys.get("serpapi"))
if serpapi_key:
    print("🔎 SerpAPI (free tier: 250/mo — only testing ONCE to save quota)")
    r, e = test_source("serpapi", search_serpapi, QUERY, serpapi_key, PROBE_COUNTS["serpapi"], rounds=1)
    report.append({"source": "serpapi", "r1": r[0], "r2": "skipped(quota)", "errors": e, "api_limit": "10/page+start"})
else:
    print("🔎 SerpAPI: NO KEY")

print()

# GitHub repos
github_key = pick_key(keys.get("github"))
print("📦 GitHub repos (with token)" if github_key else "📦 GitHub repos (no token, gh CLI fallback)")
r, e = test_source("github-repos", search_github_repos, QUERY, PROBE_COUNTS["github"], github_key)
report.append({"source": "github-repos", "r1": r[0], "r2": r[1] if len(r)>1 else "?", "errors": e, "api_limit": "100/page"})

print()

# ====== Summary ======
print("\n" + "="*60)
print("📊 汇总报告")
print("="*60)
print(f"{'Source':<16} {'实际 R1':>6} {'实际 R2':>8} {'API声明上限':>12} {'是否稳定':>8}")
print("-"*60)
for row in report:
    stable = "✅" if str(row["r1"]) == str(row["r2"]) else "⚠️ 差异"
    print(f"{row['source']:<16} {str(row['r1']):>6} {str(row['r2']):>8} {row['api_limit']:>12} {stable:>8}")
    if row["errors"]:
        for e in row["errors"]:
            print(f"  ⚠️  {e}")

print()
print("提示：R1=第1次，R2=第2次（SerpAPI 只测1次保配额）")
