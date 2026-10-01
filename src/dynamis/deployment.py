"""Rights-checked deployment seed authority."""

from __future__ import annotations

import hashlib
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
    session_id: str


@dataclass(frozen=True, slots=True)
class DemoResource:
    dataset_id: str
    session_id: str
    worlds: tuple[str, ...]


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
        session_id = item.get("session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            raise DeploymentError(f"{dataset_id}: a single sample session_id is required")
        seeds.append(
            SeedDataset(
                dataset_id=dataset_id,
                version=version_id,
                license_identifier=license_identifier,
                attribution=attribution,
                keys=tuple(keys),
                session_id=session_id,
            )
        )
    if not seeds:
        raise DeploymentError("public seed allowlist is empty")
    return tuple(seeds)


def load_public_demo_resources(path: Path | None = None) -> tuple[DemoResource, ...]:
    """Return the pinned sessions whose complete artifacts may enter public Blob."""
    target = path or repository_root() / ALLOWLIST_PATH
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentError(f"cannot read public seed allowlist: {target}") from exc
    resources = payload.get("demo_resources")
    if not isinstance(resources, list) or not resources:
        raise DeploymentError("public seed must declare at least one curated demo resource")
    sessions = {seed.dataset_id: seed.session_id for seed in load_public_seed(target)}
    seen: set[tuple[str, str]] = set()
    seen_datasets: set[str] = set()
    result: list[DemoResource] = []
    for item in resources:
        dataset_id = item.get("dataset_id", "")
        session_id = item.get("session_id", "")
        worlds = item.get("worlds")
        identity = (dataset_id, session_id)
        if not dataset_id or not session_id or identity in seen:
            raise DeploymentError(f"demo resource is missing or duplicated: {identity!r}")
        if dataset_id in seen_datasets:
            raise DeploymentError(f"demo dataset {dataset_id!r} must have exactly one sample")
        if dataset_id not in sessions or sessions[dataset_id] != session_id:
            raise DeploymentError(
                f"demo resource is outside its pinned source session: {identity!r}"
            )
        if (
            not isinstance(worlds, list)
            or not worlds
            or any(not isinstance(x, str) for x in worlds)
        ):
            raise DeploymentError(f"demo resource {identity!r} must name its Worlds")
        if len(set(worlds)) != len(worlds):
            raise DeploymentError(f"demo resource {identity!r} contains duplicate Worlds")
        seen.add(identity)
        seen_datasets.add(dataset_id)
        result.append(DemoResource(dataset_id, session_id, tuple(sorted(worlds))))
    if seen_datasets != set(sessions):
        missing = sorted(set(sessions) - seen_datasets)
        raise DeploymentError("every public dataset must have one demo resource: " + ", ".join(missing))
    return tuple(sorted(result, key=lambda item: (item.dataset_id, item.session_id)))


def rights_allowlist_sha256(path: Path | None = None) -> str:
    target = path or repository_root() / ALLOWLIST_PATH
    try:
        return hashlib.sha256(target.read_bytes()).hexdigest()
    except OSError as exc:
        raise DeploymentError(f"cannot hash public seed allowlist: {target}") from exc
