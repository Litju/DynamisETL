from __future__ import annotations

import gzip
import json
import math
from pathlib import Path

import pytest

from dynamis.adapters.skillcorner_basketball import authorities
from dynamis.adapters.skillcorner_basketball.aggregates import (
    _canonicalize,
    _persist_player_identities,
)
from dynamis.adapters.skillcorner_basketball.catalog import (
    _preserve_materialized_contest_metadata,
    build_catalog_entries,
    build_game_domain,
    contest_catalog_id,
    load_corpus_manifest,
)
from dynamis.adapters.skillcorner_basketball.events import build_event_table
from dynamis.adapters.skillcorner_basketball.tracking import (
    BasketballTrackingCanonicalizer,
    write_frame_clock,
)
from dynamis.contracts.sports import SportsEntityKind, canonical_sports_id
from dynamis.registry import source_by_id, validate_registry


def _fixture_frames(path: Path) -> None:
    frames = (
        {
            "frameIdx": 10,
            "wallClock": 400,
            "gameClock": 600.0,
            "gameClockStopped": False,
            "period": 1,
            "shotClock": 24.0,
            "homePlayers": [{"playerId": 1, "xyz": [1.0, 2.0, 0.0], "isDetected": 1}],
            "awayPlayers": [],
            "ball": {"xyz": [3.0, 4.0, 5.0], "isDetected": 1.0},
        },
        {
            "frameIdx": 11,
            "wallClock": 440,
            "gameClock": 599.96,
            "gameClockStopped": False,
            "period": 1,
            "shotClock": 23.96,
            "homePlayers": [],
            "awayPlayers": [],
            "ball": {"isDetected": 0},
        },
        {
            "frameIdx": 12,
            "wallClock": 480,
            "gameClock": 599.92,
            "gameClockStopped": False,
            "period": 1,
            "shotClock": 23.92,
            "homePlayers": [],
            "awayPlayers": [{"playerId": 2, "xyz": [-1.0, -2.0, 0.0], "isDetected": 0}],
            "ball": {"xyz": [4.0, 5.0, 6.0]},
        },
    )
    with gzip.open(path, "wt", encoding="utf-8") as target:
        for frame in frames:
            target.write(json.dumps(frame) + "\n")


def test_acb_sample_catalog_is_metadata_first() -> None:
    corpus = load_corpus_manifest()
    assert len(corpus["matches"]) == 10
    assert len(corpus["files"]) == 35
    assert corpus["coverage"]["sample_game_team_count"] == 17
    assert corpus["coverage"]["season_aggregate_team_count"] == 18
    assert (
        sum(
            file["size_bytes"]
            for file in corpus["files"]
            if file["key"].endswith("_tracking_data.jsonl.gz")
        )
        > 300_000_000
    )
    domain = build_game_domain(corpus, corpus["matches"][0])
    assert domain.streams == ()
    assert domain.sports_contexts[0].contest.sport_id == "basketball"
    assert domain.sports_contexts[0].contest_teams[0].score is not None
    assert domain.sports_contexts[0].session.source_catalog_entry_id == contest_catalog_id(
        str(corpus["matches"][0]["match"]["id"])
    )
    assert len(domain.participants) >= 20
    entries = build_catalog_entries(
        source_by_id(validate_registry(), authorities.DATASET_ID), corpus
    )
    contest_entry = next(entry for entry in entries if entry["object_kind"] == "contest")
    aggregate_entry = next(entry for entry in entries if entry["object_kind"] == "aggregate")
    assert contest_entry["dataset"] == authorities.DATASET_ID
    assert contest_entry["provider_metadata"]["file_families"]["tracking"]["key"].endswith(
        "_tracking_data.jsonl.gz"
    )
    assert aggregate_entry["dataset"] == authorities.DATASET_ID
    assert aggregate_entry["teams"] == []
    assert aggregate_entry["provider_metadata"]["sample_game_team_count"] == 17
    assert aggregate_entry["provider_metadata"]["season_aggregate_team_count"] == 18


def test_metadata_reregistration_preserves_materialized_contest_flags() -> None:
    corpus = load_corpus_manifest()
    domain = build_game_domain(corpus, corpus["matches"][0])
    updated = _preserve_materialized_contest_metadata(
        domain,
        {"play_by_play_available": True, "tracking_available": True, "period_count": 4},
    )
    contest_metadata = next(
        item.metadata
        for item in updated.sports_contexts[0].crosswalks
        if item.entity_kind is SportsEntityKind.CONTEST
    )
    assert contest_metadata["play_by_play_available"] is True
    assert contest_metadata["tracking_available"] is True
    assert contest_metadata["period_count"] == 4


def test_aggregate_subject_rows_use_canonical_sports_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    from dynamis.adapters.skillcorner_basketball import aggregates

    persisted: dict[str, list[dict[str, object]]] = {}

    def capture(_connection, table, rows):
        persisted[table.name] = rows
        return len(rows)

    monkeypatch.setattr(aggregates, "_upsert_refresh", capture)
    _persist_player_identities(
        object(),
        [
            {
                "provider_mappings": [
                    {"provider_id": "alias", "canonical_id": "canonical", "display_name": "Name"}
                ],
                "provider_team_mappings": [],
            }
        ],
        {"matches": []},
    )

    expected = canonical_sports_id(authorities.NAMESPACE, SportsEntityKind.SUBJECT, "canonical")
    assert [row["subject_id"] for row in persisted["subject"]] == [expected]


def test_cli_basketball_ingestion_requires_one_complete_game_set() -> None:
    from dynamis.acquisition.plan import PlanError
    from dynamis.pipeline.cli import _skillcorner_basketball_file_set

    keys = (
        "data/matches/114243/114243_game_data.json",
        "data/matches/114243/114243_tracking_data.jsonl.gz",
        "data/matches/114243/114243_dynamic_events.json",
    )
    paths = {key: Path(key) for key in keys}
    assert _skillcorner_basketball_file_set(paths) == tuple(paths[key] for key in keys)

    mixed = {
        **paths,
        "data/matches/114234/114234_tracking_data.jsonl.gz": Path("other-tracking.jsonl.gz"),
    }
    with pytest.raises(PlanError, match="exactly one game"):
        _skillcorner_basketball_file_set(mixed)

    with pytest.raises(PlanError, match="full file set"):
        _skillcorner_basketball_file_set({keys[0]: paths[keys[0]]})


def test_25_hz_tracking_keeps_clock_only_dead_time_without_positions(tmp_path: Path) -> None:
    tracking_path = tmp_path / "tracking.jsonl.gz"
    frame_clock_path = tmp_path / "frame-clock.parquet"
    _fixture_frames(tracking_path)
    frame_clock, written = write_frame_clock(
        tracking_path,
        game_id="game-1",
        session_id="game-1",
        output_path=frame_clock_path,
        dataset_root=tmp_path,
        batch_size=2,
        row_group_size=2,
    )
    canonicalizer = BasketballTrackingCanonicalizer(
        path=tracking_path,
        game_id="game-1",
        game_data={"homeTeam": {"teamId": 10}, "awayTeam": {"teamId": 20}},
        frame_clock=frame_clock,
        batch_size=20,
    )
    rows = [
        row
        for stream in canonicalizer.streams()
        for batch in stream.batches
        for row in batch.to_pylist()
    ]
    assert frame_clock.frame_count == 3
    assert frame_clock.dead_time_frames == 1
    assert frame_clock.wall_clock_delta_counts_ms == {40: 2}
    assert written.row_count == 3
    assert len(rows) == 4
    assert all(row["nominal_sampling_rate_hz"] == 25.0 for row in rows)
    assert rows[0]["x_m"] == 0.3048
    assert rows[0]["y_m"] == 0.6096
    assert {row["object_type"] for row in rows} == {"player", "ball"}


def test_feet_spatial_reference_transform_round_trips_to_source_coordinates() -> None:
    reference = authorities.spatial_reference()
    frame = authorities.coordinate_frame()
    scale = float(reference.source_transform["scale"])
    source_xyz_ft = (-47.25, 12.5, 5.75)
    canonical_xyz_m = tuple(value * scale for value in source_xyz_ft)
    recovered_xyz_ft = tuple(value / scale for value in canonical_xyz_m)

    assert reference.units == "ft"
    assert reference.source_transform == {
        "kind": "unit_scale",
        "from_unit": "ft",
        "to_unit": "m",
        "scale": 0.3048,
    }
    assert frame.length_unit == "m"
    assert all(
        math.isclose(actual, expected, abs_tol=1e-12)
        for actual, expected in zip(recovered_xyz_ft, source_xyz_ft, strict=True)
    )


def test_dynamic_event_envelope_links_by_exact_frame_key(tmp_path: Path) -> None:
    tracking_path = tmp_path / "tracking.jsonl.gz"
    frame_clock_path = tmp_path / "frame-clock.parquet"
    events_path = tmp_path / "events.json"
    _fixture_frames(tracking_path)
    write_frame_clock(
        tracking_path,
        game_id="game-1",
        session_id="game-1",
        output_path=frame_clock_path,
        dataset_root=tmp_path,
        batch_size=2,
        row_group_size=2,
    )
    events_path.write_text(
        json.dumps(
            {
                "shots": [
                    {
                        "id": "shot-1",
                        "period": 1,
                        "startFrame": 12,
                        "startWallClock": 480,
                        "startGameClock": 599.92,
                        "startShotClock": 23.92,
                        "location": {"x": 4.0, "y": 5.0},
                        "shooterId": 2,
                        "teamId": 20,
                    }
                ],
                "timeouts": [{"id": "timeout-1", "period": 1}],
                "passes": [{"id": "wallclock-1", "period": 1, "wallClock": 440}],
                "dribbles": [
                    {"id": "game-clock-1", "period": 1, "gameClock": 599.92, "shotClock": 23.92}
                ],
            }
        ),
        encoding="utf-8",
    )
    teams = {"10": "team-home", "20": "team-away"}
    table, summary = build_event_table(
        path=events_path,
        frame_clock_path=frame_clock_path,
        game_id="game-1",
        provider_team_ids=teams,
        source_revision="pinned-revision",
    )
    rows = table.to_pylist()
    shot = next(row for row in rows if row["source_event_id"] == "shot-1")
    unlinked = next(row for row in rows if row["source_event_id"] == "timeout-1")
    assert table.schema.metadata[b"dynamis.contract"] == b"cross_sport_event_envelope"
    assert summary["linked_events"] == 3
    assert summary["unlinked_events"] == 1
    assert summary["linkage_reconciliation"] == {
        "total_events": 4,
        "exact_frame": 1,
        "authoritative_time_clock": 2,
        "legitimately_unlinked": 1,
        "unlinked_reasons": {"provider_temporal_keys_missing": 1},
        "by_family": {
            "dribbles": {
                "total_events": 1,
                "exact_frame": 0,
                "authoritative_time_clock": 1,
                "legitimately_unlinked": 0,
                "unlinked_reasons": {},
            },
            "passes": {
                "total_events": 1,
                "exact_frame": 0,
                "authoritative_time_clock": 1,
                "legitimately_unlinked": 0,
                "unlinked_reasons": {},
            },
            "shots": {
                "total_events": 1,
                "exact_frame": 1,
                "authoritative_time_clock": 0,
                "legitimately_unlinked": 0,
                "unlinked_reasons": {},
            },
            "timeouts": {
                "total_events": 1,
                "exact_frame": 0,
                "authoritative_time_clock": 0,
                "legitimately_unlinked": 1,
                "unlinked_reasons": {"provider_temporal_keys_missing": 1},
            },
        },
    }
    assert shot["canonical_time_ns"] == 480_000_000
    shot_clock = json.loads(shot["source_clock_json"])
    assert shot_clock["linked_frame_idx"] == 12
    assert shot_clock["linkage_disposition"] == "exact_frame"
    assert shot["location"] == {"x": 4.0, "y": 5.0, "z": None}
    wall = next(row for row in rows if row["source_event_id"] == "wallclock-1")
    assert wall["canonical_time_ns"] == 440_000_000
    assert json.loads(wall["source_clock_json"])["link_method"] == "wallClock"
    game_clock = next(row for row in rows if row["source_event_id"] == "game-clock-1")
    assert game_clock["canonical_time_ns"] == 480_000_000
    assert json.loads(game_clock["source_clock_json"])["link_method"] == "gameClock"
    assert unlinked["canonical_time_ns"] is None
    unlinked_clock = json.loads(unlinked["source_clock_json"])
    assert unlinked_clock["linkage_disposition"] == "legitimately_unlinked"
    assert unlinked_clock["unlinked_reason"] == "provider_temporal_keys_missing"
    assert unlinked["location"] is None


def test_ambiguous_game_clock_is_not_snapped_to_a_frame(tmp_path: Path) -> None:
    tracking_path = tmp_path / "tracking.jsonl.gz"
    frame_clock_path = tmp_path / "frame-clock.parquet"
    events_path = tmp_path / "events.json"
    _fixture_frames(tracking_path)
    with gzip.open(tracking_path, "at", encoding="utf-8") as target:
        target.write(
            json.dumps(
                {
                    "frameIdx": 13,
                    "wallClock": 520,
                    "gameClock": 599.92,
                    "gameClockStopped": False,
                    "period": 1,
                    "shotClock": 23.92,
                    "homePlayers": [],
                    "awayPlayers": [],
                    "ball": {},
                }
            )
            + "\n"
        )
    write_frame_clock(
        tracking_path,
        game_id="game-1",
        session_id="game-1",
        output_path=frame_clock_path,
        dataset_root=tmp_path,
        batch_size=20,
        row_group_size=2,
    )
    events_path.write_text(
        json.dumps(
            {"shots": [{"id": "ambiguous", "period": 1, "gameClock": 599.92, "shotClock": 23.92}]}
        ),
        encoding="utf-8",
    )
    table, summary = build_event_table(
        path=events_path,
        frame_clock_path=frame_clock_path,
        game_id="game-1",
        provider_team_ids={},
        source_revision="pinned-revision",
    )

    row = table.to_pylist()[0]
    source_clock = json.loads(row["source_clock_json"])
    assert summary["linkage_reconciliation"]["legitimately_unlinked"] == 1
    assert source_clock["linked_frame_idx"] is None
    assert source_clock["unlinked_reason"] == "ambiguous_period_game_clock_key"


def test_player_alias_rows_merge_with_additive_and_weighted_source_metrics(
    tmp_path: Path,
) -> None:
    path = tmp_path / "shots.csv"
    path.write_text(
        "competition_id,competition_name,season_id,season_name,player_id,player_name,team_id,team_name,games_played,attempts,mades,fg_percentage\n"
        "8,Liga ACB,51,2025-2026,10,Player Name,1,Team One,2,10,5,0.5\n"
        "8,Liga ACB,51,2025-2026,20,Player Alias,1,Team One,3,10,7,0.7\n"
        "8,Liga ACB,51,2025-2026,10,Player Name,,total,2,1,1,1.0\n",
        encoding="utf-8",
    )
    table, summary = _canonicalize(
        path,
        family="shots",
        aliases={"20": "10"},
        names={"10": "Player Name"},
    )
    row = table.to_pylist()[0]
    assert summary["source_rows"] == 3
    assert summary["canonical_rows"] == 1
    assert summary["ignored_total_rows"] == 1
    assert summary["canonical_exclusions"] == [
        {
            "source_row_number": 4,
            "provider_player_id": "10",
            "provider_team_id": None,
            "provider_team_name": "total",
            "reason": "provider season-total row duplicates traded-player team rows",
        }
    ]
    assert row["games_played"] == 5
    assert row["attempts"] == 20
    assert row["mades"] == 12
    assert row["fg_percentage"] == 0.6
    assert row["provider_player_id"] == "10,20"
    assert row["position_group"] == "not_reported"


def test_pick_rate_and_efficiency_aliases_use_documented_denominators(tmp_path: Path) -> None:
    path = tmp_path / "picks.csv"
    path.write_text(
        "competition_id,competition_name,season_id,season_name,player_id,player_name,team_id,team_name,games_played,"
        "handler_total_picks,handler_successful_pick_rate,handler_successful_pick_pct,"
        "handler_picks_at_middle,handler_successful_pick_rate_at_middle,"
        "handler_score_2pt,handler_miss_2pt,handler_fg2_pct,"
        "handler_score_2pt_vs_blitz,handler_miss_2pt_vs_blitz,handler_fg2_pct_vs_blitz,"
        "handler_ppp_at_middle\n"
        "8,Liga ACB,51,2025-2026,10,Player Name,1,Team One,2,10,0.5,0.5,2,0.5,2,3,0.4,1,1,0.5,2.0\n"
        "8,Liga ACB,51,2025-2026,20,Player Alias,1,Team One,3,30,0.3,0.3,8,0.25,6,4,"
        "0.6,3,1,0.75,1.0\n",
        encoding="utf-8",
    )
    table, summary = _canonicalize(
        path,
        family="picks",
        aliases={"20": "10"},
        names={"10": "Player Name"},
    )

    row = table.to_pylist()[0]
    assert row["handler_successful_pick_rate"] == 0.35
    assert row["handler_successful_pick_pct"] == 0.35
    assert row["handler_successful_pick_rate_at_middle"] == 0.3
    assert math.isclose(row["handler_fg2_pct"], 8 / 15)
    assert math.isclose(row["handler_fg2_pct_vs_blitz"], 4 / 6)
    assert row["handler_ppp_at_middle"] == 1.2
    assert summary["unsupported_derived_fields"] == []
