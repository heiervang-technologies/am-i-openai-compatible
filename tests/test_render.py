"""Tests for the `aioc render` subcommand + render module.

Renders are TTY-aware: colors must appear when explicitly requested
and disappear when the renderer is told to strip them. The dedupe
rule must collapse two events per endpoint (Phase A + Phase B) into
the most informative one, matching the GH-action step-summary
priority.
"""

from __future__ import annotations

import json

from am_i_openai_compatible import render


def _events():
    return [
        {"endpoint": "/v1/models", "phase": "A", "status": "PASS", "detail": "200"},
        {
            "endpoint": "implies: models list→retrieve",
            "phase": "C",
            "status": "PASS",
            "detail": "consistent",
        },
        {"endpoint": "/v1/chat/completions", "phase": "A", "status": "PASS", "detail": "400"},
        {"endpoint": "/v1/chat/completions", "phase": "B", "status": "PASS", "detail": "shape ok"},
        {"endpoint": "/v1/reranking", "phase": "A", "status": "WARN", "detail": "501 — not yet"},
        # No Phase B row for reranking — Phase A WARN is the only row.
        {"endpoint": "/v1/segmentations", "phase": "A", "status": "FAIL", "detail": "404"},
    ]


def test_best_per_endpoint_prefers_more_informative_phase():
    rows = render.best_per_endpoint(_events())
    by_ep = {r["endpoint"]: r for r in rows}
    # Phase B PASS wins over Phase A PASS for chat/completions.
    assert by_ep["/v1/chat/completions"]["phase"] == "B"
    # First-seen order preserved.
    assert [r["endpoint"] for r in rows] == [
        "/v1/models",
        "implies: models list→retrieve",
        "/v1/chat/completions",
        "/v1/reranking",
        "/v1/segmentations",
    ]


def test_render_emits_ansi_when_color_on():
    out = render.render(_events(), use_color=True)
    # Each known status has a color escape.
    assert "\033[32m" in out  # green PASS
    assert "\033[33m" in out  # yellow WARN
    assert "\033[31m" in out  # red FAIL


def test_render_strips_ansi_when_color_off():
    out = render.render(_events(), use_color=False)
    assert "\033[" not in out
    # Glyph + status still present.
    assert "● PASS" in out
    assert "▲ WARN" in out
    assert "✖ FAIL" in out


def test_render_limit_caps_rows():
    out = render.render(_events(), limit=2, use_color=False)
    # Header (2 lines) + 2 data rows = 4 newlines.
    assert out.count("\n") == 4


def test_render_includes_phase_c_implication():
    out = render.render(_events(), use_color=False)
    assert "implies: models list→retrieve" in out
    assert "consistent" in out


def test_render_file_round_trip(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps(_events()))
    out = render.render_file(str(path), use_color=False)
    assert "/v1/chat/completions" in out
    assert "shape ok" in out
