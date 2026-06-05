# Getting started

## Install

Not on PyPI yet — install straight from this repo:

```bash
# Latest main:
pip install git+https://github.com/heiervang-technologies/am-i-openai-compatible.git

# Pin to a tag (recommended for CI):
pip install git+https://github.com/heiervang-technologies/am-i-openai-compatible.git@v0.4.0
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
aioc probe http://localhost:8080 --name llama.cpp --report llama.json
```

`aioc probe` writes a flat JSON event list to `--report` and prints a
one-line summary on stdout:

```
probe 'llama.cpp': 27 events in 5.4s  ·  FAIL=1  PASS=20  SKIP=4  WARN=2
report: llama.json
```

For a per-endpoint table view, pipe the report through `aioc render`:

```bash
aioc render llama.json
```

```
Endpoint                        Status    Detail
──────────────────────────────  ──────    ────────────────────────────
/v1/models                      ● PASS    shape ok
/v1/chat/completions            ● PASS    shape ok
/v1/chat/completions[stream]    ● PASS    chunks=9, [DONE]=True
/v1/embeddings                  ▲ WARN    501 — endpoint is disabled
/v1/audio/speech                ▲ WARN    404 — capability not offered
/v1/audio/transcriptions        ○ SKIP    no model of kind 'asr'
...
```

`render` picks one event per endpoint by priority: FAIL > WARN > Phase
B PASS > Phase A PASS > SKIP. `/v1/embeddings` and `/v1/audio/*` are
`kind="optional"` — a 404 or 501 on them grades WARN, not FAIL.
They're capability-gated (boot flag, missing model), not
non-compliance. FAIL is reserved for `kind="core"` rows that should
always route (chat / models) or for Phase B schema mismatches against
a server that does serve the kind.

The JSON report itself is a flat list of event objects — one per
phase per endpoint, in catalog order:

```json
[
  {
    "service": "llama.cpp",
    "endpoint": "/v1/chat/completions",
    "phase": "A",
    "status": "PASS",
    "detail": "400 (route exists)",
    "method": "POST",
    "http_status": 400,
    "kind": "core",
    "group": "chat",
    "profile": "openai"
  },
  {
    "service": "llama.cpp",
    "endpoint": "/v1/chat/completions",
    "phase": "B",
    "status": "PASS",
    "detail": "shape ok",
    "method": "POST",
    "http_status": 200,
    "kind": "core",
    "group": "chat",
    "profile": "openai"
  }
]
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
