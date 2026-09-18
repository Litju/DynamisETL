"""Declared authorities for the White CMJ accelerometer + vGRF release.

Evidence used (verified locally against the deposited ``cmj_dataset_both.npz``
and the provider's own preparation code, ``scripts/prepare_dataset.py`` in the
linked ``acc2grf-cmj`` repository):

* the distributed accelerometer member is a full per-trial recording at 250 Hz
  in ``g``, not a pre-cut window;
* the distributed vGRF member is a per-trial pre-takeoff curve at 1000 Hz,
  already normalised by body weight (standing level ~1.0, takeoff ~0.0), whose
  last sample is the takeoff instant;
* both members carry a per-trial takeoff index/annotation produced by the
  provider, so the canonical time axis is takeoff-relative;
* the distributed corpus contains no participant body mass, so the released
  force stays a dimensionless body-weight ratio in canonical form.

The 2022 PLOS acquisition paper places the lower-back sensor over L4 while the
2026 Zenodo release states L5. That conflict is preserved verbatim; no placement
is chosen and no signal is altered because of it.
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

WHITE_DATASET_ID = "white-cmj-acc-grf"
WHITE_VERSION = "v1"

#: The single accepted distributed member for RES-98.
WHITE_NPZ_KEY = "cmj_dataset_both.npz"

#: Canonical accelerometer and force stream identities (one pair per trial).
ACC_STREAM_PREFIX = "imu"
FORCE_STREAM_PREFIX = "force"

#: Exact deterministic unit conversion: 1 g of proper acceleration.
STANDARD_GRAVITY_M_S2 = 9.80665

#: Source-declared sampling rates of the distributed members.
ACC_SOURCE_RATE_HZ = 250
GRF_SOURCE_RATE_HZ = 1000

#: Distributed condition vocabulary (provider preparation code: 1 = no arms,
#: 2 = arms).
CONDITION_LABELS: dict[int, str] = {1: "noarms", 2: "arms"}

#: Sensor-frame authority: the release documents neither axis orientation nor
#: handedness, so every direction is explicitly unspecified. Nothing may be
#: inferred from the waveform.
SENSOR_FRAME_ID = "white-delsys-trigno-sensor"
#: Plate-frame authority: only the vertical direction is documented (up), so the
#: horizontal axes stay explicitly unspecified.
PLATE_FRAME_ID = "white-kistler-plate-vertical"
#: Shared takeoff-relative clock: each trial's origin is its own takeoff.
CLOCK_ID = "white-takeoff-relative"
#: One source-provided synchronization authority for the released arrays.
SYNC_SPEC_ID = "white-source-provided-takeoff-aligned"

#: Device identities describing the original instruments while the streams stay
#: classified as source-derived released representations.
TRIGNO_DEVICE_ID = "white-delsys-trigno"
KISTLER_DEVICE_ID = "white-kistler-platforms"

#: The source documentation conflict is part of the authority record.
SENSOR_PLACEMENT_DISTRIBUTED_RECORD = "L5"
SENSOR_PLACEMENT_ORIGINAL_PAPER = "L4"
SENSOR_PLACEMENT_AUTHORITY = "conflicting source documentation"

TIMEBASE_NOTES = (
    "Each trial is an independent takeoff-relative sample axis: t_rel_ns = 0 at the "
    "provider-annotated takeoff instant, pre-takeoff samples are negative. The released "
    "accelerometer member is a full recording at 250 Hz anchored at its takeoff index; "
    "the released vGRF member is a pre-takeoff 1000 Hz curve whose final sample is takeoff. "
    "No absolute UTC time exists in the release and none is invented; t_rel_ns is not "
    "comparable across trials."
)

SYNC_NOTES = (
    "The distributed arrays are provided by the source already aligned to the instant of "
    "takeoff, and the original acquisition paper reports accelerometer and force were "
    "synchronized through Vicon. The provider publishes no residual timing uncertainty for "
    "the released arrays, so no uncertainty or residual is asserted. Pairing of a trial's "
    "force and IMU streams is a declared scale-1, zero-offset alignment on the shared "
    "takeoff axis, which is not a claim that the original instruments had zero timing error."
)


def sensor_frame() -> CoordinateFrame:
    """Sensor frame whose axis orientation and handedness are undocumented."""
    return CoordinateFrame(
        frame_id=SENSOR_FRAME_ID,
        name="White CMJ lower-back accelerometer sensor frame (undocumented orientation)",
        kind=FrameKind.SENSOR,
        handedness=Handedness.UNSPECIFIED,
        x_direction=AxisDirection.UNSPECIFIED,
        y_direction=AxisDirection.UNSPECIFIED,
        z_direction=AxisDirection.UNSPECIFIED,
        origin_description=(
            "Delsys Trigno sensor attached to the lower back. The released dataset does not "
            "document axis orientation, so no anatomical or device axis direction is asserted."
        ),
        length_unit="m",
        description=(
            "Source documentation conflict preserved: the 2026 distributed record places the "
            f"sensor at {SENSOR_PLACEMENT_DISTRIBUTED_RECORD}, the 2022 acquisition paper at "
            f"{SENSOR_PLACEMENT_ORIGINAL_PAPER}; placement authority = "
            f"{SENSOR_PLACEMENT_AUTHORITY}. The orientation is undocumented, so all axes are "
            "'unspecified' and handedness is explicitly unspecified. No axis meaning was "
            "inferred from the waveform."
        ),
    )


def plate_frame() -> CoordinateFrame:
    """Plate frame with a documented vertical axis and undocumented horizontal axes."""
    return CoordinateFrame(
        frame_id=PLATE_FRAME_ID,
        name="White CMJ Kistler plate frame (vertical axis only)",
        kind=FrameKind.LABORATORY,
        handedness=Handedness.UNSPECIFIED,
        x_direction=AxisDirection.UNSPECIFIED,
        y_direction=AxisDirection.UNSPECIFIED,
        z_direction=AxisDirection.UP,
        origin_description=(
            "Force-platform surface. The released vGRF is already combined and normalised, so "
            "no individual plate origin or horizontal axis is declared."
        ),
        length_unit="m",
        description=(
            "Only the vertical (up) direction is documented by the release. Horizontal axes "
            "and handedness are explicitly unspecified rather than inferred."
        ),
    )


def takeoff_clock() -> Clock:
    """Shared takeoff-relative monotonic clock; per-stream rates are declared on streams."""
    return Clock(
        clock_id=CLOCK_ID,
        timebase=Timebase.DEVICE_MONOTONIC,
        frequency_hz=None,
        notes=TIMEBASE_NOTES,
    )


def source_sync_spec() -> SynchronizationSpec:
    """Source-provided takeoff alignment with no asserted residual."""
    return SynchronizationSpec(
        sync_spec_id=SYNC_SPEC_ID,
        method=SynchronizationMethod.SOURCE_PROVIDED,
        reference_clock_id=CLOCK_ID,
        notes=SYNC_NOTES,
    )
