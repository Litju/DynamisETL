"""Declared authorities for the SPL Open Data free-throw provider.

Source facts (``basketball/freethrow/README.md`` at the registry-pinned revision
``a3f9cffbde917b1e1747cedd6ec25dfab18c6051``):

* pose keypoints and ball XYZ are distributed in **feet**; conversion to metres is
  exactly ``0.3048``;
* the origin is the court centre and Z follows the right-hand rule (documented as
  pointing out of the court diagram);
* two acquisition generations exist (2024-08-28 at 30 fps, 2025-12-18 at 60 fps)
  and not every session was processed with the same pose model, so keypoint
  availability is session-specific;
* participant ids are consistent across sessions (P0001 is the same athlete).

The provider publishes an ordered keypoint table but no anatomical parent graph;
skeletons are therefore ``landmark_set`` authorities whose joint order is the
documented table order, with any name outside that table appended deterministically
and reported. No parent is ever invented.
"""

from __future__ import annotations

import hashlib

from dynamis.contracts import (
    AlgorithmKind,
    AlgorithmSpec,
    AxisDirection,
    Clock,
    CoordinateFrame,
    FrameKind,
    Handedness,
    JointDefinition,
    SkeletonDefinition,
    SkeletonTopology,
    SynchronizationMethod,
    SynchronizationSpec,
    Timebase,
)

SPL_DATASET_ID = "spl-open-data"
SPL_ADAPTER_ID = "spl_freethrow"

#: Documented session sampling rates (README session table).
SPL_SESSION_RATES_HZ: dict[str, float] = {
    "2024-08-28": 30.0,
    "2025-12-18": 60.0,
}

#: Exact documented feet -> metre scale.
FEET_TO_METRE_SCALE = 0.3048
SOURCE_LENGTH_UNIT = "ft"

COURT_FRAME_ID = "spl-court-center-m"
POSE_STREAM_ID_PREFIX = "pose"

#: The provider's documented 69-keypoint table, in keypoint-number order.
SPL_KEYPOINTS: tuple[str, ...] = (
    "NOSE",
    "LEFT_EYE",
    "RIGHT_EYE",
    "LEFT_EAR",
    "RIGHT_EAR",
    "NECK",
    "LEFT_SHOULDER",
    "RIGHT_SHOULDER",
    "LEFT_ELBOW",
    "RIGHT_ELBOW",
    "LEFT_WRIST",
    "RIGHT_WRIST",
    "LEFT_THUMB",
    "RIGHT_THUMB",
    "LEFT_PINKY",
    "RIGHT_PINKY",
    "LEFT_FIRST_FINGER_CMC",
    "LEFT_FIRST_FINGER_MCP",
    "LEFT_FIRST_FINGER_IP",
    "LEFT_FIRST_FINGER_DISTAL",
    "LEFT_SECOND_FINGER_MCP",
    "LEFT_SECOND_FINGER_PIP",
    "LEFT_SECOND_FINGER_DIP",
    "LEFT_SECOND_FINGER_DISTAL",
    "LEFT_THIRD_FINGER_MCP",
    "LEFT_THIRD_FINGER_PIP",
    "LEFT_THIRD_FINGER_DIP",
    "LEFT_THIRD_FINGER_DISTAL",
    "LEFT_FOURTH_FINGER_MCP",
    "LEFT_FOURTH_FINGER_PIP",
    "LEFT_FOURTH_FINGER_DIP",
    "LEFT_FOURTH_FINGER_DISTAL",
    "LEFT_FIFTH_FINGER_MCP",
    "LEFT_FIFTH_FINGER_PIP",
    "LEFT_FIFTH_FINGER_DIP",
    "LEFT_FIFTH_FINGER_DISTAL",
    "RIGHT_FIRST_FINGER_CMC",
    "RIGHT_FIRST_FINGER_MCP",
    "RIGHT_FIRST_FINGER_IP",
    "RIGHT_FIRST_FINGER_DISTAL",
    "RIGHT_SECOND_FINGER_MCP",
    "RIGHT_SECOND_FINGER_PIP",
    "RIGHT_SECOND_FINGER_DIP",
    "RIGHT_SECOND_FINGER_DISTAL",
    "RIGHT_THIRD_FINGER_MCP",
    "RIGHT_THIRD_FINGER_PIP",
    "RIGHT_THIRD_FINGER_DIP",
    "RIGHT_THIRD_FINGER_DISTAL",
    "RIGHT_FOURTH_FINGER_MCP",
    "RIGHT_FOURTH_FINGER_PIP",
    "RIGHT_FOURTH_FINGER_DIP",
    "RIGHT_FOURTH_FINGER_DISTAL",
    "RIGHT_FIFTH_FINGER_MCP",
    "RIGHT_FIFTH_FINGER_PIP",
    "RIGHT_FIFTH_FINGER_DIP",
    "RIGHT_FIFTH_FINGER_DISTAL",
    "MID_HIP",
    "LEFT_HIP",
    "RIGHT_HIP",
    "LEFT_KNEE",
    "RIGHT_KNEE",
    "LEFT_ANKLE",
    "RIGHT_ANKLE",
    "LEFT_BIG_TOE",
    "LEFT_SMALL_TOE",
    "LEFT_HEEL",
    "RIGHT_BIG_TOE",
    "RIGHT_SMALL_TOE",
    "RIGHT_HEEL",
)

_SPL_KEYPOINT_INDEX = {name: index for index, name in enumerate(SPL_KEYPOINTS)}


def ordered_keypoints(names: set[str]) -> tuple[str, ...]:
    """Documented order first, then names outside the table sorted deterministically."""
    documented = [name for name in SPL_KEYPOINTS if name in names]
    undocumented = sorted(name for name in names if name not in _SPL_KEYPOINT_INDEX)
    return tuple((*documented, *undocumented))


def skeleton_id_for(keypoints: tuple[str, ...]) -> str:
    """Content-addressed skeleton identity for one observed keypoint set."""
    digest = hashlib.sha1("|".join(keypoints).encode("utf-8")).hexdigest()
    return f"spl-freethrow-keypoints-{digest[:12]}"


def skeleton_for(session_date: str, keypoints: tuple[str, ...]) -> SkeletonDefinition:
    """Session-specific landmark set with no source parent graph."""
    undocumented = [name for name in keypoints if name not in _SPL_KEYPOINT_INDEX]
    return SkeletonDefinition(
        skeleton_id=skeleton_id_for(keypoints),
        name=f"SPL free-throw keypoints ({session_date}, {len(keypoints)} landmarks)",
        topology=SkeletonTopology.LANDMARK_SET,
        joint_count=len(keypoints),
        joints=tuple(
            JointDefinition(joint_id=index, joint_name=name, parent_joint_id=None)
            for index, name in enumerate(keypoints)
        ),
        description=(
            f"Session {session_date}: the provider documents keypoint availability as "
            "session-specific (different pose models across acquisition generations). "
            "Names are ordered by the documented keypoint table; "
            f"{len(undocumented)} name(s) outside the table are appended sorted and "
            "reported in the reconciliation receipt. No anatomical parent graph is "
            "published and none is invented."
        ),
    )


def court_frame() -> CoordinateFrame:
    """Court-centred frame in metres; source values pass through the declared scale."""
    return CoordinateFrame(
        frame_id=COURT_FRAME_ID,
        name="SPL basketball court-centred frame (metres)",
        kind=FrameKind.PITCH,
        handedness=Handedness.RIGHT,
        x_direction=AxisDirection.LONG_AXIS,
        y_direction=AxisDirection.SHORT_AXIS,
        z_direction=AxisDirection.UP,
        origin_description=(
            "Centre of the basketball court at floor level; the provider documents the "
            "origin at the court centre with Z following the right-hand rule."
        ),
        description=(
            "Provider values are distributed in feet and are converted to metres with the "
            "exact factor 0.3048 before canonicalization; no rotation, sign flip or implicit "
            "transform is applied. The provider's diagram documents the axis directions and "
            "the free-throw line location."
        ),
    )


def session_clock(session_date: str, sampling_rate_hz: float) -> Clock:
    """Session-nominal clock anchored at the first distributed frame."""
    return Clock(
        clock_id=f"spl-court-clock-{session_date}",
        timebase=Timebase.SESSION_MONOTONIC,
        frequency_hz=sampling_rate_hz,
        notes=(
            f"Session {session_date}: the provider distributes no absolute timestamps; "
            f"t_rel_ns is the frame ordinal divided by the documented {sampling_rate_hz:g} fps "
            "rate, measured from the first distributed frame. timestamp_utc_ns stays null "
            "because no UTC epoch is declared."
        ),
    )


def session_sync_spec(session_date: str, sampling_rate_hz: float) -> SynchronizationSpec:
    return SynchronizationSpec(
        sync_spec_id=f"spl-source-provided-{session_date}",
        method=SynchronizationMethod.SOURCE_PROVIDED,
        reference_clock_id=f"spl-court-clock-{session_date}",
        uncertainty_ms=None,
        notes=(
            f"Single provider export for session {session_date}: every keypoint shares the "
            f"documented {sampling_rate_hz:g} fps frame clock. The provider publishes no "
            "residual uncertainty, so none is asserted; no cross-session synchronization is "
            "claimed."
        ),
    )


def pose_stream_id(session_date: str, trial_id: str) -> str:
    return f"{POSE_STREAM_ID_PREFIX}-{session_date}-{trial_id}"


def adapter_algorithm_spec() -> AlgorithmSpec:
    return AlgorithmSpec(
        algorithm_id=SPL_ADAPTER_ID,
        name="SPL Open Data free-throw anti-corruption adapter",
        version="1",
        kind=AlgorithmKind.ADAPTER,
        description=(
            "Streams the pinned SPL free-throw trials into canonical pose_joint_sample "
            "streams: exact feet-to-metre conversion, session-specific keypoint availability, "
            "explicit unavailable keypoints and no invented parent graph."
        ),
    )


__all__ = [
    "COURT_FRAME_ID",
    "FEET_TO_METRE_SCALE",
    "SPL_ADAPTER_ID",
    "SPL_DATASET_ID",
    "SPL_KEYPOINTS",
    "SPL_SESSION_RATES_HZ",
    "adapter_algorithm_spec",
    "court_frame",
    "ordered_keypoints",
    "pose_stream_id",
    "session_clock",
    "session_sync_spec",
    "skeleton_for",
    "skeleton_id_for",
]
