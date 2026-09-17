"""Dependency-free repository boundary check for CI and local use.

Usage::

    python scripts/guard_repository.py

Exits non-zero and prints every violation when scientific data, database state,
secrets, machine-specific absolute paths or static-analysis suppression are
found in the working tree.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from dynamis.guard import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["--root", str(_REPO_ROOT)]))
