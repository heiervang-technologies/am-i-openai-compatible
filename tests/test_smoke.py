"""Smoke tests — make sure the package imports and the catalog is sane.

These do not hit any real network. The probe-against-mock test lives
separately in test_probe_mock.py once the respx fixtures are wired up.
"""

from __future__ import annotations

import argparse

import am_i_openai_compatible as aioc
from am_i_openai_compatible.cli import build_parser


def test_version_present():
    assert isinstance(aioc.__version__, str)
    assert aioc.__version__.count(".") >= 1


def test_catalog_non_empty():
    assert len(aioc.ENDPOINTS) > 0
    paths = {e.path for e in aioc.ENDPOINTS}
    # Headline endpoints must exist in the catalog.
    assert "/v1/models" in paths
    assert "/v1/chat/completions" in paths


def test_catalog_kinds_are_known():
    valid = {"core", "optional", "ext", "ours"}
    for e in aioc.ENDPOINTS:
        assert e.kind in valid, f"{e.path} has unknown kind {e.kind!r}"


def test_cli_help_does_not_crash():
    parser = build_parser()
    # argparse exits with SystemExit(0) on -h; we just verify parser builds.
    assert parser.prog == "aioc"
    assert {a.dest for a in parser._actions if a.dest != "help"} >= {"cmd"}


def test_cli_spec_subcommand_registered():
    parser = build_parser()
    sub = next(a for a in parser._actions if a.dest == "cmd")
    assert "probe" in sub.choices
    assert "gap" in sub.choices
    assert "spec" in sub.choices


def test_cli_main_dispatches_to_render_subcommand(capsys, tmp_path):
    """End-to-end dispatch test for `aioc render`. Covers
    cli.py:main + cli.py:_cmd_render (the entire body that was
    previously uncovered). Writes a minimal probe report, invokes
    via main()'s arg-parsing, asserts the table rendered.
    """
    import json

    from am_i_openai_compatible.cli import main

    report = tmp_path / "r.json"
    report.write_text(
        json.dumps(
            [
                {
                    "service": "test",
                    "endpoint": "/v1/chat/completions",
                    "phase": "A",
                    "status": "PASS",
                    "detail": "200 (route exists)",
                    "method": "POST",
                    "kind": "core",
                    "group": "chat",
                    "profile": "openai",
                }
            ]
        )
    )

    rc = main(["render", str(report), "--no-color"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "/v1/chat/completions" in out
    assert "PASS" in out


def test_cli_main_dispatches_spec_json(capsys):
    """End-to-end test for `aioc spec --json`. Covers the JSON
    branch of _cmd_spec which was uncovered until now."""
    import json

    from am_i_openai_compatible.cli import main

    rc = main(["spec", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    rows = json.loads(out)
    assert isinstance(rows, list)
    assert len(rows) > 25  # 31 catalog rows as of v0.4.1
    # Sanity: every row has the documented fields
    for row in rows:
        for field in ("path", "method", "group", "kind", "notes"):
            assert field in row, (row, field)


def test_cli_main_dispatches_spec_with_group_filter(capsys):
    """`aioc spec --group chat` filters by the GROUP field — not by
    path prefix. The chat group includes /v1/chat/completions plus
    /v1/completions, /v1/responses, /v1/realtime, etc.
    """
    from am_i_openai_compatible.cli import main

    rc = main(["spec", "--group", "chat"])
    assert rc == 0
    out = capsys.readouterr().out
    body_lines = [line for line in out.splitlines() if line.startswith("/v1/")]
    assert body_lines, out
    # Every row must have "chat" as a whitespace-separated token
    for line in body_lines:
        assert "chat" in line.split(), line
    # Spot-check: /v1/chat/completions IS chat-group; /v1/embeddings is NOT
    assert any("/v1/chat/completions" == line.split()[0] for line in body_lines)
    assert not any("/v1/embeddings" == line.split()[0] for line in body_lines)


def test_cli_spec_table_columns_dont_overflow(capsys):
    """Regression for the column-overflow bug: `aioc spec` used a
    hardcoded 10-char-wide GROUP column. Groups longer than that
    (`moderations`, `fine-tuning`, `audio-segment`) bled into the
    KIND column, producing strings like `moderationsext` and
    `audio-segmentours`. Fix computes column widths dynamically.
    """
    from am_i_openai_compatible.cli import _cmd_spec

    args = argparse.Namespace(group=None, json=False)
    _cmd_spec(args)
    out = capsys.readouterr().out
    # The bug: these tokens appear in the output if the columns ran
    # together. Each must NOT be a single contiguous string.
    assert "moderationsext" not in out
    assert "fine-tuningext" not in out
    assert "audio-segmentours" not in out
    # Sanity: every catalog row's group + kind should appear as
    # whitespace-separated tokens on its line.
    from am_i_openai_compatible.endpoints import ENDPOINTS

    for e in ENDPOINTS:
        for line in out.splitlines():
            if e.path in line:
                tokens = line.split()
                assert e.group in tokens, (e.path, e.group, line)
                assert e.kind in tokens, (e.path, e.kind, line)
                break
