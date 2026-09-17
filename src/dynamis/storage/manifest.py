"""Bronze retrieval manifests.

The registry states what a dataset *should* contain; the Bronze manifest records
what was actually retrieved, with upstream checksums and the locally computed
SHA-256 of every immutable native file. Nothing about a downloaded file is
believed without a checksum.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import AwareDatetime, Field

from dynamis.config import Settings
from dynamis.contracts.base import MD5, SHA1, SHA256, Contract, DatasetId, Identifier
from dynamis.contracts.domain import DatasetSource, DatasetVersion
from dynamis.contracts.enums import RetrievalStatus
from dynamis.storage.atomic import atomic_write_text, sha256_file
from dynamis.storage.paths import bronze_manifest_path, bronze_native_path

BRONZE_MANIFEST_SCHEMA_VERSION = "1"


class BronzeFile(Contract):
    key: str = Field(min_length=1)
    size_bytes: int | None = Field(default=None, gt=0)
    upstream_md5: MD5 | None = None
    upstream_sha1: SHA1 | None = None
    upstream_sha256: SHA256 | None = None
    local_sha256: SHA256 | None = None
    retrieved_at: AwareDatetime | None = None


class BronzeManifest(Contract):
    schema_version: str = BRONZE_MANIFEST_SCHEMA_VERSION
    dataset_id: DatasetId
    version: Identifier
    upstream_url: str = Field(min_length=1)
    retrieved_at: AwareDatetime | None = None
    files: tuple[BronzeFile, ...] = ()


@dataclass(frozen=True, slots=True)
class ManifestVerification:
    """Outcome of re-hashing a retrieved Bronze payload against its manifest."""

    ok: bool
    verified: tuple[str, ...]
    missing: tuple[str, ...]
    mismatched: tuple[str, ...]
    size_mismatched: tuple[str, ...]

    @property
    def problems(self) -> tuple[str, ...]:
        return (*self.missing, *self.mismatched, *self.size_mismatched)


def manifest_from_registry(source: DatasetSource, version: DatasetVersion) -> BronzeManifest:
    """Project a registry entry into an (unfetched) Bronze manifest expectation."""
    files = tuple(
        BronzeFile(
            key=item.key,
            size_bytes=item.size_bytes,
            upstream_md5=None if item.md5 == "unknown" else item.md5,
            upstream_sha1=None if item.sha1 == "unknown" else item.sha1,
            upstream_sha256=None if item.sha256 == "unknown" else item.sha256,
            local_sha256=item.local_sha256,
            retrieved_at=item.retrieved_at,
        )
        for item in version.retrieval.files
    )
    if version.retrieval.status is RetrievalStatus.FETCHED:
        retrieved_at = version.retrieval.retrieved_at
    else:
        retrieved_at = None
    return BronzeManifest(
        dataset_id=source.dataset_id,
        version=version.version,
        upstream_url=str(version.upstream_url),
        retrieved_at=retrieved_at,
        files=files,
    )


def write_bronze_manifest(settings: Settings, manifest: BronzeManifest) -> Path:
    path = bronze_manifest_path(settings, dataset_id=manifest.dataset_id, version=manifest.version)
    payload = json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True)
    return atomic_write_text(path, payload + "\n")


def read_bronze_manifest(settings: Settings, *, dataset_id: str, version: str) -> BronzeManifest:
    path = bronze_manifest_path(settings, dataset_id=dataset_id, version=version)
    return BronzeManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))


def verify_manifest(settings: Settings, manifest: BronzeManifest) -> ManifestVerification:
    """Re-hash every retrieved file against the manifest and report mismatches."""
    verified: list[str] = []
    missing: list[str] = []
    mismatched: list[str] = []
    size_mismatched: list[str] = []
    for item in manifest.files:
        path = bronze_native_path(
            settings,
            dataset_id=manifest.dataset_id,
            version=manifest.version,
            key=item.key,
        )
        if not path.is_file():
            if item.local_sha256 is not None:
                missing.append(item.key)
            continue
        if item.local_sha256 is not None:
            if sha256_file(path) != item.local_sha256:
                mismatched.append(item.key)
            else:
                verified.append(item.key)
        if item.size_bytes is not None and path.stat().st_size != item.size_bytes:
            size_mismatched.append(item.key)
    return ManifestVerification(
        ok=not (missing or mismatched or size_mismatched),
        verified=tuple(verified),
        missing=tuple(missing),
        mismatched=tuple(mismatched),
        size_mismatched=tuple(size_mismatched),
    )


def record_retrieval(
    settings: Settings,
    manifest: BronzeManifest,
    *,
    retrieved_at: datetime,
    only_keys: tuple[str, ...] = (),
) -> BronzeManifest:
    """Stamp locally computed checksums for present files into a new manifest.

    Only files that actually exist under Bronze are stamped, so a manifest never
    claims a checksum for a file that was not retrieved.
    """
    if retrieved_at.tzinfo is None:
        raise ValueError("retrieved_at must be timezone-aware")
    updated: list[BronzeFile] = []
    for item in manifest.files:
        if only_keys and item.key not in only_keys:
            updated.append(item)
            continue
        path = bronze_native_path(
            settings,
            dataset_id=manifest.dataset_id,
            version=manifest.version,
            key=item.key,
        )
        if not path.is_file():
            updated.append(item)
            continue
        updated.append(
            item.model_copy(
                update={
                    "local_sha256": sha256_file(path),
                    "size_bytes": path.stat().st_size,
                    "retrieved_at": retrieved_at,
                }
            )
        )
    return manifest.model_copy(update={"files": tuple(updated), "retrieved_at": retrieved_at})
