"""Verified acquisition runner: plan -> Bronze -> manifest -> receipt.

The runner is the only component allowed to write native payloads, and it
enforces the immutability rule: an existing final Bronze file is verified
against the registry expectation and the recorded manifest, never overwritten.
Re-running a completed acquisition is a provenance no-op: the bytes, the local
SHA-256 and the first-entry ``retrieved_at`` stay unchanged while the run is
recorded as a new verification event (``verified_at``).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Collection
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import requests

from dynamis.acquisition.download import (
    USER_AGENT,
    FileDigest,
    digest_file,
    download_verified,
)
from dynamis.acquisition.plan import AcquisitionPlan, PlannedFile
from dynamis.config import Settings
from dynamis.contracts import DatasetRegistry
from dynamis.registry import (
    RegistryError,
    assert_acquisition_acknowledged,
    source_by_id,
    validate_registry,
)
from dynamis.rights import assert_dataset_root_outside_repository
from dynamis.storage.atomic import atomic_write_text
from dynamis.storage.manifest import (
    BronzeManifest,
    manifest_from_registry,
    read_bronze_manifest,
    record_retrieval,
    verify_manifest,
    write_bronze_manifest,
)
from dynamis.storage.paths import (
    bronze_native_path,
    ensure_dataset_layout,
    receipt_path,
    relative_posix,
)

ACTION_DOWNLOADED = "downloaded"
ACTION_ALREADY_PRESENT = "already_present"


class ImmutableArtifactError(RuntimeError):
    """An existing Bronze artifact contradicts its declared identity.

    Immutable evidence is never overwritten; the operator must investigate and,
    if the registry authority itself was wrong, change the registry deliberately.
    """


@dataclass(frozen=True, slots=True)
class FileOutcome:
    key: str
    layer_path: Path
    relative_path: str
    url: str
    size_bytes: int
    sha256: str
    md5: str
    git_blob_sha1: str | None
    action: str
    attempts: int
    #: First entry of these bytes into Bronze (immutable once recorded).
    retrieved_at: datetime | None = None
    #: This run's re-validation of the bytes.
    verified_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AcquisitionReceipt:
    dataset_id: str
    version: str
    selection: str
    license_identifier: str | None
    license_local_only: bool
    attribution_required: bool
    citation: str | None
    #: Earliest first-acquisition instant of the selected file set: the run time
    #: when anything was downloaded, otherwise the original Bronze entry time.
    retrieved_at: datetime
    #: This run's verification instant (advances on every re-run).
    verified_at: datetime
    retrieval_performed: bool
    outcomes: tuple[FileOutcome, ...]
    manifest_path: Path
    manifest_relative_path: str
    manifest_verified: bool

    @property
    def bytes_downloaded(self) -> int:
        return sum(item.size_bytes for item in self.outcomes if item.action == ACTION_DOWNLOADED)

    @property
    def downloaded(self) -> tuple[str, ...]:
        return tuple(item.key for item in self.outcomes if item.action == ACTION_DOWNLOADED)

    @property
    def already_present(self) -> tuple[str, ...]:
        return tuple(item.key for item in self.outcomes if item.action == ACTION_ALREADY_PRESENT)

    def to_dict(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "version": self.version,
            "selection": self.selection,
            "license": {
                "identifier": self.license_identifier,
                "local_only": self.license_local_only,
                "attribution_required": self.attribution_required,
            },
            "citation": self.citation,
            "retrieved_at": self.retrieved_at.isoformat(),
            "verified_at": self.verified_at.isoformat(),
            "retrieval_performed": self.retrieval_performed,
            "bytes_downloaded": self.bytes_downloaded,
            "files": [
                {
                    "key": item.key,
                    "url": item.url,
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                    "md5": item.md5,
                    "git_blob_sha1": item.git_blob_sha1,
                    "action": item.action,
                    "attempts": item.attempts,
                    "retrieved_at": (
                        None if item.retrieved_at is None else item.retrieved_at.isoformat()
                    ),
                    "verified_at": (
                        None if item.verified_at is None else item.verified_at.isoformat()
                    ),
                }
                for item in self.outcomes
            ],
            "manifest": {
                "relative_path": self.manifest_relative_path,
                "verified": self.manifest_verified,
            },
        }

    def describe(self) -> str:
        lines = [
            f"acquired {self.dataset_id}/{self.version}: "
            f"{len(self.outcomes)} file(s), {self.bytes_downloaded} bytes downloaded",
        ]
        for item in self.outcomes:
            lines.append(
                f"  [{item.action}] {item.key}: {item.size_bytes} bytes sha256={item.sha256}"
            )
        lines.append(
            f"  manifest: {self.manifest_relative_path} (verified={self.manifest_verified})"
        )
        return "\n".join(lines)


def _verify_existing(path: Path, item: PlannedFile) -> FileDigest:
    """Verify a present Bronze payload against the planned identity."""
    digest = digest_file(path, git_blob=item.git_blob_sha1 is not None)
    problems: list[str] = []
    if digest.size_bytes != item.size_bytes:
        problems.append(f"size {digest.size_bytes} != {item.size_bytes}")
    if item.upstream_sha256 and digest.sha256 != item.upstream_sha256.lower():
        problems.append(f"sha256 {digest.sha256} != {item.upstream_sha256}")
    if item.upstream_md5 and digest.md5 != item.upstream_md5.lower():
        problems.append(f"md5 {digest.md5} != {item.upstream_md5}")
    if item.git_blob_sha1 and digest.git_blob_sha1 != item.git_blob_sha1.lower():
        problems.append(f"git blob {digest.git_blob_sha1} != {item.git_blob_sha1}")
    if problems:
        raise ImmutableArtifactError(
            f"existing Bronze artifact {path} contradicts its declared identity "
            f"({'; '.join(problems)}); refusing to overwrite immutable evidence"
        )
    return digest


def _load_or_expect(
    settings: Settings, plan: AcquisitionPlan, registry: DatasetRegistry | None
) -> BronzeManifest:
    try:
        return read_bronze_manifest(settings, dataset_id=plan.dataset_id, version=plan.version)
    except FileNotFoundError:
        document = registry if registry is not None else validate_registry()
        source = source_by_id(document, plan.dataset_id)
        return manifest_from_registry(source, source.version(plan.version))


def _stamp_upstream_urls(manifest: BronzeManifest, urls: dict[str, str]) -> BronzeManifest:
    files = tuple(
        item.model_copy(update={"upstream_url": urls[item.key]})
        if item.key in urls and item.upstream_url is None
        else item
        for item in manifest.files
    )
    return manifest.model_copy(update={"files": files})


def acquire(
    settings: Settings,
    plan: AcquisitionPlan,
    *,
    session: requests.Session | None = None,
    registry: DatasetRegistry | None = None,
    allow_insecure: bool = False,
    acknowledgements: Collection[str] = (),
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> AcquisitionReceipt:
    """Fetch every planned file into immutable Bronze and verify the manifest.

    ``acknowledgements`` re-checks the source-specific eligibility gate so a
    programmatic caller cannot bypass the planner; ``allow_insecure`` exists for
    loopback test servers only, and production provider URLs are always required
    to be HTTPS.

    One deterministic run instant is captured up front and reused for every
    file, so a run has a single, reproducible acquisition/verification stamp.
    The existing manifest is loaded (and schema-validated) before any byte is
    promoted, so an unreadable manifest can never leave a freshly downloaded
    immutable file without its manifest update.
    """
    # Rights gate first: raw payloads of a local-only source must never land
    # inside the repository, not even an empty layout directory on an ignored path.
    # The registry that produced the plan is the same one consulted here.
    document = registry if registry is not None else validate_registry()
    try:
        source = source_by_id(document, plan.dataset_id)
    except KeyError as exc:
        raise RegistryError(
            f"registry has no dataset {plan.dataset_id!r}; the plan was not built from "
            "this registry"
        ) from exc
    assert_acquisition_acknowledged(source, acknowledgements)
    assert_dataset_root_outside_repository(source, settings.dataset_root)
    ensure_dataset_layout(settings)
    run_at = now()
    manifest = _load_or_expect(settings, plan, document)
    owns_session = session is None
    http = session if session is not None else requests.Session()
    http.headers.setdefault("User-Agent", USER_AGENT)
    try:
        outcomes: list[FileOutcome] = []
        digests: dict[str, FileDigest] = {}
        for item in plan.files:
            final = bronze_native_path(
                settings,
                dataset_id=plan.dataset_id,
                version=plan.version,
                key=item.key,
            )
            if final.is_file():
                digest = _verify_existing(final, item)
                outcomes.append(
                    FileOutcome(
                        key=item.key,
                        layer_path=final,
                        relative_path=relative_posix(settings.dataset_root, final),
                        url=item.url,
                        size_bytes=digest.size_bytes,
                        sha256=digest.sha256,
                        md5=digest.md5,
                        git_blob_sha1=digest.git_blob_sha1,
                        action=ACTION_ALREADY_PRESENT,
                        attempts=0,
                    )
                )
            else:
                receipt = download_verified(
                    http,
                    item.url,
                    final,
                    key=item.key,
                    expected_size=item.size_bytes,
                    expected_md5=item.upstream_md5,
                    expected_sha1=None,
                    expected_sha256=item.upstream_sha256,
                    expected_git_blob_sha1=item.git_blob_sha1,
                    allow_insecure=allow_insecure,
                    now=lambda: run_at,
                )
                digest = FileDigest(
                    size_bytes=receipt.size_bytes,
                    md5=receipt.md5,
                    sha1=receipt.sha1,
                    sha256=receipt.sha256,
                    git_blob_sha1=receipt.git_blob_sha1,
                )
                outcomes.append(
                    FileOutcome(
                        key=item.key,
                        layer_path=final,
                        relative_path=relative_posix(settings.dataset_root, final),
                        url=item.url,
                        size_bytes=receipt.size_bytes,
                        sha256=receipt.sha256,
                        md5=receipt.md5,
                        git_blob_sha1=receipt.git_blob_sha1,
                        action=ACTION_DOWNLOADED,
                        attempts=receipt.attempts,
                    )
                )
            digests[item.key] = digest
    finally:
        if owns_session:
            http.close()

    manifest = _stamp_upstream_urls(manifest, {item.key: item.url for item in plan.files})
    stamped = record_retrieval(
        settings,
        manifest,
        retrieved_at=run_at,
        verified_at=run_at,
        only_keys=tuple(item.key for item in plan.files),
    )
    # The stamp comes from the verified files on disk; assert the digests the
    # runner itself computed so a race or a rewritable path cannot slip through.
    stamps: dict[str, tuple[datetime | None, datetime | None]] = {}
    for item in stamped.files:
        digest = digests.get(item.key)
        if digest is None:
            continue
        if item.local_sha256 != digest.sha256:
            raise ImmutableArtifactError(
                f"{item.key}: manifest stamp {item.local_sha256} != verified {digest.sha256}"
            )
        if item.size_bytes != digest.size_bytes:
            raise ImmutableArtifactError(
                f"{item.key}: manifest size {item.size_bytes} != verified {digest.size_bytes}"
            )
        stamps[item.key] = (item.retrieved_at, item.verified_at)
    manifest_path = write_bronze_manifest(settings, stamped)
    verification = verify_manifest(settings, stamped)
    if not verification.ok:
        raise ImmutableArtifactError(
            f"Bronze manifest verification failed after acquisition: "
            f"missing={list(verification.missing)} mismatched={list(verification.mismatched)} "
            f"size_mismatched={list(verification.size_mismatched)}"
        )

    final_outcomes = tuple(
        replace(
            item,
            retrieved_at=stamps.get(item.key, (None, None))[0],
            verified_at=stamps.get(item.key, (None, None))[1],
        )
        for item in outcomes
    )
    # Receipt-level acquisition provenance is the earliest first-entry instant
    # of the selected file set (never a manifest-wide value from unrelated keys).
    selection_retrievals = [
        item.retrieved_at for item in final_outcomes if item.retrieved_at is not None
    ]
    receipt = AcquisitionReceipt(
        dataset_id=plan.dataset_id,
        version=plan.version,
        selection=plan.selection,
        license_identifier=plan.license_identifier,
        license_local_only=plan.license_local_only,
        attribution_required=plan.attribution_required,
        citation=plan.citation,
        retrieved_at=min(selection_retrievals) if selection_retrievals else run_at,
        verified_at=run_at,
        retrieval_performed=any(item.action == ACTION_DOWNLOADED for item in final_outcomes),
        outcomes=final_outcomes,
        manifest_path=manifest_path,
        manifest_relative_path=relative_posix(settings.dataset_root, manifest_path),
        manifest_verified=verification.ok,
    )
    receipt_file = receipt_path(
        settings,
        dataset_id=plan.dataset_id,
        kind="acquisition",
        name=plan.version,
    )
    atomic_write_text(
        receipt_file,
        json.dumps(receipt.to_dict(), indent=2, sort_keys=True) + "\n",
    )
    return receipt
