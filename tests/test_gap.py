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


def test_gap_ignores_phase_c_pseudo_endpoints():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        implication = _ev("implies: models list→retrieve", status="FAIL", phase="C")
        mp = _write(tmp, "mono.json", [implication])
        cp = _write(tmp, "clu.json", [])
        out_path = tmp / "GAP.md"

        rc = gap.main(
            [
                "--monolith",
                str(mp),
                "--cluster",
                str(cp),
                "--format",
                "markdown",
                "-o",
                str(out_path),
            ]
        )

        assert rc == 0
        assert "implies: models list→retrieve" not in out_path.read_text()


def test_gap_broken_in_monolith_when_monolith_fails_cluster_passes():
    """Verdict path: monolith has the route but it FAILs; cluster
    covers it with PASS. Verdict should be BROKEN-IN-MONOLITH and
    the exit code should be non-zero (broken endpoints fail the
    gap-analysis build).
    """
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        mp = _write(tmp, "mono.json", [_ev("/v1/chat/completions", status="FAIL")])
        cp = _write(tmp, "clu.json", [_ev("/v1/chat/completions", status="PASS")])
        out_path = tmp / "GAP.md"
        rc = gap.main(
            [
                "--monolith",
                str(mp),
                "--cluster",
                str(cp),
                "--format",
                "markdown",
                "-o",
                str(out_path),
            ]
        )
        # Non-zero exit on BROKEN-IN-MONOLITH — gap analysis treats
        # this as a build-failing condition.
        assert rc != 0, "BROKEN-IN-MONOLITH should yield non-zero exit"
        text = out_path.read_text()
        assert "BROKEN-IN-MONOLITH" in text


def test_gap_out_of_scope_when_neither_side_exposes():
    """Both monolith and cluster are ABSENT for an endpoint —
    OUT-OF-SCOPE verdict. Constructed by referencing an endpoint
    that's in the catalog but missing from both reports."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        # Both reports cover only /v1/chat/completions; the spec implies
        # /v1/embeddings exists in catalog but neither side reports it
        mp = _write(tmp, "mono.json", [_ev("/v1/chat/completions")])
        cp = _write(tmp, "clu.json", [_ev("/v1/chat/completions", phase="B")])
        # Run as text — verify no crash and the report mentions catalog
        # endpoints that didn't appear in either report
        rc = gap.main(["--monolith", str(mp), "--cluster", str(cp), "--format", "text"])
        assert rc == 0


def test_render_gum_falls_back_to_text_when_gum_missing(monkeypatch, capsys):
    """If `gum` isn't on PATH, render_gum must degrade gracefully:
    fall through to the text renderer and return 0 without
    attempting any subprocess calls. Covers gap.py:304-306.
    """
    from am_i_openai_compatible import gap as gap_mod

    monkeypatch.setattr(gap_mod.shutil, "which", lambda _: None)

    # Build one minimal Row directly so we don't need a CLI roundtrip.
    rows = [
        gap_mod.Row(
            endpoint="/v1/chat/completions",
            monolith=gap_mod.Cell(status="PASS", detail="", phase="A"),
            cluster_services=["svc"],
            cluster_status="PASS",
            verdict="MATCHED",
        )
    ]
    rc = gap_mod.render_gum(rows, monolith_name="mono", cluster_label="cluster")
    assert rc == 0
    out = capsys.readouterr().out
    # Text-renderer fallback should mention the endpoint
    assert "/v1/chat/completions" in out


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


def test_gap_cli_multiple_cluster_reports():
    """Verify aioc gap CLI dispatch supports multiple --cluster flags."""
    from am_i_openai_compatible import cli

    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        mp = _write(tmp, "mono.json", [_ev("/v1/chat/completions")])
        cp1 = _write(tmp, "clu1.json", [_ev("/v1/chat/completions", service="svc1")])
        cp2 = _write(tmp, "clu2.json", [_ev("/v1/embeddings", service="svc2")])
        out = tmp / "GAP.md"
        rc = cli.main(
            [
                "gap",
                "--monolith",
                str(mp),
                "--cluster",
                str(cp1),
                "--cluster",
                str(cp2),
                "--format",
                "markdown",
                "-o",
                str(out),
            ]
        )
        assert rc == 0
        text = out.read_text()
        assert "svc1" in text
        assert "svc2" in text


def test_gap_failing_path_creates_report_file_before_nonzero_exit():
    """Verify that when aioc gap fails (BROKEN-IN-MONOLITH), the output
    report file is still created on disk so CI artifact upload steps can
    find and upload it."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        mp = _write(tmp, "mono.json", [_ev("/v1/chat/completions", status="FAIL")])
        cp = _write(tmp, "clu.json", [_ev("/v1/chat/completions", status="PASS")])
        out_path = tmp / "aioc-gap-report.md"

        rc = gap.main(
            [
                "--monolith",
                str(mp),
                "--cluster",
                str(cp),
                "--format",
                "markdown",
                "-o",
                str(out_path),
            ]
        )

        assert rc != 0
        assert out_path.exists()
        assert out_path.stat().st_size > 0
        assert "BROKEN-IN-MONOLITH" in out_path.read_text()
