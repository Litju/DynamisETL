"""Verify the curated checksum-bound object set in a deployed Blob manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from dynamis.deployment_manifest import validate_manifest


def verify(path: Path, environment: str, git_sha: str) -> tuple[str, ...]:
    try:
        receipt: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ("artifact receipt is missing or invalid JSON",)
    return validate_manifest(receipt, environment, git_sha)


def _objects(
    receipt: dict[str, Any],
) -> set[tuple[str, str, str, int, tuple[str, ...], tuple[str, ...]]]:
    return {
        (
            item["dataset_id"],
            item["checksum_sha256"],
            item["object_key"],
            item["size_bytes"],
            tuple(sorted(item["source_kinds"])),
            tuple(sorted(item["artifact_ids"])),
        )
        for item in receipt["objects"]
    }


def compare_receipts(preview_path: Path, production_path: Path, git_sha: str) -> tuple[str, ...]:
    failures = [
        *verify(preview_path, "preview", git_sha),
        *verify(production_path, "production", git_sha),
    ]
    if failures:
        return tuple(failures)
    preview = json.loads(preview_path.read_text(encoding="utf-8"))
    production = json.loads(production_path.read_text(encoding="utf-8"))
    if preview["demo_resources"] != production["demo_resources"]:
        return ("production demo resources do not match Preview",)
    if _objects(preview) != _objects(production):
        return ("production Blob objects do not match Preview",)
    return ()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--environment", choices=("preview", "production"), required=True)
    parser.add_argument("--git-sha", required=True)
    args = parser.parse_args(argv)
    failures = verify(args.receipt, args.environment, args.git_sha)
    if failures:
        print("artifact deployment gate blocked: " + "; ".join(failures), file=sys.stderr)
        return 2
    print("curated artifact count and checksum-bound private Blob manifest reconciled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
