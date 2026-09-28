"""Canonical player-season Shots, Drives and Picks artifacts for SeasonLab."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.csv as pacsv

from dynamis.adapters.skillcorner_basketball import authorities
from dynamis.adapters.skillcorner_basketball.catalog import (
    aggregate_catalog_id,
    edition_id,
    load_corpus_manifest,
    persist_catalog,
)
from dynamis.config import ConfigurationError, Settings
from dynamis.config import settings as resolve_settings
from dynamis.contracts import AlgorithmKind, AlgorithmSpec
from dynamis.contracts.sports import (
    DataGrain,
    DataGrainKind,
    ProviderIdentityCrosswalk,
    SportsEntityKind,
    canonical_sports_id,
    provider_crosswalk,
    provider_crosswalk_id,
)
from dynamis.pipeline.ingest import assert_local_only_boundary
from dynamis.pipeline.persist import (
    PROVIDER_CROSSWALK_TABLE,
    SUBJECT_TABLE,
    TEAM_TABLE,
    _upsert_refresh,
    persist_bronze_state,
    persist_skillcorner_aggregate_artifacts,
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
from dynamis.storage.manifest import read_bronze_manifest, verify_manifest
from dynamis.storage.parquet import write_parquet_atomic
from dynamis.storage.paths import bronze_native_path, ensure_dataset_layout

DATASET_ID = authorities.DATASET_ID
GRAIN = DataGrain(
    kind=DataGrainKind.PLAYER_SEASON,
    axes=("subject", "team", "competition_edition", "position_group"),
)
_SOURCE_ID_COLUMNS = (
    "competition_id",
    "competition_name",
    "season_id",
    "season_name",
    "player_id",
    "player_name",
    "team_id",
    "team_name",
)


def _aliases(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    id_map: dict[str, str] = {}
    name_map: dict[str, str] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"player_id", "canonical_player_id", "canonical_player_name"}
        if not reader.fieldnames or not required <= set(reader.fieldnames):
            raise ValueError(f"player alias file lacks fields {sorted(required)}")
        for row in reader:
            source_id = str(row["player_id"]).strip()
            canonical_id = str(row["canonical_player_id"]).strip()
            if not source_id or not canonical_id:
                raise ValueError("player alias file contains an empty provider id")
            id_map[source_id] = canonical_id
            name_map[canonical_id] = str(row["canonical_player_name"]).strip()
    return id_map, name_map


def _aggregation_weight(family: str, column: str) -> str | tuple[str, ...] | None:
    """Return only denominator columns documented by the provider schema."""
    if family == "shots":
        exact = {
            "avg_attempts_distance": "attempts",
            "fg_percentage": "attempts",
            "efg_percentage": "attempts",
            "fouled_fg_percentage": "fouled_fg_attempts",
            "two_pt_percentage": "two_attempts",
            "three_pt_percentage": "three_attempts",
            "ft_percentage": "ft_attempts",
            "points_per_shot": "attempts",
            "three_pa_rate": "attempts",
        }
        if column in exact:
            return exact[column]
        for suffix, weight in (
            ("two_fg_percentage", "two_attempts"),
            ("three_fg_percentage", "three_attempts"),
            ("efg_percentage", "attempts"),
            ("fg_percentage", "attempts"),
            ("points_per_shot", "attempts"),
        ):
            if column.endswith(suffix):
                return f"{column.removesuffix(suffix)}{weight}"
        if column.endswith("_attempt_rate"):
            return "attempts"
        return None
    if family == "drives":
        if column == "points_per_shot_in_drive":
            return "fga_in_drive"
        if column.endswith("_rate") or column == "points_per_drive":
            return "total_drives"
        return None
    if family == "picks":
        role = column.split("_", 1)[0]
        for points, attempts in (("_fg2_pct", "2pt"), ("_fg3_pct", "3pt")):
            if points in column:
                suffix = column.split(points, 1)[1]
                return (
                    f"{role}_score_{attempts}{suffix}",
                    f"{role}_miss_{attempts}{suffix}",
                )
        if column.endswith("_points_per_shot_in_pick"):
            return f"{role}_fga_in_pick"
        if "_ppp" in column:
            bucket = column.split("_ppp", 1)[1]
            if bucket.startswith("_vs_"):
                return f"{role}_picks_vs_{bucket.removeprefix('_vs_')}"
            if bucket.startswith("_at_"):
                return f"{role}_picks_at_{bucket.removeprefix('_at_')}"
            return f"{role}_total_picks"
        if "_vs_" in column:
            return f"{role}_picks_vs_{column.split('_vs_', 1)[1]}"
        if "_at_" in column:
            return f"{role}_picks_at_{column.split('_at_', 1)[1]}"
        if column.endswith(("_rate", "_pct")) or "_rate_" in column:
            return f"{role}_total_picks"
        return None
    return None


def _is_derived(column: str) -> bool:
    return (
        column.endswith(("_pct", "_ppp"))
        or any(token in column for token in ("_pct_", "_ppp_"))
        or any(token in column for token in ("percentage", "_rate", "_per_", "avg_"))
    )


def _canonicalize(path: Path, *, family: str, aliases: dict[str, str], names: dict[str, str]):
    table = pacsv.read_csv(
        path,
        convert_options=pacsv.ConvertOptions(strings_can_be_null=True),
    )
    required = set(_SOURCE_ID_COLUMNS) | {"games_played"}
    missing = required - set(table.column_names)
    if missing:
        raise ValueError(f"{family} aggregate lacks columns {sorted(missing)}")
    source_rows = table.to_pylist()
    grouped_rows: dict[tuple[str, str], list[int]] = {}
    canonical_names: dict[tuple[str, str], str] = {}
    aliases_seen: set[str] = set()
    ignored_total_rows = 0
    canonical_exclusions: list[dict[str, Any]] = []
    for index, row in enumerate(source_rows):
        raw_team = row.get("team_id")
        team_name = str(row.get("team_name") or "").strip()
        if team_name.lower() == "total":
            if raw_team is not None and str(raw_team).strip():
                raise ValueError(f"{family} aggregate total row {index} unexpectedly has a team_id")
            ignored_total_rows += 1
            canonical_exclusions.append(
                {
                    "source_row_number": index + 2,
                    "provider_player_id": str(row.get("player_id") or "") or None,
                    "provider_team_id": None,
                    "provider_team_name": team_name,
                    "reason": "provider season-total row duplicates traded-player team rows",
                }
            )
            continue
        if raw_team is None or not str(raw_team).strip():
            raise ValueError(
                f"{family} aggregate row {index} lacks a team_id and is not a total row"
            )
        raw_player = str(row.get("player_id") or "").strip()
        raw_team_id = str(raw_team).strip()
        if not raw_player or not raw_team_id or row.get("games_played") is None:
            raise ValueError(f"{family} aggregate row {index} lacks player, team or games_played")
        canonical_player = aliases.get(raw_player, raw_player)
        key = (canonical_player, raw_team_id)
        grouped_rows.setdefault(key, []).append(index)
        display_name = names.get(canonical_player) or str(row["player_name"])
        if canonical_names.setdefault(key, display_name) != display_name:
            raise ValueError(f"{family} aliases disagree on canonical name for {key}")
        if raw_player != canonical_player:
            aliases_seen.add(raw_player)
    grouped_keys = sorted(grouped_rows)
    first_source_rows = [source_rows[grouped_rows[key][0]] for key in grouped_keys]
    canonical_players = [player for player, _team in grouped_keys]
    player_names = [canonical_names[key] for key in grouped_keys]
    subject_ids = [
        canonical_sports_id(authorities.NAMESPACE, SportsEntityKind.SUBJECT, player)
        for player in canonical_players
    ]
    provider_team_ids = [team for _player, team in grouped_keys]
    canonical_teams = [
        canonical_sports_id(authorities.NAMESPACE, SportsEntityKind.TEAM, team)
        for team in provider_team_ids
    ]
    provider_player_ids = [
        ",".join(sorted({str(source_rows[index]["player_id"]) for index in grouped_rows[key]}))
        for key in grouped_keys
    ]
    provider_canonical_player_ids = list(canonical_players)
    provider_competition_ids = [str(row["competition_id"]) for row in first_source_rows]
    provider_season_ids = [str(row["season_id"]) for row in first_source_rows]
    metric_columns = [column for column in table.column_names if column not in _SOURCE_ID_COLUMNS]
    unsupported_derived_fields: set[str] = set()
    metric_arrays: list[tuple[str, pa.Array]] = []
    for column in metric_columns:
        source_type = table.schema.field(column).type
        values_by_group: list[Any] = []
        weight = _aggregation_weight(family, column)
        weight_columns = (weight,) if isinstance(weight, str) else weight or ()
        for key in grouped_keys:
            indices = grouped_rows[key]
            values = [source_rows[index].get(column) for index in indices]
            populated = [value for value in values if value is not None]
            if len(indices) == 1:
                values_by_group.append(values[0])
            elif not populated:
                values_by_group.append(None)
            elif pa.types.is_integer(source_type) or pa.types.is_floating(source_type):
                if not _is_derived(column):
                    values_by_group.append(sum(populated))
                    continue
                if not weight_columns or any(
                    weight_column not in table.column_names for weight_column in weight_columns
                ):
                    unsupported_derived_fields.add(column)
                    values_by_group.append(None)
                    continue
                weighted: list[tuple[float, float]] = []
                invalid_denominator = False
                for index, value in zip(indices, values, strict=True):
                    counts = [source_rows[index].get(name) for name in weight_columns]
                    if any(count is None for count in counts):
                        if value is not None or any(count is not None for count in counts):
                            invalid_denominator = True
                            break
                        continue
                    denominator_for_row = sum(float(count) for count in counts)
                    if not math.isfinite(denominator_for_row) or denominator_for_row < 0:
                        invalid_denominator = True
                        break
                    if value is None:
                        if denominator_for_row > 0:
                            invalid_denominator = True
                            break
                        continue
                    if denominator_for_row == 0 and float(value) == 0:
                        continue
                    if denominator_for_row <= 0:
                        invalid_denominator = True
                        break
                    weighted.append((float(value), denominator_for_row))
                denominator = sum(weight for _value, weight in weighted)
                if denominator > 0 and not invalid_denominator:
                    values_by_group.append(
                        sum(value * weight for value, weight in weighted) / denominator
                    )
                else:
                    unsupported_derived_fields.add(column)
                    values_by_group.append(None)
            elif len({str(value) for value in populated}) == 1:
                values_by_group.append(populated[0])
            else:
                values_by_group.append(None)
        metric_arrays.append((column, pa.array(values_by_group, type=source_type)))
    reduced = pa.Table.from_arrays(
        [array for _name, array in metric_arrays],
        names=[name for name, _array in metric_arrays],
    )
    canonical_edition = edition_id()
    output_columns: list[tuple[str, pa.Array]] = [
        ("subject_id", pa.array(subject_ids, type=pa.string())),
        ("player_name", pa.array(player_names, type=pa.string())),
        ("player_short_name", pa.array(player_names, type=pa.string())),
        ("team_id", pa.array(canonical_teams, type=pa.string())),
        (
            "team_name",
            pa.array(
                [str(row["team_name"]) for row in first_source_rows],
                type=pa.string(),
            ),
        ),
        ("position_group", pa.array(["not_reported"] * len(grouped_keys), type=pa.string())),
        (
            "competition_edition_id",
            pa.array([canonical_edition] * len(grouped_keys), type=pa.string()),
        ),
        ("provider_player_id", pa.array(provider_player_ids, type=pa.string())),
        (
            "provider_canonical_player_id",
            pa.array(provider_canonical_player_ids, type=pa.string()),
        ),
        ("provider_team_id", pa.array(provider_team_ids, type=pa.string())),
        ("provider_competition_id", pa.array(provider_competition_ids, type=pa.string())),
        ("provider_season_id", pa.array(provider_season_ids, type=pa.string())),
        (
            "competition_name",
            pa.array(
                [str(row["competition_name"]) for row in first_source_rows],
                type=pa.string(),
            ),
        ),
        (
            "season_name",
            pa.array(
                [str(row["season_name"]) for row in first_source_rows],
                type=pa.string(),
            ),
        ),
    ]
    for name, column in output_columns:
        reduced = reduced.append_column(name, column)
    grain_rows = [
        {
            "subject": subject,
            "team": team,
            "competition_edition": canonical_edition,
            "position_group": "not_reported",
        }
        for subject, team in zip(subject_ids, canonical_teams, strict=True)
    ]
    from dynamis.contracts.sports import validate_grain_rows

    validate_grain_rows(GRAIN, grain_rows)
    reduced = reduced.sort_by(
        [
            ("subject_id", "ascending"),
            ("team_id", "ascending"),
            ("competition_edition_id", "ascending"),
            ("position_group", "ascending"),
        ]
    )
    metadata = dict(reduced.schema.metadata or {})
    metadata.update(
        {
            b"dynamis.aggregate_family": family.encode(),
            b"dynamis.position_group_semantics": b"not_reported_by_provider",
        }
    )
    reduced = reduced.replace_schema_metadata(metadata)
    provider_mappings = {
        (
            str(source_rows[index]["player_id"]),
            canonical_players[group_index],
            player_names[group_index],
        )
        for group_index, key in enumerate(grouped_keys)
        for index in grouped_rows[key]
    }
    team_mappings = {
        (
            key[1],
            str(source_rows[grouped_rows[key][0]]["team_name"]),
        )
        for key in grouped_keys
    }
    return reduced, {
        "source_rows": table.num_rows,
        "canonical_rows": reduced.num_rows,
        "ignored_total_rows": ignored_total_rows,
        "canonical_exclusions": canonical_exclusions,
        "alias_ids": sorted(aliases_seen),
        "unsupported_derived_fields": sorted(unsupported_derived_fields),
        "distinct_canonical_players": len(set(canonical_players)),
        "distinct_teams": len(set(canonical_teams)),
        "provider_player_ids": provider_player_ids,
        "provider_canonical_player_ids": provider_canonical_player_ids,
        "player_names": player_names,
        "provider_team_ids": provider_team_ids,
        "provider_mappings": [
            {"provider_id": raw, "canonical_id": canonical, "display_name": name}
            for raw, canonical, name in sorted(provider_mappings)
        ],
        "provider_team_mappings": [
            {"provider_id": provider_id, "display_name": name}
            for provider_id, name in sorted(team_mappings)
        ],
    }


def _persist_player_identities(
    connection,
    metadata_by_family: list[dict[str, Any]],
    corpus: dict[str, Any],
) -> dict[str, int]:
    subjects: set[str] = set()
    by_provider_id: dict[str, tuple[str, str]] = {}
    by_provider_team: dict[str, str] = {}
    jersey_by_provider_id: dict[str, str] = {}
    for item in corpus["matches"]:
        for team_key in ("homeTeam", "awayTeam"):
            for player in item["detail"][team_key].get("players", []):
                jersey_by_provider_id[str(player["playerId"])] = str(player["jersey"])
    for metadata in metadata_by_family:
        for mapping in metadata["provider_mappings"]:
            raw_id = mapping["provider_id"]
            canonical_id = mapping["canonical_id"]
            name = mapping["display_name"]
            subjects.add(
                canonical_sports_id(
                    authorities.NAMESPACE,
                    SportsEntityKind.SUBJECT,
                    canonical_id,
                )
            )
            prior = by_provider_id.get(raw_id)
            if prior and prior[0] != canonical_id:
                raise ValueError(f"provider player {raw_id} maps to conflicting canonical ids")
            by_provider_id[raw_id] = (canonical_id, name)
        for team in metadata["provider_team_mappings"]:
            by_provider_team.setdefault(team["provider_id"], team["display_name"])
    subject_rows = [
        {"dataset_id": DATASET_ID, "subject_id": subject_id, "sex": "unspecified"}
        for subject_id in sorted(subjects)
    ]
    crosswalk_rows: list[dict[str, Any]] = []
    for raw_id, (canonical_id, name) in sorted(by_provider_id.items()):
        item = ProviderIdentityCrosswalk(
            provider_namespace=authorities.NAMESPACE,
            entity_kind=SportsEntityKind.SUBJECT,
            provider_entity_id=raw_id,
            canonical_entity_id=canonical_sports_id(
                authorities.NAMESPACE, SportsEntityKind.SUBJECT, canonical_id
            ),
            source_authority="SkillCorner player_id_aliases.csv and season aggregate CSVs",
            metadata={
                "display_name": name,
                "canonical_provider_player_id": canonical_id,
                **(
                    {"jersey": jersey_by_provider_id[raw_id]}
                    if raw_id in jersey_by_provider_id
                    else {}
                ),
            },
        )
        crosswalk_rows.append(
            {
                "crosswalk_id": provider_crosswalk_id(item),
                "provider_namespace": item.provider_namespace,
                "entity_kind": item.entity_kind.value,
                "provider_entity_id": item.provider_entity_id,
                "canonical_entity_id": item.canonical_entity_id,
                "valid_from": item.valid_from,
                "valid_to": item.valid_to,
                "source_authority": item.source_authority,
                "metadata_json": item.metadata,
            }
        )
    team_rows = []
    for provider_team_id, display_name in sorted(by_provider_team.items()):
        canonical_team_id = canonical_sports_id(
            authorities.NAMESPACE, SportsEntityKind.TEAM, provider_team_id
        )
        team_rows.append(
            {
                "team_id": canonical_team_id,
                "sport_id": "basketball",
                "display_name": display_name,
            }
        )
        item = provider_crosswalk(
            provider_namespace=authorities.NAMESPACE,
            entity_kind=SportsEntityKind.TEAM,
            provider_entity_id=provider_team_id,
            source_authority="SkillCorner basketball season aggregate CSVs",
            metadata={"display_name": display_name},
        )
        crosswalk_rows.append(
            {
                "crosswalk_id": provider_crosswalk_id(item),
                "provider_namespace": item.provider_namespace,
                "entity_kind": item.entity_kind.value,
                "provider_entity_id": item.provider_entity_id,
                "canonical_entity_id": item.canonical_entity_id,
                "valid_from": item.valid_from,
                "valid_to": item.valid_to,
                "source_authority": item.source_authority,
                "metadata_json": item.metadata,
            }
        )
    return {
        "subject": _upsert_refresh(connection, SUBJECT_TABLE, subject_rows),
        "team": _upsert_refresh(connection, TEAM_TABLE, team_rows),
        "provider_identity_crosswalk": _upsert_refresh(
            connection, PROVIDER_CROSSWALK_TABLE, crosswalk_rows
        ),
    }


def ingest_skillcorner_basketball_aggregates(
    resolved: Settings | None = None,
    *,
    engine=None,
) -> dict[str, Any]:
    config = resolved or resolve_settings()
    corpus = load_corpus_manifest()
    registry = validate_registry()
    source = source_by_id(registry, DATASET_ID)
    revision = str(corpus["upstream"]["revision"])
    source.version(revision)
    manifest = read_bronze_manifest(config, dataset_id=DATASET_ID, version=revision)
    verification = verify_manifest(config, manifest)
    if not verification.ok:
        raise ValueError(f"basketball Bronze manifest failed: {verification.problems}")
    bronze = {item.key: item for item in manifest.files}
    assert_local_only_boundary(config, DATASET_ID)
    ensure_dataset_layout(config)
    aliases_key = "data/player_id_aliases.csv"
    aliases_file = bronze.get(aliases_key)
    if aliases_file is None or aliases_file.local_sha256 is None:
        raise ValueError(f"alias metadata has not been acquired: {aliases_key}")
    aliases_path = bronze_native_path(
        config, dataset_id=DATASET_ID, version=revision, key=aliases_key
    )
    if sha256_file(aliases_path) != aliases_file.local_sha256:
        raise ValueError("basketball player alias checksum does not match Bronze")
    alias_map, canonical_names = _aliases(aliases_path)
    canonical_edition = edition_id(corpus)
    artifacts: list[dict[str, Any]] = []
    reconciliations: list[StreamReconciliation] = []
    metadata_by_family: list[dict[str, Any]] = []
    source_checksums: dict[str, str] = {aliases_key: aliases_file.local_sha256}
    for aggregate in sorted(corpus["aggregates"], key=lambda item: str(item["family"])):
        family = str(aggregate["family"])
        key = str(aggregate["asset"]["key"])
        acquired = bronze.get(key)
        if acquired is None or acquired.local_sha256 is None:
            raise ValueError(f"{family} aggregate has not been acquired: {key}")
        path = bronze_native_path(config, dataset_id=DATASET_ID, version=revision, key=key)
        if sha256_file(path) != acquired.local_sha256:
            raise ValueError(f"{family} aggregate checksum does not match Bronze")
        if acquired.size_bytes != path.stat().st_size:
            raise ValueError(f"{family} aggregate size does not match Bronze")
        table, info = _canonicalize(path, family=family, aliases=alias_map, names=canonical_names)
        metadata_by_family.append(info)
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
            / "sport=basketball"
            / f"competition_edition_id={canonical_edition}"
            / "provider_family=skillcorner"
            / f"aggregate_family={family}.parquet"
        )
        written = write_parquet_atomic(table, target, relative_to=config.dataset_root, grain=GRAIN)
        source_entry_id = aggregate_catalog_id(canonical_edition, family)
        artifact_metadata = {
            "dataset_id": DATASET_ID,
            "competition_edition_id": canonical_edition,
            "provider_competition_edition_id": str(
                corpus["upstream"]["competition_edition"]["provider_id"]
            ),
            "aggregate_family": family,
            "source_catalog_entry_id": source_entry_id,
            "source_file_key": key,
            "source_revision": revision,
            "source_checksum_sha256": acquired.local_sha256,
            "alias_file_key": aliases_key,
            "source_population_rows": info["source_rows"],
            "canonical_rows": info["canonical_rows"],
            "distinct_canonical_player_count": info["distinct_canonical_players"],
            "distinct_team_count": info["distinct_teams"],
            "ignored_total_rows": info["ignored_total_rows"],
            "canonical_exclusions": info["canonical_exclusions"],
            "alias_rows_consolidated": (
                info["source_rows"] - info["canonical_rows"] - info["ignored_total_rows"]
            ),
            "unsupported_derived_fields": info["unsupported_derived_fields"],
            "provider_ids_preserved": [
                "provider_player_id",
                "provider_canonical_player_id",
                "provider_team_id",
                "provider_competition_id",
                "provider_season_id",
            ],
            "position_group": "not_reported",
            "position_group_is_source_data": False,
        }
        artifacts.append(
            {
                "artifact_id": f"skillcorner-basketball-season-{canonical_edition}-{family}",
                "relative_path": written.relative_path,
                "checksum_sha256": written.checksum_sha256,
                "byte_size": written.byte_size,
                "row_count": written.row_count,
                "data_grain_kind": GRAIN.kind.value,
                "data_grain_axes": list(GRAIN.axes),
                "artifact_metadata": artifact_metadata,
            }
        )
        source_checksums[key] = acquired.local_sha256
        reconciliations.append(
            StreamReconciliation(
                stream_id=f"season-{family}",
                modality="season_aggregate",
                subject_id=None,
                trial_id=None,
                source_records=info["source_rows"],
                canonical_rows=info["canonical_rows"],
                quarantined_rows=0,
                ignored_records=info["source_rows"] - info["canonical_rows"],
                ignored_reasons={
                    "provider season-total convenience rows without a team": (
                        info["ignored_total_rows"]
                    ),
                    "alias rows consolidated into canonical player-team rows": (
                        info["source_rows"] - info["canonical_rows"] - info["ignored_total_rows"]
                    ),
                },
                checks={
                    "provider_family": family,
                    "data_grain_kind": GRAIN.kind.value,
                    "data_grain_axes": list(GRAIN.axes),
                    "distinct_canonical_player_count": info["distinct_canonical_players"],
                    "distinct_team_count": info["distinct_teams"],
                    "canonical_edition_id": canonical_edition,
                    "unsupported_derived_fields": info["unsupported_derived_fields"],
                    "canonical_exclusions": info["canonical_exclusions"],
                    "source_checksum_sha256": acquired.local_sha256,
                    "silver_checksum_sha256": written.checksum_sha256,
                    "player_alias_file": aliases_key,
                },
            )
        )

    receipt = ReconciliationReceipt(
        dataset_id=DATASET_ID,
        version=revision,
        session_id="season-211",
        source_keys=tuple(sorted(source_checksums)),
        streams=tuple(reconciliations),
        domain={
            "competition": "Liga ACB",
            "competition_edition_id": canonical_edition,
            "season": str(corpus["upstream"]["season"]["label"]),
            "families": [item["family"] for item in corpus["aggregates"]],
            "position_group": "not_reported by provider; one explicit all-position group",
            "season_total_rows": "excluded from canonical player x team grain",
        },
        silver_artifacts=tuple(artifacts),
        notes=(
            "Shots, Drives and Picks are provider season aggregates, not recomputed from "
            "the 10 sample games.",
            "Player aliases are resolved through the pinned player_id_aliases.csv; both "
            "provider ids are retained.",
            "Season-total convenience rows with no team are excluded to keep PLAYER_SEASON "
            "grain non-null and avoid double counting.",
        ),
    )
    assert_reconciled(receipt)
    receipt_path = write_reconciliation_receipt(
        config, receipt, name=f"skillcorner-basketball-season-{revision[:12]}"
    )
    algorithm = AlgorithmSpec(
        algorithm_id="skillcorner_basketball.season_aggregate_canonicalization",
        name="SkillCorner basketball season aggregate canonicalization",
        version="1",
        kind=AlgorithmKind.ADAPTER,
        description=(
            "Preserves ACB Shots, Drives and Picks season aggregates and resolves source "
            "player aliases; "
            "and exposes a non-null player-team-season grain."
        ),
    )
    run_id = f"skillcorner-basketball-season-{revision[:12]}"
    owns_engine = engine is None
    active = engine or control_plane_engine(config)
    try:
        with active.begin() as connection:
            persist_source(connection, source)
            persist_catalog(connection, source, corpus)
            persist_bronze_state(connection, config, dataset_id=DATASET_ID, version=revision)
            identity_rows = _persist_player_identities(connection, metadata_by_family, corpus)
            artifact_rows = persist_skillcorner_aggregate_artifacts(
                connection,
                source=source,
                algorithm=algorithm,
                run_id=run_id,
                source_checksums=source_checksums,
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
        "rows_written": {**identity_rows, **artifact_rows},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dynamis-ingest-skillcorner-basketball-aggregates",
        description="Canonicalize ACB Shots, Drives and Picks season aggregates.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        result = ingest_skillcorner_basketball_aggregates()
    except (ConfigurationError, OSError, ValueError, AssertionError) as exc:
        print(f"dynamis-ingest-skillcorner-basketball-aggregates: {exc}", file=sys.stderr)
        return 2
    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        rows = sum(item["row_count"] for item in result["artifacts"])
        print(
            f"reconciled {rows} ACB Shots/Drives/Picks season rows; "
            f"receipt: {result['receipt_path']}"
        )
    return 0


__all__ = ["GRAIN", "ingest_skillcorner_basketball_aggregates", "main"]
