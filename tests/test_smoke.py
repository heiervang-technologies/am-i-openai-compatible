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
