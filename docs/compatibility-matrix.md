# Compatibility matrix

A high-density at-a-glance view. Rows are the canonical endpoints
the prober checks. Columns are the major OSS implementations.

Legend: ✅ pass · ⚠️ pass-with-deviation · ❌ not implemented · — out of scope

## Core surface

| Endpoint                                | OpenAI | vLLM | llama.cpp | Ollama | LM Studio | TabbyAPI |
|-----------------------------------------|--------|------|-----------|--------|-----------|----------|
| `/v1/models`                            | ✅     | ✅   | ✅        | ✅     | ✅        | ✅       |
| `/v1/models/{id}`                       | ✅     | ✅   | ⚠️        | ✅     | ⚠️        | ✅       |
| `/v1/chat/completions`                  | ✅     | ✅   | ✅        | ✅     | ✅        | ✅       |
| `/v1/chat/completions` *(stream)*       | ✅     | ✅   | ✅        | ✅     | ✅        | ✅       |
| `/v1/completions`                       | ✅     | ✅   | ✅        | ⚠️     | ✅        | ✅       |
| `/v1/embeddings`                        | ✅     | ✅   | ✅        | ✅     | ✅        | ❌       |
| `/v1/audio/transcriptions`              | ✅     | ✅   | ❌        | ❌     | ❌        | ❌       |
| `/v1/audio/speech`                      | ✅     | ⚠️   | ❌        | ❌     | ❌        | ❌       |
| `/v1/images/generations`                | ✅     | ⚠️   | ❌        | ❌     | ❌        | ❌       |
| `/v1/images/edits`                      | ✅     | ❌   | ❌        | ❌     | ❌        | ❌       |

## Extensions

| Endpoint                                | OpenAI | vLLM | llama.cpp | Ollama | LM Studio | TabbyAPI |
|-----------------------------------------|--------|------|-----------|--------|-----------|----------|
| `/v1/responses`                         | ✅     | ⚠️   | ❌        | ❌     | ❌        | ❌       |
| `/v1/responses/compact`                 | ✅     | ❌   | ❌        | ❌     | ❌        | ❌       |
| `/v1/realtime` *(WebSocket)*            | ✅     | ❌   | ❌        | ❌     | ❌        | ❌       |
| `/v1/audio/translations`                | ✅     | ⚠️   | ❌        | ❌     | ❌        | ❌       |
| `/v1/moderations`                       | ✅     | ❌   | ❌        | ❌     | ❌        | ❌       |
| `/v1/files`                             | ✅     | ❌   | ❌        | ❌     | ❌        | ❌       |
| `/v1/fine_tuning/jobs`                  | ✅     | ❌   | ❌        | ❌     | ❌        | ❌       |

## Feature deviations on shared endpoints

For endpoints all servers implement, what's actually different:

| Behavior                                          | OpenAI | vLLM | llama.cpp | Ollama | LM Studio | TabbyAPI |
|---------------------------------------------------|--------|------|-----------|--------|-----------|----------|
| Streaming `usage` when requested via `stream_options.include_usage` | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ |
| Honors `seed` deterministically                   | ✅     | ✅   | ✅        | ⚠️     | ⚠️        | ⚠️       |
| `response_format: json_schema`                    | ✅     | ✅   | ✅        | ⚠️     | ⚠️        | ⚠️       |
| `tool_calls[].function.arguments` is a string     | ✅     | ✅   | ✅        | ⚠️     | ✅        | ✅       |
| OpenAI error envelope on 4xx                      | ✅     | ✅   | ⚠️        | ⚠️     | ⚠️        | ⚠️       |
| `cache_prompt` / KV-cache reuse                   | n/a    | ✅   | ✅        | ⚠️     | ✅        | ✅       |
| Logprobs on chat completions                      | ✅     | ✅   | ✅        | ⚠️     | ⚠️        | ⚠️       |

## Retired

Endpoints OpenAI used to expose but no longer route:

* **`/v1/images/variations`** — DALL·E-2-era image variation endpoint.
  An unauth probe of `api.openai.com` on 2026-05-16 returned 404; the
  public Images API docs no longer list it. The canonical
  image-variation flow is now `/v1/images/edits` with `gpt-image-1`.
  Pruned from the catalog in v0.3.1 (see issue #7).

## Caveats

* **Snapshots are best-effort.** Each cell reflects the most recent
  `aioc probe` run we have a record of, against the *latest stable*
  release. Pre-release builds may differ.
* **"Honors `seed`"** is a Phase C implication test — currently
  manual. We mark it ⚠️ when reproducibility was inconsistent in our
  tests, even if the parameter is accepted.
* **The matrix isn't a leaderboard.** A red row may simply mean a
  server doesn't target that surface (Ollama isn't trying to do
  audio).

## Help us keep it honest

PRs that update a cell with a fresh `aioc probe` report attached are
the easiest way to contribute. See [Contributing](contributing.md).
