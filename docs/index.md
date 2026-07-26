# Am I OpenAI Compatible?

> Every implementation claims to speak the OpenAI API.
> This project tells you which parts they actually got right.

## What "OpenAI-compatible" really means

The phrase has been worn smooth by overuse. When a project says it's
*OpenAI-compatible*, it almost always means **some endpoints, some
fields, in some configurations, with caveats nobody documented**.

That ambiguity is fine when you're prototyping locally. It becomes
expensive the moment you swap servers and discover that your client
silently relied on `usage.completion_tokens`, or `seed`, or
`response_format: json_schema`, or the existence of `/v1/responses`.

This site is two things at once:

1. **A probe** — `aioc probe <url>` tells you exactly what a server
   implements and where it deviates, in a few seconds.
2. **A reference** — an honest, opinionated catalog of the OpenAI
   surface plus per-implementation deep-dives, kept current by people
   who actually run these servers in production.

[Get started](getting-started.md){ .md-button .md-button--primary }
[See the matrix](compatibility-matrix.md){ .md-button }
[HT-compat extensions](spec/ht-compat.md){ .md-button }

## Why a separate spec?

OpenAI's docs describe the production API as it stands today. They
don't describe:

* what's been *removed* (legacy `/v1/completions`, plugin manifest
  endpoints, fine-tune v1 endpoints…) but is still widely implemented
  by OSS projects;
* what's a *de facto extension* (e.g. `seed` in chat completions,
  `response_format: json_schema`, `tool_choice: required`) versus a
  hard-spec field;
* what's *aspirational* (`/v1/responses`, the upcoming Realtime API)
  versus shipped;
* what individual servers have *added* (vLLM's batched logprobs,
  llama.cpp's `cache_prompt`, comfy-openai's `/v1/videos` job model).

The catalog in
[`endpoints.py`](https://github.com/heiervang-technologies/am-i-openai-compatible/blob/main/src/am_i_openai_compatible/endpoints.py)
is the source of truth. Each entry is tagged `core`, `optional`,
`ext`, or `ours`, so a server that lacks a `core` endpoint is a hard
fail and one that lacks an `ext` is a documented absence. The `ours`
rows belong to the [HT-compat profile](spec/ht-compat.md) — an
opinionated extension covering model classes (segmentation, omni
chat, reranking, layered image gen) that OpenAI doesn't yet have
endpoints for.

## Headline claims

* **Single command, no auth, no spinup.** `aioc probe URL` works
  against a running server. No SDK, no API key.
* **Tiny budget.** One shared `/v1/models` discovery request, then ≤ 2
  requests per selected endpoint, with `max_tokens=4` and 512×512
  images. Safe to point at production.
* **Real validation, not just `200 OK`.** Standard surfaces with a
  registered response schema are validated against Pydantic models;
  the remaining surfaces enforce their cataloged key contracts.
  Extras are allowed so server-added metadata doesn't fail validation.
* **No cluster assumptions.** The probe doesn't know about your
  setup. It only knows the spec, which is one Python file.
* **Open catalog.** Spec drift goes through pull requests. Every entry
  cites the spec source and any known deviations.

## What this is not

* Not a benchmark. We don't measure latency, throughput, or quality.
* Not a conformance certification. PASS in `aioc` means "the shape is
  right against the catalog as of this commit". Update the catalog,
  update the meaning.
* Not a substitute for real client integration testing. Real clients
  rely on subtler behavior than a one-shot prober can cover (long
  contexts, function-calling chains, multi-turn streaming).
