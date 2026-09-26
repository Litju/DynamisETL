"""DFL/Sportec IDSSE match adapter: three XML files -> canonical streams + domain.

The adapter owns the provider descriptor: dataset identity, pinned version,
session/participant/period domain records, declared authorities and the
canonical streams (two multi-entity tracking streams, one event stream).

Domain metadata is emitted as plain contract objects (Session, Subject,
SessionParticipant, Trial, SensorStream) so the pipeline can persist it to the
control plane without re-deriving provider semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dynamis.adapters.sportec_idsse import authorities
from dynamis.adapters.sportec_idsse.events import EventsCanonicalizer, EventsSummary
from dynamis.adapters.sportec_idsse.matchinfo import (
    IdsseMatchMetadata,
    PlayerRecord,
    parse_match_information,
)
from dynamis.adapters.sportec_idsse.positions import (
    PositionsCanonicalizer,
    PositionsSummary,
)
from dynamis.contracts import (
    AlgorithmKind,
    AlgorithmSpec,
    MeasurementClass,
    Modality,
    ParticipantRole,
    SensorStream,
    Session,
    SessionKind,
    SessionParticipant,
    Subject,
    Trial,
)
from dynamis.contracts.sports import (
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
    PeriodKind,
    ProviderIdentityCrosswalk,
    SessionSportContext,
    SpatialReference,
    Sport,
    SportsContext,
    SportsEntityKind,
    SurfaceGeometry,
    Team,
    TeamRosterMembership,
    canonical_sports_id,
    provider_crosswalk,
)
from dynamis.pipeline.streams import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_ROW_GROUP_SIZE,
    CanonicalStream,
    ProviderDomain,
    SourceAuthorities,
)

IDSSE_DATASET_ID = authorities.IDSSE_DATASET_ID


def adapter_algorithm_spec() -> AlgorithmSpec:
    """Deterministic algorithm identity for the DFL/Sportec adapter."""
    return AlgorithmSpec(
        algorithm_id="sportec_idsse_adapter",
        name="DFL/Sportec IDSSE anti-corruption adapter",
        version="1",
        kind=AlgorithmKind.ADAPTER,
        description=(
            "Streams the pinned IDSSE matchinformation/events/positions XML into "
            "canonical tracking_sample and event_record streams."
        ),
    )


BALL_SUBJECT_PREFIX = "ball"


@dataclass(frozen=True, slots=True)
class IdsseMatchAdapterConfig:
    version: str
    batch_size: int = DEFAULT_BATCH_SIZE
    row_group_size: int = DEFAULT_ROW_GROUP_SIZE


class IdsseMatchAdapter:
    """Provider descriptor for one complete IDSSE match."""

    def __init__(
        self,
        *,
        match_information_path: Path,
        events_path: Path,
        positions_path: Path,
        version: str,
        spill_dir: Path,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._match_information_path = Path(match_information_path)
        self._events_path = Path(events_path)
        self._positions_path = Path(positions_path)
        self._version = version
        self._batch_size = batch_size
        self._spill_dir = Path(spill_dir)
        self._metadata: IdsseMatchMetadata | None = None
        self._positions: PositionsCanonicalizer | None = None
        self._events: EventsCanonicalizer | None = None
        self._positions_summary: PositionsSummary | None = None
        self._events_summary: EventsSummary | None = None

    # -- identity --------------------------------------------------------

    @property
    def dataset_id(self) -> str:
        return authorities.IDSSE_DATASET_ID

    @property
    def version(self) -> str:
        return self._version

    @property
    def metadata(self) -> IdsseMatchMetadata:
        if self._metadata is None:
            self._metadata = parse_match_information(self._match_information_path)
        return self._metadata

    @property
    def session_id(self) -> str:
        return self.metadata.match_id

    def algorithm_spec(self) -> AlgorithmSpec:
        return adapter_algorithm_spec()

    # -- authorities -----------------------------------------------------

    def source_authorities(self) -> SourceAuthorities:
        metadata = self.metadata
        kickoff_ns = round(metadata.kickoff_utc.timestamp() * 1_000_000_000)
        return SourceAuthorities(
            frames=(
                authorities.center_frame(metadata.pitch_x_m, metadata.pitch_y_m),
                authorities.corner_frame(metadata.pitch_x_m, metadata.pitch_y_m),
            ),
            clocks=(authorities.utc_clock(metadata.kickoff_utc),),
            synchronizations=(authorities.source_sync_spec(),),
            spatial_references=(
                SpatialReference(
                    spatial_reference_id=f"{authorities.CENTER_FRAME_ID}:{metadata.match_id}",
                    version="1",
                    units="m",
                    origin={"x": 0.0, "y": 0.0, "z": 0.0},
                    axis_orientation={"x": "long_axis", "y": "short_axis", "z": "up"},
                    handedness="right",
                    canonical_display_transform={"kind": "identity", "version": "1"},
                    source_transform={
                        "kind": "translation",
                        "from_frame": authorities.CORNER_FRAME_ID,
                        "to_frame": f"{authorities.CENTER_FRAME_ID}:{metadata.match_id}",
                        "translation_m": [-metadata.pitch_x_m / 2, -metadata.pitch_y_m / 2, 0],
                    },
                ),
            ),
            surface_geometries=(
                SurfaceGeometry(
                    surface_id=f"dfl-pitch:{metadata.match_id}",
                    version="1",
                    sport_id="football",
                    name="DFL/Sportec pitch",
                    dimensions={"length_m": metadata.pitch_x_m, "width_m": metadata.pitch_y_m},
                    spatial_reference_id=f"{authorities.CENTER_FRAME_ID}:{metadata.match_id}",
                    spatial_reference_version="1",
                    source_authority=f"matchinformation Environment.PitchX/PitchY@{self._version}",
                ),
            ),
            clock_mappings=(
                ClockMapping(
                    mapping_id=f"dfl-kickoff-relative-utc:{metadata.match_id}",
                    version="1",
                    clock_kind=ClockKind.WALL_TIME,
                    direction=ClockDirection.MONOTONIC,
                    source_unit="ns",
                    scale_to_ns=1.0,
                    period_origin_ns=0,
                    offset_ns=-kickoff_ns,
                    authority=f"matchinformation KickoffTime@{self._version}",
                    evidence={"kickoff_utc": metadata.kickoff_utc.isoformat()},
                ),
            ),
        )

    # -- domain ----------------------------------------------------------

    def domain(self) -> ProviderDomain:
        metadata = self.metadata
        subjects: list[Subject] = []
        participants: list[SessionParticipant] = []
        for player in metadata.players:
            subjects.append(
                Subject(
                    dataset_id=self.dataset_id,
                    subject_id=player.person_id,
                    sex="male",
                    cohort=metadata.team_name(player.team_id),
                    notes=(
                        f"shirt {player.shirt_number} "
                        f"({player.shortname or player.last_name or player.person_id})"
                    ),
                )
            )
            participants.append(
                SessionParticipant(
                    dataset_id=self.dataset_id,
                    session_id=metadata.match_id,
                    subject_id=player.person_id,
                    role=(
                        ParticipantRole.GOALKEEPER
                        if player.is_goalkeeper
                        else ParticipantRole.PLAYER
                    ),
                    group_label=player.team_id,
                )
            )
        trials = tuple(
            Trial(
                dataset_id=self.dataset_id,
                session_id=metadata.match_id,
                trial_id=period.period_id,
                label=period.section,
                started_at=period.started_at,
                ended_at=period.ended_at,
            )
            for period in self._periods()
        )
        session = Session(
            dataset_id=self.dataset_id,
            session_id=metadata.match_id,
            kind=SessionKind.MATCH,
            label=metadata.title,
            started_at=self._periods()[0].started_at if self._periods() else None,
            ended_at=self._periods()[-1].ended_at if self._periods() else None,
            venue=metadata.stadium,
        )
        streams = tuple(self._stream_records(trials))
        session_metadata = {
            "provider_request_id": metadata.request_id,
            "competition": metadata.competition,
            "season": metadata.season,
            "match_day": metadata.match_day,
            "result": metadata.result,
            "kickoff_utc": metadata.kickoff_utc.isoformat(),
            "planned_kickoff_utc": metadata.planned_kickoff_utc.isoformat(),
            "home_team": {
                "team_id": metadata.home_team.team_id,
                "name": metadata.home_team.name,
                "lineup": metadata.home_team.lineup,
            },
            "away_team": {
                "team_id": metadata.away_team.team_id,
                "name": metadata.away_team.name,
                "lineup": metadata.away_team.lineup,
            },
            "pitch_size_m": [metadata.pitch_x_m, metadata.pitch_y_m],
            "player_count": metadata.player_count,
            "trainer_count": metadata.trainer_count,
            "referee_count": metadata.referee_count,
            "period_total_times_ms": metadata.period_total_times_ms,
            "capture": "TRACAB optical tracking (DFL/Sportec provider)",
        }
        namespace = "sportec_idsse"
        authority = f"matchinformation@{self._version}"
        sport = Sport(sport_id="football", code="football", display_name="Football")
        competition_id = canonical_sports_id(
            namespace, SportsEntityKind.COMPETITION, metadata.competition
        )
        edition_id = canonical_sports_id(
            namespace,
            SportsEntityKind.EDITION,
            f"{metadata.competition}/{metadata.season}",
        )
        contest_id = canonical_sports_id(namespace, SportsEntityKind.CONTEST, metadata.match_id)
        home_team_id = canonical_sports_id(
            namespace, SportsEntityKind.TEAM, metadata.home_team.team_id
        )
        away_team_id = canonical_sports_id(
            namespace, SportsEntityKind.TEAM, metadata.away_team.team_id
        )
        team_by_source_id = {
            metadata.home_team.team_id: home_team_id,
            metadata.away_team.team_id: away_team_id,
        }
        sports_context = SportsContext(
            sport=sport,
            competition=Competition(
                competition_id=competition_id,
                sport_id=sport.sport_id,
                name=metadata.competition,
            ),
            edition=CompetitionEdition(
                edition_id=edition_id,
                competition_id=competition_id,
                label=metadata.season,
                kind=EditionKind.LEAGUE_SEASON,
            ),
            teams=(
                Team(
                    team_id=home_team_id,
                    sport_id=sport.sport_id,
                    display_name=metadata.home_team.name,
                ),
                Team(
                    team_id=away_team_id,
                    sport_id=sport.sport_id,
                    display_name=metadata.away_team.name,
                ),
            ),
            contest=Contest(
                contest_id=contest_id,
                sport_id=sport.sport_id,
                competition_edition_id=edition_id,
                scheduled_start_at=metadata.planned_kickoff_utc,
                actual_start_at=metadata.kickoff_utc,
                venue=metadata.stadium or None,
                home_away_supported=True,
                source_authority=authority,
            ),
            contest_teams=(
                ContestTeam(
                    contest_id=contest_id, team_id=home_team_id, side=ContestSide.HOME, side_order=0
                ),
                ContestTeam(
                    contest_id=contest_id, team_id=away_team_id, side=ContestSide.AWAY, side_order=1
                ),
            ),
            periods=tuple(
                ContestPeriod(
                    contest_period_id=f"{contest_id}:period:{trial.trial_id}",
                    contest_id=contest_id,
                    source_period_number=trial.trial_id,
                    kind=PeriodKind.OTHER,
                    label=trial.label,
                    provider_namespace=namespace,
                )
                for trial in trials
            ),
            roster_memberships=tuple(
                TeamRosterMembership(
                    dataset_id=self.dataset_id,
                    subject_id=player.person_id,
                    team_id=team_by_source_id[player.team_id],
                    competition_edition_id=edition_id,
                )
                for player in metadata.players
            ),
            session=SessionSportContext(
                dataset_id=self.dataset_id,
                session_id=metadata.match_id,
                contest_id=contest_id,
            ),
            crosswalks=(
                provider_crosswalk(
                    provider_namespace=namespace,
                    entity_kind=SportsEntityKind.COMPETITION,
                    provider_entity_id=metadata.competition,
                    source_authority=authority,
                ),
                provider_crosswalk(
                    provider_namespace=namespace,
                    entity_kind=SportsEntityKind.EDITION,
                    provider_entity_id=f"{metadata.competition}/{metadata.season}",
                    source_authority=authority,
                ),
                provider_crosswalk(
                    provider_namespace=namespace,
                    entity_kind=SportsEntityKind.TEAM,
                    provider_entity_id=metadata.home_team.team_id,
                    source_authority=authority,
                ),
                provider_crosswalk(
                    provider_namespace=namespace,
                    entity_kind=SportsEntityKind.TEAM,
                    provider_entity_id=metadata.away_team.team_id,
                    source_authority=authority,
                ),
                provider_crosswalk(
                    provider_namespace=namespace,
                    entity_kind=SportsEntityKind.CONTEST,
                    provider_entity_id=metadata.match_id,
                    source_authority=authority,
                ),
                *(
                    ProviderIdentityCrosswalk(
                        provider_namespace=namespace,
                        entity_kind=SportsEntityKind.SUBJECT,
                        provider_entity_id=player.person_id,
                        canonical_entity_id=f"{self.dataset_id}/{player.person_id}",
                        source_authority=authority,
                    )
                    for player in metadata.players
                ),
            ),
        )
        return ProviderDomain(
            session=session,
            subjects=tuple(subjects),
            participants=tuple(participants),
            trials=trials,
            streams=streams,
            authorities=self.source_authorities(),
            session_metadata=session_metadata,
            sports_contexts=(sports_context,),
            participants_ignored={
                "trainers": metadata.trainer_count,
                "referees_and_officials": metadata.referee_count,
            },
        )

    def playing_positions(self) -> dict[str, str | None]:
        return {player.person_id: player.playing_position for player in self.metadata.players}

    def player_records(self) -> tuple[PlayerRecord, ...]:
        return self.metadata.players

    def _periods(self):
        if self._events_summary is None:
            self.parse_events()
        assert self._events_summary is not None
        return self._events_summary.periods

    def _stream_records(self, trials: tuple[Trial, ...]) -> list[SensorStream]:
        metadata = self.metadata
        streams: list[SensorStream] = []
        for trial in trials:
            streams.append(
                SensorStream(
                    dataset_id=self.dataset_id,
                    session_id=metadata.match_id,
                    stream_id=authorities.tracking_stream_id(trial.trial_id),
                    modality=Modality.TRACKING,
                    measurement_class=MeasurementClass.RAW_MEASURED,
                    clock_id=authorities.CLOCK_ID,
                    synchronization_spec_id=authorities.SYNC_SPEC_ID,
                    coordinate_frame_id=authorities.CENTER_FRAME_ID,
                    trial_id=trial.trial_id,
                    nominal_sampling_rate_hz=25.0,
                    si_units=("m", "m/s", "m/s**2", "1"),
                    stream_metadata={
                        "source_file_key": self._positions_path.name,
                        "frame_major": True,
                        "multi_entity": True,
                        "pitch_dimensions_m": {
                            "length_m": metadata.pitch_x_m,
                            "width_m": metadata.pitch_y_m,
                        },
                    },
                    data_grain=DataGrain(kind=DataGrainKind.FRAME_SERIES),
                )
            )
        streams.append(
            SensorStream(
                dataset_id=self.dataset_id,
                session_id=metadata.match_id,
                stream_id=authorities.EVENT_STREAM_ID,
                modality=Modality.EVENT,
                measurement_class=MeasurementClass.SOURCE_DERIVED,
                clock_id=authorities.CLOCK_ID,
                synchronization_spec_id=authorities.SYNC_SPEC_ID,
                coordinate_frame_id=authorities.CENTER_FRAME_ID,
                nominal_sampling_rate_hz=None,
                si_units=("m",),
                stream_metadata={"source_file_key": self._events_path.name},
                data_grain=DataGrain(kind=DataGrainKind.EVENT_SERIES),
            )
        )
        return streams

    # -- canonical streams ----------------------------------------------

    def parse_positions(self) -> PositionsSummary:
        if self._positions is None:
            metadata = self.metadata
            self._positions = PositionsCanonicalizer(
                self._positions_path,
                metadata,
                spill_dir=self._spill_dir,
                batch_size=self._batch_size,
                dataset_id=self.dataset_id,
                clock_id=authorities.CLOCK_ID,
                synchronization_spec_id=authorities.SYNC_SPEC_ID,
                coordinate_frame_id=authorities.CENTER_FRAME_ID,
            )
        if self._positions_summary is None:
            self._positions_summary = self._positions.spill()
        return self._positions_summary

    def parse_events(self) -> EventsSummary:
        if self._events is None:
            self._events = EventsCanonicalizer(
                self._events_path,
                self.metadata,
                transform=authorities.corner_to_center_transform(
                    self.metadata.pitch_x_m, self.metadata.pitch_y_m
                ),
                dataset_id=self.dataset_id,
                session_id=self.session_id,
                clock_id=authorities.CLOCK_ID,
                synchronization_spec_id=authorities.SYNC_SPEC_ID,
                coordinate_frame_id=authorities.CENTER_FRAME_ID,
                batch_size=self._batch_size,
            )
        if self._events_summary is None:
            self._events_summary = self._events.summary
            self._events.parse()
        return self._events_summary

    def tracking_streams(self) -> tuple[CanonicalStream, ...]:
        self.parse_positions()
        assert self._positions is not None
        return self._positions.streams(session_id=self.session_id)

    def event_stream(self) -> CanonicalStream:
        self.parse_events()
        assert self._events is not None
        return self._events.stream()

    def quarantined(self):
        records = []
        if self._positions is not None:
            records.extend(self._positions.quarantined())
        if self._events_summary is not None:
            records.extend(self._events_summary.quarantined)
        return tuple(records)

    def cleanup(self) -> None:
        if self._positions is not None:
            self._positions.cleanup()
