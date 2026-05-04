# Ollama

Ollama exposes both its native API and an OpenAI-compatible shim. The
shim was added late in the project's history and has caught up
gradually.

## Surface (current)

| Endpoint                          | Status | Notes                                            |
|-----------------------------------|--------|--------------------------------------------------|
| `/v1/models`                      | ✅     | Maps to `ollama list`                            |
| `/v1/models/{id}`                 | ✅     | Returns the model object                         |
| `/v1/chat/completions`            | ✅     | Tools, JSON mode                                 |
| `/v1/chat/completions` *(stream)* | ✅     | `[DONE]` sentinel emitted                        |
| `/v1/completions`                 | ⚠️     | Routes through chat under the hood; finish_reason mapping is approximate |
| `/v1/embeddings`                  | ✅     | `/api/embed` is preferred                        |
| `/v1/audio/*`                     | ❌     | Not implemented                                  |
| `/v1/images/*`                    | ❌     | Not implemented (Ollama is text/vision only)     |

## Common deviations

* **Tool-call argument JSON drift.** For models without strong
  tool-use training, Ollama's shim sometimes returns
  `tool_calls[].function.arguments` as a parsed object instead of a
  JSON-encoded string. WARN.
* **Inference parameters.** Ollama accepts many OpenAI params
  (`temperature`, `top_p`, `seed`) but silently caps `max_tokens`
  against its own `num_predict`. Probes that ask for more than the
  model's default `num_predict` may get fewer tokens than requested.
* **`response_format: json_schema`** is not honored — Ollama ignores
  the schema and falls back to a generic JSON-mode prompt.

## Quirks worth knowing

* **Native API is richer.** If you can use `/api/chat` and
  `/api/embed`, you get features (model pulling, parameter passing
  via Modelfile) that don't have OpenAI analogs.
* **Concurrency.** Ollama serializes requests per loaded model. The
  prober's ≤2 requests/endpoint budget is fine, but concurrent
  pytest runs against the same Ollama instance will queue.

## See also

* upstream: <https://github.com/ollama/ollama>
* OpenAI-compat docs: <https://github.com/ollama/ollama/blob/main/docs/openai.md>
