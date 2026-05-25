"""ANSI table renderer for `aioc probe` JSON reports.

One row per endpoint (dedup via the same priority rule as the GitHub
Action step-summary: FAIL > WARN > Phase B PASS > Phase A PASS > SKIP).
Colors are stripped when stdout isn't a TTY, so the output stays
pipe-friendly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

GLYPH = {"PASS": "●", "WARN": "▲", "FAIL": "✖", "SKIP": "○"}
COLOR = {"PASS": "32", "WARN": "33", "FAIL": "31", "SKIP": "90"}
_RANK = {
    ("A", "FAIL"): 0,
    ("B", "FAIL"): 0,
    ("A", "WARN"): 1,
    ("B", "WARN"): 1,
    ("B", "PASS"): 2,
    ("A", "PASS"): 3,
    ("A", "SKIP"): 4,
    ("B", "SKIP"): 4,
}


def best_per_endpoint(events: list[dict]) -> list[dict]:
    """Pick one event per endpoint using the priority rule above.

    Preserves first-seen order so the rendered table matches the
    catalog order the prober emits.
    """
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


def render(events: list[dict], limit: int = 0, use_color: bool = True) -> str:
    """Return the colored table as a single string (newline-terminated lines)."""
    rows = best_per_endpoint(events)
    if limit:
        rows = rows[:limit]
    if not rows:
        return ""
    ep_w = max(len(r["endpoint"]) for r in rows)
    lines = [
        f"{'Endpoint':<{ep_w}}  Status    Detail",
        f"{'─' * ep_w}  ──────    {'─' * 28}",
    ]
    for r in rows:
        status = r["status"]
        cell = _paint(status, GLYPH[status], use_color)
        pad = 6 - len(status)
        detail = (r.get("detail") or "")[:48]
        lines.append(f"{r['endpoint']:<{ep_w}}  {cell}{' ' * pad}  {detail}")
    return "\n".join(lines) + "\n"


def render_file(path: str, limit: int = 0, use_color: bool | None = None) -> str:
    """Read a report JSON and render it. `use_color=None` auto-detects TTY."""
    if use_color is None:
        use_color = sys.stdout.isatty()
    events = json.loads(Path(path).read_text())
    return render(events, limit=limit, use_color=use_color)
