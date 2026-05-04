# TabbyAPI

Exllamav2-based inference server with an OpenAI-compatible surface.
Targeted at users who want EXL2 quantization performance with a
familiar API.

## Surface (current)

| Endpoint                          | Status | Notes                                       |
|-----------------------------------|--------|---------------------------------------------|
| `/v1/models`                      | ✅     | Lists loaded model and adjacent presets     |
| `/v1/models/{id}`                 | ✅                                                |
| `/v1/chat/completions`            | ✅     | Tools, JSON mode                            |
| `/v1/chat/completions` *(stream)* | ✅                                                |
| `/v1/completions`                 | ✅                                                |
| `/v1/embeddings`                  | ❌     | Not the focus of the project                |
| `/v1/audio/*`                     | ❌                                                |
| `/v1/images/*`                    | ❌                                                |

## Extensions worth knowing

* **`top_a`** — alternative sampler. Spec-silent.
* **DRY sampler** — discourages repeated phrases. Spec-silent.
* **Speculative decoding** — exposed as `n_speculative_tokens` and
  related params; runtime-only, no spec analog.
* **Multi-model routing** — load multiple models in one process;
  request specifies which one.

## Common deviations

* **Sampler defaults differ from OpenAI.** TabbyAPI's defaults lean
  toward narrative writing (lower top_p, higher temperature) than
  OpenAI's. The compliance probe doesn't care, but a client that
  doesn't set its own params will see different style than they
  expect.

## See also

* upstream: <https://github.com/theroyallab/tabbyAPI>
