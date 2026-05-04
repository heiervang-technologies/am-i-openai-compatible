# LM Studio

Desktop-first inference UI; ships an OpenAI-compatible HTTP server
behind a "Local Server" toggle.

## Surface (current)

| Endpoint                          | Status | Notes                                       |
|-----------------------------------|--------|---------------------------------------------|
| `/v1/models`                      | ✅     | Lists loaded model + downloaded models      |
| `/v1/models/{id}`                 | ⚠️     | Often 404; LM Studio has been improving     |
| `/v1/chat/completions`            | ✅     | Tools, JSON mode (template-dependent)       |
| `/v1/chat/completions` *(stream)* | ✅                                                |
| `/v1/completions`                 | ✅     | Maintained                                  |
| `/v1/embeddings`                  | ✅     | When an embedding model is loaded           |
| `/v1/audio/*`                     | ❌                                                |
| `/v1/images/*`                    | ❌                                                |

## Notes

* **GUI required.** The server only runs when the LM Studio app is
  running and the toggle is on. Headless server mode exists but is
  less mature than llama.cpp's.
* **Model identity.** LM Studio uses HF-style ids verbatim (e.g.
  `mistralai/Mistral-7B-Instruct-v0.2`). Make sure your client
  sends the exact id.
* **Probe carefully.** LM Studio's server is slower to warm than
  bare `llama-server`; the first request after startup can take
  multiple seconds before it accepts requests.

## See also

* product: <https://lmstudio.ai/>
