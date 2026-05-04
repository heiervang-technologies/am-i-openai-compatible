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
import sys
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

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
    kind: str = ""  # core / ext / ours
    group: str = ""


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


def _classify_kind(model_id: str) -> set[str]:
    """Heuristic: tag a model id with the endpoint kinds it likely serves.

    Our prober is offline-only — no auth, no per-server registry. We
    fall back to lexical hints from the id, then degrade gracefully:
    if no match, the model is tagged as 'chat' (the most common kind)
    so we still try at least one inference call.
    """
    s = model_id.lower()
    kinds: set[str] = set()
    if any(k in s for k in ("embed", "embedding", "bge", "e5", "gte")):
        kinds.add("embed")
    if any(k in s for k in ("whisper", "asr")):
        kinds.add("asr")
    if any(k in s for k in ("tts", "voice", "speech", "vibe", "kokoro")):
        kinds.add("tts")
    if any(k in s for k in ("flux", "sdxl", "stable-diffusion", "sd-")):
        kinds.add("image")
    if "edit" in s or "kontext" in s:
        kinds.add("image-edit")
    if any(k in s for k in ("video", "wan", "ltx", "cogvideo", "sora")):
        kinds.add("video")
    if not kinds:
        kinds.add("chat")
    return kinds


# ---------------------------------------------------------------------------
# Prober
# ---------------------------------------------------------------------------


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
    ):
        self.base = base_url.rstrip("/")
        self.name = name
        self.phase_b = phase_b
        self.conn_timeout = conn_timeout
        self.req_timeout = req_timeout
        self.client = httpx.Client(
            timeout=httpx.Timeout(req_timeout, connect=conn_timeout), http2=http2
        )
        self.events: list[Event] = []
        self.models_by_kind: dict[str, list[str]] = {}
        self._models_raw: list[dict] = []

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
            for k in _classify_kind(mid):
                self.models_by_kind.setdefault(k, []).append(mid)

    # -- phase A ------------------------------------------------------------

    def _phase_a(self, ep: Endpoint) -> tuple[str, str, int]:
        """Return (status, detail, http_status). Status ∈ {PASS, FAIL, SKIP}.

        For GET endpoints: send GET; 404 = FAIL, anything else = PASS.
        For POST endpoints: send empty POST; 404 = FAIL, 405 = WARN-ish
        but treat as PASS (route exists, just rejects empty body),
        anything 4xx/2xx = PASS.
        """
        path = ep.path
        # path templating with the most permissive sniffed id (or a
        # placeholder that should still 4xx-not-404 on a real server).
        if "{model}" in path:
            mid = (
                self.models_by_kind.get(ep.requires_model_kind or "chat")
                or [m["id"] for m in self._models_raw if "id" in m]
                or ["__probe_nonexistent__"]
            )[0]
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
            return "FAIL", "404 — endpoint absent", 404
        if r.status_code == 501:
            return "FAIL", "501 — not implemented", 501
        return "PASS", f"{r.status_code} (route exists)", r.status_code

    # -- phase B ------------------------------------------------------------

    def _phase_b(self, ep: Endpoint) -> tuple[str, str, int]:
        if not self.phase_b:
            return "SKIP", "phase B disabled", 0
        if ep.expects == () and ep.method != "POST":
            return "SKIP", "no signature defined", 0

        # Pick a model id of the right kind, if any.
        model_id: str | None = None
        if ep.requires_model_kind:
            opts = self.models_by_kind.get(ep.requires_model_kind, [])
            if opts:
                model_id = opts[0]
            elif self._models_raw:
                # fallback: use the first listed model
                model_id = self._models_raw[0]["id"]
        elif self._models_raw and ep.body and "{model}" in json.dumps(ep.body):
            model_id = self._models_raw[0]["id"]

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

        if r.status_code != 200:
            return "FAIL", f"POST → {r.status_code}: {r.text[:120]}", r.status_code

        # Audio/image responses are non-JSON.
        if ep.expects == "audio":
            ct = r.headers.get("content-type", "")
            if not (ct.startswith("audio/") or ct == "application/octet-stream"):
                return "FAIL", f"expected audio/*, got {ct!r}", r.status_code
            return "PASS", f"{ct}, {len(r.content)}B", r.status_code
        if ep.expects == "image":
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
        status = 0
        ct = ""
        try:
            with self.client.stream("POST", url, json=body, timeout=self.req_timeout) as r:
                status = r.status_code
                ct = r.headers.get("content-type", "")
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
                        json.loads(data)
                    except ValueError:
                        continue
                    chunks += 1
                    if chunks > 32:
                        break  # frugal — don't drain
        except httpx.HTTPError as e:
            return "FAIL", f"http error: {e}", status
        if chunks == 0:
            return "FAIL", "no SSE data chunks", status
        return ("PASS" if saw_done else "WARN", f"chunks={chunks}, [DONE]={saw_done}", status)

    def _multipart_payload(self, ep: Endpoint, body: dict) -> tuple[dict, dict]:
        files = {}
        if ep.group == "audio-stt":
            files["file"] = ("probe.wav", _silent_wav(), "audio/wav")
        elif ep.group == "images":
            files["image"] = ("probe.png", _tiny_png(), "image/png")
            if "edits" in ep.path:
                files["mask"] = ("mask.png", _tiny_png(), "image/png")
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
        return "PASS", "shape ok", http_status

    # -- driver -------------------------------------------------------------

    def run(self) -> list[Event]:
        live, why = self._liveness()
        if not live:
            for ep in ENDPOINTS:
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
                    )
                )
            return self.events

        self._sniff_models()

        for ep in ENDPOINTS:
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
                )
            )

            # phase B only if A says the route exists
            if a_status != "PASS":
                continue
            if ep.path.endswith("/uploads") or ep.path == "/v1/files" or ep.path == "/v1/batches":
                # admin routes — existence is the meaningful test
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
