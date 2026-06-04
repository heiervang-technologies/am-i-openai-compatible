"""Package-metadata invariants.

The v0.3.1 release shipped with `pyproject.toml = "0.3.0"` and a
hardcoded `__version__ = "0.3.0"` in `__init__.py` — so
`aioc --version` reported 0.3.0 from a v0.3.1 install. These tests
guard against that class of bug by asserting the dunder version
matches the installed package metadata. Since `__init__.py` now
derives `__version__` from `importlib.metadata`, drift between the
two sources is structurally impossible — but the invariant test is
cheap and makes the contract explicit.
"""

from __future__ import annotations

from importlib.metadata import version as _pkg_version
from pathlib import Path

import tomllib

import am_i_openai_compatible


def _pyproject_version() -> str:
    root = Path(__file__).parent.parent
    with (root / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def test_dunder_version_matches_installed_metadata():
    """__version__ is sourced from importlib.metadata at import time —
    they MUST agree."""
    assert am_i_openai_compatible.__version__ == _pkg_version("am-i-openai-compatible")


def test_dunder_version_matches_pyproject():
    """pyproject.toml is the single source of truth. Installed metadata
    flows from it via the build backend (hatchling). Drift here would
    mean the build picked up a stale wheel or the test is running
    against an unupgraded editable install."""
    assert am_i_openai_compatible.__version__ == _pyproject_version()
