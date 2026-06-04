# Am I OpenAI Compatible?

> A no-nonsense probe for any HTTP server that claims to speak the OpenAI API,
> plus a living catalog of how the OSS implementations actually behave.

[![Docs](https://img.shields.io/badge/docs-mkdocs--material-blue)](https://heiervang-technologies.github.io/am-i-openai-compatible/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

![aioc demo](docs/assets/aioc-demo.gif)

> *aioc probe against a custom llama.cpp build with HT-compat
> extensions: 27 endpoints graded in 0.2s — including
> `/v1/reranking` and `/v1/chat/completions[omni]`. Source:
> [`docs/assets/aioc-demo.tape`](docs/assets/aioc-demo.tape).*

The term "OpenAI-compatible" gets used so loosely it's nearly worthless.
Every implementation — llama.cpp, vLLM, Ollama, LM Studio, TabbyAPI,
SGLang, MLC, comfy-openai shims, you name it — picks its own subset of
the surface and adds its own quirks. Some return `usage`, some don't.
Some implement `/v1/responses`, most don't. Most reject empty `messages`,
some happily 200 it back. Some honor `seed`, some pretend to.

This project gives you two things:

1. **`aioc probe URL`** — a single command that tells you which OpenAI
   endpoints a given server actually implements, which contracts it
   honors, and where it deviates. Reports as JSON; renders as a table.
2. **The compatibility docs** — an open, opinionated reference for the
   *real* OpenAI surface and an honest matrix of how the major OSS
   servers compare. PRs welcome when behavior changes.

It also ships an opinionated **HT-compat profile** —
`aioc probe URL --profile ht` — that adds endpoints for model classes
OpenAI doesn't pin yet (promptable segmentation à la SAM3, omni-modal
chat, reranking, layered image generation, audio extraction). HT-compat
**v1.1** extends this to encoder-only BERT-style tasks: `/v1/qa`,
`/v1/ner`, `/v1/classifications` (cherry-picked from the HF
`transformers` pipelines and TEI's `/predict` semantics, wrapped in
the OpenAI-style envelope already used by `/v1/reranking`). See
[`docs/spec/ht-compat.md`](docs/spec/ht-compat.md).

## Install

Not on PyPI yet — install straight from this repo:

```bash
# Latest main:
pip install git+https://github.com/heiervang-technologies/am-i-openai-compatible.git

# Pin to a tag (recommended for CI):
pip install git+https://github.com/heiervang-technologies/am-i-openai-compatible.git@v0.3.1

# Or clone for a hackable checkout:
git clone https://github.com/heiervang-technologies/am-i-openai-compatible.git
cd am-i-openai-compatible
pip install -e .
```

The composite GitHub Action takes the same git ref via its
`aioc-version` input, e.g.
`aioc-version: "git+https://github.com/heiervang-technologies/am-i-openai-compatible.git@v0.3.1"`.

Requires Python ≥ 3.10. A PyPI release isn't planned right now; if you
need one, open an issue.

## Quickstart

```bash
aioc probe http://localhost:8080 --name llama.cpp
aioc probe https://api.openai.com --name openai
aioc gap --monolith probe-llama.json --cluster probe-openai.json

# Probe HT-compat extensions (reranking, SAM3 segmentations,
# omni chat, layered images, audio-SAM extraction) alongside
# the OpenAI surface:
aioc probe http://localhost:8080 --profile ht --name llama.cpp-ht
```

`aioc probe` writes a flat JSON list to `--report` and prints a
one-line summary; `aioc render` reads that JSON back as a per-endpoint
table:

```
$ aioc probe http://chat-server:8080 --name chat-server --report report.json
probe 'chat-server': 23 events in 4.8s  ·  FAIL=12  PASS=3  SKIP=3  WARN=5
report: report.json

$ aioc render report.json --limit 6
Endpoint                        Status    Detail
──────────────────────────────  ──────    ────────────────────────────
/v1/models                      ✖ FAIL    404 — endpoint absent
/v1/models/{model}              ✖ FAIL    404 — endpoint absent
/v1/chat/completions            ● PASS    400 (route exists)
/v1/chat/completions[stream]    ● PASS    400 (route exists)
/v1/chat/completions[logprobs]  ● PASS    400 (route exists)
/v1/completions                 ✖ FAIL    404 — endpoint absent
```

`render` picks one event per endpoint by priority: FAIL > WARN > Phase
B PASS > Phase A PASS > SKIP. Status semantics:

* `PASS` — Phase A: route exists (any non-404 reply). Phase B: response
  body validates against the spec.
* `WARN` — capability-gated (404 on an `optional` row, or 501 with the
  canonical OpenAI error envelope). Server is honest about what it
  doesn't serve.
* `FAIL` — 404 on a `core` row, schema mismatch on Phase B, or a 404
  on an HT-compat `ours` row under `--profile ht`.
* `SKIP` — Phase A unreachable, or Phase B with no model of the
  required kind discoverable from `/v1/models`.

## What the prober does

Two phases per endpoint:

* **Phase A — existence.** A minimal probe (`GET`, `OPTIONS`, or empty
  `POST`) decides if the route is wired up at all. Anything other than
  `404` or connection-refused counts as "exists".
* **Phase B — signature compliance.** One minimal valid request,
  validated against a Pydantic model that matches OpenAI's response
  shape. Bodies are tiny: `max_tokens=4`, 512×512 images, 1 s of silent
  WAV. Video creation is tested via job submission only — the prober
  never waits for completion.

Total budget: **≤ 2 requests per endpoint per run**. Safe to point at a
production server on a coffee break.

## Why does this exist?

Because saying "we're OpenAI-compatible" without specifying *which
parts* is meaningless, and every blog post on the topic is six months
out of date the day it ships. The catalog in
[`endpoints.py`](src/am_i_openai_compatible/endpoints.py) is the
source of truth, the prober uses it directly, and the docs render it
unchanged. When OpenAI ships a new endpoint or an OSS server changes
behavior, you update one file.

## Baselines

What real OpenAI-compatible servers actually implement, as observed
by `aioc probe`.

| Target                   | Probed     | Profile         | PASS · WARN · FAIL · SKIP | Notable finding                                                       |
| ------------------------ | ---------- | --------------- | ------------------------- | --------------------------------------------------------------------- |
| OpenAI `api.openai.com`  | 2026-05-16 | openai (unauth) | 20 · 0 · 4 · 14           | `/v1/realtime` accepts unauth WS upgrade (101 then auth-walls events) |

The public reference baseline lives at
[`docs/baselines.md`](docs/baselines.md); contribute additional
baselines for OSS servers (llama.cpp, vLLM, Ollama, TabbyAPI, …) via
PR using the same section shape.

## Docs

Full spec walkthrough, per-implementation deep-dives, and the
compatibility matrix live at
**<https://heiervang-technologies.github.io/am-i-openai-compatible/>**.

## Contributing

Bug reports for new deviations are gold. If `aioc probe` says `PASS`
on a server that doesn't actually pass — or `FAIL` on one that should
work — open an issue with the report JSON and we'll iterate.

## License

MIT. See [LICENSE](LICENSE).
