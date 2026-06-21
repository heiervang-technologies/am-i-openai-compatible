"""Catalog-vs-docs drift check.

The reference docs (`docs/spec/canonical-surface.md` and
`docs/compatibility-matrix.md`) are hand-curated mirrors of the
openai-profile rows in `endpoints.py`. Drift accumulated to 6
missing rows by Epoch 19 (PRs #84 / #86); this check prevents the
same thing recurring.

Per RFC #87 option 1: cheapest fix that catches the drift without
changing how the docs are authored.

The check is intentionally narrow:
- Only enforces openai-profile rows (core / optional / ext). HT-compat
  `ours` rows live in `docs/spec/ht-compat.md` which is an authored
  spec, not a mirror.
- Tolerates docs referring to paths NOT in the catalog (retired
  endpoints, spec-only polling routes) — those are valid narrative
  references.
- Catches the failure mode that hurt us: a catalog row that exists
  in `endpoints.py` but doesn't show up in either reference doc at
  all.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
DOCS = (
    REPO / "docs/spec/canonical-surface.md",
    REPO / "docs/compatibility-matrix.md",
)

# Bare path normalizations the matrix uses (`{id}` instead of `{model}`)
PATH_ALIASES = {"/v1/models/{id}": "/v1/models/{model}"}


def _doc_paths(doc: Path) -> set[str]:
    """Extract backtick-wrapped /v1/... paths from a markdown doc."""
    raw = set(re.findall(r"`(/v1/[^`]+)`", doc.read_text()))
    return {PATH_ALIASES.get(p, p) for p in raw}


def main() -> int:
    from am_i_openai_compatible.endpoints import ENDPOINTS

    openai_catalog = {
        e.path.split("[")[0] for e in ENDPOINTS if e.kind in ("core", "optional", "ext")
    }

    failed = False
    for doc in DOCS:
        missing = openai_catalog - _doc_paths(doc)
        if missing:
            failed = True
            print(
                f"::error file={doc.relative_to(REPO)}::"
                f"missing {len(missing)} openai-profile catalog row(s): "
                f"{sorted(missing)}",
                file=sys.stderr,
            )
            print(f"\n{doc.relative_to(REPO)} is missing:", file=sys.stderr)
            for p in sorted(missing):
                print(f"  - {p}", file=sys.stderr)

    if failed:
        print(
            "\nAdd a row to the affected doc(s) — see PRs #84 / #86 for examples.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
