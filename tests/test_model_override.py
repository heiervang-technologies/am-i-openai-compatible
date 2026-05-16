"""Tests for the --model override and Phase B 503 grading (v0.2.1).

Grounded in the real-world failure mode surfaced by ht-llama.cpp-dev
probing a router-mode deployment (titan): `/v1/models[0]` arbitrarily
returned a 24B model the autoload couldn't satisfy, so every Phase B
chat probe failed with 500 — even though the endpoint was healthy and
a 4B sibling on the same server worked.

The fixes:
  1. `--model NAME` pins the model id for Phase B bodies, falling back
     to kind-based selection only when the override can't serve the
     endpoint's required kind.
  2. Phase B grades 503 as WARN (transient capability gap), mirroring
     how Phase A grades 501.
"""

from __future__ import annotations

import httpx
import respx

from am_i_openai_compatible.probe import Prober

BASE = "http://aioc.test"


def _events_by_endpoint(events, path):
    return [e for e in events if e.endpoint == path]


# ---------------------------------------------------------------------------
# --model override: precedence and kind-aware fallback
# ---------------------------------------------------------------------------


@respx.mock
def test_model_override_used_when_kind_matches():
    """A `--model borealis-4b` override should be used for chat-kind
    endpoints in preference to the arbitrary /v1/models[0] pick.
    """
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"id": "Devstral-Small-2-24B-Instruct"},
                    {"id": "borealis-4b"},
                ]
            },
        )
    )
    chat_route = respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 1,
                "model": "borealis-4b",
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

    p = Prober(BASE, "test", model="borealis-4b", endpoints_filter=r"^/v1/chat/completions$")
    p.run()

    # The sent body should reference the override, not the first listed model.
    sent = chat_route.calls.last.request
    assert b'"model":"borealis-4b"' in sent.content
    assert b"Devstral" not in sent.content


@respx.mock
def test_model_override_falls_back_when_kind_mismatched():
    """`--model borealis-4b` (chat-classified) shouldn't break embeddings:
    Phase B should fall back to a real embed-classified model.
    """
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"id": "borealis-4b"},
                    {"id": "bge-large-en-v1.5"},  # embed-classified
                ]
            },
        )
    )
    embed_route = respx.post(f"{BASE}/v1/embeddings").mock(
        return_value=httpx.Response(
            200,
            json={
                "object": "list",
                "data": [{"object": "embedding", "embedding": [0.1, 0.2], "index": 0}],
                "model": "bge-large-en-v1.5",
            },
        )
    )

    p = Prober(BASE, "test", model="borealis-4b", endpoints_filter=r"^/v1/embeddings$")
    p.run()

    sent = embed_route.calls.last.request
    assert b'"model":"bge-large-en-v1.5"' in sent.content


@respx.mock
def test_model_override_unknown_model_still_used():
    """If the override doesn't appear in /v1/models, we still trust the
    operator's pin (probe is offline-only; can't validate against an
    auth-gated registry). Phase B sends with the override and the server
    decides.
    """
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "some-other-model"}]})
    )
    chat_route = respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 1,
                "model": "pinned-name",
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

    p = Prober(
        BASE,
        "test",
        model="pinned-name",
        endpoints_filter=r"^/v1/chat/completions$",
    )
    p.run()

    sent = chat_route.calls.last.request
    assert b'"model":"pinned-name"' in sent.content


@respx.mock
def test_no_model_override_keeps_default_selection():
    """Backwards compat: without --model, behavior is unchanged —
    /v1/models[0] is used for the chat probe.
    """
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"id": "first-model"}, {"id": "second-model"}]},
        )
    )
    chat_route = respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 1,
                "model": "first-model",
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
    p.run()

    sent = chat_route.calls.last.request
    assert b'"model":"first-model"' in sent.content


# ---------------------------------------------------------------------------
# Phase B 503 grading
# ---------------------------------------------------------------------------


@respx.mock
def test_phase_b_503_with_envelope_warns_with_message():
    """The exact failure mode from titan: server returns 500 (will be
    503 after ht-llama.cpp#41 lands) with the canonical envelope when
    the autoload-on-demand router can't bring a model up. Endpoint is
    healthy; the model just isn't available right now. WARN, not FAIL.
    """
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            503,
            json={
                "error": {
                    "message": "model name=Devstral-Small-2-24B failed to load",
                    "code": 503,
                    "type": "service_unavailable",
                }
            },
        )
    )

    p = Prober(BASE, "test", endpoints_filter=r"^/v1/chat/completions$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/chat/completions")
    phase_b = [e for e in rows if e.phase == "B"]
    assert phase_b, "Phase B did not run"
    assert phase_b[0].status == "WARN"
    assert "503" in phase_b[0].detail
    assert "failed to load" in phase_b[0].detail


@respx.mock
def test_phase_b_503_on_streaming_warns_too():
    """Streaming variant takes a different code path (httpx.stream);
    503 there must also grade WARN, not FAIL.
    """
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            503,
            json={"error": {"message": "router busy", "code": 503}},
        )
    )

    p = Prober(BASE, "test", endpoints_filter=r"chat/completions\[stream\]")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/chat/completions[stream]")
    phase_b = [e for e in rows if e.phase == "B"]
    assert phase_b, "Phase B did not run"
    assert phase_b[0].status == "WARN"
    assert "503" in phase_b[0].detail
    assert "router busy" in phase_b[0].detail


@respx.mock
def test_phase_b_500_still_fails():
    """500 — actual server error — stays FAIL. We don't downgrade real
    bugs; only the 503 "transient unavailable" case warrants WARN.
    """
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "chat-1"}]})
    )
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(500, json={"error": {"message": "boom", "code": 500}})
    )

    p = Prober(BASE, "test", endpoints_filter=r"^/v1/chat/completions$")
    events = p.run()
    rows = _events_by_endpoint(events, "/v1/chat/completions")
    phase_b = [e for e in rows if e.phase == "B"]
    assert phase_b and phase_b[0].status == "FAIL"
    assert "500" in phase_b[0].detail
