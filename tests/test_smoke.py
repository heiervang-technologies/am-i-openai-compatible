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


def test_catalog_response_models_are_registered():
    from am_i_openai_compatible.probe import RESPONSE_MODELS

    for endpoint in aioc.ENDPOINTS:
        if endpoint.response_model:
            assert endpoint.response_model in RESPONSE_MODELS


def test_catalog_vs_docs_no_drift():
    """The reference docs (canonical-surface.md, compatibility-matrix.md)
    are hand-curated mirrors of the openai-profile catalog. Closes the
    drift-class-of-bug the way PRs #84 / #86 fixed it, then RFC #87
    proposed preventing — running the standalone check in-process so
    contributors catch missing-row PRs before they hit CI.
    """
    import importlib.util
    from pathlib import Path

    script = Path(__file__).parent.parent / "scripts/check_catalog_doc_drift.py"
    spec = importlib.util.spec_from_file_location("_drift_check", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main() == 0, (
        "catalog/doc drift detected — see stderr above and add the missing row(s) "
        "to docs/spec/canonical-surface.md and docs/compatibility-matrix.md."
    )


def test_catalog_phase_b_skip_covers_admin_list_routes():
    """`phase_b_skip=True` is the data-driven replacement for the
    old hardcoded admin-route tuple in probe.py. The three known
    admin/list routes (`/v1/files`, `/v1/batches`,
    `/v1/fine_tuning/jobs`) must remain flagged — otherwise the
    probe would issue a Phase B GET that 401-FAILs against unauth
    servers and adds noise to baseline reports.
    """
    flagged = {e.path for e in aioc.ENDPOINTS if e.phase_b_skip}
    assert flagged == {"/v1/files", "/v1/batches", "/v1/fine_tuning/jobs"}, (
        f"phase_b_skip drift: {flagged}"
    )


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


def test_cli_main_dispatches_probe_subcommand(monkeypatch):
    """End-to-end dispatch test for `aioc probe`. Covers
    cli.py:_cmd_probe — argv translation for required + optional
    flags. The dispatcher's conditional forwarding logic
    (`if args.report:`, `if args.skip_phase_b:`, etc.) is the part
    most likely to silently break, so assert on the forwarded argv
    list directly rather than letting probe.main run.
    """
    from am_i_openai_compatible import probe
    from am_i_openai_compatible.cli import main

    captured: dict[str, list[str] | None] = {"argv": None}

    def fake_probe_main(argv):
        captured["argv"] = list(argv)
        return 0

    monkeypatch.setattr(probe, "main", fake_probe_main)

    rc = main(
        [
            "probe",
            "http://localhost:8080",
            "--name",
            "test",
            "--report",
            "/tmp/r.json",
            "--skip-phase-b",
            "--timeout",
            "5",
            "--endpoints-filter",
            "/v1/chat",
            "--profile",
            "ht",
            "--model",
            "qwen-7b",
            "--openai-api-key",
            "sk-test",
        ]
    )
    assert rc == 0
    argv = captured["argv"]
    assert argv is not None
    # Required pair
    assert "--base-url" in argv and argv[argv.index("--base-url") + 1] == "http://localhost:8080"
    assert "--name" in argv and argv[argv.index("--name") + 1] == "test"
    # Conditional forwards — every flag should make it through
    assert "--report" in argv and argv[argv.index("--report") + 1] == "/tmp/r.json"
    assert "--skip-phase-b" in argv
    assert "--req-timeout" in argv and argv[argv.index("--req-timeout") + 1] == "5.0"
    assert "--endpoints-filter" in argv and argv[argv.index("--endpoints-filter") + 1] == "/v1/chat"
    assert "--profile" in argv and argv[argv.index("--profile") + 1] == "ht"
    assert "--model" in argv and argv[argv.index("--model") + 1] == "qwen-7b"
    assert "--openai-api-key" in argv and argv[argv.index("--openai-api-key") + 1] == "sk-test"


def test_cli_main_probe_omits_unset_optional_flags(monkeypatch):
    """The `if args.profile != "openai"` branch must drop the flag
    when the user didn't override the default. Otherwise the
    forwarded argv would carry stale defaults that mask real
    misconfiguration.
    """
    from am_i_openai_compatible import probe
    from am_i_openai_compatible.cli import main

    captured: dict[str, list[str] | None] = {"argv": None}

    def fake_probe_main(argv):
        captured["argv"] = list(argv)
        return 0

    monkeypatch.setattr(probe, "main", fake_probe_main)

    rc = main(["probe", "http://localhost:8080", "--name", "test"])
    assert rc == 0
    argv = captured["argv"]
    assert argv is not None
    # Defaults must NOT be forwarded — only --base-url + --name
    for flag in (
        "--report",
        "--skip-phase-b",
        "--req-timeout",
        "--endpoints-filter",
        "--profile",
        "--model",
        "--openai-api-key",
    ):
        assert flag not in argv, f"{flag} should not be forwarded when unset"


def test_cli_main_dispatches_gap_subcommand(monkeypatch):
    """End-to-end dispatch test for `aioc gap`. Covers
    cli.py:_cmd_gap — argv translation including the optional
    --output flag.
    """
    from am_i_openai_compatible import gap
    from am_i_openai_compatible.cli import main

    captured: dict[str, list[str] | None] = {"argv": None}

    def fake_gap_main(argv):
        captured["argv"] = list(argv)
        return 0

    monkeypatch.setattr(gap, "main", fake_gap_main)

    rc = main(
        [
            "gap",
            "--monolith",
            "mono.json",
            "--cluster",
            "clu.json",
            "--format",
            "markdown",
            "-o",
            "GAP.md",
        ]
    )
    assert rc == 0
    argv = captured["argv"]
    assert argv is not None
    assert "--monolith" in argv and argv[argv.index("--monolith") + 1] == "mono.json"
    assert "--cluster" in argv and argv[argv.index("--cluster") + 1] == "clu.json"
    assert "--format" in argv and argv[argv.index("--format") + 1] == "markdown"
    assert "-o" in argv and argv[argv.index("-o") + 1] == "GAP.md"


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
