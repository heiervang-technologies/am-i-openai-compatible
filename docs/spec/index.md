# The OpenAI surface

This section is the *spec* the prober checks any server against. It
intentionally has no implementation-specific knowledge: a server that
claims to be OpenAI-compatible should match the relevant subset.

## Endpoint kinds

Every entry in the catalog is tagged with a **kind**:

| Kind       | Meaning                                                                                     | If missing |
|------------|---------------------------------------------------------------------------------------------|------------|
| `core`     | Required by the canonical OpenAI API as it stands today.                                    | `FAIL`     |
| `optional` | Capability-gated surface such as embeddings, audio, or images.                              | `WARN`     |
| `ext`      | OpenAI extension or successor surface (`/v1/responses`) that newer servers may opt into.    | `SKIP`     |
| `ours`     | Required by the HT profile; excluded from the default OpenAI profile.                       | `FAIL` under `--profile ht` |

Why distinguish? A server with no `/v1/embeddings` is broken if it
claims chat *and* embeddings. A server without `/v1/responses` is just
not bleeding-edge — that's not a defect.

## Phases

The prober runs every endpoint through up to two phases:

* **Phase A — existence.** Send the cheapest probe that should not
  return `404`. Anything else (`200`, `400`, `405`, `415`, `422`,
  `429`) means "the route is wired up".
* **Phase B — signature compliance.** Send one minimal valid request.
  Rows with a registered response model are Pydantic-validated after
  their content/key checks; rows without one enforce the dotted-key
  contract in the catalog. Extras are allowed.

Phase B is skipped when:

* The catalog entry has `phase_b_skip=True` (admin/list routes such as
  `/v1/files`, where an unauthenticated signature call adds no signal).
* `--skip-phase-b` is passed.
* No usable model can be sniffed from `/v1/models` for an endpoint
  that needs one. (Then it reports `SKIP — no model available`.)

## Where the catalog lives

[`src/am_i_openai_compatible/endpoints.py`](https://github.com/heiervang-technologies/am-i-openai-compatible/blob/main/src/am_i_openai_compatible/endpoints.py).

PRs that add or correct entries are the easiest way to contribute. See
[Contributing](../contributing.md).

## Pages in this section

* [Canonical surface](canonical-surface.md) — the full table at a
  glance.
* [Models / discovery](models.md)
* [Chat & completions](chat.md)
* [Audio (TTS / STT)](audio.md)
* [Images & videos](images-videos.md)
* [Embeddings](embeddings.md)
* [Extensions & quirks](extensions.md) — the long tail of
  almost-spec behavior every implementer pretends is portable.
