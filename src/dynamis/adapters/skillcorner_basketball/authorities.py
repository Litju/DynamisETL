"""Source authorities for SkillCorner's basketball release."""

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
from dynamis.contracts.sports import (
    ClockDirection,
    ClockKind,
    ClockMapping,
    SpatialReference,
    SurfaceGeometry,
)

DATASET_ID = "skillcorner-basketball-opendata"
ADAPTER_ID = "skillcorner_basketball_opendata"
NAMESPACE = ADAPTER_ID
COURT_REFERENCE_ID = "skillcorner-basketball-court-ft"
COURT_FRAME_ID = "skillcorner-basketball-court-m"
COURT_SURFACE_ID = "skillcorner-basketball-full-court"
WALL_CLOCK_ID = "skillcorner-basketball-wall-clock"
SYNC_SPEC_ID = "skillcorner-basketball-source-wall-clock"
FRAME_RATE_HZ = 25.0
FT_TO_M = 0.3048
COURT_LENGTH_FT = 94.0
COURT_WIDTH_FT = 50.0


def coordinate_frame() -> CoordinateFrame:
    return CoordinateFrame(
        frame_id=COURT_FRAME_ID,
        name="SkillCorner basketball court, source axes in SI metres",
        kind=FrameKind.PITCH,
        handedness=Handedness.UNSPECIFIED,
        x_direction=AxisDirection.LONG_AXIS,
        y_direction=AxisDirection.SHORT_AXIS,
        z_direction=AxisDirection.UP,
        origin_description=(
            "Source court centre. X follows the provider's court-length axis; Y follows "
            "the court-width axis. Source coordinates are feet and canonical tracking "
            "coordinates are explicitly converted to metres."
        ),
        length_unit="m",
        description=(
            "No sign flip, rotation, origin shift or player-side normalization is applied. "
            "The display inverts SVG screen Y only."
        ),
    )


def spatial_reference() -> SpatialReference:
    return SpatialReference(
        spatial_reference_id=COURT_REFERENCE_ID,
        version="1",
        units="ft",
        origin={"x": 0.0, "y": 0.0, "z": 0.0},
        axis_orientation={
            "x": "court_length_left_to_right_from_camera",
            "y": "court_width_bottom_to_top_from_camera",
            "z": "height",
        },
        handedness="unspecified",
        canonical_display_transform={
            "kind": "identity",
            "units": "ft",
            "screen_y_inversion": "presentation_only",
        },
        source_transform={
            "kind": "unit_scale",
            "from_unit": "ft",
            "to_unit": "m",
            "scale": FT_TO_M,
        },
        period_direction_semantics={
            "source_period_is_authoritative": True,
            "court_end_normalization": False,
        },
    )


def surface_geometry() -> SurfaceGeometry:
    return SurfaceGeometry(
        surface_id=COURT_SURFACE_ID,
        version="1",
        sport_id="basketball",
        name="Basketball full court",
        dimensions={"length_ft": COURT_LENGTH_FT, "width_ft": COURT_WIDTH_FT},
        spatial_reference_id=COURT_REFERENCE_ID,
        spatial_reference_version="1",
        source_authority="SkillCorner basketball tracking documentation",
    )


def clock() -> Clock:
    return Clock(
        clock_id=WALL_CLOCK_ID,
        timebase=Timebase.SESSION_MONOTONIC,
        frequency_hz=None,
        notes=(
            "wallClock is provider wall time in milliseconds from the start of the video. "
            "Frame cadence is 25 fps. gameClock and shotClock remain separate source "
            "countdown clocks and are never used to invent elapsed wall time."
        ),
    )


def synchronization() -> SynchronizationSpec:
    return SynchronizationSpec(
        sync_spec_id=SYNC_SPEC_ID,
        method=SynchronizationMethod.SOURCE_PROVIDED,
        reference_clock_id=WALL_CLOCK_ID,
        notes=(
            "Tracking and Dynamic Events share the source period and exact frame/wallClock "
            "keys. A countdown gameClock with optional shotClock is used only when it resolves "
            "to one frame; countdown clocks never invent elapsed wall time."
        ),
    )


def clock_mappings() -> tuple[ClockMapping, ...]:
    authority = "SkillCorner basketball tracking_data and Dynamic Events documentation"
    return (
        ClockMapping(
            mapping_id="skillcorner-basketball-wall-clock",
            version="1",
            clock_kind=ClockKind.WALL_TIME,
            direction=ClockDirection.MONOTONIC,
            source_unit="ms",
            scale_to_ns=1_000_000,
            period_origin_ns=0,
            authority=authority,
            evidence={"source_field": "wallClock", "definition": "ms since video start"},
        ),
        ClockMapping(
            mapping_id="skillcorner-basketball-game-clock",
            version="1",
            clock_kind=ClockKind.GAME_CLOCK,
            direction=ClockDirection.COUNT_DOWN,
            source_unit="s",
            scale_to_ns=1_000_000_000,
            source_origin=600.0,
            period_origin_ns=0,
            authority=authority,
            evidence={
                "source_field": "gameClock",
                "source_period_field": "period",
                "semantics": "countdown value is preserved; each period has its own origin",
            },
        ),
        ClockMapping(
            mapping_id="skillcorner-basketball-shot-clock",
            version="1",
            clock_kind=ClockKind.SHOT_CLOCK,
            direction=ClockDirection.COUNT_DOWN,
            source_unit="s",
            scale_to_ns=1_000_000_000,
            source_origin=24.0,
            period_origin_ns=0,
            authority=authority,
            evidence={
                "source_field": "shotClock",
                "semantics": "countdown resets within periods; not a game-time join key",
            },
        ),
    )


__all__ = [
    "ADAPTER_ID",
    "COURT_FRAME_ID",
    "COURT_LENGTH_FT",
    "COURT_REFERENCE_ID",
    "COURT_SURFACE_ID",
    "COURT_WIDTH_FT",
    "DATASET_ID",
    "FRAME_RATE_HZ",
    "FT_TO_M",
    "NAMESPACE",
    "SYNC_SPEC_ID",
    "WALL_CLOCK_ID",
    "clock",
    "clock_mappings",
    "coordinate_frame",
    "spatial_reference",
    "surface_geometry",
    "synchronization",
]
