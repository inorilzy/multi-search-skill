"""Fixed offline responses through real Core boundaries; an AI chooses every call.

This is a fixture driver, not an agent, scorer, browser, or live-network test.
See docs/source-tracing-validation.md for the independent execution protocol.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.search.query_policy import QueryFusionPolicy
from multi_search_mcp.src.search.resolve import resolve_active_sources, resolve_search_plan
from multi_search_mcp.src.service import (
    MultiSearchRequest,
    SearchWebRequest,
    run_fetch_source,
    run_read_source,
    run_search_web,
)
from multi_search_mcp.src.state.state_store import StateStore
from multi_search_mcp.src.support.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--scenario")
    parser.add_argument("--session", type=Path)
    parser.add_argument("--tool", choices=("search_web", "fetch_source", "read_source"))
    parser.add_argument("--args", default="{}", help="JSON object, or - for stdin")
    parser.add_argument("--config", type=Path, help="Explicit non-secret Core configuration")
    parser.add_argument("--freeze", type=Path, help="Reviewed policy freeze from evaluation")
    parser.add_argument("--review-policy", choices=("human_only", "allow_ai"), default="human_only")
    parser.add_argument("--allow-candidate", action="store_true", help="Run a frozen experiment that has not passed quality acceptance")
    parser.add_argument("--variant-prompt", type=Path, help="Actual frozen variant instruction artifact")
    options = parser.parse_args()
    fixture_path = ROOT / "docs/examples/source-tracing/scenarios.json"
    fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
    if options.list:
        print(json.dumps({key: item["prompt"] for key, item in fixtures.items()}, ensure_ascii=False, indent=2))
        return
    if not options.scenario or not options.session or not options.tool:
        parser.error("--scenario, --session, and --tool are required")
    if options.freeze and (not options.config or not options.variant_prompt):
        parser.error("--freeze requires --config and --variant-prompt")
    fixture = fixtures[options.scenario]
    arguments = json.loads(sys.stdin.read() if options.args == "-" else options.args)
    if options.tool == "search_web":
        arguments.setdefault("sources", ["brave", "exa"])
    config = load_config(str(options.config)) if options.config else {}
    policy = QueryFusionPolicy.from_config(config)
    metadata: dict[str, Any] = {
        "scenario": options.scenario,
        "skill_sha256": hashlib.sha256((ROOT / "skills/multi-search/SKILL.md").read_bytes()).hexdigest(),
        "fixtures_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "prompt": fixture["prompt"],
        "mode": "offline fixed provider/scraper; live Core, AI-directed tool selection",
    }
    if options.config or options.variant_prompt:
        metadata.update(
            config_sha256=hashlib.sha256(options.config.read_bytes()).hexdigest() if options.config else None,
            query_fusion=policy.to_dict(),
            policy_status="experimental_unfrozen",
        )
    if options.variant_prompt:
        metadata["variant_prompt_sha256"] = hashlib.sha256(options.variant_prompt.read_bytes()).hexdigest()
    if options.freeze:
        from multi_search_mcp.src.search.evaluation import validate_freeze

        frozen = json.loads(options.freeze.read_text(encoding="utf-8"))
        versions = dict(frozen.get("versions") or {})
        versions.update(skill_sha256=metadata["skill_sha256"],
                        variant_prompt_sha256=metadata["variant_prompt_sha256"])
        selection = dict(frozen.get("selection") or {})
        selection["query_fusion"] = policy.to_dict()
        validate_freeze(frozen, versions=versions, selection=selection, review_policy=options.review_policy,
                        allow_candidate=options.allow_candidate)
        if options.tool == "search_web":
            if arguments.get("count", frozen["limit"]) != frozen["limit"]:
                raise ValueError("search count differs from the frozen display limit")
            arguments["count"] = frozen["limit"]
            request = SearchWebRequest(**arguments)
            plan = resolve_search_plan(MultiSearchRequest(
                query=request.query, route=request.route, count=request.count,
                sources=request.sources, timeout=request.timeout, scrape_top=0,
                output="json", config_path=request.config_path, use_state=request.use_state,
            ), config)
            _selected, active = resolve_active_sources(plan.route, plan.sources, plan.disabled_sources)
            retrieval_config = {
                "route": plan.route, "active_sources": sorted(active),
                "provider_counts": plan.effective_counts, "timeout": plan.timeout,
                "serpapi_engine": plan.serpapi_engine, "count": request.count,
            }
            if retrieval_config != frozen["retrieval_config"]:
                raise ValueError("resolved retrieval configuration differs from the freeze")
        metadata.update(freeze_id=frozen["freeze_id"],
                        freeze_sha256=hashlib.sha256(options.freeze.read_bytes()).hexdigest(),
                        policy_status="candidate_frozen" if frozen["status"] == "candidate_frozen" else frozen["status"] + "_frozen")
        if frozen["status"] == "candidate_frozen":
            metadata["release_eligible"] = False
    options.session.mkdir(parents=True, exist_ok=True)
    metadata_path = options.session / "metadata.json"
    if metadata_path.exists():
        if json.loads(metadata_path.read_text(encoding="utf-8")) != metadata:
            raise ValueError("session inputs, policy, or freeze changed; use a new session directory")
    else:
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    events: list[dict] = []
    lock = threading.Lock()

    def record(event: dict) -> None:
        with lock:
            events.append({"at_ns": time.perf_counter_ns(), **event})

    def provider(name: str) -> ProviderSpec:
        def call(query, _config, _context, _key):
            record({"boundary": "provider", "provider": name, "query": query, "phase": "start"})
            # A fixed delay makes Core concurrency visible in the trace; it is
            # fixture time, never a measurement of a production provider.
            time.sleep(0.02)
            rows = [{"source": name, "content_kind": "excerpt", **row} for row in fixture["candidates"]]
            record({"boundary": "provider", "provider": name, "query": query, "phase": "end"})
            return rows
        return ProviderSpec(name=name, public_name=name, call=call)

    def scraper(url, **_kwargs):
        page = fixture["pages"].get(url)
        if page is None:
            raise ValueError("fixture has no material at this URL")
        if "error" in page:
            record({"boundary": "scraper", "url": url, "error": page["error"]})
            raise ValueError(page["error"])
        body = page["body"]
        record({"boundary": "scraper", "url": url, "acquired_chars": len(body)})
        return {"url": url, "markdown": body, "via": "offline-fixture"}

    store = StateStore(options.session / "state.sqlite")
    started = time.perf_counter_ns()
    error = None
    result = None
    try:
        if options.tool == "search_web":
            # Fixed public provider names exercise normal fusion and provenance.
            # Any query receives the same candidate set. Query quality is for
            # the human reviewer, never keyword matching in this driver.
            result = run_search_web(
                arguments,
                providers={name: provider(name) for name in ("brave", "exa")},
                keys={}, config=config, state_store=store,
                scraper=scraper, url_resolver=lambda _host: ["127.0.0.1"],
            )
        elif options.tool == "fetch_source":
            result = run_fetch_source(arguments, scraper=scraper, keys={}, config={}, state_store=store, url_resolver=lambda _host: ["93.184.216.34"])
        else:
            result = run_read_source(arguments, state_store=store)
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
    trace = {
        "tool": options.tool, "arguments": arguments,
        "elapsed_ms": (time.perf_counter_ns() - started) / 1_000_000,
        "events": events, "result": result, "error": error,
    }
    with (options.session / "calls.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(trace, ensure_ascii=False) + "\n")
    print(json.dumps(error if error else result, ensure_ascii=False, indent=2))
    if error:
        sys.exit(1)


if __name__ == "__main__":
    main()
