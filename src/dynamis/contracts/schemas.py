"""Canonical Arrow schemas for every V1 modality.

Design rules enforced here:

* one strongly typed schema per modality; there is deliberately no generic
  ``measurement(name, value)`` EAV schema;
* every high-frequency schema models ``sample_index``, ``t_rel_ns``, nominal
  sampling rate, the clock/timebase reference, synchronization semantics, the
  coordinate-frame reference, measurement class, and the dataset/session/
  trial/device/stream identity envelope;
* SI units are attached as field metadata; source units and their exact scale
  factor stay recoverable next to the SI truth;
* a field is nullable only when the modality legitimately cannot provide the
  concept, and every nullable field documents why in ``dynamis.nullable_reason``;
* schema- and field-level metadata are part of the contract and are asserted by
  tests, so nullability or unit drift cannot happen silently.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final

import pyarrow as pa

from dynamis.contracts.base import CONTRACT_SCHEMA_VERSION
from dynamis.contracts.enums import MeasurementClass, Modality
from dynamis.contracts.units import assert_si_unit

SCHEMA_VERSION: Final = CONTRACT_SCHEMA_VERSION

#: Per-contract schema revision. A contract starts at :data:`SCHEMA_VERSION` and
#: is bumped only by a deliberate additive/breaking change to that one modality,
#: so an unrelated modality's schema identity and materialized artifacts are
#: never invalidated by another contract's revision.
DEFAULT_CONTRACT_SCHEMA_VERSION: Final = SCHEMA_VERSION

#: ``imu_sample`` 2: accelerometer-only sources legitimately provide no gyroscope,
#: so the gyro channels became nullable.
#: ``force_sample`` 2: dimensionless body-weight-normalized vertical force was
#: added because a source can distribute normalized force without body mass.
CONTRACT_SCHEMA_VERSIONS: Final[dict[str, str]] = {
    "imu_sample": "2",
    "force_sample": "2",
}

SCHEMA_VERSION_KEY: Final = b"dynamis.schema_version"
CONTRACT_KEY: Final = b"dynamis.contract"
MODALITY_KEY: Final = b"dynamis.modality"
UNITS_KEY: Final = b"dynamis.units"
SUBJECT_REQUIRED_KEY: Final = b"dynamis.subject_required"
COORDINATE_FRAME_REQUIRED_KEY: Final = b"dynamis.coordinate_frame_required"
DENSE_KEY: Final = b"dynamis.dense"
SYNCHRONIZATION_KEY: Final = b"dynamis.synchronization"
MEASUREMENT_CLASS_KEY: Final = b"dynamis.measurement_class"
MEASUREMENT_CLASSES_KEY: Final = b"dynamis.measurement_classes"
PAYLOAD_COMPLETENESS_KEY: Final = b"dynamis.payload_completeness"
NOMINAL_RATE_KEY: Final = b"dynamis.nominal_sampling_rate_hz"
TIME_MONOTONICITY_KEY: Final = b"dynamis.time_monotonicity"

#: Dense single-entity streams advance time at every row.
MONOTONICITY_STRICT: Final = "strict"
#: Multi-entity frame streams share one timestamp across the entities of a frame.
MONOTONICITY_NON_DECREASING: Final = "non_decreasing"

SI_UNIT_KEY: Final = b"dynamis.si_unit"
SOURCE_UNIT_KEY: Final = b"dynamis.source_unit"
SOURCE_SCALE_KEY: Final = b"dynamis.source_to_si_scale"
DESCRIPTION_KEY: Final = b"dynamis.description"
NULLABLE_REASON_KEY: Final = b"dynamis.nullable_reason"
AXIS_KEY: Final = b"dynamis.axis"

IDENTITY_FIELD_NAMES: Final = (
    "dataset_id",
    "session_id",
    "trial_id",
    "subject_id",
    "device_id",
    "stream_id",
)

TIMING_FIELD_NAMES: Final = (
    "sample_index",
    "t_rel_ns",
    "timestamp_utc_ns",
    "nominal_sampling_rate_hz",
    "clock_id",
    "synchronization_spec_id",
)

GEOMETRY_FIELD_NAMES: Final = ("coordinate_frame_id",)

CLASSIFICATION_FIELD_NAMES: Final = ("measurement_class",)


def _f(
    name: str,
    dtype: pa.DataType,
    *,
    si_unit: str | None = None,
    source_unit: str | None = None,
    source_to_si_scale: float | None = None,
    description: str | None = None,
    axis: str | None = None,
    nullable: bool = False,
    nullable_reason: str | None = None,
) -> pa.Field:
    """Build one contract field with explicit unit and nullability provenance."""
    if nullable and not nullable_reason:
        raise ValueError(f"nullable field {name!r} must document why it can be absent")
    if not nullable and nullable_reason:
        raise ValueError(f"non-nullable field {name!r} must not carry a nullable_reason")
    if si_unit is not None:
        assert_si_unit(si_unit, field_name=f"{name}.si_unit")
    if source_to_si_scale is not None and source_unit is None:
        raise ValueError(f"{name!r}: source_to_si_scale requires an explicit source_unit")
    if source_unit is not None and si_unit is None:
        raise ValueError(f"{name!r}: source units require the SI truth they map onto")

    metadata: dict[bytes, bytes] = {}
    if si_unit is not None:
        metadata[SI_UNIT_KEY] = si_unit.encode()
    if source_unit is not None:
        metadata[SOURCE_UNIT_KEY] = source_unit.encode()
    if source_to_si_scale is not None:
        metadata[SOURCE_SCALE_KEY] = repr(float(source_to_si_scale)).encode()
    if description is not None:
        metadata[DESCRIPTION_KEY] = description.encode()
    if axis is not None:
        metadata[AXIS_KEY] = axis.encode()
    if nullable_reason is not None:
        metadata[NULLABLE_REASON_KEY] = nullable_reason.encode()
    return pa.field(name, dtype, nullable=nullable, metadata=metadata or None)


def _identity_fields(*, dense: bool) -> list[pa.Field]:
    return [
        _f(
            "dataset_id",
            pa.string(),
            description=(
                "Dataset identity. Identities are never merged across unrelated datasets."
            ),
        ),
        _f("session_id", pa.string(), description="Session identity within the dataset."),
        _f(
            "trial_id",
            pa.string(),
            description="Trial, rep, period or half scope.",
            nullable=True,
            nullable_reason="Session-level or match-level samples belong to no single trial.",
        ),
        _f(
            "subject_id",
            pa.string(),
            description="Canonical dataset-scoped subject identity.",
            nullable=True,
            nullable_reason=(
                "Multi-entity streams legitimately carry ball, referee or unknown objects."
            ),
        ),
        _f(
            "device_id",
            pa.string(),
            description="Device that produced the samples.",
            nullable=True,
            nullable_reason="Camera-derived tracking has no single physical capture device.",
        ),
        _f("stream_id", pa.string(), description="Sensor stream identity."),
        _f(
            "sample_index",
            pa.int64(),
            si_unit="1",
            description="Zero-based, monotonically increasing sample ordinal within the stream.",
        ),
        _f(
            "t_rel_ns",
            pa.int64(),
            si_unit="ns",
            description="Time relative to the stream clock origin, in nanoseconds.",
        ),
        _f(
            "timestamp_utc_ns",
            pa.int64(),
            si_unit="ns",
            description="Secondary UTC epoch nanoseconds when source truth exists.",
            nullable=True,
            nullable_reason=(
                "Many sources expose only monotonic time; UTC is optional by contract."
            ),
        ),
        _f(
            "nominal_sampling_rate_hz",
            pa.float64(),
            si_unit="Hz",
            description="Nominal stream rate actually used by these samples.",
            nullable=not dense,
            nullable_reason=(
                None if dense else "Event streams are trigger-based and have no sampling rate."
            ),
        ),
        _f(
            "measurement_class",
            pa.string(),
            description=("One of RAW_MEASURED, SOURCE_DERIVED, PIPELINE_DERIVED, MODEL_ESTIMATED."),
        ),
        _f(
            "clock_id",
            pa.string(),
            description="Clock/timebase authority governing t_rel_ns and timestamp_utc_ns.",
        ),
        _f(
            "synchronization_spec_id",
            pa.string(),
            description="Synchronization authority; free-text sync claims are not accepted.",
        ),
        _f(
            "coordinate_frame_id",
            pa.string(),
            description="Coordinate-frame authority for every position/vector column.",
            nullable=True,
            nullable_reason=(
                "Some modalities are scalar or geodetic-native and declare no local frame."
            ),
        ),
    ]


def _schema_metadata(
    *,
    modality: Modality,
    contract: str,
    subject_required: bool,
    coordinate_frame_required: bool,
    dense: bool,
    measurement_class: MeasurementClass,
    monotonicity: str,
    payload_completeness: str | None = None,
    schema_version: str | None = None,
) -> dict[bytes, bytes]:
    metadata: dict[bytes, bytes] = {
        SCHEMA_VERSION_KEY: (schema_version or SCHEMA_VERSION).encode(),
        CONTRACT_KEY: contract.encode(),
        MODALITY_KEY: modality.value.encode(),
        UNITS_KEY: b"SI",
        SUBJECT_REQUIRED_KEY: b"true" if subject_required else b"false",
        COORDINATE_FRAME_REQUIRED_KEY: b"true" if coordinate_frame_required else b"false",
        DENSE_KEY: b"true" if dense else b"false",
        SYNCHRONIZATION_KEY: b"required",
        TIME_MONOTONICITY_KEY: monotonicity.encode(),
        MEASUREMENT_CLASS_KEY: measurement_class.value.encode(),
        MEASUREMENT_CLASSES_KEY: b",".join(member.value.encode() for member in MeasurementClass),
    }
    if payload_completeness is not None:
        metadata[PAYLOAD_COMPLETENESS_KEY] = payload_completeness.encode()
    return metadata


def _build(
    *,
    modality: Modality,
    contract: str,
    payload: list[pa.Field],
    subject_required: bool,
    coordinate_frame_required: bool,
    dense: bool = True,
    measurement_class: MeasurementClass = MeasurementClass.RAW_MEASURED,
    monotonicity: str = MONOTONICITY_STRICT,
    payload_completeness: str | None = None,
    schema_version: str | None = None,
) -> pa.Schema:
    if monotonicity not in {MONOTONICITY_STRICT, MONOTONICITY_NON_DECREASING}:
        raise ValueError(f"{contract}: unsupported monotonicity {monotonicity!r}")
    fields = [*_identity_fields(dense=dense), *payload]
    names = [item.name for item in fields]
    if len(set(names)) != len(names):
        raise ValueError(f"{contract}: duplicate field names")
    version = schema_version or CONTRACT_SCHEMA_VERSIONS.get(
        contract, DEFAULT_CONTRACT_SCHEMA_VERSION
    )
    return pa.schema(
        fields,
        metadata=_schema_metadata(
            modality=modality,
            contract=contract,
            subject_required=subject_required,
            coordinate_frame_required=coordinate_frame_required,
            dense=dense,
            measurement_class=measurement_class,
            monotonicity=monotonicity,
            payload_completeness=payload_completeness,
            schema_version=version,
        ),
    )


# ---------------------------------------------------------------------------
# GNSS
# ---------------------------------------------------------------------------

GNSS_SCHEMA: Final[pa.Schema] = _build(
    modality=Modality.GNSS,
    contract="gnss_sample",
    subject_required=True,
    coordinate_frame_required=False,
    payload=[
        _f(
            "latitude_deg",
            pa.float64(),
            si_unit="deg",
            description="Geodetic latitude (WGS 84).",
        ),
        _f(
            "longitude_deg",
            pa.float64(),
            si_unit="deg",
            description="Geodetic longitude (WGS 84).",
        ),
        _f(
            "ellipsoidal_height_m",
            pa.float64(),
            si_unit="m",
            description="Height above the WGS 84 ellipsoid.",
            nullable=True,
            nullable_reason="Consumer GNSS units frequently report no reliable altitude.",
        ),
        _f(
            "ecef_x_m",
            pa.float64(),
            si_unit="m",
            axis="x",
            description="ECEF X position when the source provides it.",
            nullable=True,
            nullable_reason="Most sources publish geodetic coordinates only.",
        ),
        _f(
            "ecef_y_m",
            pa.float64(),
            si_unit="m",
            axis="y",
            description="ECEF Y position when the source provides it.",
            nullable=True,
            nullable_reason="Most sources publish geodetic coordinates only.",
        ),
        _f(
            "ecef_z_m",
            pa.float64(),
            si_unit="m",
            axis="z",
            description="ECEF Z position when the source provides it.",
            nullable=True,
            nullable_reason="Most sources publish geodetic coordinates only.",
        ),
        _f(
            "speed_m_s",
            pa.float64(),
            si_unit="m/s",
            description="Ground speed.",
            nullable=True,
            nullable_reason="Source may expose only positions, leaving speed to derivation.",
        ),
        _f(
            "course_deg",
            pa.float64(),
            si_unit="deg",
            description="Direction of travel, clockwise from north.",
            nullable=True,
            nullable_reason="Course is undefined for a stationary sample.",
        ),
        _f(
            "horizontal_accuracy_m",
            pa.float64(),
            si_unit="m",
            description="Source-reported horizontal position accuracy (1 sigma).",
            nullable=True,
            nullable_reason="Not all receivers report accuracy estimates.",
        ),
        _f(
            "vertical_accuracy_m",
            pa.float64(),
            si_unit="m",
            description="Source-reported vertical position accuracy (1 sigma).",
            nullable=True,
            nullable_reason="Not all receivers report accuracy estimates.",
        ),
        _f(
            "hdop",
            pa.float64(),
            si_unit="1",
            description="Horizontal dilution of precision.",
            nullable=True,
            nullable_reason="Dilution of precision is optional in most consumer exports.",
        ),
        _f(
            "satellites_used",
            pa.int32(),
            si_unit="1",
            description="Number of satellites contributing to the fix.",
            nullable=True,
            nullable_reason="Constellation bookkeeping is frequently stripped by vendors.",
        ),
        _f(
            "fix_type",
            pa.string(),
            description="Source fix classification (e.g. single, differential, rtk, float).",
            nullable=True,
            nullable_reason="Fix classification is vendor-specific and often absent.",
        ),
        _f(
            "quality_flag",
            pa.string(),
            description="Per-sample source quality marker; raw evidence is preserved.",
            nullable=True,
            nullable_reason="Sources without a quality channel must not be forced to invent one.",
        ),
    ],
)


# ---------------------------------------------------------------------------
# IMU
# ---------------------------------------------------------------------------

IMU_SCHEMA: Final[pa.Schema] = _build(
    modality=Modality.IMU,
    contract="imu_sample",
    subject_required=True,
    coordinate_frame_required=True,
    payload=[
        _f(
            "accel_x_m_s2",
            pa.float64(),
            si_unit="m/s**2",
            axis="x",
            description="Proper acceleration along the sensor frame X axis.",
        ),
        _f(
            "accel_y_m_s2",
            pa.float64(),
            si_unit="m/s**2",
            axis="y",
            description="Proper acceleration along the sensor frame Y axis.",
        ),
        _f(
            "accel_z_m_s2",
            pa.float64(),
            si_unit="m/s**2",
            axis="z",
            description="Proper acceleration along the sensor frame Z axis.",
        ),
        _f(
            "gyro_x_rad_s",
            pa.float64(),
            si_unit="rad/s",
            axis="x",
            description="Angular velocity about the sensor frame X axis.",
            nullable=True,
            nullable_reason="Accelerometer-only sources distribute no gyroscope channel.",
        ),
        _f(
            "gyro_y_rad_s",
            pa.float64(),
            si_unit="rad/s",
            axis="y",
            description="Angular velocity about the sensor frame Y axis.",
            nullable=True,
            nullable_reason="Accelerometer-only sources distribute no gyroscope channel.",
        ),
        _f(
            "gyro_z_rad_s",
            pa.float64(),
            si_unit="rad/s",
            axis="z",
            description="Angular velocity about the sensor frame Z axis.",
            nullable=True,
            nullable_reason="Accelerometer-only sources distribute no gyroscope channel.",
        ),
        _f(
            "mag_x_ut",
            pa.float64(),
            si_unit="uT",
            axis="x",
            description="Magnetic flux density along X, microtesla (SI symbol uT).",
            nullable=True,
            nullable_reason="Many IMUs used for sport expose no magnetometer channel.",
        ),
        _f(
            "mag_y_ut",
            pa.float64(),
            si_unit="uT",
            axis="y",
            description="Magnetic flux density along Y, microtesla.",
            nullable=True,
            nullable_reason="Many IMUs used for sport expose no magnetometer channel.",
        ),
        _f(
            "mag_z_ut",
            pa.float64(),
            si_unit="uT",
            axis="z",
            description="Magnetic flux density along Z, microtesla.",
            nullable=True,
            nullable_reason="Many IMUs used for sport expose no magnetometer channel.",
        ),
        _f(
            "temperature_deg_c",
            pa.float64(),
            si_unit="degC",
            description="Sensor die temperature.",
            nullable=True,
            nullable_reason="Temperature compensation channels are optional in sport IMUs.",
        ),
        _f(
            "quality_flag",
            pa.string(),
            description="Per-sample source quality marker; raw evidence is preserved.",
            nullable=True,
            nullable_reason="Sources without a quality channel must not be forced to invent one.",
        ),
    ],
)


# ---------------------------------------------------------------------------
# Force
# ---------------------------------------------------------------------------

FORCE_SCHEMA: Final[pa.Schema] = _build(
    modality=Modality.FORCE,
    contract="force_sample",
    subject_required=True,
    coordinate_frame_required=True,
    payload_completeness=(
        "at least one of force_x_n, force_y_n, force_z_n must be present per row, or the "
        "explicit dimensionless force_z_body_weight_ratio when the source distributes "
        "body-weight-normalized vertical force and provides no body mass; single-axis load "
        "cells legitimately provide only one channel"
    ),
    payload=[
        _f(
            "plate_id",
            pa.string(),
            description="Plate or load-cell channel identity for dual-plate setups.",
            nullable=True,
            nullable_reason="Single-plate datasets have no plate discriminator.",
        ),
        _f(
            "force_x_n",
            pa.float64(),
            si_unit="N",
            axis="x",
            description="Ground reaction force along the plate frame X axis.",
            nullable=True,
            nullable_reason="Single-axis load cells cannot provide orthogonal channels.",
        ),
        _f(
            "force_y_n",
            pa.float64(),
            si_unit="N",
            axis="y",
            description="Ground reaction force along the plate frame Y axis.",
            nullable=True,
            nullable_reason="Single-axis load cells cannot provide orthogonal channels.",
        ),
        _f(
            "force_z_n",
            pa.float64(),
            si_unit="N",
            axis="z",
            description="Ground reaction force along the plate frame Z axis (vertical).",
            nullable=True,
            nullable_reason="Single-axis load cells cannot provide orthogonal channels.",
        ),
        _f(
            "force_z_body_weight_ratio",
            pa.float64(),
            si_unit="1",
            axis="z",
            description=(
                "Vertical ground reaction force divided by the participant's body weight. "
                "Use only when the source distributes a body-weight-normalized vertical "
                "force and supplies no participant mass; never convert to newtons without "
                "a documented body mass."
            ),
            nullable=True,
            nullable_reason=(
                "Newton-valued force plates and normalized sources are mutually exclusive "
                "representations of the same physical quantity."
            ),
        ),
        _f(
            "moment_x_n_m",
            pa.float64(),
            si_unit="N*m",
            axis="x",
            description="Free moment about the plate frame X axis.",
            nullable=True,
            nullable_reason="Moment channels exist only on multi-component force plates.",
        ),
        _f(
            "moment_y_n_m",
            pa.float64(),
            si_unit="N*m",
            axis="y",
            description="Free moment about the plate frame Y axis.",
            nullable=True,
            nullable_reason="Moment channels exist only on multi-component force plates.",
        ),
        _f(
            "moment_z_n_m",
            pa.float64(),
            si_unit="N*m",
            axis="z",
            description="Free moment about the plate frame Z axis.",
            nullable=True,
            nullable_reason="Moment channels exist only on multi-component force plates.",
        ),
        _f(
            "cop_x_m",
            pa.float64(),
            si_unit="m",
            axis="x",
            description="Centre of pressure along X.",
            nullable=True,
            nullable_reason="Centre of pressure requires a multi-component plate.",
        ),
        _f(
            "cop_y_m",
            pa.float64(),
            si_unit="m",
            axis="y",
            description="Centre of pressure along Y.",
            nullable=True,
            nullable_reason="Centre of pressure requires a multi-component plate.",
        ),
        _f(
            "cop_z_m",
            pa.float64(),
            si_unit="m",
            axis="z",
            description="Centre of pressure along Z when the source defines it.",
            nullable=True,
            nullable_reason="Most plates define centre of pressure in the plate plane only.",
        ),
        _f(
            "trigger_flag",
            pa.bool_(),
            description="Source-provided event/trigger marker on the sample.",
            nullable=True,
            nullable_reason="Trigger channels are optional in exported force files.",
        ),
        _f(
            "quality_flag",
            pa.string(),
            description="Per-sample source quality marker; raw evidence is preserved.",
            nullable=True,
            nullable_reason="Sources without a quality channel must not be forced to invent one.",
        ),
    ],
)


# ---------------------------------------------------------------------------
# Linear position transducer
# ---------------------------------------------------------------------------

LPT_SCHEMA: Final[pa.Schema] = _build(
    modality=Modality.LPT,
    contract="lpt_sample",
    subject_required=True,
    coordinate_frame_required=False,
    payload=[
        _f(
            "position_m",
            pa.float64(),
            si_unit="m",
            description="Linear displacement along the transducer cable direction.",
        ),
        _f(
            "velocity_m_s",
            pa.float64(),
            si_unit="m/s",
            description="Cable velocity when the source provides or derives it.",
            nullable=True,
            nullable_reason="Many LPT exports provide displacement only.",
        ),
        _f(
            "load_kg",
            pa.float64(),
            si_unit="kg",
            description="Attached load reported as mass.",
            nullable=True,
            nullable_reason="Load is device-specific and often absent from displacement exports.",
        ),
        _f(
            "load_n",
            pa.float64(),
            si_unit="N",
            description="Attached load reported as force.",
            nullable=True,
            nullable_reason="Load is device-specific and often absent from displacement exports.",
        ),
        _f(
            "cable_angle_deg",
            pa.float64(),
            si_unit="deg",
            description="Cable angle relative to the declared reference axis.",
            nullable=True,
            nullable_reason="Only instruments with an angle channel can report it.",
        ),
        _f(
            "rep_index",
            pa.int32(),
            si_unit="1",
            description="Source-derived repetition index when segmentation is upstream.",
            nullable=True,
            nullable_reason="Repetition segmentation is usually a pipeline derivation.",
        ),
        _f(
            "quality_flag",
            pa.string(),
            description="Per-sample source quality marker; raw evidence is preserved.",
            nullable=True,
            nullable_reason="Sources without a quality channel must not be forced to invent one.",
        ),
    ],
)


# ---------------------------------------------------------------------------
# Optical / broadcast tracking
# ---------------------------------------------------------------------------

TRACKING_SCHEMA: Final[pa.Schema] = _build(
    modality=Modality.TRACKING,
    contract="tracking_sample",
    subject_required=False,
    coordinate_frame_required=True,
    monotonicity=MONOTONICITY_NON_DECREASING,
    payload=[
        _f(
            "object_id",
            pa.string(),
            description="Provider object identity (player, ball, referee, unknown).",
        ),
        _f(
            "object_type",
            pa.string(),
            description="Object classification: player, goalkeeper, ball, referee, other.",
        ),
        _f(
            "group_id",
            pa.string(),
            description="Team or group identity for team sports.",
            nullable=True,
            nullable_reason="The ball and officials belong to no team.",
        ),
        _f(
            "x_m",
            pa.float64(),
            si_unit="m",
            axis="x",
            description="Position along the declared frame X axis.",
        ),
        _f(
            "y_m",
            pa.float64(),
            si_unit="m",
            axis="y",
            description="Position along the declared frame Y axis.",
        ),
        _f(
            "z_m",
            pa.float64(),
            si_unit="m",
            axis="z",
            description="Position along the declared frame Z axis when tracked.",
            nullable=True,
            nullable_reason="Most 2D optical systems track the plane only.",
        ),
        _f(
            "vx_m_s",
            pa.float64(),
            si_unit="m/s",
            axis="x",
            description="Velocity along X.",
            nullable=True,
            nullable_reason="Provider may publish positions only.",
        ),
        _f(
            "vy_m_s",
            pa.float64(),
            si_unit="m/s",
            axis="y",
            description="Velocity along Y.",
            nullable=True,
            nullable_reason="Provider may publish positions only.",
        ),
        _f(
            "vz_m_s",
            pa.float64(),
            si_unit="m/s",
            axis="z",
            description="Velocity along Z.",
            nullable=True,
            nullable_reason="Requires a tracked vertical axis.",
        ),
        _f(
            "ax_m_s2",
            pa.float64(),
            si_unit="m/s**2",
            axis="x",
            description="Acceleration along X.",
            nullable=True,
            nullable_reason="Acceleration is normally a pipeline derivation, not source data.",
        ),
        _f(
            "ay_m_s2",
            pa.float64(),
            si_unit="m/s**2",
            axis="y",
            description="Acceleration along Y.",
            nullable=True,
            nullable_reason="Acceleration is normally a pipeline derivation, not source data.",
        ),
        _f(
            "az_m_s2",
            pa.float64(),
            si_unit="m/s**2",
            axis="z",
            description="Acceleration along Z.",
            nullable=True,
            nullable_reason="Acceleration is normally a pipeline derivation, not source data.",
        ),
        _f(
            "is_detected",
            pa.bool_(),
            description="False when the object was interpolated or extrapolated.",
            nullable=True,
            nullable_reason="Some providers do not expose detection provenance per sample.",
        ),
        _f(
            "confidence",
            pa.float64(),
            si_unit="1",
            description="Source confidence in this observation, in [0, 1].",
            nullable=True,
            nullable_reason="Not every provider publishes per-sample confidence.",
        ),
    ],
)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

EVENT_SCHEMA: Final[pa.Schema] = _build(
    modality=Modality.EVENT,
    contract="event_record",
    subject_required=False,
    coordinate_frame_required=False,
    dense=False,
    measurement_class=MeasurementClass.SOURCE_DERIVED,
    payload=[
        _f(
            "event_id",
            pa.string(),
            description="Provider event identity, unique within the stream.",
        ),
        _f(
            "event_type",
            pa.string(),
            description="Primary event classification (pass, shot, tackle, ...).",
        ),
        _f(
            "event_subtype",
            pa.string(),
            description="Provider secondary classification.",
            nullable=True,
            nullable_reason="Provider taxonomies are hierarchical only in some datasets.",
        ),
        _f(
            "provider_team_id",
            pa.string(),
            description="Raw provider team identity, preserved without reinterpretation.",
            nullable=True,
            nullable_reason="Some events (whistles, period markers) belong to no team.",
        ),
        _f(
            "provider_player_id",
            pa.string(),
            description="Raw provider player identity, distinct from canonical subject_id.",
            nullable=True,
            nullable_reason="Team-level and match-level events have no player.",
        ),
        _f(
            "x_m",
            pa.float64(),
            si_unit="m",
            axis="x",
            description="Event location along the declared frame X axis.",
            nullable=True,
            nullable_reason="Some provider events carry no spatial location.",
        ),
        _f(
            "y_m",
            pa.float64(),
            si_unit="m",
            axis="y",
            description="Event location along the declared frame Y axis.",
            nullable=True,
            nullable_reason="Some provider events carry no spatial location.",
        ),
        _f(
            "body_part",
            pa.string(),
            description="Body part involved where the provider reports it.",
            nullable=True,
            nullable_reason="Only a subset of provider event types is body-part annotated.",
        ),
        _f(
            "outcome",
            pa.string(),
            description="Provider outcome classification for the event.",
            nullable=True,
            nullable_reason="Many event types have no outcome value.",
        ),
        _f(
            "provider_context_json",
            pa.string(),
            description=(
                "Compact JSON of raw provider attributes kept for anti-corruption-layer fidelity."
            ),
            nullable=True,
            nullable_reason="Only present when the provider adds non-canonical attributes.",
        ),
    ],
)


# ---------------------------------------------------------------------------
# 3D pose
# ---------------------------------------------------------------------------

POSE_SCHEMA: Final[pa.Schema] = _build(
    modality=Modality.POSE,
    contract="pose_joint_sample",
    subject_required=True,
    coordinate_frame_required=True,
    monotonicity=MONOTONICITY_NON_DECREASING,
    payload=[
        _f(
            "skeleton_id",
            pa.string(),
            description=(
                "Skeleton/joint-topology authority; joint indices are meaningless without it."
            ),
        ),
        _f(
            "joint_id",
            pa.int32(),
            si_unit="1",
            description="Joint ordinal within the declared skeleton.",
        ),
        _f(
            "joint_name",
            pa.string(),
            description="Declared joint name, denormalized for readable reconciliation.",
        ),
        _f(
            "parent_joint_id",
            pa.int32(),
            si_unit="1",
            description="Parent joint ordinal, resolved from the skeleton authority.",
            nullable=True,
            nullable_reason="The root joint has no parent.",
        ),
        _f(
            "x_m",
            pa.float64(),
            si_unit="m",
            axis="x",
            description="Joint position along the declared frame X axis.",
        ),
        _f(
            "y_m",
            pa.float64(),
            si_unit="m",
            axis="y",
            description="Joint position along the declared frame Y axis.",
        ),
        _f(
            "z_m",
            pa.float64(),
            si_unit="m",
            axis="z",
            description="Joint position along the declared frame Z axis.",
        ),
        _f(
            "confidence",
            pa.float64(),
            si_unit="1",
            description="Per-joint estimation confidence in [0, 1].",
            nullable=True,
            nullable_reason="Not every pose provider publishes confidence.",
        ),
        _f(
            "error_m",
            pa.float64(),
            si_unit="m",
            description="Per-joint position uncertainty when the provider quantifies it.",
            nullable=True,
            nullable_reason="Providers rarely publish per-joint metric error.",
        ),
        _f(
            "is_occluded",
            pa.bool_(),
            description="Provider occlusion marker for the joint at this frame.",
            nullable=True,
            nullable_reason="Occlusion flags are provider-specific and often unavailable.",
        ),
    ],
)


def _read_metadata(schema: pa.Schema, key: bytes) -> str:
    metadata = schema.metadata
    if metadata is None or key not in metadata:
        raise ValueError(
            f"schema is missing required DynamisData metadata key {key!r}; "
            "every canonical modality schema must be produced by this module"
        )
    return str(metadata[key], "utf-8")


MODALITY_SCHEMAS: Final[dict[Modality, pa.Schema]] = {
    Modality.GNSS: GNSS_SCHEMA,
    Modality.IMU: IMU_SCHEMA,
    Modality.FORCE: FORCE_SCHEMA,
    Modality.LPT: LPT_SCHEMA,
    Modality.TRACKING: TRACKING_SCHEMA,
    Modality.EVENT: EVENT_SCHEMA,
    Modality.POSE: POSE_SCHEMA,
}


def get_schema(modality: Modality | str) -> pa.Schema:
    """Resolve the canonical schema for a modality value or member.

    Unknown modalities raise instead of silently returning a permissive schema.
    """
    if isinstance(modality, str):
        try:
            modality = Modality(modality)
        except ValueError as exc:
            raise KeyError(
                f"unknown modality {modality!r}; known modalities: "
                f"{', '.join(member.value for member in Modality)}"
            ) from exc
    try:
        return MODALITY_SCHEMAS[modality]
    except KeyError as exc:  # pragma: no cover - defensive, enum is closed
        raise KeyError(f"no canonical schema registered for {modality!r}") from exc


def get_schema_by_contract(contract: str) -> pa.Schema:
    try:
        return SCHEMA_BY_CONTRACT[contract]
    except KeyError as exc:
        raise KeyError(
            f"unknown contract {contract!r}; known contracts: "
            f"{', '.join(sorted(SCHEMA_BY_CONTRACT))}"
        ) from exc


def modality_of(schema: pa.Schema) -> Modality:
    return Modality(_read_metadata(schema, MODALITY_KEY))


def contract_of(schema: pa.Schema) -> str:
    return _read_metadata(schema, CONTRACT_KEY)


def schema_version_of(schema: pa.Schema) -> str:
    """Contract revision of this schema (per modality, not a global constant)."""
    return _read_metadata(schema, SCHEMA_VERSION_KEY)


SCHEMA_BY_CONTRACT: Final[dict[str, pa.Schema]] = {
    contract_of(schema): schema for schema in MODALITY_SCHEMAS.values()
}


def subject_required(schema: pa.Schema) -> bool:
    return _read_metadata(schema, SUBJECT_REQUIRED_KEY) == "true"


def coordinate_frame_required(schema: pa.Schema) -> bool:
    return _read_metadata(schema, COORDINATE_FRAME_REQUIRED_KEY) == "true"


def is_dense(schema: pa.Schema) -> bool:
    return _read_metadata(schema, DENSE_KEY) == "true"


def time_monotonicity(schema: pa.Schema) -> str:
    """``strict`` for single-entity streams, ``non_decreasing`` for frame streams."""
    return _read_metadata(schema, TIME_MONOTONICITY_KEY)


def si_unit_of(field: pa.Field) -> str | None:
    if not field.metadata:
        return None
    raw = field.metadata.get(SI_UNIT_KEY)
    return str(raw, "utf-8") if raw is not None else None


def source_unit_of(field: pa.Field) -> str | None:
    if not field.metadata:
        return None
    raw = field.metadata.get(SOURCE_UNIT_KEY)
    return str(raw, "utf-8") if raw is not None else None


def source_scale_of(field: pa.Field) -> float | None:
    if not field.metadata:
        return None
    raw = field.metadata.get(SOURCE_SCALE_KEY)
    return float(raw) if raw is not None else None


def axis_of(field: pa.Field) -> str | None:
    if not field.metadata:
        return None
    raw = field.metadata.get(AXIS_KEY)
    return str(raw, "utf-8") if raw is not None else None


def nullable_reason_of(field: pa.Field) -> str | None:
    if not field.metadata:
        return None
    raw = field.metadata.get(NULLABLE_REASON_KEY)
    return str(raw, "utf-8") if raw is not None else None


def schema_fingerprint(schema: pa.Schema) -> str:
    """Deterministic sha256 over names, types, nullability, units and metadata."""
    canonical = {
        "fields": [
            {
                "name": field.name,
                "type": str(field.type),
                "nullable": field.nullable,
                "metadata": {
                    str(key, "utf-8"): str(value, "utf-8")
                    for key, value in sorted((field.metadata or {}).items())
                },
            }
            for field in schema
        ],
        "metadata": {
            str(key, "utf-8"): str(value, "utf-8")
            for key, value in sorted((schema.metadata or {}).items())
        },
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def with_file_metadata(
    schema: pa.Schema,
    *,
    nominal_sampling_rate_hz: float | None = None,
    extras: dict[str, str] | None = None,
) -> pa.Schema:
    """Attach file-level facts (e.g. uniform rate) without dropping SI truth."""
    metadata = dict(schema.metadata or {})
    if nominal_sampling_rate_hz is not None:
        metadata[NOMINAL_RATE_KEY] = repr(float(nominal_sampling_rate_hz)).encode()
    for key, value in (extras or {}).items():
        metadata[f"dynamis.{key}".encode()] = value.encode()
    return schema.with_metadata(metadata)


def empty_table(schema: pa.Schema) -> pa.Table:
    return pa.Table.from_pylist([], schema=schema)


def verification_field_names(schema: pa.Schema) -> tuple[str, ...]:
    """Columns that must be non-null for the contract to be satisfiable per row."""
    required = (*IDENTITY_FIELD_NAMES, *TIMING_FIELD_NAMES)
    return tuple(name for name in required if schema.field(name).nullable is False)
