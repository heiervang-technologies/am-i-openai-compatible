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
    width = max(len(e.path) for e in rows) + 2
    print(f"{'PATH':<{width}}{'METHOD':<8}{'GROUP':<10}KIND")
    print(f"{'-' * (width - 2):<{width}}{'-' * 6:<8}{'-' * 8:<10}{'-' * 4}")
    for e in rows:
        print(f"{e.path:<{width}}{e.method:<8}{e.group:<10}{e.kind}")
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
    return probe.main(forwarded)


def _cmd_gap(args: argparse.Namespace) -> int:
    from . import gap

    forwarded = ["--monolith", args.monolith, "--cluster", args.cluster, "--format", args.format]
    if args.output:
        forwarded += ["-o", args.output]
    return gap.main(forwarded)


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
    sp.set_defaults(func=_cmd_probe)

    sg = sub.add_parser("gap", help="compare monolith vs per-service reports")
    sg.add_argument("--monolith", required=True, help="probe report for the unified surface")
    sg.add_argument("--cluster", required=True, help="report.json from the per-service harness")
    sg.add_argument("--format", choices=("text", "gum", "markdown"), default="text")
    sg.add_argument("-o", "--output", help="write rendered output here")
    sg.set_defaults(func=_cmd_gap)

    ss = sub.add_parser("spec", help="print the canonical endpoint catalog")
    ss.add_argument("--group", help="restrict to one group (chat/audio/...)")
    ss.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    ss.set_defaults(func=_cmd_spec)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
