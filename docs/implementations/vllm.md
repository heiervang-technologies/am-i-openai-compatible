# vLLM

Production-oriented inference server with the broadest OSS coverage of
OpenAI's surface. If a feature ships in OpenAI, vLLM is usually the
first OSS server to mirror it.

## Surface (current)

| Endpoint                          | Status | Notes                                              |
|-----------------------------------|--------|----------------------------------------------------|
| `/v1/models`                      | ✅     | Returns served-model-name; sidecar `id` aliasing   |
| `/v1/models/{id}`                 | ✅     | Returns the model object                           |
| `/v1/chat/completions`            | ✅     | Tools, JSON mode, json_schema, logprobs, seed      |
| `/v1/chat/completions` *(stream)* | ✅     | `usage` via `stream_options`                       |
| `/v1/completions`                 | ✅     | Maintained alongside chat                          |
| `/v1/responses`                   | ⚠️     | Partial; surface is in active development          |
| `/v1/embeddings`                  | ✅     | Pooling configurable per model                     |
| `/v1/audio/transcriptions`        | ✅     | Whisper / Qwen3-ASR                                |
| `/v1/audio/translations`          | ⚠️     | Often folded into transcriptions                   |
| `/v1/audio/speech`                | ⚠️     | Available with TTS-capable models only             |
| `/v1/images/generations`          | ⚠️     | Multimodal generation models only                  |

## Notable extensions

* **Batched logprobs** — vLLM is one of the few servers that returns
  per-token logprobs efficiently for batched requests.
* **`prompt_logprobs`** — logprobs of the *input* tokens, not just
  generated. Useful for log-likelihood scoring; no OpenAI analog.
* **`min_tokens`** — guaranteed minimum generation length. Spec-silent.
* **`guided_*`** parameters — `guided_choice`, `guided_regex`,
  `guided_grammar`, `guided_json`. Predates `response_format:
  json_schema`; both are supported.
* **`echo`** in `/v1/completions` — include the prompt in the output.
  OpenAI dropped this; vLLM kept it.

## Common deviations the catalog flags

* Few. vLLM is the closest OSS server to spec.
* **Streaming `usage` requires opt-in.** PASS by default since the
  catalog's stream probe doesn't request usage.
* **`served_model_name` sometimes diverges from `id`.** Some configs
  load model `mistralai/Mistral-7B-v0.1` but expose it as
  `mistral-7b`. `/v1/models/{served_name}` works; `/v1/models/{path}`
  may not. WARN.

## Quirks worth knowing

* **Model loading is per-process.** Unlike LlamaSwap, vLLM doesn't
  hot-swap models. Plan one vLLM process per model, or use a router
  in front.
* **Engine versions matter.** `--engine v1` (default) and `--engine
  v0` (legacy) have *meaningfully different* tool-call formatting.
  v1 is more spec-aligned.
* **Tokenizer drift.** vLLM uses HF tokenizers; if the upstream model
  releases a new tokenizer, you need to bump `tokenizers` to match.
  Out-of-spec tokenizers cause subtle finish_reason mis-reporting.

## See also

* upstream: <https://github.com/vllm-project/vllm>
