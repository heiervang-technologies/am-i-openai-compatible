"""`aioc` — Am-I-OpenAI-Compatible CLI.

Subcommands:

    aioc probe URL [--name NAME] [--report PATH] [--skip-phase-b]
        Probe one base URL and emit a JSON report.

    aioc gap --monolith REPORT --cluster REPORT [--format text|gum|markdown]
        Compare a monolith probe against per-service reports and surface
        the coverage gap.

    aioc spec [--group chat|audio|...]
        Print the canonical endpoint catalog (the spec the prober checks
        against) as a table or JSON.

    aioc render REPORT [--limit N] [--no-color]
        Render a probe JSON report as a colored ANSI table. One row per
        endpoint (FAIL > WARN > Phase B PASS > Phase A PASS > SKIP).

    aioc version
        Print version and exit.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .endpoints import ENDPOINTS


def _cmd_spec(args: argparse.Namespace) -> int:
    rows = [e for e in ENDPOINTS if not args.group or e.group == args.group]
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "path": e.path,
                        "method": e.method,
                        "group": e.group,
                        "kind": e.kind,
                        "notes": e.notes,
                    }
                    for e in rows
                ],
                indent=2,
            )
        )
        return 0
    # Compute column widths dynamically so long groups (`moderations`,
    # `fine-tuning`, `audio-segment`) don't overflow into KIND.
    pw = max(len(e.path) for e in rows) + 2
    gw = max(max(len(e.group) for e in rows), len("GROUP")) + 2
    mw = max(max(len(e.method) for e in rows), len("METHOD")) + 2
    print(f"{'PATH':<{pw}}{'METHOD':<{mw}}{'GROUP':<{gw}}KIND")
    print(f"{'-' * (pw - 2):<{pw}}{'-' * (mw - 2):<{mw}}{'-' * (gw - 2):<{gw}}{'-' * 4}")
    for e in rows:
        print(f"{e.path:<{pw}}{e.method:<{mw}}{e.group:<{gw}}{e.kind}")
    return 0


def _cmd_probe(args: argparse.Namespace) -> int:
    # Delegate to probe.py's main with the right argv.
    from . import probe

    forwarded = ["--base-url", args.url, "--name", args.name]
    if args.report:
        forwarded += ["--report", args.report]
    if args.skip_phase_b:
        forwarded.append("--skip-phase-b")
    if args.timeout is not None:
        forwarded += ["--req-timeout", str(args.timeout)]
    if args.endpoints_filter:
        forwarded += ["--endpoints-filter", args.endpoints_filter]
    if args.profile != "openai":
        forwarded += ["--profile", args.profile]
    if args.model:
        forwarded += ["--model", args.model]
    if args.openai_api_key:
        forwarded += ["--openai-api-key", args.openai_api_key]
    return probe.main(forwarded)


def _cmd_gap(args: argparse.Namespace) -> int:
    from . import gap

    forwarded = ["--monolith", args.monolith]
    clusters = args.cluster if isinstance(args.cluster, list) else [args.cluster]
    for c in clusters:
        forwarded += ["--cluster", c]
    forwarded += ["--format", args.format]
    if args.output:
        forwarded += ["-o", args.output]
    return gap.main(forwarded)


def _cmd_render(args: argparse.Namespace) -> int:
    from . import render as render_mod

    use_color = None if not args.no_color else False
    sys.stdout.write(render_mod.render_file(args.report, limit=args.limit, use_color=use_color))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aioc",
        description="Am I OpenAI Compatible? — probe any HTTP server.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("probe", help="probe one base URL")
    sp.add_argument("url", help="base URL, e.g. http://localhost:8080")
    sp.add_argument(
        "--name", default="server", help="label written into the report (default: server)"
    )
    sp.add_argument("--report", help="write JSON report to this path")
    sp.add_argument(
        "--skip-phase-b",
        action="store_true",
        help="existence checks only; do not send minimal bodies",
    )
    sp.add_argument("--timeout", type=float, help="per-request timeout in seconds")
    sp.add_argument(
        "--endpoints-filter",
        default="",
        help="regex applied to endpoint paths; only matching endpoints are probed",
    )
    sp.add_argument(
        "--profile",
        choices=("openai", "ht"),
        default="openai",
        help=(
            "which catalog rows to probe: 'openai' (default) "
            "or 'ht' (adds HT-compat extensions; see docs/spec/ht-compat.md)"
        ),
    )
    sp.add_argument(
        "--model",
        default=None,
        help=(
            "pin a specific model id for Phase B bodies (e.g. 'borealis-4b'); "
            "overrides the default first-listed-model selection. Useful for "
            "router-mode servers where /v1/models[0] is arbitrary."
        ),
    )
    sp.add_argument(
        "--openai-api-key",
        default=None,
        help=(
            "bearer token for WebSocket upgrades on /v1/realtime-style rows. "
            "OSS servers usually accept the empty default; OpenAI-hosted "
            "targets require a real key."
        ),
    )
    sp.set_defaults(func=_cmd_probe)

    sg = sub.add_parser("gap", help="compare monolith vs per-service reports")
    sg.add_argument("--monolith", required=True, help="probe report for the unified surface")
    sg.add_argument(
        "--cluster",
        required=True,
        action="append",
        help="report.json from the per-service harness (repeatable)",
    )
    sg.add_argument("--format", choices=("text", "gum", "markdown"), default="text")
    sg.add_argument("-o", "--output", help="write rendered output here")
    sg.set_defaults(func=_cmd_gap)

    ss = sub.add_parser("spec", help="print the canonical endpoint catalog")
    ss.add_argument("--group", help="restrict to one group (chat/audio/...)")
    ss.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    ss.set_defaults(func=_cmd_spec)

    sr = sub.add_parser("render", help="render a probe JSON report as a colored table")
    sr.add_argument("report", help="path to aioc probe JSON report")
    sr.add_argument(
        "--limit",
        type=int,
        default=0,
        help="cap rows shown (0 = all)",
    )
    sr.add_argument(
        "--no-color",
        action="store_true",
        help="strip ANSI colors (forced off in non-TTY by default)",
    )
    sr.set_defaults(func=_cmd_render)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
