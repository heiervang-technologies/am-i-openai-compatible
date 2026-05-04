"""Coverage-gap analyzer.

Compares a "monolith" probe report against the union of one or more
"source-of-truth" reports (typically the per-service cluster reports
from the pytest harness). Answers two questions:

  1. What does the monolith actually cover today?
  2. What gaps exist between the monolith and the scattered
     per-service surfaces — i.e. what is the phase-2 backlog?

Outputs:

  --format text       fallback plain text (CI-friendly)
  --format gum        gum-rendered colored cards (default if gum on PATH)
  --format markdown   markdown table suitable for inclusion in
                      k8s/MONOLITH.md under "## Coverage gap"

Usage:
  python gap.py --monolith report-monolith.json --cluster report.json
  python gap.py --monolith … --cluster … --format markdown -o GAP.md
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Data shaping
# ---------------------------------------------------------------------------

@dataclass
class Cell:
    status: str          # PASS / WARN / FAIL / SKIP / ABSENT
    detail: str
    phase: str = ""      # "A" / "B" / "" if N/A


def _best_event_for(events: list[dict], endpoint: str) -> Cell:
    """Pick the most informative event for a given endpoint label.

    Priority (lowest is best): Phase B FAIL > Phase A FAIL > Phase B
    PASS > Phase A PASS > anything else. We want the row that tells
    the most useful story — a Phase B failure is more interesting
    than its Phase A precondition passing.
    """
    rank = {("A", "FAIL"): 0,
            ("B", "FAIL"): 0,
            ("A", "WARN"): 1,
            ("B", "WARN"): 1,
            ("B", "PASS"): 2,
            ("A", "PASS"): 3,
            ("A", "SKIP"): 4,
            ("B", "SKIP"): 4}
    matches = [e for e in events if e.get("endpoint") == endpoint]
    if not matches:
        return Cell(status="ABSENT", detail="not probed", phase="")
    matches.sort(key=lambda e: rank.get((e.get("phase"), e["status"]), 9))
    best = matches[0]
    return Cell(status=best["status"],
                detail=best.get("detail", "")[:120],
                phase=best.get("phase", ""))


def _aggregate_cluster(reports: list[Path]) -> tuple[dict[str, list[dict]],
                                                       set[str]]:
    """Flatten N cluster reports into per-endpoint event lists +
    return the set of services seen.
    """
    per_ep: dict[str, list[dict]] = defaultdict(list)
    services_seen: set[str] = set()
    for p in reports:
        try:
            events = json.loads(p.read_text())
        except FileNotFoundError:
            print(f"warn: cluster report {p} not found — skipping",
                  file=sys.stderr)
            continue
        for e in events:
            services_seen.add(e["service"])
            per_ep[e["endpoint"]].append(e)
    return per_ep, services_seen


def _services_passing(events: list[dict]) -> list[str]:
    """Which services have a PASS for this endpoint (any phase)."""
    return sorted({e["service"] for e in events
                   if e.get("status") in ("PASS", "WARN")})


# ---------------------------------------------------------------------------
# Gap computation
# ---------------------------------------------------------------------------

@dataclass
class Row:
    endpoint: str
    monolith: Cell
    cluster_services: list[str]
    cluster_status: str   # aggregate cluster status
    verdict: str          # MATCHED / MONOLITH-ONLY / MISSING-IN-MONOLITH /
                          # BROKEN-IN-MONOLITH / GAP
    notes: str = ""


def _verdict(monolith: Cell, cluster_services: list[str],
             cluster_status: str) -> tuple[str, str]:
    mono_ok = monolith.status in ("PASS", "WARN")
    cluster_ok = cluster_status in ("PASS", "WARN")

    if mono_ok and cluster_ok:
        return "MATCHED", "covered by both"
    if mono_ok and not cluster_ok:
        return "MONOLITH-ONLY", "monolith exposes; no per-service backend"
    if not mono_ok and cluster_ok:
        if monolith.status == "ABSENT":
            return "MISSING-IN-MONOLITH", \
                f"covered by {', '.join(cluster_services)}; not routed"
        if monolith.status == "FAIL":
            return "BROKEN-IN-MONOLITH", \
                f"route exists but fails ({monolith.detail[:60]})"
        return "GAP", "monolith skipped/down but cluster covers"
    if monolith.status == "ABSENT" and not cluster_services:
        return "OUT-OF-SCOPE", "neither side exposes"
    return "GAP", "no PASS on either side"


def _is_real_http_endpoint(label: str) -> bool:
    """Filter out pseudo-endpoints (implication test labels, etc.).

    The cluster report includes rows like 'implies: chat→stream' or
    '/v1/embeddings[list]' that aren't HTTP paths the monolith could
    plausibly expose. The gap report should only compare real OpenAI
    surface paths.
    """
    if not label.startswith("/"):
        return False
    # Strip any disambiguating [suffix] (e.g. [stream], [list]) and
    # require a clean leading /v1/… path.
    base = label.split("[")[0]
    return base.startswith("/v1/") or base == "/v1"


def compute_gap(monolith_events: list[dict],
                cluster_per_ep: dict[str, list[dict]],
                ) -> list[Row]:
    # Union of probed endpoints from monolith and cluster, restricted
    # to real HTTP paths.
    endpoints = {e["endpoint"] for e in monolith_events} | \
                 set(cluster_per_ep.keys())
    endpoints = {ep for ep in endpoints if _is_real_http_endpoint(ep)}

    rows: list[Row] = []
    for ep in sorted(endpoints):
        mono = _best_event_for(monolith_events, ep)
        cluster_events = cluster_per_ep.get(ep, [])
        services = _services_passing(cluster_events)
        # cluster aggregate status: PASS if any service passes, else
        # the worst-best status.
        if services:
            cluster_status = "PASS"
        elif cluster_events:
            order = ["FAIL", "SKIP", "WARN", "PASS"]
            picks = [e["status"] for e in cluster_events]
            cluster_status = next((s for s in order if s in picks), "SKIP")
        else:
            cluster_status = "ABSENT"
        verdict, notes = _verdict(mono, services, cluster_status)
        rows.append(Row(endpoint=ep, monolith=mono,
                        cluster_services=services,
                        cluster_status=cluster_status,
                        verdict=verdict, notes=notes))
    return rows


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

VERDICT_ORDER = [
    "BROKEN-IN-MONOLITH",
    "MISSING-IN-MONOLITH",
    "GAP",
    "MONOLITH-ONLY",
    "MATCHED",
    "OUT-OF-SCOPE",
]


def _summary(rows: list[Row]) -> dict[str, int]:
    s: dict[str, int] = {}
    for r in rows: s[r.verdict] = s.get(r.verdict, 0) + 1
    return s


def render_text(rows: list[Row], monolith_name: str,
                cluster_label: str) -> str:
    lines = [f"# Gap report: {monolith_name} vs {cluster_label}", ""]
    summary = _summary(rows)
    lines.append("Summary: " + ", ".join(
        f"{v}={summary.get(v,0)}" for v in VERDICT_ORDER if summary.get(v,0)))
    lines.append("")
    lines.append(f"{'Endpoint':38} {'Monolith':10} {'Cluster':10} {'Verdict':22} Notes")
    lines.append("-" * 110)
    rows_sorted = sorted(rows,
                          key=lambda r: (VERDICT_ORDER.index(r.verdict)
                                         if r.verdict in VERDICT_ORDER else 99,
                                         r.endpoint))
    for r in rows_sorted:
        lines.append(
            f"{r.endpoint:38} {r.monolith.status:10} {r.cluster_status:10} "
            f"{r.verdict:22} {r.notes}")
    return "\n".join(lines) + "\n"


def render_markdown(rows: list[Row], monolith_name: str,
                     cluster_label: str,
                     monolith_url: str = "",
                     cluster_reports: list[Path] | None = None) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    summary = _summary(rows)
    total = len(rows)
    matched = summary.get("MATCHED", 0) + summary.get("MONOLITH-ONLY", 0)

    out = []
    out.append("<!-- AUTO-GENERATED by tests/openai-compat/gap.py — do not edit -->")
    out.append(f"_Last run: {now}_  ")
    if monolith_url:
        out.append(f"_Monolith target: `{monolith_url}`_  ")
    out.append(f"_Cluster source(s): {cluster_label}_")
    out.append("")
    out.append(f"**{matched} of {total} endpoints unified by the monolith.**")
    out.append("")

    # Headline verdict counts
    out.append("| Verdict | Count |")
    out.append("|---------|------:|")
    for v in VERDICT_ORDER:
        c = summary.get(v, 0)
        if c == 0: continue
        out.append(f"| {v} | {c} |")
    out.append("")

    # Per-endpoint table grouped by verdict.
    out.append("| Endpoint | Monolith | Cluster | Verdict | Notes |")
    out.append("|----------|---------|---------|---------|-------|")
    rows_sorted = sorted(rows,
                          key=lambda r: (VERDICT_ORDER.index(r.verdict)
                                         if r.verdict in VERDICT_ORDER else 99,
                                         r.endpoint))
    icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌", "SKIP": "⏭",
            "ABSENT": "—"}
    for r in rows_sorted:
        m = f"{icon.get(r.monolith.status, '?')} {r.monolith.status}"
        if r.cluster_services:
            c = f"{icon['PASS']} " + ", ".join(f"`{s}`" for s in r.cluster_services)
        else:
            c = f"{icon.get(r.cluster_status, '—')} {r.cluster_status}"
        out.append(f"| `{r.endpoint}` | {m} | {c} | "
                   f"**{r.verdict}** | {r.notes} |")
    out.append("")
    out.append("Re-generate with:")
    out.append("```bash")
    out.append("python tests/openai-compat/probe.py --base-url http://llm.ht.local --name monolith")
    out.append("python -m pytest tests/openai-compat -q --harness-report=tests/openai-compat/report.json")
    out.append("python tests/openai-compat/gap.py --monolith tests/openai-compat/report-monolith.json \\")
    out.append("  --cluster tests/openai-compat/report.json --format markdown -o k8s/MONOLITH-GAP.md")
    out.append("```")
    return "\n".join(out) + "\n"


def render_gum(rows: list[Row], monolith_name: str,
               cluster_label: str) -> int:
    """Print rich gum-styled cards. Returns shell exit code."""
    if not shutil.which("gum"):
        print(render_text(rows, monolith_name, cluster_label))
        return 0

    summary = _summary(rows)
    total = len(rows)
    broken = summary.get("BROKEN-IN-MONOLITH", 0)
    missing = summary.get("MISSING-IN-MONOLITH", 0)
    matched = summary.get("MATCHED", 0) + summary.get("MONOLITH-ONLY", 0)

    if broken: hi = ("196", "✖ BROKEN COVERAGE")
    elif missing: hi = ("214", "▲ COVERAGE GAPS")
    else: hi = ("42", "● FULL COVERAGE")

    subprocess.run(["gum", "style", "--bold",
                    "--foreground", hi[0],
                    "--border", "thick", "--border-foreground", hi[0],
                    "--padding", "1 3", "--margin", "1 0", "--align", "center",
                    f"{hi[1]}\n{matched}/{total} endpoints unified"],
                   check=False)

    rows_sorted = sorted(rows,
                          key=lambda r: (VERDICT_ORDER.index(r.verdict)
                                         if r.verdict in VERDICT_ORDER else 99,
                                         r.endpoint))
    color_for = {
        "BROKEN-IN-MONOLITH": "196",
        "MISSING-IN-MONOLITH": "214",
        "GAP": "214",
        "MONOLITH-ONLY": "39",
        "MATCHED": "42",
        "OUT-OF-SCOPE": "244",
    }
    icon_for = {
        "BROKEN-IN-MONOLITH": "✖",
        "MISSING-IN-MONOLITH": "▲",
        "GAP": "▲",
        "MONOLITH-ONLY": "●",
        "MATCHED": "●",
        "OUT-OF-SCOPE": "○",
    }
    last_verdict = None
    for r in rows_sorted:
        if r.verdict != last_verdict:
            last_verdict = r.verdict
            subprocess.run(
                ["gum", "style", "--bold", "--foreground",
                 color_for.get(r.verdict, "244"),
                 f"\n  {icon_for.get(r.verdict, '·')} {r.verdict}"],
                check=False)
        cluster_str = (", ".join(r.cluster_services)
                       if r.cluster_services else r.cluster_status)
        subprocess.run(
            ["gum", "style", "--foreground", "252",
             f"    {r.endpoint:38} mono={r.monolith.status:6} "
             f"cluster={cluster_str}"],
            check=False)
        if r.notes:
            subprocess.run(["gum", "style", "--faint", "--foreground", "240",
                            f"      {r.notes}"], check=False)
    return 0 if broken == 0 else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--monolith", required=True,
                   help="path to a probe report (the monolith target)")
    p.add_argument("--cluster", action="append", default=[],
                   help="path to a cluster/per-service report; repeatable")
    p.add_argument("--format",
                   choices=["text", "markdown", "gum"],
                   default=None,
                   help="output format (default: gum if available else text)")
    p.add_argument("-o", "--output", default=None,
                   help="write to file instead of stdout")
    p.add_argument("--monolith-url", default="",
                   help="optional base URL for inclusion in the markdown header")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _argparser().parse_args(argv)

    monolith_path = Path(args.monolith)
    monolith_events = json.loads(monolith_path.read_text())
    monolith_name = (monolith_events[0]["service"]
                     if monolith_events else monolith_path.stem)

    cluster_paths = [Path(c) for c in args.cluster] or \
                    [HERE / "report.json"]
    cluster_per_ep, services_seen = _aggregate_cluster(cluster_paths)
    cluster_label = ("union of " +
                     ", ".join(f"`{p.name}`" for p in cluster_paths) +
                     f"  ·  services: {', '.join(sorted(services_seen))}")

    rows = compute_gap(monolith_events, cluster_per_ep)

    fmt = args.format or ("gum" if shutil.which("gum") and not args.output
                          else "text")
    if fmt == "markdown":
        out = render_markdown(rows, monolith_name, cluster_label,
                               monolith_url=args.monolith_url,
                               cluster_reports=cluster_paths)
    elif fmt == "text":
        out = render_text(rows, monolith_name, cluster_label)
    else:
        if args.output:
            print("warning: --format gum ignores --output; use text/markdown",
                  file=sys.stderr)
        return render_gum(rows, monolith_name, cluster_label)

    if args.output:
        Path(args.output).write_text(out)
        print(f"wrote {args.output}")
    else:
        sys.stdout.write(out)
    summary = _summary(rows)
    return 0 if summary.get("BROKEN-IN-MONOLITH", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
