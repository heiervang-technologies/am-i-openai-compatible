# OpenAI (the reference)

The moving target. This page exists to document what *OpenAI itself*
does, not because we expect anyone else to match it perfectly.

## Surface

OpenAI implements the full canonical surface plus several
extensions that haven't propagated to OSS servers:

* `/v1/responses` — newer than chat completions, structured around
  *responses* (multi-turn, multi-output) instead of message arrays.
* `/v1/audio/speech` streaming.
* `/v1/threads`, `/v1/assistants`, `/v1/files` — the Assistants API.
* `/v1/batches` — async batch processing at half price.
* `/v1/realtime` — WebSocket-based bidirectional streaming.

The catalog tracks Responses, speech, files, batches, uploads, and
Realtime. Threads and Assistants remain intentionally **out of scope**:
their multi-step stateful workflows do not fit the probe's two-phase
endpoint contract.

## Auth

`Authorization: Bearer <key>` is required. Pass `--openai-api-key`, or
set `OPENAI_API_KEY` (`AIOC_API_KEY` is the fallback).

`OpenAI-Beta` headers gate features that are in flight. The prober only
adds `openai-beta: realtime=v1` for the Realtime WebSocket row.

## Probing OpenAI itself

```bash
export OPENAI_API_KEY=sk-...
aioc probe https://api.openai.com --name openai --report openai.json
```

Why probe the reference? To detect *spec drift* in our own catalog.
If OpenAI changes the chat completions response shape and the prober
flags `WARN` against `api.openai.com`, the catalog is out of date,
not OpenAI.

## Things to keep in mind

* **Rate limits.** Even with one shared discovery call and at most two
  requests per selected endpoint, a free-tier key may hit the
  per-minute cap on the chat probe. Use a paid tier or expect SKIP rows.
* **Cost.** `max_tokens=4` keeps each chat call to ~¢0.001 on
  `gpt-4o-mini`. Image generation is ~¢4 per call (`512x512, n=1` on
  `gpt-image-1`). The full probe is roughly $0.05 against the cheapest
  tier.
* **Sandbox.** OpenAI does *not* run in `sandbox=true` mode by
  default. The probe sends real prompts; review the catalog's bodies
  if you're concerned about content.
