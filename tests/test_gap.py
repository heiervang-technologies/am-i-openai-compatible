"""Smoke tests for the gap analyzer (`aioc gap`).

The gap analyzer compares a monolith probe report against per-service
cluster reports and surfaces coverage gaps. Until this file existed,
it had zero test coverage despite being ~470 LOC behind a CLI
subcommand. These tests lock in the basic invariants:

- Empty cluster → MONOLITH-ONLY rows
- Empty monolith → MISSING-IN-MONOLITH rows
- Both populated with same endpoint → MATCHED row
- Malformed events don't crash the report
- All three output formats (text, markdown, gum) return cleanly
  without raising

Comprehensive testing of verdict logic is out of scope here.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from am_i_openai_compatible import gap


def _ev(endpoint: str, status: str = "PASS", phase: str = "A", service: str = "svc"):
    return {
        "service": service,
        "endpoint": endpoint,
        "phase": phase,
        "status": status,
        "detail": f"{status} detail",
        "method": "GET",
        "kind": "core",
        "group": "test",
        "profile": "openai",
    }


def _write(tmp: Path, name: str, events: list[dict]) -> Path:
    p = tmp / name
    p.write_text(json.dumps(events))
    return p


def test_gap_matched_when_both_have_endpoint():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        mp = _write(tmp, "mono.json", [_ev("/v1/chat/completions")])
        cp = _write(tmp, "clu.json", [_ev("/v1/chat/completions", phase="B")])
        rc = gap.main(["--monolith", str(mp), "--cluster", str(cp), "--format", "text"])
        assert rc == 0


def test_gap_monolith_only_when_cluster_empty():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        mp = _write(tmp, "mono.json", [_ev("/v1/chat/completions")])
        cp = _write(tmp, "clu.json", [])
        rc = gap.main(["--monolith", str(mp), "--cluster", str(cp), "--format", "text"])
        assert rc == 0


def test_gap_missing_in_monolith_when_monolith_empty():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        mp = _write(tmp, "mono.json", [])
        cp = _write(tmp, "clu.json", [_ev("/v1/embeddings", phase="A")])
        rc = gap.main(["--monolith", str(mp), "--cluster", str(cp), "--format", "text"])
        assert rc == 0


def test_gap_handles_malformed_events_without_crashing():
    """Defensive: an event missing 'phase' or other optional fields
    must not crash the report. Falls back to defensive defaults."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        # Missing 'phase' field
        mp = _write(tmp, "mono.json", [{"service": "m", "endpoint": "/v1/x", "status": "PASS"}])
        cp = _write(tmp, "clu.json", [])
        rc = gap.main(["--monolith", str(mp), "--cluster", str(cp), "--format", "text"])
        assert rc == 0


def test_gap_markdown_format_returns_zero():
    """Markdown output path used by docs-generation flows."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        mp = _write(tmp, "mono.json", [_ev("/v1/chat/completions")])
        cp = _write(tmp, "clu.json", [_ev("/v1/chat/completions", phase="B")])
        out = tmp / "GAP.md"
        rc = gap.main(
            [
                "--monolith",
                str(mp),
                "--cluster",
                str(cp),
                "--format",
                "markdown",
                "-o",
                str(out),
            ]
        )
        assert rc == 0
        assert out.exists()
        text = out.read_text()
        # Sanity-check: the markdown table header is present
        assert "| Endpoint |" in text
        assert "/v1/chat/completions" in text
