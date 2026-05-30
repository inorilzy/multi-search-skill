#!/usr/bin/env python3
"""测试各搜索源的实际返回条数上限和稳定性。运行 2 轮，对比结果。"""

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
    search_serpapi,
    search_github_repos,
    search_hackernews,
    search_stackoverflow,
)

QUERY = "python async programming"
TEST_COUNT = 50  # 请求这么多，看能返回多少

keys = load_keys()

def test_source(name, fn, *args):
    """运行 2 次，返回 (round1_count, round2_count, errors)"""
    results = []
    errors = []
    for i in range(2):
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
        if i == 0:
            time.sleep(1)  # 避免过快触发限流
    return results, errors

print(f"\n=== 搜索源上限测试 (query='{QUERY}', count={TEST_COUNT}) ===\n")

report = []

# Brave
if "brave" in keys:
    print("🔍 Brave Search (free tier: 2000/mo, API count max=20)")
    r, e = test_source("brave", search_brave, QUERY, keys["brave"], TEST_COUNT)
    report.append({"source": "brave", "r1": r[0], "r2": r[1] if len(r)>1 else "?", "errors": e, "api_limit": "20/req"})
else:
    print("🔍 Brave: NO KEY")

print()

# Tavily
if "tavily" in keys:
    print("🌐 Tavily (free tier: 1000/mo, max_results)")
    r, e = test_source("tavily", search_tavily, QUERY, keys["tavily"], TEST_COUNT)
    report.append({"source": "tavily", "r1": r[0], "r2": r[1] if len(r)>1 else "?", "errors": e, "api_limit": "~20/req"})
else:
    print("🌐 Tavily: NO KEY")

print()

# Exa
if "exa" in keys:
    print("✨ Exa (free tier: 1000/mo)")
    r, e = test_source("exa", search_exa, QUERY, keys["exa"], TEST_COUNT)
    report.append({"source": "exa", "r1": r[0], "r2": r[1] if len(r)>1 else "?", "errors": e, "api_limit": "?"})
else:
    print("✨ Exa: NO KEY")

print()

# SerpAPI (careful - limited free quota)
if "serpapi" in keys:
    print("🔎 SerpAPI (free tier: 100/mo — only testing ONCE to save quota)")
    r, e = test_source("serpapi", search_serpapi, QUERY, keys["serpapi"], TEST_COUNT)
    report.append({"source": "serpapi", "r1": r[0], "r2": "skipped(quota)", "errors": e, "api_limit": "~10/req"})
else:
    print("🔎 SerpAPI: NO KEY")

print()

# GitHub repos
print("📦 GitHub repos (with token)" if "github" in keys else "📦 GitHub repos (no token, gh CLI fallback)")
r, e = test_source("github_repos", search_github_repos, QUERY, TEST_COUNT, keys.get("github", ""))
report.append({"source": "github_repos", "r1": r[0], "r2": r[1] if len(r)>1 else "?", "errors": e, "api_limit": "100/page"})

print()

# HackerNews
print("🟠 HackerNews (free Algolia, no limit)")
r, e = test_source("hackernews", search_hackernews, QUERY, TEST_COUNT)
report.append({"source": "hackernews", "r1": r[0], "r2": r[1] if len(r)>1 else "?", "errors": e, "api_limit": "flexible"})

print()

# StackOverflow
print("🏆 StackOverflow (free Stack Exchange API, pagesize max 100)")
r, e = test_source("stackoverflow", search_stackoverflow, QUERY, TEST_COUNT)
report.append({"source": "stackoverflow", "r1": r[0], "r2": r[1] if len(r)>1 else "?", "errors": e, "api_limit": "100/page"})

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
