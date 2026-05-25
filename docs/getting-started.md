# Getting started

## Install

Not on PyPI yet — install straight from this repo:

```bash
# Latest main:
pip install git+https://github.com/heiervang-technologies/am-i-openai-compatible.git

# Pin to a tag (recommended for CI):
pip install git+https://github.com/heiervang-technologies/am-i-openai-compatible.git@v0.3.1
```

Or, from a checkout (recommended for development):

```bash
git clone https://github.com/heiervang-technologies/am-i-openai-compatible.git
cd am-i-openai-compatible
pip install -e ".[dev]"
```

Requires Python ≥ 3.10. A PyPI release isn't planned right now; if you
need one, open an issue.

That registers two console scripts:

```bash
aioc --version
am-i-openai-compatible --version   # same thing, longer name
```

## Probe a server

```bash
aioc probe http://localhost:8080 --name llama.cpp
```

Output:

```
[A] /v1/models                         GET    200  PASS  23 models
[A] /v1/chat/completions               POST   400  PASS  exists (validation reply)
[B] /v1/chat/completions               POST   200  PASS  finish_reason=length
[B] /v1/chat/completions [stream]      POST   200  PASS  9 chunks · DONE
[A] /v1/embeddings                     POST   501  WARN  capability gated — boot with --embeddings
[A] /v1/audio/speech                   POST   404  WARN  capability not offered
...
Summary: 18 PASS, 3 WARN, 0 FAIL, 6 SKIP  →  COMPLIANT WITH WARNINGS
```

`/v1/embeddings` and `/v1/audio/*` are `kind="optional"` — a 404 or 501
on them grades WARN, not FAIL. They're capability-gated (boot flag,
missing model), not non-compliance. FAIL is reserved for catalog rows
that should always route (the chat / models surface) or for Phase B
signature mismatches against a server that does serve the kind.

Save the report:

```bash
aioc probe http://localhost:8080 --name llama.cpp --report llama.json
```

The JSON shape:

```json
{
  "service": "llama.cpp",
  "base_url": "http://localhost:8080",
  "started_at": "2026-05-04T18:30:00Z",
  "finished_at": "2026-05-04T18:30:14Z",
  "events": [
    {
      "service": "llama.cpp",
      "endpoint": "/v1/chat/completions",
      "phase": "B",
      "status": "PASS",
      "detail": "finish_reason=length",
      "method": "POST",
      "http_status": 200,
      "kind": "core",
      "group": "chat"
    },
    ...
  ],
  "summary": {"PASS": 18, "WARN": 2, "FAIL": 1, "SKIP": 6}
}
```

## Compare two reports

The `gap` subcommand is useful when you have a "monolith" surface
(say, a unified ingress) and want to know what's missing relative to
a richer per-service report:

```bash
aioc gap --monolith mono.json --cluster full.json --format markdown -o GAP.md
```

It produces a per-endpoint side-by-side and a "what's missing in the
monolith" summary suitable for issue tracking.

## Browse the spec

The catalog the prober uses is one Python file. You can read it
directly:

```bash
aioc spec
aioc spec --group chat
aioc spec --json
```

Or explore the [canonical surface](spec/canonical-surface.md) page,
which renders the same data with prose context.

## What if my server needs auth?

Set `OPENAI_API_KEY` (or `AIOC_API_KEY`) in your environment; the
prober forwards it as `Authorization: Bearer …` to every request.

## What if my server lives behind a custom path prefix?

Pass the full prefix in `--base-url`:

```bash
aioc probe https://gateway.example.com/inference/v1-proxy
```

The prober treats your `--base-url` as the root and appends the
catalog paths verbatim. So if your server publishes
`/inference/v1-proxy/v1/chat/completions`, the example above is right.
