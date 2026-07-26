# Models / discovery

Two endpoints: list and retrieve.

## `/v1/models` (GET)

The single most important endpoint in the surface. It's how clients
(and this prober) discover what's available, and it's required for any
server claiming to be OpenAI-compatible.

**Required response shape:**

```json
{
  "object": "list",
  "data": [
    {
      "id": "<id>",
      "object": "model",
      "created": 1730000000,
      "owned_by": "<vendor>"
    }
  ]
}
```

`data` may be empty (a server with zero models is degenerate but
valid). Servers that omit `created` or `owned_by` get a `WARN` — most
clients tolerate it but the OpenAI SDK pydantic-validates the field.

### Common deviations

* **Wrapper around a non-list value.** Some shims return `{"data":
  {"models": [...]}}`. Hard `FAIL`; clients break immediately.
* **Per-pod merge skew on a fanout ingress.** When `/v1/models` is
  served by a load balancer in front of N pods that each have a
  different model loaded, repeat calls return different subsets. Not
  spec-non-compliant per request, but a lurking source of confusion.
* **Status / lifecycle fields.** llama.cpp's LlamaSwap returns a
  `status: {value: "loaded|unloaded", args, preset}` object on each
  model. Catalog allows extras; valid extension.

## `/v1/models/{model}` (GET)

Returns one model object by id. Many OSS implementations return `404`
on this endpoint even when `/v1/models` lists the same id. That's a
documented deviation (`WARN`), not a hard fail — most clients only
ever hit `list`.

**Expected shape:**

```json
{
  "id": "<id>",
  "object": "model",
  "created": 1730000000,
  "owned_by": "<vendor>"
}
```

The prober expects the `id` in the response to match the path
parameter. A mismatch is a `WARN` (some servers return a normalized
id) and worth investigating. This is emitted as the derived Phase C
event `implies: models list→retrieve`; it reuses the two Phase B
responses and adds no request.
