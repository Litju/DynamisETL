"""Dagster assets for the RES-97 real provider slices.

Lineage (minimal RES-97 level, no metrics or gold marts):

    womens_j01_bronze -> womens_j01_silver_gnss
    dfl_j03wpy_bronze -> dfl_j03wpy_metadata -> dfl_j03wpy_silver_tracking
                                              -> dfl_j03wpy_silver_events

Acquisition is deliberately absent: importing these definitions never fetches
anything and CI materializes nothing here. The assets verify the immutable
Bronze manifest, then reuse the same deterministic pipeline the
``dynamis-ingest`` CLI runs. Bronze/Silver paths are always reported relative to
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

from dynamis.adapters.sportec_idsse.adapter import IdsseMatchAdapter
from dynamis.adapters.womens_soccer_positioning.authorities import WOMENS_DATASET_ID
from dynamis.config import settings
from dynamis.pipeline.ingest import ingest_dfl_match, ingest_womens_j01
from dynamis.registry import source_by_id, validate_registry
from dynamis.storage.manifest import read_bronze_manifest, verify_manifest
from dynamis.storage.paths import bronze_native_path, tmp_run_dir

WOMENS_KEY = "J01.xlsx"
DFL_MATCH_TOKEN = "J03WPY"
DFL_VERSION = "a715a38dfbaf5f58e431727c2b78d174101a703c"


class WomensSliceConfig(Config):
    """Explicit real-data slice; nothing is fetched implicitly."""

    version: str = "1.0"
    key: str = WOMENS_KEY


class DflSliceConfig(Config):
    version: str = DFL_VERSION
    match: str = DFL_MATCH_TOKEN


def _verify_bronze(dataset_id: str, version: str, keys: tuple[str, ...]) -> dict:
    resolved = settings()
    manifest = read_bronze_manifest(resolved, dataset_id=dataset_id, version=version)
    verification = verify_manifest(resolved, manifest)
    if not verification.ok:
        raise ValueError(
            f"Bronze manifest verification failed for {dataset_id}/{version}: "
            f"missing={list(verification.missing)} mismatched={list(verification.mismatched)} "
            f"size_mismatched={list(verification.size_mismatched)}"
        )
    files = []
    for key in keys:
        path = bronze_native_path(resolved, dataset_id=dataset_id, version=version, key=key)
        entry = next(item for item in manifest.files if item.key == key)
        if not path.is_file():
            raise FileNotFoundError(
                f"Bronze file is missing: {dataset_id}/{version}/{key}; run dynamis-fetch"
            )
        files.append(
            {
                "key": key,
                "size_bytes": path.stat().st_size,
                "sha256": entry.local_sha256,
                "upstream_url": entry.upstream_url,
            }
        )
    return {
        "dataset_id": dataset_id,
        "version": version,
        "manifest_verified": True,
        "files": files,
    }


@asset(group_name="real_sources", compute_kind="filesystem")
def womens_j01_bronze(config: WomensSliceConfig) -> dict:
    """Verified immutable Bronze workbook for the accepted Women's matchday."""
    return _verify_bronze(WOMENS_DATASET_ID, config.version, (config.key,))


@asset(group_name="real_sources", compute_kind="python")
def womens_j01_silver_gnss(womens_j01_bronze: dict, config: WomensSliceConfig) -> dict:
    """Canonical GNSS Silver streams plus reconciliation for ``J01.xlsx``."""
    resolved = settings()
    key = womens_j01_bronze["files"][0]["key"]
    workbook = bronze_native_path(
        resolved,
        dataset_id=WOMENS_DATASET_ID,
        version=config.version,
        key=key,
    )
    result = ingest_womens_j01(
        resolved,
        workbook_path=workbook,
        version=config.version,
        session_id="J01",
    )
    if not result.reconciliation.all_balanced:
        raise ValueError(f"{WOMENS_DATASET_ID}: reconciliation is not balanced")
    return _descriptor(result)


@asset(group_name="real_sources", compute_kind="filesystem")
def dfl_j03wpy_bronze(config: DflSliceConfig) -> dict:
    """Verified immutable Bronze three-file set for the accepted IDSSE match."""
    source = source_by_id(validate_registry(), "dfl-sportec-idsse")
    version = source.version(config.version)
    keys = tuple(item.key for item in version.retrieval.files if config.match in item.key)
    if not keys:
        raise ValueError(f"registry version {config.version} has no file matching {config.match!r}")
    return _verify_bronze("dfl-sportec-idsse", config.version, keys)


@asset(group_name="real_sources", compute_kind="python")
def dfl_j03wpy_metadata(dfl_j03wpy_bronze: dict, config: DflSliceConfig) -> dict:
    """Provider-declared match domain: teams, players, periods, pitch."""
    resolved = settings()
    files = {item["key"]: item for item in dfl_j03wpy_bronze["files"]}
    information = _bronze_path(resolved, config.version, files, "_matchinformation_")
    events = _bronze_path(resolved, config.version, files, "_events_")
    adapter = IdsseMatchAdapter(
        match_information_path=information,
        events_path=events,
        positions_path=information,
        version=config.version,
        spill_dir=tmp_run_dir(resolved, f"res97-{config.match}-metadata"),
    )
    events_summary = adapter.parse_events()
    metadata = adapter.metadata
    return {
        "match_id": metadata.match_id,
        "competition": metadata.competition,
        "season": metadata.season,
        "match_day": metadata.match_day,
        "kickoff_utc": metadata.kickoff_utc.isoformat(),
        "teams": {
            "home": {"team_id": metadata.home_team.team_id, "name": metadata.home_team.name},
            "away": {"team_id": metadata.away_team.team_id, "name": metadata.away_team.name},
        },
        "player_count": metadata.player_count,
        "pitch_size_m": [metadata.pitch_x_m, metadata.pitch_y_m],
        "periods": [period.to_dict() for period in events_summary.periods],
        "event_count": events_summary.canonical_rows,
        "deleted_events": events_summary.deleted_events,
    }


@asset(group_name="real_sources", compute_kind="python")
def dfl_j03wpy_silver_tracking(
    dfl_j03wpy_bronze: dict, dfl_j03wpy_metadata: dict, config: DflSliceConfig
) -> dict:
    """Canonical tracking and event Silver streams for the complete match.

    One ``ingest_dfl_match`` run materializes both modalities; the tracking and
    events assets are projections of that single run, so the events artifact has
    exactly one writer (a second write would replace the file behind the other
    asset's descriptor and re-parse the events XML).
    """
    resolved = settings()
    files = {item["key"]: item for item in dfl_j03wpy_bronze["files"]}
    positions = _bronze_path(resolved, config.version, files, "_positions_")
    events = _bronze_path(resolved, config.version, files, "_events_")
    information = _bronze_path(resolved, config.version, files, "_matchinformation_")
    result = ingest_dfl_match(
        resolved,
        match_information_path=information,
        events_path=events,
        positions_path=positions,
        version=config.version,
        session_id=dfl_j03wpy_metadata["match_id"],
        spill_dir=tmp_run_dir(resolved, f"res97-{config.match}-tracking"),
        row_group_size=1 << 16,
    )
    descriptor = _descriptor(result)
    if not any(stream["modality"] == "tracking" for stream in descriptor["streams"]):
        raise ValueError("tracking ingestion produced no tracking streams")
    return descriptor


@asset(group_name="real_sources", compute_kind="python")
def dfl_j03wpy_silver_events(dfl_j03wpy_silver_tracking: dict, dfl_j03wpy_metadata: dict) -> dict:
    """The event stream materialized by the single tracking/events ingest run."""
    events = next(
        (
            item
            for item in dfl_j03wpy_silver_tracking.get("streams", [])
            if item["stream_id"] == "events"
        ),
        None,
    )
    if events is None:
        raise ValueError("the tracking ingest produced no event stream")
    return {"match_id": dfl_j03wpy_metadata["match_id"], **events}


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
        "streams": [
            {
                "stream_id": stream.stream_id,
                "modality": stream.modality,
                "relative_path": stream.relative_path,
                "row_count": stream.row_count,
                "byte_size": stream.byte_size,
                "checksum_sha256": stream.checksum_sha256,
            }
            for stream in result.streams
        ],
    }


def _bronze_path(resolved, version: str, files: dict, token: str):
    key = next((key for key in files if token in key), None)
    if key is None:
        raise ValueError(f"no selected Bronze file matches {token!r}")
    return bronze_native_path(resolved, dataset_id="dfl-sportec-idsse", version=version, key=key)


@asset_check(
    asset=AssetKey("womens_j01_silver_gnss"),
    description="Women's source rows equal canonical + quarantined rows.",
)
def womens_gnss_reconciliation_balances(womens_j01_silver_gnss: dict) -> AssetCheckResult:
    return AssetCheckResult(
        passed=bool(womens_j01_silver_gnss.get("balanced")),
        severity=AssetCheckSeverity.ERROR,
        metadata={
            "source_rows": womens_j01_silver_gnss.get("source_rows"),
            "canonical_rows": womens_j01_silver_gnss.get("canonical_rows"),
        },
    )


@asset_check(
    asset=AssetKey("dfl_j03wpy_silver_tracking"),
    description="DFL tracking rows equal canonical + quarantined rows.",
)
def dfl_tracking_reconciliation_balances(dfl_j03wpy_silver_tracking: dict) -> AssetCheckResult:
    return AssetCheckResult(
        passed=bool(dfl_j03wpy_silver_tracking.get("balanced")),
        severity=AssetCheckSeverity.ERROR,
        metadata={
            "source_rows": dfl_j03wpy_silver_tracking.get("source_rows"),
            "canonical_rows": dfl_j03wpy_silver_tracking.get("canonical_rows"),
            "streams": len(dfl_j03wpy_silver_tracking.get("streams", [])),
        },
    )
