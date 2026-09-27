"""SportsDataverse release taxonomy, pinned snapshot and release-asset resolver."""

from __future__ import annotations

import copy
from typing import Any, cast

import pytest
import requests

from dynamis.acquisition.download import UpstreamDriftError
from dynamis.acquisition.resolvers import GitHubReleaseResolver, ResolverError, resolver_for
from dynamis.adapters.sportsdataverse import releases
from dynamis.adapters.sportsdataverse.taxonomy import asset_season, edition_label, map_family
from dynamis.contracts.sports import DataGrainKind
from dynamis.registry import source_by_id, validate_registry


@pytest.mark.parametrize(
    ("tag", "league", "sport", "kind", "grain"),
    [
        ("espn_nba_pbp", "nba", "basketball", "play_by_play", DataGrainKind.PLAY_BY_PLAY),
        ("nhl_pbp_lite", "nhl", "ice_hockey", "play_by_play", DataGrainKind.PLAY_BY_PLAY),
        (
            "espn_nba_player_boxscores",
            "nba",
            "basketball",
            "player_game",
            DataGrainKind.PLAYER_GAME,
        ),
        ("nhl_goalie_boxscores", "nhl", "ice_hockey", "player_game", DataGrainKind.PLAYER_GAME),
        ("nhl_team_boxscores", "nhl", "ice_hockey", "team_game", DataGrainKind.TEAM_GAME),
        ("espn_nba_schedules", "nba", "basketball", "schedule", DataGrainKind.GAME_SUMMARY),
        (
            "wnba_stats_player_season_stats",
            "wnba",
            "basketball",
            "player_season",
            DataGrainKind.PLAYER_SEASON,
        ),
        ("ncaa_mbb_player_box", "mbb", "basketball", "player_game", DataGrainKind.PLAYER_GAME),
        ("espn_nba_shots", "nba", "basketball", "shots", DataGrainKind.EVENT_SERIES),
    ],
)
def test_taxonomy_maps_families_by_explicit_rule(
    tag: str, league: str, sport: str, kind: str, grain: DataGrainKind
) -> None:
    mapping = map_family(tag)
    assert (mapping.league_id, mapping.sport_id, mapping.family_kind, mapping.grain) == (
        league,
        sport,
        kind,
        grain,
    )
    assert mapping.mapped
    assert mapping.rule.startswith("sportsdataverse-taxonomy/1:")


def test_unknown_families_stay_unmapped_instead_of_guessed() -> None:
    injuries = map_family("espn_nba_injuries")
    assert injuries.league_id == "nba"
    assert injuries.family_kind == "unmapped"
    assert injuries.grain is None
    assert not injuries.mapped
    assert map_family("totally_new_family").league_id is None


def test_asset_season_and_edition_labels() -> None:
    assert asset_season("play_by_play_2026.parquet") == (2026, "parquet")
    assert asset_season("play_by_play_lite_2026.parquet") == (2026, "parquet")
    assert asset_season("play_by_play_2010_lite.csv") == (2010, "csv")
    assert asset_season("schedule_2025-26.rds") == (2026, "rds")
    assert asset_season("timestamp.json") is None
    assert edition_label("nba", 2026) == "2025-26"
    assert edition_label("nhl", 2026) == "2025-26"
    assert edition_label("wnba", 2026) == "2026"


def test_committed_snapshot_is_valid_and_matches_the_registry() -> None:
    snapshot = releases.load_snapshot()
    assert snapshot["family_count"] >= 300
    pins = releases.pinned_assets(snapshot)
    assert [pin.key for pin in pins] == [
        releases.pinned_key(tag, name) for tag, name in releases.PINNED_ASSETS
    ]
    assert {pin.league_id for pin in pins} == {"nba", "nhl"}
    assert {pin.season for pin in pins} == {2026}
    assert all(pin.freshness.get("timestamp") for pin in pins)

    source = source_by_id(validate_registry(), releases.DATASET_ID)
    version = source.version(snapshot["snapshot"])
    files = {item.key: item for item in version.retrieval.files}
    assert set(files) == {pin.key for pin in pins}
    for pin in pins:
        assert files[pin.key].size_bytes == pin.size_bytes
    assert source.license.local_only
    assert source.license.redistribution.value == "prohibited"
    assert resolver_for(source).name == "github_release"


def test_snapshot_refuses_unpinned_or_retaxonomized_content(tmp_path) -> None:
    snapshot = releases.load_snapshot()
    extra = copy.deepcopy(snapshot)
    extra["pinned"].append(dict(extra["pinned"][0], key="espn_nba_pbp/play_by_play_2025.parquet"))
    path = tmp_path / "extra.json"
    releases.write_snapshot(extra, path)
    with pytest.raises(releases.SnapshotError, match="bounded NBA/NHL"):
        releases.load_snapshot(path)

    drifted = copy.deepcopy(snapshot)
    drifted["families"][0]["rule"] = "sportsdataverse-taxonomy/0:schedule"
    releases.write_snapshot(drifted, path)
    with pytest.raises(releases.SnapshotError, match="stored rule differs"):
        releases.load_snapshot(path)


class _Response:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status
        self.ok = status < 400

    def json(self) -> Any:
        return self._payload

    def close(self) -> None:
        return None


class _Session:
    def __init__(self, releases_by_tag: dict[str, Any]) -> None:
        self.releases_by_tag = releases_by_tag
        self.urls: list[str] = []

    def get(self, url: str, **_: Any) -> _Response:
        self.urls.append(url)
        tag = url.rsplit("/", 1)[-1]
        payload = self.releases_by_tag.get(tag)
        return _Response(payload, 200 if payload is not None else 404)


def _live_release(pin: releases.PinnedAsset, **overrides: Any) -> dict[str, Any]:
    asset = {
        "name": pin.asset_name,
        "id": pin.asset_id,
        "size": pin.size_bytes,
        "updated_at": pin.updated_at,
        "browser_download_url": f"https://example.invalid/{pin.key}",
    }
    asset.update(overrides)
    return {"tag_name": pin.tag, "assets": [asset]}


def test_release_resolver_cross_checks_the_pin_before_any_byte() -> None:
    snapshot = releases.load_snapshot()
    pin = releases.pinned_assets(snapshot)[1]
    source = source_by_id(validate_registry(), releases.DATASET_ID)
    version = source.version(snapshot["snapshot"])
    resolver = GitHubReleaseResolver()

    session = _Session({pin.tag: _live_release(pin)})
    (resolved,) = resolver.resolve(
        cast(requests.Session, session),
        source=source,
        version=version,
        keys=[pin.key],
        timeout=(1.0, 1.0),
    )
    assert resolved.size_bytes == pin.size_bytes
    assert resolved.provider_metadata["asset_id"] == str(pin.asset_id)
    assert all("/download/" not in url for url in session.urls)

    for drift in ({"size": pin.size_bytes + 1}, {"id": pin.asset_id + 1}, {"updated_at": "2030"}):
        with pytest.raises(UpstreamDriftError):
            resolver.resolve(
                cast(requests.Session, _Session({pin.tag: _live_release(pin, **drift)})),
                source=source,
                version=version,
                keys=[pin.key],
                timeout=(1.0, 1.0),
            )
    with pytest.raises(ResolverError, match="not a pinned release asset"):
        resolver.resolve(
            cast(requests.Session, session),
            source=source,
            version=version,
            keys=["espn_nba_pbp/play_by_play_2019.parquet"],
            timeout=(1.0, 1.0),
        )
