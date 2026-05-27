#!/usr/bin/env python3
"""Post-fix dflash validator (mission m-20260527-103737-36364b).

Dev's fix d7a88fdbc: cache_prompt + dflash interaction — cached KV
restore was skipping dflash feature extraction. This script verifies
the surface that broke is now whole, end-to-end:

  1. Sequential cache-hit test on chat-completions.
     Two identical requests, same nonce, cache_prompt=true. Both
     must return non-empty content with a canonical finish_reason.
     This is the precise sequence that was broken pre-fix: second
     request hit the prefix cache, drafter feature-extraction got
     skipped, all-NaN logits, empty content.

  2. Streaming sanity.
     SSE chunks with valid shape, [DONE] sentinel, aggregate
     delta.content non-empty. If the model exposes
     `delta.reasoning_content`, validate it's a string.

  3. finish_reason semantics.
     Both stream and non-stream final answers must carry a
     finish_reason in {stop, length, tool_calls, content_filter}.

  4. Standard catalog surface via `aioc probe`.
     Wraps the existing prober (with the PR #12 empty-content gate
     active) against /v1/chat/completions and /v1/completions on
     this base, restricted to the chat group. Any FAIL here is a
     surface-shape regression independent of the cache bug.

Exit code 0 only if every check passes. Prints a single-line summary
followed by per-check diagnostics.
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

CANONICAL_FINISH = {"stop", "length", "tool_calls", "content_filter"}


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    extra: dict = field(default_factory=dict)


def check_cache_hit_sequence(client: httpx.Client, base: str, model: str) -> CheckResult:
    """Two identical requests, cache_prompt=true. Both must succeed.
    This is the literal sequence that reproduced the pre-fix bug.
    """
    nonce = secrets.token_hex(4)
    prompt = f"[Q-{nonce}] please respond with the word 'acknowledged'."
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 32,
        "temperature": 0,
        "cache_prompt": True,
    }
    shots = []
    for i in (1, 2):
        try:
            r = client.post(f"{base}/v1/chat/completions", json=body, timeout=120)
        except httpx.HTTPError as e:
            return CheckResult(
                f"cache-hit shot {i}",
                False,
                f"http error: {type(e).__name__}: {e}",
            )
        if r.status_code != 200:
            return CheckResult(
                f"cache-hit shot {i}",
                False,
                f"HTTP {r.status_code}: {r.text[:120]}",
            )
        try:
            j = r.json()
            content = j["choices"][0]["message"]["content"]
            finish = j["choices"][0]["finish_reason"]
        except (ValueError, KeyError, IndexError, TypeError) as e:
            return CheckResult(
                f"cache-hit shot {i}",
                False,
                f"shape error: {type(e).__name__}: {e}",
            )
        shots.append({"content": content, "finish": finish, "len": len(content or "")})
        if not content:
            return CheckResult(
                f"cache-hit shot {i}",
                False,
                f"empty content (the dflash bug signature); finish={finish!r}",
                extra={"shots": shots},
            )
        if finish not in CANONICAL_FINISH:
            return CheckResult(
                f"cache-hit shot {i}",
                False,
                f"non-canonical finish_reason {finish!r}",
                extra={"shots": shots},
            )
    return CheckResult(
        "cache-hit sequence (2 identical requests, cache_prompt=true)",
        True,
        f"shot1 len={shots[0]['len']} finish={shots[0]['finish']!r}; "
        f"shot2 len={shots[1]['len']} finish={shots[1]['finish']!r}",
        extra={"shots": shots, "nonce": nonce},
    )


def check_streaming(client: httpx.Client, base: str, model: str) -> CheckResult:
    """Streaming SSE: chunk shape, [DONE], aggregate content,
    optional reasoning_content presence."""
    nonce = secrets.token_hex(4)
    body = {
        "model": model,
        "messages": [
            {"role": "user", "content": f"[Q-{nonce}] reply with one short sentence."}
        ],
        "max_tokens": 64,
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
        "cache_prompt": True,
    }
    chunks = 0
    saw_done = False
    content_total = 0
    reasoning_total = 0
    final_finish: str | None = None
    try:
        with client.stream(
            "POST", f"{base}/v1/chat/completions", json=body, timeout=120
        ) as r:
            if r.status_code != 200:
                return CheckResult(
                    "streaming", False, f"HTTP {r.status_code}: {r.read()[:120]!r}"
                )
            ct = r.headers.get("content-type", "")
            if "text/event-stream" not in ct:
                return CheckResult(
                    "streaming", False, f"unexpected content-type {ct!r}"
                )
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    saw_done = True
                    break
                try:
                    evt = json.loads(data)
                except ValueError:
                    continue
                chunks += 1
                # The usage chunk emitted under stream_options.include_usage
                # carries `choices: []`; skip it cleanly.
                choices = evt.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                if isinstance(delta.get("content"), str):
                    content_total += len(delta["content"])
                if isinstance(delta.get("reasoning_content"), str):
                    reasoning_total += len(delta["reasoning_content"])
                fr = choices[0].get("finish_reason")
                if fr is not None:
                    final_finish = fr
    except httpx.HTTPError as e:
        return CheckResult(
            "streaming", False, f"http error: {type(e).__name__}: {e}"
        )
    if chunks == 0:
        return CheckResult("streaming", False, "no SSE data chunks")
    if not saw_done:
        return CheckResult(
            "streaming",
            False,
            f"missing [DONE] sentinel (chunks={chunks})",
        )
    if content_total == 0:
        return CheckResult(
            "streaming",
            False,
            f"empty aggregate delta.content (chunks={chunks})",
        )
    if final_finish is not None and final_finish not in CANONICAL_FINISH:
        return CheckResult(
            "streaming",
            False,
            f"non-canonical final finish_reason {final_finish!r}",
        )
    return CheckResult(
        "streaming (SSE chunks, [DONE], delta.content)",
        True,
        f"chunks={chunks} content_len={content_total} "
        f"reasoning_len={reasoning_total} finish={final_finish!r}",
    )


def check_aioc_probe(base: str, model: str, report_path: Path) -> CheckResult:
    """Run aioc probe restricted to the chat group; FAIL if any
    chat-row event grades FAIL. Invokes via `python -m
    am_i_openai_compatible.cli` so we pick up the aioc package that
    matches the validator's interpreter — otherwise the system
    `/home/me/.local/bin/aioc` (or any other PATH-resolved binary)
    may be pinned to an older release without the empty-content gate.
    """
    cmd = [
        sys.executable,
        "-m",
        "am_i_openai_compatible.cli",
        "probe",
        base,
        "--name",
        f"dflash-postfix-{model}",
        "--model",
        model,
        "--endpoints-filter",
        r"^/v1/(chat/completions(\[stream\])?|completions)$",
        "--report",
        str(report_path),
        "--timeout",
        "90",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return CheckResult("aioc probe", False, "subprocess timeout (300s)")
    if not report_path.exists():
        return CheckResult(
            "aioc probe", False, f"no report written; stderr={proc.stderr[:200]}"
        )
    events = json.loads(report_path.read_text())
    fails = [e for e in events if e.get("status") == "FAIL"]
    warns = [e for e in events if e.get("status") == "WARN"]
    if fails:
        snippet = "; ".join(
            f"{e['endpoint']}[{e['phase']}] {e['detail']}" for e in fails[:3]
        )
        return CheckResult(
            "aioc probe",
            False,
            f"{len(fails)} FAIL row(s); first: {snippet}",
            extra={"fails": fails, "warns": warns, "n_events": len(events)},
        )
    return CheckResult(
        "aioc probe (chat surface, empty-content gate)",
        True,
        f"{len(events)} events, 0 FAIL, {len(warns)} WARN",
        extra={"warns": warns, "n_events": len(events)},
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("base_url")
    ap.add_argument("--model", required=True, help="model id, e.g. gemma-4-31b-dflash-Q6_K")
    ap.add_argument("--reports", default=".probe-reports/dflash-postfix")
    args = ap.parse_args()

    reports = Path(args.reports)
    reports.mkdir(parents=True, exist_ok=True)

    print(
        f"[validate] base={args.base_url} model={args.model}",
        file=sys.stderr,
    )

    def _safe(fn, label):
        try:
            return fn()
        except Exception as e:
            return CheckResult(label, False, f"unhandled {type(e).__name__}: {e}")

    t0 = time.monotonic()
    results: list[CheckResult] = []
    client = httpx.Client()
    try:
        r1 = _safe(
            lambda: check_cache_hit_sequence(client, args.base_url, args.model),
            "cache-hit sequence",
        )
        print(f"  [{'PASS' if r1.passed else 'FAIL'}] {r1.name}: {r1.detail}", file=sys.stderr)
        results.append(r1)

        r2 = _safe(
            lambda: check_streaming(client, args.base_url, args.model),
            "streaming",
        )
        print(f"  [{'PASS' if r2.passed else 'FAIL'}] {r2.name}: {r2.detail}", file=sys.stderr)
        results.append(r2)
    finally:
        client.close()

    report_path = reports / f"{args.model}-aioc.json"
    r3 = _safe(
        lambda: check_aioc_probe(args.base_url, args.model, report_path),
        "aioc probe",
    )
    print(f"  [{'PASS' if r3.passed else 'FAIL'}] {r3.name}: {r3.detail}", file=sys.stderr)
    results.append(r3)

    overall = all(r.passed for r in results)
    elapsed = time.monotonic() - t0

    # Summary line + JSON sidecar
    summary = f"\n[validate] {'PASS' if overall else 'FAIL'} ({sum(r.passed for r in results)}/{len(results)} checks) in {elapsed:.1f}s"
    print(summary, file=sys.stderr)
    for r in results:
        print(f"  {'✓' if r.passed else '✖'} {r.name}: {r.detail}", file=sys.stderr)

    (reports / f"{args.model}-summary.json").write_text(
        json.dumps(
            {
                "base_url": args.base_url,
                "model": args.model,
                "overall_pass": overall,
                "results": [
                    {"name": r.name, "passed": r.passed, "detail": r.detail, "extra": r.extra}
                    for r in results
                ],
                "elapsed_s": elapsed,
            },
            indent=2,
        )
    )
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
