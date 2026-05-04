# Implementations

Per-server deep-dives. Each page covers what the server actually does
relative to the canonical spec — what's there, what's missing, what's
extended, and what to watch out for in production.

These pages are **opinionated and current as of the date in the page
footer**. OSS servers move fast; if a deviation here doesn't match
what your build does, that's a bug — please open a PR.

## Pages

* [OpenAI (reference)](openai.md) — the moving target.
* [llama.cpp](llama-cpp.md) — `llama-server`, `llamacpp-python`.
* [vLLM](vllm.md) — full surface, fast.
* [Ollama](ollama.md) — opinionated subset.
* [LM Studio](lmstudio.md) — desktop-first.
* [TabbyAPI](tabbyapi.md) — Exllama-based.

## How we score deviations

Each page summarizes the server's behavior against three questions:

1. **What does `aioc probe` say?** A snapshot of the latest known run.
2. **Where does it deviate?** Spec-vs-actual differences worth
   flagging, with the catalog kind (`core` / `ext` / `ours`) so you
   can tell defects from "didn't implement".
3. **What does it add?** Genuine value-adds outside spec — e.g.
   llama.cpp's `cache_prompt`, vLLM's batched logprobs.

A high-deviation server isn't automatically worse — sometimes the
deviation is a feature. The point of these pages is to *describe*
behavior, not to rank servers.

## See also

* [Compatibility matrix](../compatibility-matrix.md) — at-a-glance
  comparison.
