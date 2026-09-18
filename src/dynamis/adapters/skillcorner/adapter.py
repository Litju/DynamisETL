"""SkillCorner Open Data match adapter: metadata + tracking + body pose.

The adapter owns provider semantics and emits canonical domain records
(``Session``/``Subject``/``SessionParticipant``/``Trial``/``SensorStream``), the
declared authorities (two frames, one clock, one synchronization spec, one
29-landmark skeleton set and two explicit pose -> tracking alignments) and the
canonical streams. It streams the ~3.3 GB pose member straight from the ZIP and
never expands it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dynamis.adapters.skillcorner import authorities
from dynamis.adapters.skillcorner.metadata import (
    SkillCornerMatchMetadata,
    parse_match_metadata,
)
from dynamis.adapters.skillcorner.pose import (
    CoincidenceReport,
    PoseCanonicalizer,
    analyse_coincidences,
)
from dynamis.adapters.skillcorner.tracking import (
    TrackingCanonicalizer,
    TrackingPeriodSummary,
)
from dynamis.contracts import (
    AlgorithmSpec,
    MeasurementClass,
    Modality,
    ParticipantRole,
    SensorStream,
    Session,
    SessionKind,
    SessionParticipant,
    Subject,
    SyncAlignment,
    Trial,
)
from dynamis.pipeline.quarantine import QuarantinedRecord
from dynamis.pipeline.streams import (
    DEFAULT_BATCH_SIZE,
    CanonicalStream,
    ProviderDomain,
    SourceAuthorities,
)


@dataclass(frozen=True, slots=True)
class SkillCornerAdapterConfig:
    version: str
    batch_size: int = DEFAULT_BATCH_SIZE


class SkillCornerMatchAdapter:
    """Provider descriptor for one complete SkillCorner match slice."""

    def __init__(
        self,
        *,
        match_json_path: Path,
        tracking_path: Path,
        pose_zip_path: Path,
        version: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._match_json_path = Path(match_json_path)
        self._tracking_path = Path(tracking_path)
        self._pose_zip_path = Path(pose_zip_path)
        self._version = version
        self._batch_size = batch_size
        self._metadata: SkillCornerMatchMetadata | None = None
        self._tracking: TrackingCanonicalizer | None = None
        self._pose: PoseCanonicalizer | None = None
        self._coincidence_report: CoincidenceReport | None = None

    # -- identity --------------------------------------------------------

    @property
    def dataset_id(self) -> str:
        return authorities.SKILLCORNER_DATASET_ID

    @property
    def version(self) -> str:
        return self._version

    @property
    def metadata(self) -> SkillCornerMatchMetadata:
        if self._metadata is None:
            self._metadata = parse_match_metadata(self._match_json_path)
        return self._metadata

    @property
    def session_id(self) -> str:
        return self.metadata.session_id

    def algorithm_spec(self) -> AlgorithmSpec:
        return authorities.adapter_algorithm_spec()

    # -- authorities -----------------------------------------------------

    def source_authorities(self) -> SourceAuthorities:
        metadata = self.metadata
        alignments: list[SyncAlignment] = []
        for period in metadata.periods:
            alignments.append(
                SyncAlignment(
                    source_stream_id=authorities.pose_stream_id(period.period),
                    target_stream_id=authorities.tracking_stream_id(period.period),
                    offset_ns=0,
                    scale=1.0,
                    sync_spec_id=authorities.SYNC_SPEC_ID,
                    notes=(
                        "Declared per-period alignment between the 25 Hz pose stream and its "
                        "10 Hz tracking counterpart: both carry the provider match clock "
                        f"({authorities.POSE_TRACKING_FRAME_RATIO:g} pose frames per tracking "
                        "frame) with offset 0 and scale 1. This states a shared released "
                        "coordinate, not zero provider error; exact coincidences are measured "
                        "as V&V evidence."
                    ),
                )
            )
        return SourceAuthorities(
            frames=(
                authorities.pitch_frame(metadata.pitch_length_m, metadata.pitch_width_m),
                authorities.pose_hybrid_frame(),
            ),
            clocks=(authorities.match_clock(),),
            synchronizations=(authorities.source_sync_spec(),),
            alignments=tuple(alignments),
            skeletons=(authorities.pose_skeleton(),),
        )

    # -- domain ----------------------------------------------------------

    def domain(self) -> ProviderDomain:
        metadata = self.metadata
        subjects = tuple(
            Subject(
                dataset_id=self.dataset_id,
                subject_id=player.player_id,
                sex="unspecified",
                cohort=player.team_name,
                notes=(
                    f"shirt {player.shirt_number} ({player.short_name or player.player_id})"
                    if player.shirt_number is not None
                    else (player.short_name or player.player_id)
                ),
            )
            for player in metadata.players
        )
        participants = tuple(
            SessionParticipant(
                dataset_id=self.dataset_id,
                session_id=metadata.session_id,
                subject_id=player.player_id,
                role=ParticipantRole.GOALKEEPER if player.is_goalkeeper else ParticipantRole.PLAYER,
                group_label=player.team_id,
            )
            for player in metadata.players
        )
        trials = tuple(
            Trial(
                dataset_id=self.dataset_id,
                session_id=metadata.session_id,
                trial_id=period.name,
                label=f"period {period.period}",
            )
            for period in metadata.periods
        )
        session = Session(
            dataset_id=self.dataset_id,
            session_id=metadata.session_id,
            kind=SessionKind.MATCH,
            label=(
                f"{metadata.home_team_name} "
                f"{metadata.home_score if metadata.home_score is not None else '?'}-"
                f"{metadata.away_score if metadata.away_score is not None else '?'} "
                f"{metadata.away_team_name}"
            ),
            started_at=metadata.kickoff_utc,
            venue=metadata.stadium,
        )
        streams: list[SensorStream] = []
        for period in metadata.periods:
            streams.append(
                SensorStream(
                    dataset_id=self.dataset_id,
                    session_id=metadata.session_id,
                    stream_id=authorities.tracking_stream_id(period.period),
                    modality=Modality.TRACKING,
                    measurement_class=MeasurementClass.MODEL_ESTIMATED,
                    clock_id=authorities.CLOCK_ID,
                    synchronization_spec_id=authorities.SYNC_SPEC_ID,
                    coordinate_frame_id=authorities.TRACKING_FRAME_ID,
                    trial_id=period.name,
                    nominal_sampling_rate_hz=authorities.TRACKING_FRAME_RATE_HZ,
                    si_units=("m",),
                    source_unit="m",
                    stream_metadata={
                        "source_file_key": self._tracking_path.name,
                        "frame_entity_observations": True,
                        "multi_entity": True,
                        "provider_product": "broadcast tracking (computer-vision)",
                    },
                )
            )
            streams.append(
                SensorStream(
                    dataset_id=self.dataset_id,
                    session_id=metadata.session_id,
                    stream_id=authorities.pose_stream_id(period.period),
                    modality=Modality.POSE,
                    measurement_class=MeasurementClass.MODEL_ESTIMATED,
                    clock_id=authorities.CLOCK_ID,
                    synchronization_spec_id=authorities.SYNC_SPEC_ID,
                    coordinate_frame_id=authorities.POSE_FRAME_ID,
                    skeleton_id=authorities.POSE_SKELETON_ID,
                    trial_id=period.name,
                    nominal_sampling_rate_hz=authorities.POSE_FRAME_RATE_HZ,
                    si_units=("m",),
                    source_unit="m",
                    stream_metadata={
                        "source_file_key": self._pose_zip_path.name,
                        "provider_product": "body pose (25 fps, 29 landmarks)",
                        "joint_rows_per_player_frame": len(authorities.POSE_LANDMARKS),
                        "error_source_field": authorities.POSE_ERROR_SOURCE_FIELD,
                        "error_source_to_si_scale": (authorities.POSE_ERROR_SOURCE_TO_SI_SCALE),
                        "error_semantics": authorities.POSE_ERROR_SEMANTICS,
                    },
                )
            )
        return ProviderDomain(
            session=session,
            subjects=subjects,
            participants=participants,
            trials=trials,
            streams=tuple(streams),
            authorities=self.source_authorities(),
            session_metadata={
                "match_id": metadata.match_id,
                "date_time_utc": metadata.kickoff_utc.isoformat(),
                "pitch_size_m": [metadata.pitch_length_m, metadata.pitch_width_m],
                "home_team": {
                    "team_id": metadata.home_team_id,
                    "name": metadata.home_team_name,
                    "score": metadata.home_score,
                },
                "away_team": {
                    "team_id": metadata.away_team_id,
                    "name": metadata.away_team_name,
                    "score": metadata.away_score,
                },
                "stadium": metadata.stadium,
                "declared_players": len(metadata.players),
                "declared_player_ids": self._declared_player_ids(),
                "periods": [period.to_dict() for period in metadata.periods],
                "pose_geometry": authorities.HYBRID_GEOMETRY_STATEMENT,
                "pose_tracking_alignment": authorities.ALIGNMENT_STATEMENT,
                "measurement_note": (
                    "tracking and pose are provider broadcast-video model estimates; pose "
                    "coordinates are MODEL_ESTIMATED, never raw instrument measurements"
                ),
            },
        )

    def _declared_player_ids(self) -> list[str]:
        # Squad identities declared by the match metadata; sample-level
        # observation coverage is reported by the canonicalizers and receipts.
        return [player.player_id for player in self.metadata.players]

    # -- canonical streams ----------------------------------------------

    def parse_tracking(self) -> TrackingCanonicalizer:
        if self._tracking is None:
            self._tracking = TrackingCanonicalizer(
                self._tracking_path,
                self.metadata,
                dataset_id=self.dataset_id,
                batch_size=self._batch_size,
            )
        return self._tracking

    def tracking_streams(self) -> tuple[CanonicalStream, ...]:
        return self.parse_tracking().streams()

    def tracking_summary(self, period: int) -> TrackingPeriodSummary:
        return self.parse_tracking().summary(period)

    def parse_pose(self) -> PoseCanonicalizer:
        if self._pose is None:
            self._pose = PoseCanonicalizer(
                self._pose_zip_path,
                self.metadata,
                dataset_id=self.dataset_id,
                batch_size=self._batch_size,
            )
        return self._pose

    def pose_streams(self) -> tuple[CanonicalStream, ...]:
        return self.parse_pose().streams()

    def pose_summary(self, period: int):
        return self.parse_pose().summary(period)

    def coincidence_report(self, *, refresh: bool = False) -> CoincidenceReport:
        if self._coincidence_report is None or refresh:
            self._coincidence_report = analyse_coincidences(
                pose_zip_path=self._pose_zip_path,
                tracking_path=self._tracking_path,
                match_id=self.metadata.match_id,
            )
        return self._coincidence_report

    def quarantined(self) -> tuple[QuarantinedRecord, ...]:
        records: list[QuarantinedRecord] = []
        if self._tracking is not None:
            for period in self.metadata.periods:
                records.extend(self._tracking.summary(period.period).quarantined)
        if self._pose is not None:
            for period in self.metadata.periods:
                records.extend(self._pose.summary(period.period).quarantined)
        return tuple(records)

    def cleanup(self) -> None:
        return None
