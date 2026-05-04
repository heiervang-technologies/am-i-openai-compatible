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

## Quickstart

```bash
pip install am-i-openai-compatible

aioc probe http://localhost:8080 --name llama.cpp
aioc probe https://api.openai.com --name openai
aioc gap --monolith probe-llama.json --cluster probe-openai.json
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
