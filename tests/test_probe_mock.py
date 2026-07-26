"""Probe-against-mock tests using respx.

Drives the Prober end-to-end against synthetic HTTP fixtures so we
can assert the probe → event pipeline behaves correctly without a
real server. Covers the core decision points: core vs optional kind
on 404, 501 surfacing the server's own error message, Phase B shape
validation, SSE streaming with and without [DONE], and the
--endpoints-filter regex.
"""

from __future__ import annotations

import json
import re

import httpx
import pytest
import respx

from am_i_openai_compatible.probe import (
    Prober,
    _classify_kind,
    _get_dotted,
    _server_error_message,
)

BASE = "http://aioc.test"


def _events_by_endpoint(events, path):
    return [e for e in events if e.endpoint == path]


# ---------------------------------------------------------------------------
# Helpers — unit-level
# ---------------------------------------------------------------------------


def test_get_dotted_dict_and_list():
    body = {"choices": [{"message": {"content": "hi"}}]}
    ok, val = _get_dotted(body, "choices.0.message.content")
    assert ok and val == "hi"


def test_get_dotted_missing_returns_false():
    ok, _ = _get_dotted({"a": 1}, "a.nonexistent")
    assert not ok


def test_get_dotted_list_index_out_of_range():
    """`choices.0.x` against `choices=[]` — IndexError path."""
    ok, _ = _get_dotted({"choices": []}, "choices.0.message")
    assert not ok


def test_get_dotted_list_non_integer_part():
    """`choices.foo` against a list — ValueError on int(part)."""
    ok, _ = _get_dotted({"choices": [{"a": 1}]}, "choices.foo")
    assert not ok


def test_get_dotted_scalar_at_intermediate_path():
    """The walk hits a scalar before reaching the leaf — `else: return False`."""
    ok, _ = _get_dotted({"a": 1}, "a.b")
    assert not ok


def test_server_error_message_openai_envelope():
    r = httpx.Response(501, json={"error": {"message": "Start it with --embeddings", "code": 501}})
    assert _server_error_message(r) == "Start it with --embeddings"


def test_server_error_message_fastapi_detail():
    r = httpx.Response(400, json={"detail": "validation failed"})
    assert _server_error_message(r) == "validation failed"


def test_server_error_message_plain_text():
    r = httpx.Response(500, text="boom")
    assert _server_error_message(r) == "boom"


def test_server_error_message_error_as_string():
    """Some non-canonical envelopes put a string directly at `error` —
    rare but seen in the wild. Helper should surface it verbatim."""
    r = httpx.Response(500, json={"error": "something went wrong"})
    assert _server_error_message(r) == "something went wrong"


def test_server_error_message_json_dict_without_error_or_detail():
    """Body parses as JSON but has neither error nor detail — falls
    back to the raw-text snippet."""
    r = httpx.Response(500, json={"status": "fail", "code": 500})
    out = _server_error_message(r)
    # Should be a truncation of the JSON text or an HTTP-N fallback.
    assert out != ""
    # Sanity: it should NOT be one of the structured-extraction values
    # (since neither error nor detail was present)
    assert out != "fail"


def test_server_error_message_empty_body_uses_http_code():
    """No body at all — defaults to HTTP <code>."""
    r = httpx.Response(503)
    assert _server_error_message(r) == "HTTP 503"


@respx.mock
def test_bearer_token_is_sent_on_rest_discovery_and_endpoint_requests():
    models = respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    chat = respx.post(f"{BASE}/v1/chat/completions").mock(return_value=httpx.Response(422))

    Prober(
        BASE,
        "test",
        phase_b=False,
        api_key="sk-test-rest",
        endpoints_filter=r"^/v1/chat/completions$",
    ).run()

    assert models.calls.last.request.headers["Authorization"] == "Bearer sk-test-rest"
    assert chat.calls.last.request.headers["Authorization"] == "Bearer sk-test-rest"


def test_api_key_environment_fallback_and_precedence(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("AIOC_API_KEY", "sk-aioc")

    from_openai_env = Prober(BASE, "test")
    try:
        assert from_openai_env.api_key == "sk-openai"
    finally:
        from_openai_env.client.close()

    explicit = Prober(BASE, "test", api_key="sk-explicit")
    try:
        assert explicit.api_key == "sk-explicit"
    finally:
        explicit.client.close()

    monkeypatch.delenv("OPENAI_API_KEY")
    from_aioc_env = Prober(BASE, "test")
    try:
        assert from_aioc_env.api_key == "sk-aioc"
    finally:
        from_aioc_env.client.close()


def test_classify_kind_uses_lexical_hints():
    assert "embed" in _classify_kind("text-embedding-ada-002")
    assert "asr" in _classify_kind("whisper-large-v3")
    assert "tts" in _classify_kind("kokoro-v1")
    assert "image" in _classify_kind("flux-schnell")
    assert "video" in _classify_kind("wan-2.1")
    # No hint → falls back to chat so we still try at least one inference call.
    assert "chat" in _classify_kind("some-unknown-model")


def test_classify_kind_sam_requires_word_boundary():
    """`"sam" in s` would false-positive on "samantha-*" and similar.
    Real SAM family ids (sam3, sam2-base, facebook-sam-vit-h) must
    still match, but bare-substring matches on unrelated names must
    not.
    """
    assert "segment" in _classify_kind("sam3")
    assert "segment" in _classify_kind("sam2-base")
    assert "segment" in _classify_kind("facebook-sam-vit-h")
    # False-positive guard: "samantha" is a Vicuna-family LLM, not a SAM model.
    assert "segment" not in _classify_kind("samantha-1.2-mistral-7b")
    # Audio-SAM still correctly tagged audio-segment, NOT segment.
    assert "audio-segment" in _classify_kind("sam-audio-v1")
    assert "segment" not in _classify_kind("sam-audio-v1")


def test_classify_kind_tts_requires_word_boundary():
    """PR #32 fixed sam/ner; this pass 2 catches the TTS-token false
    positives. `"tts" in s` matched \"chattsbot\"; `"voice"` matched
    \"voicebot-chat\"; `"vibe"` matched \"vibes-coder\". `_word()`
    requires a separator (or start/end) around the token.
    """
    # True positives — real TTS model ids stay matched
    assert "tts" in _classify_kind("kokoro-v1")
    assert "tts" in _classify_kind("tts-1-hd")
    assert "tts" in _classify_kind("parler-tts")
    assert "tts" in _classify_kind("xtts-v2")
    assert "tts" in _classify_kind("bark")
    assert "tts" in _classify_kind("voice-1")
    # False positives — common LLM ids that contain the tokens as substrings
    assert "tts" not in _classify_kind("chattsbot-7b")
    assert "tts" not in _classify_kind("voicebot-chat-v1")
    assert "tts" not in _classify_kind("vibes-coder-7b")
    # `"speech"` is intentionally dropped from TTS hints — it
    # ambiguously matches speech-recognition / speech-emotion encoders
    # which are NOT TTS.
    assert "tts" not in _classify_kind("speech-emotion-classifier")
    assert "tts" not in _classify_kind("wav2vec2-speech")


def test_classify_kind_video_requires_word_boundary():
    """`"wan"` is a 3-letter substring that matched `swan-music-gen`.
    `"sora"` matched `arabsora-7b`. Tighten via `_word()`."""
    # True positives
    assert "video" in _classify_kind("wan-2.1")
    assert "video" in _classify_kind("ltx-video")
    assert "video" in _classify_kind("sora-2")
    assert "video" in _classify_kind("cogvideo-x")
    # False positives
    assert "video" not in _classify_kind("swan-music-gen")
    assert "video" not in _classify_kind("arabsora-7b")


def test_classify_kind_sam_word_boundary_pass_2():
    """PR #32's first fix used `sam[0-9-]` which matched mid-word
    (`llamabsam-7b` has `sam-` as a substring with `-` boundary on
    one side only). Pass 2 requires a separator on BOTH sides via
    `_word()`.
    """
    # True positives
    assert "segment" in _classify_kind("sam3")
    assert "segment" in _classify_kind("sam2-base")
    assert "segment" in _classify_kind("facebook-sam-vit-h")
    # False positives — `sam` as a sub-token, not a real SAM family id
    assert "segment" not in _classify_kind("llamabsam-7b")
    assert "segment" not in _classify_kind("samantha-7b")


def test_classify_kind_ner_requires_word_boundary():
    """`"ner" in s` would false-positive on "owner", "tuner",
    "generator". Real NER ids (bert-base-NER, dslim/bert-base-ner,
    conll-*) must still match.
    """
    assert "ner" in _classify_kind("bert-base-NER")
    assert "ner" in _classify_kind("dslim/bert-base-ner")
    assert "ner" in _classify_kind("conll-2003")
    # False-positive guards: common "ner"-substring tokens.
    assert "ner" not in _classify_kind("owner-model-v1")
    assert "ner" not in _classify_kind("tuner-7b")
    assert "ner" not in _classify_kind("turner-chat")


# ---------------------------------------------------------------------------
# Prober — Phase A behavior
# ---------------------------------------------------------------------------


@respx.mock
def test_phase_a_404_on_core_is_fail():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    # Make every other endpoint 404.
    respx.route().mock(return_value=httpx.Response(404, json={"error": {"message": "nope"}}))

    p = Prober(BASE, "test", phase_b=False, endpoints_filter=r"chat/completions$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/chat/completions")
    assert any(e.status == "FAIL" and "404" in e.detail for e in rows)


@respx.mock
def test_phase_a_404_on_optional_is_warn():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    respx.route().mock(return_value=httpx.Response(404, json={"error": {"message": "nope"}}))

    p = Prober(BASE, "test", phase_b=False, endpoints_filter=r"audio/transcriptions")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/audio/transcriptions")
    assert any(e.status == "WARN" and "capability not offered" in e.detail for e in rows)


@respx.mock
def test_phase_a_404_on_ext_is_skip():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    respx.post(f"{BASE}/v1/completions").mock(return_value=httpx.Response(404))

    events = Prober(BASE, "test", endpoints_filter=r"^/v1/completions$").run()
    rows = _events_by_endpoint(events, "/v1/completions")
    assert len(rows) == 1
    assert rows[0].phase == "A"
    assert rows[0].status == "SKIP"
    assert "extension not offered" in rows[0].detail


@respx.mock
def test_phase_a_501_surfaces_server_message_verbatim():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    respx.post(f"{BASE}/v1/embeddings").mock(
        return_value=httpx.Response(
            501,
            json={
                "error": {
                    "message": "This server does not support embeddings. Start it with --embeddings",
                    "code": 501,
                    "type": "not_supported_error",
                }
            },
        )
    )

    p = Prober(BASE, "test", phase_b=False, endpoints_filter=r"^/v1/embeddings$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/embeddings")
    assert any(e.status == "WARN" and "Start it with --embeddings" in e.detail for e in rows), [
        e.detail for e in rows
    ]


# ---------------------------------------------------------------------------
# Prober — Phase B behavior
# ---------------------------------------------------------------------------


@respx.mock
def test_phase_b_chat_passes_with_valid_shape():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 1,
                "model": "chat-1",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "hi"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )
    )

    p = Prober(BASE, "test", endpoints_filter=r"^/v1/chat/completions$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/chat/completions")
    assert any(e.phase == "B" and e.status == "PASS" for e in rows), [
        (e.phase, e.status, e.detail) for e in rows
    ]


@respx.mock
def test_phase_b_501_with_envelope_grades_warn():
    """Phase B must mirror Phase A on canonical 501 — endpoint is wired
    but config-disabled (e.g. llama-server booted without `--reranking`).
    FAIL would misleadingly flag a deliberate, documented capability
    gate as a server bug. Aligns with the v1.0 spec's 501-with-envelope
    rule.
    """
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"id": "rerank-1", "owned_by": "test", "tags": ["rerank"]}]},
        )
    )

    def _reranking_responder(request):
        body = json.loads(request.content or b"{}")
        if not body:
            # Phase A — empty POST. Validation reply means "route exists".
            return httpx.Response(400, json={"error": {"message": "no model"}})
        return httpx.Response(
            501,
            json={
                "error": {
                    "message": "This server does not support reranking. Start it with --reranking",
                    "code": 501,
                    "type": "not_supported_error",
                }
            },
        )

    respx.post(f"{BASE}/v1/reranking").mock(side_effect=_reranking_responder)

    p = Prober(BASE, "test", profile="ht", endpoints_filter=r"^/v1/reranking$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/reranking")
    phase_b = next((e for e in rows if e.phase == "B"), None)
    assert phase_b is not None, [(e.phase, e.status, e.detail) for e in rows]
    assert phase_b.status == "WARN", (phase_b.status, phase_b.detail)
    assert "Start it with --reranking" in phase_b.detail


@respx.mock
def test_phase_b_chat_fails_when_required_keys_missing():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            # No choices → spec violation.
            json={"id": "x", "object": "chat.completion", "created": 1, "model": "chat-1"},
        )
    )

    p = Prober(BASE, "test", endpoints_filter=r"^/v1/chat/completions$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/chat/completions")
    failure = next((e for e in rows if e.phase == "B"), None)
    assert failure is not None
    assert failure.status == "FAIL"
    assert "missing keys" in failure.detail


@respx.mock
def test_phase_b_chat_uses_pydantic_after_key_contract_checks():
    """A payload containing the dotted keys can still violate the model."""
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "hi"},
                        "finish_reason": 123,
                    }
                ]
            },
        )
    )

    events = Prober(BASE, "test", endpoints_filter=r"^/v1/chat/completions$").run()
    phase_b = next(e for e in events if e.phase == "B")
    assert phase_b.status == "FAIL"
    assert "schema mismatch (ChatCompletionResponse)" in phase_b.detail


@respx.mock
def test_phase_b_chat_fails_on_empty_content():
    """Catches the 200-OK-but-empty-content bug class — a real failure
    mode where the server returns a well-shaped response with
    `finish_reason="stop"` but zero content tokens (seen with
    speculative-decoding KV-reuse regressions producing all-NaN logits,
    and quantization corner cases that collapse the output
    distribution). A shape check that only verifies key existence
    would PASS this, since `choices[0].message.content` exists — it's
    just the empty string. With content_path + min_content_length=1
    on the chat row, the response now grades FAIL.
    """
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 1,
                "model": "chat-1",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": ""},
                        "finish_reason": "stop",
                    }
                ],
            },
        )
    )

    p = Prober(BASE, "test", endpoints_filter=r"^/v1/chat/completions$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/chat/completions")
    phase_b = next((e for e in rows if e.phase == "B"), None)
    assert phase_b is not None, [(e.phase, e.status, e.detail) for e in rows]
    assert phase_b.status == "FAIL", (phase_b.status, phase_b.detail)
    assert "empty content" in phase_b.detail


@respx.mock
@pytest.mark.parametrize(
    "label,message_obj,expected_substr",
    [
        # `content: null` — a real shape we've seen on misconfigured servers
        # (json-null instead of empty string). Pre-fix collapsed to "missing
        # content"; differentiated diagnostic surfaces the actual fault.
        ("null_content", {"role": "assistant", "content": None}, "null content"),
        # `content` key absent altogether. Reads as "missing key" (vs the
        # empty-string case which reads as "empty content").
        ("absent_content_key", {"role": "assistant"}, "missing key"),
        # `content` resolved to a non-string. Some servers default to 0 or
        # [] when they have nothing to say. Diagnostic includes the type.
        ("non_string_content", {"role": "assistant", "content": 0}, "non-string content"),
    ],
)
def test_phase_b_chat_differentiates_content_failure_modes(label, message_obj, expected_substr):
    """One detail string per failure shape — collapsing them all into
    'missing content' misled debugging on real server-bug reports."""
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "model": "chat-1",
                "choices": [{"index": 0, "message": message_obj, "finish_reason": "stop"}],
            },
        )
    )
    p = Prober(BASE, "test", endpoints_filter=r"^/v1/chat/completions$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/chat/completions")
    phase_b = next((e for e in rows if e.phase == "B"), None)
    assert phase_b is not None, [(e.phase, e.status, e.detail) for e in rows]
    assert phase_b.status == "FAIL", (label, phase_b.status, phase_b.detail)
    assert expected_substr in phase_b.detail, (label, phase_b.detail)


@respx.mock
def test_phase_b_sse_stream_fails_on_empty_delta_content():
    """Streaming variant of the empty-content bug: chunks ARE emitted
    (the SSE framing works) and [DONE] is sent, but every chunk's
    `choices[0].delta.content` is empty. Today: PASS. After
    min_content_length=1 on the stream row: FAIL.
    """
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    empty_chunk = json.dumps(
        {
            "id": "x",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "chat-1",
            "choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": "stop"}],
        }
    )
    body = f"data: {empty_chunk}\n\ndata: {empty_chunk}\n\ndata: [DONE]\n\n"
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)
    )

    p = Prober(BASE, "test", endpoints_filter=r"chat/completions\[stream\]")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/chat/completions[stream]")
    phase_b = next((e for e in rows if e.phase == "B"), None)
    assert phase_b is not None, [(e.phase, e.status, e.detail) for e in rows]
    assert phase_b.status == "FAIL", (phase_b.status, phase_b.detail)
    assert "empty content" in phase_b.detail


@respx.mock
def test_phase_b_completions_passes_with_text_content():
    """Legacy `/v1/completions` has its own empty-content gate via
    `content_path: 'choices.0.text'`. Happy-path test asserts Phase B
    PASSes when the server returns a non-empty `choices[0].text` — the
    gate doesn't accidentally trip on valid completions.
    """
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    respx.post(f"{BASE}/v1/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "cmpl-x",
                "object": "text_completion",
                "created": 1,
                "model": "chat-1",
                "choices": [
                    {
                        "index": 0,
                        "text": " world",
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )
    )

    p = Prober(BASE, "test", endpoints_filter=r"^/v1/completions$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/completions")
    phase_b = next((e for e in rows if e.phase == "B"), None)
    assert phase_b is not None, [(e.phase, e.status, e.detail) for e in rows]
    assert phase_b.status == "PASS", (phase_b.status, phase_b.detail)


@respx.mock
def test_phase_b_completions_fails_on_empty_text():
    """Same empty-content failure mode the chat-completions gate catches,
    but on the legacy `/v1/completions` row. content_path resolves to
    `choices[0].text` instead of `choices[0].message.content`.
    """
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    respx.post(f"{BASE}/v1/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "cmpl-x",
                "object": "text_completion",
                "model": "chat-1",
                "choices": [{"index": 0, "text": "", "finish_reason": "stop"}],
            },
        )
    )

    p = Prober(BASE, "test", endpoints_filter=r"^/v1/completions$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/completions")
    phase_b = next((e for e in rows if e.phase == "B"), None)
    assert phase_b is not None, [(e.phase, e.status, e.detail) for e in rows]
    assert phase_b.status == "FAIL", (phase_b.status, phase_b.detail)
    assert "empty content" in phase_b.detail


@respx.mock
def test_phase_b_responses_compact_passes_with_output_array():
    """OpenAI's /v1/responses/compact (used by Codex CLI compact_remote.rs)
    returns {output: [...]} with one item of type='compaction'. Phase B
    only validates the output array is non-empty — encrypted_content is
    opaque by design."""
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    respx.post(f"{BASE}/v1/responses/compact").mock(
        return_value=httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "compaction",
                        "encrypted_content": "AAAAA-opaque-AES-blob",
                    }
                ]
            },
        )
    )

    p = Prober(BASE, "test", endpoints_filter=r"^/v1/responses/compact$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/responses/compact")
    assert any(e.phase == "B" and e.status == "PASS" for e in rows), [
        (e.phase, e.status, e.detail) for e in rows
    ]


@respx.mock
def test_files_phase_b_intentionally_skipped():
    """`/v1/files` is admin/list — Phase B is intentionally skipped
    (see admin-routes branch in `probe.py`). Existence is the
    meaningful test for these routes; templating a Phase B body would
    require a real file upload (`/v1/uploads` flow). Regression guard:
    only Phase A events should emit for this row.
    """
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    respx.get(f"{BASE}/v1/files").mock(
        return_value=httpx.Response(200, json={"object": "list", "data": []})
    )

    p = Prober(BASE, "test", endpoints_filter=r"^/v1/files$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/files")
    assert any(e.phase == "A" and e.status == "PASS" for e in rows), [
        (e.phase, e.status, e.detail) for e in rows
    ]
    assert not any(e.phase == "B" for e in rows), (
        "Phase B should be skipped for /v1/files (admin/list route)"
    )


@respx.mock
def test_fine_tuning_jobs_phase_b_intentionally_skipped():
    """`/v1/fine_tuning/jobs` mirrors `/v1/files` and `/v1/batches` —
    admin/list route where Phase B is intentionally skipped (existence
    is the meaningful test). Added in the spec/catalog consistency
    audit (was in canonical-surface.md and the compat matrix but
    missing from endpoints.py).
    """
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    respx.get(f"{BASE}/v1/fine_tuning/jobs").mock(
        return_value=httpx.Response(200, json={"object": "list", "data": []})
    )

    p = Prober(BASE, "test", endpoints_filter=r"^/v1/fine_tuning/jobs$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/fine_tuning/jobs")
    assert any(e.phase == "A" and e.status == "PASS" for e in rows), [
        (e.phase, e.status, e.detail) for e in rows
    ]
    assert not any(e.phase == "B" for e in rows), (
        "Phase B should be skipped for /v1/fine_tuning/jobs (admin/list route)"
    )


@respx.mock
def test_batches_phase_b_intentionally_skipped():
    """`/v1/batches` mirrors `/v1/files` — admin/list, Phase B skipped.
    Regression guard for the same admin-routes branch in `probe.py`.
    """
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    respx.get(f"{BASE}/v1/batches").mock(
        return_value=httpx.Response(200, json={"object": "list", "data": []})
    )

    p = Prober(BASE, "test", endpoints_filter=r"^/v1/batches$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/batches")
    assert any(e.phase == "A" and e.status == "PASS" for e in rows), [
        (e.phase, e.status, e.detail) for e in rows
    ]
    assert not any(e.phase == "B" for e in rows), (
        "Phase B should be skipped for /v1/batches (admin/list route)"
    )


@respx.mock
def test_phase_b_audio_speech_fails_on_empty_body():
    """200 OK with audio/* Content-Type but zero bytes — binary
    version of the empty-content bug class. A real failure mode on
    misconfigured TTS shims (the synthesis stage crashes silently
    after the HTTP envelope is sent)."""
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "tts-kokoro-v1"}]})
    )
    respx.post(f"{BASE}/v1/audio/speech").mock(
        return_value=httpx.Response(200, headers={"content-type": "audio/wav"}, content=b"")
    )

    p = Prober(BASE, "test", endpoints_filter=r"^/v1/audio/speech$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/audio/speech")
    phase_b = next((e for e in rows if e.phase == "B"), None)
    assert phase_b is not None, [(e.phase, e.status, e.detail) for e in rows]
    assert phase_b.status == "FAIL", (phase_b.status, phase_b.detail)
    assert "empty audio" in phase_b.detail


@respx.mock
def test_phase_b_audio_voices_passes_with_voices_array():
    """GET /v1/audio/voices is the OSS convention for voice
    enumeration (OpenAI uses a fixed enum and omits this endpoint).
    Phase B asserts the `voices` key exists; the shape is permissive
    (object list or bare-string list both accepted)."""
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "kokoro-v1"}]})
    )
    respx.get(f"{BASE}/v1/audio/voices").mock(
        return_value=httpx.Response(
            200,
            json={
                "voices": [
                    {"id": "alloy", "name": "Alloy", "language": "en"},
                    {"id": "stevejobs-clone-1", "name": "Steve Jobs (clone)"},
                ]
            },
        )
    )

    p = Prober(BASE, "test", endpoints_filter=r"^/v1/audio/voices$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/audio/voices")
    assert any(e.phase == "B" and e.status == "PASS" for e in rows), [
        (e.phase, e.status, e.detail) for e in rows
    ]


@respx.mock
def test_phase_b_audio_voices_accepts_bare_string_list():
    """Minimal servers may return `{voices: ["alloy", "echo"]}` rather
    than the object-list form. Phase B's key-existence check should
    PASS either way — the catalog deliberately doesn't pin the
    inner item shape."""
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "kokoro-v1"}]})
    )
    respx.get(f"{BASE}/v1/audio/voices").mock(
        return_value=httpx.Response(200, json={"voices": ["alloy", "stevejobs-clone-1"]})
    )

    p = Prober(BASE, "test", endpoints_filter=r"^/v1/audio/voices$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/audio/voices")
    assert any(e.phase == "B" and e.status == "PASS" for e in rows), [
        (e.phase, e.status, e.detail) for e in rows
    ]


@respx.mock
def test_phase_b_audio_speech_passes_with_audio_bytes():
    """TTS — expects=audio sentinel. The probe checks the response is
    binary audio (any non-empty bytes content with audio/* content-type).
    """
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "tts-kokoro-v1"}]})
    )
    # Minimal WAV header + a few sample bytes
    wav_bytes = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 16 + b"data" + b"\x00" * 4
    respx.post(f"{BASE}/v1/audio/speech").mock(
        return_value=httpx.Response(200, headers={"content-type": "audio/wav"}, content=wav_bytes)
    )

    p = Prober(BASE, "test", endpoints_filter=r"^/v1/audio/speech$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/audio/speech")
    assert any(e.phase == "B" and e.status == "PASS" for e in rows), [
        (e.phase, e.status, e.detail) for e in rows
    ]


@respx.mock
def test_phase_b_audio_transcriptions_passes_with_text_response():
    """ASR — multipart upload (audio file), response is JSON `{text}`."""
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "whisper-large-v3"}]})
    )
    respx.post(f"{BASE}/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "hello world"})
    )

    p = Prober(BASE, "test", endpoints_filter=r"^/v1/audio/transcriptions$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/audio/transcriptions")
    assert any(e.phase == "B" and e.status == "PASS" for e in rows), [
        (e.phase, e.status, e.detail) for e in rows
    ]


@respx.mock
def test_phase_b_images_generations_passes_with_data_array():
    """Image generation — expects=data.0. Mock a 1x1 PNG b64 placeholder."""
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "flux-schnell"}]})
    )
    respx.post(f"{BASE}/v1/images/generations").mock(
        return_value=httpx.Response(
            200,
            json={
                "created": 1,
                "data": [
                    {
                        "b64_json": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
                    }
                ],
            },
        )
    )

    p = Prober(BASE, "test", endpoints_filter=r"^/v1/images/generations$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/images/generations")
    assert any(e.phase == "B" and e.status == "PASS" for e in rows), [
        (e.phase, e.status, e.detail) for e in rows
    ]


@respx.mock
def test_phase_b_images_edits_passes_with_data_array():
    """Image edits — multipart, expects=data.0."""
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "flux-kontext-edit"}]})
    )
    respx.post(f"{BASE}/v1/images/edits").mock(
        return_value=httpx.Response(
            200,
            json={
                "created": 1,
                "data": [
                    {
                        "b64_json": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
                    }
                ],
            },
        )
    )

    p = Prober(BASE, "test", endpoints_filter=r"^/v1/images/edits$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/images/edits")
    assert any(e.phase == "B" and e.status == "PASS" for e in rows), [
        (e.phase, e.status, e.detail) for e in rows
    ]


@respx.mock
def test_phase_b_sse_stream_with_done_passes():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )

    chunk = json.dumps(
        {
            "id": "x",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "chat-1",
            "choices": [{"index": 0, "delta": {"content": "hi"}}],
        }
    )
    body = f"data: {chunk}\n\ndata: [DONE]\n\n"
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)
    )

    p = Prober(BASE, "test", endpoints_filter=r"chat/completions\[stream\]")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/chat/completions[stream]")
    assert any(e.phase == "B" and e.status == "PASS" and "[DONE]=True" in e.detail for e in rows)


@respx.mock
def test_phase_b_sse_stream_without_done_warns():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    chunk = json.dumps(
        {
            "id": "x",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "chat-1",
            "choices": [{"index": 0, "delta": {"content": "hi"}}],
        }
    )
    # No [DONE] sentinel — clients hang in real life.
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, headers={"content-type": "text/event-stream"}, text=f"data: {chunk}\n\n"
        )
    )

    p = Prober(BASE, "test", endpoints_filter=r"chat/completions\[stream\]")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/chat/completions[stream]")
    assert any(e.phase == "B" and e.status == "WARN" and "[DONE]=False" in e.detail for e in rows)


# ---------------------------------------------------------------------------
# Prober — endpoints filter
# ---------------------------------------------------------------------------


@respx.mock
def test_endpoints_filter_restricts_probed_set():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    respx.route().mock(return_value=httpx.Response(404))

    p = Prober(BASE, "test", phase_b=False, endpoints_filter=r"^/v1/models$")
    events = p.run()
    paths = {e.endpoint for e in events}
    assert paths == {"/v1/models"}


@respx.mock
def test_discovery_response_is_reused_for_models_phase_a_and_b():
    """One discovery request also satisfies both /v1/models phases."""
    models = respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {
                        "id": "chat-1",
                        "object": "model",
                        "created": 1,
                        "owned_by": "test",
                    }
                ],
            },
        )
    )

    events = Prober(BASE, "test", endpoints_filter=r"^/v1/models$").run()
    assert models.call_count == 1
    assert [(e.phase, e.status) for e in events] == [("A", "PASS"), ("B", "PASS")]


@respx.mock
def test_phase_a_only_uses_one_shared_discovery_request():
    models = respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    chat = respx.post(f"{BASE}/v1/chat/completions").mock(return_value=httpx.Response(422))

    Prober(
        BASE,
        "test",
        phase_b=False,
        endpoints_filter=r"^/v1/chat/completions$",
    ).run()
    assert models.call_count == 1
    assert chat.call_count == 1
    assert len(respx.calls) == 2


@respx.mock
def test_missing_required_model_kind_skips_without_wrong_model_request():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    embeddings = respx.post(f"{BASE}/v1/embeddings").mock(
        return_value=httpx.Response(422, json={"detail": "model required"})
    )

    events = Prober(BASE, "test", endpoints_filter=r"^/v1/embeddings$").run()
    phase_b = next(e for e in events if e.phase == "B")
    assert phase_b.status == "SKIP"
    assert "no model of kind 'embed'" in phase_b.detail
    assert embeddings.call_count == 1  # Phase A only


# ---------------------------------------------------------------------------
# Prober — liveness short-circuit
# ---------------------------------------------------------------------------


@respx.mock
def test_unreachable_host_skips_everything():
    respx.get(f"{BASE}/v1/models").mock(side_effect=httpx.ConnectError("nope"))

    p = Prober(BASE, "test", endpoints_filter=r"^/v1/(models|chat)")
    events = p.run()
    assert events  # we still emit one SKIP per endpoint
    assert all(e.status == "SKIP" for e in events)
    assert all("connection refused" in e.detail for e in events)


# ---------------------------------------------------------------------------
# Sanity guards
# ---------------------------------------------------------------------------


@respx.mock
def test_phase_b_uploads_passes_when_create_returns_upload_object():
    """v0.3.1: /v1/uploads switched from GET (existence-only) to POST
    creating an upload object. Probe sends the canonical create body
    (purpose/bytes/filename/mime_type) and validates the upload object
    shape (id + object) per the OpenAI Uploads API."""
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    captured: dict = {}

    def _capture(request):
        captured["body"] = request.content
        return httpx.Response(
            200,
            json={
                "id": "upload_abc",
                "object": "upload",
                "bytes": 1024,
                "filename": "probe.jsonl",
                "purpose": "fine-tune",
                "status": "pending",
                "created_at": 1,
            },
        )

    respx.post(f"{BASE}/v1/uploads").mock(side_effect=_capture)

    p = Prober(BASE, "test", endpoints_filter=r"^/v1/uploads$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/uploads")
    assert any(e.phase == "B" and e.status == "PASS" for e in rows), [
        (e.phase, e.status, e.detail) for e in rows
    ]
    body = captured["body"]
    assert b'"purpose"' in body
    assert b'"bytes"' in body
    assert b'"filename"' in body
    assert b'"mime_type"' in body


def test_images_variations_row_is_pruned():
    """Regression guard: /v1/images/variations was pruned in v0.3.1
    after an unauth probe of api.openai.com on 2026-05-16 returned 404.
    OpenAI's docs no longer list it; canonical image-variation flow
    moved to /v1/images/edits with gpt-image-1."""
    from am_i_openai_compatible.endpoints import ENDPOINTS

    paths = {e.path for e in ENDPOINTS}
    assert "/v1/images/variations" not in paths


def test_invalid_filter_regex_raises_at_construction():
    with pytest.raises(re.error):
        Prober(BASE, "test", endpoints_filter="(unbalanced")


def test_bearer_token_normalization_and_prefix_stripping():
    p = Prober(BASE, "test", api_key="  Bearer  sk-test-token  ")
    assert p._bearer_token() == "sk-test-token"
    assert p.client.headers["Authorization"] == "Bearer sk-test-token"
    assert p._ws_headers()["Authorization"] == "Bearer sk-test-token"
    p.client.close()


def test_explicit_empty_api_key_overrides_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key")
    p = Prober(BASE, "test", api_key="")
    assert p.api_key == ""
    assert p._bearer_token() is None
    assert "Authorization" not in p.client.headers
    p.client.close()


@respx.mock
def test_liveness_timeout_skips_all_endpoints():
    respx.get(f"{BASE}/v1/models").mock(side_effect=httpx.ReadTimeout("timeout"))

    p = Prober(BASE, "test", endpoints_filter=r"^/v1/(models|chat)")
    events = p.run()
    assert events
    assert all(e.status == "SKIP" for e in events)
    assert all("connection timeout" in e.detail for e in events)


@respx.mock
def test_model_override_fallback_when_kind_unrecognized():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    embeddings = respx.post(f"{BASE}/v1/embeddings").mock(
        return_value=httpx.Response(
            200,
            json={
                "object": "list",
                "data": [{"object": "embedding", "index": 0, "embedding": [0.1]}],
                "model": "custom-vec",
            },
        )
    )

    p = Prober(
        BASE,
        "test",
        model="custom-vec-v1",
        endpoints_filter=r"^/v1/embeddings$",
    )
    events = p.run()
    phase_b = next(e for e in events if e.phase == "B")
    assert phase_b.status == "PASS"
    assert embeddings.calls.last.request.content.decode().find("custom-vec-v1") != -1


@respx.mock
def test_phase_b_sse_ignores_non_completion_control_events():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    sse_body = (
        'data: {"type": "ping"}\n\n'
        'data: {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "m1", '
        '"choices": [{"index": 0, "delta": {"content": "hi"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=sse_body
        )
    )

    p = Prober(BASE, "test", endpoints_filter=r"^/v1/chat/completions\[stream\]$")
    events = p.run()
    phase_b = next(e for e in events if e.phase == "B")
    assert phase_b.status == "PASS"


@respx.mock
def test_phase_b_sse_rejects_unknown_non_chunk_events():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content='data: {"unexpected": true}\n\ndata: [DONE]\n\n',
        )
    )

    events = Prober(
        BASE,
        "test",
        endpoints_filter=r"^/v1/chat/completions\[stream\]$",
    ).run()
    phase_b = next(e for e in events if e.phase == "B")
    assert phase_b.status == "FAIL"
    assert "schema mismatch (ChatCompletionChunk)" in phase_b.detail
