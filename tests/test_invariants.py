"""Cross-entity invariants, including the multi-subject match requirement."""

from __future__ import annotations

import pytest

from dynamis.contracts import (
    MeasurementClass,
    Modality,
    ParticipantRole,
    SensorStream,
    Session,
    SessionKind,
    SessionParticipant,
    Trial,
)
from dynamis.contracts.invariants import (
    InvariantError,
    assert_modality_frame_requirement,
    assert_session_participation,
    assert_single_dataset,
    assert_stream_authorities,
    assert_trial_subject_is_participant,
    coordinate_frame_required_for,
)

DATASET = "synthetic-foundation"


def _session(
    session_id: str = "syn-session-0001", kind: SessionKind = SessionKind.MATCH
) -> Session:
    return Session(dataset_id=DATASET, session_id=session_id, kind=kind)


def _participant(subject_id: str, session_id: str = "syn-session-0001") -> SessionParticipant:
    return SessionParticipant(
        dataset_id=DATASET,
        session_id=session_id,
        subject_id=subject_id,
        role=ParticipantRole.PLAYER,
    )


def test_one_match_session_holds_many_players_without_duplicating_identity() -> None:
    session = _session()
    participants = tuple(_participant(f"syn-subject-{index:04d}") for index in range(11))
    subjects = assert_session_participation(session, participants)
    assert len(subjects) == 11
    assert session.session_id == "syn-session-0001"


def test_collective_session_cannot_be_represented_as_one_subject() -> None:
    with pytest.raises(InvariantError, match="at least two distinct participants"):
        assert_session_participation(_session(), (_participant("syn-subject-0001"),))


def test_individual_session_requires_at_least_one_participant() -> None:
    with pytest.raises(InvariantError, match="declares no participants"):
        assert_session_participation(_session(kind=SessionKind.LABORATORY), ())
    assert assert_session_participation(
        _session(kind=SessionKind.LABORATORY), (_participant("syn-subject-0001"),)
    ) == ("syn-subject-0001",)


def test_duplicate_and_cross_session_participation_are_rejected() -> None:
    with pytest.raises(InvariantError, match="duplicate participation"):
        assert_session_participation(
            _session(),
            (_participant("syn-subject-0001"), _participant("syn-subject-0001")),
        )
    with pytest.raises(InvariantError, match="belongs to session"):
        assert_session_participation(
            _session(),
            (
                _participant("syn-subject-0001"),
                _participant("syn-subject-0002", session_id="other-session"),
            ),
        )


def test_identities_are_never_merged_across_datasets() -> None:
    other = Session(dataset_id="other-dataset", session_id="syn-session-0001")
    with pytest.raises(InvariantError, match="different datasets"):
        assert_single_dataset(_session(), other)


def test_trial_subject_must_be_a_session_participant() -> None:
    participants = (_participant("syn-subject-0001"), _participant("syn-subject-0002"))
    ok = Trial(
        dataset_id=DATASET,
        session_id="syn-session-0001",
        trial_id="syn-trial-0001",
        subject_id="syn-subject-0001",
    )
    assert_trial_subject_is_participant(ok, participants)

    stranger = Trial(
        dataset_id=DATASET,
        session_id="syn-session-0001",
        trial_id="syn-trial-0002",
        subject_id="syn-subject-9999",
    )
    with pytest.raises(InvariantError, match="not a participant"):
        assert_trial_subject_is_participant(stranger, participants)

    match_level = Trial(
        dataset_id=DATASET, session_id="syn-session-0001", trial_id="syn-trial-0003"
    )
    assert_trial_subject_is_participant(match_level, participants)


def _stream(**overrides: object) -> SensorStream:
    base: dict[str, object] = {
        "dataset_id": DATASET,
        "session_id": "syn-session-0001",
        "stream_id": "imu-00000001",
        "modality": Modality.IMU,
        "measurement_class": MeasurementClass.RAW_MEASURED,
        "clock_id": "syn-clock",
        "synchronization_spec_id": "syn-sync",
        "coordinate_frame_id": "syn-frame-imu-body",
        "si_units": ("m/s**2", "rad/s"),
    }
    base.update(overrides)
    return SensorStream.model_validate(base)


def test_stream_must_reference_declared_authorities() -> None:
    participants = (
        _participant("syn-subject-0001"),
        _participant("syn-subject-0002"),
    )
    assert_stream_authorities(
        _stream(),
        session=_session(),
        frame_ids={"syn-frame-imu-body"},
        clock_ids={"syn-clock"},
        synchronization_ids={"syn-sync"},
        participants=participants,
    )
    with pytest.raises(InvariantError, match="unknown clock_id"):
        assert_stream_authorities(
            _stream(),
            session=_session(),
            frame_ids={"syn-frame-imu-body"},
            clock_ids=set(),
            synchronization_ids={"syn-sync"},
        )
    with pytest.raises(InvariantError, match="unknown synchronization_spec_id"):
        assert_stream_authorities(
            _stream(),
            session=_session(),
            frame_ids={"syn-frame-imu-body"},
            clock_ids={"syn-clock"},
            synchronization_ids=set(),
        )
    with pytest.raises(InvariantError, match="unknown coordinate_frame_id"):
        assert_stream_authorities(
            _stream(),
            session=_session(),
            frame_ids=set(),
            clock_ids={"syn-clock"},
            synchronization_ids={"syn-sync"},
        )


def test_modalities_that_need_a_frame_cannot_omit_it() -> None:
    assert coordinate_frame_required_for(Modality.IMU)
    assert coordinate_frame_required_for(Modality.FORCE)
    assert coordinate_frame_required_for(Modality.POSE)
    assert not coordinate_frame_required_for(Modality.LPT)
    assert not coordinate_frame_required_for(Modality.EVENT)

    with pytest.raises(InvariantError, match="requires an explicit coordinate frame"):
        assert_modality_frame_requirement(Modality.FORCE, None)
    assert_modality_frame_requirement(Modality.FORCE, "syn-frame-force-plate")

    with pytest.raises(InvariantError, match="requires an explicit coordinate frame"):
        assert_stream_authorities(
            _stream(modality=Modality.FORCE, coordinate_frame_id=None),
            session=_session(),
            clock_ids={"syn-clock"},
            synchronization_ids={"syn-sync"},
        )


def test_stream_subject_must_be_a_participant_when_scoped() -> None:
    participants = (
        _participant("syn-subject-0001"),
        _participant("syn-subject-0002"),
    )
    with pytest.raises(InvariantError, match="not a participant"):
        assert_stream_authorities(
            _stream(subject_id="syn-subject-9999"),
            session=_session(),
            frame_ids={"syn-frame-imu-body"},
            clock_ids={"syn-clock"},
            synchronization_ids={"syn-sync"},
            participants=participants,
        )


def test_pose_stream_requires_a_skeleton_authority() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _stream(modality=Modality.POSE, stream_id="pose-00000001")
    pose = _stream(
        modality=Modality.POSE,
        stream_id="pose-00000001",
        skeleton_id="syn-skeleton-lower-limb-3joint",
    )
    assert pose.skeleton_id is not None
    with pytest.raises(ValidationError):
        _stream(skeleton_id="syn-skeleton-lower-limb-3joint")
