# HT-compat compatibility matrix

Sibling to the [OpenAI compatibility matrix](compatibility-matrix.md).
Rows are the HT-compat extension endpoints from
[the HT-compat spec](spec/ht-compat.md); columns are the major OSS
implementations that have started to converge on the canonical
signatures.

Run `aioc probe URL --profile ht` to populate the data for a new
server. PRs that update a cell should link the report.

Legend: ✅ pass · ⚠️ pass-with-deviation · ❌ not implemented · — out of scope

## HT-compat-1.0 endpoints

| Endpoint                            | ht-llama.cpp | vLLM omni | vanilla llama.cpp | titan-comfy-openai | OpenAI |
|-------------------------------------|--------------|-----------|-------------------|--------------------|--------|
| `/v1/reranking`                     | ⚠️            | ⚠️         | ⚠️                 | ❌                  | —      |
| `/v1/segmentations`                 | ❌            | ❌         | ❌                 | ❌                  | —      |
| `/v1/audio/segmentations`           | ❌            | ❌         | ❌                 | ❌                  | —      |
| `/v1/chat/completions` *(omni)*     | ❌            | ✅         | ❌                 | ❌                  | —      |
| `/v1/images/decompositions`         | ❌            | ❌         | ❌                 | ❌                  | —      |
| `/v1/3d/generations`                | ❌            | ❌         | ❌                 | **✅**              | —      |
| `/v1/videos`                        | ❌            | ❌         | ❌                 | ⚠️                  | —      |

## Reference implementations

The HT-compat spec aligns to one reference implementation per
endpoint. These are the upstreams we cribbed signatures from; the
matrix above tracks which servers have adopted the canonical shape.

| Endpoint                        | Reference implementation                              |
|---------------------------------|-------------------------------------------------------|
| `/v1/reranking`                 | Cohere Rerank v2 · Jina Reranker · vLLM Cohere-compat |
| `/v1/segmentations`             | Meta SAM3 (paper + reference Python)                  |
| `/v1/audio/segmentations`       | Meta SAM-Audio (paper + reference Python)             |
| `/v1/chat/completions[omni]`    | vLLM-Omni serving Qwen2.5-Omni                        |
| `/v1/images/decompositions`     | Qwen-Image-Layered via fal.ai                         |
| `/v1/3d/generations`            | TRELLIS-2 + Hunyuan3D via ComfyUI workflow shim       |
| `/v1/videos`                    | OpenAI Sora signature (HT-implemented; no OSS impls yet) |

## Scope per fork

HT-compat is a buffet, not a checklist — most forks will only
plausibly cover a subset.

| Fork              | Plausible HT-compat surface                                   |
|-------------------|---------------------------------------------------------------|
| `ht-llama.cpp`    | `/v1/reranking`. Possibly `[omni]` via proxy to ht-vllm-omni. |
| `ht-vllm-omni`    | `/v1/chat/completions[omni]`. `/v1/audio/segmentations`?      |
| `ht-vibe`         | `/v1/audio/segmentations`, future `/v1/audio/separations`.    |

A fork running `aioc probe --profile ht` on a server that only
implements a subset should set `fail-on: none` (discovery mode); the
report renders without failing the build. Flip to `fail-on: FAIL`
once the server has wired up the endpoints it claims.

## Caveats

* **Wider than typical compat matrix.** HT-compat targets model
  classes OpenAI doesn't have endpoints for, so most cells start `❌`
  by definition — the table tracks adoption rather than current
  parity.
* **The OpenAI column is `—` throughout.** HT-compat sits in OpenAI's
  gaps; if OpenAI ships a `/v1/segmentations` we'll re-evaluate.
* **`⚠️` for vLLM rerank** because vLLM's rerank endpoint is
  Cohere-compatible (no `/v1/` prefix); the response shape matches.
* **`✅` for titan-comfy-openai 3D generations** — first HT-compat
  endpoint with a working OSS implementation. Hunyuan3D-2 served via
  ComfyUI workflow shim; verified end-to-end with `aioc probe
  http://192.168.8.170:30385 --profile ht` (Phase A + Phase B both
  PASS). HTTP 202 on submission, GLB returned via `/v1/3d/generations/{id}/content`.
* **`⚠️` for titan-comfy-openai videos** — server returns 400
  requiring field name `image` rather than the spec's `image_url`.
  Tracking the impl-side alignment; not blocking matrix entry.
* **`⚠️` for llama.cpp rerank** (both forks) because `llama-server`
  ships the `/v1/reranking` route from upstream and, when booted
  *without* `--reranking`, returns 501 with the canonical OpenAI
  error envelope — the HT-compat-1.0 capability-gating contract. A
  server booted with `--reranking` and a rerank-class model would
  flip to ✅; first probe report against that config is welcome.
  Confirmed via aioc probe report from ht-llama.cpp PR #39 (run
  25821142550 against `feat/ci-aioc-compat-probe` on origin/ht).
