"""Render an aioc probe JSON report as a colored ANSI table.

Used by the VHS demo tape, but useful any time you want the
report on a human terminal:

    aioc probe URL --report out.json
    python scripts/render-report.py out.json

One row per endpoint (dedup via the same priority rule as the
GitHub Action step-summary: FAIL > WARN > Phase B PASS > Phase A
PASS > SKIP). Colors are stripped when stdout isn't a TTY, so the
output stays pipe-friendly.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

GLYPH = {"PASS": "●", "WARN": "▲", "FAIL": "✖", "SKIP": "○"}
COLOR = {"PASS": "32", "WARN": "33", "FAIL": "31", "SKIP": "90"}
_RANK = {
    ("A", "FAIL"): 0, ("B", "FAIL"): 0,
    ("A", "WARN"): 1, ("B", "WARN"): 1,
    ("B", "PASS"): 2,
    ("A", "PASS"): 3,
    ("A", "SKIP"): 4, ("B", "SKIP"): 4,
}


def _best_per_endpoint(events: list[dict]) -> list[dict]:
    order: list[str] = []
    by_ep: dict[str, dict] = {}
    for e in events:
        ep = e["endpoint"]
        if ep not in by_ep:
            order.append(ep)
            by_ep[ep] = e
            continue
        cur = by_ep[ep]
        cur_rank = _RANK.get((cur.get("phase", "A"), cur["status"]), 5)
        new_rank = _RANK.get((e.get("phase", "A"), e["status"]), 5)
        if new_rank < cur_rank:
            by_ep[ep] = e
    return [by_ep[ep] for ep in order]


def _paint(status: str, glyph: str, use_color: bool) -> str:
    if not use_color:
        return f"{glyph} {status}"
    return f"\033[{COLOR[status]}m{glyph} {status}\033[0m"


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("report", help="path to aioc probe JSON report")
    p.add_argument("--limit", type=int, default=0, help="cap rows (0 = all)")
    p.add_argument("--no-color", action="store_true", help="strip ANSI colors")
    args = p.parse_args(argv)

    events = json.loads(Path(args.report).read_text())
    rows = _best_per_endpoint(events)
    if args.limit:
        rows = rows[: args.limit]

    use_color = not args.no_color and sys.stdout.isatty()
    ep_w = max(len(r["endpoint"]) for r in rows)
    print(f"{'Endpoint':<{ep_w}}  Status    Detail")
    print(f"{'─' * ep_w}  ──────    {'─' * 28}")
    for r in rows:
        status = r["status"]
        cell = _paint(status, GLYPH[status], use_color)
        pad = 6 - len(status)
        detail = (r.get("detail") or "")[:48]
        print(f"{r['endpoint']:<{ep_w}}  {cell}{' ' * pad}  {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
