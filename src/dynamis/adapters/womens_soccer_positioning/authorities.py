"""Declared authorities for the Women's Soccer Positioning provider.

Provider truth: the workbook exposes device local wall-clock text timestamps and
geographic GNSS/GPS latitude/longitude positions. The provider metadata does
**not** explicitly declare a geodetic datum, so WGS 84 is carried as the
canonical interpretation --- an explicit, documented pipeline assumption --- not
as a provider declaration. Coordinates are passed through unchanged; no datum
transformation is applied. No timezone, no UTC epoch and no device identity are
declared upstream either, so the clock is session-monotonic and UTC stays null
rather than being guessed.
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

#: The source representation actually published by the provider.
SOURCE_COORDINATE_REPRESENTATION = "geographic GNSS latitude/longitude"
#: The provider publishes no explicit geodetic-datum declaration.
SOURCE_DATUM_DECLARATION = "not explicitly declared by the provider"
#: The datum the canonical GNSS contract interprets those values in.
CANONICAL_DATUM = "WGS 84"
#: Where that interpretation comes from: an inference, not provider truth.
DATUM_AUTHORITY = "inferred pipeline assumption"

#: Source sampling interval observed in the verified workbook (0.1 s).
NOMINAL_RATE_HZ = 10.0

#: Source unit of the ``speed(km/h)`` column and its exact SI scale.
SPEED_SOURCE_UNIT = "km/h"
SPEED_SOURCE_TO_SI_SCALE = 1.0 / 3.6


def wgs84_frame() -> CoordinateFrame:
    """Canonical geodetic frame for the provider's latitude/longitude columns.

    The provider publishes geographic GNSS/GPS latitude and longitude, but its
    metadata does not explicitly declare the geodetic datum. WGS 84 is the
    canonical interpretation (an inferred pipeline assumption), and the source
    values are passed through unchanged.
    """
    return CoordinateFrame(
        frame_id=WGS84_FRAME_ID,
        name=(
            "WGS 84 geodetic coordinates (canonical interpretation of an "
            "undeclared source datum; Women's Soccer Positioning)"
        ),
        kind=FrameKind.WORLD_GEODETIC,
        handedness=Handedness.RIGHT,
        x_direction=AxisDirection.EAST,
        y_direction=AxisDirection.NORTH,
        z_direction=AxisDirection.UP,
        origin_description=(
            "WGS 84 ellipsoid (canonical interpretation); geodetic latitude/longitude in "
            "degrees, ellipsoidal height in metres. Longitude increases east, latitude "
            "increases north."
        ),
        length_unit="m",
        description=(
            f"Source representation: {SOURCE_COORDINATE_REPRESENTATION} in decimal degrees. "
            f"Source datum: {SOURCE_DATUM_DECLARATION}. Canonical interpretation: "
            f"{CANONICAL_DATUM} ({DATUM_AUTHORITY}). No datum transformation is applied; "
            "source coordinate values are passed through unchanged."
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
