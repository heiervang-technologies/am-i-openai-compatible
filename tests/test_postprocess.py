"""Tests for scripts/postprocess.py — the action's report wrapper.

Runs the script in-process with monkeypatched env vars so we can
assert the GITHUB_OUTPUT lines, GITHUB_STEP_SUMMARY content, and
exit code without spawning subprocesses.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "postprocess.py"


def _load_postprocess():
    spec = importlib.util.spec_from_file_location("postprocess", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["postprocess"] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_report(tmp_path: Path, events: list[dict]) -> Path:
    p = tmp_path / "report.json"
    p.write_text(json.dumps(events))
    return p


def _read_kv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


def _make_event(endpoint: str, phase: str, status: str, **extra) -> dict:
    return {
        "service": "test",
        "endpoint": endpoint,
        "phase": phase,
        "status": status,
        "detail": extra.get("detail", ""),
        "method": extra.get("method", "GET"),
        "http_status": extra.get("http_status", 0),
        "kind": extra.get("kind", "core"),
        "group": extra.get("group", "misc"),
    }


def test_counts_and_summary_on_clean_run(tmp_path, monkeypatch):
    pp = _load_postprocess()
    report = _write_report(
        tmp_path,
        [
            _make_event("/v1/models", "A", "PASS", detail="200 (route exists)"),
            _make_event("/v1/chat/completions", "B", "PASS", detail="shape ok"),
        ],
    )
    output_file = tmp_path / "output"
    summary_file = tmp_path / "summary"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))

    rc = pp.main(["--report", str(report), "--fail-on", "FAIL", "--step-summary", "true"])
    assert rc == 0

    kv = _read_kv(output_file)
    assert kv["pass-count"] == "2"
    assert kv["fail-count"] == "0"
    assert kv["warn-count"] == "0"
    assert kv["skip-count"] == "0"
    assert kv["report-path"] == str(report)

    summary = summary_file.read_text()
    assert "## aioc probe — `test`" in summary
    assert "✅ 2 PASS" in summary
    # Catalog order: /v1/models comes before /v1/chat/completions.
    assert summary.index("/v1/models") < summary.index("/v1/chat/completions")


def test_fail_on_fail_returns_nonzero(tmp_path, monkeypatch):
    pp = _load_postprocess()
    report = _write_report(
        tmp_path,
        [
            _make_event("/v1/models", "A", "PASS"),
            _make_event("/v1/responses", "A", "FAIL", detail="404 — endpoint absent"),
        ],
    )
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    rc = pp.main(["--report", str(report), "--fail-on", "FAIL", "--step-summary", "false"])
    assert rc == 1


def test_fail_on_warn_treats_warn_as_failure(tmp_path, monkeypatch):
    pp = _load_postprocess()
    report = _write_report(
        tmp_path,
        [_make_event("/v1/embeddings", "A", "WARN", detail="501 — Start it with --embeddings")],
    )
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    rc = pp.main(["--report", str(report), "--fail-on", "WARN", "--step-summary", "false"])
    assert rc == 1


def test_fail_on_none_always_succeeds(tmp_path, monkeypatch):
    pp = _load_postprocess()
    report = _write_report(
        tmp_path,
        [_make_event("/v1/responses", "A", "FAIL", detail="404 — endpoint absent")],
    )
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    rc = pp.main(["--report", str(report), "--fail-on", "none", "--step-summary", "false"])
    assert rc == 0


def test_missing_report_returns_nonzero_with_zero_counts(tmp_path, monkeypatch):
    pp = _load_postprocess()
    output_file = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    rc = pp.main(["--report", str(tmp_path / "nope.json"), "--fail-on", "FAIL"])
    assert rc == 1
    kv = _read_kv(output_file)
    assert kv["pass-count"] == "0"
    assert kv["fail-count"] == "0"


def test_summary_picks_most_informative_event_per_endpoint(tmp_path, monkeypatch):
    """When an endpoint has both Phase A PASS and Phase B FAIL, the
    summary should show the more interesting Phase B FAIL row."""
    pp = _load_postprocess()
    report = _write_report(
        tmp_path,
        [
            _make_event("/v1/chat/completions", "A", "PASS", detail="200 (route exists)"),
            _make_event("/v1/chat/completions", "B", "FAIL", detail="missing keys: choices"),
        ],
    )
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    summary_file = tmp_path / "summary"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))

    pp.main(["--report", str(report), "--fail-on", "none", "--step-summary", "true"])

    summary = summary_file.read_text()
    # The Phase B FAIL line should win for this endpoint.
    chat_lines = [
        line for line in summary.splitlines() if "/v1/chat/completions" in line and "|" in line
    ]
    assert any("FAIL" in line for line in chat_lines)
    assert not any("PASS" in line for line in chat_lines)
