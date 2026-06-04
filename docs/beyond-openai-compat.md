# Beyond OpenAI-compat

OpenAI's `/v1/...` surface is the de-facto floor for "what an
LLM-serving HTTP API looks like", but it has model-class gaps —
encoder tasks (QA, NER, classification), reranking, image
segmentation, omni-modal chat, 3D generation, async video jobs.
Servers that fill those gaps tend to invent their own shapes, and
some of those shapes have started to converge into informal (or in
one case, formal) standards.

This page is an honest survey. For each task, it shows:

- what the closest-thing-to-a-canonical shape is on the public
  internet (e.g. Cohere v2 rerank, HF Inference API question-
  answering),
- how OSS servers that implement the task actually wire it
  (TEI, vLLM, ComfyUI shims, …),
- where [HT-compat](spec/ht-compat.md) lands, and why.

Many OpenAI-compatible servers ship one or more of these extensions
under similar-but-not-identical names. If you implement a server,
this page is meant to make it easy to either follow a converged
convention or — if you have to invent — see which prior art exists
and which is the most-cited reference.

!!! note "What counts as a 'standard' here"
    Nothing on this page is a standard in the IETF / W3C sense.
    "Formal" means published by a vendor with a versioned reference
    page (Cohere v2). "Informal" means several independent
    implementations have converged on the same shape without a
    central authority. "Idiosyncratic" means one server's invention,
    cited so readers can identify it but not held up as a target.

---

## Reranking

**Convergence: strong.** Cohere published `/v2/rerank` with stable
field names; vLLM advertises Cohere/Jina compatibility; Voyage AI
mirrors the shape with small tweaks; Jina's rerank API uses the same
core fields. Reranking is the closest thing the post-OpenAI surface
has to an actually-agreed standard.

### Cohere v2 — `POST /v2/rerank` (formal)

**Request:**

```json
{
  "model": "rerank-v4.0-pro",
  "query": "What is the capital of the United States?",
  "documents": [
    "Carson City is the capital city of the American state of Nevada.",
    "Washington, D.C. is the capital of the United States."
  ],
  "top_n": 1
}
```

Optional: `max_tokens_per_doc` (default 4096), `priority` (default 0).

**Response:**

```json
{
  "id": "abc123",
  "results": [{"index": 1, "relevance_score": 0.95}],
  "meta": {"api_version": {...}, "billed_units": {...}}
}
```

No `model` echoed in the response body; no `usage` block (Cohere
puts billing under `meta.billed_units`); `relevance_score` is
unbounded above by spec (commonly in `[0, 1]` for cross-encoders).

### Voyage AI — `POST /v1/rerank`

Same core fields. Renames `top_n` → `top_k`. Adds
`return_documents: bool` (default `false`) — when `true`, each
result includes `document: "..."` (a bare string, not an object).
Adds `truncation: bool` (default `true`).

**Response:**

```json
{"results": [{"index": 0, "relevance_score": 0.92, "document": "..."}]}
```

No `id`, no `meta`. Flatter envelope than Cohere.

### TEI — `POST /rerank`

Source: `huggingface/text-embeddings-inference`. Renames `documents`
→ `texts`, `top_n` → (omitted — server returns all results, sorted),
`return_documents` → `return_text`. No `model` field (TEI serves one
model per process). Adds `truncate`, `truncation_direction`,
`raw_scores`.

**Request:**

```json
{"query": "What is Deep Learning?", "texts": ["...", "..."]}
```

**Response** (bare array, no envelope):

```json
[{"index": 0, "text": "...", "score": 1.0}]
```

Note `score`, not `relevance_score`. Note bare-array response.

### vLLM — `POST /v1/rerank` (and `/v2/rerank`)

Documented as Cohere and Jina compatible. Response uses Cohere's
`results: [{index, document: {text}, relevance_score}]` shape.
`top_n` optional; defaults to all documents. Notable: `document`
nests `text` under an object (matches Cohere's optional response
form when `return_documents: true`).

### HT-compat — `POST /v1/reranking`

Cherry-picked from Cohere v2 as the most-cited reference. Diverges
in three places, intentionally:

| Difference | Why |
|---|---|
| Requires `model` in the request | HT-compat servers are multi-model by convention; the field matches every other `/v1/...` body. |
| Echoes `model` in the response | OpenAI's `/v1/embeddings` and `/v1/chat/completions` envelope; reduces client-side bookkeeping. |
| `usage: {...}` block, no `meta.billed_units` | OpenAI's envelope, applied consistently across HT-compat rows. |

Field names (`query`, `documents`, `top_n`, `return_documents`,
`relevance_score`) match Cohere v2 verbatim.

---

## Sequence classification (supervised + zero-shot)

**Convergence: weak.** Each major server picks a different field
shape and response envelope. HF Inference API and TEI both come from
the same upstream (transformers pipelines) but expose the task
differently over HTTP.

### Hugging Face Inference API — `POST /models/{model}` (`text-classification` task)

The HF Inference Provider wire shape: a flat `{inputs, parameters}`
envelope, repeated across every task. The model is part of the URL,
not the body.

**Request:**

```json
{
  "inputs": "I love this product.",
  "parameters": {"function_to_apply": "softmax", "top_k": 3}
}
```

`function_to_apply` ∈ `{"sigmoid", "softmax", "none"}`.

**Response** (bare array, no envelope):

```json
[
  {"label": "POSITIVE", "score": 0.999},
  {"label": "NEGATIVE", "score": 0.001}
]
```

### HF Inference API — `zero-shot-classification`

Same `{inputs, parameters}` envelope. `parameters.candidate_labels`
is required; `hypothesis_template` and `multi_label` optional.

```json
{
  "inputs": "I have a problem with my iPhone.",
  "parameters": {
    "candidate_labels": ["urgent", "not urgent", "tech support"],
    "multi_label": false
  }
}
```

Response is `[{label, score}]` (same shape as supervised — the
upstream pipeline normalizes both paths to one).

### TEI — `POST /predict`

TEI flattens `parameters` into the top-level body (no nesting). No
`model` field (single-model server). Adds `raw_scores: bool` for
pre-activation scores. The response wraps differently for single vs
batched input:

**Request (single):**

```json
{"inputs": "I like you.", "raw_scores": false}
```

**Response (single — flat array):**

```json
[{"score": 0.95, "label": "admiration"}]
```

**Response (batched, when `inputs` is `[[...], [...]]`):**

```json
[
  [{"score": 0.95, "label": "admiration"}],
  [{"score": 0.91, "label": "joy"}]
]
```

Note `score`/`label` field order is reversed from HF (`label` first
in HF, `score` first in TEI). Functionally identical.

### vLLM — `POST /classify` (and `/v1/classify`)

vLLM ships a real OpenAI-shaped envelope here, the only encoder-task
server in this survey that does. Note the response carries
**probability vectors**, not per-label rows — clients have to map
`probs[i]` to label index themselves (or look at the top-1 via the
`label` field).

**Request:**

```json
{"model": "jason9693/Qwen2.5-1.5B-apeach", "input": "Loved it."}
```

**Response:**

```json
{
  "id": "classify-9bf17f...",
  "object": "list",
  "model": "jason9693/Qwen2.5-1.5B-apeach",
  "data": [
    {"index": 0, "label": "Default", "probs": [0.566, 0.434], "num_classes": 2}
  ],
  "usage": {"prompt_tokens": 10, "total_tokens": 10}
}
```

`object: "list"` and `data: [...]` mirror `/v1/embeddings`'s envelope.

### HT-compat — `POST /v1/classifications`

Unifies supervised and zero-shot under one endpoint; the request
distinguishes by the presence of `candidate_labels`. Response is
sorted by `score` descending — easier to consume than HF's
arbitrary order.

```json
{
  "model": "facebook/bart-large-mnli",
  "input": "The new lens has excellent low-light performance.",
  "candidate_labels": ["positive", "negative", "neutral"],
  "multi_label": false
}
```

```json
{
  "id": "classify-...",
  "model": "facebook/bart-large-mnli",
  "classifications": [
    {"label": "positive", "score": 0.94},
    {"label": "neutral",  "score": 0.05},
    {"label": "negative", "score": 0.01}
  ],
  "usage": {"total_tokens": 18}
}
```

Diverges from HF/TEI by lifting `candidate_labels` to top-level
(matches OpenAI's `/v1/embeddings` flat-body convention) and naming
the result key `classifications` (task-meaningful, matches
`/v1/moderations.results` precedent). Diverges from vLLM by
returning `[{label, score}]` rows rather than `[{probs[], label}]`
— directly consumable, no client-side index math.

---

## Extractive question answering

**Convergence: weak.** Only Hugging Face exposes QA as a stable HTTP
task; TEI doesn't have it, vLLM doesn't have it. The HF shape is
effectively the only prior art.

### HF Inference API — `question-answering`

```json
{
  "inputs": {
    "context": "Mount Everest is the highest mountain above sea level.",
    "question": "What is the highest mountain?"
  },
  "parameters": {"top_k": 1}
}
```

Parameters: `top_k`, `doc_stride`, `max_answer_len`, `max_seq_len`,
`max_question_len`, `handle_impossible_answer`, `align_to_words`.

**Response** (bare array):

```json
[{"answer": "Mount Everest", "score": 0.98, "start": 0, "end": 13}]
```

### HT-compat — `POST /v1/qa`

```json
{
  "model": "deepset/roberta-base-squad2",
  "input": {"context": "...", "question": "..."},
  "top_k": 1
}
```

Keeps HF's `(context, question)` nesting and response field names.
Diverges: nesting is under `input` (matches OpenAI's other
`/v1/...` bodies; HF uses `inputs`), parameters are flat
(no `parameters: {...}` wrapper), and the response wraps in
`{id, model, answers, usage}`. The
[spec](spec/ht-compat.md#v1qa-extractive-question-answering-v11) pins
`context[start:end] == answer` as a hard invariant — easier to
contract-test than HF's "characters of the input" wording.

A subset of `parameters` is intentionally not in v1.1:
`max_seq_len`, `max_question_len`, `doc_stride`, `align_to_words`
are implementation-tuning knobs that don't change the response
shape and can be added in a later minor without breakage.

---

## Token classification (NER)

**Convergence: weak.** HF defines the task; few servers expose it
as a first-class endpoint.

### HF Inference API — `token-classification`

```json
{
  "inputs": "Hugging Face Inc. is based in New York.",
  "parameters": {"aggregation_strategy": "simple", "ignore_labels": ["O"]}
}
```

`aggregation_strategy` ∈ `{"none", "simple", "first", "average", "max"}`
— **load-bearing**: with `"none"`, response rows carry the raw
BIO-prefixed `entity` field; with any other value, rows carry the
aggregated `entity_group` field. Two response shapes from one
endpoint.

**Response** (aggregated, bare array):

```json
[
  {"entity_group": "ORG", "score": 0.99, "word": "Hugging Face Inc.", "start": 0, "end": 17},
  {"entity_group": "LOC", "score": 0.99, "word": "New York", "start": 30, "end": 38}
]
```

**Response** (`"none"` — per-token):

```json
[
  {"entity": "B-ORG", "score": 0.99, "word": "Hugging", "start": 0, "end": 7},
  {"entity": "I-ORG", "score": 0.98, "word": "Face", "start": 8, "end": 12}
]
```

### TEI — `POST /predict` (token-classification models)

TEI re-uses `/predict` for token classification, but the response
loses the `word`/`start`/`end` context — you get just `[{score,
label}]` per token. Useful only if the client retains its own
tokenization. Not really a NER-shaped endpoint.

### HT-compat — `POST /v1/ner`

```json
{
  "model": "dslim/bert-base-NER",
  "input": "Hugging Face Inc. is based in New York.",
  "aggregation_strategy": "simple"
}
```

Keeps HF's `aggregation_strategy` semantics verbatim, including the
load-bearing entity/entity_group switch. Wraps in
`{id, model, entities, usage}`. Pins document order (not
score-sorted) — NER scores cluster near-identically and document
order is the actionable layout.

---

## Async video generation

**Convergence: partial.** Every video API in the field is async
(submit job → poll/webhook → download URL). Beyond that universal
shape, field names diverge: `prompt` vs `promptText` vs `text_prompt`;
`aspect_ratio` (`"16:9"`) vs `ratio` (`"1280:720"`) vs `size`
(`"1280x720"`); `duration` (seconds) vs `seconds` (string seconds) vs
`length` (frames). OpenAI's Sora API is the closest thing to a
formal reference but it's narrow and **scheduled for deprecation on
2026-09-24** — so HT-compat's Sora-shape pin is convergence-target
rather than tracking-an-evolving-vendor.

### OpenAI Sora — `POST /v1/videos` (formal, deprecating 2026-09-24)

Deprecation announced 2026-03-24 for shutdown 2026-09-24, per
OpenAI's [deprecations page](https://developers.openai.com/api/docs/deprecations).
The Sora consumer web/app was already discontinued 2026-04-26;
the API outlives the consumer product by five months.

JSON body for text-only generations; `multipart/form-data` when
attaching an image reference.

```json
{
  "model": "sora-2",
  "prompt": "Wide tracking shot of a teal coupe driving through a desert highway.",
  "size": "1280x720",
  "seconds": "8"
}
```

| Field | Type | Notes |
|---|---|---|
| `model` | string | `sora-2` (default) or `sora-2-pro` |
| `prompt` | string | required |
| `size` | string | width×height; e.g. `"720x1280"`, `"1920x1080"` (sora-2-pro only) |
| `seconds` | string | `"4"`, `"8"`, `"12"`, or up to `"20"` (Mar-2026 expansion) |
| `characters` | array | reusable reference IDs (Mar-2026 expansion) |

**Response** (job envelope):

```json
{
  "id": "video_68d7512d...",
  "object": "video",
  "created_at": 1758941485,
  "status": "queued",
  "model": "sora-2-pro",
  "progress": 0,
  "seconds": "8",
  "size": "1280x720"
}
```

Status: `queued` → `in_progress` → `completed` | `failed`. Poll via
`GET /v1/videos/{id}`. Download via a separate content endpoint.
Companion endpoints: `POST /v1/videos/characters`,
`POST /v1/videos/extensions`,
`POST /v1/videos/{video_id}/edits`.

### Runway — `POST /v1/image_to_video`

Different envelope, different field names, custom version header.

```json
{
  "model": "gen4_turbo",
  "promptText": "A timelapse on a sunny day with clouds flying by",
  "promptImage": "https://...jpg",
  "ratio": "1280:720",
  "duration": 5,
  "seed": 4294967295
}
```

Headers: `X-Runway-Version: 2024-11-06`, `Authorization: Bearer ...`.
Note `promptText` / `promptImage` (camelCase),
`ratio: "1280:720"` (colon-separated pixel ratio, not `:` aspect
ratio like Luma), `duration` as integer seconds. Gen-4.5 supports
text-to-video by omitting `promptImage`.

### Luma Dream Machine — `POST /dream-machine/v1/generations`

```json
{
  "prompt": "an old lady laughing underwater, wearing a scuba diving suit",
  "model": "ray-2",
  "aspect_ratio": "16:9",
  "loop": true,
  "resolution": "1080p",
  "duration": 5
}
```

Fields: `prompt`, `model`, `aspect_ratio` (colon-separated:
`"1:1"`, `"16:9"`, `"9:16"`, `"4:3"`, `"3:4"`, `"21:9"`, `"9:21"`),
`resolution` (`"540p"`/`"720p"`/`"1080p"`/`"4k"`), `duration` (5 or 9),
`loop` (bool), `keyframes: {frame0, frame1}` for image-to-video /
extend / interpolate.

**Response** carries a `state` enum (not `status`) and an `assets`
object with URLs by type:

```json
{
  "id": "123e4567-e89b-...",
  "state": "completed",
  "failure_reason": null,
  "created_at": "2023-06-01T12:00:00Z",
  "assets": {"video": "https://example.com/video.mp4"},
  "version": "ray-2",
  "request": {"prompt": "...", "aspect_ratio": "16:9", "loop": true}
}
```

The `request` echoback is unusual — clients can resume context
without keeping their own copy.

### fal.ai — queue pattern (applies to LTX, Pika, MiniMax, Kling, etc.)

fal.ai is a model aggregator; it normalizes every model under a
single queue/result shape. The same wrapper covers dozens of video
backends.

**Submit:**

```js
const { request_id } = await fal.queue.submit("fal-ai/ltx-video", {
  input: {
    prompt: "...",
    negative_prompt: "...",
    seed: 42,
    num_inference_steps: 30,
    guidance_scale: 3
  },
  webhookUrl: "https://..."
});
```

`input` is model-specific (LTX has different fields than Pika has
different fields than MiniMax). The envelope around it is universal.

**Result** (after polling `fal.queue.status` or webhook):

```json
{
  "data": {
    "video": {
      "url": "https://...",
      "content_type": "video/mp4",
      "file_name": "...",
      "file_size": 12345678
    },
    "seed": 42
  },
  "requestId": "..."
}
```

Pika 2.1+ ships via fal.ai endpoints (`fal-ai/pika/v2.1/text-to-video`)
as the canonical access path — the older `pikapikapika.io` community
endpoint still exists but is third-party.

### Replicate — `POST /v1/predictions` (predictions pattern)

Replicate uses a single endpoint for all models; the request body
identifies which model+version to run.

```json
{
  "version": "owner/model:version_id",
  "input": {"prompt": "...", "aspect_ratio": "16:9"},
  "webhook": "https://...",
  "webhook_events_filter": ["start", "output", "completed"]
}
```

Status: `starting` → `processing` → `succeeded` | `failed` |
`canceled`. Poll via `GET /v1/predictions/{prediction_id}`. Optional
`Prefer: wait=n` header on the submit blocks up to 60s, turning the
async API into pseudo-sync. Outputs are HTTPS URLs on
`replicate.delivery`; default expiry is one hour.

### HT-compat — `POST /v1/videos`

```json
{"model": "wan22-i2v", "image": "<base64>", "prompt": "..."}
```

**Response** (job envelope):

```json
{
  "id": "<job-id>",
  "model": "wan22-i2v",
  "status": "queued",
  "created": 1730000000,
  "started": null,
  "finished": null,
  "error": null
}
```

Poll via `GET /v1/videos/{id}`; fetch result bytes via
`GET /v1/videos/{id}/content` (separate path; `Content-Type:
video/mp4`).

Diverges from every alternative deliberately:

| Difference | Why |
|---|---|
| `image` accepts base64, not just a URL | SSRF safety; portable across server hardenings. |
| `status` (not `state`/`progress`) | Matches OpenAI's pre-2026 envelope conventions. |
| Separate `/content` endpoint instead of URL in response | Decouples job state from CDN delivery; same pattern as `/v1/files`. |
| No `aspect_ratio` / `size` / `duration` fields pinned | Each backend exposes different parameter sets; v1.0 keeps the surface minimal and lets servers route extras as per-model knobs. |

The catalog deliberately submits a *bad* image during the Phase B
probe so the job fails fast — we want to confirm route existence
and that the error envelope is OpenAI-canonical, not actually drive
a multi-minute generation.

---

## 3D mesh generation

**Convergence: emerging.** Every API is async (3D generation is
2–10 minutes); every API returns one or more downloadable mesh
files; most converge on GLB as the default container; the rest of
the wire shape varies. Notably the two-step workflows
(geometry-first then texture-second) are server-specific and not
yet standardized.

### Meshy — `POST /openapi/v2/text-to-3d` (and `image-to-3d`)

Two-step workflow: a fast geometry-only `preview` task, then a
texture `refine` task that re-uses the preview's task ID. Each
step returns a task ID and is polled separately.

**Preview (step 1):**

```json
{
  "mode": "preview",
  "prompt": "a low-poly fox sculpture",
  "should_remesh": true,
  "target_polycount": 30000,
  "pose_mode": "a-pose",
  "target_formats": ["glb", "fbx", "obj"]
}
```

**Refine (step 2):**

```json
{
  "mode": "refine",
  "preview_task_id": "<id from step 1>",
  "target_formats": ["glb"],
  "enable_pbr": true,
  "auto_size": true
}
```

**Submit response:** `{"result": "018a210d-8ba4-..."}` (just the ID,
no envelope).

**Poll** via `GET /openapi/v2/text-to-3d/{task_id}`. On completion,
the task object carries `model_urls` with one signed URL per
requested format:

```json
{
  "id": "018a210d-...",
  "type": "text-to-3d-preview",
  "model_urls": {
    "glb":  "https://assets.meshy.ai/.../model.glb?Expires=...",
    "fbx":  "https://assets.meshy.ai/.../model.fbx?Expires=...",
    "obj":  "https://assets.meshy.ai/.../model.obj?Expires=...",
    "mtl":  "https://assets.meshy.ai/.../model.mtl?Expires=...",
    "usdz": "https://assets.meshy.ai/.../model.usdz?Expires=..."
  }
}
```

### fal.ai TRELLIS — image-to-3D, single-step

Exposes the underlying model parameters directly (no preview/refine
split). Image-only input.

```js
const result = await fal.subscribe("fal-ai/trellis", {
  input: {
    image_url: "https://...png",
    seed: 42,
    ss_guidance_strength: 7.5,
    ss_sampling_steps: 12,
    slat_guidance_strength: 3,
    slat_sampling_steps: 12,
    mesh_simplify: 0.95,
    texture_size: "1024"
  }
});
```

`texture_size` ∈ `{"512", "1024", "2048"}`. Output is a single GLB
URL:

```json
{
  "model_mesh": {
    "url": "https://...",
    "content_type": "model/gltf-binary",
    "file_name": "...",
    "file_size": 1572864
  },
  "timings": {...}
}
```

Hunyuan3D, InstantMesh, Rodin, and other 3D models on fal.ai follow
the same `{input: {...}} → {model_mesh: {url, ...}}` shape with
model-specific input fields.

### Tripo3D — `POST /v2/openapi/task`

Single endpoint, typed by `type` field. Async task ID returned;
polling via `GET /v2/openapi/task/{task_id}` (not shown here).

```json
{
  "type": "text_to_model",
  "prompt": "a vintage leather armchair with wooden legs",
  "negative_prompt": "low quality, blurry, distorted",
  "model_version": "v2.5"
}
```

Task types include `text_to_model`, `image_to_model`,
`multiview_to_model` (the `images` array variant for 3+ angles).
Additional fields: `texture_quality`, `auto_scale`, `face_limit`.

### CSM — `POST /v3/sessions` (image-to-3D, multiview-to-3D)

A "sessions" abstraction wrapping the same async pattern with a
nested `input.settings` block for texture control.

```json
{
  "image_url": "<URL>",
  "geometry_model": "turbo",
  "input": {"settings": {"texture_model": "pbr"}}
}
```

`texture_model` ∈ `{"none", "baked", "pbr"}`. Auth via `x-api-key`
header (not Bearer). Webhook on session completion; polling via
`GET /v3/sessions/{session_id}`. Output mesh formats: `obj`, `glb`,
`fbx`, `usdz`.

### Replicate (TRELLIS, Hunyuan3D, InstantMesh hosting)

All three 3D models above are also available via Replicate's
universal predictions pattern (see Videos section). The
model-specific `input` block matches the underlying paper /
reference repo's argument names.

### HT-compat — `POST /v1/3d/generations`

```json
{
  "model": "trellis-image-large",
  "image_url": "https://example.com/source.png",
  "prompt": "a low-poly fox sculpture, game-ready",
  "output_format": "glb",
  "n": 1,
  "seed": 42
}
```

`image_url` MAY be either a `data:` URI (every server MUST accept)
or an `http(s)://...` URL (server opt-in with SSRF hardening).
`output_format` ∈ `{"glb", "obj", "ply", "usdz"}`. `texture_resolution`
optional (`1024` default, `2048`, `4096`). At least one of
`image_url` or `prompt` is required.

**Response (job submission):** HTTP **`202 Accepted`** (vs 200 — the
distinct code disambiguates "queued for async work" from "already
done"):

```json
{
  "id": "model3d-abc123",
  "object": "3d.generation",
  "created": 1234567890,
  "model": "trellis-image-large",
  "status": "queued",
  "estimated_completion_seconds": 180
}
```

**Polling** via `GET /v1/3d/generations/{id}`; on `completed`, the
envelope adds a `data` array with one entry per variant:

```json
{
  "data": [{
    "url": "https://example.com/files/model3d-abc123.glb",
    "format": "glb",
    "size_bytes": 1572864,
    "preview_image_url": "https://example.com/files/preview.png",
    "expires_at": 1234654290
  }]
}
```

Diverges from the alternatives in three ways:

| Difference | Why |
|---|---|
| One `output_format` per request, not multi-format like Meshy | Servers route to one ComfyUI graph; multi-format conversion is downstream client work. Avoids the format-product explosion. |
| 202 on submit (not 200), `status` in body | Same disambiguation OpenAI Sora uses; gives clients a clean signal to start polling. |
| `expires_at` Unix timestamp instead of "1 hour by default" | Server tells the client when to fetch by, in a machine-readable way. Matches the `audio.expires_at` field in HT-compat omni. |

`/v1/3d/generations` deliberately follows `/v1/videos`'s envelope —
both are async + URL-delivery; using the same shape lets clients
share the polling and download logic.

---

## Omni-modal chat (audio in / audio out)

**Convergence: split along an architectural fork.** Two completely
different transport models, both with serious adopters:

- **REST extension** — add audio content parts to
  `/v1/chat/completions`, return audio in
  `choices[0].message.audio.data`. Stateless per request. Works
  through any HTTP client, library, proxy, or load balancer that
  already speaks OpenAI chat. Adopted by vLLM-Omni; followed by
  HT-compat.
- **WebSocket session** — open a persistent bidirectional connection
  that carries event-typed JSON messages, with server-side session
  state, VAD-managed turn boundaries, and `interruption` events when
  the user starts speaking while the model is responding. Adopted
  by OpenAI Realtime, Google Gemini Live, ElevenLabs Conversational
  AI.

Neither pattern is a strict superset of the other. The REST shape
makes it easy to slot omni into a normal OpenAI-shaped client (same
SDK, same endpoint, optional fields); the WebSocket shape lowers
end-to-end latency and natively models barge-in. Both are real
"beyond OpenAI-compat" surfaces — they just differ on how much
state lives in the protocol.

### vLLM-Omni — REST extension on `/v1/chat/completions`

Same path as plain chat. New `modalities` field. Audio in as a
content part; audio out under `choices[0].message.audio`.

```json
{
  "model": "Qwen/Qwen2.5-Omni-7B",
  "modalities": ["text", "audio"],
  "audio": {"voice": "Cherry", "format": "wav"},
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "Describe this audio."},
        {"type": "audio_url", "audio_url": {"url": "https://example.com/clip.mp3"}}
      ]
    }
  ]
}
```

vLLM-Omni's `audio_url` mirrors the OpenAI `image_url` convention
for symmetry across modalities (`image_url`, `video_url`,
`audio_url`, `text`). The `url` field accepts either an
`http(s)://` URL the server fetches, or a local file path that
the client SDK auto-encodes to a `data:` URI before sending.
**Not** the OpenAI Audio API's `input_audio` content type with
inline base64 — that's a different convention. (HT-compat picks
`input_audio` instead; see below.)

`modalities` ∈ `{["text"], ["audio"], ["text","audio"]}` (text-only
skips the audio-generation stages for lower latency). Available
voices on the reference Qwen2.5-Omni serve are `Cherry`, `Ethan`,
`Serena`, `Chelsie`. Input audio formats supported: `mp3`, `wav`,
`ogg`, `flac`, `m4a`.

Response carries both text and audio when `modalities` includes
both:

```json
{
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "The audio is a piano arpeggio.",
      "audio": {
        "id": "audio-...",
        "data": "<base64 wav>",
        "format": "wav"
      }
    }
  }]
}
```

Streaming: standard SSE, with `delta.audio.data` (base64 chunks)
interleaved with `delta.content` (text). The reference
implementation doesn't guarantee codec-aligned audio chunk
boundaries — clients concatenate `data` across chunks before
decoding.

**Caveat:** standard upstream vLLM only supports the thinker
(text-out only) for Qwen-Omni models. Audio output requires
**vLLM-Omni** (the separate fork project under `vllm-omni`) or
vLLM ≥ source-built from late-April 2025.

### OpenAI Realtime — WebSocket session

Connect:

```
wss://api.openai.com/v1/realtime?model=gpt-realtime-2
Authorization: Bearer $OPENAI_API_KEY
```

The session is event-typed JSON in both directions. Key events:

| Direction | Event type | Purpose |
|---|---|---|
| client → server | `session.update` | configure model/instructions/voice/tools/VAD; server echoes back `session.updated` |
| client → server | `input_audio_buffer.append` | append base64-encoded PCM16 audio (24 kHz) to the input buffer; up to 15 MiB per event |
| client → server | `input_audio_buffer.commit` | finalize the input buffer (skipped under server VAD) |
| client → server | `response.create` | request a response; alternative to letting VAD trigger |
| server → client | `response.audio.delta` | streaming audio output (base64 PCM16 24 kHz) |
| server → client | `response.audio_transcript.delta` | text transcript of the model's speech |
| server → client | `response.done` | turn complete |

Session state lives server-side for the duration of the connection.
If the WebSocket drops, the session is lost — there is no resume
protocol. Clients implement their own reconnect + replay-last-turn.

Example `input_audio_buffer.append`:

```json
{
  "event_id": "event_456",
  "type": "input_audio_buffer.append",
  "audio": "<base64 PCM16 24 kHz>"
}
```

OpenAI recommends WebRTC (not raw WebSocket) for browser and mobile
clients; the WebSocket path is positioned as server-to-server.

### Google Gemini Live — WebSocket session

Connect:

```
wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key=$KEY
```

Setup-then-stream pattern. The client opens the connection, sends a
`setup` message, waits for `setupComplete` from the server, then
streams audio.

```json
{
  "setup": {
    "model": "models/gemini-3.1-flash-live-preview",
    "generation_config": {
      "response_modalities": ["AUDIO"],
      "speech_config": {
        "voice_config": {"prebuilt_voice_config": {"voice_name": "Kore"}}
      }
    },
    "system_instruction": {"parts": [{"text": "You are a helpful assistant."}]}
  }
}
```

Audio in: `realtimeInput.audio` with `mimeType: "audio/pcm;rate=16000"`
(PCM16, 16 kHz):

```json
{
  "realtimeInput": {
    "audio": {"data": "<base64>", "mimeType": "audio/pcm;rate=16000"}
  }
}
```

Audio out: `serverContent.modelTurn.parts[].inlineData.data` (PCM16
at 24 kHz — note the sample-rate asymmetry vs OpenAI Realtime's
symmetric 24 kHz in/out).

Distinct from OpenAI: separate `realtimeInput` (high-frequency
streaming) and `clientContent` (discrete turns with `turnComplete`)
message types. `realtimeInput` doesn't guarantee ordering across
modality streams — audio, video, and text can interleave however
the client wants.

### ElevenLabs Conversational AI — WebSocket (agent-flavored)

Connect:

```
wss://api.elevenlabs.io/v1/convai/conversation?agent_id={agent_id}
```

Higher-level than the OpenAI/Gemini WebSocket APIs — wraps the
session in agent metaphor (system prompt, voice, tools live on the
agent, configured via dashboard or passed as
`conversation_config_override`). Event types focus on conversation
lifecycle rather than buffer manipulation:

| Direction | Event type | Purpose |
|---|---|---|
| client → server | `conversation_initiation_client_data` | start session with optional config overrides + dynamic variables |
| client → server | `user_audio_chunk` | base64 PCM audio |
| client → server | `multimodal_message` | text + file reference (added 2026) |
| server → client | `conversation_initiation_metadata` | session ID, audio formats |
| server → client | `user_transcript` | live ASR of user speech |
| server → client | `agent_response_complete` | turn fully delivered including any tool-call chains (added 2026) |
| server → client | `interruption` | user started talking; client should stop playback immediately |
| server → client | `guardrail_triggered` | safety policy fired (added 2026) |

Protocol is published as an AsyncAPI 2.6 specification — typed
SDKs (TypeScript, Python, React) are generated from it.

### HT-compat — `POST /v1/chat/completions[omni]`

Same REST path as plain chat (NOT a new endpoint). HT-compat picks
the REST-extension side of the architectural fork. Rationale: any
HTTP client that already speaks OpenAI chat works without WS
infrastructure; load balancers and proxies don't need WS support;
retries are normal HTTP retries; observability is HTTP observability.

Request and response shape match vLLM-Omni's top-level fields
(`modalities`, `audio: {voice, format}`, `choices[0].message.audio`)
but diverge on the audio-input content-part type:

```json
{
  "model": "qwen2.5-omni-7b",
  "modalities": ["text", "audio"],
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "Describe this audio."},
      {"type": "input_audio", "input_audio": {"data": "<base64>", "format": "wav"}}
    ]
  }],
  "audio": {"voice": "alloy", "format": "wav"}
}
```

Differences from vLLM-Omni — three intentional, one historical:

| Difference | Why |
|---|---|
| `input_audio` content part with inline base64 (vs vLLM-Omni's `audio_url` with URL or auto-base64'd file path) | HT-compat mirrors OpenAI Audio's `input_audio` convention rather than extending `image_url`'s symmetry. Clients targeting both OpenAI and HT-compat reuse the same content-part shape; servers that want vLLM-Omni compatibility ship an additional translator path. (The choice predates this survey; v1.2 may add `audio_url` acceptance as an alias.) |
| `input_audio.format` MUST accept `wav`/`mp3`/`flac`/`ogg`/`m4a` | Pinned set across HT-compat servers — no surprises about container support. |
| Unsupported `modalities` value → **501** (not 400) | "Capability gap" vs "bad input"; matches the rest of HT-compat's 501-with-envelope convention. |
| Response `audio.expires_at` is a Unix timestamp | Machine-readable retention contract; same as `/v1/3d/generations`'s `expires_at`. |

Streaming follows OpenAI SSE with one extension: `delta.audio.data`
(base64 chunks) interleaved with `delta.content`. Codec-aligned
chunk boundaries are **implementation-defined in v1.0** — clients
concatenate before decoding. Pinning aligned framing is a v1.2 item.

Multi-turn audio reuse (`previous_item_id` / `audio.id` echo back)
is **not** in v1.0 — every turn re-`base64`s the bytes. Reserved
for v1.2 once the convention stabilizes (OpenAI Realtime, Gemini
Live, and ElevenLabs all expose this differently today).

### When to pick which

| Constraint | REST extension | WebSocket session |
|---|---|---|
| End-to-end latency under 500 ms | ✗ — request/response round-trip dominates | ✓ — server-side VAD + streaming |
| Barge-in / interruptions | ✗ — model-side is stateless | ✓ — first-class `interruption` event |
| Existing OpenAI SDK works | ✓ — extra fields in a normal POST | ✗ — different transport entirely |
| Server infrastructure (LB, proxies, WAF) | ✓ — normal HTTP | ✗ — WS-aware everything |
| Retries / debugging | ✓ — replay any request | ✗ — session state is connection-scoped |
| Server-side session continuity | ✗ — client carries context | ✓ — built in |

HT-compat-1.0 commits to the REST extension because every OpenAI-
compat server can implement it as a small additive change to their
existing chat endpoint. A future HT-compat WebSocket profile for
session-scoped voice is plausible (the
[v1.0 spec](spec/ht-compat.md#v1chatcompletionsomni-omni-modal-chat)
notes it as out of scope; `/v1/realtime` is OpenAI's path and
HT-compat tracks it as `ext` rather than adopting an opinionated
shape over it).

---

## Other "beyond OpenAI-compat" surface

Where convergence is weak or absent, [HT-compat](spec/ht-compat.md)
proposes a shape and points at the one or two implementations that
implement it.

| Task | Closest reference | HT-compat | Notes |
|---|---|---|---|
| Image segmentation (promptable) | Meta SAM3 (Python reference) | `/v1/segmentations` — multipart with `image` + `prompts` JSON | Convergence: none; HT-compat is the first HTTP shape. Replicate and fal.ai host SAM2 via their generic prediction wrappers, but neither pins a SAM-specific signature. |
| Audio extraction (promptable) | Meta SAM-Audio (Python reference) | `/v1/audio/segmentations` | Convergence: none. |
| Layered image generation | Qwen-Image-Layered | `/v1/images/decompositions` | Convergence: none. fal.ai and Replicate host this through their generic shape — no layer-specific signature pinned anywhere. |

Audio source separation (Demucs-style), music generation (MusicGen),
SAM3-video, and per-model `x_ht_compat` capability advertisement are
deferred to a future HT-compat release — see the
[deferred section of the spec](spec/ht-compat.md#deferred-to-v12).

---

## Patterns the survey makes obvious

- **Envelope discipline differs.** OpenAI wraps every list response
  in `{id, model, data: [...], usage}` (embeddings) or
  `{id, model, choices: [...], usage}` (chat). HF and TEI return
  bare arrays. Cohere v2 wraps in `{id, results, meta}`. vLLM picks
  envelope-or-bare per endpoint. HT-compat picks the OpenAI envelope
  consistently — predictable for clients, even if it adds bytes.
- **Field naming for the result key matters.** When the result is
  task-meaningful (answers, entities, classifications, results),
  naming the key after the task documents intent in the wire shape.
  Generic `data` works for embeddings (where each row is
  task-agnostic) but obscures the task when the rows have semantic
  structure.
- **Parameters: flat vs nested.** HF's `{inputs, parameters}` ages
  poorly when you add a `model` field — now you have three
  top-level keys and an awkward `parameters` bag. OpenAI never
  introduced a `parameters` nesting and HT-compat follows that.
- **Multi-input batching is unsolved.** HF uses `inputs: [...]`,
  TEI uses `inputs: [[...]]` for some tasks, vLLM and Cohere use
  `documents` arrays for rerank specifically. HT-compat 1.1 punts
  on this — v1.1 servers MUST `400` on array-valued `input` rather
  than guess.
- **Async is universal for media generation; everything else
  diverges.** Every video and 3D API surveyed is async (submit →
  poll/webhook → download). Beyond that, field names are
  inconsistent (`prompt` vs `promptText` vs `text_prompt`;
  `aspect_ratio` vs `ratio` vs `size`; `status` vs `state`),
  status enums differ (`queued/in_progress/completed/failed` vs
  `starting/processing/succeeded/failed/canceled` vs
  `completed/failure_reason`), and output delivery splits between
  signed URLs in the response (Luma, Runway, Replicate, fal.ai)
  and a separate content endpoint (OpenAI Sora, HT-compat). The
  async contract converged; the everything-else didn't.
- **Aggregators (fal.ai, Replicate) are de-facto standardization
  layers.** When dozens of model authors ship via the same
  aggregator, the aggregator's `{input: {...}} → {output: {...}}`
  envelope becomes the lingua franca even though the inner `input`
  fields stay model-specific. Many "Pika API" or "Hunyuan3D API"
  guides on the public internet are documenting fal.ai's wrapper,
  not the model's native HTTP surface (most of these models don't
  have one). An HT-compat-compliant server can treat these
  aggregator envelopes as one more inbound shape to translate from
  — easier than writing per-model bridge code.
- **Two-step workflows are server-specific.** Meshy's
  preview → refine split exposes the cost/quality tradeoff
  directly; fal.ai's TRELLIS does it all in one step; Tripo3D's
  task-type field encodes the variant up front. None of these
  patterns is dominant. HT-compat picks single-step and lets
  servers expose preview-only as a model variant (e.g.
  `trellis-preview` vs `trellis-image-large`) rather than as a
  workflow stage in the wire shape.
- **Real-time voice forked the transport.** Every other extension
  in this survey stayed on HTTP request/response. Real-time voice
  split: REST-extension (vLLM-Omni, HT-compat) on one side,
  WebSocket session (OpenAI Realtime, Gemini Live, ElevenLabs) on
  the other. The constraint is latency — barge-in needs round-trip
  budget tighter than a normal HTTP request can deliver. Servers
  picking the REST side optimize for SDK reuse and infrastructure
  compatibility; servers picking the WebSocket side optimize for
  latency and server-managed session state. Neither is strictly
  better; they pay different prices.

---

## References

**Encoder + reranking:**

- Cohere v2 rerank: <https://docs.cohere.com/v2/reference/rerank>
- Voyage AI rerank: <https://docs.voyageai.com/reference/reranker-api>
- TEI source (request/response structs):
  <https://github.com/huggingface/text-embeddings-inference/blob/main/router/src/http/types.rs>
- vLLM scoring/rerank/classify usage docs:
  <https://docs.vllm.ai/en/latest/models/pooling_models/scoring/>,
  <https://docs.vllm.ai/en/latest/models/pooling_models/classify/>
- HF Inference API tasks (per-task pages under
  <https://huggingface.co/docs/api-inference/tasks/>):
  question-answering, token-classification, text-classification,
  zero-shot-classification.

**Video generation:**

- OpenAI Sora video API:
  <https://platform.openai.com/docs/guides/video-generation>
- Runway API: <https://docs.dev.runwayml.com/api/>
- Luma Dream Machine API: <https://docs.lumalabs.ai/docs/api>
- fal.ai LTX Video model card:
  <https://fal.ai/models/fal-ai/ltx-video/api>
- Replicate predictions framework:
  <https://replicate.com/docs/reference/http>

**3D mesh generation:**

- Meshy text-to-3D + image-to-3D:
  <https://docs.meshy.ai/en/api/text-to-3d>
- fal.ai TRELLIS: <https://fal.ai/models/fal-ai/trellis/api>
- Tripo3D OpenAPI: <https://apidog.com/blog/how-to-use-tripo-3d-api/>
- CSM API: <https://docs.csm.ai/>

**Omni-modal chat:**

- OpenAI Realtime API events:
  <https://platform.openai.com/docs/api-reference/realtime-client-events>
- Google Gemini Live API:
  <https://ai.google.dev/api/live>
- ElevenLabs Conversational AI WebSocket:
  <https://elevenlabs.io/docs/eleven-agents/api-reference/eleven-agents/websocket>
- vLLM-Omni online serving examples:
  <https://docs.vllm.ai/projects/vllm-omni/en/latest/user_guide/examples/online_serving/qwen2_5_omni/>

**HT-compat spec:** [spec/ht-compat.md](spec/ht-compat.md).

If you maintain a server that implements one of these extensions and
the wire shape isn't reflected here, open a PR adding your shape's
side-by-side entry; the goal of this page is the same as
`docs/baselines.md` — to make the actual landscape visible.
