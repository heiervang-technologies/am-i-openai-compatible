"""Post-process an aioc probe report for the GitHub Action.

Responsibilities:

  1. Parse the JSON report written by `aioc probe`.
  2. Compute pass/warn/fail/skip counts and write them to GITHUB_OUTPUT.
  3. Append a per-endpoint markdown table to GITHUB_STEP_SUMMARY in
     catalog order, so PR-diff-of-summary stays readable across runs.
  4. Apply the `fail-on` threshold and exit non-zero if breached.

Kept deliberately small: the action stays a thin wrapper, and the
canonical probe + catalog logic lives in the Python package.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from am_i_openai_compatible.endpoints import ENDPOINTS

ICON = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌", "SKIP": "⏭"}


def _argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report", required=True, help="path to aioc probe JSON report")
    p.add_argument(
        "--fail-on",
        choices=("FAIL", "WARN", "none"),
        default="FAIL",
        help="threshold above which the action exits non-zero",
    )
    p.add_argument(
        "--step-summary",
        default="true",
        help="if 'true', write GITHUB_STEP_SUMMARY",
    )
    return p


def _best_event_for(events: list[dict], endpoint: str) -> dict | None:
    """Pick the most informative event for an endpoint.

    Priority: any FAIL > any WARN > Phase B PASS > Phase A PASS > SKIP.
    Mirrors the prioritization in gap.py so the summary tells the same
    story as the gap report.
    """
    rank = {
        ("A", "FAIL"): 0,
        ("B", "FAIL"): 0,
        ("A", "WARN"): 1,
        ("B", "WARN"): 1,
        ("B", "PASS"): 2,
        ("A", "PASS"): 3,
        ("A", "SKIP"): 4,
        ("B", "SKIP"): 4,
    }
    matches = [e for e in events if e.get("endpoint") == endpoint]
    if not matches:
        return None
    matches.sort(key=lambda e: rank.get((e.get("phase"), e.get("status")), 9))
    return matches[0]


def _set_output(name: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        return
    with open(out, "a") as f:
        f.write(f"{name}={value}\n")


def _write_summary(events: list[dict], counts: dict[str, int], service: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines: list[str] = []
    lines.append(f"## aioc probe — `{service}`")
    lines.append("")
    summary_parts = [f"{ICON[k]} {counts.get(k, 0)} {k}" for k in ("PASS", "WARN", "FAIL", "SKIP")]
    lines.append(" · ".join(summary_parts))
    lines.append("")
    lines.append("| Endpoint | Status | Detail |")
    lines.append("|----------|--------|--------|")
    for ep in ENDPOINTS:
        best = _best_event_for(events, ep.path)
        if best is None:
            continue
        status = best.get("status", "")
        icon = ICON.get(status, "?")
        detail = (best.get("detail") or "").replace("|", "\\|")[:120]
        lines.append(f"| `{ep.path}` | {icon} {status} | {detail} |")
    lines.append("")
    with open(path, "a") as f:
        f.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    args = _argparser().parse_args(argv)
    report_path = Path(args.report)
    if not report_path.exists():
        print(f"::error::aioc report not found at {report_path}", file=sys.stderr)
        _set_output("report-path", str(report_path))
        for k in ("pass", "warn", "fail", "skip"):
            _set_output(f"{k}-count", "0")
        return 1

    events: list[dict] = json.loads(report_path.read_text())
    counts: dict[str, int] = {"PASS": 0, "WARN": 0, "FAIL": 0, "SKIP": 0}
    for e in events:
        s = e.get("status", "")
        if s in counts:
            counts[s] += 1

    service = events[0].get("service", "probe") if events else "probe"

    _set_output("report-path", str(report_path))
    for k in ("PASS", "WARN", "FAIL", "SKIP"):
        _set_output(f"{k.lower()}-count", str(counts[k]))

    if args.step_summary == "true":
        _write_summary(events, counts, service)

    print(
        f"aioc probe '{service}': "
        + " · ".join(f"{ICON[k]} {counts[k]} {k}" for k in ("PASS", "WARN", "FAIL", "SKIP"))
    )

    if args.fail_on == "FAIL" and counts["FAIL"] > 0:
        print(f"::error::aioc fail-on=FAIL: {counts['FAIL']} FAIL events", file=sys.stderr)
        return 1
    if args.fail_on == "WARN" and (counts["FAIL"] > 0 or counts["WARN"] > 0):
        print(
            f"::error::aioc fail-on=WARN: {counts['FAIL']} FAIL, {counts['WARN']} WARN",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
