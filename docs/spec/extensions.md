# Extensions & quirks

The long tail of "almost spec" behavior. Things every client
eventually trips over even though no single behavior is a hard
violation.

## Implication tests (planned)

Beyond per-endpoint shape checks, there are *implication* checks the
prober treats as a third phase: properties that should hold across
endpoints if a server is internally consistent. Examples:

* **list → retrieve.** If `/v1/models` lists `id`, then
  `/v1/models/{id}` should return the same id (or 404, but never a
  *different* id).
* **chat ↔ completion logprobs.** If `/v1/chat/completions` accepts
  `logprobs: true`, then a basic chat call with `logprobs: true`
  should have `choices[0].logprobs` populated. Servers that *accept
  the parameter* but never populate the field violate the implication.
* **streaming finish_reason.** A streamed chat must emit a final delta
  with `finish_reason` set and then `[DONE]` — a stream that ends
  without a `finish_reason` chunk leaves clients hanging.
* **temperature 0 determinism.** Two calls with `temperature: 0,
  seed: 42` should return identical outputs. A server that doesn't
  honor `seed` will fail this even when both responses are individually
  spec-valid.

These don't all run today (some need stable-output models that aren't
worth assuming), but the catalog reserves them as a future Phase C.

## Quirks worth flagging

### Streaming gotchas

* **No `[DONE]` sentinel.** Real bug; clients hang.
* **Trailing whitespace deltas.** `delta.content: " "` after a
  `finish_reason` chunk. Spec doesn't allow content after the final
  reason, but a few servers do this.
* **Heartbeat / keepalive frames.** Some servers send `: keep-alive\n`
  comment lines mid-stream. Spec-allowed; but breaks a hand-rolled SSE
  parser that expects only `data:` frames.

### Tool calls

* **Function vs. tool naming.** The legacy `function_call` field is
  deprecated; servers should emit `tool_calls`. Many OSS servers still
  emit `function_call` for backward compatibility — spec-discouraged
  but not invalid. Catalog tracks this as a WARN.
* **Tool argument JSON drift.** `tool_calls[i].function.arguments` is
  a *string* (JSON-as-text). Some servers emit it as a parsed object,
  which breaks every client that does `JSON.parse(args)`.

### `response_format`

Three values land:

* `{type: "text"}` — the default.
* `{type: "json_object"}` — model must produce valid JSON. Most OSS
  servers approximate by injecting a system prompt; few fail-fast on
  invalid output the way OpenAI does.
* `{type: "json_schema", json_schema: {...}}` — schema-constrained
  generation. vLLM and llama.cpp implement this via grammar-based
  sampling. Many shims either ignore the schema or hard-error.

The prober doesn't currently send `response_format` (cost: needs a
real model loaded that supports JSON mode). It's an excellent
follow-up for a Phase B+ check.

### Authentication

OpenAI uses `Authorization: Bearer <key>`. Most OSS servers either
ignore the header or accept any non-empty bearer. A server that *also*
accepts `?api_key=<key>` URL parameters or `X-API-Key` headers is
adding extension behavior — spec-allowed but worth knowing about for
client fallbacks.

### WebSocket: `/v1/realtime`

OpenAI's Realtime API uses a WebSocket bidirectional event stream
rather than HTTP-SSE. `aioc` speaks WS for any catalog row with
`protocol="ws"` set; today that's only `/v1/realtime` but the path
generalizes.

Probe behavior:

* **Phase A** = "did the upgrade succeed?". Grading mirrors HTTP:
  * `101 Switching Protocols` (accepted) → PASS
  * `404` on the upgrade → FAIL (route absent)
  * `401`/`403` → WARN — "auth required" — endpoint exists, we just
    don't have a bearer. Pass `--openai-api-key` (or the `model:`
    action input's sibling `openai-api-key:`) to authenticate.
  * Anything else → FAIL with the upgrade status
  * Connection refused → SKIP (same as HTTP liveness short-circuit)
* **Phase B** sends a `session.update` event with empty modalities
  and waits up to 10s for a `session.created` event back. Grading:
  * `session.created` received → PASS
  * Connected, other events seen, no `session.created` → WARN
  * Connected, no events at all in budget → WARN
* The probe sets `openai-beta: realtime=v1` on every upgrade — the
  subprotocol header OpenAI's server gates on. Servers that don't
  care about it ignore it.

OSS-server status: essentially nobody implements the Realtime API
shape today. Forks that ship a WS event surface (Hume EVI, Sesame
CSM, in-house S2S) almost always use their own event vocabulary;
HT-compat could pin a vendor-neutral version in a future v1.1 if a
reference implementation emerges. For now the catalog probes the
OpenAI shape as `kind="ext"`.

### Context compaction (`/v1/responses/compact`)

OpenAI shipped server-side compaction in 2026 as part of the Responses
API; Codex CLI's `compact_remote.rs` calls it on long sessions to
shed history without losing model latent state. Two surfaces:

* **Standalone** — `POST /v1/responses/compact` with
  `{model, input: [ResponseItem...], tools, parallel_tool_calls, ...}`.
  Returns `{output: [...]}` where one item is
  `{type: "compaction", encrypted_content: "<opaque-AES-blob>"}`. The
  client passes the blob back as part of the next `/v1/responses`
  `input` array; the server decrypts and restores latent state.
* **Inline** — `POST /v1/responses` with
  `context_management: {type: "compaction", compact_threshold: <int>}`.
  When the rendered token count crosses the threshold the server
  emits the same compaction output item in-stream — no separate call.

`encrypted_content` is intentionally opaque (prevents client-side
tampering / prompt injection on summaries; carries internal state
markers OpenAI doesn't expose). Clients MUST NOT inspect or modify
it.

OSS-server status: essentially nobody implements this today. The
catalog probes it as `kind="ext"`; expect ❌ on every non-OpenAI
endpoint. Implementing it server-side without OpenAI's encryption
key requires either:

* A plaintext fallback (drops the tamper-resistance property but
  preserves the shape and the "shed-history" semantics — useful
  enough to be worth a try for forks).
* Or a public-key envelope the fork controls (much heavier).

If/when an OSS implementation emerges, the matrix flips ⚠️ (shape
ok, no encryption) or ✅ (full equivalence).

### Error envelope

The OpenAI error shape:

```json
{
  "error": {
    "message": "...",
    "type": "invalid_request_error",
    "param": "messages",
    "code": "invalid_value"
  }
}
```

Servers that respond to a 400 with `{"detail": "..."}` (FastAPI
default) are deviating; the catalog calls this a WARN because
**every** Python OSS server starts there until someone wires up the
canonical envelope.

## Where to add yours

Open a PR adding to
[`docs/spec/extensions.md`](https://github.com/heiervang-technologies/am-i-openai-compatible/blob/main/docs/spec/extensions.md)
with:

1. The behavior, in one or two sentences.
2. The server(s) that do it.
3. Whether the catalog should flag it as `WARN` or stay silent.
