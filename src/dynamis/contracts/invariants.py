"""Cross-entity invariants that a single frozen contract cannot express.

These helpers are the executable form of the V1 Authority's non-negotiable
semantics. Registry validation, canonicalization, the SQLAlchemy loader and the
scientific test-suite all call them, so no rule is restated in two places.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol

from dynamis.contracts.domain import SensorStream, Session, SessionParticipant, Trial
from dynamis.contracts.enums import Modality, ParticipantRole, SessionKind
from dynamis.contracts.schemas import coordinate_frame_required, get_schema

_COLLECTIVE_KINDS = frozenset({SessionKind.TEAM, SessionKind.MATCH})


class InvariantError(ValueError):
    """Raised when a set of otherwise-valid contracts is mutually inconsistent."""


class _DatasetScoped(Protocol):
    dataset_id: str


def assert_single_dataset(*objects: _DatasetScoped) -> str:
    """Every object in a canonicalization unit must share one dataset identity.

    Executable form of "never merge identities across unrelated datasets":
    combining two datasets in one processing unit is an error, not a warning.
    """
    identifiers = {obj.dataset_id for obj in objects}
    if len(identifiers) != 1:
        raise InvariantError(
            "objects from different datasets must never be combined: "
            f"found dataset_id values {sorted(identifiers)}"
        )
    return identifiers.pop()


def assert_session_participation(
    session: Session,
    participants: Sequence[SessionParticipant],
) -> tuple[str, ...]:
    """Validate collective and individual session participation.

    A football match or team session must hold many players without duplicating
    the match identity, so collective sessions require at least two distinct
    subjects and every participant must be scoped to that session.
    """
    seen: set[tuple[str, ParticipantRole]] = set()
    subject_ids: list[str] = []
    for participant in participants:
        assert_single_dataset(session, participant)
        if participant.session_id != session.session_id:
            raise InvariantError(
                f"participant {participant.subject_id!r} belongs to session "
                f"{participant.session_id!r}, not {session.session_id!r}"
            )
        key = (participant.subject_id, participant.role)
        if key in seen:
            raise InvariantError(
                f"duplicate participation for subject {participant.subject_id!r} "
                f"in role {participant.role.value!r}"
            )
        seen.add(key)
        subject_ids.append(participant.subject_id)

    distinct = tuple(dict.fromkeys(subject_ids))
    if session.kind in _COLLECTIVE_KINDS:
        if len(distinct) < 2:
            raise InvariantError(
                f"a {session.kind.value} session requires at least two distinct participants; "
                f"found {len(distinct)}. Collective sessions must not be represented as "
                "one-subject sessions."
            )
    elif not distinct:
        raise InvariantError(f"session {session.session_id!r} declares no participants")
    return distinct


def assert_trial_subject_is_participant(
    trial: Trial,
    participants: Sequence[SessionParticipant],
) -> None:
    """A subject-scoped trial must reference a declared session participant."""
    if trial.subject_id is None:
        return
    known = {participant.subject_id for participant in participants}
    if trial.subject_id not in known:
        raise InvariantError(
            f"trial {trial.trial_id!r} references subject {trial.subject_id!r} "
            "which is not a participant of its session"
        )


def assert_stream_authorities(
    stream: SensorStream,
    *,
    session: Session,
    frame_ids: Iterable[str] = (),
    clock_ids: Iterable[str] = (),
    synchronization_ids: Iterable[str] = (),
    skeleton_ids: Iterable[str] = (),
    participants: Sequence[SessionParticipant] = (),
) -> None:
    """Validate a stream against its session and the declared support authorities."""
    assert_single_dataset(stream, session)
    if stream.session_id != session.session_id:
        raise InvariantError(
            f"stream {stream.stream_id!r} belongs to session {stream.session_id!r}, "
            f"not {session.session_id!r}"
        )

    if stream.clock_id not in set(clock_ids):
        raise InvariantError(f"stream declares unknown clock_id {stream.clock_id!r}")
    if stream.synchronization_spec_id not in set(synchronization_ids):
        raise InvariantError(
            f"stream declares unknown synchronization_spec_id {stream.synchronization_spec_id!r}"
        )
    if stream.coordinate_frame_id is not None and stream.coordinate_frame_id not in set(frame_ids):
        raise InvariantError(
            f"stream declares unknown coordinate_frame_id {stream.coordinate_frame_id!r}"
        )
    if stream.skeleton_id is not None and stream.skeleton_id not in set(skeleton_ids):
        raise InvariantError(f"stream declares unknown skeleton_id {stream.skeleton_id!r}")

    if coordinate_frame_required_for(stream.modality) and stream.coordinate_frame_id is None:
        raise InvariantError(
            f"modality {stream.modality.value!r} requires an explicit coordinate frame; "
            "a coordinate_frame_id column without a declared frame is insufficient"
        )

    if stream.subject_id is not None and participants:
        known_subjects = {participant.subject_id for participant in participants}
        if stream.subject_id not in known_subjects:
            raise InvariantError(
                f"stream references subject {stream.subject_id!r} which is not a participant "
                f"of session {session.session_id!r}"
            )


def coordinate_frame_required_for(modality: Modality) -> bool:
    """Schema-declared frame requirement for a modality."""
    return coordinate_frame_required(get_schema(modality))


def assert_modality_frame_requirement(
    modality: Modality,
    coordinate_frame_id: str | None,
) -> None:
    """Schema-level frame requirement, independent of any stream object."""
    if coordinate_frame_required_for(modality) and coordinate_frame_id is None:
        raise InvariantError(f"modality {modality.value!r} requires an explicit coordinate frame")
