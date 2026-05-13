"""HT-compat profile tests.

Covers profile filtering and Phase B happy-path for each new HT
extension row added in v0.2.

The probe defaults to the OpenAI profile; HT rows are only probed
under `--profile ht` (or its alias `all`). A 404 on an HT row under
the ht profile must FAIL, mirroring how the prober already treats a
404 on a `core` endpoint.
"""

from __future__ import annotations

import base64

import httpx
import pytest
import respx

from am_i_openai_compatible.endpoints import ENDPOINTS
from am_i_openai_compatible.probe import PROFILE_KINDS, Prober

BASE = "http://aioc.test"


def _events_by_endpoint(events, path):
    return [e for e in events if e.endpoint == path]


def _ht_paths() -> set[str]:
    return {e.path for e in ENDPOINTS if e.kind == "ours"}


# ---------------------------------------------------------------------------
# Profile filtering
# ---------------------------------------------------------------------------


def test_profile_kinds_table_is_what_we_expect():
    assert PROFILE_KINDS["openai"] == frozenset({"core", "optional", "ext"})
    assert PROFILE_KINDS["ht"] == frozenset({"core", "optional", "ext", "ours"})
    assert PROFILE_KINDS["all"] == PROFILE_KINDS["ht"]


def test_unknown_profile_raises():
    with pytest.raises(ValueError):
        Prober(BASE, "test", profile="bogus")


@respx.mock
def test_openai_profile_skips_ours_rows():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    respx.route().mock(return_value=httpx.Response(404))

    # No endpoints_filter; profile alone should exclude every `ours` row.
    p = Prober(BASE, "test", phase_b=False, profile="openai")
    events = p.run()
    seen = {e.endpoint for e in events}
    assert seen.isdisjoint(_ht_paths()), seen & _ht_paths()


@respx.mock
def test_ht_profile_includes_ours_rows():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    respx.route().mock(return_value=httpx.Response(404))

    p = Prober(BASE, "test", phase_b=False, profile="ht")
    events = p.run()
    seen = {e.endpoint for e in events}
    assert _ht_paths().issubset(seen), _ht_paths() - seen


@respx.mock
def test_all_profile_is_alias_for_ht():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    respx.route().mock(return_value=httpx.Response(404))

    p = Prober(BASE, "test", phase_b=False, profile="all")
    events = p.run()
    seen = {e.endpoint for e in events}
    assert _ht_paths().issubset(seen)


@respx.mock
def test_404_on_ours_under_ht_profile_is_fail():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    respx.route().mock(return_value=httpx.Response(404, json={"error": {"message": "nope"}}))

    p = Prober(
        BASE,
        "test",
        phase_b=False,
        profile="ht",
        endpoints_filter=r"^/v1/reranking$",
    )
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/reranking")
    assert rows, "expected /v1/reranking to be probed under ht profile"
    assert any(e.status == "FAIL" and "404" in e.detail for e in rows)
    assert all(e.profile == "ht" for e in rows)


# ---------------------------------------------------------------------------
# Phase B happy-path for each new HT endpoint
# ---------------------------------------------------------------------------


@respx.mock
def test_phase_b_reranking_passes_with_valid_shape():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "bge-reranker-v2"}]})
    )
    respx.post(f"{BASE}/v1/reranking").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "rerank-1",
                "model": "bge-reranker-v2",
                "results": [
                    {"index": 0, "relevance_score": 0.9},
                    {"index": 1, "relevance_score": 0.1},
                ],
                "usage": {"total_tokens": 14},
            },
        )
    )

    p = Prober(BASE, "test", profile="ht", endpoints_filter=r"^/v1/reranking$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/reranking")
    assert any(e.phase == "B" and e.status == "PASS" for e in rows), [
        (e.phase, e.status, e.detail) for e in rows
    ]


@respx.mock
def test_phase_b_segmentations_passes_with_valid_shape():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "sam3"}]})
    )
    mask_b64 = base64.b64encode(b"\x00" * 16).decode()
    respx.post(f"{BASE}/v1/segmentations").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "seg-1",
                "model": "sam3",
                "masks": [
                    {
                        "mask": mask_b64,
                        "bbox": {"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.4},
                        "score": 0.93,
                        "instance_id": 0,
                    }
                ],
            },
        )
    )

    p = Prober(BASE, "test", profile="ht", endpoints_filter=r"^/v1/segmentations$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/segmentations")
    assert any(e.phase == "B" and e.status == "PASS" for e in rows), [
        (e.phase, e.status, e.detail) for e in rows
    ]


@respx.mock
def test_phase_b_audio_segmentations_passes_with_valid_shape():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "sam-audio-v1"}]})
    )
    audio_b64 = base64.b64encode(b"RIFF" + b"\x00" * 60).decode()
    respx.post(f"{BASE}/v1/audio/segmentations").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "audio-seg-1",
                "model": "sam-audio-v1",
                "sources": [
                    {
                        "audio": audio_b64,
                        "label": "vocals",
                        "score": 0.88,
                        "source_id": 0,
                    }
                ],
            },
        )
    )

    p = Prober(BASE, "test", profile="ht", endpoints_filter=r"^/v1/audio/segmentations$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/audio/segmentations")
    assert any(e.phase == "B" and e.status == "PASS" for e in rows), [
        (e.phase, e.status, e.detail) for e in rows
    ]


@respx.mock
def test_phase_b_chat_omni_passes_with_audio_in_message():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "qwen2.5-omni-7b"}]})
    )
    audio_b64 = base64.b64encode(b"\x00" * 100).decode()
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "model": "qwen2.5-omni-7b",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "ok",
                            "audio": {
                                "id": "audio-1",
                                "data": audio_b64,
                                "format": "wav",
                                "expires_at": 0,
                            },
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )
    )

    p = Prober(
        BASE,
        "test",
        profile="ht",
        endpoints_filter=r"chat/completions\[omni\]",
    )
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/chat/completions[omni]")
    assert any(e.phase == "B" and e.status == "PASS" for e in rows), [
        (e.phase, e.status, e.detail) for e in rows
    ]


@respx.mock
def test_phase_b_images_decompositions_passes_with_layered_shape():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "qwen-image-layered"}]})
    )
    png_b64 = base64.b64encode(b"\x89PNG\r\n" + b"\x00" * 60).decode()
    respx.post(f"{BASE}/v1/images/decompositions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "imgdecomp-1",
                "created": 1,
                "model": "qwen-image-layered",
                "data": {
                    "composite": {"b64_json": png_b64},
                    "layers": [
                        {
                            "index": 0,
                            "label": "background",
                            "b64_json": png_b64,
                            "bbox": {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0},
                        },
                        {
                            "index": 1,
                            "label": "subject",
                            "b64_json": png_b64,
                            "bbox": {"x1": 0.3, "y1": 0.2, "x2": 0.7, "y2": 0.85},
                        },
                    ],
                },
            },
        )
    )

    p = Prober(
        BASE,
        "test",
        profile="ht",
        endpoints_filter=r"^/v1/images/decompositions$",
    )
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/images/decompositions")
    assert any(e.phase == "B" and e.status == "PASS" for e in rows), [
        (e.phase, e.status, e.detail) for e in rows
    ]
