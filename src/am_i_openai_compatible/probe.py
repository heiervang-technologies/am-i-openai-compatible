"""Generic OpenAI-compat prober.

Probes any base URL against the canonical OpenAI surface declared in
endpoints.py. Two phases:

  Phase A — existence (no auth needed). For each endpoint we send a
  minimal probe (GET, OPTIONS, or a deliberately-empty POST) and treat
  anything other than 404 / connection-refused as "exists".

  Phase B — signature compliance. For each endpoint we send one
  minimal valid request and validate the response shape. We sniff a
  model id from /v1/models when needed; a missing model list disables
  Phase B and reports SKIP.

Output is JSON with the same schema as the per-service harness, so the
existing check.sh renderer can display a probe report unchanged.

Usage:
  python probe.py --base-url http://llm.ht.local --name monolith
  python probe.py --base-url http://localhost:8080 --report /tmp/x.json
  python probe.py --base-url http://… --skip-phase-b   # existence only
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import re
import sys
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

try:
    # websockets is a hard dep at runtime; the import is wrapped so the
    # rest of the module still loads if a downstream installs an older
    # release that lacks the sync subpackage. The WS probe path returns
    # SKIP with a clear message if this import fails.
    from websockets.exceptions import ConnectionClosed as _WSConnectionClosed
    from websockets.sync.client import connect as _ws_connect  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover — exercised only by minimal installs
    _ws_connect = None  # type: ignore[assignment]
    _WSConnectionClosed = Exception  # type: ignore[assignment, misc]

from .endpoints import ENDPOINTS, Endpoint

# ---------------------------------------------------------------------------
# Tiny synthetic media — kept frugal (1 s of silence, 1×1 PNG) to minimize
# bandwidth and decoder cost on the server.
# ---------------------------------------------------------------------------


def _silent_wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)
    return buf.getvalue()


def _tiny_png() -> bytes:
    # 1x1 transparent PNG; constant blob so we don't need PIL.
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAj"
        "CB0C8AAAAASUVORK5CYII="
    )


# ---------------------------------------------------------------------------
# Report event — same schema as conftest.py emits.
# ---------------------------------------------------------------------------


@dataclass
class Event:
    service: str  # for the prober this is the --name argument
    endpoint: str  # the endpoint label (path + group hint)
    phase: str  # "A" / "B"
    status: str  # PASS / WARN / FAIL / SKIP
    detail: str
    method: str = ""
    http_status: int = 0
    kind: str = ""  # core / optional / ext / ours
    group: str = ""
    profile: str = "openai"  # which probe profile this event was recorded under


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_dotted(obj: Any, dotted: str) -> tuple[bool, Any]:
    """Return (found, value) for a dotted path like 'choices.0.message.content'."""
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return False, None
        elif isinstance(cur, dict):
            if part not in cur:
                return False, None
            cur = cur[part]
        else:
            return False, None
    return True, cur


def _server_error_message(r: httpx.Response) -> str:
    """Best-effort extraction of the server's own error description.

    OpenAI-style envelopes put it at `error.message`; we fall back to
    `detail` (FastAPI default) and finally a snippet of the raw text.
    Used to surface the server's own explanation as a probe hint —
    much cleaner than guessing config from substrings.
    """
    try:
        body = r.json()
    except ValueError:
        return r.text[:120].strip() or f"HTTP {r.status_code}"
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return err["message"]
        if isinstance(err, str):
            return err
        if isinstance(body.get("detail"), str):
            return body["detail"]
    return r.text[:120].strip() or f"HTTP {r.status_code}"


def _classify_kind(model_id: str) -> set[str]:
    """Heuristic: tag a model id with the endpoint kinds it likely serves.

    Our prober is offline-only — no auth, no per-server registry. We
    fall back to lexical hints from the id, then degrade gracefully:
    if no match, the model is tagged as 'chat' (the most common kind)
    so we still try at least one inference call.
    """
    s = model_id.lower()
    kinds: set[str] = set()

    def _word(token: str) -> bool:
        """Match `token` as a separator-bounded word inside the model id.
        Treats `[a-z0-9]` as 'word' and `[-_/.]` (plus the start/end of
        string) as 'boundary'. Avoids the false positives from bare
        substring matching on short tokens (e.g. `tts` inside
        `chattsbot`, `wan` inside `swan`, `sam` inside `samantha`).
        """
        return bool(re.search(rf"(?:^|[-_/.]){re.escape(token)}(?=$|[-_/.0-9])", s))

    is_rerank = any(k in s for k in ("rerank", "reranker"))
    if is_rerank:
        kinds.add("rerank")
    if any(k in s for k in ("embed", "embedding", "e5", "gte")) or ("bge" in s and not is_rerank):
        kinds.add("embed")
    if any(k in s for k in ("whisper", "asr")):
        kinds.add("asr")
    # TTS tokens are 3-5 chars; bare substring matches caught `chattsbot`,
    # `voicebot`, `vibes-coder`, etc. Require word boundary. `speech`
    # intentionally dropped — it's ambiguous (speech-recognition,
    # speech-emotion-classifier are not TTS), and real TTS model ids
    # use specific tokens (tts/voice/bark/kokoro/xtts) instead.
    if any(_word(t) for t in ("tts", "voice", "vibe", "kokoro", "bark", "xtts")):
        kinds.add("tts")
    if any(k in s for k in ("flux", "sdxl", "stable-diffusion", "sd-")):
        kinds.add("image")
    if "edit" in s or "kontext" in s:
        kinds.add("image-edit")
    if "layered" in s or "decompose" in s:
        kinds.add("image-decompose")
    # `video`, `wan`, `ltx` are short; bare substring caught `swan-music-gen`
    # and `arabsora-7b`. Require word boundary.
    if any(_word(t) for t in ("video", "wan", "ltx", "cogvideo", "sora")):
        kinds.add("video")
    if any(k in s for k in ("trellis", "hunyuan3d", "instantmesh")):
        kinds.add("3d")
    if "sam-audio" in s or "audio-sam" in s:
        kinds.add("audio-segment")
    # `sam` is a 3-letter substring — PR #32's first fix `sam[0-9-]` still
    # matched `llamabsam-7b` (the `-` boundary matched ANY position, not
    # just word-start). Tighten to a true word-boundary match on both
    # sides via `_word()`.
    if _word("sam") and "audio" not in s:
        kinds.add("segment")
    if "omni" in s or "minicpm-o" in s:
        kinds.add("omni")
    # HT-compat v1.1: encoder-style tasks. NER / QA / sequence classification
    # have no overlap with chat/embed model ids in practice — the common
    # public checkpoints follow HF naming (squad, conll, mnli, go_emotions,
    # bert-base-NER, distilbert-…-squad).
    if "squad" in s or "-qa" in s or s.endswith("-qa") or "qa-" in s:
        kinds.add("qa")
    # `ner` is a 3-letter substring — bare `"ner" in s` false-positives
    # on "owner", "tuner", "generator". Require a word-boundary
    # neighbour so we match `bert-base-NER`, `dslim/bert-ner-…`, etc.
    if (
        re.search(r"\bner\b", s)
        or "-ner-" in s
        or "-ner" == s[-4:]
        or s.startswith("ner-")
        or "conll" in s
    ):
        kinds.add("ner")
    if any(
        k in s
        for k in (
            "mnli",
            "zero-shot",
            "zeroshot",
            "go_emotions",
            "sentiment",
            "-classifier",
            "classification",
        )
    ):
        kinds.add("classify")
    if not kinds:
        kinds.add("chat")
    return kinds


def _kinds_from_architecture(model: dict) -> set[str]:
    """Read per-model capability hints from `/v1/models[i].architecture`.

    Some llama.cpp-derived servers expose `architecture.input_modalities`
    and `architecture.output_modalities` per model in the OpenAI-shaped
    model response. Use them as a second signal alongside lexical
    `_classify_kind` so model ids that don't follow HF naming still get
    tagged correctly. Surfaced by issue #15: a model with
    `input_modalities=['text', 'image', 'audio']` but no `omni`
    substring in its id was falling back to plain `chat`.
    """
    arch = model.get("architecture") or {}
    in_mods = arch.get("input_modalities") or []
    out_mods = arch.get("output_modalities") or []
    if not isinstance(in_mods, list) or not isinstance(out_mods, list):
        return set()
    kinds: set[str] = set()
    if "audio" in in_mods or "audio" in out_mods:
        # The omni HT-compat row requires audio I/O; either direction
        # qualifies (input_audio + text_out is still omni per vLLM/Qwen2.5-Omni).
        kinds.add("omni")
    return kinds


# ---------------------------------------------------------------------------
# Prober
# ---------------------------------------------------------------------------


PROFILE_KINDS: dict[str, frozenset[str]] = {
    "openai": frozenset({"core", "optional", "ext"}),
    "ht": frozenset({"core", "optional", "ext", "ours"}),
}


class Prober:
    def __init__(
        self,
        base_url: str,
        name: str,
        *,
        phase_b: bool = True,
        conn_timeout: float = 4.0,
        req_timeout: float = 60.0,
        http2: bool = False,
        endpoints_filter: str = "",
        profile: str = "openai",
        model: str | None = None,
        api_key: str | None = None,
    ):
        if profile not in PROFILE_KINDS:
            raise ValueError(f"unknown profile {profile!r}; choose from {sorted(PROFILE_KINDS)}")
        self.base = base_url.rstrip("/")
        self.name = name
        self.phase_b = phase_b
        self.profile = profile
        self.model_override = model or None
        self.api_key = api_key or None
        self.conn_timeout = conn_timeout
        self.req_timeout = req_timeout
        self.client = httpx.Client(
            timeout=httpx.Timeout(req_timeout, connect=conn_timeout), http2=http2
        )
        self.events: list[Event] = []
        self.models_by_kind: dict[str, list[str]] = {}
        self._models_raw: list[dict] = []
        self._endpoints_filter = re.compile(endpoints_filter) if endpoints_filter else None

    # -- network primitives -------------------------------------------------

    def _emit(self, ev: Event) -> None:
        self.events.append(ev)

    def _liveness(self) -> tuple[bool, str]:
        try:
            r = self.client.get(self.base + "/v1/models", timeout=self.conn_timeout)
            return True, f"GET /v1/models -> {r.status_code}"
        except httpx.ConnectError as e:
            return False, f"connection refused ({e.__class__.__name__})"
        except httpx.HTTPError as e:
            # 4xx on /v1/models still means the host is up.
            return True, f"reachable ({e.__class__.__name__})"

    def _sniff_models(self) -> None:
        try:
            r = self.client.get(self.base + "/v1/models")
        except httpx.HTTPError:
            return
        if r.status_code != 200:
            return
        try:
            data = r.json().get("data") or []
        except ValueError:
            return
        self._models_raw = [d for d in data if isinstance(d, dict)]
        for m in self._models_raw:
            mid = m.get("id")
            if not isinstance(mid, str):
                continue
            kinds = _classify_kind(mid)
            kinds.update(_kinds_from_architecture(m))
            for k in kinds:
                self.models_by_kind.setdefault(k, []).append(mid)

    # -- model selection ----------------------------------------------------

    def _pick_model(self, ep: Endpoint) -> str | None:
        """Pick a model id to use for this endpoint's probe.

        Precedence:
          1. If --model NAME is set AND the override's classified kind
             includes ep.requires_model_kind (or ep has no kind
             requirement), use the override. This handles the
             router-mode case where /v1/models[0] is arbitrary and the
             operator wants to pin a known-good model.
          2. First model classified as ep.requires_model_kind.
          3. First model in /v1/models (last-resort fallback).
          4. None — Phase B should SKIP.
        """
        if self.model_override:
            override = self.model_override
            override_kinds = _classify_kind(override)
            if ep.requires_model_kind is None or ep.requires_model_kind in override_kinds:
                return override
            # Override doesn't match the endpoint's required kind; fall
            # through to the kind-based selection so e.g.
            # `--model borealis-4b` doesn't break /v1/embeddings.
        if ep.requires_model_kind:
            opts = self.models_by_kind.get(ep.requires_model_kind, [])
            if opts:
                return opts[0]
        if self._models_raw:
            return self._models_raw[0].get("id")
        return None

    # -- WebSocket primitives -----------------------------------------------

    def _ws_url(self, ep: Endpoint) -> str:
        """Build a wss://... URL from the base HTTP URL + endpoint path."""
        scheme_swap = self.base.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        return scheme_swap + ep.path.split("[")[0]

    def _ws_headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        # OpenAI's Realtime API uses the openai-beta subprotocol header.
        # Cheap to set; servers that don't care ignore it.
        h["openai-beta"] = "realtime=v1"
        return h

    def _phase_a_ws(self, ep: Endpoint) -> tuple[str, str, int]:
        """Phase A for WebSocket endpoints — try to open the upgrade.

        Grading:
          * Upgrade accepted (handshake completes) → PASS
          * 404 on the upgrade → FAIL (route absent) — `ours` rows under
            ht profile also FAIL same as core
          * 401/403 → WARN with "auth required" (route exists; we just
            don't have a key)
          * Any other HTTP error during handshake → FAIL
          * Connection refused / timeout → SKIP
        """
        if _ws_connect is None:
            return "SKIP", "websockets library not available", 0
        url = self._ws_url(ep)
        try:
            with _ws_connect(
                url,
                additional_headers=self._ws_headers(),
                open_timeout=self.conn_timeout,
                close_timeout=2.0,
            ):
                return "PASS", "ws upgrade ok", 101
        except Exception as exc:  # websockets raises a variety of types
            return self._ws_handshake_error(exc)

    def _ws_handshake_error(self, exc: BaseException) -> tuple[str, str, int]:
        """Map a websockets connect failure to a (status, detail, code)."""
        # InvalidStatus exposes the HTTP response on .response.status_code
        status = getattr(getattr(exc, "response", None), "status_code", 0)
        if status == 404:
            return "FAIL", "404 — endpoint absent", 404
        if status in (401, 403):
            return "WARN", f"{status} — auth required for upgrade", status
        if status:
            return "FAIL", f"upgrade rejected: {status}", status
        # No HTTP response → connect-level failure
        return "SKIP", f"ws connect: {exc.__class__.__name__}: {exc}", 0

    def _phase_b_ws(self, ep: Endpoint) -> tuple[str, str, int]:
        """Phase B for WebSocket endpoints — send the init event and
        wait for the expected event-type response.

        Grading:
          * Upgrade fails → FAIL (Phase A would have caught this too)
          * Init event sent, expected event received in time → PASS
          * Connected but no expected event in the budget → WARN
          * Any other exception → FAIL
        """
        if _ws_connect is None:
            return "SKIP", "websockets library not available", 0
        if ep.ws_init_event is None or not ep.ws_expect_event:
            return "SKIP", "no ws signature defined", 0

        url = self._ws_url(ep)
        # Wait budget is bounded by req_timeout but capped at 10s for the
        # Phase B happy-path — the Realtime API's session.created is
        # supposed to land "immediately" post-upgrade, not after long
        # model warmup.
        wait_budget = min(self.req_timeout, 10.0)

        try:
            with _ws_connect(
                url,
                additional_headers=self._ws_headers(),
                open_timeout=self.conn_timeout,
                close_timeout=2.0,
            ) as ws:
                ws.send(json.dumps(ep.ws_init_event))
                deadline = time.monotonic() + wait_budget
                seen_types: list[str] = []
                while time.monotonic() < deadline:
                    remaining = deadline - time.monotonic()
                    try:
                        raw = ws.recv(timeout=remaining)
                    except TimeoutError:
                        break
                    except _WSConnectionClosed:
                        # Server hung up gracefully — no more events
                        # coming. Treat the same as a timeout: if we've
                        # seen the expected event we'd already have
                        # returned PASS; otherwise fall through to WARN.
                        break
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="replace")
                    try:
                        evt = json.loads(raw)
                    except ValueError:
                        continue
                    evt_type = evt.get("type", "")
                    if evt_type:
                        seen_types.append(evt_type)
                    if evt_type == ep.ws_expect_event:
                        return "PASS", f"saw {evt_type}", 101
                    if len(seen_types) > 32:
                        break  # frugal — don't drain
                if seen_types:
                    return (
                        "WARN",
                        f"no {ep.ws_expect_event!r} (saw: {','.join(seen_types[:4])})",
                        101,
                    )
                return "WARN", f"no events within {wait_budget}s", 101
        except Exception as exc:
            status, detail, code = self._ws_handshake_error(exc)
            if status == "PASS":
                return "FAIL", f"ws error after upgrade: {exc}", 0
            return status, detail, code

    # -- phase A ------------------------------------------------------------

    def _phase_a(self, ep: Endpoint) -> tuple[str, str, int]:
        """Return (status, detail, http_status).

        Status semantics:
          * 404 on a `core` endpoint → FAIL (spec violation)
          * 404 on an `optional` endpoint → WARN (capability not offered;
            not non-compliance — a chat-only server is allowed to skip
            audio/images/embeddings entirely)
          * 501 on any endpoint → WARN with the server's own error body
            verbatim. Servers like llama-server return 501 with a
            self-describing message (e.g. "This server does not support
            embeddings. Start it with --embeddings"); surfacing that
            text is more useful than guessing config from a status code.
          * Anything else 2xx/4xx → PASS (route exists; Phase B decides
            whether the contract is honored).

        WebSocket endpoints (ep.protocol == "ws") take a separate path —
        Phase A means "did the upgrade succeed?".
        """
        if ep.protocol == "ws":
            return self._phase_a_ws(ep)
        path = ep.path
        # path templating with the most permissive sniffed id (or a
        # placeholder that should still 4xx-not-404 on a real server).
        if "{model}" in path:
            mid = self._pick_model(ep) or "__probe_nonexistent__"
            path = path.replace("{model}", mid)

        # Strip the [stream] label we use to disambiguate streaming chat.
        url = self.base + path.split("[")[0]
        method = ep.method
        try:
            if method == "GET":
                r = self.client.get(url)
            elif method == "POST":
                if ep.multipart:
                    # Send empty multipart — server should 400/422, not 404.
                    r = self.client.post(url, files={"file": ("p.bin", b"")})
                else:
                    r = self.client.post(url, json={})
            else:
                r = self.client.request(method, url)
        except httpx.ConnectError as e:
            return "SKIP", f"connect: {e}", 0
        except httpx.HTTPError as e:
            return "SKIP", f"http: {e.__class__.__name__}", 0

        if r.status_code == 404:
            if ep.kind == "optional":
                return "WARN", "404 — capability not offered", 404
            # `ours` rows are only probed under --profile ht (filtered out
            # otherwise), so a 404 here means the server claims HT-compat
            # but is missing a required endpoint — grade as FAIL, same
            # as a missing `core` endpoint.
            return "FAIL", "404 — endpoint absent", 404
        if r.status_code == 501:
            return "WARN", f"501 — {_server_error_message(r)}", 501
        return "PASS", f"{r.status_code} (route exists)", r.status_code

    # -- phase B ------------------------------------------------------------

    def _phase_b(self, ep: Endpoint) -> tuple[str, str, int]:
        if not self.phase_b:
            return "SKIP", "phase B disabled", 0
        if ep.protocol == "ws":
            return self._phase_b_ws(ep)
        if ep.expects == () and ep.method != "POST":
            return "SKIP", "no signature defined", 0

        model_id = self._pick_model(ep)

        if ep.body is None and ep.method == "GET":
            return self._phase_b_get(ep)
        return self._phase_b_post(ep, model_id)

    def _phase_b_get(self, ep: Endpoint) -> tuple[str, str, int]:
        path = ep.path.split("[")[0]
        if "{model}" in path:
            if not self._models_raw:
                return "SKIP", "no models to template", 0
            path = path.replace("{model}", self._models_raw[0]["id"])
        try:
            r = self.client.get(self.base + path)
        except httpx.HTTPError as e:
            return "FAIL", f"http error: {e}", 0
        if r.status_code == 501:
            return "WARN", f"501 — {_server_error_message(r)}", 501
        if r.status_code != 200:
            return "FAIL", f"GET → {r.status_code}", r.status_code
        try:
            body = r.json()
        except ValueError:
            return "FAIL", "non-JSON response", r.status_code
        return self._validate_shape(ep, body, r.status_code)

    def _phase_b_post(self, ep: Endpoint, model_id: str | None) -> tuple[str, str, int]:
        if ep.body and "{model}" in json.dumps(ep.body) and model_id is None:
            return "SKIP", f"no model of kind '{ep.requires_model_kind}'", 0

        body = json.loads(json.dumps(ep.body or {}).replace("{model}", model_id or ""))
        url = self.base + ep.path.split("[")[0]
        stream = bool(body.pop("stream", False)) if isinstance(body, dict) else False

        try:
            if ep.multipart:
                files, data = self._multipart_payload(ep, body)
                r = self.client.post(url, files=files, data=data, timeout=self.req_timeout)
            elif stream:
                return self._phase_b_sse(ep, url, body)
            else:
                r = self.client.post(url, json=body, timeout=self.req_timeout)
        except httpx.HTTPError as e:
            return "FAIL", f"http error: {e}", 0

        if r.status_code == 503:
            # Transient capability gap — autoload-on-demand router that
            # couldn't bring the model up right this instant, server
            # under temporary memory pressure, etc. Endpoint is wired,
            # bytes are spec-correct, but right-now-not-available. WARN
            # mirrors how Phase A grades 501.
            return "WARN", f"503 — {_server_error_message(r)}", 503
        if r.status_code == 501:
            # Permanent capability gate — endpoint is wired but
            # config-disabled (e.g. boot without --reranking). Same
            # grading as Phase A; not the server's bug to retry.
            return "WARN", f"501 — {_server_error_message(r)}", 501
        if not (200 <= r.status_code < 300):
            return "FAIL", f"POST → {r.status_code}: {r.text[:120]}", r.status_code
        # 2xx — including 202 Accepted for async job submission. Shape
        # validation below handles whether the envelope is correct.

        # Audio/image responses are non-JSON. Both need an empty-content
        # gate analogous to the JSON one in `_validate_shape`: a server
        # returning the right Content-Type but a zero-byte body is the
        # binary version of "well-shaped 200 with no useful content".
        if ep.expects == "audio":
            ct = r.headers.get("content-type", "")
            if not (ct.startswith("audio/") or ct == "application/octet-stream"):
                return "FAIL", f"expected audio/*, got {ct!r}", r.status_code
            if len(r.content) == 0:
                return "FAIL", f"empty audio body (200 OK, ct={ct!r})", r.status_code
            return "PASS", f"{ct}, {len(r.content)}B", r.status_code
        if ep.expects == "image":
            if len(r.content) == 0:
                return "FAIL", "empty image body (200 OK)", r.status_code
            return "PASS", f"image bytes={len(r.content)}", r.status_code

        try:
            body_json = r.json()
        except ValueError:
            return "FAIL", "non-JSON response", r.status_code
        return self._validate_shape(ep, body_json, r.status_code)

    def _phase_b_sse(self, ep: Endpoint, url: str, body: dict) -> tuple[str, str, int]:
        body = dict(body)
        body["stream"] = True
        chunks = 0
        saw_done = False
        content_len = 0
        status = 0
        ct = ""
        try:
            with self.client.stream("POST", url, json=body, timeout=self.req_timeout) as r:
                status = r.status_code
                ct = r.headers.get("content-type", "")
                if status == 503:
                    r.read()  # so httpx populates r.text for the error helper
                    return ("WARN", f"503 — {_server_error_message(r)}", 503)
                if status == 501:
                    r.read()
                    return ("WARN", f"501 — {_server_error_message(r)}", 501)
                if status != 200 or "text/event-stream" not in ct:
                    return ("FAIL", f"POST stream → {status} ct={ct!r}", status)
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        saw_done = True
                        break
                    try:
                        evt = json.loads(data)
                    except ValueError:
                        continue
                    chunks += 1
                    ok, dc = _get_dotted(evt, "choices.0.delta.content")
                    if ok and isinstance(dc, str):
                        content_len += len(dc)
                    if chunks > 32:
                        break  # frugal — don't drain
        except httpx.HTTPError as e:
            return "FAIL", f"http error: {e}", status
        if chunks == 0:
            return "FAIL", "no SSE data chunks", status
        if ep.min_content_length > 0 and content_len < ep.min_content_length:
            return (
                "FAIL",
                f"empty content (chunks={chunks}, delta.content total len {content_len})",
                status,
            )
        return ("PASS" if saw_done else "WARN", f"chunks={chunks}, [DONE]={saw_done}", status)

    def _multipart_payload(self, ep: Endpoint, body: dict) -> tuple[dict, dict]:
        files = {}
        if ep.group in ("audio-stt", "audio-segment"):
            files["file"] = ("probe.wav", _silent_wav(), "audio/wav")
        elif ep.group == "images":
            files["image"] = ("probe.png", _tiny_png(), "image/png")
            if "edits" in ep.path:
                files["mask"] = ("mask.png", _tiny_png(), "image/png")
        elif ep.group == "segment":
            files["image"] = ("probe.png", _tiny_png(), "image/png")
        return files, body

    def _validate_shape(self, ep: Endpoint, body: Any, http_status: int) -> tuple[str, str, int]:
        if not isinstance(ep.expects, tuple) or not ep.expects:
            return "PASS", "200 (no shape check)", http_status
        missing = []
        for k in ep.expects:
            ok, _ = _get_dotted(body, k)
            if not ok:
                missing.append(k)
        if missing:
            return ("FAIL", f"missing keys: {', '.join(missing)}", http_status)
        if ep.content_path and ep.min_content_length > 0:
            ok, val = _get_dotted(body, ep.content_path)
            # Differentiate the three failure shapes — same gate, different
            # diagnostic. Conflating them all as "missing content" misleads
            # debugging: a null value at the path is a different server bug
            # from the path being absent, and either is different from a
            # non-string (e.g. some servers default to 0 / [] when they
            # have nothing to say).
            if not ok:
                return ("FAIL", f"missing key {ep.content_path}", http_status)
            if val is None:
                return ("FAIL", f"null content at {ep.content_path}", http_status)
            if not isinstance(val, str):
                return (
                    "FAIL",
                    f"non-string content at {ep.content_path} (got {type(val).__name__})",
                    http_status,
                )
            if len(val) < ep.min_content_length:
                return (
                    "FAIL",
                    f"empty content (200 OK, {ep.content_path}=len {len(val)})",
                    http_status,
                )
        return "PASS", "shape ok", http_status

    # -- driver -------------------------------------------------------------

    def _endpoints(self) -> list[Endpoint]:
        allowed = PROFILE_KINDS[self.profile]
        eps = [e for e in ENDPOINTS if e.kind in allowed]
        if self._endpoints_filter is not None:
            eps = [e for e in eps if self._endpoints_filter.search(e.path)]
        return eps

    def run(self) -> list[Event]:
        endpoints = self._endpoints()
        live, why = self._liveness()
        if not live:
            for ep in endpoints:
                self._emit(
                    Event(
                        service=self.name,
                        endpoint=ep.path,
                        phase="A",
                        status="SKIP",
                        detail=why,
                        method=ep.method,
                        kind=ep.kind,
                        group=ep.group,
                        profile=self.profile,
                    )
                )
            return self.events

        self._sniff_models()

        for ep in endpoints:
            label = ep.path
            # phase A
            a_status, a_detail, a_code = self._phase_a(ep)
            self._emit(
                Event(
                    service=self.name,
                    endpoint=label,
                    phase="A",
                    status=a_status,
                    detail=a_detail,
                    method=ep.method,
                    http_status=a_code,
                    kind=ep.kind,
                    group=ep.group,
                    profile=self.profile,
                )
            )

            # phase B only if A says the route exists
            if a_status != "PASS":
                continue
            if ep.path in ("/v1/files", "/v1/batches", "/v1/fine_tuning/jobs"):
                # admin/list routes — existence is the meaningful test.
                # /v1/uploads was historically here but graduated to POST
                # with a real create body in v0.3.1, so it now runs Phase B.
                continue

            b_status, b_detail, b_code = self._phase_b(ep)
            self._emit(
                Event(
                    service=self.name,
                    endpoint=label,
                    phase="B",
                    status=b_status,
                    detail=b_detail,
                    method=ep.method,
                    http_status=b_code,
                    kind=ep.kind,
                    group=ep.group,
                    profile=self.profile,
                )
            )

        return self.events


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--base-url", required=True, help="root URL of the target (e.g. http://llm.ht.local)"
    )
    p.add_argument("--name", default=None, help="label for the report (defaults to base-url host)")
    p.add_argument(
        "--report",
        default=None,
        help="output JSON path (default: tests/openai-compat/report-<name>.json)",
    )
    p.add_argument("--skip-phase-b", action="store_true", help="existence-only run (Phase A only)")
    p.add_argument("--conn-timeout", type=float, default=4.0)
    p.add_argument("--req-timeout", type=float, default=60.0)
    p.add_argument(
        "--endpoints-filter",
        default="",
        help="regex; only endpoint paths matching are probed",
    )
    p.add_argument(
        "--profile",
        choices=sorted(PROFILE_KINDS),
        default="openai",
        help=(
            "which catalog rows to probe: 'openai' (core/optional/ext; default), "
            "'ht' (adds HT-compat 'ours' rows and FAILs on 404)"
        ),
    )
    p.add_argument(
        "--model",
        default=None,
        help=(
            "pin a specific model id for Phase B bodies (e.g. 'borealis-4b'). "
            "Useful for router-mode servers where /v1/models[0] is arbitrary. "
            "Falls back to kind-based selection for endpoints whose required "
            "kind the override can't serve."
        ),
    )
    p.add_argument(
        "--openai-api-key",
        default=None,
        help=(
            "bearer token sent on WebSocket upgrades (only used by ws-protocol "
            "rows like /v1/realtime; ignored for REST probes). Most OSS servers "
            "accept the empty default; OpenAI-hosted endpoints require a real key."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _argparser().parse_args(argv)
    name = args.name or httpx.URL(args.base_url).host or "probe"
    report = Path(args.report) if args.report else Path.cwd() / f"report-{name}.json"

    prober = Prober(
        args.base_url,
        name,
        phase_b=not args.skip_phase_b,
        conn_timeout=args.conn_timeout,
        req_timeout=args.req_timeout,
        endpoints_filter=args.endpoints_filter,
        profile=args.profile,
        model=args.model,
        api_key=args.openai_api_key,
    )
    t0 = time.monotonic()
    events = prober.run()
    elapsed = time.monotonic() - t0

    report.write_text(json.dumps([asdict(e) for e in events], indent=2))

    # Quick text summary so the CLI return makes sense without check.sh.
    n = len(events)
    by_status: dict[str, int] = {}
    for e in events:
        by_status[e.status] = by_status.get(e.status, 0) + 1
    summary = "  ".join(f"{k}={v}" for k, v in sorted(by_status.items()))
    print(f"probe '{name}': {n} events in {elapsed:.1f}s  ·  {summary}")
    print(f"report: {report}")
    return 0 if by_status.get("FAIL", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
