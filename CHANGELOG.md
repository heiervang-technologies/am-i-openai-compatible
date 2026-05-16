# Changelog

Notable changes per release. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Probe-target baselines (2026-05-16)

- `docs/baselines.md` — per-target findings against OpenAI
  (`api.openai.com`), `titan-comfy-openai`, the `lile-daemon`, and
  the `lile-proxy`. Reports archived under `.probe-reports/`
  (gitignored). Surfaced two real server bugs on `titan-comfy-openai`
  (filed to `heiervang-technologies/cloud#113`) and three Codex-CLI
  compat gaps on lile (notified to the agi/lile maintainer).
- Probe-target inventory tracked in #10.

## [0.3.1] — 2026-05-16

Catalog drift cleanup + CI bump (PRs #8, #9).

### Removed

- `/v1/images/variations` catalog row. OpenAI returns 404 on this
  path (verified via unauth probe of `api.openai.com` on
  2026-05-16); their docs no longer list it. Canonical
  image-variation flow is `/v1/images/edits` with `gpt-image-1`.
  Regression test guards against accidental re-add. Compatibility
  matrix gains a "Retired" section. (PR #8, closes #7.)

### Changed

- `/v1/uploads` row switched from `GET` (existence-only) to `POST`
  with the canonical Uploads-API create body
  (`purpose`/`bytes`/`filename`/`mime_type`); validates `id` +
  `object` on the response. Removed from probe.py's admin-routes
  Phase-B-skip list so the new shape actually runs. (PR #8.)

### CI

- Test matrix extended to Python 3.13 + 3.14 (was capped at 3.12).
  Trove classifiers updated to match. (PR #9.)

## [0.3.0] — 2026-05-16

Two feature branches landed via squash merges (PRs #5, #6).

### feat/v0.3-websocket branch (issue #4, PR #6)

- **WebSocket protocol support.** New `_phase_b_ws` path in the Prober,
  routed via a new `protocol="ws"` field on the `Endpoint` dataclass.
  Adds `websockets>=13` as a hard dependency.
- **`/v1/realtime` catalog row** — OpenAI's Realtime API. Phase A grades
  the upgrade (101=PASS, 404=FAIL, 401/403=WARN auth-required), Phase B
  sends a `session.update` event and waits for `session.created`.
- **`--openai-api-key`** flag on the CLI + action input. Forwarded as
  `Authorization: Bearer <key>` on WS upgrades; ignored for REST.
- **`openai-beta: realtime=v1`** header set on every WS upgrade so
  servers that gate on the subprotocol let the probe through.
- 6 new tests (`test_ws_probe.py`) covering all 5 grading paths plus
  auth-header forwarding, running against an in-process `websockets`
  server.

### feat/v0.2.1-model-select branch (issue #3, PR #5)

- `--model NAME` override for Phase B body model selection — pins a
  known-good model id for router-mode servers where `/v1/models[0]`
  is arbitrary. Kind-aware fallback: a chat-classified override
  doesn't hijack `/v1/embeddings` probes.
- Phase B grades HTTP 503 with the canonical envelope as **WARN**,
  mirroring how Phase A grades 501. 500 stays FAIL — we don't
  downgrade real server bugs.
- Phase B accepts any 2xx (not just 200) — surfaced when comfy-openai
  returned 202 on `/v1/videos`.
- `model` input added to `action.yml`; forwards as `--model` to the
  CLI.
- `image_url` canonical field accepted on `/v1/3d/generations` and
  `/v1/videos` request bodies (alias for `image` server-side for
  backwards compat).
- **`/v1/3d/generations`** promoted from v1.1-deferred to a full
  HT-compat-1.0 endpoint: async job submission for TRELLIS-2 /
  Hunyuan3D / InstantMesh, mirroring `/v1/videos`. Reference backend
  is ComfyUI via the 3D node packs. New catalog row (`kind="ours"`,
  `requires_model_kind="3d"`), `_classify_kind` learns `trellis` /
  `hunyuan3d` / `instantmesh` patterns, respx Phase B test, matrix
  row.
- **`/v1/responses/compact`** — Codex CLI compaction endpoint,
  OpenAI-compat `ext`. `CompactionInput` shape cribbed from
  `openai/codex codex-rs/codex-api/src/common.rs`.
- Spec doc tightens HT-compat http(s) URL fetching from MUST to MAY.

## [0.2.0] — 2026-05-13

### Added

- **HT-compat profile** — `aioc probe URL --profile ht` adds
  opinionated `/v1/...` signatures for model classes OpenAI doesn't
  pin yet. See [`docs/spec/ht-compat.md`](docs/spec/ht-compat.md).
- Five new `kind="ours"` catalog rows: `/v1/reranking`,
  `/v1/segmentations`, `/v1/audio/segmentations`,
  `/v1/chat/completions[omni]`, `/v1/images/decompositions`.
- `--profile {openai,ht}` flag on the CLI and the GitHub Action.
  Under `ht`, a 404 on a `ours` row grades FAIL (mirror of `core`).
- Step summary splits into "OpenAI compat" / "HT compat" sections.
- [`docs/ht-compatibility-matrix.md`](docs/ht-compatibility-matrix.md)
  — adoption tracker with scope-per-fork callout.
- 11 respx tests for HT profile filtering and per-endpoint Phase B.
- 4 respx tests for the step-summary section split.
- `examples/ci/llama-cpp.yml` gains a discovery-mode HT probe job.

### Changed

- Catalog `kind` field documented: profile-dependent grading for
  `ours` (SKIP under openai, FAIL under ht). `optional`,
  `core`, `ext` semantics unchanged.

## [0.1.1] — 2026-05-08

### Added

- `optional` kind for capability-gated endpoints (audio, images,
  embeddings). 404 or 501 on `optional` → WARN, not FAIL.
- 501-with-self-describing-body surfacing: Phase A grades 501 with
  the server's own `error.message` verbatim, no substring guessing.
- `/v1/chat/completions[logprobs]` row probing the `logprobs:
  true, top_logprobs: 3` shape.
- Streaming `stream_options: {include_usage: true}` opt-in per spec.
- `--endpoints-filter REGEX` to scope a run.
- Composite GitHub Action with `aioc-version: git+...` ref support
  for pre-release pinning.
- `scripts/postprocess.py` — counts to GITHUB_OUTPUT, step summary
  to GITHUB_STEP_SUMMARY, `fail-on` threshold gating.
- 22 respx tests covering the new probe behavior.

### Fixed

- `--embedding` → `--embeddings` in docs.
- Compatibility matrix streaming `usage` row reflects the
  `stream_options.include_usage` reality.

## [0.1.0] — earlier

Initial scaffold: catalog, Prober, gap analyzer, mkdocs site.
