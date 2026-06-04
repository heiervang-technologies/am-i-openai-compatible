# Beyond OpenAI-compat

OpenAI's `/v1/...` surface is the de-facto floor for "what an
LLM-serving HTTP API looks like", but it has model-class gaps —
encoder tasks (QA, NER, classification), reranking, image
segmentation, omni-modal chat, 3D generation, async video jobs.
Servers that fill those gaps tend to invent their own shapes, and
some of those shapes have started to converge into informal (or in
one case, formal) standards.

This page is an honest survey. For each task, it shows:

- what the closest-thing-to-a-canonical shape is on the public
  internet (e.g. Cohere v2 rerank, HF Inference API question-
  answering),
- how OSS servers that implement the task actually wire it
  (TEI, vLLM, ComfyUI shims, …),
- where [HT-compat](spec/ht-compat.md) lands, and why.

Many OpenAI-compatible servers ship one or more of these extensions
under similar-but-not-identical names. If you implement a server,
this page is meant to make it easy to either follow a converged
convention or — if you have to invent — see which prior art exists
and which is the most-cited reference.

!!! note "What counts as a 'standard' here"
    Nothing on this page is a standard in the IETF / W3C sense.
    "Formal" means published by a vendor with a versioned reference
    page (Cohere v2). "Informal" means several independent
    implementations have converged on the same shape without a
    central authority. "Idiosyncratic" means one server's invention,
    cited so readers can identify it but not held up as a target.

---

## Reranking

**Convergence: strong.** Cohere published `/v2/rerank` with stable
field names; vLLM advertises Cohere/Jina compatibility; Voyage AI
mirrors the shape with small tweaks; Jina's rerank API uses the same
core fields. Reranking is the closest thing the post-OpenAI surface
has to an actually-agreed standard.

### Cohere v2 — `POST /v2/rerank` (formal)

**Request:**

```json
{
  "model": "rerank-v4.0-pro",
  "query": "What is the capital of the United States?",
  "documents": [
    "Carson City is the capital city of the American state of Nevada.",
    "Washington, D.C. is the capital of the United States."
  ],
  "top_n": 1
}
```

Optional: `max_tokens_per_doc` (default 4096), `priority` (default 0).

**Response:**

```json
{
  "id": "abc123",
  "results": [{"index": 1, "relevance_score": 0.95}],
  "meta": {"api_version": {...}, "billed_units": {...}}
}
```

No `model` echoed in the response body; no `usage` block (Cohere
puts billing under `meta.billed_units`); `relevance_score` is
unbounded above by spec (commonly in `[0, 1]` for cross-encoders).

### Voyage AI — `POST /v1/rerank`

Same core fields. Renames `top_n` → `top_k`. Adds
`return_documents: bool` (default `false`) — when `true`, each
result includes `document: "..."` (a bare string, not an object).
Adds `truncation: bool` (default `true`).

**Response:**

```json
{"results": [{"index": 0, "relevance_score": 0.92, "document": "..."}]}
```

No `id`, no `meta`. Flatter envelope than Cohere.

### TEI — `POST /rerank`

Source: `huggingface/text-embeddings-inference`. Renames `documents`
→ `texts`, `top_n` → (omitted — server returns all results, sorted),
`return_documents` → `return_text`. No `model` field (TEI serves one
model per process). Adds `truncate`, `truncation_direction`,
`raw_scores`.

**Request:**

```json
{"query": "What is Deep Learning?", "texts": ["...", "..."]}
```

**Response** (bare array, no envelope):

```json
[{"index": 0, "text": "...", "score": 1.0}]
```

Note `score`, not `relevance_score`. Note bare-array response.

### vLLM — `POST /v1/rerank` (and `/v2/rerank`)

Documented as Cohere and Jina compatible. Response uses Cohere's
`results: [{index, document: {text}, relevance_score}]` shape.
`top_n` optional; defaults to all documents. Notable: `document`
nests `text` under an object (matches Cohere's optional response
form when `return_documents: true`).

### HT-compat — `POST /v1/reranking`

Cherry-picked from Cohere v2 as the most-cited reference. Diverges
in three places, intentionally:

| Difference | Why |
|---|---|
| Requires `model` in the request | HT-compat servers are multi-model by convention; the field matches every other `/v1/...` body. |
| Echoes `model` in the response | OpenAI's `/v1/embeddings` and `/v1/chat/completions` envelope; reduces client-side bookkeeping. |
| `usage: {...}` block, no `meta.billed_units` | OpenAI's envelope, applied consistently across HT-compat rows. |

Field names (`query`, `documents`, `top_n`, `return_documents`,
`relevance_score`) match Cohere v2 verbatim.

---

## Sequence classification (supervised + zero-shot)

**Convergence: weak.** Each major server picks a different field
shape and response envelope. HF Inference API and TEI both come from
the same upstream (transformers pipelines) but expose the task
differently over HTTP.

### Hugging Face Inference API — `POST /models/{model}` (`text-classification` task)

The HF Inference Provider wire shape: a flat `{inputs, parameters}`
envelope, repeated across every task. The model is part of the URL,
not the body.

**Request:**

```json
{
  "inputs": "I love this product.",
  "parameters": {"function_to_apply": "softmax", "top_k": 3}
}
```

`function_to_apply` ∈ `{"sigmoid", "softmax", "none"}`.

**Response** (bare array, no envelope):

```json
[
  {"label": "POSITIVE", "score": 0.999},
  {"label": "NEGATIVE", "score": 0.001}
]
```

### HF Inference API — `zero-shot-classification`

Same `{inputs, parameters}` envelope. `parameters.candidate_labels`
is required; `hypothesis_template` and `multi_label` optional.

```json
{
  "inputs": "I have a problem with my iPhone.",
  "parameters": {
    "candidate_labels": ["urgent", "not urgent", "tech support"],
    "multi_label": false
  }
}
```

Response is `[{label, score}]` (same shape as supervised — the
upstream pipeline normalizes both paths to one).

### TEI — `POST /predict`

TEI flattens `parameters` into the top-level body (no nesting). No
`model` field (single-model server). Adds `raw_scores: bool` for
pre-activation scores. The response wraps differently for single vs
batched input:

**Request (single):**

```json
{"inputs": "I like you.", "raw_scores": false}
```

**Response (single — flat array):**

```json
[{"score": 0.95, "label": "admiration"}]
```

**Response (batched, when `inputs` is `[[...], [...]]`):**

```json
[
  [{"score": 0.95, "label": "admiration"}],
  [{"score": 0.91, "label": "joy"}]
]
```

Note `score`/`label` field order is reversed from HF (`label` first
in HF, `score` first in TEI). Functionally identical.

### vLLM — `POST /classify` (and `/v1/classify`)

vLLM ships a real OpenAI-shaped envelope here, the only encoder-task
server in this survey that does. Note the response carries
**probability vectors**, not per-label rows — clients have to map
`probs[i]` to label index themselves (or look at the top-1 via the
`label` field).

**Request:**

```json
{"model": "jason9693/Qwen2.5-1.5B-apeach", "input": "Loved it."}
```

**Response:**

```json
{
  "id": "classify-9bf17f...",
  "object": "list",
  "model": "jason9693/Qwen2.5-1.5B-apeach",
  "data": [
    {"index": 0, "label": "Default", "probs": [0.566, 0.434], "num_classes": 2}
  ],
  "usage": {"prompt_tokens": 10, "total_tokens": 10}
}
```

`object: "list"` and `data: [...]` mirror `/v1/embeddings`'s envelope.

### HT-compat — `POST /v1/classifications`

Unifies supervised and zero-shot under one endpoint; the request
distinguishes by the presence of `candidate_labels`. Response is
sorted by `score` descending — easier to consume than HF's
arbitrary order.

```json
{
  "model": "facebook/bart-large-mnli",
  "input": "The new lens has excellent low-light performance.",
  "candidate_labels": ["positive", "negative", "neutral"],
  "multi_label": false
}
```

```json
{
  "id": "classify-...",
  "model": "facebook/bart-large-mnli",
  "classifications": [
    {"label": "positive", "score": 0.94},
    {"label": "neutral",  "score": 0.05},
    {"label": "negative", "score": 0.01}
  ],
  "usage": {"total_tokens": 18}
}
```

Diverges from HF/TEI by lifting `candidate_labels` to top-level
(matches OpenAI's `/v1/embeddings` flat-body convention) and naming
the result key `classifications` (task-meaningful, matches
`/v1/moderations.results` precedent). Diverges from vLLM by
returning `[{label, score}]` rows rather than `[{probs[], label}]`
— directly consumable, no client-side index math.

---

## Extractive question answering

**Convergence: weak.** Only Hugging Face exposes QA as a stable HTTP
task; TEI doesn't have it, vLLM doesn't have it. The HF shape is
effectively the only prior art.

### HF Inference API — `question-answering`

```json
{
  "inputs": {
    "context": "Mount Everest is the highest mountain above sea level.",
    "question": "What is the highest mountain?"
  },
  "parameters": {"top_k": 1}
}
```

Parameters: `top_k`, `doc_stride`, `max_answer_len`, `max_seq_len`,
`max_question_len`, `handle_impossible_answer`, `align_to_words`.

**Response** (bare array):

```json
[{"answer": "Mount Everest", "score": 0.98, "start": 0, "end": 13}]
```

### HT-compat — `POST /v1/qa`

```json
{
  "model": "deepset/roberta-base-squad2",
  "input": {"context": "...", "question": "..."},
  "top_k": 1
}
```

Keeps HF's `(context, question)` nesting and response field names.
Diverges: nesting is under `input` (matches OpenAI's other
`/v1/...` bodies; HF uses `inputs`), parameters are flat
(no `parameters: {...}` wrapper), and the response wraps in
`{id, model, answers, usage}`. The
[spec](spec/ht-compat.md#v1qa-extractive-question-answering-v11) pins
`context[start:end] == answer` as a hard invariant — easier to
contract-test than HF's "characters of the input" wording.

A subset of `parameters` is intentionally not in v1.1:
`max_seq_len`, `max_question_len`, `doc_stride`, `align_to_words`
are implementation-tuning knobs that don't change the response
shape and can be added in a later minor without breakage.

---

## Token classification (NER)

**Convergence: weak.** HF defines the task; few servers expose it
as a first-class endpoint.

### HF Inference API — `token-classification`

```json
{
  "inputs": "Hugging Face Inc. is based in New York.",
  "parameters": {"aggregation_strategy": "simple", "ignore_labels": ["O"]}
}
```

`aggregation_strategy` ∈ `{"none", "simple", "first", "average", "max"}`
— **load-bearing**: with `"none"`, response rows carry the raw
BIO-prefixed `entity` field; with any other value, rows carry the
aggregated `entity_group` field. Two response shapes from one
endpoint.

**Response** (aggregated, bare array):

```json
[
  {"entity_group": "ORG", "score": 0.99, "word": "Hugging Face Inc.", "start": 0, "end": 17},
  {"entity_group": "LOC", "score": 0.99, "word": "New York", "start": 30, "end": 38}
]
```

**Response** (`"none"` — per-token):

```json
[
  {"entity": "B-ORG", "score": 0.99, "word": "Hugging", "start": 0, "end": 7},
  {"entity": "I-ORG", "score": 0.98, "word": "Face", "start": 8, "end": 12}
]
```

### TEI — `POST /predict` (token-classification models)

TEI re-uses `/predict` for token classification, but the response
loses the `word`/`start`/`end` context — you get just `[{score,
label}]` per token. Useful only if the client retains its own
tokenization. Not really a NER-shaped endpoint.

### HT-compat — `POST /v1/ner`

```json
{
  "model": "dslim/bert-base-NER",
  "input": "Hugging Face Inc. is based in New York.",
  "aggregation_strategy": "simple"
}
```

Keeps HF's `aggregation_strategy` semantics verbatim, including the
load-bearing entity/entity_group switch. Wraps in
`{id, model, entities, usage}`. Pins document order (not
score-sorted) — NER scores cluster near-identically and document
order is the actionable layout.

---

## Other "beyond OpenAI-compat" surface

Where convergence is weak or absent, [HT-compat](spec/ht-compat.md)
proposes a shape and points at the one or two implementations that
implement it.

| Task | Closest reference | HT-compat | Notes |
|---|---|---|---|
| Omni-modal chat (audio in/out) | vLLM-Omni serving Qwen2.5-Omni | `/v1/chat/completions[omni]` — same path, `modalities: ["text","audio"]` + `input_audio` content parts | Convergence: weak (one reference impl). |
| Image segmentation (promptable) | Meta SAM3 (Python reference) | `/v1/segmentations` — multipart with `image` + `prompts` JSON | Convergence: none; HT-compat is the first HTTP shape. |
| Audio extraction (promptable) | Meta SAM-Audio (Python reference) | `/v1/audio/segmentations` | Convergence: none. |
| Layered image generation | Qwen-Image-Layered | `/v1/images/decompositions` | Convergence: none. |
| 3D mesh generation | TRELLIS-2, Hunyuan3D via ComfyUI | `/v1/3d/generations` — async job model | Convergence: emerging — ComfyUI workflow shims tend to share this shape. |
| Async video generation | OpenAI Sora-shape | `/v1/videos` | Sora is the only formal reference; OSS implementers mostly extend the Sora shape with their own model-specific fields. |

Audio source separation (Demucs-style), music generation (MusicGen),
SAM3-video, and per-model `x_ht_compat` capability advertisement are
deferred to a future HT-compat release — see the
[deferred section of the spec](spec/ht-compat.md#deferred-to-v12).

---

## Patterns the survey makes obvious

- **Envelope discipline differs.** OpenAI wraps every list response
  in `{id, model, data: [...], usage}` (embeddings) or
  `{id, model, choices: [...], usage}` (chat). HF and TEI return
  bare arrays. Cohere v2 wraps in `{id, results, meta}`. vLLM picks
  envelope-or-bare per endpoint. HT-compat picks the OpenAI envelope
  consistently — predictable for clients, even if it adds bytes.
- **Field naming for the result key matters.** When the result is
  task-meaningful (answers, entities, classifications, results),
  naming the key after the task documents intent in the wire shape.
  Generic `data` works for embeddings (where each row is
  task-agnostic) but obscures the task when the rows have semantic
  structure.
- **Parameters: flat vs nested.** HF's `{inputs, parameters}` ages
  poorly when you add a `model` field — now you have three
  top-level keys and an awkward `parameters` bag. OpenAI never
  introduced a `parameters` nesting and HT-compat follows that.
- **Multi-input batching is unsolved.** HF uses `inputs: [...]`,
  TEI uses `inputs: [[...]]` for some tasks, vLLM and Cohere use
  `documents` arrays for rerank specifically. HT-compat 1.1 punts
  on this — v1.1 servers MUST `400` on array-valued `input` rather
  than guess.

---

## References

- Cohere v2 rerank: <https://docs.cohere.com/v2/reference/rerank>
- Voyage AI rerank: <https://docs.voyageai.com/reference/reranker-api>
- TEI source (request/response structs):
  <https://github.com/huggingface/text-embeddings-inference/blob/main/router/src/http/types.rs>
- vLLM scoring/rerank/classify usage docs:
  <https://docs.vllm.ai/en/latest/models/pooling_models/scoring/>,
  <https://docs.vllm.ai/en/latest/models/pooling_models/classify/>
- HF Inference API tasks (per-task pages under
  <https://huggingface.co/docs/api-inference/tasks/>):
  question-answering, token-classification, text-classification,
  zero-shot-classification.
- HT-compat spec: [spec/ht-compat.md](spec/ht-compat.md).

If you maintain a server that implements one of these extensions and
the wire shape isn't reflected here, open a PR adding your shape's
side-by-side entry; the goal of this page is the same as
`docs/baselines.md` — to make the actual landscape visible.
