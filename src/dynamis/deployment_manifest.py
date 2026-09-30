"""Validation and lookup for SHA-scoped Vercel Private Blob manifests."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from dynamis.deployment import (
    DeploymentError,
    load_public_demo_resources,
    load_public_seed,
    rights_allowlist_sha256,
)
from dynamis.storage.object_store import immutable_object_key


def manifest_key(environment: str, git_sha: str) -> str:
    if environment not in {"preview", "production"}:
        raise DeploymentError("manifest environment must be preview or production")
    if not re.fullmatch(r"[0-9a-f]{40}", git_sha):
        raise DeploymentError("manifest Git SHA must be a 40-character lowercase SHA")
    return f"manifests/{environment}/{git_sha}.json"


def validate_manifest(receipt: dict[str, Any], environment: str, git_sha: str) -> tuple[str, ...]:
    """Validate the full curated object receipt before it becomes readiness evidence."""
    failures: list[str] = []
    if receipt.get("schema_version") != 1:
        failures.append("artifact receipt schema version is unsupported")
    if receipt.get("environment") != environment:
        failures.append("artifact receipt environment does not match the deployment")
    if receipt.get("git_sha") != git_sha:
        failures.append("artifact receipt Git SHA does not match the release revision")
    if receipt.get("manifest_key") != manifest_key(environment, git_sha):
        failures.append("artifact receipt does not identify its SHA-scoped Blob manifest")
    if receipt.get("rights_allowlist_sha256") != rights_allowlist_sha256():
        failures.append("artifact receipt rights allow-list hash does not match this release")

    try:
        allowlisted = sorted(seed.dataset_id for seed in load_public_seed())
        demo_resources = [
            {
                "dataset_id": item.dataset_id,
                "session_id": item.session_id,
                "worlds": list(item.worlds),
            }
            for item in load_public_demo_resources()
        ]
    except DeploymentError as exc:
        return tuple([*failures, str(exc)])
    if receipt.get("allowlisted_datasets") != allowlisted:
        failures.append("artifact receipt allow-list differs from the committed rights authority")
    if receipt.get("demo_resources") != demo_resources:
        failures.append("artifact receipt demo slice differs from the committed selection")

    objects = receipt.get("objects")
    if not isinstance(objects, list) or not objects:
        return tuple([*failures, "artifact receipt contains no objects"])
    if receipt.get("object_count") != len(objects):
        failures.append("artifact receipt object count does not reconcile")
    byte_count = 0
    demo_datasets = {item["dataset_id"] for item in demo_resources}
    seen_objects: set[tuple[str, str]] = set()
    seen_artifacts: set[str] = set()
    for item in objects:
        if not isinstance(item, dict):
            failures.append("artifact receipt contains an invalid object entry")
            continue
        dataset_id = item.get("dataset_id")
        checksum = item.get("checksum_sha256", "")
        size = item.get("size_bytes")
        if dataset_id not in demo_datasets:
            failures.append(f"object dataset {dataset_id!r} is outside the curated demo slice")
        elif dataset_id not in allowlisted:
            failures.append(f"object dataset {dataset_id!r} is outside the rights allow-list")
        if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            failures.append(f"{dataset_id}: object checksum is invalid")
            continue
        if item.get("object_key") != immutable_object_key(checksum):
            failures.append(f"{dataset_id}: object key is not checksum-bound")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            failures.append(f"{dataset_id}: object size is invalid")
        else:
            byte_count += size
        if item.get("environment") != environment:
            failures.append(f"{dataset_id}: object environment does not match the receipt")
        if item.get("git_sha") != git_sha:
            failures.append(f"{dataset_id}: object Git SHA does not match the receipt")
        source_kinds = item.get("source_kinds")
        if not isinstance(source_kinds, list) or not source_kinds:
            failures.append(f"{dataset_id}: object source kinds are missing")
        artifact_ids = item.get("artifact_ids")
        if (
            not isinstance(artifact_ids, list)
            or not artifact_ids
            or any(
                not isinstance(artifact_id, str) or not artifact_id for artifact_id in artifact_ids
            )
        ):
            failures.append(f"{dataset_id}: object artifact ids are missing")
        else:
            duplicates = seen_artifacts.intersection(artifact_ids)
            if duplicates:
                failures.append(f"artifact receipt repeats artifact ids: {sorted(duplicates)}")
            seen_artifacts.update(artifact_ids)
        identity = (str(dataset_id), checksum)
        if identity in seen_objects:
            failures.append("artifact receipt contains duplicate dataset/checksum entries")
        seen_objects.add(identity)
    if receipt.get("byte_count") != byte_count:
        failures.append("artifact receipt byte count does not reconcile")
    return tuple(failures)


def parse_manifest(raw: bytes, environment: str, git_sha: str) -> frozenset[str]:
    try:
        receipt = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeploymentError("deployed Blob manifest is invalid JSON") from exc
    if not isinstance(receipt, dict):
        raise DeploymentError("deployed Blob manifest must be an object")
    failures = validate_manifest(receipt, environment, git_sha)
    if failures:
        raise DeploymentError("deployed Blob manifest failed validation: " + "; ".join(failures))
    return frozenset(
        artifact_id for item in receipt["objects"] for artifact_id in item["artifact_ids"]
    )


def load_manifest(storage: Any, environment: str, git_sha: str) -> frozenset[str]:
    """Read the exact release manifest from the configured private object store."""
    raw = storage.get_bytes(manifest_key(environment, git_sha))
    artifact_ids = parse_manifest(raw, environment, git_sha)
    receipt = json.loads(raw)
    for item in receipt["objects"]:
        metadata = storage.head(item["object_key"])
        if (
            metadata is None
            or metadata.size_bytes != item["size_bytes"]
            or (metadata.sha256 and metadata.sha256 != item["checksum_sha256"])
        ):
            raise DeploymentError("deployed Blob manifest references missing or mismatched bytes")
    return artifact_ids


def receipt_sha256(path_bytes: bytes) -> str:
    """Stable digest recorded by the Neon promotion receipt for a Blob receipt."""
    return hashlib.sha256(path_bytes).hexdigest()
