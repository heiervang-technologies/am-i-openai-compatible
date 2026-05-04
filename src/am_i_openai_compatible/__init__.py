"""am-i-openai-compatible — probe any HTTP server for OpenAI API compliance.

Public API:

    from am_i_openai_compatible import probe_url, ENDPOINTS

    report = probe_url("http://localhost:8080", name="my-server")
    print(report["summary"])
"""

from __future__ import annotations

from .endpoints import ENDPOINTS, Endpoint
from .schemas import (
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

__version__ = "0.1.0"
__all__ = [
    "ENDPOINTS",
    "Endpoint",
    "ChatCompletionResponse",
    "ChatCompletionChunk",
    "CompletionResponse",
    "EmbeddingsResponse",
    "ImagesResponse",
    "ListModelsResponse",
    "ModelObject",
    "OpenAIErrorEnvelope",
    "TranscriptionJSON",
    "TranscriptionVerboseJSON",
    "VideoJob",
    "__version__",
]
