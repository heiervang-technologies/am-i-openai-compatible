# llama.cpp (`llama-server`)

The reference low-dependency local inference server. Its OpenAI
endpoint is implemented in `examples/server/server.cpp` and has
matured rapidly through 2025.

## Surface (current)

| Endpoint                          | Status | Notes                                            |
|-----------------------------------|--------|--------------------------------------------------|
| `/v1/models`                      | ✅     | Returns the loaded model + any preset entries    |
| `/v1/models/{id}`                 | ⚠️     | 404 in vanilla `llama-server`; LlamaSwap adds it |
| `/v1/chat/completions`            | ✅     | Tools, JSON mode, schema-constrained sampling    |
| `/v1/chat/completions` *(stream)* | ✅     | `[DONE]` sentinel, `usage` opt-in                |
| `/v1/completions`                 | ✅     | Legacy text completion still maintained          |
| `/v1/responses`                   | ❌     | Not implemented                                  |
| `/v1/embeddings`                  | ✅     | Requires `--embedding` flag at server start      |
| `/v1/audio/speech`                | ❌     | No TTS in vanilla; out of scope                  |
| `/v1/audio/transcriptions`        | ❌     | Likewise                                         |
| `/v1/images/generations`          | ❌     | Out of scope                                     |
| `/v1/videos`                      | ❌     | Out of scope                                     |

## Notable extensions

* **`cache_prompt`** in chat / completion bodies — keeps the prompt
  KV cache across requests when prefixes match. No spec analog;
  enormous latency win for chat UIs that pin a system prompt.
* **`grammar` / `grammar_lazy`** — GBNF-constrained sampling. The
  catalog's `response_format: json_schema` falls through to this on
  llama.cpp.
* **`mirostat`, `mirostat_tau`, `mirostat_eta`** — alternative
  sampler. Spec-silent; harmless extras.
* **Multi-modal**: when started with `--mmproj`, `llama-server`
  accepts `image_url` content parts in chat messages. The mmproj is
  loaded once at server start; you can't switch projectors per
  request.

## Common deviations the catalog flags

* **`/v1/models/{id}` 404.** WARN. Acceptable; clients rarely use it.
* **`usage` missing on streamed responses** unless
  `stream_options.include_usage: true` is set. The catalog probes
  without that flag and tolerates absence on streams (PASS).
* **`finish_reason: "length"` for `max_tokens` cap.** Spec correct.
* **`finish_reason: "stop"` even when the model emits its EOS.**
  Correct per spec; some older shims used `"eos"`.

## Quirks worth knowing

* **`--jinja` matters.** Without it, llama.cpp uses its own
  approximate chat templating, which can disagree with the model's
  trained format on tool-call syntax. With it, the server respects
  the GGUF's embedded jinja chat template. Always pass `--jinja` for
  modern instruction-tuned models.
* **`n_parallel` and KV-cache eviction.** `--parallel N` lets N
  requests share the KV cache. Setting `n_parallel=1` with
  `--cont-batching` gives lowest latency; setting `n_parallel >= 4`
  helps throughput at the cost of cache thrash on long contexts.
* **`/props` for build introspection.** Not OpenAI-compat, but the
  endpoint that tells you *which build* is running. Catalog ignores
  it; ops engineers love it.

## How LlamaSwap layers on top

[LlamaSwap](https://github.com/mostlygeek/llama-swap) wraps `N` `llama-server`
instances behind one HTTP port. The OpenAI surface stays the same; what
changes is that `/v1/models` enumerates *all* preset model ids, not
just the loaded one. The catalog accepts this as a valid extension —
`status.value` of `"loaded"` / `"unloaded"` is a documented extra
field.

LlamaSwap's `/v1/models/{id}` works (it returns the preset) — so a
LlamaSwap-fronted llama.cpp gets a PASS where vanilla gets a WARN.

## Probing recipe

```bash
# Vanilla llama-server on 8080
aioc probe http://localhost:8080 --name llama.cpp

# LlamaSwap fronting llama-server
aioc probe http://localhost:8080 --name llamaswap

# In a Kubernetes setup with NodePort
aioc probe http://192.168.8.158:30184 --name titan-llm
```

## See also

* upstream: <https://github.com/ggerganov/llama.cpp>
* heiervang-technologies fork: <https://github.com/heiervang-technologies/ht-llama.cpp>
