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
    # No 'all' alias by design — drops a misleading abstraction (cf.
    # PR #1 review). If a third profile ever lands, we'll add a real
    # "everything" semantics then, not retroactively re-purpose 'all'.
    assert "all" not in PROFILE_KINDS


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


def test_unknown_profile_all_raises_after_alias_drop():
    # Regression guard — `all` was an alias for `ht` until the v0.2
    # PR review pointed out it was misleading. Verify it's gone.
    with pytest.raises(ValueError):
        Prober(BASE, "test", profile="all")


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
def test_segmentations_multipart_payload_carries_prompts_as_form_field():
    """PR #1 review item: the segmentations row sets multipart=True and
    embeds the prompts JSON as a string value in body. Verify the wire
    request actually contains a `prompts` form field with the JSON
    payload, plus the image file part — i.e. httpx serialized our
    body dict as form fields, not JSON-body-with-files.
    """
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "sam3"}]})
    )
    captured: dict = {}

    def _capture(request):
        captured["content_type"] = request.headers.get("content-type", "")
        captured["body"] = request.content
        return httpx.Response(200, json={"masks": [{"mask": "AAA"}]})

    respx.post(f"{BASE}/v1/segmentations").mock(side_effect=_capture)

    p = Prober(BASE, "test", profile="ht", endpoints_filter=r"^/v1/segmentations$")
    p.run()

    assert captured["content_type"].startswith("multipart/form-data"), captured["content_type"]
    body = captured["body"]
    # The image file part — _multipart_payload attached probe.png.
    assert b'name="image"' in body
    assert b"probe.png" in body
    # The prompts form field — value is the JSON string from the catalog body.
    assert b'name="prompts"' in body
    assert b'"type":"point"' in body
    # The model form field — same mechanism, value from {model} substitution.
    assert b'name="model"' in body
    assert b"sam3" in body


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
def test_omni_detected_from_server_architecture_modalities():
    """Regression for issue #15: a model id without an 'omni' substring
    must still be picked for the omni endpoint when the server's
    /v1/models[i].architecture.input_modalities or .output_modalities
    list contains 'audio'. Lithium's gemma-4-e4b is the live example —
    no 'omni' in the id but architecture.input_modalities is
    ['text', 'image', 'audio'].
    """
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "gemma-4-e4b",
                        "architecture": {
                            "input_modalities": ["text", "image", "audio"],
                            "output_modalities": ["text"],
                        },
                    },
                ]
            },
        )
    )
    audio_b64 = base64.b64encode(b"\x00" * 100).decode()
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "model": "gemma-4-e4b",
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
            },
        )
    )

    p = Prober(BASE, "test", profile="ht", endpoints_filter=r"chat/completions\[omni\]")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/chat/completions[omni]")
    # The signal we care about: Phase B did NOT SKIP with "no model of kind
    # 'omni'", i.e. the model was picked despite having no 'omni' substring.
    phase_b = next((e for e in rows if e.phase == "B"), None)
    assert phase_b is not None, [(e.phase, e.status, e.detail) for e in rows]
    assert phase_b.status != "SKIP" or "no model of kind 'omni'" not in phase_b.detail, (
        phase_b.status,
        phase_b.detail,
    )


@respx.mock
def test_phase_b_videos_passes_with_job_envelope():
    """Async video job submission shape: server returns {id, status} on
    POST; clients poll GET /v1/videos/{id} and fetch bytes via
    /v1/videos/{id}/content when status flips to completed. Phase B only
    validates the submission envelope — we deliberately submit a tiny
    1-second 1px image so the job either succeeds fast or fails fast,
    but never blocks the probe budget on real generation."""
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "wan22-i2v"}]})
    )
    respx.post(f"{BASE}/v1/videos").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "video-abc123",
                "model": "wan22-i2v",
                "status": "queued",
                "created": 1730000000,
                "started": None,
                "finished": None,
                "error": None,
            },
        )
    )

    p = Prober(BASE, "test", profile="ht", endpoints_filter=r"^/v1/videos$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/videos")
    assert any(e.phase == "B" and e.status == "PASS" for e in rows), [
        (e.phase, e.status, e.detail) for e in rows
    ]


@respx.mock
def test_phase_b_3d_generations_passes_with_job_envelope():
    """Async job submission shape (mirrors /v1/videos): server returns
    {id, status} on POST; clients poll GET /v1/3d/generations/{id}
    for completion. Phase B only validates the submission shape."""
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "trellis-image-large"}]})
    )
    respx.post(f"{BASE}/v1/3d/generations").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "model3d-abc123",
                "object": "3d.generation",
                "created": 1,
                "model": "trellis-image-large",
                "status": "queued",
                "estimated_completion_seconds": 180,
            },
        )
    )

    p = Prober(BASE, "test", profile="ht", endpoints_filter=r"^/v1/3d/generations$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/3d/generations")
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


# ---------------------------------------------------------------------------
# HT-compat v1.1: BERT-style encoder tasks
# ---------------------------------------------------------------------------


@respx.mock
def test_phase_b_qa_passes_with_valid_shape():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "deepset/roberta-base-squad2"}]})
    )
    respx.post(f"{BASE}/v1/qa").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "qa-1",
                "model": "deepset/roberta-base-squad2",
                "answers": [{"answer": "Mount Everest", "score": 0.98, "start": 0, "end": 13}],
                "usage": {"total_tokens": 24},
            },
        )
    )

    p = Prober(BASE, "test", profile="ht", endpoints_filter=r"^/v1/qa$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/qa")
    assert any(e.phase == "B" and e.status == "PASS" for e in rows), [
        (e.phase, e.status, e.detail) for e in rows
    ]


@respx.mock
def test_phase_b_ner_passes_with_valid_shape():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "dslim/bert-base-NER"}]})
    )
    respx.post(f"{BASE}/v1/ner").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "ner-1",
                "model": "dslim/bert-base-NER",
                "entities": [
                    {
                        "entity_group": "ORG",
                        "score": 0.99,
                        "word": "Hugging Face Inc.",
                        "start": 0,
                        "end": 17,
                    },
                    {
                        "entity_group": "LOC",
                        "score": 0.99,
                        "word": "New York",
                        "start": 30,
                        "end": 38,
                    },
                ],
                "usage": {"total_tokens": 12},
            },
        )
    )

    p = Prober(BASE, "test", profile="ht", endpoints_filter=r"^/v1/ner$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/ner")
    assert any(e.phase == "B" and e.status == "PASS" for e in rows), [
        (e.phase, e.status, e.detail) for e in rows
    ]


@respx.mock
def test_phase_b_classifications_passes_with_valid_shape():
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "SamLowe/roberta-base-go_emotions"}]}
        )
    )
    respx.post(f"{BASE}/v1/classifications").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "classify-1",
                "model": "SamLowe/roberta-base-go_emotions",
                "classifications": [
                    {"label": "love", "score": 0.94},
                    {"label": "joy", "score": 0.05},
                ],
                "usage": {"total_tokens": 18},
            },
        )
    )

    p = Prober(BASE, "test", profile="ht", endpoints_filter=r"^/v1/classifications$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/classifications")
    assert any(e.phase == "B" and e.status == "PASS" for e in rows), [
        (e.phase, e.status, e.detail) for e in rows
    ]


def test_classify_kind_tags_bert_style_model_ids():
    """v1.1 kind-classifier hints — common public checkpoints follow HF
    naming and should sniff cleanly so Phase B sends the right body to
    the right endpoint."""
    from am_i_openai_compatible.probe import _classify_kind

    assert "qa" in _classify_kind("deepset/roberta-base-squad2")
    assert "qa" in _classify_kind("distilbert-base-cased-distilled-squad")
    assert "ner" in _classify_kind("dslim/bert-base-NER")
    assert "ner" in _classify_kind("xlm-roberta-large-finetuned-conll03-english")
    assert "classify" in _classify_kind("facebook/bart-large-mnli")
    assert "classify" in _classify_kind("MoritzLaurer/ModernBERT-large-zeroshot-v2.0")
    assert "classify" in _classify_kind("SamLowe/roberta-base-go_emotions")
    # No false positives on plain chat / embed model ids.
    assert "qa" not in _classify_kind("gpt-4")
    assert "ner" not in _classify_kind("text-embedding-3-small")
    assert "classify" not in _classify_kind("borealis-4b")
