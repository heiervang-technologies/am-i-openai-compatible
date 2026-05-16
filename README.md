# Am I OpenAI Compatible?

> A no-nonsense probe for any HTTP server that claims to speak the OpenAI API,
> plus a living catalog of how the OSS implementations actually behave.

[![Docs](https://img.shields.io/badge/docs-mkdocs--material-blue)](https://heiervang-technologies.github.io/am-i-openai-compatible/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

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
chat, reranking, layered image generation, audio extraction).
See [`docs/spec/ht-compat.md`](docs/spec/ht-compat.md).

## Quickstart

```bash
pip install am-i-openai-compatible

aioc probe http://localhost:8080 --name llama.cpp
aioc probe https://api.openai.com --name openai
aioc gap --monolith probe-llama.json --cluster probe-openai.json

# Probe HT-compat extensions (reranking, SAM3 segmentations,
# omni chat, layered images, audio-SAM extraction) alongside
# the OpenAI surface:
aioc probe http://localhost:8080 --profile ht --name llama.cpp-ht
```

Output is a per-endpoint pass / warn / fail / skip table:

```
Service     Endpoint                                Status   Detail
─────────   ─────────────────────────────────────   ──────   ──────────────────────
llama.cpp   /v1/models                              ● PASS   23 models
llama.cpp   /v1/chat/completions                    ● PASS   finish_reason=length
llama.cpp   /v1/chat/completions [stream]           ● PASS   9 chunks · DONE
llama.cpp   /v1/models/{id}                         ▲ WARN   404 — list only
llama.cpp   /v1/responses                           ○ SKIP   not implemented
llama.cpp   /v1/audio/speech                        ✖ FAIL   404
```

* `PASS` — endpoint exists, body is valid against the spec
* `WARN` — endpoint works but deviates (documented; many do)
* `FAIL` — endpoint missing or schema invalid
* `SKIP` — endpoint intentionally absent or server unreachable

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
by `aioc probe` (catalog: 27 rows, `aioc 0.3.0`).

| Target                   | Probed     | Profile         | PASS · WARN · FAIL · SKIP | Notable finding                                                       |
| ------------------------ | ---------- | --------------- | ------------------------- | --------------------------------------------------------------------- |
| OpenAI `api.openai.com`  | 2026-05-16 | openai (unauth) | 20 · 0 · 4 · 14           | `/v1/realtime` accepts unauth WS upgrade (101 then auth-walls events) |
| ht-comfy-openai (titan)  | 2026-05-16 | openai          | 6 · 4 · 14 · 0            | `/v1/images/edits` returns 500 on empty body (cloud#113)              |
| ht-comfy-openai (titan)  | 2026-05-16 | ht              | 10 · 4 · 19 · 0           | `/v1/3d/generations` + `/v1/videos` PASS Phase A; segmentations ❌    |
| lile-daemon (`:8768`)    | 2026-05-16 | openai          | 3 · 5 · 12 · 3            | chat-only; `/v1/models` 404 blocks Codex CLI discovery                |
| lile-proxy (`:8766`)     | 2026-05-16 | openai          | 0 · 14 · 5 · 1            | 501 with `<!DOCTYPE HTML>` body — breaks canonical envelope contract  |
| llama.cpp vanilla        | (fork CI)  | openai + ht     | (see fork run 25821142550) | `/v1/reranking` 501 with canonical OpenAI error envelope — HT-compat compliant |
| vLLM                     | —          | —               | —                         | deployment URL pending                                                |
| vllm-omni                | —          | —               | —                         | deployment URL pending                                                |

Full reports + per-target writeups at
[`docs/baselines.md`](docs/baselines.md). Raw JSON reports for the
maintainer host are archived under `.probe-reports/` (gitignored).

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
