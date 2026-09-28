from __future__ import annotations

from dynamis.adapters.sportsdataverse.releases import load_snapshot
from dynamis.contracts.sports import DataGrainKind
from dynamis.serving.catalog import build_catalog_read_model
from dynamis.serving.models import (
    DatasetSummary,
    GameEditionView,
    GameFamilyRef,
    LicenseView,
    SeasonEditionView,
    SeasonFamilyRef,
    SessionDetail,
    SessionSummary,
    SourceCapabilityView,
    SportsCatalogMatchView,
    StreamView,
)

LICENSE = LicenseView(
    policy_id="example",
    identifier="CC BY 4.0",
    status="declared",
    attribution_required=True,
    noncommercial_only=False,
    share_alike=False,
    redistribution="conditional",
    local_only=False,
    restrictions=[],
    notice="Attribution required",
)


def capability(
    entry_id: str,
    *,
    provider: str,
    sport_id: str,
    edition_id: str,
    upstream: list[str],
    registered: list[str],
    materialized: list[str],
    grains: list[str],
) -> SourceCapabilityView:
    return SourceCapabilityView(
        entry_id=entry_id,
        provider=provider,
        sport_id=sport_id,
        competition_id=f"{sport_id}:competition",
        competition_name=sport_id,
        edition_id=edition_id,
        edition_label="2025-26",
        external_id=entry_id,
        object_kind="contest",
        availability_state="MATERIALIZED",
        source_readiness="UPSTREAM_AVAILABLE",
        local_readiness="READY",
        upstream_capabilities=upstream,
        registered_capabilities=registered,
        materialized_capabilities=materialized,
        materialized_grains=grains,
        local_capabilities=materialized,
        pending_local_capabilities=[],
        preparation_eligible=True,
        preparation_action="validate",
        provider_metadata={},
        source_file_states={},
    )


def test_semantic_catalog_routes_only_from_local_capabilities_and_grain() -> None:
    football = capability(
        "football-match",
        provider="SkillCorner",
        sport_id="football",
        edition_id="football-edition",
        upstream=["TRACKING"],
        registered=["TRACKING"],
        materialized=["TRACKING"],
        grains=[DataGrainKind.FRAME_SERIES.value],
    )
    basketball = capability(
        "basketball-match",
        provider="SkillCorner",
        sport_id="basketball",
        edition_id="basketball-edition",
        upstream=["TRACKING", "EVENTS"],
        registered=["TRACKING"],
        materialized=["TRACKING"],
        grains=[DataGrainKind.FRAME_SERIES.value],
    )
    performance = DatasetSummary(
        dataset_id="white-cmj-acc-grf",
        name="White CMJ",
        provider="Zenodo",
        domain="laboratory",
        doi=None,
        upstream_urls=["https://example.org/white-cmj"],
        modalities=["force"],
        license=LICENSE,
        version_count=1,
        session_count=1,
        subject_count=1,
        trial_count=1,
        stream_count=1,
        metric_count=0,
        quality_issue_count=0,
    )
    sportsdataverse = DatasetSummary(
        dataset_id="sportsdataverse",
        name="SportsDataverse NBA/NHL releases",
        provider="SportsDataverse",
        domain="multi_sport",
        doi=None,
        upstream_urls=["https://github.com/sportsdataverse/sportsdataverse-data"],
        modalities=["event"],
        license=LICENSE,
        version_count=1,
        session_count=0,
        subject_count=0,
        trial_count=0,
        stream_count=0,
        metric_count=0,
        quality_issue_count=0,
    )
    upstream_lpt = DatasetSummary(
        dataset_id="gymaware-landmine-vision",
        name="GymAware Landmine Vision",
        provider="Zenodo",
        domain="laboratory",
        doi=None,
        upstream_urls=["https://example.org/gymaware"],
        modalities=["lpt"],
        license=LICENSE,
        version_count=1,
        session_count=0,
        subject_count=0,
        trial_count=0,
        stream_count=0,
        metric_count=0,
        quality_issue_count=0,
    )
    session = SessionDetail(
        dataset_id=performance.dataset_id,
        session=SessionSummary(
            session_id="cmj-1",
            kind="trial",
            label="Countermovement jump",
            started_at=None,
            ended_at=None,
            participant_count=1,
            trial_count=1,
            stream_count=1,
        ),
        participants=[],
        trials=[],
        streams=[
            StreamView(
                stream_id="force-1",
                modality="force",
                measurement_class="RAW_MEASURED",
                subject_id="athlete-1",
                trial_id="cmj-1",
                device_id=None,
                nominal_sampling_rate_hz=1000,
                si_units=["N"],
                source_unit="N",
                coordinate_frame_id=None,
                synchronization_spec_id="clock-1",
                clock_id="clock-1",
                skeleton_id=None,
                sample_artifact_ids=["force-artifact"],
                sample_row_count=100,
                data_grain_kind=DataGrainKind.TRIAL_SERIES.value,
                data_grain_axes=["subject", "trial", "sample_index"],
            )
        ],
    )
    game = GameEditionView(
        dataset_id="sportsdataverse",
        provider="SportsDataverse",
        sport_id="basketball",
        sport_name="Basketball",
        league_id="nba",
        competition_id="nba-competition",
        competition_name="NBA",
        edition_id="nba-2026",
        edition_label="2025-26",
        starts_on=None,
        ends_on=None,
        contest_count=1,
        completed_count=1,
        measurement_class="SOURCE_DERIVED",
        license=LICENSE,
        families=[
            GameFamilyRef(
                family="play_by_play",
                artifact_id="pbp-1",
                artifact_type="play_by_play",
                grain_kind=DataGrainKind.PLAY_BY_PLAY.value,
                row_count=20,
                checksum_sha256="a" * 64,
                run_id="run-1",
                source_file_key="play_by_play_2026.parquet",
                release_tag="espn_nba_pbp",
                release_asset_id=1,
                snapshot="sdv-2026-09-27",
            )
        ],
    )
    season = SeasonEditionView(
        dataset_id="skillcorner-opendata",
        provider="SkillCorner",
        sport_id="football",
        sport_name="Football",
        competition_id="football-competition",
        competition_name="A-League",
        edition_id="football-season-2026",
        edition_label="2025-26",
        measurement_class="SOURCE_DERIVED",
        inclusion_rule="published season population",
        glossary_url=None,
        registry_version="1",
        license=LICENSE,
        families=[
            SeasonFamilyRef(
                family="physical",
                label="Physical",
                artifact_id="season-1",
                row_count=10,
                checksum_sha256="b" * 64,
                run_id="run-season",
                grain_kind=DataGrainKind.PLAYER_SEASON.value,
                grain_axes=["subject", "team", "competition_edition"],
                source_revision="rev-1",
                source_file_key="physical.csv",
                source_population_rows=10,
                match_count_column="matches",
            )
        ],
    )
    match_rows = [
        SportsCatalogMatchView(
            dataset_id="skillcorner-opendata",
            session_id=session_id,
            provider_match_id=provider_id,
            contest_id=contest_id,
            sport_id=sport_id,
            sport_code=sport_id,
            sport_name=sport_name,
            competition_id=f"{sport_id}:competition",
            competition_name="Competition",
            edition_id=f"{sport_id}-edition",
            edition_label="2025-26",
            label="Same display name",
            scheduled_start_at=None,
            actual_start_at=None,
            venue=None,
            home_away_supported=False,
            teams=[],
            periods=[],
            source_capability=source_capability,
        )
        for contest_id, provider_id, session_id, sport_id, sport_name, source_capability in (
            ("contest-football", "f-1", "session-football", "football", "Football", football),
            (
                "contest-basketball",
                "b-1",
                "session-basketball",
                "basketball",
                "Basketball",
                basketball,
            ),
        )
    ]

    result = build_catalog_read_model(
        datasets=[performance, sportsdataverse, upstream_lpt],
        matches=match_rows,
        game_editions=[game],
        season_editions=[season],
        source_capabilities={
            "skillcorner-opendata": [football],
            "sportsdataverse": [],
            performance.dataset_id: [],
            upstream_lpt.dataset_id: [
                SourceCapabilityView(
                    entry_id="gymaware-release",
                    provider="Zenodo",
                    external_id="gymaware/landmine-vision.csv",
                    object_kind="release_asset",
                    availability_state="REGISTERED",
                    source_readiness="UPSTREAM_AVAILABLE",
                    local_readiness="NOT_MATERIALIZED",
                    upstream_capabilities=["LPT"],
                    registered_capabilities=[],
                    materialized_capabilities=[],
                    materialized_grains=[],
                    local_capabilities=[],
                    pending_local_capabilities=["LPT"],
                    preparation_eligible=True,
                    preparation_action="acquire",
                    provider_metadata={},
                    source_file_states={},
                )
            ],
        },
        performance_sessions=[(performance, session)],
        sportsdataverse_snapshot=load_snapshot(),
    )
    by_id = {item.resource_id: item for item in result.resources}

    assert by_id["contest-football"].stages.ready == "ready"
    assert any(
        route.product == "MatchLab" and route.ready for route in by_id["contest-football"].routes
    )
    assert by_id["contest-basketball"].basketball_spatial_ready
    assert any(route.product == "GameLab" and route.ready for route in by_id["nba-2026"].routes)
    assert by_id["nba-2026"].rights_identifiers == ["CC BY 4.0"]
    assert any(
        route.product == "SeasonLab" and route.ready
        for route in by_id["football-season-2026"].routes
    )
    assert any(
        route.product == "PerformanceLab" and route.ready
        for route in by_id["white-cmj-acc-grf/cmj-1"].routes
    )
    assert by_id["contest-football"].label == by_id["contest-basketball"].label
    assert "contest-football" in by_id and "contest-basketball" in by_id

    upstream_performance = by_id["gymaware-landmine-vision"]
    assert upstream_performance.resource_kind == "performance_dataset"
    assert upstream_performance.stages.upstream == "available"
    assert upstream_performance.stages.registered == "registered"
    assert upstream_performance.stages.materialized == "not_materialized"
    assert upstream_performance.stages.ready == "not_ready"
    assert upstream_performance.preparation_actions == ["acquire"]
    assert not any(route.ready for route in upstream_performance.routes)

    upstream_only = next(
        item
        for item in result.resources
        if item.resource_kind == "competition_edition"
        and "SportsDataverse" in item.providers
        and item.availability_state == "UPSTREAM_AVAILABLE"
    )
    assert upstream_only.stages.upstream == "available"
    assert upstream_only.stages.materialized == "not_materialized"
    assert upstream_only.stages.ready == "not_ready"
    assert not any(route.ready for route in upstream_only.routes)
    upstream_leagues = {
        item.sport_id
        for item in result.resources
        if "SportsDataverse" in item.providers and item.availability_state == "UPSTREAM_AVAILABLE"
    }
    assert {"basketball", "ice_hockey"}.issubset(upstream_leagues)
