"""Dagster assets for the RES-98 laboratory provider slices.

Lineage (minimal, no processors or gold marts):

    white_cmj_bronze -> white_cmj_discovery -> white_cmj_silver
                                             -> white_cmj_reconciliation

    gymaware_landmine_bronze -> gymaware_landmine_discovery
                             -> gymaware_landmine_canonical
                             -> gymaware_landmine_reconciliation

Importing these definitions never fetches anything: every asset requires an
already-verified immutable Bronze file, and the real acquisition step is the
explicit ``dynamis-fetch`` command. Bronze paths are always reported relative to
the configured dataset root, never as machine paths.

This module intentionally avoids ``from __future__ import annotations``:
Dagster resolves ``Config`` parameter annotations at decoration time and needs
the real class objects, not PEP 563 strings.
"""

from dagster import (
    AssetCheckResult,
    AssetCheckSeverity,
    AssetKey,
    Config,
    asset,
    asset_check,
)

from dynamis.adapters.gymaware_landmine.authorities import GYMAWARE_DATASET_ID
from dynamis.adapters.white_cmj.authorities import WHITE_DATASET_ID
from dynamis.config import settings
from dynamis.pipeline.ingest import (
    ingest_gymaware_landmine,
    ingest_white_cmj,
    write_discovery_receipts,
)
from dynamis.storage.manifest import read_bronze_manifest, verify_manifest
from dynamis.storage.paths import bronze_native_path

WHITE_KEY = "cmj_dataset_both.npz"
GYMAWARE_KEY = "LP_data.zip"
GYMAWARE_VERSION = "v1"
WHITE_VERSION = "v1"


class WhiteSliceConfig(Config):
    """Explicit verified White CMJ slice; nothing is fetched implicitly."""

    version: str = WHITE_VERSION
    key: str = WHITE_KEY


class GymAwareSliceConfig(Config):
    """Explicit verified GymAware landmine slice; nothing is fetched implicitly."""

    version: str = GYMAWARE_VERSION
    key: str = GYMAWARE_KEY


def _verify_bronze(dataset_id: str, version: str, key: str) -> dict:
    resolved = settings()
    manifest = read_bronze_manifest(resolved, dataset_id=dataset_id, version=version)
    verification = verify_manifest(resolved, manifest)
    if not verification.ok:
        raise ValueError(
            f"Bronze manifest verification failed for {dataset_id}/{version}: "
            f"missing={list(verification.missing)} mismatched={list(verification.mismatched)} "
            f"size_mismatched={list(verification.size_mismatched)}"
        )
    path = bronze_native_path(resolved, dataset_id=dataset_id, version=version, key=key)
    entry = next((item for item in manifest.files if item.key == key), None)
    if entry is None:
        raise ValueError(f"{dataset_id}/{version} declares no file {key!r}")
    if not path.is_file():
        raise FileNotFoundError(
            f"Bronze file is missing: {dataset_id}/{version}/{key}; run dynamis-fetch"
        )
    return {
        "dataset_id": dataset_id,
        "version": version,
        "key": key,
        "manifest_verified": True,
        "size_bytes": path.stat().st_size,
        "sha256": entry.local_sha256,
    }


def _white_path(version: str, key: str):
    return bronze_native_path(settings(), dataset_id=WHITE_DATASET_ID, version=version, key=key)


def _gymaware_path(version: str, key: str):
    return bronze_native_path(settings(), dataset_id=GYMAWARE_DATASET_ID, version=version, key=key)


@asset(group_name="lab_sources", compute_kind="filesystem")
def white_cmj_bronze(config: WhiteSliceConfig) -> dict:
    """Verified immutable Bronze ``cmj_dataset_both.npz`` release."""
    return _verify_bronze(WHITE_DATASET_ID, config.version, config.key)


@asset(group_name="lab_sources", compute_kind="python")
def white_cmj_discovery(white_cmj_bronze: dict, config: WhiteSliceConfig) -> dict:
    """Structural NPZ discovery receipt (members, shapes, dtypes, timing)."""
    resolved = settings()
    npz_path = _white_path(config.version, white_cmj_bronze["key"])
    receipt = write_discovery_receipts(
        resolved,
        dataset_id=WHITE_DATASET_ID,
        version=config.version,
        npz_path=npz_path,
        name="white-cmj-release-npz",
    )
    from dynamis.adapters.white_cmj.discovery import discover_white_cmj_file

    discovery = discover_white_cmj_file(npz_path).to_dict()
    return {
        "dataset_id": WHITE_DATASET_ID,
        "receipt_path": receipt,
        "trial_count": discovery["structure"]["trial_dimension"],
        "subject_count": discovery["structure"]["subject_count_present"],
        "condition_counts": discovery["structure"]["condition_counts"],
        "acc_sampling_rate_hz": discovery["structure"]["acc_sampling_rate_hz"],
        "grf_sampling_rate_hz": discovery["structure"]["grf_sampling_rate_hz"],
        "acc_non_finite": discovery["structure"]["acc_non_finite_values"],
        "grf_non_finite": discovery["structure"]["grf_non_finite_values"],
    }


@asset(group_name="lab_sources", compute_kind="python")
def white_cmj_silver(
    white_cmj_bronze: dict, white_cmj_discovery: dict, config: WhiteSliceConfig
) -> dict:
    """Per-trial canonical IMU + force Silver streams and reconciliation."""
    resolved = settings()
    npz_path = _white_path(config.version, white_cmj_bronze["key"])
    result = ingest_white_cmj(resolved, npz_path=npz_path, version=config.version)
    if not result.reconciliation.all_balanced:
        raise ValueError(f"{WHITE_DATASET_ID}: reconciliation is not balanced")
    return _descriptor(result)


@asset(group_name="lab_sources", compute_kind="python")
def white_cmj_reconciliation(white_cmj_silver: dict) -> dict:
    """Projection of the White reconciliation without re-materializing Silver."""
    return {
        "dataset_id": WHITE_DATASET_ID,
        "source_rows": white_cmj_silver["source_rows"],
        "canonical_rows": white_cmj_silver["canonical_rows"],
        "quarantined_rows": white_cmj_silver["quarantined_rows"],
        "balanced": white_cmj_silver["balanced"],
        "streams": len(white_cmj_silver["streams"]),
        "receipt_path": white_cmj_silver["receipt_path"],
    }


@asset(group_name="lab_sources", compute_kind="filesystem")
def gymaware_landmine_bronze(config: GymAwareSliceConfig) -> dict:
    """Verified immutable Bronze ``LP_data.zip`` archive."""
    return _verify_bronze(GYMAWARE_DATASET_ID, config.version, config.key)


@asset(group_name="lab_sources", compute_kind="python")
def gymaware_landmine_discovery(
    gymaware_landmine_bronze: dict, config: GymAwareSliceConfig
) -> dict:
    """ZIP central-directory discovery and structured-member evidence."""
    resolved = settings()
    archive_path = _gymaware_path(config.version, gymaware_landmine_bronze["key"])
    receipt = write_discovery_receipts(
        resolved,
        dataset_id=GYMAWARE_DATASET_ID,
        version=config.version,
        archive_path=archive_path,
        name="gymaware-landmine-release-zip",
    )
    from dynamis.adapters.gymaware_landmine.discovery import discover_gymaware_landmine

    discovery = discover_gymaware_landmine(archive_path)
    return {
        "dataset_id": GYMAWARE_DATASET_ID,
        "receipt_path": receipt,
        "member_count": len(discovery.inspection.members),
        "structured_member_count": len(discovery.structured_member_hashes),
        "gymaware_sets": len(discovery.gymaware_sets),
        "gymaware_rep_rows": discovery.gymaware_rep_rows,
        "vision_populated_values": discovery.vision.populated_value_count,
        "dense_lpt_stream_present": False,
    }


@asset(group_name="lab_sources", compute_kind="python")
def gymaware_landmine_canonical(
    gymaware_landmine_bronze: dict,
    gymaware_landmine_discovery: dict,
    config: GymAwareSliceConfig,
) -> dict:
    """Source-derived trial metrics; no dense LPT stream is fabricated."""
    resolved = settings()
    archive_path = _gymaware_path(config.version, gymaware_landmine_bronze["key"])
    result = ingest_gymaware_landmine(resolved, zip_path=archive_path, version=config.version)
    if not result.reconciliation.all_balanced:
        raise ValueError(f"{GYMAWARE_DATASET_ID}: reconciliation is not balanced")
    descriptor = _descriptor(result)
    descriptor["source_metric_observations"] = len(result.source_metrics)
    return descriptor


@asset(group_name="lab_sources", compute_kind="python")
def gymaware_landmine_reconciliation(gymaware_landmine_canonical: dict) -> dict:
    """Projection of the GymAware reconciliation without re-importing metrics."""
    return {
        "dataset_id": GYMAWARE_DATASET_ID,
        "streams": [
            {
                "stream_id": stream["stream_id"],
                "source_records": stream["source_records"],
                "canonical_rows": stream["canonical_rows"],
                "quarantined_rows": stream["quarantined_rows"],
                "ignored_records": stream["ignored_records"],
            }
            for stream in gymaware_landmine_canonical["reconciliation_streams"]
        ],
        "balanced": gymaware_landmine_canonical["balanced"],
        "source_metric_observations": gymaware_landmine_canonical["source_metric_observations"],
        "receipt_path": gymaware_landmine_canonical["receipt_path"],
    }


def _descriptor(result) -> dict:
    return {
        "dataset_id": result.dataset_id,
        "version": result.version,
        "session_id": result.session_id,
        "balanced": result.reconciliation.all_balanced,
        "source_rows": result.reconciliation.source_rows,
        "canonical_rows": result.reconciliation.canonical_rows,
        "quarantined_rows": result.reconciliation.quarantined_rows,
        "receipt_path": result.receipt_path,
        "reconciliation_streams": [stream.to_dict() for stream in result.reconciliation.streams],
        "streams": [
            {
                "stream_id": stream.stream_id,
                "modality": stream.modality,
                "relative_path": stream.relative_path,
                "row_count": stream.row_count,
                "byte_size": stream.byte_size,
                "checksum_sha256": stream.checksum_sha256,
                "schema_version": stream.schema_version,
            }
            for stream in result.streams
        ],
        "source_metric_observations": len(result.source_metrics),
    }


@asset_check(
    asset=AssetKey("white_cmj_silver"),
    description="White source samples equal canonical + quarantined samples.",
)
def white_cmj_reconciliation_balances(white_cmj_silver: dict) -> AssetCheckResult:
    return AssetCheckResult(
        passed=bool(white_cmj_silver.get("balanced")),
        severity=AssetCheckSeverity.ERROR,
        metadata={
            "source_rows": white_cmj_silver.get("source_rows"),
            "canonical_rows": white_cmj_silver.get("canonical_rows"),
            "quarantined_rows": white_cmj_silver.get("quarantined_rows"),
        },
    )


@asset_check(
    asset=AssetKey("gymaware_landmine_canonical"),
    description="GymAware sets, rep rows and metric values all reconcile.",
)
def gymaware_landmine_reconciliation_balances(
    gymaware_landmine_canonical: dict,
) -> AssetCheckResult:
    return AssetCheckResult(
        passed=bool(gymaware_landmine_canonical.get("balanced")),
        severity=AssetCheckSeverity.ERROR,
        metadata={
            "source_metric_observations": gymaware_landmine_canonical.get(
                "source_metric_observations"
            ),
            "streams": len(gymaware_landmine_canonical.get("reconciliation_streams", [])),
        },
    )
