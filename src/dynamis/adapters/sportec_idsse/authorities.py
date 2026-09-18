"""Declared authorities for the DFL/Sportec IDSSE provider.

Both geometric systems are taken from the provider's reference client (kloppy,
which the dataset card names as the supported reader) rather than invented:

* tracking positions use a pitch-centred origin (``Origin.CENTER``), metres;
* event positions use a bottom-left origin, metres, with the same axis
  orientation.

The corner-to-centre conversion is therefore a pure translation and is declared
as an explicit :class:`FrameTransform`; no implicit sign flip or axis swap is
performed anywhere in the adapter.
"""

from __future__ import annotations

from datetime import datetime

from dynamis.contracts import (
    AxisDirection,
    Clock,
    CoordinateFrame,
    FrameKind,
    FrameTransform,
    Handedness,
    SynchronizationMethod,
    SynchronizationSpec,
    Timebase,
)

IDSSE_DATASET_ID = "dfl-sportec-idsse"
CENTER_FRAME_ID = "dfl-pitch-center-m"
CORNER_FRAME_ID = "dfl-pitch-corner-m"
CLOCK_ID = "dfl-sportec-utc"
SYNC_SPEC_ID = "dfl-source-provided"

SPORTEC_FPS = 25
FRAME_INTERVAL_NS = 1_000_000_000 // SPORTEC_FPS

EVENT_STREAM_ID = "events"


def tracking_stream_id(period_id: str) -> str:
    """Canonical tracking stream identity for one period (single authority)."""
    return f"tracking-{period_id}"


REFERENCE_CLIENT = (
    "kloppy 3.19.0 SportecTrackingDataCoordinateSystem (Origin.CENTER, "
    "VerticalOrientation.BOTTOM_TO_TOP) and SportecEventDataCoordinateSystem "
    "(Origin.BOTTOM_LEFT, same executable orientation), both in metres with "
    "MetricPitchDimensions X=length, Y=width. Kloppy prose is inconsistent "
    "(the event docstring says top-to-bottom) but its executable properties are "
    "authoritative. Independent RES-103 oracle: all 1,387 coordinate-bearing "
    "canonical J03WPY events agree with the executable Kloppy transform within "
    "1.8e-15 m (max |dx|) and 0 m (max |dy|)"
)


def center_frame(pitch_x_m: float, pitch_y_m: float) -> CoordinateFrame:
    """Pitch-centred tracking frame declared by the provider's reference client."""
    return CoordinateFrame(
        frame_id=CENTER_FRAME_ID,
        name="DFL/Sportec pitch-centred frame (metres)",
        kind=FrameKind.PITCH,
        handedness=Handedness.RIGHT,
        x_direction=AxisDirection.LONG_AXIS,
        y_direction=AxisDirection.SHORT_AXIS,
        z_direction=AxisDirection.UP,
        origin_description=(
            f"Centre of the pitch ({pitch_x_m:g} m x {pitch_y_m:g} m) at z=0 on the "
            "pitch surface; x runs along the long axis, y along the short axis."
        ),
        length_unit="m",
        description=(
            "Tracking X/Y/Z pass through unchanged from the provider's centre-origin "
            f"system. The goal-to-goal direction of +x is not declared upstream. "
            f"Reference: {REFERENCE_CLIENT}."
        ),
    )


def corner_to_center_transform(pitch_x_m: float, pitch_y_m: float) -> FrameTransform:
    """Declared translation from the event system into the centre frame."""
    return FrameTransform(
        source_frame_id=CORNER_FRAME_ID,
        target_frame_id=CENTER_FRAME_ID,
        translation_m=(-pitch_x_m / 2.0, -pitch_y_m / 2.0, 0.0),
        rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
        notes=(
            "Pure origin translation between two systems that share axis directions: "
            "the provider publishes event coordinates with a bottom-left origin "
            f"(x in [0, {pitch_x_m:g}], y in [0, {pitch_y_m:g}]) and tracking coordinates "
            f"with a centre origin. Verified against the executable reference client by an "
            f"independent RES-103 oracle over all coordinate-bearing J03WPY events. "
            f"{REFERENCE_CLIENT}."
        ),
    )


def corner_frame(pitch_x_m: float, pitch_y_m: float) -> CoordinateFrame:
    """The provider's event-position frame, declared as a child of the centre frame."""
    return CoordinateFrame(
        frame_id=CORNER_FRAME_ID,
        name="DFL/Sportec event frame (bottom-left origin, metres)",
        kind=FrameKind.PITCH,
        handedness=Handedness.RIGHT,
        x_direction=AxisDirection.LONG_AXIS,
        y_direction=AxisDirection.SHORT_AXIS,
        z_direction=AxisDirection.UP,
        origin_description=(
            f"Bottom-left pitch corner of the {pitch_x_m:g} m x {pitch_y_m:g} m pitch; "
            "x runs along the long axis, y along the short axis."
        ),
        length_unit="m",
        parent_frame_id=CENTER_FRAME_ID,
        transform=corner_to_center_transform(pitch_x_m, pitch_y_m),
        description=(
            "Source frame of the provider's event X-Position/Y-Position attributes, "
            f"resolved into the centre frame through the declared transform. {REFERENCE_CLIENT}."
        ),
    )


def utc_clock(kickoff_utc: datetime) -> Clock:
    """Provider UTC clock at 25 Hz with ``t_rel_ns`` measured from kickoff."""
    return Clock(
        clock_id=CLOCK_ID,
        timebase=Timebase.UTC,
        frequency_hz=float(SPORTEC_FPS),
        epoch_utc=kickoff_utc,
        notes=(
            "Source timestamps are UTC with an explicit offset. t_rel_ns = source UTC "
            "timestamp minus the provider-declared KickoffTime; the frame counter advances "
            f"exactly {FRAME_INTERVAL_NS} ns per frame (25 Hz)."
        ),
    )


def source_sync_spec() -> SynchronizationSpec:
    """Tracking frames and events share one provider UTC clock in one export."""
    return SynchronizationSpec(
        sync_spec_id=SYNC_SPEC_ID,
        method=SynchronizationMethod.SOURCE_PROVIDED,
        reference_clock_id=CLOCK_ID,
        notes=(
            "Single provider export (DFL/Sportec): tracking frames and events are already "
            "on the provider UTC clock with an exactly 40 ms frame interval. The provider "
            "publishes no residual uncertainty, so none is asserted."
        ),
    )
