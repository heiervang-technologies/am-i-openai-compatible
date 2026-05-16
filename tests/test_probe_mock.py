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


def test_server_error_message_openai_envelope():
    r = httpx.Response(501, json={"error": {"message": "Start it with --embeddings", "code": 501}})
    assert _server_error_message(r) == "Start it with --embeddings"


def test_server_error_message_fastapi_detail():
    r = httpx.Response(400, json={"detail": "validation failed"})
    assert _server_error_message(r) == "validation failed"


def test_server_error_message_plain_text():
    r = httpx.Response(500, text="boom")
    assert _server_error_message(r) == "boom"


def test_classify_kind_uses_lexical_hints():
    assert "embed" in _classify_kind("text-embedding-ada-002")
    assert "asr" in _classify_kind("whisper-large-v3")
    assert "tts" in _classify_kind("kokoro-v1")
    assert "image" in _classify_kind("flux-schnell")
    assert "video" in _classify_kind("wan-2.1")
    # No hint → falls back to chat so we still try at least one inference call.
    assert "chat" in _classify_kind("some-unknown-model")


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
