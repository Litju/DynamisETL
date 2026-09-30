"""Verify checksum-bound allowlisted artifacts before a Vercel deployment."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from dynamis.deployment import DeploymentError, load_public_seed
from dynamis.storage.object_store import immutable_object_key


def verify(path: Path, environment: str, git_sha: str) -> tuple[str, ...]:
    try:
        receipt: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ("artifact receipt is missing or invalid JSON",)
    failures: list[str] = []
    if receipt.get("environment") != environment:
        failures.append("artifact receipt environment does not match the deployment")
    if receipt.get("git_sha") != git_sha:
        failures.append("artifact receipt Git SHA does not match the release revision")
    try:
        allowlisted = {item.dataset_id for item in load_public_seed()}
    except DeploymentError as exc:
        return tuple([*failures, str(exc)])
    objects = receipt.get("objects")
    if not isinstance(objects, list) or not objects:
        return tuple([*failures, "artifact receipt contains no objects"])
    if len(objects) != 1:
        failures.append("artifact receipt must contain exactly one production-approved object")
    seen: set[tuple[str, str]] = set()
    for item in objects:
        if not isinstance(item, dict):
            failures.append("artifact receipt contains an invalid object entry")
            continue
        dataset_id = item.get("dataset_id")
        checksum = item.get("checksum_sha256", "")
        if dataset_id not in allowlisted:
            failures.append(f"object dataset {dataset_id!r} is outside the rights allowlist")
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", checksum):
            failures.append(f"{dataset_id}: object checksum is invalid")
            continue
        if item.get("object_key") != immutable_object_key(checksum):
            failures.append(f"{dataset_id}: object key is not checksum-bound")
        if not isinstance(item.get("size_bytes"), int) or item["size_bytes"] <= 0:
            failures.append(f"{dataset_id}: object size is invalid")
        seen.add((dataset_id, checksum))
    if receipt.get("object_count") != len(objects):
        failures.append("artifact receipt object count does not reconcile")
    if len(seen) != len(objects):
        failures.append("artifact receipt contains duplicate dataset/checksum entries")
    return tuple(failures)


def compare_receipts(preview_path: Path, production_path: Path, git_sha: str) -> tuple[str, ...]:
    failures = [
        *verify(preview_path, "preview", git_sha),
        *verify(production_path, "production", git_sha),
    ]
    if failures:
        return tuple(failures)
    preview = json.loads(preview_path.read_text(encoding="utf-8"))
    production = json.loads(production_path.read_text(encoding="utf-8"))

    def objects(receipt: dict[str, Any]) -> set[tuple[str, str, str, int]]:
        return {
            (item["dataset_id"], item["checksum_sha256"], item["object_key"], item["size_bytes"])
            for item in receipt["objects"]
        }

    if objects(preview) != objects(production):
        return ("production artifact checksums do not match Preview",)
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
    print("allowlisted object count and checksum-bound keys reconciled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
