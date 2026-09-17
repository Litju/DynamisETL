"""Declared authorities for the Women's Soccer Positioning provider.

Provider truth: the workbook exposes device local wall-clock text timestamps and
WGS 84 geodetic positions. No timezone, no UTC epoch and no device identity are
declared upstream, so the clock is session-monotonic and UTC stays null rather
than being guessed.
"""

from __future__ import annotations

from dynamis.contracts import (
    AxisDirection,
    Clock,
    CoordinateFrame,
    FrameKind,
    Handedness,
    SynchronizationMethod,
    SynchronizationSpec,
    Timebase,
)

WOMENS_DATASET_ID = "womens-soccer-positioning"
WOMENS_VERSION = "1.0"
WOMENS_SESSION_ID = "J01"

WGS84_FRAME_ID = "wsp-wgs84-geodetic"
CLOCK_ID = "wsp-local-clock"
SYNC_SPEC_ID = "wsp-source-provided"

#: Source sampling interval observed in the verified workbook (0.1 s).
NOMINAL_RATE_HZ = 10.0

#: Source unit of the ``speed(km/h)`` column and its exact SI scale.
SPEED_SOURCE_UNIT = "km/h"
SPEED_SOURCE_TO_SI_SCALE = 1.0 / 3.6


def wgs84_frame() -> CoordinateFrame:
    """Geodetic WGS 84 frame implied by the provider's latitude/longitude pair."""
    return CoordinateFrame(
        frame_id=WGS84_FRAME_ID,
        name="WGS 84 geodetic coordinates (Women's Soccer Positioning)",
        kind=FrameKind.WORLD_GEODETIC,
        handedness=Handedness.RIGHT,
        x_direction=AxisDirection.EAST,
        y_direction=AxisDirection.NORTH,
        z_direction=AxisDirection.UP,
        origin_description=(
            "WGS 84 ellipsoid; geodetic latitude/longitude in degrees, ellipsoidal height "
            "in metres. Longitude increases east, latitude increases north."
        ),
        length_unit="m",
        description=(
            "The provider publishes only the (latitude, longitude, speed) triple; the "
            "geodetic frame is the geometric authority for those columns."
        ),
    )


def local_clock(*, origin_local: str) -> Clock:
    """Session-monotonic clock anchored at the earliest workbook timestamp."""
    return Clock(
        clock_id=CLOCK_ID,
        timebase=Timebase.SESSION_MONOTONIC,
        frequency_hz=NOMINAL_RATE_HZ,
        notes=(
            "Provider timestamps are device local wall-clock text with no timezone or UTC "
            f"declaration. t_rel_ns is measured from the session origin {origin_local} "
            "(earliest accepted sample of the workbook); timestamp_utc_ns stays null."
        ),
    )


def source_sync_spec() -> SynchronizationSpec:
    """All sheets come from one provider export on one local clock."""
    return SynchronizationSpec(
        sync_spec_id=SYNC_SPEC_ID,
        method=SynchronizationMethod.SOURCE_PROVIDED,
        reference_clock_id=CLOCK_ID,
        notes=(
            "Single provider export: every sheet is timestamped on the same device local "
            "clock. The provider publishes no residual uncertainty, so none is asserted."
        ),
    )
