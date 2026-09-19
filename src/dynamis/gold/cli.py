"""``dynamis-gold``: deterministic export -> dbt build -> publish pipeline.

Usage::

    dynamis-gold build     # export control plane + run dbt build (models/tests)
    dynamis-gold publish   # copy the built marts into the PostgreSQL gold schema
    dynamis-gold all       # build then publish

No step downloads anything: the export reads the configured PostgreSQL control
plane, dbt reads the local serving Parquet export, and publication reads the
local Gold DuckDB marts and writes the PostgreSQL Gold serving schema.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from dynamis.config import settings
from dynamis.gold.build import build_gold
from dynamis.gold.export import export_serving
from dynamis.gold.publish import publish_gold
from dynamis.storage.control_plane import control_plane_engine


def _engine():
    resolved = settings()
    return resolved, control_plane_engine(resolved)


def build() -> dict[str, Any]:
    """Export the control plane and run the dbt build."""
    resolved, engine = _engine()
    try:
        export = export_serving(resolved, engine)
        built = build_gold(resolved)
    finally:
        engine.dispose()
    return {"export": export.to_dict(), "build": built.to_dict()}


def publish() -> dict[str, Any]:
    """Publish the built marts into the PostgreSQL gold schema."""
    resolved, engine = _engine()
    try:
        return publish_gold(resolved, engine)
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the Gold build/publish pipeline."""
    parser = argparse.ArgumentParser(prog="dynamis-gold", description=__doc__)
    parser.add_argument("command", choices=("build", "publish", "all"))
    args = parser.parse_args(argv)
    if args.command == "build":
        summary = build()
    elif args.command == "publish":
        summary = publish()
    else:
        built = build()
        summary = {"build": built, "publish": publish()}
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
