"""Declared authorities for the SkillCorner Open Data provider.

Source facts (SkillCorner ``README.md`` and ``data/bodypose/README.md`` at the
registry-pinned revision ``4340d274572876239c154c90bc507a9b3250a656``):

* tracking is 10 fps, broadcast-video computer-vision output with an explicit
  ``is_detected`` flag; coordinates are metres with the origin at the pitch
  centre, x along the long side and y along the short side;
* body pose is 25 fps with 29 landmarks per player; ``pose_frame = 2.5 *
  tracking_frame`` and every fifth pose frame lands exactly on an even tracking
  frame without interpolation;
* pose/player XY and tracking XY are generated separately and may differ
  slightly; neither is ever overwritten;
* joint Z is accurate relative to the player's centroid but not necessarily in
  the pitch coordinate system, so the pose frame is a declared hybrid: pitch-
  global X/Y with a centroid-relative Z, and no hidden correction is applied;
* each joint carries ``p90_mae_cm``: a predicted error radius such that 90% of
  estimated key points sit within it relative to the player's pose. It is an
  error radius, never a probability or confidence.
"""

from __future__ import annotations

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
    SkeletonDisplayConnection,
    SkeletonTopology,
    SynchronizationMethod,
    SynchronizationSpec,
    Timebase,
)

SKILLCORNER_DATASET_ID = "skillcorner-opendata"
SKILLCORNER_ADAPTER_ID = "skillcorner_opendata"

MATCH_METADATA_KEY_PREFIX = "data/matches/"
MATCH_TRACKING_KEY_SUFFIX = "_tracking_extrapolated.jsonl"
MATCH_MATCH_JSON_SUFFIX = "_match.json"
POSE_ARCHIVE_PREFIX = "raw/"

TRACKING_FRAME_RATE_HZ = 10.0
POSE_FRAME_RATE_HZ = 25.0
#: Documented relation: ``pose_frame = 2.5 * tracking_frame``.
POSE_TRACKING_FRAME_RATIO = 2.5
TRACKING_INTERVAL_NS = 100_000_000
POSE_INTERVAL_NS = 40_000_000

CLOCK_ID = "skillcorner-match-clock"
SYNC_SPEC_ID = "skillcorner-source-provided-match-clock"
TRACKING_FRAME_ID = "skillcorner-pitch-long-short-m"
POSE_FRAME_ID = "skillcorner-pose-hybrid-m"
POSE_SKELETON_ID = "skillcorner-bodypose-29-landmarks"
SKILLCORNER_SOURCE_REVISION = "4340d274572876239c154c90bc507a9b3250a656"

#: The provider's documented 29-joint order (``data/bodypose/README.md``). The
#: JSON member order in the archive is alphabetical and is deliberately not used
#: as the authority.
POSE_LANDMARKS: tuple[str, ...] = (
    "nose",
    "neck",
    "lEye",
    "rEye",
    "lEar",
    "rEar",
    "lShoulder",
    "rShoulder",
    "lElbow",
    "rElbow",
    "lWrist",
    "rWrist",
    "lThumb",
    "rThumb",
    "lPinky",
    "rPinky",
    "midHip",
    "lHip",
    "rHip",
    "lKnee",
    "rKnee",
    "lAnkle",
    "rAnkle",
    "lHeel",
    "rHeel",
    "lBigToe",
    "rBigToe",
    "lSmallToe",
    "rSmallToe",
)

#: Provider display topology from ``src/data/pose_loading.py:SKELETON`` at the
#: pinned source revision. These are drawable landmark connections, not an
#: inferred parent graph or a processor-defined analytical segment list.
POSE_DISPLAY_CONNECTIONS: tuple[tuple[str, str], ...] = (
    ("nose", "neck"),
    ("nose", "lEye"),
    ("nose", "rEye"),
    ("lEye", "lEar"),
    ("rEye", "rEar"),
    ("neck", "lShoulder"),
    ("neck", "rShoulder"),
    ("neck", "midHip"),
    ("lShoulder", "lElbow"),
    ("lElbow", "lWrist"),
    ("rShoulder", "rElbow"),
    ("rElbow", "rWrist"),
    ("lWrist", "lThumb"),
    ("lWrist", "lPinky"),
    ("rWrist", "rThumb"),
    ("rWrist", "rPinky"),
    ("midHip", "lHip"),
    ("midHip", "rHip"),
    ("lHip", "lKnee"),
    ("lKnee", "lAnkle"),
    ("rHip", "rKnee"),
    ("rKnee", "rAnkle"),
    ("lAnkle", "lHeel"),
    ("lAnkle", "lBigToe"),
    ("lBigToe", "lSmallToe"),
    ("rAnkle", "rHeel"),
    ("rAnkle", "rBigToe"),
    ("rBigToe", "rSmallToe"),
)

POSE_ERROR_SOURCE_FIELD = "p90_mae_cm"
#: Exact centimetre -> metre scale for the provider's error radius.
POSE_ERROR_SOURCE_TO_SI_SCALE = 0.01
POSE_ERROR_SEMANTICS = (
    "90th-percentile predicted error radius relative to the player's pose "
    "(SkillCorner p90_mae_cm); never a probability or confidence"
)

#: Source statements preserved verbatim as metadata, not re-derived.
HYBRID_GEOMETRY_STATEMENT = (
    "Position on the z-axis is accurate relatively to the player's centroid, but not "
    "necessarily in the pitch coordinate system (SkillCorner body pose limitation)."
)
ALIGNMENT_STATEMENT = (
    "XY Tracking data and Body Pose are generated separately. This can cause minor "
    "misalignments between the XY attributes (positions, is_detected flag) and the "
    "Body Pose joints (SkillCorner body pose limitation)."
)


def tracking_stream_id(period: int) -> str:
    """Canonical tracking stream identity for one period."""
    return f"tracking-period-{period}"


def pose_stream_id(period: int) -> str:
    """Canonical pose stream identity for one period."""
    return f"pose-period-{period}"


def pitch_frame(pitch_length_m: float, pitch_width_m: float) -> CoordinateFrame:
    """Pitch-centred X/Y frame declared by the provider's tracking documentation.

    X/Y are pitch-global metres with the origin at the pitch centre. Z is the
    source value passed through unchanged: the release documents no global
    registration for every Z channel, so the axis direction is deliberately left
    unspecified instead of being asserted.
    """
    return CoordinateFrame(
        frame_id=TRACKING_FRAME_ID,
        name="SkillCorner pitch-centred X/Y (metres)",
        kind=FrameKind.PITCH,
        handedness=Handedness.UNSPECIFIED,
        x_direction=AxisDirection.LONG_AXIS,
        y_direction=AxisDirection.SHORT_AXIS,
        z_direction=AxisDirection.UNSPECIFIED,
        origin_description=(
            f"Centre of the {pitch_length_m:g} m x {pitch_width_m:g} m pitch; x runs along "
            "the long side and y along the short side, metres."
        ),
        description=(
            "Provider tracking documentation: metres, centre-of-pitch origin, x long side, "
            "y short side. Z is preserved exactly as the source provides it (the ball is the "
            "only object with a distributed Z) and no global registration or absolute-height "
            "claim is made here. Handedness is left unspecified because the provider does not "
            "declare it."
        ),
    )


def pose_hybrid_frame() -> CoordinateFrame:
    """Declared hybrid pose frame: pitch-global X/Y with centroid-relative Z.

    The provider states that joint Z is accurate relative to the player's centroid
    but not necessarily in the pitch coordinate system. Declaring the triple as a
    globally registered Euclidean pitch frame would be false, so X/Y carry the
    provider's pitch-global directions while Z is explicitly unspecified; no
    correction, height interpretation or hidden transform is applied.
    """
    return CoordinateFrame(
        frame_id=POSE_FRAME_ID,
        name="SkillCorner body-pose hybrid frame (pitch-global X/Y, centroid-relative Z)",
        kind=FrameKind.PITCH,
        handedness=Handedness.UNSPECIFIED,
        x_direction=AxisDirection.LONG_AXIS,
        y_direction=AxisDirection.SHORT_AXIS,
        z_direction=AxisDirection.UNSPECIFIED,
        origin_description=(
            "X/Y: pitch centre in metres on the provider's long-axis/short-axis convention. "
            "Z: relative to the player's own centroid, not registered in the pitch "
            "coordinate system."
        ),
        description=(
            f"Hybrid geometry declared by the source, not a pipeline transform. "
            f"{HYBRID_GEOMETRY_STATEMENT} No hidden correction, no absolute-height "
            "interpretation and no implicit frame transform exists in this pipeline."
        ),
    )


def match_clock() -> Clock:
    """Source match-time clock shared by the 25 Hz pose and 10 Hz tracking streams.

    ``t_rel_ns`` is the provider's own match-time timestamp parsed exactly
    (centisecond precision). Period 1 runs from 00:00:00 and period 2 continues the
    provider's clock from 45:00:00, so each canonical file is one period and never
    mixes the two clock labels.
    """
    return Clock(
        clock_id=CLOCK_ID,
        timebase=Timebase.SESSION_MONOTONIC,
        frequency_hz=None,
        notes=(
            "Provider match-time clock parsed exactly from the source timestamp text "
            "(HH:MM:SS.cc). Period 1 origin is the kickoff timestamp 00:00:00; period 2 "
            "continues the provider's official clock from 45:00:00, which is why pose and "
            "tracking are split into per-period streams. Stream rates (25 Hz pose, 10 Hz "
            "tracking) are declared per stream and are not clock properties."
        ),
    )


def source_sync_spec() -> SynchronizationSpec:
    """Both streams carry the provider's match clock in one synchronized export."""
    return SynchronizationSpec(
        sync_spec_id=SYNC_SPEC_ID,
        method=SynchronizationMethod.SOURCE_PROVIDED,
        reference_clock_id=CLOCK_ID,
        notes=(
            "Single provider export: 25 Hz body pose and 10 Hz tracking carry the same "
            "provider match clock with the documented pose_frame = 2.5 * tracking_frame "
            "relation. The provider publishes no independent synchronization residual; "
            "the pipeline measures exact-coincidence timestamp/ID/XY residuals as V&V "
            "evidence without forcing equality."
        ),
    )


def pose_skeleton() -> SkeletonDefinition:
    """Source-published landmark list plus its separate display topology."""
    return SkeletonDefinition(
        skeleton_id=POSE_SKELETON_ID,
        name="SkillCorner body pose 29-landmark set",
        topology=SkeletonTopology.LANDMARK_SET,
        joint_count=len(POSE_LANDMARKS),
        joints=tuple(
            JointDefinition(joint_id=index, joint_name=name, parent_joint_id=None)
            for index, name in enumerate(POSE_LANDMARKS)
        ),
        display_connections=tuple(
            SkeletonDisplayConnection(start_joint_name=start, end_joint_name=end)
            for start, end in POSE_DISPLAY_CONNECTIONS
        ),
        description=(
            "SkillCorner publishes an ordered landmark list (data/bodypose/README.md at the "
            f"pinned revision {SKILLCORNER_SOURCE_REVISION}) and no anatomical parent graph. "
            "Parent ids are deliberately absent; the JSON member order in the archive is "
            "alphabetical and is not the authority. The provider's SKELETON display pairs "
            "are retained separately as drawable connections."
        ),
    )


def adapter_algorithm_spec() -> AlgorithmSpec:
    """Deterministic algorithm identity for the SkillCorner adapter."""
    return AlgorithmSpec(
        algorithm_id=SKILLCORNER_ADAPTER_ID,
        name="SkillCorner Open Data anti-corruption adapter",
        version="1",
        kind=AlgorithmKind.ADAPTER,
        description=(
            "Streams the pinned SkillCorner match metadata, 10 Hz tracking JSONL and 25 Hz "
            "body-pose archive member into canonical tracking_sample and pose_joint_sample "
            "streams with explicit frame, clock, skeleton and synchronization authorities."
        ),
    )
