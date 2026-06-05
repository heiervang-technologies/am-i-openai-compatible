"""am-i-openai-compatible — probe any HTTP server for OpenAI API compliance.

Public API:

    from am_i_openai_compatible import probe_url, ENDPOINTS

    report = probe_url("http://localhost:8080", name="my-server")
    print(report["summary"])
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

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

try:
    __version__ = _pkg_version("am-i-openai-compatible")
except PackageNotFoundError:
    # Editable / source-tree import without `pip install -e .` (rare —
    # mostly CI build steps that run tests from a checkout). Surface the
    # placeholder so `aioc --version` doesn't crash; the test-suite
    # asserts the installed flow returns the real number.
    __version__ = "0.0.0+unknown"
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
