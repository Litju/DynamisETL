"""Thin wrapper: export the FastAPI OpenAPI document.

The implementation lives in :mod:`dynamis.serving.openapi` so the operation is a
packaged console script; this file only keeps ``python scripts/...`` invocations
working.
"""

from __future__ import annotations

import sys

from dynamis.serving.openapi import main

if __name__ == "__main__":
    sys.exit(main())
