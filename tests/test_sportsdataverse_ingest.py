"""SportsDataverse NBA/NHL canonicalization and bounded game reads (synthetic data)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dynamis.adapters.sportsdataverse import ingest
from dynamis.contracts.sports import DataGrainKind, validate_grain_rows
from dynamis.serving import games

NS = 1_000_000_000


def _nba_tables() -> dict[str, pa.Table]:
    schedule = pa.table(
        {
            "game_id": pa.array([101, 102], pa.int32()),
            "season_type": pa.array([2, 3], pa.int32()),
            "start_date": ["2026-01-01T00:30Z", "2026-05-01T01:00Z"],
            "game_date": [date(2025, 12, 31), date(2026, 4, 30)],
            "status_type_completed": [True, True],
            "status_type_name": ["STATUS_FINAL", "STATUS_FINAL"],
            "venue_full_name": ["Arena A", "Arena B"],
            "neutral_site": [False, False],
            "home_id": pa.array([1, 2], pa.int32()),
            "away_id": pa.array([2, 1], pa.int32()),
            "home_display_name": ["Home Team", "Away Team"],
            "away_display_name": ["Away Team", "Home Team"],
            "home_score": pa.array([100, 90], pa.int32()),
            "away_score": pa.array([98, 95], pa.int32()),
            "PBP": [True, True],
            "player_box": [True, True],
            "team_box": [True, True],
        }
    )
    pbp = pa.table(
        {
            "game_id": pa.array([101, 101, 101, 102], pa.int32()),
            "game_play_number": pa.array([2, 1, 3, 1], pa.int32()),
            "id": pa.array([10102, 10101, 10103, 10201], pa.int64()),
            "period_number": pa.array([1, 1, 5, 1], pa.int32()),
            "period_display_value": ["1st Quarter", "1st Quarter", "OT", "1st Quarter"],
            "clock_display_value": ["11:00", "12:00", "4:30", "12:00"],
            "clock_minutes": pa.array([11, 12, 4, 12], pa.int32()),
            "clock_seconds": [0.0, 0.0, 30.0, 0.0],
            "type_text": ["Jump Shot", "Jumpball", "Free Throw", "Jumpball"],
            "team_id": pa.array([1, 1, 2, 2], pa.int32()),
            "athlete_id_1": pa.array([7, None, 8, 8], pa.int32()),
            "home_score": pa.array([2, 0, 100, 0], pa.int32()),
            "away_score": pa.array([0, 0, 98, 0], pa.int32()),
            "scoring_play": [True, False, True, False],
        }
    )
    player = pa.table(
        {
            "game_id": pa.array([101, 101], pa.int32()),
            "athlete_id": pa.array([7, 8], pa.int32()),
            "athlete_display_name": ["Player Seven", "Player Eight"],
            "team_id": pa.array([1, 2], pa.int32()),
            "points": pa.array([20, 18], pa.int32()),
        }
    )
    team = pa.table(
        {
            "game_id": pa.array([101, 101], pa.int32()),
            "team_id": pa.array([1, 2], pa.int32()),
            "team_score": pa.array([100, 98], pa.int32()),
            "team_logo": ["https://x/logo1.png", "https://x/logo2.png"],
        }
    )
    return {"schedule": schedule, "pbp": pbp, "player_game": player, "team_game": team}


def _nhl_tables() -> dict[str, pa.Table]:
    schedule = pa.table(
        {
            "game_id": pa.array([2001, 2002], pa.int32()),
            "game_type": ["R", "R"],
            "game_state": ["OFF", "OFF"],
            "game_time": ["2025-10-07T23:00:00Z", "2025-10-08T23:00:00Z"],
            "game_date": ["2025-10-07", "2025-10-08"],
            "venue": ["Rink A", "Rink B"],
            "home_team_abbr": ["AAA", "BBB"],
            "away_team_abbr": ["BBB", "AAA"],
            "home_team_name": ["Alpha", "Beta"],
            "away_team_name": ["Beta", "Alpha"],
            "home_score": pa.array([3, 4], pa.int32()),
            "away_score": pa.array([2, 3], pa.int32()),
            "PBP": [True, True],
            "skater_box": [True, True],
            "team_box": [True, True],
        }
    )
    pbp = pa.table(
        {
            "game_id": pa.array([2001, 2001, 2002, 2002, 2002], pa.int64()),
            "event_idx": pa.array([1, 2, 1, 2, 3], pa.int64()),
            "event_id": pa.array([11, 12, 21, 22, 23], pa.int64()),
            "period": pa.array([1, 3, 1, 4, 5], pa.int64()),
            "period_type": ["REGULAR", "REGULAR", "REGULAR", "OVERTIME", "SHOOTOUT"],
            "period_seconds": pa.array([0, 1190, 5, 100, 0], pa.int64()),
            "period_time": ["00:00", "19:50", "00:05", "01:40", "00:00"],
            "event_type": ["FACEOFF", "GOAL", "FACEOFF", "SHOT", "SHOOTOUT_GOAL"],
            "event_team_abbr": ["AAA", "AAA", "BBB", "AAA", "BBB"],
            "event_player_1_id": pa.array([501, 501, 601, 501, 601], pa.int64()),
            "home_score": pa.array([0, 3, 0, 3, 3], pa.int64()),
            "away_score": pa.array([0, 2, 0, 3, 3], pa.int64()),
            "strength_state": ["5v5"] * 5,
        }
    )
    skater = pa.table(
        {
            "game_id": pa.array([2001, 2001], pa.int64()),
            "player_id": pa.array([501, 601], pa.int64()),
            "player_name": ["A. Skater", "B. Skater"],
            "team_id": pa.array([10, 20], pa.int64()),
            "goals": pa.array([1, 0], pa.int64()),
        }
    )
    goalie = pa.table(
        {
            "game_id": pa.array([2001], pa.int64()),
            "player_id": pa.array([777], pa.int64()),
            "player_name": ["G. Keeper"],
            "team_id": pa.array([20], pa.int64()),
            "saves": pa.array([30], pa.int64()),
        }
    )
    team = pa.table(
        {
            "game_id": pa.array([2001, 2001, 2002, 2002], pa.int64()),
            "team_id": pa.array([10, 20, 20, 10], pa.int64()),
            "team_abbrev": ["AAA", "BBB", "BBB", "AAA"],
            "team_name": ["Aces", "Bees", "Bees", "Aces"],
        }
    )
    return {
        "schedule": schedule,
        "pbp": pbp,
        "skater_game": skater,
        "goalie_game": goalie,
        "team_game": team,
    }


def test_clock_mapping_semantics_per_sport() -> None:
    nba, nhl = ingest.NBA, ingest.NHL
    # Basketball counts down: 11:00 left in Q1 is 60 s into the contest.
    assert ingest.canonical_time_ns(nba, period=1, clock_s=660, postseason=False) == 60 * NS
    # Overtime 1 starts after 4 × 12 minutes and lasts 5 minutes.
    assert ingest.canonical_time_ns(nba, period=5, clock_s=300, postseason=False) == 2880 * NS
    assert ingest.canonical_time_ns(nba, period=1, clock_s=900, postseason=False) is None
    # Hockey counts up; regular-season OT is 5 minutes, playoff OT 20 minutes.
    assert ingest.canonical_time_ns(nhl, period=2, clock_s=30, postseason=False) == 1230 * NS
    assert ingest.canonical_time_ns(nhl, period=4, clock_s=400, postseason=False) is None
    assert ingest.canonical_time_ns(nhl, period=4, clock_s=400, postseason=True) == 4000 * NS
    mappings = ingest.clock_mappings(nba, max_period=5, postseason=False)
    assert [mapping.to_canonical_ns(660) for mapping in mappings[:1]] == [60 * NS]
    assert all(mapping.source_origin is not None for mapping in mappings)


def test_nba_canonicalization_preserves_order_identity_and_source_columns() -> None:
    result = ingest._nba(_nba_tables(), season=2026, authority="test")
    assert result.edition_label == "2025-26"
    pbp, grain = result.artifacts["pbp"]
    assert grain.kind is DataGrainKind.PLAY_BY_PLAY
    validate_grain_rows(grain, ingest.grain_rows(pbp, grain))
    first = [row for row in pbp.to_pylist() if row["provider_game_id"] == "101"]
    # Provider play number orders plays within the game, not the input row order.
    assert [row["sequence_index"] for row in first] == ["000001", "000002", "000003"]
    assert first[1]["canonical_time_ns"] == 60 * NS
    assert first[2]["period_number"] == 5
    assert json.loads(first[1]["source_clock_json"])["clock"] == "11:00"
    assert first[1]["subject_id"] == "sportsdataverse/espn_nba/7"
    assert {"src_type_text", "src_clock_display_value"} <= set(pbp.column_names)
    attributes = json.loads(first[1]["attributes_json"])
    assert attributes["scoring_play"] is True
    periods = {row["contest_period_id"]: row for row in result.semantic["contest_period"]}
    overtime = next(row for row in periods.values() if row["source_period_number"] == "5")
    assert overtime["kind"] == "overtime"
    assert overtime["start_ns"] == 2880 * NS
    subjects = [
        row
        for row in result.semantic["provider_identity_crosswalk"]
        if row["entity_kind"] == "subject"
    ]
    assert {row["canonical_entity_id"] for row in subjects} == {
        "sportsdataverse/espn_nba/7",
        "sportsdataverse/espn_nba/8",
    }
    recon = result.reconciliation
    assert recon["final_score_matches"] == 1
    assert recon["provider_score_discrepancies"] == 1  # game 102's pbp stops at 0-0


def test_nhl_canonicalization_handles_overtime_and_shootout() -> None:
    result = ingest._nhl(_nhl_tables(), season=2026, authority="test")
    assert result.edition_label == "2025-26"
    pbp, grain = result.artifacts["pbp"]
    validate_grain_rows(grain, ingest.grain_rows(pbp, grain))
    rows = {row["source_event_id"]: row for row in pbp.to_pylist()}
    assert rows["12"]["canonical_time_ns"] == (2400 + 1190) * NS
    assert rows["22"]["canonical_time_ns"] == (3600 + 100) * NS
    assert rows["23"]["canonical_time_ns"] is None  # a shootout has no contest time
    kinds = {
        (row["contest_id"], row["source_period_number"]): (row["kind"], row["start_ns"])
        for row in result.semantic["contest_period"]
    }
    assert ("other", None) in kinds.values()
    teams = {row["display_name"] for row in result.semantic["team"]}
    assert teams == {"Alpha Aces", "Beta Bees"}
    recon = result.reconciliation
    assert recon["shootout_decided"] == 1
    assert recon["provider_score_discrepancies"] == 0
    skater, _ = result.artifacts["skater_game"]
    goalie, _ = result.artifacts["goalie_game"]
    assert skater.num_rows == 2 and goalie.num_rows == 1


def test_no_cross_sport_schema_contamination() -> None:
    nba = ingest._nba(_nba_tables(), season=2026, authority="test").artifacts["pbp"][0]
    nhl = ingest._nhl(_nhl_tables(), season=2026, authority="test").artifacts["pbp"][0]
    envelope = set(ingest._ENVELOPE_COLUMNS)
    assert envelope <= set(nba.column_names) and envelope <= set(nhl.column_names)
    nba_source = {name for name in nba.column_names if name.startswith("src_")}
    nhl_source = {name for name in nhl.column_names if name.startswith("src_")}
    assert "src_strength_state" not in nba_source
    assert "src_clock_display_value" not in nhl_source
    assert set(nba["attributes_schema_id"].to_pylist()) == {"sportsdataverse.espn_nba.pbp"}
    assert set(nhl["attributes_schema_id"].to_pylist()) == {"sportsdataverse.nhl.pbp_lite"}


def test_play_by_play_for_an_unscheduled_game_is_refused() -> None:
    tables = _nba_tables()
    tables["schedule"] = tables["schedule"].slice(0, 1)
    with pytest.raises(ingest.IngestError, match="absent from the schedule"):
        ingest._nba(tables, season=2026, authority="test")


def test_bounded_game_reads_scope_to_one_contest(tmp_path: Path) -> None:
    result = ingest._nba(_nba_tables(), season=2026, authority="test")
    pbp_path = tmp_path / "pbp.parquet"
    pq.write_table(result.artifacts["pbp"][0], pbp_path, row_group_size=2)
    contest = next(
        row["contest_id"]
        for row in result.artifacts["pbp"][0].to_pylist()
        if row["provider_game_id"] == "101"
    )
    total, plays = games.read_plays(pbp_path, contest_id=contest, period=None, limit=2, offset=0)
    assert total == 3
    assert [play["sequence_index"] for play in plays] == ["000001", "000002"]
    assert plays[1]["source_clock"]["direction"] == "count_down"
    total, overtime = games.read_plays(pbp_path, contest_id=contest, period=5, limit=10, offset=0)
    assert total == 1 and overtime[0]["provider_event_type"] == "Free Throw"
    assert games.period_event_counts(pbp_path, contest_id=contest) == {1: 2, 5: 1}

    _, projected = games.read_plays(
        pbp_path,
        contest_id=contest,
        period=1,
        limit=5,
        offset=0,
        extra_columns=("clock_display_value", "scoring_play"),
    )
    assert projected[0]["source"] == {"clock_display_value": "12:00", "scoring_play": False}
    with pytest.raises(games.GameDataError, match="not in this artifact"):
        games.read_plays(
            pbp_path, contest_id=contest, period=1, limit=5, offset=0, extra_columns=("nope",)
        )

    box_path = tmp_path / "team.parquet"
    pq.write_table(result.artifacts["team_game"][0], box_path)
    columns, rows = games.read_box(box_path, contest_id=contest)
    assert "team_logo" not in columns  # presentation assets are not served
    assert "source__team_id" in columns and columns.count("team_id") == 1
    expected_provider_teams = {
        row["team_id"]: row["src_team_id"] for row in result.artifacts["team_game"][0].to_pylist()
    }
    assert all(expected_provider_teams[row["team_id"]] == row["source__team_id"] for row in rows)
    assert {row["source__team_score"] for row in rows} == {100, 98}


class _RightsBackend:
    """Minimal game backend: one local-only contest."""

    def __init__(self, local_only: bool) -> None:
        from dynamis.serving.models import LicenseView

        self.license = LicenseView(
            policy_id="lic",
            identifier="CC-BY-4.0",
            status="declared",
            attribution_required=True,
            noncommercial_only=False,
            share_alike=False,
            redistribution="prohibited" if local_only else "conditional",
            local_only=local_only,
            restrictions=[],
            notice="CC-BY-4.0; local-only" if local_only else "CC-BY-4.0",
        )

    def game_license(self, contest_id: str):
        return self.license

    def game_plays(self, contest_id: str, *, period, limit, offset, source_columns=()):
        from dynamis.serving.models import GamePlayPage

        return GamePlayPage(
            contest_id=contest_id, period=period, total=0, limit=limit, offset=offset, rows=[]
        )

    def game_box(self, contest_id: str, grain):
        from dynamis.serving.models import GameBoxView

        return GameBoxView(contest_id=contest_id, grain=grain, families=[])


def test_public_exposure_refuses_local_only_game_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from dynamis.serving.app import create_app, serving_exposure

    public = TestClient(create_app(backend=_RightsBackend(local_only=True), exposure="public"))
    for path in ("/api/games/c1/plays", "/api/games/c1/box?grain=team"):
        response = public.get(path)
        assert response.status_code == 451
        assert response.json()["state"] == "rights_restricted"

    local = TestClient(create_app(backend=_RightsBackend(local_only=True), exposure="local"))
    assert local.get("/api/games/c1/plays").status_code == 200

    open_source = TestClient(
        create_app(backend=_RightsBackend(local_only=False), exposure="public")
    )
    assert open_source.get("/api/games/c1/box").status_code == 200

    monkeypatch.setenv("DYNAMIS_SERVING_EXPOSURE", "internet")
    assert serving_exposure() == "public"  # unknown modes fail closed
    monkeypatch.delenv("DYNAMIS_SERVING_EXPOSURE")
    assert serving_exposure() == "local"
