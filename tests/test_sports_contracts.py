from datetime import UTC, datetime
from hashlib import md5

import pytest

from dynamis.contracts.sports import (
    EVENT_ENVELOPE_SCHEMA,
    Capability,
    CapabilityEvidence,
    CapabilityOrigin,
    CapabilityProfile,
    CapabilityScope,
    ClockDirection,
    ClockKind,
    ClockMapping,
    Competition,
    CompetitionEdition,
    Contest,
    ContestPeriod,
    ContestSide,
    ContestTeam,
    DataGrain,
    DataGrainKind,
    EditionKind,
    EventAttributeSchema,
    EventAttributeType,
    EventEnvelope,
    PeriodKind,
    ProductSurface,
    ProviderIdentityCrosswalk,
    SessionSportContext,
    SourceCatalogEntry,
    SourceCatalogState,
    SourceObjectKind,
    SpatialReference,
    Sport,
    SportsContext,
    SportsEntityKind,
    SurfaceGeometry,
    Team,
    TeamRosterMembership,
    canonical_sports_id,
    capability_profile_from_records,
    event_envelope_table,
    grain_artifact_layout,
    openlineage_dataset,
    openlineage_event,
    openlineage_job,
    openlineage_run,
    provider_crosswalk,
    provider_crosswalk_id,
    route_products,
    validate_grain_rows,
)


def test_sports_overlay_preserves_existing_subject_link_and_provider_alias() -> None:
    sport = Sport(sport_id="football", code="football", display_name="Football")
    competition = Competition(competition_id="comp-dfl", sport_id="football", name="League")
    edition = CompetitionEdition(
        edition_id="edition-dfl-2025",
        competition_id="comp-dfl",
        label="2025",
        kind=EditionKind.LEAGUE_SEASON,
    )
    team = Team(team_id="team-internal-1", sport_id="football", display_name="Home")
    contest = Contest(
        contest_id="contest-internal-1",
        sport_id="football",
        competition_edition_id=edition.edition_id,
        home_away_supported=True,
        source_authority="matchinformation v1",
    )
    membership = TeamRosterMembership(
        dataset_id="dfl-sportec-idsse",
        subject_id="player-1",
        team_id=team.team_id,
        competition_edition_id=edition.edition_id,
    )
    context = SportsContext(
        sport=sport,
        competition=competition,
        edition=edition,
        teams=(team,),
        contest=contest,
        contest_teams=(
            ContestTeam(
                contest_id=contest.contest_id,
                team_id=team.team_id,
                side=ContestSide.HOME,
                side_order=0,
                score=1,
            ),
        ),
        periods=(
            ContestPeriod(
                contest_period_id="period-1",
                contest_id=contest.contest_id,
                source_period_number="1",
                kind=PeriodKind.HALF,
            ),
        ),
        roster_memberships=(membership,),
        session=SessionSportContext(
            dataset_id="dfl-sportec-idsse",
            session_id="source-session-1",
            contest_id=contest.contest_id,
        ),
        crosswalks=(
            ProviderIdentityCrosswalk(
                provider_namespace="sportec_idsse",
                entity_kind=SportsEntityKind.TEAM,
                provider_entity_id="provider-team-1",
                canonical_entity_id=team.team_id,
                source_authority="matchinformation v1",
            ),
        ),
    )
    assert context.session.session_id == "source-session-1"
    assert context.roster_memberships[0].subject_id == "player-1"
    assert context.crosswalks[0].canonical_entity_id != context.crosswalks[0].provider_entity_id


def test_provider_scoped_ids_match_the_sql_backfill_contract() -> None:
    identity = "sportec_idsse:contest:match-1"
    assert canonical_sports_id("sportec_idsse", SportsEntityKind.CONTEST, "match-1") == (
        "contest-" + md5(identity.encode(), usedforsecurity=False).hexdigest()[:24]
    )
    alias = provider_crosswalk(
        provider_namespace="sportec_idsse",
        entity_kind=SportsEntityKind.TEAM,
        provider_entity_id="team-1",
        source_authority="match information",
    )
    assert (
        provider_crosswalk_id(alias)
        == "xw-" + md5(b"sportec_idsse:team:team-1", usedforsecurity=False).hexdigest()
    )


def test_grain_axes_and_duplicate_validation() -> None:
    grain = DataGrain(kind=DataGrainKind.PLAYER_SEASON)
    assert grain.axes == ("subject", "team", "competition_edition")
    validate_grain_rows(
        grain,
        [{"subject": "p1", "team": "t1", "competition_edition": "e1"}],
    )
    with pytest.raises(ValueError, match="duplicate"):
        validate_grain_rows(
            grain,
            [
                {"subject": "p1", "team": "t1", "competition_edition": "e1"},
                {"subject": "p1", "team": "t1", "competition_edition": "e1"},
            ],
        )
    with pytest.raises(ValueError, match="null"):
        validate_grain_rows(grain, [{"subject": "p1", "team": None, "competition_edition": "e1"}])
    assert (
        grain_artifact_layout(DataGrain(kind=DataGrainKind.FRAME_SERIES))[0]
        == "contest-period-modality"
    )


def test_capabilities_are_order_independent_and_route_on_local_evidence() -> None:
    evidence = (
        CapabilityEvidence(
            capability=Capability.TRACKING,
            origin=CapabilityOrigin.SOURCE_CATALOG,
            scope=CapabilityScope.UPSTREAM,
            evidence_id="catalog-1",
            source_authority="release registry",
        ),
        CapabilityEvidence(
            capability=Capability.EVENTS,
            origin=CapabilityOrigin.MATERIALIZED_ARTIFACT,
            scope=CapabilityScope.LOCAL,
            evidence_id="artifact-1",
            source_authority="verified Parquet artifact",
        ),
        CapabilityEvidence(
            capability=Capability.TRACKING,
            origin=CapabilityOrigin.MODEL_ESTIMATED,
            scope=CapabilityScope.LOCAL,
            evidence_id="model-1",
            source_authority="accepted processor",
        ),
    )
    first = CapabilityProfile.derive(evidence)
    second = CapabilityProfile.derive(reversed(evidence))
    assert first == second
    assert Capability.TRACKING in first.upstream_capabilities
    assert Capability.TRACKING in first.model_estimated_capabilities
    routes = {route.product: route for route in route_products(first, [DataGrainKind.EVENT_SERIES])}
    assert routes[ProductSurface.GAMELAB].ready
    assert not routes[ProductSurface.MATCHLAB].ready


def test_capability_profile_uses_catalog_stream_artifact_and_processor_evidence() -> None:
    stream = {
        "stream_id": "tracking-1",
        "modality": "tracking",
        "measurement_class": "MODEL_ESTIMATED",
    }
    catalog = SourceCatalogEntry.model_validate(
        {
            "entry_id": "catalog-1",
            "provider": "provider",
            "dataset": "dataset",
            "external_id": "asset-1",
            "object_kind": SourceObjectKind.RELEASE_ASSET,
            "upstream_url": "https://example.org/asset.parquet",
            "rights": {"identifier": "MIT"},
            "upstream_capabilities": ("TRACKING",),
            "discovered_at": datetime(2026, 1, 1, tzinfo=UTC),
        }
    )
    profile = capability_profile_from_records(
        catalog_entries=(catalog,),
        registered_streams=(stream,),
        materialized_artifacts=((stream, {"artifact_id": "artifact-1"}),),
        accepted_processors=(
            ({"algorithm_id": "tactical.shape", "version": "1"}, (Capability.TACTICAL,)),
        ),
    )
    assert Capability.TRACKING in profile.upstream_capabilities
    assert Capability.TRACKING in profile.registered_capabilities
    assert Capability.TRACKING in profile.local_capabilities
    assert Capability.TRACKING in profile.model_estimated_capabilities
    assert Capability.TACTICAL in profile.local_capabilities


def test_catalog_state_path_and_failure_evidence() -> None:
    entry = SourceCatalogEntry.model_validate(
        {
            "entry_id": "entry-1",
            "provider": "SkillCorner",
            "dataset": "skillcorner-opendata",
            "external_id": "1925299/tracking.jsonl",
            "object_kind": SourceObjectKind.RELEASE_ASSET,
            "sport_id": "football",
            "upstream_url": "https://example.org/tracking.jsonl",
            "rights": {"identifier": "MIT"},
            "discovered_at": datetime(2026, 1, 1, tzinfo=UTC),
        }
    )
    with pytest.raises(ValueError, match="invalid source catalog transition"):
        entry.transition(SourceCatalogState.READY)
    failed = entry.transition(
        SourceCatalogState.ACQUISITION_FAILED, evidence={"reason": "checksum mismatch"}
    )
    assert failed.failure_stage == "acquisition"
    recovered = failed.transition(SourceCatalogState.REGISTERED)
    assert recovered.failure_evidence is None
    assert (
        recovered.transition(SourceCatalogState.ACQUIRED).availability_state
        is SourceCatalogState.ACQUIRED
    )


def test_surface_event_clock_and_openlineage_contracts() -> None:
    reference = SpatialReference(
        spatial_reference_id="court-centred-m",
        version="1",
        units="m",
        origin={"x": 0, "y": 0},
        axis_orientation={"x": "court_long_axis", "y": "court_short_axis"},
        handedness="right",
        canonical_display_transform={"version": "1"},
        source_transform={"version": "1"},
    )
    surface = SurfaceGeometry(
        surface_id="court-1",
        version="1",
        sport_id="basketball",
        name="Court",
        dimensions={"length": 28, "width": 15},
        spatial_reference_id=reference.spatial_reference_id,
        spatial_reference_version=reference.version,
        source_authority="source coordinates",
    )
    assert surface.dimensions["length"] == 28
    event = EventEnvelope(
        contest_id="game-1",
        contest_period_id="q1",
        sequence_index="12",
        source_event_id="source-12",
        provider_namespace="provider",
        provider_event_type="shot",
        location={"x": 2, "y": 3},
        spatial_reference_id=reference.spatial_reference_id,
        attributes_schema_id="basketball.event",
        attributes_schema_version="1",
    )
    assert event.provider_event_type == "shot"
    with pytest.raises(ValueError, match="spatial reference"):
        EventEnvelope(
            contest_id="game-1",
            contest_period_id="q1",
            sequence_index="12",
            source_event_id="source-12",
            provider_namespace="provider",
            provider_event_type="shot",
            location={"x": 2, "y": 3},
            attributes_schema_id="basketball.event",
            attributes_schema_version="1",
        )
    schema = EventAttributeSchema(
        schema_id="basketball.event",
        version="1",
        properties={"points": EventAttributeType.INTEGER, "made": EventAttributeType.BOOLEAN},
        required=("points", "made"),
    )
    event = event.model_copy(update={"attributes_json": {"points": 2, "made": True}})
    table = event_envelope_table([event], {("basketball.event", "1"): schema})
    assert table.schema.metadata == EVENT_ENVELOPE_SCHEMA.metadata
    assert table.column("provider_event_type").to_pylist() == ["shot"]
    with pytest.raises(ValueError, match="must be integer"):
        invalid = event.model_copy(update={"attributes_json": {"points": True, "made": True}})
        event_envelope_table([invalid], {("basketball.event", "1"): schema})
    clock = ClockMapping(
        mapping_id="countdown-game-clock-v1",
        version="1",
        clock_kind=ClockKind.GAME_CLOCK,
        direction=ClockDirection.COUNT_DOWN,
        source_unit="ms",
        scale_to_ns=1_000_000,
        source_origin=600_000,
        period_origin_ns=0,
        authority="adapter",
        evidence={"declared": True},
    )
    assert clock.to_canonical_ns(300_000) == 300_000_000_000
    assert (
        openlineage_job(
            namespace="dynamis",
            algorithm_id="pose.kinematics",
            version="1",
            parameters_hash="a" * 64,
        )["name"]
        == "pose.kinematics:1"
    )
    assert openlineage_run(run_id="run-1", code_sha="b" * 40)["runId"] == "run-1"
    assert (
        openlineage_dataset(
            namespace="s3://artifacts", name="silver/stream.parquet", checksum_sha256="c" * 64
        )["facets"]["dynamis_artifact"]["checksumSha256"]
        == "c" * 64
    )
    event = openlineage_event(
        event_time=datetime(2026, 1, 1, tzinfo=UTC),
        event_type="COMPLETE",
        producer="dynamisetl",
        job={"namespace": "local", "name": "processor"},
        run={"runId": "run-1"},
        inputs=({"namespace": "s3", "name": "bronze/input.parquet"},),
        outputs=({"namespace": "s3", "name": "gold/output.parquet"},),
    )
    assert event["eventType"] == "COMPLETE"
    assert event["outputs"][0]["name"] == "gold/output.parquet"
