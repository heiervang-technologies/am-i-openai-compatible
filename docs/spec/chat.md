# Chat & completions

The most heavily used surface and the one with the most quiet drift.

## `/v1/chat/completions` — non-streaming

**Required request fields:**

```json
{
  "model": "<id>",
  "messages": [{"role": "user", "content": "hi"}]
}
```

**Required response fields:**

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1730000000,
  "model": "<id>",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "..."},
      "finish_reason": "stop|length|tool_calls|content_filter"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 4,
    "total_tokens": 14
  }
}
```

The prober's
[`ChatCompletionResponse`](https://github.com/heiervang-technologies/am-i-openai-compatible/blob/main/src/am_i_openai_compatible/schemas.py)
treats `usage` as optional because llama.cpp omits it in some
configurations and that's not worth a hard `FAIL`.

### Common deviations

* **Missing `usage` on stream + `usage_chunks=false`** — llama.cpp.
  Easy fix: pass `stream_options: {include_usage: true}` if the server
  supports it.
* **`finish_reason: "eos"`** instead of `"stop"` — older llama.cpp
  shims; modern builds emit `"stop"`.
* **No `choices[].index`** — exotic. Hard `FAIL`.
* **Tool calls returned as a string** rather than the structured
  `tool_calls` array — some Ollama versions when the model wasn't
  trained for tool use; reportable but not a server defect per se.

### Validation rules the prober applies

* `choices` must be a non-empty array.
* `choices[0].message.content` must be a string or an array of content
  parts.
* `choices[0].finish_reason` must be one of the canonical values *or*
  `null` (some servers emit `null` mid-stream — but for non-streaming
  the prober expects a final value).
* `usage`, when present, must contain `prompt_tokens` and
  `total_tokens`. `completion_tokens` is allowed to be `null`.

## `/v1/chat/completions` — streaming

A separate catalog row so a missing-stream regression shows up
distinctly. Probe sends:

```json
{"model": "<id>", "messages": [{"role": "user", "content": "hi"}],
 "max_tokens": 4, "stream": true}
```

Server must respond with `text/event-stream` framing:

```
data: {"id": "chatcmpl-...", "object": "chat.completion.chunk",
       "created": 1730000000, "model": "<id>",
       "choices": [{"index": 0, "delta": {"role": "assistant"},
                    "finish_reason": null}]}

data: {"...": "...", "choices": [{"index": 0, "delta": {"content": "h"}}]}
...
data: [DONE]
```

The prober counts at least 1 chunk *and* sees `[DONE]`. Servers that
forget the `[DONE]` sentinel (a real Ollama bug for a while) get a
`WARN`.

### Stream-specific deviations

* **No `[DONE]` line.** Clients using `openai-python` 1.x usually
  cope; bare-bones SSE clients may hang waiting for a final frame.
* **`role` only on the first delta.** This is canonical; servers that
  repeat it on every delta are still spec but inflate bytes.
* **Last delta carries the full message** instead of a single token.
  Spec doesn't forbid it; some optimizers do this when the model
  output is shorter than the streaming flush window.
* **`include_usage` ignored.** Servers that don't support
  `stream_options.include_usage` should ignore it without erroring.
  vLLM and llama.cpp do the right thing; some shims 400 the request.

## Sampling parameters

`temperature`, `top_p`, `max_tokens`, `seed`, `stop`, `frequency_penalty`,
and `presence_penalty` are the canonical OpenAI knobs and are honored
broadly. Beyond them, open inference servers expose **non-standard
sampling controls** that real clients depend on — and the one that bites
portability hardest is the **repetition penalty**.

### Repetition penalty

OpenAI has **no** `repetition_penalty`. Its only repetition controls are
the additive `frequency_penalty` and `presence_penalty`. Open servers
added a *multiplicative* repetition penalty instead, and they do **not**
agree on the field name:

| Server    | Field                | Notes                                                        |
|-----------|----------------------|--------------------------------------------------------------|
| vLLM      | `repetition_penalty` | float, `1.0` = off; `frequency_penalty`/`presence_penalty` also accepted |
| SGLang    | `repetition_penalty` | same semantics as vLLM                                       |
| TabbyAPI  | `repetition_penalty` | plus `repetition_range`, `repetition_decay` (ExLlama sampler) |
| llama.cpp | `repeat_penalty`     | float, `1.0` = off; plus `repeat_last_n` lookback window     |
| LM Studio | `repeat_penalty`     | llama.cpp-backed; same spelling                             |
| Ollama    | `repeat_penalty`     | native under `options`; the `/v1` shim forwards only `frequency_penalty`/`presence_penalty` |

The trap: every server above **silently drops unknown fields** rather
than returning a 4xx. So a client that sends `repetition_penalty: 1.1`
to llama.cpp gets *no penalty at all* (it wanted `repeat_penalty`), with
no error to signal the miss — and vice-versa on vLLM. Portable clients
send **both** keys. `1.0` disables it everywhere; typical anti-repetition
values are `1.05`–`1.15`.

The prober does not yet assert repetition-penalty *behavior* (that needs
a Phase-C implication test like `seed`); the
[compatibility matrix](../compatibility-matrix.md#feature-deviations-on-shared-endpoints)
tracks per-server support and the field-name split.

## `/v1/completions` *(legacy text completion)*

`ext` in this catalog. Many newer servers (vLLM ≥ 0.5, Ollama after
the OpenAI-compat refactor) keep it for backward compatibility but
mark it deprecated.

```json
{"model": "<id>", "prompt": "hello", "max_tokens": 4}
```

The expected shape:

```json
{
  "id": "cmpl-...",
  "object": "text_completion",
  "created": 1730000000,
  "model": "<id>",
  "choices": [{"text": "...", "index": 0, "finish_reason": "..."}]
}
```

Servers that "implement" `/v1/completions` by silently rerouting to
chat completions and returning the chat shape get a `FAIL` — the
shapes are different and clients break. This is rare but does happen.

## `/v1/responses` *(the newer Responses API)*

`ext`. Almost no OSS server implements this fully today. The prober
sends:

```json
{"model": "<id>", "input": "hi"}
```

…and validates that `output` exists in the response. A `404` here is
expected and yields `SKIP`, not `FAIL`.
