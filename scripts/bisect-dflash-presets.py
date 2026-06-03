#!/usr/bin/env python3
"""Bisect which gemma-4-31b-* presets on a router-mode llama-server
exhibit the dflash empty-content bug (mission m-20260527-103737-36364b).

Dev's root cause as of 2026-05-27: prefix-cache reuse breaks the dflash
drafter — the FIRST request to a preset (cache empty) works; the SECOND
request reusing the same prompt's cache emits all-NaN logits → empty
content. `/v1/completions` first-shot accept (12.25%) was a measurement
artefact because tests began against an empty cache. The asymmetry IS
the bug.

For each preset and each endpoint (chat-completions, completions), we
fire three shots with the same minimal prompt:

  shot 1 (cold-cache):   cache_prompt=true, fresh server-side cache
  shot 2 (warm-cache):   cache_prompt=true, sent immediately after #1
                         → reuses #1's KV prefix → reproduces the bug
  shot 3 (no-cache):     cache_prompt=false → bypasses prefix reuse
                         → should always work, even on dflash

Cell encoding: glyph for each shot's content-length verdict. The
diagnostic signature for the bug is `✓ ✖ ✓` (shot 1 ok, shot 2 empty,
shot 3 ok). A `✓ ✓ ✓` row means the preset doesn't exhibit the bug.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
import time
import urllib.request
from pathlib import Path

import httpx

# Threshold for "useful content" — same as the new aioc gate.
MIN_CONTENT_LEN = 1
GLYPH = {"PASS": "✓", "FAIL": "✖", "LOOP": "↺", "ERR": "!"}


def _grade_content(prompt: str, content: str | None, err: str | None) -> tuple[str, int]:
    """ERR (transport/shape), FAIL (empty), LOOP (degenerate — content is
    just the prompt tokens looped, very few distinct chars), PASS
    (non-empty and reasonably diverse).
    """
    if err is not None:
        return ("ERR", 0)
    if content is None:
        return ("FAIL", 0)
    n = len(content)
    if n < MIN_CONTENT_LEN:
        return ("FAIL", n)
    # LOOP heuristic: collapse whitespace, count distinct non-space chars.
    # The dflash bug on /v1/completions emits "hihihihi..." — 2 distinct
    # chars. A real (even short) reply usually has 4+.
    distinct = len(set(content.lower()) - set(" \n\t.,!?"))
    if distinct <= 2 and n >= 4:
        return ("LOOP", n)
    return ("PASS", n)


def list_presets(base: str, pattern: str) -> list[dict]:
    with urllib.request.urlopen(f"{base}/v1/models", timeout=10) as r:
        data = json.load(r)
    rx = re.compile(pattern)
    out = []
    for m in data.get("data", []):
        mid = m.get("id", "")
        if not rx.search(mid) or "mmproj" in mid:
            continue
        args = " ".join(m.get("status", {}).get("args", []))
        match = re.search(r"--model\s+(\S+)", args)
        out.append(
            {
                "id": mid,
                "jinja": "--jinja" in args,
                "dflash": "--dflash" in args,
                "base": (match.group(1).split("/")[-1].replace(".gguf", "") if match else "?"),
            }
        )
    return out


def shot_chat(client: httpx.Client, base: str, model: str, prompt: str, cache_prompt: bool):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 16,
        "temperature": 0,
        "cache_prompt": cache_prompt,
    }
    try:
        r = client.post(f"{base}/v1/chat/completions", json=body, timeout=120)
    except httpx.HTTPError as e:
        return ("ERR", 0, f"http {type(e).__name__}: {e}")
    if r.status_code != 200:
        return ("ERR", 0, f"{r.status_code} {r.text[:80]!r}")
    try:
        j = r.json()
        content = j["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        return ("ERR", 0, f"shape {type(e).__name__}: {e}")
    status, n = _grade_content(prompt, content, None)
    return (status, n, (content or "")[:40])


def shot_completions(client: httpx.Client, base: str, model: str, prompt: str, cache_prompt: bool):
    body = {
        "model": model,
        "prompt": prompt,
        "max_tokens": 16,
        "temperature": 0,
        "cache_prompt": cache_prompt,
    }
    try:
        r = client.post(f"{base}/v1/completions", json=body, timeout=120)
    except httpx.HTTPError as e:
        return ("ERR", 0, f"http {type(e).__name__}: {e}")
    if r.status_code != 200:
        return ("ERR", 0, f"{r.status_code} {r.text[:80]!r}")
    try:
        j = r.json()
        text = j["choices"][0]["text"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        return ("ERR", 0, f"shape {type(e).__name__}: {e}")
    status, n = _grade_content(prompt, text, None)
    return (status, n, (text or "")[:40])


def run_three_shots(client: httpx.Client, base: str, preset: str, shotter):
    """Three shots probing the cache-reuse axis. Nonces force prompt
    uniqueness so the first shot can't accidentally hit a stale prefix
    from a prior session.

      shot 1 (cold-cache):  unique nonce N1, cache_prompt=true
                            → first time server sees N1; no prefix to reuse.
      shot 2 (warm-cache):  same nonce N1, cache_prompt=true
                            → server's prefix cache from #1 should hit.
      shot 3 (no-cache):    unique nonce N2, cache_prompt=false
                            → bypasses prefix reuse entirely.
    """
    n1 = secrets.token_hex(4)
    n2 = secrets.token_hex(4)
    prompt_a = f"[Q-{n1}] please say hi"
    prompt_b = f"[Q-{n2}] please say hi"
    schedule = [
        ("cold", prompt_a, True),
        ("warm", prompt_a, True),
        ("no-cache", prompt_b, False),
    ]
    out = []
    for label, prompt, cache in schedule:
        t0 = time.monotonic()
        status, n, snippet = shotter(client, base, preset, prompt, cache)
        dt = time.monotonic() - t0
        print(
            f"    [{label:<8} cache_prompt={cache} nonce={prompt[:14]}] "
            f"{status:<4} n={n:<3} {dt:.1f}s snippet={snippet!r}",
            file=sys.stderr,
        )
        out.append((status, n, snippet))
    return out


def render_table(matrix: dict, presets: list[dict]) -> str:
    cols = [("chat", "shot_chat"), ("completions", "shot_completions")]
    head = f"| {'preset':<46} | jinja | dflash | "
    head += " | ".join(f"{c[0]:<14}" for c in cols)
    head += " |"
    sep = "|" + "-" * 48 + "|-------|--------|" + "|".join("-" * 16 for _ in cols) + "|"
    out = [head, sep]
    for p in presets:
        row = f"| `{p['id']:<44}` | {'yes' if p['jinja'] else 'no':<5} | {'yes' if p['dflash'] else 'no':<6} |"
        for _, attr in cols:
            shots = matrix[p["id"]][attr]
            cell = "".join(GLYPH.get(s[0], "?") for s in shots)
            row += f" {cell:<14} |"
        out.append(row)
    out.append("")
    out.append("Cells encode three shots in order: **cold cache** · **warm cache** · **no cache**.")
    out.append("Bug signature is `✓✖✓` (cold ok, warm empty, no-cache ok).")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("base_url")
    ap.add_argument("--pattern", default=r"^gemma-4-31[bB]")
    ap.add_argument("--reports", default=".probe-reports/dflash-bisect")
    ap.add_argument("--out", default="-")
    args = ap.parse_args()

    reports = Path(args.reports)
    reports.mkdir(parents=True, exist_ok=True)

    presets = list_presets(args.base_url, args.pattern)
    print(f"[bisect] {len(presets)} preset(s) match {args.pattern!r}:", file=sys.stderr)
    for p in presets:
        print(
            f"  - {p['id']}  jinja={p['jinja']}  dflash={p['dflash']}  base={p['base']}",
            file=sys.stderr,
        )

    client = httpx.Client()
    matrix: dict[str, dict[str, list]] = {}
    try:
        for p in presets:
            print(
                f"\n[bisect] {p['id']} (jinja={p['jinja']}, dflash={p['dflash']})",
                file=sys.stderr,
            )
            matrix[p["id"]] = {}
            for attr, shotter in [("shot_chat", shot_chat), ("shot_completions", shot_completions)]:
                print(f"  -> {attr}", file=sys.stderr)
                matrix[p["id"]][attr] = run_three_shots(client, args.base_url, p["id"], shotter)
    finally:
        client.close()

    table = render_table(matrix, presets)
    if args.out == "-":
        print("\n" + table)
    else:
        Path(args.out).write_text(table + "\n")
        print(f"[bisect] wrote {args.out}", file=sys.stderr)

    side = reports / "_summary.json"
    side.write_text(
        json.dumps(
            {
                "base_url": args.base_url,
                "pattern": args.pattern,
                "matrix": {
                    pid: {
                        ep: [{"status": s[0], "len": s[1], "snippet": s[2]} for s in cells]
                        for ep, cells in by_ep.items()
                    }
                    for pid, by_ep in matrix.items()
                },
                "presets": presets,
                "min_content_len": MIN_CONTENT_LEN,
                "shot_sequence": [
                    "cold-cache_prompt=true",
                    "warm-cache_prompt=true",
                    "no-cache_prompt=false",
                ],
            },
            indent=2,
        )
    )
    print(f"[bisect] wrote {side}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
