# Embeddings

The simplest endpoint and yet still a source of subtle drift.

## `/v1/embeddings`

```json
{ "model": "<id>", "input": "hello world" }
```

`input` may be a string or an array of strings. Some servers require
arrays; spec accepts both.

**Response:**

```json
{
  "object": "list",
  "data": [
    {"object": "embedding", "index": 0, "embedding": [0.012, -0.034, ...]}
  ],
  "model": "<id>",
  "usage": {"prompt_tokens": 2, "total_tokens": 2}
}
```

The prober validates:

* `object` is the literal string `"list"`.
* `data` is non-empty.
* Each `data[i].embedding` is a list of floats.
* `data[i].index` matches its position (server may renumber, but
  clients depend on this).

### Common deviations

* **Embeddings as strings.** OpenAI offers `encoding_format:
  "base64"`. Servers that *default* to base64 break clients that
  expect floats. The prober sends no `encoding_format`, so a base64
  default is a `FAIL`.
* **`usage` omitted.** WARN. Some embedding servers genuinely don't
  count tokens.
* **Multimodal inputs.** OpenAI doesn't accept images on
  `/v1/embeddings`; some local servers do (LCO-Embedding, etc.). They
  should also accept plain-string input — a server that *only* accepts
  multimodal input fails the catalog's plain-string probe.

## Dimensions, normalization, and bias

Outside the scope of compliance probing. The catalog says nothing
about the *quality* or *dimensionality* of an embedding — just that
the response shape is a valid `ListResponse[EmbeddingObject]`.

If you want quality benchmarks, MTEB and the SentenceBenchmark suites
are the right tools, not this one.
