# Baselines

Snapshots of what real OpenAI-compatible HTTP servers actually
implement, as observed by `aioc probe`. Each section names a target,
the date/version under which it was probed, and the noteworthy
findings — not the full per-endpoint table (those live in
`.probe-reports/*.json`).

All probes below were run against `aioc 0.3.0` (27 catalog rows
across `core / optional / ext / ours` kinds plus the `/v1/realtime`
WebSocket row).

> **Reading the numbers.** PASS = endpoint exists and (where Phase B
> ran) honors the response shape. WARN = exists but deviates,
> capability-gated 501, or auth-walled WebSocket upgrade. FAIL = 404
> on a required endpoint, malformed response, or non-canonical error
> envelope. SKIP = liveness short-circuit or no model of the required
> kind to test against.

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
| Report | `.probe-reports/openai-api-com-2026-05-16-v0.3.json` |

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

---

## ht-comfy-openai (titan) · `http://192.168.8.170:30385`

In-house ComfyUI translator pod maintained by the `snoop-kube` agent.
Translates ComfyUI workflows into the OpenAI surface for images,
videos, and (as of v0.2.1 / PR #5) 3D generation.

### `openai` profile

**Probed:** 2026-05-16 · `aioc 0.3.0`, default profile.

| | |
|---|---|
| PASS | 6 |
| WARN | 4 |
| FAIL | 14 |
| SKIP | 0 |
| Duration | 15.5s |
| Report | `.probe-reports/titan-comfy-2026-05-16.json` |

**Surface:** model discovery works (`/v1/models`, `/v1/models/{id}`).
Capability-gated endpoints (`/v1/audio/speech`,
`/v1/audio/transcriptions`, `/v1/embeddings`) honestly 404 → WARN. No
chat — this pod doesn't pretend.

**Two real bugs found:**

* **`/v1/images/edits` returns `500 Internal Server Error`** on an
  empty multipart body where 4xx is the OpenAI canonical response.
  Worth a ticket to snoop-kube — looks like missing input-validation
  before the worker dispatch.
* **`/v1/images/generations` times out** at the 15s probe budget.
  Either slow first-request warmup or the row's tiny synthetic-image
  body trips the ComfyUI workflow. Probably benign in production, but
  the probe can't grade it.

### `ht` profile

**Probed:** 2026-05-16 · `aioc 0.3.0`, `--profile ht`.

| | |
|---|---|
| PASS | 10 |
| WARN | 4 |
| FAIL | 19 |
| SKIP | 0 |
| Duration | 15.4s |
| Report | `.probe-reports/titan-comfy-ht-2026-05-16.json` |

**HT-compat row coverage:**

| Endpoint | Result |
|---|---|
| `/v1/3d/generations` | ✅ Phase A PASS (400 on empty body — route exists, validation works) |
| `/v1/videos` | ✅ Phase A PASS (422 on empty body — route exists, schema validation) |
| `/v1/reranking` | ❌ 404 |
| `/v1/segmentations` | ❌ 404 |
| `/v1/audio/segmentations` | ❌ 404 |
| `/v1/chat/completions[omni]` | ❌ 404 (no chat surface at all on this pod) |
| `/v1/images/decompositions` | ❌ 404 |

Two HT endpoints live, five not implemented — exactly what you'd
expect from a ComfyUI translator: image/video/3D pipelines, no LLM
surface.

---

## lile / live-learn (daemon) · `http://127.0.0.1:8768`

In-house RLVR training daemon (`~/ht/agi/lile`). Exposes an
OpenAI-shaped `/v1/*` surface intended primarily as a learn-loop
endpoint, not a general-purpose model router.

**Probed:** 2026-05-16 · `aioc 0.3.0`, `--skip-phase-b` (chat-only
surface, no `/v1/models` sniff).

| | |
|---|---|
| PASS | 3 |
| WARN | 5 |
| FAIL | 12 |
| SKIP | 3 |
| Report | `.probe-reports/lile-daemon-2026-05-16.json` |

**Surface:** `/v1/chat/completions` family is the entire footprint —
the three `chat/completions[*]` rows PASS Phase A. Every other
core/ext endpoint returns 404. Optional capability endpoints
(`/v1/audio/speech`, `/v1/audio/transcriptions`, `/v1/embeddings`,
`/v1/images/generations`) honestly 404 → WARN.

**Notable absence:** `/v1/models` returns 404 → FAIL. lile is
chat-only and doesn't advertise discovery; clients have to know the
model name out-of-band. Worth a follow-up to either implement
`/v1/models` returning a single-element list, or document this
deliberate omission.

**`/v1/realtime` returns 403** on the WS upgrade — graded WARN ("auth
required"). Probably accidental; lile's chat surface is unauth
otherwise.

---

## lile demo proxy · `http://127.0.0.1:8766`

The companion proxy that fronts the daemon (`LILE_PROXY_BIND`).

**Probed:** 2026-05-16 · `aioc 0.3.0`, `--skip-phase-b`.

| | |
|---|---|
| PASS | 0 |
| WARN | 14 |
| FAIL | 5 |
| SKIP | 1 |
| Report | `.probe-reports/lile-proxy-2026-05-16.json` |

**Headline:** **the proxy returns `501 Not Implemented` with a Python
stdlib `<!DOCTYPE HTML>` error page** on every chat/audio/images
endpoint. That's *technically* the capability-gated response —
`aioc` correctly grades it WARN — but the HTML body breaks the
OpenAI canonical error envelope contract (HT-compat-1.0 explicitly
calls this out as non-compliant; see
[the error-envelope section](spec/ht-compat.md#error-envelope-required)).

**Follow-up:** patch the proxy to wrap responses in
`{"error": {"message": "...", "type": "..."}}` JSON so OSS clients
that parse the canonical shape don't choke.

---

## llama.cpp · vanilla (no HT patches)

Not probed in this round directly from the maintainer host — the
canonical baseline lives inside
[`heiervang-technologies/ht-llama.cpp`](https://github.com/heiervang-technologies/ht-llama.cpp)'s
own CI workflow, which runs `aioc` against a freshly-booted
`llama-server` on every PR.

The fork's most recent baseline (CI run 25821142550 on
`feat/ci-aioc-compat-probe`) showed `/v1/reranking` returning **501
with the canonical OpenAI error envelope** when booted without
`--reranking` — the HT-compat capability-gating contract done right.

---

## ht-llama.cpp (lithium) · multi-model router

**Probed:** 2026-05-21 · `aioc 0.3.0`, `ht` profile, against a live
deploy on lithium (`/app/llama-server --models-preset llama-router.ini
--models-max 1`). Tunneled to the maintainer host over SSH to the pod
IP `10.42.5.233:8080`. 12 models served (text + embedding + omni).

| | Phase A only | Phase A + B |
|---|---|---|
| PASS | 10 | 3 |
| WARN | 2 | 2 |
| FAIL | 15 | 22 |
| Duration | 0.3s | 71s |
| Report | `.probe-reports/lithium-ht-llama-cpp-2026-05-21-phaseA.json` | `.probe-reports/lithium-ht-llama-cpp-2026-05-21.json` |

**Headline finding:** Phase A on this fork PASSes `/v1/reranking` and
`/v1/chat/completions[omni]` — both HT-compat extensions wired up
beyond vanilla llama.cpp. **But under Phase B with the default 12s
budget, six chat/embedding rows time out** because the router
autoloads the target model on first request and cold-load on this
hardware exceeds 12s.

**Warm-budget re-probe** (90s timeout, chat/embedding/rerank/omni
only, report `.probe-reports/lithium-ht-llama-cpp-2026-05-21-warm.json`):

| Endpoint | Status | Detail |
|---|---|---|
| `/v1/chat/completions` | ● PASS | shape ok |
| `/v1/chat/completions[stream]` | ● PASS | chunks=4, [DONE]=True |
| `/v1/embeddings` | ▲ 501 WARN | capability gated; needs `--embeddings` boot flag |
| `/v1/reranking` | ▲ 501 WARN | capability gated; needs `--reranking` boot flag |
| `/v1/chat/completions[omni]` | ✖ FAIL | `choices[0].message.audio.data` missing — partial omni impl |

(The original 2026-05-21 run graded those two 501 rows as FAIL — Phase
B's grading was stricter than Phase A's at the time. That asymmetry
was fixed in commit `5eea1c2`; re-running today produces the WARN rows
shown above.)

**Real findings worth filing:**

1. ~~**Phase B grades canonical 501 as FAIL, Phase A grades it as
   WARN.**~~ Fixed in `5eea1c2`: Phase B `_phase_b_post / _get / _sse`
   now grade a 501-with-envelope as WARN, matching Phase A. New
   regression test in `tests/test_probe_mock.py::test_phase_b_501_with_envelope_grades_warn`.
2. **Omni signature gap on this fork.** `/v1/chat/completions[omni]`
   returns 200 but without `audio.data` in the message — i.e. text
   half of the omni contract works, audio output not yet wired. The
   `vllm-omni` baseline (TBD) is the canonical reference here.
3. **`/v1/models` already exposes per-model modality metadata** via
   `architecture.input_modalities` / `architecture.output_modalities`
   plus a `status.value` field (`loaded` / `unloaded`). That's the
   de-facto answer to #2's "per-model capability advertisement" item
   for the modality axis. A formal `x_ht_compat` array (covering
   capabilities like `reranking`, `omni`, `embedding`) would still be
   additive.

The `aioc-demo.gif` in the README is the Phase A render of this
target — its green PASSes on `/v1/reranking` and
`/v1/chat/completions[omni]` represent route-existence only; Phase B
shows where the surface meets reality.

### v1.1 endpoint addendum (2026-06-04, ht-compat 1.1 branch)

Re-probed lithium against the `feat/ht-compat-1.1-bert` aioc to
validate the new BERT-style catalog rows wire up correctly. Used
`--skip-phase-b` for a 40-event Phase A sweep plus a focused
`--endpoints-filter '^/v1/(qa|ner|classifications)$'` run.

All three v1.1 rows grade as expected on a chat-only server:

| Endpoint              | Phase A status | HTTP | Notes |
|---|---|---|---|
| `/v1/qa`              | ✖ FAIL | 404 | route absent (vanilla llama-server has no encoder backend) |
| `/v1/ner`             | ✖ FAIL | 404 | same |
| `/v1/classifications` | ✖ FAIL | 404 | same |

Under `--profile ht`, a 404 on a `kind="ours"` row grades FAIL by
design (the server claims HT-compat but is missing a required
endpoint). The 40-event sweep totals **FAIL=18 · PASS=10 · SKIP=10 ·
WARN=2** — the FAIL bucket is dominated by the new v1.1 rows
plus the existing `ours` rows for segmentations / decompositions /
audio-segmentations / 3d / videos. Reports archived under
`.probe-reports/lithium-ht-llama-cpp-2026-06-04.json` and
`.probe-reports/lithium-v11-2026-06-04.json` (gitignored).

This is the catalog wire-up evidence — confirms the requires_model_kind
classifier paths (`qa`/`ner`/`classify`) don't accidentally pick up
chat models, and the Phase A 404→FAIL grading covers the new rows.
**Not** evidence that lithium implements these endpoints (it doesn't,
and isn't expected to — encoder-only tasks are out of scope for a
decoder-focused llama.cpp fork). The matrix row remains ❌.

---

## vLLM · `~/ht/forks/ht-vllm`

**Not yet probed** in this round — no live deployment URL available
to the maintainer host as of 2026-05-16.

`snoop-kube` (`~/ht/cloud`) likely owns the cluster spec; once a
service URL exists, the command is:

```bash
aioc probe http://<vllm-host>:8000 --name vllm
```

---

## vllm-omni · `~/ht/forks/ht-vllm-omni`

**Not yet probed** for the same reason as vanilla vLLM. This is the
only known `/v1/chat/completions[omni]` reference implementation —
worth re-baselining under `--profile ht` once available:

```bash
aioc probe http://<vllm-omni-host>:8000 --name vllm-omni \
  --profile ht --model qwen2.5-omni-7b
```

---

## How to refresh

1. Run the probe (commands per section above).
2. Archive the report under `.probe-reports/<service>-<date>.json` —
   the directory is gitignored, durable across `/tmp` wipes.
3. If the report surfaces real catalog drift (a 404 against a server
   that should implement the endpoint), file a follow-up issue.
4. Update [the compatibility matrix](compatibility-matrix.md) and (for
   `--profile ht` runs) [the HT-compat matrix](ht-compatibility-matrix.md).

Tracked in [issue #10](https://github.com/heiervang-technologies/am-i-openai-compatible/issues/10).
