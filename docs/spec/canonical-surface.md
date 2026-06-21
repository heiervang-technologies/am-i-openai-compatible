# Canonical surface

The endpoints the prober walks under the default `openai` profile,
plus the `/v1/videos` HT-compat extension as a representative `ours`
row. The catalog is sourced from
[`endpoints.py`](https://github.com/heiervang-technologies/am-i-openai-compatible/blob/main/src/am_i_openai_compatible/endpoints.py);
the full HT-compat `ours` surface (rerank, segmentation, encoder
rows, omni chat, 3D, image decomposition, audio segmentation) lives
in [HT-compat profile](ht-compat.md).

You can produce a current copy of this table with:

```bash
aioc spec
```

## Models / discovery

| Path                        | Method | Kind | Notes                                                  |
|-----------------------------|--------|------|--------------------------------------------------------|
| `/v1/models`                | GET    | core | Required for any compat surface; powers model sniffing |
| `/v1/models/{model}`        | GET    | core | Many OSS impls return 404; OpenAI returns the object   |

## Chat & completions

| Path                                  | Method | Kind | Notes                                                      |
|---------------------------------------|--------|------|------------------------------------------------------------|
| `/v1/chat/completions`                | POST   | core | The headline endpoint; supports tools, JSON mode, streams  |
| `/v1/chat/completions` *(stream)*     | POST   | core | Separate row so a missing-stream regression is visible     |
| `/v1/chat/completions` *(logprobs)*   | POST   | ext  | Separate row so a missing-logprobs regression is visible   |
| `/v1/completions`                     | POST   | ext  | Legacy text completion; many newer servers omit it         |
| `/v1/responses`                       | POST   | ext  | Newer Responses API; few OSS servers implement             |
| `/v1/responses/compact`               | POST   | ext  | Compact-output variant of the Responses API                |
| `/v1/realtime`                        | GET    | ext  | WebSocket upgrade for low-latency conversational sessions  |

## Audio

| Path                       | Method | Kind | Notes                                                   |
|----------------------------|--------|------|---------------------------------------------------------|
| `/v1/audio/speech`         | POST   | core | TTS; returns audio bytes (mp3/opus/wav)                 |
| `/v1/audio/transcriptions` | POST   | core | STT; multipart upload, returns `text` JSON              |
| `/v1/audio/translations`   | POST   | ext  | STT to English; many servers fold into transcriptions   |
| `/v1/audio/voices`         | GET    | ext  | List installed TTS voice ids                            |

## Images

| Path                  | Method | Kind | Notes                                                       |
|-----------------------|--------|------|-------------------------------------------------------------|
| `/v1/images/generations` | POST | core | Returns `{data: [{url}|{b64_json}]}`                        |
| `/v1/images/edits`    | POST   | core | OpenAI requires multipart; some OSS take JSON (WARN)        |

> `/v1/images/variations` was pruned from the catalog in v0.3.1 — see
> the [Retired](../compatibility-matrix.md#retired) section of the
> matrix for context.

## Videos *(`ours` extension)*

| Path                  | Method | Kind | Notes                                                       |
|-----------------------|--------|------|-------------------------------------------------------------|
| `/v1/videos`          | POST   | ours | Async job creation; mirrors OpenAI's Sora job shape         |

> The polling routes `/v1/videos/{id}` and `/v1/videos/{id}/content`
> are part of the HT-compat protocol but aren't probed directly —
> they need a live job id, which would couple a probe to a multi-
> second render.

## Embeddings

| Path             | Method | Kind | Notes                                  |
|------------------|--------|------|----------------------------------------|
| `/v1/embeddings` | POST   | core | Returns `{data: [{embedding: [...]}]}` |

## Files / batches / fine-tuning *(typically not implemented)*

| Path                  | Method | Kind | Notes                                                   |
|-----------------------|--------|------|---------------------------------------------------------|
| `/v1/files`           | GET    | ext  | Uploads listing; most OSS servers omit                  |
| `/v1/batches`         | GET    | ext  | OpenAI Batch API; almost no OSS server implements       |
| `/v1/fine_tuning/jobs`| GET    | ext  | OSS servers don't fine-tune via API                     |
| `/v1/uploads`         | POST   | ext  | Multi-part upload-session creation (OpenAI Uploads API) |

The three GET routes (`/v1/files`, `/v1/batches`, `/v1/fine_tuning/jobs`)
carry `phase_b_skip=True` in the catalog — Phase A existence is the
meaningful signal; Phase B against an unauth server would just 401.

## Moderation / safety

| Path               | Method | Kind | Notes                                  |
|--------------------|--------|------|----------------------------------------|
| `/v1/moderations`  | POST   | ext  | Few OSS servers implement              |

## Reading the deviations

A `WARN` row in `aioc probe` output is *not* a failure — it's an
endpoint that exists and broadly works but deviates from the canonical
shape in a way the catalog has flagged as "common but non-spec".
Examples:

* `/v1/images/edits` taking JSON instead of multipart (vLLM fork).
* `/v1/audio/speech` returning `application/octet-stream` instead of
  `audio/mpeg` (some llama.cpp shims).
* `/v1/chat/completions` omitting the `usage` object on streamed
  responses (llama.cpp's default).

These are documented per-implementation in
[Implementations](../implementations/index.md) so a `WARN` doesn't
surprise you twice.
