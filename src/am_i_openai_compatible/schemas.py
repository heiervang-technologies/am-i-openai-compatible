"""Pydantic models that mirror the OpenAI spec for response validation.

These are *minimal* — only the fields a compliant client relies on. They
allow extras (extension fields like comfy-openai's `kind`) so we don't
fail clients that add metadata. Spec source: platform.openai.com/docs +
the openai Python SDK type stubs (verified against vLLM and llama.cpp
reference implementations).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class ModelObject(_Open):
    id: str
    object: Literal["model"]
    created: int
    owned_by: str


class ListModelsResponse(_Open):
    object: Literal["list"]
    data: list[ModelObject]


class Usage(_Open):
    prompt_tokens: int
    completion_tokens: int | None = None
    total_tokens: int


class ChatMessage(_Open):
    role: str
    content: str | list[Any] | None = None


class ChatChoice(_Open):
    index: int
    message: ChatMessage
    finish_reason: str | None


class ChatCompletionResponse(_Open):
    id: str
    object: Literal["chat.completion"]
    created: int
    model: str
    choices: list[ChatChoice]
    usage: Usage | None = None  # llama.cpp omits in some configs


class ChatChoiceDelta(_Open):
    index: int
    delta: dict[str, Any]
    finish_reason: str | None = None


class ChatCompletionChunk(_Open):
    id: str
    object: Literal["chat.completion.chunk"]
    created: int
    model: str
    choices: list[ChatChoiceDelta]


class CompletionChoice(_Open):
    text: str
    index: int
    finish_reason: str | None
    logprobs: Any = None


class CompletionResponse(_Open):
    id: str
    object: Literal["text_completion"]
    created: int
    model: str
    choices: list[CompletionChoice]
    usage: Usage | None = None


class EmbeddingObject(_Open):
    object: Literal["embedding"]
    index: int
    embedding: list[float]


class EmbeddingsResponse(_Open):
    object: Literal["list"]
    data: list[EmbeddingObject]
    model: str
    usage: Usage | None = None


class TranscriptionJSON(_Open):
    text: str


class TranscriptionVerboseJSON(_Open):
    text: str
    language: str | None = None
    duration: float | None = None
    segments: list[dict[str, Any]] | None = None


class ImageDataItem(_Open):
    # Exactly one of url / b64_json should be present.
    url: str | None = None
    b64_json: str | None = None
    revised_prompt: str | None = None


class ImagesResponse(_Open):
    created: int
    data: list[ImageDataItem]


class VideoJob(_Open):
    """OpenAI Sora-style async video job (extension)."""

    id: str
    model: str
    status: Literal["queued", "in_progress", "completed", "failed"]
    created: int
    error: str | None = None


# OpenAI error envelope shape (used to validate failure paths if needed).
class OpenAIErrorEnvelope(_Open):
    error: dict[str, Any] = Field(...)
