"""Canonical OpenAI API endpoint catalog.

This is the spec the generic prober checks any base URL against. It
intentionally has no cluster-specific knowledge — any service that
claims to be OpenAI-compatible should match the relevant subset of
this surface.

Each endpoint declares:

  path              HTTP path (may include {model} which probe.py
                    sniffs from /v1/models)
  method            "GET" / "POST" / "DELETE" …
  group             rough grouping for reporting (chat / audio / …)
  kind              "core"  → required-by-spec; missing = FAIL
                    "ext"   → an OpenAI extension (newer / optional);
                              missing = SKIP
                    "ours"  → our own extension (e.g. /v1/videos);
                              missing = SKIP
  existence_only    if True, never run Phase B (just check 404 vs not)
  body              JSON body for the minimal Phase B call, or None.
                    {model} is substituted from a sniffed id.
  multipart         if True, body is form fields and a tiny WAV/PNG
                    file is attached (path keyed by name).
  expects           shape validator: list of "key.path" that must be
                    present in the JSON response, or one of the
                    sentinel strings:
                      "audio"   → response is non-JSON audio bytes
                      "image"   → image bytes / b64
                      "sse"     → text/event-stream
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Endpoint:
    path: str
    method: str = "GET"
    group: str = "misc"
    kind: str = "core"  # core | ext | ours
    body: dict | None = None
    multipart: bool = False
    expects: object = ()  # tuple of dotted keys, or sentinel str
    requires_model_kind: str | None = None  # "chat" | "embed" | "asr" | …
    notes: str = ""


# ---------------------------------------------------------------------------
# Catalog. Order matters only for output: we sort by group then path.
# ---------------------------------------------------------------------------

ENDPOINTS: list[Endpoint] = [
    # --- models / discovery ---------------------------------------------
    Endpoint(
        path="/v1/models",
        method="GET",
        group="models",
        kind="core",
        expects=("data",),
        notes="discovery; required for any compat surface",
    ),
    Endpoint(
        path="/v1/models/{model}",
        method="GET",
        group="models",
        kind="core",
        expects=("id", "object"),
        notes="retrieve a single model — many OSS impls return 404",
    ),
    # --- chat / completions ---------------------------------------------
    Endpoint(
        path="/v1/chat/completions",
        method="POST",
        group="chat",
        kind="core",
        body={
            "model": "{model}",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 4,
            "temperature": 0,
        },
        expects=("choices.0.message.content", "choices.0.finish_reason"),
        requires_model_kind="chat",
    ),
    Endpoint(
        path="/v1/chat/completions[stream]",
        method="POST",
        group="chat",
        kind="core",
        body={
            "model": "{model}",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 4,
            "stream": True,
        },
        expects="sse",
        requires_model_kind="chat",
        notes="separate row so a missing-stream regression is visible",
    ),
    Endpoint(
        path="/v1/completions",
        method="POST",
        group="chat",
        kind="ext",
        body={"model": "{model}", "prompt": "hello", "max_tokens": 4},
        expects=("choices.0.text",),
        requires_model_kind="chat",
        notes="legacy text completion — many newer servers omit it",
    ),
    Endpoint(
        path="/v1/responses",
        method="POST",
        group="chat",
        kind="ext",
        body={"model": "{model}", "input": "hi"},
        expects=("output",),
        requires_model_kind="chat",
        notes="newer Responses API; few OSS servers implement",
    ),
    # --- embeddings ------------------------------------------------------
    Endpoint(
        path="/v1/embeddings",
        method="POST",
        group="embed",
        kind="core",
        body={"model": "{model}", "input": "hi"},
        expects=("data.0.embedding",),
        requires_model_kind="embed",
    ),
    # --- audio: STT ------------------------------------------------------
    Endpoint(
        path="/v1/audio/transcriptions",
        method="POST",
        group="audio-stt",
        kind="core",
        multipart=True,
        body={"model": "{model}", "response_format": "json"},
        expects=("text",),
        requires_model_kind="asr",
    ),
    Endpoint(
        path="/v1/audio/translations",
        method="POST",
        group="audio-stt",
        kind="ext",
        multipart=True,
        body={"model": "{model}", "response_format": "json"},
        expects=("text",),
        requires_model_kind="asr",
        notes="OpenAI Whisper-only; vLLM transcription server omits it",
    ),
    # --- audio: TTS ------------------------------------------------------
    Endpoint(
        path="/v1/audio/speech",
        method="POST",
        group="audio-tts",
        kind="core",
        body={"model": "{model}", "input": "hi", "voice": "alloy", "response_format": "wav"},
        expects="audio",
        requires_model_kind="tts",
    ),
    Endpoint(
        path="/v1/audio/voices",
        method="GET",
        group="audio-tts",
        kind="ext",
        expects=("voices",),
        notes="extension used by most OSS TTS servers; OpenAI omits",
    ),
    # --- images ----------------------------------------------------------
    Endpoint(
        path="/v1/images/generations",
        method="POST",
        group="images",
        kind="core",
        body={
            "model": "{model}",
            "prompt": "a red dot",
            "n": 1,
            "size": "256x256",
            "response_format": "b64_json",
        },
        expects=("data.0",),
        requires_model_kind="image",
    ),
    Endpoint(
        path="/v1/images/edits",
        method="POST",
        group="images",
        kind="ext",
        multipart=True,
        body={
            "model": "{model}",
            "prompt": "make it blue",
            "n": 1,
            "size": "256x256",
            "response_format": "b64_json",
        },
        expects=("data.0",),
        requires_model_kind="image-edit",
        notes="OpenAI requires multipart/form-data with image+mask",
    ),
    Endpoint(
        path="/v1/images/variations",
        method="POST",
        group="images",
        kind="ext",
        multipart=True,
        body={"model": "{model}", "n": 1, "size": "256x256", "response_format": "b64_json"},
        expects=("data.0",),
        requires_model_kind="image-edit",
        notes="rare in OSS — DALL·E-only feature historically",
    ),
    # --- moderations -----------------------------------------------------
    Endpoint(
        path="/v1/moderations",
        method="POST",
        group="moderations",
        kind="ext",
        body={"input": "hello world"},
        expects=("results.0.flagged",),
        notes="OpenAI moderation classifier; rare in OSS",
    ),
    # --- files / batches (mostly admin; existence-only) ------------------
    Endpoint(
        path="/v1/files",
        method="GET",
        group="files",
        kind="ext",
        expects=("data",),
        notes="OpenAI Files API; usually absent in OSS shims",
    ),
    Endpoint(
        path="/v1/batches",
        method="GET",
        group="batches",
        kind="ext",
        expects=("data",),
        notes="OpenAI Batch API; usually absent in OSS shims",
    ),
    Endpoint(
        path="/v1/uploads",
        method="GET",
        group="files",
        kind="ext",
        expects=(),
        notes="newer OpenAI multipart uploads; existence-only check",
    ),
    # --- our extensions --------------------------------------------------
    Endpoint(
        path="/v1/videos",
        method="POST",
        group="video",
        kind="ours",
        body={"model": "{model}", "prompt": "a slow zoom on a red dot", "seconds": 1},
        expects=("id", "status"),
        requires_model_kind="video",
        notes="our /v1/videos extension (Sora-style)",
    ),
]


def by_group() -> dict[str, list[Endpoint]]:
    out: dict[str, list[Endpoint]] = {}
    for e in ENDPOINTS:
        out.setdefault(e.group, []).append(e)
    return out
