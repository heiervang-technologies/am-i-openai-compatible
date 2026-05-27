#!/usr/bin/env python3
"""Characterize the stream:true crash on dflash post-Gate-C.

Smoke (stream:false): 5/5 PASS, 8.14% accept, NaN absent.
Heierchat (stream:true): crashes dflash child → 500 → empty bubble.

That's a stream-vs-non-stream differential. This probe:

  1. Issues a stream:false request and a stream:true request against
     the SAME body. Records the differential.

  2. For the stream:true path, captures EVERY chunk (or chunk fragment)
     before the disconnect. Records: SSE chunks count, time-to-first-
     byte, time-to-disconnect, per-chunk delta.content / delta.reasoning_content
     presence, finish_reason if seen, last partial line if mid-chunk crash.

  3. Minimization sweep: vary one parameter at a time to find the
     smallest stream:true request that crashes. Axes:
       - max_tokens (4, 16, 64, 256)
       - prompt length (1, 32, 256 chars)
       - cache_prompt (true, false)
       - stream_options.include_usage (true, false, omitted)

  4. Emits a structured JSON forensic record + a human-readable summary.

Run after snoop confirms the dflash child is back up.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx


@dataclass
class StreamCapture:
    """Everything observed on a streaming request, including the
    pathological case of mid-stream disconnect."""

    http_status: int = 0
    content_type: str = ""
    body_text_if_error: str = ""
    sse_chunks: int = 0
    content_total: int = 0
    reasoning_total: int = 0
    deltas_with_content: int = 0
    deltas_with_reasoning: int = 0
    finish_reason: str | None = None
    saw_done: bool = False
    last_chunk_raw: str = ""
    partial_after_disconnect: str = ""
    elapsed_s: float = 0.0
    error: str = ""

    def verdict(self) -> str:
        if self.error and "503" not in self.error and "501" not in self.error:
            return "CRASH"
        if self.http_status >= 500:
            return "CRASH"
        if self.http_status != 200:
            return "REJECT"
        if self.sse_chunks == 0:
            return "EMPTY"
        if not self.saw_done:
            return "TRUNCATED"
        if self.content_total == 0:
            return "NO_CONTENT"
        return "OK"


def capture_stream(client: httpx.Client, base: str, body: dict, timeout: float = 60.0) -> StreamCapture:
    """POST a streaming chat-completions request and capture
    everything observable, including post-crash state."""
    cap = StreamCapture()
    body = dict(body)
    body["stream"] = True
    t0 = time.monotonic()
    try:
        with client.stream(
            "POST", f"{base}/v1/chat/completions", json=body, timeout=timeout
        ) as r:
            cap.http_status = r.status_code
            cap.content_type = r.headers.get("content-type", "")
            if r.status_code != 200:
                try:
                    cap.body_text_if_error = r.read().decode(errors="replace")[:600]
                except Exception:
                    cap.body_text_if_error = "(could not read error body)"
                cap.elapsed_s = time.monotonic() - t0
                return cap
            buf = ""
            for line in r.iter_lines():
                cap.last_chunk_raw = line[:200]
                if not line.startswith("data:"):
                    if line.strip():
                        buf += line + "\n"
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    cap.saw_done = True
                    break
                try:
                    evt = json.loads(data)
                except ValueError:
                    cap.partial_after_disconnect = data[:200]
                    continue
                cap.sse_chunks += 1
                choices = evt.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                c = delta.get("content")
                rc = delta.get("reasoning_content")
                if isinstance(c, str):
                    cap.content_total += len(c)
                    if c:
                        cap.deltas_with_content += 1
                if isinstance(rc, str):
                    cap.reasoning_total += len(rc)
                    if rc:
                        cap.deltas_with_reasoning += 1
                fr = choices[0].get("finish_reason")
                if fr is not None:
                    cap.finish_reason = fr
    except httpx.HTTPError as e:
        cap.error = f"{type(e).__name__}: {e}"
    cap.elapsed_s = time.monotonic() - t0
    return cap


def capture_nonstream(client: httpx.Client, base: str, body: dict, timeout: float = 60.0) -> dict:
    body = dict(body)
    body.pop("stream", None)
    body.pop("stream_options", None)
    t0 = time.monotonic()
    out = {"elapsed_s": 0.0}
    try:
        r = client.post(f"{base}/v1/chat/completions", json=body, timeout=timeout)
        out["http_status"] = r.status_code
        out["elapsed_s"] = time.monotonic() - t0
        if r.status_code != 200:
            out["body_text"] = r.text[:300]
            return out
        j = r.json()
        choices = j.get("choices") or []
        if choices:
            out["content"] = (choices[0].get("message") or {}).get("content") or ""
            out["content_len"] = len(out["content"] or "")
            out["finish_reason"] = choices[0].get("finish_reason")
        else:
            out["body_text"] = json.dumps(j)[:300]
    except httpx.HTTPError as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def base_body(model: str, max_tokens: int, prompt: str, cache_prompt: bool, include_usage):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "cache_prompt": cache_prompt,
    }
    if include_usage is not None:
        body["stream_options"] = {"include_usage": bool(include_usage)}
    return body


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("base_url")
    ap.add_argument("--model", required=True)
    ap.add_argument("--reports", default=".probe-reports/dflash-stream-crash")
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()

    reports = Path(args.reports)
    reports.mkdir(parents=True, exist_ok=True)

    nonce = secrets.token_hex(4)
    prompt_short = f"[Q-{nonce}] reply with one short sentence."

    print(f"[stream-crash-probe] base={args.base_url} model={args.model}", file=sys.stderr)

    findings = {
        "base_url": args.base_url,
        "model": args.model,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "differential": {},
        "minimization": [],
    }

    client = httpx.Client()
    try:
        # ---- 1. Stream vs non-stream differential on the same body ----
        body = base_body(args.model, 64, prompt_short, True, True)
        print("\n[1] differential (same body, stream off vs on)", file=sys.stderr)
        ns = capture_nonstream(client, args.base_url, body, timeout=args.timeout)
        print(f"  nonstream: {json.dumps(ns)[:200]}", file=sys.stderr)
        st = capture_stream(client, args.base_url, body, timeout=args.timeout)
        print(f"  stream:    verdict={st.verdict()} chunks={st.sse_chunks} "
              f"content_len={st.content_total} reasoning_len={st.reasoning_total} "
              f"finish={st.finish_reason!r} saw_done={st.saw_done} "
              f"http={st.http_status} ct={st.content_type!r}", file=sys.stderr)
        if st.body_text_if_error:
            print(f"             error body: {st.body_text_if_error[:200]!r}", file=sys.stderr)
        if st.last_chunk_raw:
            print(f"             last line: {st.last_chunk_raw!r}", file=sys.stderr)
        findings["differential"] = {"nonstream": ns, "stream": asdict(st)}

        # ---- 2. Minimization sweep — vary one axis at a time ----
        print("\n[2] minimization sweep (stream:true only)", file=sys.stderr)
        sweep_cases = [
            ("max_tokens=4",   base_body(args.model,   4, prompt_short, True,  True)),
            ("max_tokens=16",  base_body(args.model,  16, prompt_short, True,  True)),
            ("max_tokens=64",  base_body(args.model,  64, prompt_short, True,  True)),
            ("max_tokens=256", base_body(args.model, 256, prompt_short, True,  True)),
            ("prompt=1ch",     base_body(args.model,  64, "?",          True,  True)),
            ("prompt=256ch",   base_body(args.model,  64, ("[Q-%s] " % nonce) + "x" * 240, True, True)),
            ("cache=false",    base_body(args.model,  64, prompt_short, False, True)),
            ("usage=false",    base_body(args.model,  64, prompt_short, True,  False)),
            ("usage=omit",     base_body(args.model,  64, prompt_short, True,  None)),
        ]
        for label, b in sweep_cases:
            cap = capture_stream(client, args.base_url, b, timeout=args.timeout)
            print(f"  {label:<18} → {cap.verdict():<10} chunks={cap.sse_chunks:<3} "
                  f"content={cap.content_total:<4} finish={cap.finish_reason!r:<10} "
                  f"http={cap.http_status} elapsed={cap.elapsed_s:.1f}s",
                  file=sys.stderr)
            findings["minimization"].append({"case": label, "body": b, "capture": asdict(cap)})
    finally:
        client.close()

    out_path = reports / f"{args.model}-stream-crash.json"
    out_path.write_text(json.dumps(findings, indent=2))
    print(f"\n[stream-crash-probe] wrote {out_path}", file=sys.stderr)

    # Final summary
    diff = findings["differential"]
    ns_ok = diff["nonstream"].get("content_len", 0) > 0
    st_verdict = StreamCapture(**diff["stream"]).verdict()
    print(
        f"\n[summary] nonstream={'OK' if ns_ok else 'BROKEN'}  "
        f"stream={st_verdict}",
        file=sys.stderr,
    )
    if ns_ok and st_verdict != "OK":
        print("  → confirms stream-vs-non-stream differential", file=sys.stderr)
        crashing = [c for c in findings["minimization"] if c["capture"]["error"] or c["capture"]["http_status"] >= 500]
        if crashing:
            sizes = [(c["case"], c["body"]["max_tokens"], len(c["body"]["messages"][0]["content"]))
                     for c in crashing]
            print(f"  → {len(crashing)} crashing case(s) in sweep", file=sys.stderr)
            for s in sizes:
                print(f"     - {s[0]} max_tokens={s[1]} prompt_chars={s[2]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
