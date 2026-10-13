"""Opt-in live-provider check. Requires an existing credential and may consume quota.

Never run by default, CI, packaging, or controlled acceptance. This does not accept
secrets on argv or write configuration. Supply credentials through the normal CLI
credential store/environment before explicitly opting in.
"""
import argparse
import json
import subprocess
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--source", choices=["tavily", "exa", "brave", "parallel", "baidu", "firecrawl", "serpapi", "github-repos"], required=True)
    parser.add_argument("--allow-paid-provider", action="store_true", help="Explicitly acknowledge a real request may consume provider quota")
    options = parser.parse_args(argv)
    if not options.allow_paid_provider:
        parser.error("Not run: provide your own credential securely and explicitly pass --allow-paid-provider; a real request may consume quota")
    if not options.cli.is_absolute() or not options.cli.is_file():
        parser.error("--cli must name an installed absolute executable path")
    result = subprocess.run([str(options.cli), "search", "multi-search installation smoke", "--source", options.source], capture_output=True, text=True, encoding="utf-8", timeout=60)
    try:
        payload = json.loads(result.stdout)
        outcome = payload.get("outcome", "invalid_response")
    except (json.JSONDecodeError, AttributeError):
        outcome = "invalid_response"
    # Raw provider responses, stderr, URLs and configuration are deliberately not logged.
    print(json.dumps({"source": options.source, "exit_code": result.returncode, "outcome": outcome}))
    return 0 if result.returncode == 0 and outcome == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
