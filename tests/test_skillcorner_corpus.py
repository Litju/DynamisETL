from __future__ import annotations

import json

from dynamis.adapters.skillcorner.adapter import SkillCornerMatchAdapter
from dynamis.adapters.skillcorner.aggregates import _canonicalize
from dynamis.adapters.skillcorner.authorities import pose_stream_id, tracking_stream_id
from dynamis.adapters.skillcorner.catalog import (
    build_catalog_entries,
    build_skillcorner_catalog_rows,
    load_corpus_manifest,
)
from dynamis.contracts.sports import DataGrain, DataGrainKind, SportsEntityKind, canonical_sports_id
from dynamis.registry import source_by_id, validate_registry
from dynamis.storage.parquet import read_parquet_schema, write_parquet_atomic


def test_pinned_skillcorner_corpus_registers_all_match_families_without_pose_download() -> None:
    corpus = load_corpus_manifest()
    source = source_by_id(validate_registry(), corpus["dataset_id"])
    semantic = build_skillcorner_catalog_rows(corpus)
    entries = build_catalog_entries(source, corpus)

    assert len(corpus["matches"]) == 20
    assert len(corpus["files"]) == 86
    assert (len(semantic["team"]), len(semantic["contest"])) == (13, 20)
    assert (len(semantic["contest_team"]), len(semantic["contest_period"])) == (40, 40)
    assert len(entries) == 23
    assert len({item["external_id"] for item in entries}) == len(entries)

    by_match = {item["external_id"]: item for item in entries if item["object_kind"] == "contest"}
    assert "POSE" in by_match["contest:1996435"]["upstream_capabilities"]
    assert "POSE" not in by_match["contest:1996436"]["upstream_capabilities"]
    assert (
        by_match["contest:1996436"]["provider_metadata"]["pose_availability"]
        == "UPSTREAM_UNAVAILABLE"
    )
    assert sum(item["object_kind"] == "aggregate" for item in entries) == 3


def test_skillcorner_season_aggregate_keeps_provider_ids_and_position_group_grain(
    tmp_path,
) -> None:
    path = tmp_path / "physical.csv"
    path.write_text(
        "player_id,team_id,season_id,position_group,distance_m\n"
        "101,55,95,Forward,9200.5\n"
        "101,55,95,Midfielder,9100.0\n",
        encoding="utf-8",
    )

    table = _canonicalize(path, family="physical", expected_rows=2)
    rows = table.to_pylist()
    expected_team = canonical_sports_id("skillcorner_opendata", SportsEntityKind.TEAM, "55")
    expected_edition = canonical_sports_id("skillcorner_opendata", SportsEntityKind.EDITION, "870")

    assert table.num_rows == 2
    grain = DataGrain(
        kind=DataGrainKind.PLAYER_SEASON,
        axes=("subject", "team", "competition_edition", "position_group"),
    )
    artifact = write_parquet_atomic(table, tmp_path / "season.parquet", grain=grain)
    rerun = write_parquet_atomic(table, tmp_path / "season-rerun.parquet", grain=grain)
    assert (
        read_parquet_schema(artifact.path).metadata[b"dynamis.data_grain_kind"] == b"PLAYER_SEASON"
    )
    assert artifact.checksum_sha256 == rerun.checksum_sha256
    assert {row["provider_player_id"] for row in rows} == {"101"}
    assert {row["player_id"] for row in rows} == {101}
    assert {row["provider_team_id"] for row in rows} == {"55"}
    assert {row["team_id"] for row in rows} == {expected_team}
    assert {row["provider_competition_edition_id"] for row in rows} == {"870"}
    assert {row["competition_edition_id"] for row in rows} == {expected_edition}
    assert {row["position_group"] for row in rows} == {"Forward", "Midfielder"}
    assert {row["distance_m"] for row in rows} == {9200.5, 9100.0}


def test_skillcorner_match_stream_ids_preserve_legacy_and_scope_new_matches() -> None:
    assert tracking_stream_id(1) == tracking_stream_id(1, "1925299")
    assert pose_stream_id(1) == pose_stream_id(1, "1925299")
    assert tracking_stream_id(1, "1996435") != tracking_stream_id(1, "1925299")
    assert pose_stream_id(1, "1996435") != pose_stream_id(1, "1925299")


def test_pinned_match_adapter_preserves_catalog_contest_provenance(tmp_path) -> None:
    corpus = load_corpus_manifest()
    source_match = next(item for item in corpus["matches"] if str(item["id"]) == "1996435")
    match_path = tmp_path / "match.json"
    details = {
        **source_match["detail"],
        "id": source_match["id"],
        "pitch_length": 105.0,
        "pitch_width": 68.0,
        "players": [],
    }
    match_path.write_text(json.dumps(details), encoding="utf-8")
    adapter = SkillCornerMatchAdapter(
        match_json_path=match_path,
        tracking_path=tmp_path / "tracking.jsonl",
        pose_zip_path=tmp_path / "pose.zip",
        version=corpus["upstream"]["revision"],
    )

    context = adapter.domain().sports_contexts[0]
    crosswalks = {
        (item.entity_kind.value, item.provider_entity_id): item for item in context.crosswalks
    }
    team = next(
        item
        for item in corpus["teams"]
        if str(item["provider_team_id"]) == str(source_match["home_team"]["id"])
    )

    assert context.contest.source_authority == (
        f"SkillCorner matches.json and match.json@{corpus['upstream']['revision']}"
    )
    assert crosswalks[("team", str(team["provider_team_id"]))].metadata == {
        "short_name": team["short_name"]
    }
    assert crosswalks[("contest", "1996435")].metadata == {
        "matches_json_status": source_match["status"]
    }
