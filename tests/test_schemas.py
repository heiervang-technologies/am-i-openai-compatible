"""Smoke tests for the public-API pydantic schemas.

`am_i_openai_compatible.schemas` exports pydantic models that mirror
the OpenAI response shapes. They're consumed both by external code
and by catalog rows whose Phase B response has a registered model.

These tests lock in:
- Real OpenAI-shape responses parse without error
- Extra fields (extension fields, model-specific metadata) are
  accepted (extra="allow" in _Open base)
- Required fields are actually required (ValidationError on miss)
- Optional fields don't break when omitted
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from am_i_openai_compatible.schemas import (
    ChatCompletionChunk,
    ChatCompletionResponse,
    CompletionResponse,
    EmbeddingsResponse,
    ImagesResponse,
    ListModelsResponse,
    ModelObject,
    OpenAIErrorEnvelope,
    TranscriptionJSON,
    TranscriptionVerboseJSON,
    VideoJob,
)


def test_model_object_parses_minimal_openai_shape():
    m = ModelObject(id="gpt-4", object="model", created=1, owned_by="openai")
    assert m.id == "gpt-4"


def test_model_object_accepts_extra_fields():
    """Extension fields (e.g. comfy-openai's `kind`, lithium's
    `architecture` block) must not break parsing."""
    m = ModelObject.model_validate(
        {
            "id": "gpt-4",
            "object": "model",
            "created": 1,
            "owned_by": "openai",
            "kind": "chat",
            "architecture": {"input_modalities": ["text"]},
        }
    )
    assert m.id == "gpt-4"


def test_model_object_required_fields_missing_raises():
    with pytest.raises(ValidationError):
        ModelObject(id="gpt-4")  # type: ignore[call-arg]


def test_list_models_response_parses_openai_envelope():
    payload = {
        "object": "list",
        "data": [
            {"id": "gpt-4", "object": "model", "created": 1, "owned_by": "openai"},
            {"id": "gpt-3.5", "object": "model", "created": 1, "owned_by": "openai"},
        ],
    }
    resp = ListModelsResponse.model_validate(payload)
    assert len(resp.data) == 2


def test_chat_completion_response_parses_real_openai_shape():
    resp = ChatCompletionResponse.model_validate(
        {
            "id": "chatcmpl-abc",
            "object": "chat.completion",
            "created": 1,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "hi"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )
    assert resp.id == "chatcmpl-abc"
    assert resp.choices[0].message.content == "hi"


def test_chat_completion_response_usage_optional():
    """llama.cpp omits usage in some configs — schema must allow that."""
    resp = ChatCompletionResponse.model_validate(
        {
            "id": "chatcmpl-abc",
            "object": "chat.completion",
            "created": 1,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "hi"},
                    "finish_reason": "stop",
                }
            ],
        }
    )
    assert resp.usage is None


def test_chat_completion_chunk_parses_streaming_envelope():
    chunk = ChatCompletionChunk.model_validate(
        {
            "id": "chatcmpl-abc",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "gpt-4",
            "choices": [{"index": 0, "delta": {"content": "h"}, "finish_reason": None}],
        }
    )
    assert chunk.choices[0].delta == {"content": "h"}


def test_completion_response_parses_legacy_shape():
    resp = CompletionResponse.model_validate(
        {
            "id": "cmpl-abc",
            "object": "text_completion",
            "created": 1,
            "model": "gpt-3.5-turbo-instruct",
            "choices": [{"text": "hello", "index": 0, "finish_reason": "stop"}],
        }
    )
    assert resp.choices[0].text == "hello"


def test_embeddings_response_parses_with_vector():
    resp = EmbeddingsResponse.model_validate(
        {
            "object": "list",
            "data": [{"index": 0, "object": "embedding", "embedding": [0.1, 0.2, 0.3]}],
            "model": "text-embedding-ada-002",
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        }
    )
    assert resp.data[0].embedding == [0.1, 0.2, 0.3]


def test_transcription_json_parses_minimal_text():
    t = TranscriptionJSON(text="hello world")
    assert t.text == "hello world"


def test_transcription_verbose_json_parses_with_segments():
    t = TranscriptionVerboseJSON.model_validate(
        {
            "text": "hello world",
            "language": "en",
            "duration": 1.5,
            "segments": [{"id": 0, "text": "hello world", "start": 0.0, "end": 1.5}],
        }
    )
    assert t.duration == 1.5


def test_images_response_parses_url_form():
    resp = ImagesResponse.model_validate(
        {"created": 1, "data": [{"url": "https://example.com/img.png"}]}
    )
    assert resp.data[0].url == "https://example.com/img.png"
    assert resp.data[0].b64_json is None


def test_images_response_parses_b64_form():
    resp = ImagesResponse.model_validate({"created": 1, "data": [{"b64_json": "iVBORw0K..."}]})
    assert resp.data[0].b64_json == "iVBORw0K..."


def test_video_job_status_literal_rejects_unknown():
    """status is constrained to the four documented values."""
    VideoJob(id="x", model="sora", status="queued", created=1)
    with pytest.raises(ValidationError):
        VideoJob(id="x", model="sora", status="bogus", created=1)  # type: ignore[arg-type]


def test_openai_error_envelope_requires_error_field():
    OpenAIErrorEnvelope.model_validate({"error": {"message": "bad", "type": "invalid"}})
    with pytest.raises(ValidationError):
        OpenAIErrorEnvelope.model_validate({"detail": "bad"})  # FastAPI default ≠ canonical
