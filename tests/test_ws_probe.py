"""WebSocket Phase A/B tests (v0.3) for /v1/realtime-style endpoints.

Spins up an in-process `websockets` server in a daemon thread, points
the Prober at it via a synthesized `base-url`, and asserts the
grading. Covers:

  * Handshake succeeds + expected event arrives → PASS
  * Handshake succeeds but no expected event in budget → WARN
  * Server returns 404 on upgrade → FAIL
  * Server returns 401 on upgrade → WARN auth required
  * Connection refused on a closed port → SKIP

The Endpoint catalog ships a `/v1/realtime` row; tests use
`endpoints_filter` to scope to it.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from contextlib import contextmanager

import pytest

websockets_sync_server = pytest.importorskip("websockets.sync.server")
from websockets.datastructures import Headers  # noqa: E402
from websockets.http11 import Response as WSResponse  # noqa: E402
from websockets.sync.server import serve  # noqa: E402

from am_i_openai_compatible.probe import Prober  # noqa: E402


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def _ws_server(handler, process_request=None):
    """Spin up a websockets sync server on a free port, yield base_url."""
    port = _free_port()
    server = serve(
        handler,
        "127.0.0.1",
        port,
        process_request=process_request,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Give the listener a beat to bind. websockets sync.server is fast;
    # a tiny sleep avoids racey connect refusals.
    time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=2.0)


def _events_by_endpoint(events, path):
    return [e for e in events if e.endpoint == path]


# ---------------------------------------------------------------------------
# Phase B happy / sad path
# ---------------------------------------------------------------------------


def test_ws_phase_b_passes_when_session_created_arrives():
    """The Realtime API shape: server emits session.created right after
    upgrade. Probe should grade PASS."""

    def handler(ws):
        # Send session.created unprompted (real Realtime API does this).
        ws.send(json.dumps({"type": "session.created", "session": {"id": "sess-1"}}))
        # Wait for the probe's session.update, then close.
        try:
            ws.recv(timeout=2.0)
        except TimeoutError:
            pass

    with _ws_server(handler) as base:
        # Models endpoint won't be hit (ws path skips the http liveness),
        # but the liveness check still pings /v1/models. Stub it via a
        # 404 → liveness still treats the host as up.
        p = Prober(base, "test", endpoints_filter=r"^/v1/realtime$")
        events = p.run()
    rows = _events_by_endpoint(events, "/v1/realtime")
    phase_b = [e for e in rows if e.phase == "B"]
    assert phase_b and phase_b[0].status == "PASS", [(e.phase, e.status, e.detail) for e in rows]


def test_ws_phase_b_warns_when_expected_event_never_arrives():
    """Server upgrades but never emits session.created. Phase B should
    WARN with what it did see, not FAIL — endpoint is wired."""

    def handler(ws):
        # Send a different event type — useful but not what we expect.
        ws.send(json.dumps({"type": "session.error", "message": "nope"}))
        try:
            ws.recv(timeout=2.0)
        except TimeoutError:
            pass

    with _ws_server(handler) as base:
        p = Prober(
            base,
            "test",
            req_timeout=2.0,  # cap the wait so the test is fast
            endpoints_filter=r"^/v1/realtime$",
        )
        events = p.run()
    rows = _events_by_endpoint(events, "/v1/realtime")
    phase_b = [e for e in rows if e.phase == "B"]
    assert phase_b and phase_b[0].status == "WARN"
    assert "session.created" in phase_b[0].detail
    assert "session.error" in phase_b[0].detail


# ---------------------------------------------------------------------------
# Handshake failures
# ---------------------------------------------------------------------------


def _reject(status: int):
    def process_request(connection, request):
        return WSResponse(status, "rejected", Headers(), b"")

    return process_request


def test_ws_phase_a_404_is_fail():
    """A WS upgrade attempt that gets HTTP 404 from the server should
    grade Phase A as FAIL — the route doesn't exist."""

    def handler(ws):
        pass  # never reached

    with _ws_server(handler, process_request=_reject(404)) as base:
        p = Prober(base, "test", phase_b=False, endpoints_filter=r"^/v1/realtime$")
        events = p.run()
    rows = _events_by_endpoint(events, "/v1/realtime")
    assert rows and rows[0].status == "FAIL"
    assert "404" in rows[0].detail


def test_ws_phase_a_401_is_warn_auth_required():
    """401/403 means the route exists; we just don't have a key. WARN
    so an unauthed CI run doesn't tank on Realtime probes."""

    def handler(ws):
        pass

    with _ws_server(handler, process_request=_reject(401)) as base:
        p = Prober(base, "test", phase_b=False, endpoints_filter=r"^/v1/realtime$")
        events = p.run()
    rows = _events_by_endpoint(events, "/v1/realtime")
    assert rows and rows[0].status == "WARN"
    assert "auth" in rows[0].detail.lower()


# ---------------------------------------------------------------------------
# Connectivity
# ---------------------------------------------------------------------------


def test_ws_phase_a_connect_refused_is_skip():
    """No server listening on the port at all → SKIP (matches the HTTP
    liveness short-circuit for the rest of the catalog)."""
    port = _free_port()
    base = f"http://127.0.0.1:{port}"

    p = Prober(base, "test", phase_b=False, endpoints_filter=r"^/v1/realtime$")
    events = p.run()
    # The HTTP liveness check fails first → every endpoint SKIPs.
    rows = _events_by_endpoint(events, "/v1/realtime")
    assert rows and rows[0].status == "SKIP"


# ---------------------------------------------------------------------------
# Auth header forwarding
# ---------------------------------------------------------------------------


def test_ws_sends_authorization_header_when_api_key_given():
    """Probe with --openai-api-key should forward Bearer <key> on the
    WS upgrade. Server captures the header and asserts."""
    captured: dict = {}

    def process_request(connection, request):
        captured["auth"] = request.headers.get("Authorization", "")
        captured["beta"] = request.headers.get("openai-beta", "")
        return None  # allow upgrade

    def handler(ws):
        ws.send(json.dumps({"type": "session.created"}))
        try:
            ws.recv(timeout=2.0)
        except TimeoutError:
            pass

    with _ws_server(handler, process_request=process_request) as base:
        p = Prober(
            base,
            "test",
            api_key="sk-test-123",
            endpoints_filter=r"^/v1/realtime$",
        )
        p.run()
    assert captured["auth"] == "Bearer sk-test-123"
    assert captured["beta"] == "realtime=v1"
