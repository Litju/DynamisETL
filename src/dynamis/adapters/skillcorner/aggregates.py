"""Canonicalize the pinned SkillCorner A-League player-season aggregates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv

from dynamis.adapters.skillcorner.catalog import (
    DATASET_ID,
    NAMESPACE,
    load_corpus_manifest,
    skillcorner_aggregate_catalog_id,
)
from dynamis.config import ConfigurationError, Settings
from dynamis.config import settings as resolve_settings
from dynamis.contracts import AlgorithmKind, AlgorithmSpec
from dynamis.contracts.sports import (
    DataGrain,
    DataGrainKind,
    SportsEntityKind,
    canonical_sports_id,
    validate_grain_rows,
)
from dynamis.pipeline.ingest import assert_local_only_boundary
from dynamis.pipeline.persist import (
    persist_bronze_state,
    persist_skillcorner_aggregate_artifacts,
    persist_skillcorner_corpus,
    persist_source,
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

AGGREGATE_VERSION = "1"
GRAIN = DataGrain(
    kind=DataGrainKind.PLAYER_SEASON,
    axes=("subject", "team", "competition_edition", "position_group"),
)


def _canonicalize(path: Path, *, family: str, expected_rows: int) -> pa.Table:
    table = pacsv.read_csv(path, convert_options=pacsv.ConvertOptions(strings_can_be_null=True))
    required = {"player_id", "team_id", "season_id", "position_group"}
    missing = required - set(table.column_names)
    if missing:
        raise ValueError(f"{family} aggregate lacks required provider columns: {sorted(missing)}")
    if table.num_rows != expected_rows:
        raise ValueError(f"{family} aggregate has {table.num_rows} rows; expected {expected_rows}")

    player_ids = pc.cast(table["player_id"], pa.string()).to_pylist()
    team_ids = pc.cast(table["team_id"], pa.string()).to_pylist()
    if any(value is None for value in (*player_ids, *team_ids)):
        raise ValueError(f"{family} aggregate contains a null player or team identity")
    table = table.append_column("provider_player_id", pa.array(player_ids, type=pa.string()))
    team_index = table.schema.get_field_index("team_id")
    table = table.set_column(
        team_index,
        "provider_team_id",
        pa.array(team_ids, type=pa.string()),
    )
    canonical_subjects = [f"{DATASET_ID}/{player_id}" for player_id in player_ids]
    canonical_teams = [
        canonical_sports_id(NAMESPACE, SportsEntityKind.TEAM, team_id) for team_id in team_ids
    ]
    canonical_edition = canonical_sports_id(NAMESPACE, SportsEntityKind.EDITION, "870")

    if "competition_edition_id" in table.column_names:
        edition_index = table.schema.get_field_index("competition_edition_id")
        provider_editions = pc.cast(table["competition_edition_id"], pa.string())
        table = table.set_column(
            edition_index, "provider_competition_edition_id", provider_editions
        )
    else:
        table = table.append_column(
            "provider_competition_edition_id",
            pa.array(["870"] * table.num_rows, type=pa.string()),
        )
    table = table.append_column("subject_id", pa.array(canonical_subjects, type=pa.string()))
    table = table.append_column("team_id", pa.array(canonical_teams, type=pa.string()))
    if "competition_edition_id" in table.column_names:
        table = table.set_column(
            table.schema.get_field_index("competition_edition_id"),
            "competition_edition_id",
            pa.array([canonical_edition] * table.num_rows, type=pa.string()),
        )
    else:
        table = table.append_column(
            "competition_edition_id",
            pa.array([canonical_edition] * table.num_rows, type=pa.string()),
        )
    table = table.append_column("provider_season_id", pc.cast(table["season_id"], pa.string()))
    validate_grain_rows(
        GRAIN,
        [
            dict(zip(GRAIN.axes, row.values(), strict=True))
            for row in table.select(
                ["subject_id", "team_id", "competition_edition_id", "position_group"]
            ).to_pylist()
        ],
    )
    return table.sort_by(
        [
            ("subject_id", "ascending"),
            ("team_id", "ascending"),
            ("competition_edition_id", "ascending"),
            ("position_group", "ascending"),
        ]
    )


def ingest_skillcorner_aggregates(
    resolved: Settings | None = None,
    *,
    engine=None,
) -> dict[str, Any]:
    """Ingest and reconcile all three pinned A-League season aggregate files."""
    config = resolved or resolve_settings()
    corpus = load_corpus_manifest()
    registry = validate_registry()
    source = source_by_id(registry, DATASET_ID)
    revision = corpus["upstream"]["revision"]
    source.version(revision)
    manifest = read_bronze_manifest(config, dataset_id=DATASET_ID, version=revision)
    bronze = {file.key: file for file in manifest.files}
    assert_local_only_boundary(config, DATASET_ID)
    ensure_dataset_layout(config)

    artifacts: list[dict[str, Any]] = []
    reconciliations: list[StreamReconciliation] = []
    input_checksums: dict[str, str] = {}
    for aggregate in sorted(corpus["aggregates"], key=lambda item: item["family"]):
        family = aggregate["family"]
        key = aggregate["asset"]["key"]
        file = bronze.get(key)
        if file is None or file.local_sha256 is None:
            raise ValueError(f"aggregate source {key} has not been acquired into Bronze")
        path = bronze_native_path(config, dataset_id=DATASET_ID, version=revision, key=key)
        if not path.is_file() or sha256_file(path) != file.local_sha256:
            raise ValueError(f"aggregate Bronze checksum does not match its manifest: {key}")
        if aggregate["asset"].get("size_bytes") != path.stat().st_size:
            raise ValueError(f"aggregate Bronze size does not match the pinned source: {key}")
        table = _canonicalize(
            path, family=family, expected_rows=aggregate["source_population_rows"]
        )
        canonical_edition = canonical_sports_id(
            NAMESPACE, SportsEntityKind.EDITION, str(aggregate["competition_edition_id"])
        )
        metadata = dict(table.schema.metadata or {})
        metadata.update(
            {
                b"dynamis.source_dataset_id": DATASET_ID.encode(),
                b"dynamis.source_revision": revision.encode(),
                b"dynamis.source_file_key": key.encode(),
                b"dynamis.aggregate_family": family.encode(),
            }
        )
        table = table.replace_schema_metadata(metadata)
        target = (
            config.dataset_root
            / "silver"
            / f"dataset_id={DATASET_ID}"
            / "sport=football"
            / f"competition_edition_id={canonical_edition}"
            / "provider_family=skillcorner"
            / f"aggregate_family={family}.parquet"
        )
        written = write_parquet_atomic(table, target, relative_to=config.dataset_root, grain=GRAIN)
        entry_id = skillcorner_aggregate_catalog_id(canonical_edition, family)
        artifacts.append(
            {
                "artifact_id": f"skillcorner-season-{canonical_edition}-{family}",
                "relative_path": written.relative_path,
                "checksum_sha256": written.checksum_sha256,
                "byte_size": written.byte_size,
                "row_count": written.row_count,
                "data_grain_kind": GRAIN.kind.value,
                "data_grain_axes": list(GRAIN.axes),
                "artifact_metadata": {
                    "dataset_id": DATASET_ID,
                    "competition_edition_id": canonical_edition,
                    "provider_competition_edition_id": str(aggregate["competition_edition_id"]),
                    "aggregate_family": family,
                    "source_catalog_entry_id": entry_id,
                    "source_file_key": key,
                    "source_revision": revision,
                    "source_checksum_sha256": file.local_sha256,
                    "source_population_rows": aggregate["source_population_rows"],
                    "provider_ids_preserved": [
                        "player_id",
                        "provider_player_id",
                        "provider_team_id",
                        "provider_competition_edition_id",
                        "season_id",
                        "provider_season_id",
                    ],
                },
            }
        )
        input_checksums[key] = file.local_sha256
        reconciliations.append(
            StreamReconciliation(
                stream_id=f"season-{family}",
                modality="season_aggregate",
                subject_id=None,
                trial_id=None,
                source_records=aggregate["source_population_rows"],
                canonical_rows=written.row_count,
                quarantined_rows=0,
                ignored_records=0,
                checks={
                    "provider_family": family,
                    "data_grain_kind": GRAIN.kind.value,
                    "data_grain_axes": list(GRAIN.axes),
                    "distinct_player_count": aggregate["distinct_player_count"],
                    "distinct_team_count": aggregate["distinct_team_count"],
                    "source_checksum_sha256": file.local_sha256,
                    "silver_checksum_sha256": written.checksum_sha256,
                },
            )
        )

    receipt = ReconciliationReceipt(
        dataset_id=DATASET_ID,
        version=revision,
        session_id="season-870",
        source_keys=tuple(sorted(input_checksums)),
        streams=tuple(reconciliations),
        domain={
            "competition": "A-League",
            "competition_edition_id": "870",
            "season": "2024/2025",
            "families": sorted(item["family"] for item in corpus["aggregates"]),
            "position_group_preserved_as_grain_axis": True,
        },
        silver_artifacts=tuple(artifacts),
    )
    assert_reconciled(receipt)
    receipt_path = write_reconciliation_receipt(
        config, receipt, name=f"skillcorner-season-aggregates-{revision[:12]}"
    )

    algorithm = AlgorithmSpec(
        algorithm_id="skillcorner.season_aggregate_canonicalization",
        name="SkillCorner season aggregate canonicalization",
        version=AGGREGATE_VERSION,
        kind=AlgorithmKind.ADAPTER,
        description="Preserves SkillCorner player-season rows and provider identifiers.",
    )
    run_id = f"skillcorner-season-aggregates-{revision[:12]}"
    owns_engine = engine is None
    active = engine or control_plane_engine(config)
    try:
        with active.begin() as connection:
            persist_source(connection, source)
            persist_skillcorner_corpus(connection, source, corpus)
            persist_bronze_state(connection, config, dataset_id=DATASET_ID, version=revision)
            rows_written = persist_skillcorner_aggregate_artifacts(
                connection,
                source=source,
                algorithm=algorithm,
                run_id=run_id,
                source_checksums=input_checksums,
                artifacts=artifacts,
            )
    finally:
        if owns_engine:
            active.dispose()

    return {
        "dataset_id": DATASET_ID,
        "revision": revision,
        "run_id": run_id,
        "reconciliation": receipt.to_dict(),
        "receipt_path": receipt_path,
        "artifacts": artifacts,
        "rows_written": rows_written,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dynamis-ingest-skillcorner-aggregates",
        description="Canonicalize and reconcile SkillCorner A-League season aggregates.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        result = ingest_skillcorner_aggregates()
    except (ConfigurationError, OSError, ValueError, AssertionError) as exc:
        print(f"dynamis-ingest-skillcorner-aggregates: {exc}", file=sys.stderr)
        return 2
    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            f"reconciled {result['reconciliation']['canonical_rows']} SkillCorner season rows; "
            f"receipt: {result['receipt_path']}"
        )
    return 0
