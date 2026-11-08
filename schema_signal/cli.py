"""CLI and portable reproduction bundle writer."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .core import API, Client, DemoClient, make_request, probe, scrub


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:-]{0,159}", value) or value.startswith("sk-or-"):
        raise argparse.ArgumentTypeError("Use a model ID or provider slug, not a URL or credential")
    return value


def bounded_int(low: int, high: int):
    def parse(value: str):
        try:
            number = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError("Must be an integer") from None
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f"Must be between {low} and {high}")
        return number
    return parse


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Compare OpenRouter structured-output routing; dry-run by default.")
    mode = result.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="Make up to two billable generation requests")
    mode.add_argument("--demo", action="store_true", help="Use fictional offline responses, no key/network")
    result.add_argument("--model", type=identifier, default="openai/gpt-4o-mini")
    result.add_argument("--provider", type=identifier, help="Pin one provider slug, with fallbacks disabled")
    result.add_argument("--max-tokens", type=bounded_int(16, 4096), default=256)
    result.add_argument("--timeout", type=bounded_int(1, 120), default=30, help="Per-request timeout in seconds")
    result.add_argument("--out", type=Path, default=None, help="New output directory; existing directories are never overwritten")
    result.add_argument("--version", action="version", version=__version__)
    return result


def report_markdown(report: dict) -> str:
    lines = ["# Schema Signal report", "", f"Mode: **{report['mode']}**", "",
             f"Created: {report['created_at']}", f"Requested model: `{report['requested_model']}`", "",
             "| require_parameters | Result | HTTP | Provider observed | Evidence | JSON / schema |",
             "| --- | --- | --- | --- | --- | --- |"]
    for result in report["results"]:
        routing = result.get("routing", {})
        validation = result.get("validation", {})
        lines.append(f"| {str(result['require_parameters']).lower()} | {result['status']} | "
                     f"{result.get('http_status', 'n/a')} | {routing.get('provider') or 'unknown'} | "
                     f"{routing.get('source', 'not run')} | {validation.get('json_valid')} / {validation.get('schema_valid')} |")
    lines.extend(["", "## Read this before drawing a conclusion", "",
                  "- DEMO is a fictional fixture, not OpenRouter evidence. DRY RUN makes no network calls.",
                  "- A live run is one observation per setting, not a causal experiment or a benchmark.",
                  "- Matching results are useful: response_format is already a soft routing preference.",
                  "- require_parameters=true filters all requested parameters, not just the schema.",
                  "- A provider name identifies the reported serving provider, not every attempted endpoint or fallback.",
                  "- Unknown routing stays unknown. A failed metadata lookup does not imply a provider failure.",
                  "- Schema-valid means structure only, not a correct extraction.",
                  "- A timeout has an uncertain server-side outcome and may still be billed. No POST is retried.",
                  "", "## Shareable reproduction", "",
                  "The request files use synthetic input. Report content excludes raw model output, raw errors,",
                  "authorization headers, and generation IDs. Model/provider labels and usage remain.",
                  "Review these files before sharing. No report is uploaded automatically.",
                  "", "`reproduce.sh` replays both requests and may incur charges. It prints raw API responses",
                  "to your own terminal; do not paste them publicly without review. Its successful exit",
                  "does not prove schema validity. Run the Python CLI for validation.", ""])
    return "\n".join(lines)


REPRODUCE = r'''#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"
: "${OPENROUTER_API_KEY:?Set OPENROUTER_API_KEY in your environment}"
printf '%s\n' 'This sends TWO requests to OpenRouter and may incur charges.' >&2
for setting in off on; do
  printf '\n%s\n' "require_parameters=$setting" >&2
  curl --silent --show-error --fail-with-body --max-time 120 \
    'https://openrouter.ai/api/v1/chat/completions' \
    -H "Authorization: Bearer ${OPENROUTER_API_KEY}" \
    -H 'Content-Type: application/json' \
    --data-binary "@request-$setting.json"
  printf '\n'
done
'''


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    mode = "LIVE" if args.live else ("DEMO: SIMULATED, NOT LIVE" if args.demo else "DRY RUN: NOT EXECUTED")
    key = os.environ.get("OPENROUTER_API_KEY", "").strip() if args.live else ""
    if args.live and not key:
        print("Missing OPENROUTER_API_KEY. No requests sent. Use --demo for an offline walkthrough.", file=sys.stderr)
        return 2
    if any(c in key for c in "\r\n"):
        print("Invalid credential format. No requests sent.", file=sys.stderr)
        return 2
    now = datetime.now(timezone.utc)
    destination = args.out or Path("runs") / now.strftime("%Y%m%dT%H%M%S.%fZ")
    try:
        destination.mkdir(parents=True, exist_ok=False)
    except OSError:
        print("Cannot create output directory. Choose a new writable --out directory. No requests sent.", file=sys.stderr)
        return 2
    requests = [make_request(args.model, required, args.provider, args.max_tokens) for required in (False, True)]
    report = {"tool_version": __version__, "mode": mode, "created_at": now.isoformat(),
              "endpoint": API + "/chat/completions", "requested_model": args.model,
              "provider_pin": args.provider, "results": []}
    try:
        # Persist reproductions before any live call. Headers are never serialized.
        for name, request in zip(("off", "on"), requests):
            (destination / f"request-{name}.json").write_text(json.dumps(scrub(request, key), indent=2) + "\n", encoding="utf-8")
        (destination / "reproduce.sh").write_text(REPRODUCE, encoding="utf-8")
        print(f"Schema Signal | {mode}")
        if args.live:
            print("Up to 2 generation requests, plus up to 2 metadata reads. Charges may apply. No retries.")
        client = Client(key, args.timeout) if args.live else DemoClient()
        for request in requests:
            if not (args.live or args.demo):
                result = {"require_parameters": request["provider"]["require_parameters"], "status": "not_run"}
            elif report["results"] and report["results"][0].get("http_status") in (401, 402, 403, 429):
                result = {"require_parameters": True, "status": "skipped_after_auth_credits_or_rate_limit"}
            else:
                result = probe(client, request)
            result = scrub(result, key)
            report["results"].append(result)
            # Persist after each result in case the second call is interrupted.
            safe_report = scrub(report, key)
            (destination / "report.json").write_text(json.dumps(safe_report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            (destination / "report.md").write_text(report_markdown(safe_report), encoding="utf-8")
            provider = result.get("routing", {}).get("provider") or "unknown"
            print(f"  require_parameters={str(result['require_parameters']).lower():5}  {result['status']:16}  provider={provider}")
    except (OSError, ValueError):
        print("Could not finish writing the report. Earlier requests may have completed; inspect the output directory before rerunning.", file=sys.stderr)
        return 2
    print(f"Bundle: {destination}")
    if args.live and any(item["status"] != "valid" for item in report["results"]):
        return 1
    return 0
