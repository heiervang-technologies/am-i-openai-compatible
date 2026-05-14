# HT-compat — Heiervang Technologies API extension

> **HT-compat-1.0** — opinionated `/v1/...` signatures for model classes
> OpenAI doesn't yet pin. Reference layer for OSS forks (`ht-llama.cpp`,
> downstream vLLM patches, etc.) so clients can be written once and
> retarget across implementations.

## Why this exists

`am-i-openai-compatible` (`aioc`) probes whether a server honors
OpenAI's HTTP surface. It works because OpenAI defined the signature
first — there is something to be "compatible" with.

But OpenAI's surface has *model-class* gaps. There is no canonical
`/v1/...` for:

| Model class | Reference model(s) | OpenAI status |
|---|---|---|
| Promptable segmentation | SAM, SAM2, SAM3 (Meta) | no endpoint |
| Promptable audio extraction | SAM-Audio (Meta) | no endpoint |
| Omni-modal chat (audio+image in, audio+text out) | Qwen2.5-Omni, MiniCPM-o | no endpoint (Realtime API is WS-only) |
| Layered image generation | Qwen Image Layered | no endpoint |
| Reranking | Cohere rerank, BGE, Jina | no endpoint |

For each gap, OSS implementations diverge wildly — or ship Python
inference and no HTTP layer at all. **HT-compat publishes opinionated
signatures so forks can converge.** A server is HT-compat-1.0 if it
implements the endpoints below to the letter, including the response
shapes and the canonical error envelope.

This is **additive**. HT-compat servers are still OpenAI-compatible
for the OpenAI surface; the HT endpoints sit alongside `/v1/chat/...`
etc. and follow the same conventions (JSON, `Authorization: Bearer`,
`{model}` field at top of every request body).

## Probe with aioc

```bash
aioc probe http://your-server:8080 --profile ht
```

The `ht` profile probes the OpenAI catalog **plus** the HT extension
rows. A 404 on an HT row counts as FAIL (the server claims HT-compat
but is missing a required endpoint). Under the default `openai`
profile these rows are SKIPped.

## Versioning

HT-compat uses semantic-version-style strings. The current version is
**HT-compat-1.0**. Servers SHOULD advertise compliance with:

```
X-HT-Compat: 1.0
```

on every response from an HT endpoint. Clients MAY send the same
header on requests to declare which version they expect.

A v1.1 may add endpoints (v1 of the spec lists candidates below) but
will not remove or break v1.0 signatures.

## Error envelope (required)

HT-compat servers MUST return errors in OpenAI's canonical envelope:

```json
{
  "error": {
    "message": "...",
    "type": "invalid_request_error",
    "param": "documents",
    "code": "invalid_value"
  }
}
```

`message` and `type` are required. `param` and `code` SHOULD be set
when applicable. The FastAPI default of `{"detail": "..."}` is **not**
compliant — wrap it.

A 501 response MAY include the error envelope to explain why a
capability is disabled (mirrors llama-server's
`501 — This server does not support embeddings`). HT-compat servers
that capability-gate one of the endpoints below MUST return 501 (not
404) with a self-describing message.

## Capability negotiation

A server that implements a strict subset of HT-compat-1.0 (e.g. only
reranking) SHOULD still advertise `X-HT-Compat: 1.0` and return 501
with an explanatory error envelope on the unsupported endpoints. This
lets clients soft-detect partial compliance.

`GET /v1/ht/capabilities` is reserved for v1.1; its absence in v1.0 is
deliberate — discover by trying the endpoints.

---

## Endpoints

### `/v1/reranking` — text reranking

**Aligned with:** Cohere Rerank v2, Jina Reranker, vLLM's Cohere-compatible
endpoint. Mature de-facto convention; HT-compat adopts it verbatim
with `/v1/` prefix for consistency.

**Request**

```http
POST /v1/reranking
Content-Type: application/json
```

```json
{
  "model": "bge-reranker-v2-m3",
  "query": "what is OpenAI compatibility",
  "documents": ["...", "..."],
  "top_n": 10
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `model` | string | yes | model id, from `/v1/models` |
| `query` | string | yes | the query to rank against |
| `documents` | array of string | yes | candidate documents |
| `top_n` | integer | no | return only the top-N (default: all) |
| `return_documents` | boolean | no | include original text in response (default false) |

**Response**

```json
{
  "id": "rerank-...",
  "model": "bge-reranker-v2-m3",
  "results": [
    {"index": 3, "relevance_score": 0.91},
    {"index": 0, "relevance_score": 0.62}
  ],
  "usage": {"total_tokens": 142}
}
```

`results` is sorted by `relevance_score` descending. `index` references
position in the request `documents` array. `usage` is optional but
SHOULD be included for cost-tracking.

When the request sets `return_documents: true`, each result MUST also
include the original document under `document.text` (Cohere v2
convention):

```json
{"index": 3, "relevance_score": 0.91, "document": {"text": "..."}}
```

`id` is an implementation-defined string (the `rerank-...` prefix used
in the example is illustrative, not normative). The same convention
applies to `seg-...`, `audio-seg-...`, `imgdecomp-...`, and
`chatcmpl-...` ids throughout this spec.

---

### `/v1/segmentations` — promptable image segmentation

**Aligned with:** Meta SAM3 (image+video segmentation, multi-prompt).
SAM3 itself has no REST API yet; HT-compat proposes one. Single image
in v1.0; video deferred to v1.1 (`/v1/video/segmentations`).

**Request**

`multipart/form-data` with an image part and a JSON `prompts` part:

```http
POST /v1/segmentations
Content-Type: multipart/form-data
```

Fields:

| Field | Type | Required | Notes |
|---|---|---|---|
| `model` | string | yes | e.g. `sam3` |
| `image` | file | yes | PNG / JPEG / WebP |
| `prompts` | JSON string | yes | array of prompt objects (see below) |
| `output_format` | string | no | `"rle"` (default), `"png"`, `"polygon"` |

A prompt is one of:

```json
{"type": "point", "x": 0.5, "y": 0.5, "label": 1}
{"type": "box",   "x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.4}
{"type": "text",  "value": "the red cup"}
{"type": "mask",  "value": "<base64 PNG>"}
```

Coordinates are normalized `[0, 1]`. `label: 1` means foreground,
`label: 0` means background-exclusion.

> **Deliberate divergence from SAM reference implementations.** The
> Python SAM/SAM2/SAM3 reference impls use absolute pixel coordinates.
> HT-compat normalizes to `[0, 1]` so client code stays
> resolution-independent — clients shouldn't have to ship image
> dimensions alongside prompts. Servers MUST scale internally.

All prompts in a single request collapse to one object query (SAM
convention). The response returns `masks` for that single query;
clients that want multiple independent queries SHOULD make multiple
requests. Future v1.1 may add a `prompt_index` echo if multi-query
batching becomes worth supporting.

**Response**

```json
{
  "id": "seg-...",
  "model": "sam3",
  "masks": [
    {
      "mask": "<base64 PNG of binary mask>",
      "bbox": {"x1": 0.12, "y1": 0.09, "x2": 0.38, "y2": 0.41},
      "score": 0.94,
      "instance_id": 0
    }
  ]
}
```

If `output_format: "rle"`, `mask` is a **compressed COCO-RLE string**
(the `counts` string form, as produced by `pycocotools.mask.encode`;
not the uncompressed-counts-list variant). If `output_format:
"polygon"`, `mask` is an array of `[x, y]` vertices in normalized
`[0, 1]` coordinates.

---

### `/v1/audio/segmentations` — promptable audio extraction

**Aligned with:** Meta SAM-Audio. Same one-prompt-many-outputs
philosophy as SAM3 but for audio sources. No REST convention exists
yet; HT-compat proposes one.

**Request**

`multipart/form-data` with an audio file and a JSON prompt:

```http
POST /v1/audio/segmentations
Content-Type: multipart/form-data
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `model` | string | yes | e.g. `sam-audio` |
| `file` | file | yes | WAV / MP3 / FLAC / OGG |
| `prompt` | JSON string | yes | a prompt object (see below) |
| `response_format` | string | no | `"wav"` (default), `"mp3"`, `"flac"` |

A prompt is one of:

```json
{"type": "text", "value": "the singing voice"}
{"type": "span", "start_ms": 1200, "end_ms": 1850}
{"type": "exemplar", "value": "<base64 reference clip>"}
```

All timings in this endpoint (`start_ms`, `end_ms`) use milliseconds,
matching the convention OpenAI's Realtime API uses for `audio_end_ms`
etc. Don't mix in seconds.

**Response**

```json
{
  "id": "audio-seg-...",
  "model": "sam-audio",
  "sources": [
    {
      "audio": "<base64-encoded WAV>",
      "format": "wav",
      "label": "vocals",
      "score": 0.88,
      "source_id": 0
    }
  ]
}
```

`format` MUST echo the container of the returned `audio` bytes
(matches `response_format` from the request unless transcoding
failed; never leave a client guessing during demux). `label` is
free-text describing the source (`"vocals"`, `"speech"`, `"barking"`,
etc.). `sources` is one element by default; multi-output models MAY
return several.

---

### `/v1/chat/completions[omni]` — omni-modal chat

**Aligned with:** vLLM-Omni's Qwen2.5-Omni serving. This is **not a
new path** — it's a use of `/v1/chat/completions` with new content
types and the `modalities` field. HT-compat-1.0 says: if you accept
multi-modal in/out, you do it with this exact shape.

**Request**

```http
POST /v1/chat/completions
Content-Type: application/json
```

```json
{
  "model": "qwen2.5-omni-7b",
  "modalities": ["text", "audio"],
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "Describe this audio."},
        {
          "type": "input_audio",
          "input_audio": {"data": "<base64 WAV>", "format": "wav"}
        }
      ]
    }
  ],
  "audio": {"voice": "alloy", "format": "wav"}
}
```

Content-part types HT-compat-1.0 accepts (in addition to OpenAI's
`text` and `image_url`):

| Type | Inner shape |
|---|---|
| `input_audio` | `{"data": "<base64>", "format": <see below>}` |
| `input_video` | `{"data": "<base64>", "format": "mp4"\|"webm"}` |

`input_audio.format` accepts `"wav"`, `"mp3"`, `"flac"`, `"ogg"`,
`"m4a"`. Servers MAY accept additional containers but MUST accept
those five (matches vLLM-Omni's surface). An unsupported `format`
MUST return **400** with `error.code: "unsupported_audio_format"`.
An unsupported `modalities` value (e.g. `"audio"` on a server that
only does text) MUST return **501** with a self-describing
`error.message`.

Top-level fields:

| Field | Purpose |
|---|---|
| `modalities` | `["text"]`, `["audio"]`, or `["text", "audio"]`. Default `["text"]`. |
| `audio` | `{voice, format}` — required when `modalities` includes `"audio"`. |

`audio.voice` is implementation-defined. HT-compat does **not** pin
the OpenAI voice set (`alloy`, `echo`, `fable`, `onyx`, `nova`,
`shimmer`) because several reference implementations
(notably `ht-llama.cpp`'s ref-audio-clone TTS) use arbitrary file
names instead of a fixed catalog. Clients SHOULD enumerate available
voices via `/v1/audio/voices` and pass one of the returned ids. A
server that gets a voice name it doesn't know MUST return **400**
with `error.code: "unknown_voice"`.

`audio.format` accepts `"wav"`, `"mp3"`, `"flac"`, `"ogg"`, `"m4a"`,
mirroring the input formats.

**Response**

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "model": "qwen2.5-omni-7b",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "The audio is a piano arpeggio.",
        "audio": {
          "id": "audio-...",
          "data": "<base64 WAV>",
          "format": "wav",
          "expires_at": 1234567890
        }
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {"prompt_tokens": 42, "completion_tokens": 18, "total_tokens": 60}
}
```

When `modalities` includes `"audio"`, `choices[0].message.audio` MUST
be populated. The text transcript SHOULD still appear in
`choices[0].message.content` for clients that ignore audio.

In HT-compat-1.0, the response `audio.id` is an opaque identifier
that clients MAY surface for logging but MUST NOT echo back in
subsequent turns — every audio reference in a follow-up request is a
full re-`base64` of an `input_audio` content part. Multi-turn
audio-id reuse (analogous to OpenAI Realtime's `previous_item_id`)
is reserved for v1.1.

`audio.expires_at` is a Unix timestamp after which the server is no
longer obligated to retain the audio bytes. Clients that need a
durable copy MUST persist the bytes locally before then.

**Streaming**

Streaming follows OpenAI's SSE format with one extension: audio
deltas appear as `delta.audio.data` (base64 chunks) interleaved with
text deltas. `[DONE]` rules unchanged. In HT-compat-1.0, the framing
of audio chunks (codec block boundaries vs arbitrary base64 slices)
is **implementation-defined** — clients MUST concatenate `data`
across chunks before decoding the container. v1.1 may pin
codec-aligned framing once a reference impl exists to crib from.

---

### `/v1/3d/generations` — image/text-to-3D mesh generation

**Aligned with:** TRELLIS-2 (Microsoft), Hunyuan3D (Tencent), InstantMesh.
Async job submission — 3D generation is minutes-scale; sync responses
would block clients. Mirrors the `/v1/videos` job-submission pattern
in this spec.

**Reference backend:** ComfyUI is the most common OSS execution
backend for these models (via the ComfyUI-3D-Pack, TRELLIS-ComfyUI,
and Hunyuan3D-ComfyUI node sets). An HT-compat server typically
ships a thin HTTP shim that translates `/v1/3d/generations` calls
into a ComfyUI workflow graph, POSTs it to ComfyUI's `/prompt`
endpoint, polls `/history/{prompt_id}` for completion, and serves
the resulting GLB/OBJ file back through `data[].url`.

**Request**

```http
POST /v1/3d/generations
Content-Type: application/json
```

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

| Field | Type | Required | Notes |
|---|---|---|---|
| `model` | string | yes | model id from `/v1/models` (e.g. `trellis-image-large`, `hunyuan3d-2`) |
| `image_url` | string | conditional | required for image-to-3D models (TRELLIS, Hunyuan3D) |
| `prompt` | string | conditional | required for text-to-3D models; optional refinement hint for image-to-3D |
| `output_format` | string | no | `"glb"` (default), `"obj"`, `"ply"`, `"usdz"` |
| `n` | integer | no | number of variants (default `1`) |
| `seed` | integer | no | reproducibility |
| `texture_resolution` | integer | no | `1024` (default), `2048`, `4096` |

At least one of `image_url` or `prompt` MUST be present. Servers
without either MUST return **400** with
`error.code: "missing_input"`. Unsupported `output_format` returns
**400** with `error.code: "unsupported_output_format"`.

**Response (job submission)**

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

`status` is one of `"queued"`, `"processing"`, `"completed"`,
`"failed"`. On the initial submission the response carries `queued`
or `processing` (never `completed` — generation is minutes-scale).
`estimated_completion_seconds` is a non-binding hint clients use to
set their initial poll cadence.

**Polling**

```http
GET /v1/3d/generations/{id}
```

Returns the same envelope shape. When `status` is `"completed"`,
the `data` array is populated:

```json
{
  "id": "model3d-abc123",
  "object": "3d.generation",
  "created": 1234567890,
  "model": "trellis-image-large",
  "status": "completed",
  "data": [
    {
      "url": "https://example.com/files/model3d-abc123.glb",
      "format": "glb",
      "size_bytes": 1572864,
      "preview_image_url": "https://example.com/files/model3d-abc123-preview.png",
      "expires_at": 1234654290
    }
  ]
}
```

`data[].url` MAY be an absolute CDN URL or a relative path served by
the same server (e.g. `/v1/files/<file-id>`). `preview_image_url` is
optional but RECOMMENDED — clients use it for catalog thumbnails
without downloading the full mesh. `expires_at` is a Unix timestamp
after which the server MAY garbage-collect the file; clients SHOULD
persist locally before then (same convention as
`message.audio.expires_at` in the omni shape).

On `status: "failed"`, the envelope MUST include
`error: {message, type, code}` per the canonical envelope rule.

**Notes**

- 3D generation typically runs **2–10 minutes** per request. Clients
  SHOULD poll no more than once every 5 seconds for long jobs, and
  back off from the `estimated_completion_seconds` hint.
- A server under load MAY return **503** with the canonical envelope
  on submission (transient queue saturation) — clients retry with
  exponential backoff, same as the v0.2.1 503 grading rule for other
  endpoints.
- ComfyUI bridges typically expose model ids that match the
  workflow name (e.g. `trellis-image-large`, `hunyuan3d-2-mv`).
  Clients SHOULD discover available models via `/v1/models`.

---

### `/v1/images/decompositions` — layered image generation

**Aligned with:** Qwen Image Layered. Generates a stack of RGBA layers
(background + N foreground subjects with alpha) instead of one flat
composite. Useful for editable composition.

**Request**

```http
POST /v1/images/decompositions
Content-Type: application/json
```

```json
{
  "model": "qwen-image-layered",
  "prompt": "a cat sitting on a wooden table by a window",
  "num_layers": 3,
  "size": "1024x1024",
  "response_format": "b64_json"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `model` | string | yes | |
| `prompt` | string | yes | |
| `num_layers` | integer | no | requested layer count (default model-dependent) |
| `size` | string | no | `"WIDTHxHEIGHT"`, mirrors `/v1/images/generations` |
| `response_format` | string | no | `"b64_json"` (default) or `"url"` |
| `seed` | integer | no | reproducibility |

**Response**

```json
{
  "id": "imgdecomp-...",
  "created": 1234567890,
  "model": "qwen-image-layered",
  "data": {
    "composite": {
      "index": -1,
      "label": "composite",
      "b64_json": "<base64 PNG>",
      "bbox": {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0}
    },
    "layers": [
      {
        "index": 0,
        "label": "background",
        "b64_json": "<base64 RGBA PNG>",
        "bbox": {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0}
      },
      {
        "index": 1,
        "label": "cat",
        "b64_json": "<base64 RGBA PNG>",
        "bbox": {"x1": 0.30, "y1": 0.20, "x2": 0.70, "y2": 0.85}
      }
    ]
  }
}
```

`data.composite` and each entry of `data.layers` share the same
shape — `{index, label, b64_json, bbox}` — so client code can treat
them uniformly. `composite.index` is conventionally `-1` and
`composite.label` is conventionally `"composite"`; layers index from
`0`. `layers[].b64_json` is RGBA with the alpha channel populated.

`label` is free-text; servers SHOULD use stable labels across
identical `(prompt, seed)` runs but HT-compat-1.0 does not require
deterministic labels (the underlying models route through
segmentation steps that may merge or split layers on tiny prompt
changes).

If `response_format: "url"`, replace `b64_json` with `url` of equal
shape on both `composite` and `layers[]`.

---

## Deferred to v1.1

The following are model-class gaps the catalog knows about but does
not pin in v1.0. Sketches here are non-normative.

**New endpoints**

* **`/v1/video/segmentations`** — SAM3-video. Adds `time_ms` to point
  prompts; response is per-frame mask sequence.
* **`/v1/audio/separations`** — Demucs-style stem separation
  (vocals/drums/bass/other) without prompts. Sibling to
  `/v1/audio/segmentations`; the former is unprompted decomposition,
  the latter is prompt-conditioned extraction.
* **`/v1/audio/generations`** — MusicGen / Stable Audio Open. Distinct
  from `/v1/audio/speech` (TTS): general audio synthesis from a text
  prompt.
* **`/v1/realtime`** — speech-to-speech via WebSocket. Aligns with
  OpenAI's Realtime API once that signature stabilizes.

**Refinements to existing v1.0 endpoints**

* **Per-model capability advertisement.** Each entry in `/v1/models`
  gains an optional `x_ht_compat` field (e.g. `["reranking", "omni"]`)
  so clients can pick the right model without trial-and-error.
* **Omni multi-turn audio reuse.** Allow clients to reference a
  prior `audio.id` instead of re-`base64`-ing the bytes every turn
  (cf. OpenAI Realtime's `previous_item_id`).
* **Omni streaming chunk framing.** Pin codec-aligned framing for
  `delta.audio.data` once a reference impl exists; v1.0 leaves it
  implementation-defined.
* **Segmentation multi-prompt batching.** Add `prompt_index` on
  masks if multi-prompt-per-request becomes a real need (currently
  all prompts collapse to one query per SAM convention).

## How to propose changes

Open a PR against this file with the proposed endpoint, the reference
implementation it aligns with, and a paragraph on why. We will not
merge an endpoint until at least one OSS implementation can be
pointed at it — HT-compat is a convergence target, not aspirational
design.
