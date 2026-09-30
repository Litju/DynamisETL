"""Rights-checked deployment seed authority."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dynamis.config import repository_root
from dynamis.registry import validate_registry

PUBLIC_LICENSES = frozenset({"CC-BY-4.0", "MIT"})
ALLOWLIST_PATH = Path("infra/deploy/production-data-allowlist.json")


class DeploymentError(RuntimeError):
    """A deployment seed violates the committed rights or reproducibility gate."""


@dataclass(frozen=True, slots=True)
class SeedDataset:
    dataset_id: str
    version: str
    license_identifier: str
    attribution: str
    keys: tuple[str, ...]
    session_id: str | None


def public_rights_error(policy: Any) -> str | None:
    """Return a blocker unless the registry grants unconditional public-demo use."""
    if policy is None:
        return "rights evidence is unavailable"
    status = getattr(policy.status, "value", policy.status)
    redistribution = getattr(policy.redistribution, "value", policy.redistribution)
    identifier = policy.identifier
    if status != "declared" or not identifier:
        return "rights are unclear"
    if policy.local_only or redistribution == "prohibited":
        return "source is local-only or redistribution is prohibited"
    if policy.noncommercial_only:
        return "license is noncommercial-only"
    if identifier not in PUBLIC_LICENSES:
        return f"license {identifier!r} is not on the public seed allowlist"
    return None


def load_public_seed(path: Path | None = None) -> tuple[SeedDataset, ...]:
    """Validate every pinned dataset and source key against the registry authority."""
    target = path or repository_root() / ALLOWLIST_PATH
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentError(f"cannot read public seed allowlist: {target}") from exc
    if payload.get("schema_version") != 1 or not isinstance(payload.get("datasets"), list):
        raise DeploymentError("public seed allowlist has an unsupported schema")

    registry = validate_registry()
    seeds: list[SeedDataset] = []
    seen_ids: set[str] = set()
    for item in payload["datasets"]:
        dataset_id = item.get("dataset_id", "")
        if not dataset_id or dataset_id in seen_ids:
            raise DeploymentError(
                f"public seed contains a missing or duplicate dataset id: {dataset_id!r}"
            )
        seen_ids.add(dataset_id)
        source = registry.source(dataset_id)
        blocked = public_rights_error(source.license)
        if blocked:
            raise DeploymentError(f"{dataset_id}: {blocked}; refusing public seed")
        license_identifier = source.license.identifier
        if license_identifier is None:
            raise DeploymentError(f"{dataset_id}: source has no license identifier")
        if item.get("license_identifier") != license_identifier:
            raise DeploymentError(f"{dataset_id}: allowlist license differs from registry")
        version_id = item.get("version", "")
        version = source.version(version_id)
        keys = item.get("keys")
        if not isinstance(keys, list) or not keys or any(not isinstance(key, str) for key in keys):
            raise DeploymentError(f"{dataset_id}/{version_id}: source keys must be explicit")
        if len(set(keys)) != len(keys):
            raise DeploymentError(f"{dataset_id}/{version_id}: source keys contain duplicates")
        declared = {file.key for file in version.retrieval.files}
        unknown = sorted(set(keys) - declared)
        if unknown:
            raise DeploymentError(
                f"{dataset_id}/{version_id}: keys are absent from the registry: {unknown}"
            )
        attribution = item.get("attribution", "").strip()
        if source.license.attribution_required and not attribution:
            raise DeploymentError(f"{dataset_id}: required attribution is missing")
        seeds.append(
            SeedDataset(
                dataset_id=dataset_id,
                version=version_id,
                license_identifier=license_identifier,
                attribution=attribution,
                keys=tuple(keys),
                session_id=item.get("session_id"),
            )
        )
    if not seeds:
        raise DeploymentError("public seed allowlist is empty")
    return tuple(seeds)
