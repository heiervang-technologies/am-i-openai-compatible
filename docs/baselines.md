# Baselines

Snapshots of what real OpenAI-compatible HTTP servers actually
implement, as observed by `aioc probe`. Each section names a target,
the date/version under which it was probed, and the noteworthy
findings — not the full per-endpoint table.

> **Reading the numbers.** PASS = endpoint exists and (where Phase B
> ran) honors the response shape. WARN = exists but deviates,
> capability-gated 501, or auth-walled WebSocket upgrade. FAIL = 404
> on a required endpoint, malformed response, or non-canonical error
> envelope. SKIP = liveness short-circuit or no model of the required
> kind to test against.

The OpenAI section below is the only public reference baseline kept
here — other baselines live with their respective deployments. To
contribute a baseline for an OSS server (llama.cpp, vLLM, Ollama,
LM Studio, TabbyAPI, …), open a PR adding a section using the same
shape.

---

## OpenAI · `https://api.openai.com`

**Probed:** 2026-05-16 · `aioc 0.3.0`, default `openai` profile,
**unauth** (no `OPENAI_API_KEY` available).

| | |
|---|---|
| PASS | 20 |
| WARN | 0 |
| FAIL | 4 |
| SKIP | 14 |
| Duration | 11.8s |

**Headline:** **`/v1/realtime` accepts unauth WebSocket upgrades.** The
upgrade returns `101 Switching Protocols`; OpenAI then presumably
rejects the first event without a bearer. The probe still grades the
upgrade as PASS — useful signal that the WS surface is wired.

**Other Phase A PASS coverage** spans the entire OpenAI catalog
(`/v1/chat/completions` and its `[stream]` / `[logprobs]` variants,
`/v1/responses`, `/v1/responses/compact`, `/v1/completions`,
`/v1/embeddings`, `/v1/audio/*`, `/v1/images/{generations,edits}`,
`/v1/files`, `/v1/batches`, `/v1/uploads`). All return `401 Unauthorized`
on unauth — graded PASS because the route exists.

**Phase B SKIPs** (14) are all "no model of kind X" — `/v1/models` is
auth-walled so we can't sniff models to template against.

**The four FAILs** are endpoints that don't even reach the auth check
on an empty body and respond with a real error envelope (`/v1/models`
GET returning 401 + body, `/v1/uploads` POST 401, etc.). These are
*not* server bugs — they're just shapes Phase B can't validate
without a bearer.

**Caveat.** Re-running with `--openai-api-key sk-...` would unlock
full Phase B coverage (real chat completions, embeddings, the
Realtime `session.created` event round-trip). The unauth baseline
above is the floor — every endpoint that wasn't a `404` exists.

A nightly canary against `https://api.openai.com` runs from
`.github/workflows/openai-canary.yml`; reports are archived as
build artifacts so drift in OpenAI's own surface is detectable.

---

## How to add or refresh a baseline

1. Run the probe against your target — `aioc probe http://<host>`
   (add `--profile ht` to include HT-compat extension rows;
   `--openai-api-key …` to unlock Phase B against OpenAI).
2. Save the report somewhere durable (`.probe-reports/` is gitignored
   here, so reports stay local unless you commit them explicitly).
3. If the report surfaces real catalog drift — a 404 against a server
   that should implement the endpoint, or a malformed response shape
   — file an issue.
4. To contribute a baseline section to this doc, open a PR with the
   same headline / summary-table / findings shape as the OpenAI
   section above. Keep it factual and short; the per-endpoint detail
   belongs in the probe report, not in prose.
