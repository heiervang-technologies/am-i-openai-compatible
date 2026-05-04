# Canonical surface

The full table the prober walks. Generated from
[`endpoints.py`](https://github.com/heiervang-technologies/am-i-openai-compatible/blob/main/src/am_i_openai_compatible/endpoints.py).

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

| Path                                | Method | Kind | Notes                                                      |
|-------------------------------------|--------|------|------------------------------------------------------------|
| `/v1/chat/completions`              | POST   | core | The headline endpoint; supports tools, JSON mode, streams  |
| `/v1/chat/completions` *(stream)*   | POST   | core | Separate row so a missing-stream regression is visible     |
| `/v1/completions`                   | POST   | ext  | Legacy text completion; many newer servers omit it         |
| `/v1/responses`                     | POST   | ext  | Newer Responses API; few OSS servers implement             |

## Audio

| Path                       | Method | Kind | Notes                                                   |
|----------------------------|--------|------|---------------------------------------------------------|
| `/v1/audio/speech`         | POST   | core | TTS; returns audio bytes (mp3/opus/wav)                 |
| `/v1/audio/transcriptions` | POST   | core | STT; multipart upload, returns `text` JSON              |
| `/v1/audio/translations`   | POST   | ext  | STT to English; many servers fold into transcriptions   |

## Images

| Path                  | Method | Kind | Notes                                                       |
|-----------------------|--------|------|-------------------------------------------------------------|
| `/v1/images/generations` | POST | core | Returns `{data: [{url}|{b64_json}]}`                        |
| `/v1/images/edits`    | POST   | core | OpenAI requires multipart; some OSS take JSON (WARN)        |
| `/v1/images/variations` | POST | ext  | Less commonly implemented                                   |

## Videos *(`ours` extension)*

| Path                  | Method | Kind | Notes                                                       |
|-----------------------|--------|------|-------------------------------------------------------------|
| `/v1/videos`          | POST   | ours | Async job creation; mirrors OpenAI's Sora job shape         |
| `/v1/videos/{id}`     | GET    | ours | Job status polling                                          |
| `/v1/videos/{id}/content` | GET | ours | Final video bytes when status is `completed`              |

## Embeddings

| Path             | Method | Kind | Notes                                  |
|------------------|--------|------|----------------------------------------|
| `/v1/embeddings` | POST   | core | Returns `{data: [{embedding: [...]}]}` |

## Files / fine-tuning *(typically not implemented)*

| Path                  | Method | Kind | Notes                                  |
|-----------------------|--------|------|----------------------------------------|
| `/v1/files`           | GET    | ext  | Uploads — most OSS servers omit        |
| `/v1/fine_tuning/jobs`| GET    | ext  | OSS servers don't fine-tune via API    |

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
