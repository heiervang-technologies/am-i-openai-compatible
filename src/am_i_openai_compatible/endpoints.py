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
  kind              "core"     → required-by-spec for any chat-claiming
                                 server; missing = FAIL.
                    "optional" → capability-gated (audio/images/embeddings).
                                 Missing or 501 = WARN with the server's
                                 own error body as the hint; misshapen
                                 response when present = FAIL.
                    "ext"      → an OpenAI extension (newer / optional);
                                 missing = SKIP.
                    "ours"     → an HT-compat extension (docs/spec/ht-compat.md).
                                 Profile-dependent: skipped entirely under
                                 the default `openai` profile; under
                                 `--profile ht` these rows are probed and
                                 a 404 is graded as FAIL (the server
                                 claims HT-compat but is missing a
                                 required endpoint).
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
    protocol: str = "http"  # "http" (REST/SSE) or "ws" (WebSocket); ws rows
    # go through Prober._phase_b_ws instead of the http POST/GET paths.
    ws_init_event: dict | None = None  # event to send after WS upgrade
    ws_expect_event: str = ""  # event "type" we expect back to count as PASS


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
            "stream_options": {"include_usage": True},
        },
        expects="sse",
        requires_model_kind="chat",
        notes="separate row so a missing-stream regression is visible",
    ),
    Endpoint(
        path="/v1/chat/completions[logprobs]",
        method="POST",
        group="chat",
        kind="ext",
        body={
            "model": "{model}",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 4,
            "logprobs": True,
            "top_logprobs": 3,
        },
        expects=("choices.0.logprobs.content",),
        requires_model_kind="chat",
        notes="many servers accept the params but never populate the field",
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
    Endpoint(
        path="/v1/realtime",
        method="GET",  # WS upgrades go through GET in the HTTP layer
        group="chat",
        kind="ext",
        protocol="ws",
        ws_init_event={
            "type": "session.update",
            "session": {"turn_detection": None, "modalities": ["text"]},
        },
        ws_expect_event="session.created",
        notes="OpenAI Realtime API; WebSocket bidirectional events; almost no OSS impls",
    ),
    Endpoint(
        path="/v1/responses/compact",
        method="POST",
        group="chat",
        kind="ext",
        body={
            "model": "{model}",
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "hi"}],
                }
            ],
            "tools": [],
            "parallel_tool_calls": False,
        },
        expects=("output.0",),
        requires_model_kind="chat",
        notes="server-side context compaction (Codex CLI uses this; OpenAI-hosted only)",
    ),
    # --- embeddings ------------------------------------------------------
    Endpoint(
        path="/v1/embeddings",
        method="POST",
        group="embed",
        kind="optional",
        body={"model": "{model}", "input": "hi"},
        expects=("data.0.embedding",),
        requires_model_kind="embed",
        notes="config-gated: llama-server returns 501 unless --embeddings is set at startup",
    ),
    # --- audio: STT ------------------------------------------------------
    Endpoint(
        path="/v1/audio/transcriptions",
        method="POST",
        group="audio-stt",
        kind="optional",
        multipart=True,
        body={"model": "{model}", "response_format": "json"},
        expects=("text",),
        requires_model_kind="asr",
        notes="capability-gated: missing on chat-only servers, not non-compliance",
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
        kind="optional",
        body={"model": "{model}", "input": "hi", "voice": "alloy", "response_format": "wav"},
        expects="audio",
        requires_model_kind="tts",
        notes="capability-gated: missing on chat-only servers, not non-compliance",
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
        kind="optional",
        body={
            "model": "{model}",
            "prompt": "a red dot",
            "n": 1,
            "size": "256x256",
            "response_format": "b64_json",
        },
        expects=("data.0",),
        requires_model_kind="image",
        notes="capability-gated: missing on chat-only servers, not non-compliance",
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
    # /v1/images/variations is intentionally absent.
    #
    # OpenAI returned 404 on this path during an unauth probe of
    # api.openai.com on 2026-05-16 (.probe-reports/openai-api-com-
    # 2026-05-16-unauth.json), and the public Images API docs no longer
    # list it — the canonical image-variation flow is now
    # /v1/images/edits with the `gpt-image-1` model. The row used to
    # ship as kind="ext"; pruning it instead of inventing a "legacy"
    # bucket keeps the catalog honest about the current OpenAI surface.
    # If OpenAI brings it back, re-add. See issue #7.
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
        method="POST",
        group="files",
        kind="ext",
        # POST /v1/uploads creates an upload object; subsequent
        # PUT /v1/uploads/{id}/parts then POST /v1/uploads/{id}/complete
        # finalize it. We only probe the create step — the multi-step
        # finalize requires real file bytes and would breach the
        # ≤2 reqs/endpoint budget. Verified via unauth probe of
        # api.openai.com on 2026-05-16 (issue #7).
        body={
            "purpose": "fine-tune",
            "bytes": 1024,
            "filename": "probe.jsonl",
            "mime_type": "application/jsonl",
        },
        expects=("id", "object"),
        notes="newer OpenAI multipart uploads; POST root creates upload object",
    ),
    # --- HT-compat extensions (docs/spec/ht-compat.md) -------------------
    # These rows are probed only under `--profile ht`. A 404 there is a
    # FAIL: the server claims HT-compat but is missing a required
    # endpoint.
    Endpoint(
        path="/v1/videos",
        method="POST",
        group="video",
        kind="ours",
        body={
            "model": "{model}",
            "prompt": "a slow zoom on a red dot",
            "image_url": (
                "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAA"
                "AAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
            ),
            "seconds": 1,
        },
        expects=("id", "status"),
        requires_model_kind="video",
        notes="HT-compat: Sora-style video job submission (image_url tolerated; image-to-video models like LTX require it)",
    ),
    Endpoint(
        path="/v1/reranking",
        method="POST",
        group="rerank",
        kind="ours",
        body={
            "model": "{model}",
            "query": "what is OpenAI compatibility",
            "documents": ["a relevant document", "an unrelated document"],
        },
        expects=("results.0.index", "results.0.relevance_score"),
        requires_model_kind="rerank",
        notes="HT-compat: Cohere/Jina rerank convention",
    ),
    Endpoint(
        path="/v1/segmentations",
        method="POST",
        group="segment",
        kind="ours",
        multipart=True,
        # `prompts` ships as a JSON-encoded string form field, not as
        # a JSON-body key — httpx serializes every value in `body` as a
        # `multipart/form-data` field when files= is also set. The wire
        # request carries `name="prompts"` whose value is the JSON
        # string below, alongside the `name="image"` file part attached
        # by Prober._multipart_payload. Covered by
        # test_segmentations_multipart_payload_carries_prompts_as_form_field.
        body={
            "model": "{model}",
            "prompts": '[{"type":"point","x":0.5,"y":0.5,"label":1}]',
        },
        expects=("masks.0.mask",),
        requires_model_kind="segment",
        notes="HT-compat: SAM3-style promptable image segmentation",
    ),
    Endpoint(
        path="/v1/audio/segmentations",
        method="POST",
        group="audio-segment",
        kind="ours",
        multipart=True,
        body={
            "model": "{model}",
            "prompt": '{"type":"text","value":"vocals"}',
        },
        expects=("sources.0.audio",),
        requires_model_kind="audio-segment",
        notes="HT-compat: SAM-Audio-style promptable audio extraction",
    ),
    Endpoint(
        path="/v1/chat/completions[omni]",
        method="POST",
        group="chat",
        kind="ours",
        body={
            "model": "{model}",
            "modalities": ["text", "audio"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "hi"},
                    ],
                }
            ],
            "audio": {"voice": "alloy", "format": "wav"},
            "max_tokens": 4,
        },
        expects=("choices.0.message.audio.data",),
        requires_model_kind="omni",
        notes="HT-compat: vLLM-Omni-style multi-modal in/out via modalities field",
    ),
    Endpoint(
        path="/v1/images/decompositions",
        method="POST",
        group="images",
        kind="ours",
        body={
            "model": "{model}",
            "prompt": "a red dot",
            "num_layers": 2,
            "size": "256x256",
            "response_format": "b64_json",
        },
        expects=("data.layers.0.b64_json",),
        requires_model_kind="image-decompose",
        notes="HT-compat: Qwen-Image-Layered-style RGBA layer decomposition",
    ),
    Endpoint(
        path="/v1/3d/generations",
        method="POST",
        group="3d",
        kind="ours",
        body={
            "model": "{model}",
            "image_url": (
                "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAA"
                "AAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
            ),
            "prompt": "a small red cube",
            "output_format": "glb",
            "n": 1,
        },
        expects=("id", "status"),
        requires_model_kind="3d",
        notes="HT-compat: TRELLIS/Hunyuan3D-style async 3D mesh generation (ComfyUI backend; image_url required, text-to-3D is v1.1)",
    ),
]


def by_group() -> dict[str, list[Endpoint]]:
    out: dict[str, list[Endpoint]] = {}
    for e in ENDPOINTS:
        out.setdefault(e.group, []).append(e)
    return out
