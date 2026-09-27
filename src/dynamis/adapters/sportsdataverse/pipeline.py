"""``dynamis-sdv-ingest``: canonicalize the pinned SportsDataverse slice end to end.

Bronze (verified by local SHA-256) → V4 semantics + clock mappings + grain-aware
Silver artifacts → PostgreSQL control plane, with a reconciliation receipt. The
whole release catalog is also registered, metadata-only, as UPSTREAM_AVAILABLE.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from typing import Any

from dynamis.adapters.sportsdataverse import ingest
from dynamis.adapters.sportsdataverse.releases import (
    DATASET_ID,
    DOWNLOAD_URL,
    PinnedAsset,
    load_snapshot,
    pinned_assets,
)
from dynamis.adapters.sportsdataverse.taxonomy import LEAGUES as TAXONOMY_LEAGUES
from dynamis.config import ConfigurationError, Settings
from dynamis.config import settings as resolve_settings
from dynamis.contracts import AlgorithmKind, AlgorithmSpec
from dynamis.contracts.sports import SportsEntityKind, canonical_sports_id
from dynamis.pipeline.ingest import assert_local_only_boundary
from dynamis.pipeline.persist import (
    persist_bronze_state,
    persist_source,
    persist_sportsdataverse,
)
from dynamis.pipeline.reconcile import (
    ReconciliationReceipt,
    StreamReconciliation,
    assert_reconciled,
    write_reconciliation_receipt,
)
from dynamis.registry import source_by_id, validate_registry
from dynamis.storage.atomic import sha256_file
from dynamis.storage.control_plane import control_plane_engine
from dynamis.storage.manifest import read_bronze_manifest
from dynamis.storage.parquet import write_parquet_atomic
from dynamis.storage.paths import bronze_native_path, ensure_dataset_layout

ALGORITHM_ID = "sportsdataverse.release_canonicalization"
ROW_GROUP_ROWS = 16_384
ARTIFACT_TYPES = {
    "pbp": "play_by_play",
    "schedule": "game_summary",
    "player_game": "player_game",
    "skater_game": "player_game",
    "goalie_game": "player_game",
    "team_game": "team_game",
}
SPORT_NAMES = {
    "basketball": "Basketball",
    "ice_hockey": "Ice hockey",
    "american_football": "American football",
    "baseball": "Baseball",
}
FAMILY_CAPABILITIES = {
    "play_by_play": ["PLAY_BY_PLAY"],
    "player_game": ["BOX_SCORE"],
    "team_game": ["BOX_SCORE"],
    "player_season": ["SEASON_AGGREGATE"],
    "team_season": ["SEASON_AGGREGATE"],
    "shots": ["EVENTS"],
}


def _catalog_rows(
    snapshot: dict[str, Any],
    *,
    rights: dict[str, Any],
    pinned_keys: set[str],
    editions: dict[tuple[str, int], str],
    competitions: dict[str, str],
) -> list[dict[str, Any]]:
    """Metadata-only entries for every season-sliced Parquet release asset."""
    discovered = datetime.fromisoformat(snapshot["discovered_at"])
    rows: list[dict[str, Any]] = []
    for family in snapshot["families"]:
        tag = family["tag"]
        league = family.get("league_id")
        for name, season, size, asset_id in family["parquet_assets"]:
            key = f"{tag}/{name}"
            if key in pinned_keys:
                continue
            identity = f"{DATASET_ID}:release:{key}"
            rows.append(
                {
                    "entry_id": "src-"
                    + hashlib.md5(identity.encode(), usedforsecurity=False).hexdigest(),
                    "provider": "SportsDataverse",
                    "dataset": DATASET_ID,
                    "registry_dataset_id": None,
                    "registry_version": None,
                    "registry_file_key": None,
                    "external_id": f"release:{key}",
                    "object_kind": "release_asset",
                    "sport_id": family.get("sport_id"),
                    "competition_id": competitions.get(league) if league else None,
                    "competition_edition_id": editions.get((league, int(season)))
                    if league
                    else None,
                    "teams": [],
                    "upstream_url": DOWNLOAD_URL.format(tag=tag, name=name),
                    "upstream_revision": f"asset:{asset_id}",
                    "asset_identity": f"{key}#{asset_id}",
                    "expected_size_bytes": int(size),
                    "rights": rights,
                    "provider_metadata": {
                        "release_tag": tag,
                        "family_kind": family["family_kind"],
                        "grain": family["grain"],
                        "league_id": league,
                        "competition_name": family.get("competition_name"),
                        "season": int(season),
                        "taxonomy_rule": family["rule"],
                        "snapshot": snapshot["snapshot"],
                    },
                    "upstream_capabilities": FAMILY_CAPABILITIES.get(family["family_kind"], []),
                    "discovered_at": discovered,
                    "availability_state": "UPSTREAM_AVAILABLE",
                    "failure_stage": None,
                    "failure_evidence": None,
                }
            )
    return rows


def _verify_bronze(
    config: Settings, *, version: str, pins: tuple[PinnedAsset, ...]
) -> dict[str, str]:
    manifest = read_bronze_manifest(config, dataset_id=DATASET_ID, version=version)
    by_key = {item.key: item for item in manifest.files}
    checksums: dict[str, str] = {}
    for pin in pins:
        entry = by_key.get(pin.key)
        if entry is None or entry.local_sha256 is None:
            raise ValueError(f"{pin.key} has not been acquired; run dynamis-fetch sportsdataverse")
        path = bronze_native_path(config, dataset_id=DATASET_ID, version=version, key=pin.key)
        if not path.is_file() or sha256_file(path) != entry.local_sha256:
            raise ValueError(f"{pin.key}: Bronze bytes do not match the verified manifest")
        if path.stat().st_size != pin.size_bytes:
            raise ValueError(f"{pin.key}: Bronze size differs from the pinned release asset")
        checksums[pin.key] = entry.local_sha256
    return checksums


def ingest_sportsdataverse(resolved: Settings | None = None, *, engine=None) -> dict[str, Any]:
    config = resolved or resolve_settings()
    snapshot = load_snapshot()
    version = snapshot["snapshot"]
    registry = validate_registry()
    source = source_by_id(registry, DATASET_ID)
    source.version(version)
    assert_local_only_boundary(config, DATASET_ID)
    ensure_dataset_layout(config)
    pins = pinned_assets(snapshot)
    checksums = _verify_bronze(config, version=version, pins=pins)

    def read(pin: PinnedAsset):
        path = bronze_native_path(config, dataset_id=DATASET_ID, version=version, key=pin.key)
        return ingest.read_bronze_table(str(path))

    results = ingest.canonicalize(read, snapshot=snapshot)

    semantic: dict[str, list[dict[str, Any]]] = {
        "sport": [
            {"sport_id": sport, "code": sport, "display_name": name}
            for sport, name in sorted(SPORT_NAMES.items())
            if sport in {league.sport_id for league in TAXONOMY_LEAGUES}
        ],
        "competition": [],
        "competition_edition": [],
        "team": [],
        "contest": [],
        "contest_team": [],
        "contest_period": [],
        "provider_identity_crosswalk": [],
    }
    clock_rows: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    streams: list[StreamReconciliation] = []
    editions: dict[tuple[str, int], str] = {}
    competitions: dict[str, str] = {}
    pinned_catalog: dict[str, dict[str, Any]] = {}
    league_summaries: dict[str, Any] = {}
    for result, chosen in results:
        spec = result.spec
        for name, rows in result.semantic.items():
            if name != "sport":
                semantic[name].extend(rows)
        competition_id = canonical_sports_id(
            spec.namespace, SportsEntityKind.COMPETITION, spec.league_id
        )
        competitions[spec.league_id] = competition_id
        editions[(spec.league_id, result.season)] = result.edition_id
        for pin in chosen.values():
            pinned_catalog[pin.key] = {
                "sport_id": spec.sport_id,
                "competition_id": competition_id,
                "competition_edition_id": result.edition_id,
            }
        clock_rows.extend(mapping.model_dump(mode="json") for mapping in result.clock_mappings)
        league_summaries[spec.league_id] = {
            "edition_id": result.edition_id,
            "edition_label": result.edition_label,
            "season": result.season,
            "contests": len(result.semantic["contest"]),
            "teams": len(result.semantic["team"]),
            "reconciliation": result.reconciliation,
        }
        for family, (table, grain) in result.artifacts.items():
            source_family = "pbp" if family == "pbp" else family
            pin = chosen[source_family]
            target = (
                config.dataset_root
                / "silver"
                / f"dataset_id={DATASET_ID}"
                / f"sport={spec.sport_id}"
                / f"competition_edition_id={result.edition_id}"
                / f"provider_family={spec.namespace}"
                / f"family={family}.parquet"
            )
            written = write_parquet_atomic(
                table,
                target,
                relative_to=config.dataset_root,
                grain=grain,
                row_group_size=ROW_GROUP_ROWS,
            )
            artifact_id = f"sdv-{spec.league_id}-{result.season}-{family}"
            metadata: dict[str, Any] = {
                "dataset_id": DATASET_ID,
                "league_id": spec.league_id,
                "sport_id": spec.sport_id,
                "provider_namespace": spec.namespace,
                "competition_id": competition_id,
                "competition_edition_id": result.edition_id,
                "edition_label": result.edition_label,
                "family": family,
                "source_file_key": pin.key,
                "source_checksum_sha256": checksums[pin.key],
                "release_tag": pin.tag,
                "release_asset_id": pin.asset_id,
                "release_asset_updated_at": pin.updated_at,
                "release_freshness": dict(pin.freshness),
                "snapshot": version,
                "schema_fingerprint": result.reconciliation["schema_fingerprints"][source_family],
                "preserved_source_prefix": "src_",
            }
            if family == "pbp":
                metadata["attributes_schema_id"] = spec.attributes_schema_id
                metadata["attributes_schema_version"] = ingest.INGEST_VERSION
                metadata["clock_mapping_ids"] = sorted(
                    mapping.mapping_id for mapping in result.clock_mappings
                )
                metadata["score_reconciliation"] = {
                    key: value
                    for key, value in result.reconciliation.items()
                    if key not in {"source_rows", "silver_rows", "schema_fingerprints"}
                }
            artifacts.append(
                {
                    "artifact_id": artifact_id,
                    "artifact_type": ARTIFACT_TYPES[family],
                    "relative_path": written.relative_path,
                    "checksum_sha256": written.checksum_sha256,
                    "byte_size": written.byte_size,
                    "row_count": written.row_count,
                    "data_grain_kind": grain.kind.value,
                    "data_grain_axes": list(grain.axes),
                    "artifact_metadata": metadata,
                }
            )
            source_rows = result.reconciliation["source_rows"][source_family]
            nulls = ingest.null_identity_counts(table, grain)
            timed = (
                [value for value in table["canonical_time_ns"].to_pylist() if value is not None]
                if family == "pbp"
                else []
            )
            streams.append(
                StreamReconciliation(
                    stream_id=artifact_id,
                    modality="event" if family == "pbp" else "game_record",
                    subject_id=None,
                    trial_id=None,
                    source_records=source_rows,
                    canonical_rows=written.row_count,
                    quarantined_rows=0,
                    ignored_records=source_rows - written.row_count,
                    ignored_reasons=(
                        {
                            (
                                "schedule_entry_without_team_identity"
                                if family == "schedule"
                                else "game_outside_scheduled_contest_set"
                            ): source_rows - written.row_count
                        }
                        if source_rows != written.row_count
                        else {}
                    ),
                    canonical_time_min_ns=min(timed) if timed else None,
                    canonical_time_max_ns=max(timed) if timed else None,
                    null_counts=nulls,
                    checks={
                        "data_grain_kind": grain.kind.value,
                        "silver_checksum_sha256": written.checksum_sha256,
                        "source_checksum_sha256": checksums[pin.key],
                    },
                )
            )

    receipt = ReconciliationReceipt(
        dataset_id=DATASET_ID,
        version=version,
        session_id="release-slice",
        source_keys=tuple(sorted(checksums)),
        streams=tuple(streams),
        domain={"leagues": league_summaries},
        silver_artifacts=tuple(artifacts),
    )
    assert_reconciled(receipt)
    receipt_path = write_reconciliation_receipt(config, receipt, name=f"sportsdataverse-{version}")
    catalog_rows = _catalog_rows(
        snapshot,
        rights=source.license.model_dump(mode="json"),
        pinned_keys={pin.key for pin in pins},
        editions=editions,
        competitions=competitions,
    )
    algorithm = AlgorithmSpec(
        algorithm_id=ALGORITHM_ID,
        name="SportsDataverse release canonicalization",
        version=ingest.INGEST_VERSION,
        kind=AlgorithmKind.ADAPTER,
        description=(
            "Maps pinned NBA/NHL release assets to V4 semantics, the cross-sport event "
            "envelope and PLAYER_GAME/TEAM_GAME/GAME_SUMMARY grains; preserves every "
            "source column."
        ),
    )
    run_id = f"sportsdataverse-{version}"
    owns_engine = engine is None
    active = engine or control_plane_engine(config)
    try:
        with active.begin() as connection:
            persist_source(connection, source)
            persist_bronze_state(connection, config, dataset_id=DATASET_ID, version=version)
            rows_written = persist_sportsdataverse(
                connection,
                source=source,
                version=version,
                semantic=semantic,
                clock_mappings=clock_rows,
                algorithm=algorithm,
                run_id=run_id,
                source_checksums=checksums,
                artifacts=artifacts,
                catalog_rows=catalog_rows,
                pinned_catalog=pinned_catalog,
            )
    finally:
        if owns_engine:
            active.dispose()
    return {
        "dataset_id": DATASET_ID,
        "version": version,
        "run_id": run_id,
        "receipt_path": receipt_path,
        "leagues": league_summaries,
        "artifacts": [
            {key: item[key] for key in ("artifact_id", "row_count", "byte_size", "relative_path")}
            for item in artifacts
        ],
        "catalog_entries": len(catalog_rows),
        "rows_written": rows_written,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dynamis-sdv-ingest",
        description="Canonicalize the pinned SportsDataverse NBA/NHL slices into V4 grains.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        result = ingest_sportsdataverse()
    except (ConfigurationError, OSError, ValueError, AssertionError) as exc:
        print(f"dynamis-sdv-ingest: {exc}", file=sys.stderr)
        return 2
    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        for league, summary in result["leagues"].items():
            recon = summary["reconciliation"]
            print(
                f"{league} {summary['edition_label']}: {summary['contests']} contests, "
                f"{summary['teams']} teams; final scores: {recon['final_score_matches']} exact, "
                f"{recon['shootout_decided']} shootout-decided, "
                f"{recon['provider_score_discrepancies']} provider discrepancies "
                f"of {recon['completed_games_with_pbp']}"
            )
        print(f"{result['catalog_entries']} release assets catalogued")
        print(f"receipt: {result['receipt_path']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
