"""Markdown formatters for results + scraped content sections."""

SOURCE_ICONS = {
    "brave": "🔍",
    "tavily": "🌐",
    "exa": "✨",
    "firecrawl": "🔥",
    "github-repos": "📦",
    "serpapi": "🔎",
    "hackernews": "🟠",
    "stackoverflow": "🏆",
    "twitter": "🐦",
}

_SUMMARY_SKIP_PREFIXES = (
    "Title:", "URL Source:", "Published Time:", "Markdown Content:",
    "[", "!", "#", "|", "*", "-", "Skip", "We use", "Cookie",
    "Subscribe", "Get Started", "Support", "Overview", "Navigation",
)


def format_scrapes(scrapes: list, max_chars: int = 2000) -> str:
    """Format scraped pages as markdown sections, with a key-findings summary table up front."""
    if not scrapes:
        return ""

    summary_rows = []
    for i, s in enumerate(scrapes, 1):
        if s.get("error"):
            summary_rows.append(f"| {i} | ⚠️ error | {s['url'][:80]} | {s['error'][:80]} |")
        else:
            title = (s.get("title") or s["url"])[:60].replace("|", "｜")
            via = s.get("via", "?")
            first_line = ""
            for line in (s.get("markdown") or "").splitlines():
                line = line.strip()
                if (len(line) > 50
                        and not line.startswith(_SUMMARY_SKIP_PREFIXES)
                        and " | " not in line
                        and not line.endswith(":")):
                    first_line = line[:120]
                    break
            summary_rows.append(f"| {i} | {title} | {via} | {first_line} |")

    table = (
        "| # | 标题 | 来源 | 摘要 |\n"
        "|---|------|------|------|\n"
        + "\n".join(summary_rows)
    )

    lines = ["\n---\n\n## 🔥 Scraped Content\n", "### 📋 关键信息速览\n", table, "\n---\n"]

    for i, s in enumerate(scrapes, 1):
        via = s.get("via", "")
        via_label = f" _(via {via})_" if via else ""
        if s.get("error"):
            lines.append(f"### {i}. ⚠️ {s['url']}\n\n> Scrape error: {s['error']}\n")
            continue
        title = s.get("title") or s["url"]
        md = s.get("markdown", "")
        truncated = md[:max_chars]
        suffix = f"\n\n_...truncated ({s['length']} chars total)_" if len(md) > max_chars else ""
        lines.append(f"### {i}. [{title}]({s['url']}){via_label}\n\n{truncated}{suffix}\n")
    return "\n".join(lines)


def format_results(results: list, query: str, raw_counts: dict | None = None,
                   brief: bool = False) -> str:
    """Format aggregated results for display."""
    lines = [f"## Search Results: `{query}`\n"]
    tavily_answers = [r for r in results if r.get("source") == "tavily_answer"]
    exa_answers = [r for r in results if r.get("source") == "exa_answer"]
    serpapi_answers = [r for r in results if r.get("source") == "serpapi_answer"]
    results = [r for r in results if r.get("source") not in ("tavily_answer", "serpapi_answer", "exa_answer")]
    if tavily_answers:
        lines.append(f"\n> **Tavily AI Answer:** {tavily_answers[0]['answer']}\n")
    if exa_answers:
        lines.append(f"\n> **Exa AI Answer:** {exa_answers[0]['answer']}\n")
    if serpapi_answers:
        lines.append(f"\n> **Google Knowledge Graph:** {serpapi_answers[0]['answer']}\n")

    if raw_counts is None:
        source_counts: dict = {}
        for item in results:
            if "error" in item:
                continue
            src = item.get("source", "?")
            source_counts[src] = source_counts.get(src, 0) + 1
    else:
        source_counts = raw_counts

    summary_parts = [
        f"{SOURCE_ICONS.get(s, '•')} **{s}**: {n}" for s, n in source_counts.items()
    ]
    lines.append("**Sources (raw hits):** " + " | ".join(summary_parts))

    def _weight(item):
        if "error" in item:
            return -1
        return 1 + len(item.get("also_from") or [])

    results = sorted(results, key=_weight, reverse=True)

    valid = [r for r in results if "error" not in r]
    consensus_count = sum(1 for r in valid if _weight(r) >= 2)
    max_weight = max((_weight(r) for r in valid), default=0)
    if valid:
        lines.append(
            f"**Consensus:** {len(valid)} unique URLs, {consensus_count} "
            f"matched by 2+ sources (top weight: ×{max_weight})\n"
        )
    else:
        lines.append("")

    for i, item in enumerate(results, 1):
        if "error" in item:
            lines.append(f"{i}. ⚠️ [{item['source']} error] {item['error']}")
            continue
        src = item.get("source", "?")
        icon = SOURCE_ICONS.get(src, "•")
        title = item.get("title", "(no title)")
        url = item.get("url", "")
        desc = item.get("description", "")
        stars = item.get("stars")
        stars_str = f" ⭐{stars}" if stars else ""
        also = item.get("also_from") or []
        weight = 1 + len(also)
        if weight >= 3:
            weight_prefix = f"**【×{weight}】** "
        elif weight == 2:
            weight_prefix = "**【×2】** "
        else:
            weight_prefix = "【 1 】 "
        also_str = f"  _from: {src}" + (f", {', '.join(also)}" if also else "") + "_"
        lines.append(f"{i}. {weight_prefix}{icon} **[{title}]({url})**{stars_str}{also_str}")
        if desc and not brief:
            short = desc[:200].replace("\n", " ")
            if len(desc) > 200:
                short += "..."
            lines.append(f"   {short}")
        lines.append("")

    return "\n".join(lines)
