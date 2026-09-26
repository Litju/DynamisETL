"""SPL Open Data free-throw adapter: locked trials -> canonical pose streams.

One provider slice is a participant's first trial from each acquisition
generation (30 fps and 60 fps). The same participant identity (``P0001``) is
deliberately shared across the two sessions; the sessions stay distinct and no
cross-session synchronization is claimed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dynamis.adapters.spl import authorities
from dynamis.adapters.spl.trial import (
    SplTrialCanonicalizer,
    SplTrialIdentity,
    SplTrialSummary,
    identity_from_key,
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
    Trial,
)
from dynamis.contracts.sports import DataGrain, DataGrainKind
from dynamis.pipeline.quarantine import QuarantinedRecord
from dynamis.pipeline.streams import (
    DEFAULT_BATCH_SIZE,
    CanonicalStream,
    ProviderDomain,
    SourceAuthorities,
)


@dataclass(frozen=True, slots=True)
class SplTrialSource:
    """One locked registry key plus its immutable Bronze path."""

    key: str
    path: Path


class SplFreethrowAdapter:
    """Provider descriptor for the accepted SPL free-throw trials."""

    def __init__(
        self,
        *,
        trials: tuple[SplTrialSource, ...],
        version: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        if not trials:
            raise ValueError("the SPL adapter requires at least one declared trial")
        self._sources = trials
        self._version = version
        self._batch_size = batch_size
        self._canonicalizers: dict[str, SplTrialCanonicalizer] | None = None

    @property
    def dataset_id(self) -> str:
        return authorities.SPL_DATASET_ID

    @property
    def version(self) -> str:
        return self._version

    def algorithm_spec(self) -> AlgorithmSpec:
        return authorities.adapter_algorithm_spec()

    def canonicalizers(self) -> dict[str, SplTrialCanonicalizer]:
        if self._canonicalizers is None:
            built: dict[str, SplTrialCanonicalizer] = {}
            for source in self._sources:
                identity = identity_from_key(source.key)
                built[source.key] = SplTrialCanonicalizer(
                    source.path,
                    identity,
                    dataset_id=self.dataset_id,
                    batch_size=self._batch_size,
                )
            self._canonicalizers = built
        return self._canonicalizers

    def identities(self) -> tuple[SplTrialIdentity, ...]:
        return tuple(identity_from_key(source.key) for source in self._sources)

    def summaries(self) -> tuple[SplTrialSummary, ...]:
        return tuple(canonicalizer.summary() for canonicalizer in self.canonicalizers().values())

    # -- authorities -----------------------------------------------------

    def source_authorities(self) -> SourceAuthorities:
        sessions = {identity.session_date for identity in self.identities()}
        clocks = tuple(
            authorities.session_clock(session, authorities.SPL_SESSION_RATES_HZ[session])
            for session in sorted(sessions)
        )
        synchronizations = tuple(
            authorities.session_sync_spec(session, authorities.SPL_SESSION_RATES_HZ[session])
            for session in sorted(sessions)
        )
        skeletons = {
            canonicalizer.skeleton_id: authorities.skeleton_for(
                canonicalizer.identity.session_date, canonicalizer.keypoints
            )
            for canonicalizer in self.canonicalizers().values()
        }
        return SourceAuthorities(
            frames=(authorities.court_frame(),),
            clocks=clocks,
            synchronizations=synchronizations,
            skeletons=tuple(skeletons[key] for key in sorted(skeletons)),
        )

    # -- domain ----------------------------------------------------------

    def domain(self) -> ProviderDomain:
        participants_seen: list[tuple[str, str]] = []
        for identity in self.identities():
            key = (identity.session_date, identity.participant_id)
            if key not in participants_seen:
                participants_seen.append(key)
        subject_ids = sorted({participant for _, participant in participants_seen})
        subjects = tuple(
            Subject(
                dataset_id=self.dataset_id,
                subject_id=subject_id,
                sex="unspecified",
                notes="dataset-scoped participant identity, consistent across sessions",
            )
            for subject_id in subject_ids
        )
        participants = tuple(
            SessionParticipant(
                dataset_id=self.dataset_id,
                session_id=session_date,
                subject_id=subject_id,
                role=ParticipantRole.ATHLETE,
            )
            for session_date, subject_id in participants_seen
        )
        sessions = tuple(
            Session(
                dataset_id=self.dataset_id,
                session_id=session_date,
                kind=SessionKind.LABORATORY,
                label=f"SPL free-throw session {session_date}",
            )
            for session_date in sorted({date for date, _ in participants_seen})
        )
        trials = tuple(
            Trial(
                dataset_id=self.dataset_id,
                session_id=identity.session_date,
                trial_id=identity.trial_id,
                subject_id=identity.participant_id,
                label=f"free throw {identity.trial_id}",
            )
            for identity in self.identities()
        )
        streams = tuple(
            self._stream_record(canonicalizer) for canonicalizer in self.canonicalizers().values()
        )
        return ProviderDomain(
            session=None,
            sessions=sessions,
            subjects=subjects,
            participants=participants,
            trials=trials,
            streams=streams,
            authorities=self.source_authorities(),
            session_metadata={
                "sessions": sorted({identity.session_date for identity in self.identities()}),
                "participant_identity_consistent_across_sessions": True,
                "participant_ids": subject_ids,
                "trials": [
                    {
                        "session_date": identity.session_date,
                        "participant_id": identity.participant_id,
                        "trial_id": identity.trial_id,
                        "sampling_rate_hz": authorities.SPL_SESSION_RATES_HZ[identity.session_date],
                    }
                    for identity in self.identities()
                ],
                "measurement_note": (
                    "markerless 3D keypoints are provider model estimates "
                    "(MODEL_ESTIMATED), never raw instrument measurements"
                ),
                "feet_to_metre_scale": authorities.FEET_TO_METRE_SCALE,
                "cross_session_synchronization": False,
            },
        )

    def _stream_record(self, canonicalizer: SplTrialCanonicalizer) -> SensorStream:
        identity = canonicalizer.identity
        return SensorStream(
            dataset_id=self.dataset_id,
            session_id=identity.session_id,
            stream_id=authorities.pose_stream_id(identity.session_date, identity.trial_id),
            modality=Modality.POSE,
            measurement_class=MeasurementClass.MODEL_ESTIMATED,
            clock_id=f"spl-court-clock-{identity.session_date}",
            synchronization_spec_id=f"spl-source-provided-{identity.session_date}",
            coordinate_frame_id=authorities.COURT_FRAME_ID,
            skeleton_id=canonicalizer.skeleton_id,
            trial_id=identity.trial_id,
            subject_id=identity.participant_id,
            nominal_sampling_rate_hz=canonicalizer.sampling_rate_hz,
            si_units=("m",),
            source_unit=authorities.SOURCE_LENGTH_UNIT,
            stream_metadata={
                "source_length_unit": authorities.SOURCE_LENGTH_UNIT,
                "source_to_si_scale": authorities.FEET_TO_METRE_SCALE,
                "keypoint_count": len(canonicalizer.keypoints),
                "session_specific_availability": True,
            },
            data_grain=DataGrain(
                kind=DataGrainKind.TRIAL_SERIES,
                axes=("subject", "trial", "sample_index", "joint"),
            ),
        )

    # -- canonical streams ----------------------------------------------

    def streams(self) -> tuple[CanonicalStream, ...]:
        return tuple(canonicalizer.stream() for canonicalizer in self.canonicalizers().values())

    def quarantined(self) -> tuple[QuarantinedRecord, ...]:
        records: list[QuarantinedRecord] = []
        for canonicalizer in self.canonicalizers().values():
            records.extend(canonicalizer.summary().quarantined)
        return tuple(records)

    def cleanup(self) -> None:
        return None
