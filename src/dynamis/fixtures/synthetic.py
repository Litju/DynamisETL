"""Deterministic synthetic fixtures for every V1 modality.

These are **not** samples of any external dataset. They are analytically known
trajectories and signals used to prove the canonical contracts, units, frames,
synchronization semantics and the Arrow -> Parquet(Zstd) -> DuckDB path with
known-answer tests.

Each fixture exposes, besides its Arrow table, an ``expected`` mapping of column
name to the exact expected SI values in row order. Reconciliation therefore
compares stored values against declared expectations instead of against whatever
happens to be in the file.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pyarrow as pa

from dynamis.contracts import (
    MeasurementClass,
    Modality,
    get_schema,
    make_stream_id,
    with_file_metadata,
)

SYNTHETIC_DATASET_ID = "synthetic-foundation"
SYNTHETIC_SESSION_ID = "syn-session-0001"
SYNTHETIC_TRIAL_ID = "syn-trial-0001"
SYNTHETIC_SUBJECT_ID = "syn-subject-0001"
SYNTHETIC_DEVICE_ID = "syn-device-0001"
SYNTHETIC_CLOCK_ID = "syn-clock-session-monotonic"
SYNTHETIC_SYNC_SPEC_ID = "syn-sync-source-provided"
SYNTHETIC_MEASUREMENT_CLASS = MeasurementClass.RAW_MEASURED.value

GNSS_FRAME_ID = "syn-frame-wgs84-geodetic"
IMU_FRAME_ID = "syn-frame-imu-body"
FORCE_FRAME_ID = "syn-frame-force-plate"
TRACKING_FRAME_ID = "syn-frame-pitch-center"
POSE_FRAME_ID = "syn-frame-body-pelvis"
POSE_SKELETON_ID = "syn-skeleton-lower-limb-3joint"

EARTH_MEAN_RADIUS_M = 6_371_008.8
STANDARD_GRAVITY_M_S2 = 9.80665


@dataclass(frozen=True, slots=True)
class ModalityFixture:
    """One deterministic synthetic stream plus its exact expectations."""

    name: str
    modality: Modality
    table: pa.Table
    nominal_sampling_rate_hz: float | None
    sample_count: int
    stream_id: str
    clock_id: str
    synchronization_spec_id: str
    subject_id: str | None
    session_id: str = SYNTHETIC_SESSION_ID
    trial_id: str | None = SYNTHETIC_TRIAL_ID
    device_id: str | None = SYNTHETIC_DEVICE_ID
    dataset_id: str = SYNTHETIC_DATASET_ID
    coordinate_frame_id: str | None = None
    skeleton_id: str | None = None
    measurement_class: str = SYNTHETIC_MEASUREMENT_CLASS
    expected: Mapping[str, tuple[Any, ...]] = field(default_factory=dict)
    tolerance: float = 1e-9

    @property
    def schema(self) -> pa.Schema:
        return self.table.schema

    def expected_ns(self, index: int) -> int:
        if self.nominal_sampling_rate_hz is None:
            raise ValueError(f"{self.name} is trigger-based and has no nominal rate")
        return round(index * 1_000_000_000 / self.nominal_sampling_rate_hz)


def _identity_rows(
    *,
    count: int,
    stream_id: str,
    rate_hz: float,
    subject_id: str | None,
    coordinate_frame_id: str | None,
    skeleton_id: str | None = None,
    trial_id: str | None = SYNTHETIC_TRIAL_ID,
    device_id: str | None = SYNTHETIC_DEVICE_ID,
    measurement_class: str = SYNTHETIC_MEASUREMENT_CLASS,
) -> list[dict[str, Any]]:
    if count <= 0:
        raise ValueError("a synthetic fixture needs at least one sample")
    rows: list[dict[str, Any]] = []
    for index in range(count):
        rows.append(
            {
                "dataset_id": SYNTHETIC_DATASET_ID,
                "session_id": SYNTHETIC_SESSION_ID,
                "trial_id": trial_id,
                "subject_id": subject_id,
                "device_id": device_id,
                "stream_id": stream_id,
                "sample_index": index,
                "t_rel_ns": round(index * 1_000_000_000 / rate_hz),
                "timestamp_utc_ns": None,
                "nominal_sampling_rate_hz": rate_hz,
                "measurement_class": measurement_class,
                "clock_id": SYNTHETIC_CLOCK_ID,
                "synchronization_spec_id": SYNTHETIC_SYNC_SPEC_ID,
                "coordinate_frame_id": coordinate_frame_id,
                "skeleton_id": skeleton_id,
            }
        )
    return rows


def _build_table(
    modality: Modality,
    rows: list[dict[str, Any]],
    *,
    rate_hz: float | None,
) -> pa.Table:
    schema = with_file_metadata(
        get_schema(modality),
        nominal_sampling_rate_hz=rate_hz,
        extras={"origin": "synthetic-fixture", "generator": "dynamis.fixtures.synthetic"},
    )
    return pa.Table.from_pylist(rows, schema=schema)


# ---------------------------------------------------------------------------
# GNSS: constant-velocity trajectory with an analytically known position
# ---------------------------------------------------------------------------


def gnss_constant_velocity(
    *,
    speed_m_s: float = 5.0,
    heading_deg: float = 0.0,
    rate_hz: float = 10.0,
    sample_count: int = 100,
    anchor_latitude_deg: float = 40.0,
    anchor_longitude_deg: float = -3.0,
) -> ModalityFixture:
    """North-east local motion projected onto the WGS 84 sphere.

    ``heading_deg`` follows the GNSS course convention: clockwise from north, so
    0 degrees is due north and 90 degrees is due east. ``east_m`` grows east and
    ``north_m`` grows north. Latitude/longitude are derived with a documented
    spherical model, so the expected values are closed-form.
    """
    stream_id = make_stream_id(Modality.GNSS, 1)
    heading_rad = math.radians(heading_deg)
    rows: list[dict[str, Any]] = []
    latitudes: list[float] = []
    longitudes: list[float] = []
    east_values: list[float] = []
    north_values: list[float] = []
    speeds: list[float] = []

    for base in _identity_rows(
        count=sample_count,
        stream_id=stream_id,
        rate_hz=rate_hz,
        subject_id=SYNTHETIC_SUBJECT_ID,
        coordinate_frame_id=GNSS_FRAME_ID,
    ):
        index = int(base["sample_index"])
        t_s = index / rate_hz
        north_m = speed_m_s * math.cos(heading_rad) * t_s
        east_m = speed_m_s * math.sin(heading_rad) * t_s
        latitude = anchor_latitude_deg + math.degrees(north_m / EARTH_MEAN_RADIUS_M)
        longitude = anchor_longitude_deg + math.degrees(
            east_m / (EARTH_MEAN_RADIUS_M * math.cos(math.radians(anchor_latitude_deg)))
        )
        rows.append(
            {
                **base,
                "latitude_deg": latitude,
                "longitude_deg": longitude,
                "ellipsoidal_height_m": None,
                "ecef_x_m": None,
                "ecef_y_m": None,
                "ecef_z_m": None,
                "speed_m_s": speed_m_s,
                "course_deg": heading_deg,
                "horizontal_accuracy_m": 0.5,
                "vertical_accuracy_m": None,
                "hdop": None,
                "satellites_used": 12,
                "fix_type": "rtk",
                "quality_flag": None,
            }
        )
        latitudes.append(latitude)
        longitudes.append(longitude)
        east_values.append(east_m)
        north_values.append(north_m)
        speeds.append(speed_m_s)

    table = _build_table(Modality.GNSS, rows, rate_hz=rate_hz)
    expected: dict[str, tuple[Any, ...]] = {
        "latitude_deg": tuple(latitudes),
        "longitude_deg": tuple(longitudes),
        "speed_m_s": tuple(speeds),
        "course_deg": tuple(heading_deg for _ in range(sample_count)),
        "satellites_used": tuple(12 for _ in range(sample_count)),
        "ellipsoidal_height_m": tuple(None for _ in range(sample_count)),
    }
    return ModalityFixture(
        name="gnss_constant_velocity",
        modality=Modality.GNSS,
        table=table,
        nominal_sampling_rate_hz=rate_hz,
        sample_count=sample_count,
        stream_id=stream_id,
        clock_id=SYNTHETIC_CLOCK_ID,
        synchronization_spec_id=SYNTHETIC_SYNC_SPEC_ID,
        subject_id=SYNTHETIC_SUBJECT_ID,
        coordinate_frame_id=GNSS_FRAME_ID,
        expected=expected,
        tolerance=1e-9,
    )


def gnss_local_offsets(
    fixture: ModalityFixture,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """East/north local offsets implied by the fixture's own latitude/longitude."""
    latitudes = fixture.expected["latitude_deg"]
    longitudes = fixture.expected["longitude_deg"]
    anchor_latitude = float(latitudes[0])
    anchor_longitude = float(longitudes[0])
    north = tuple(
        math.radians(float(latitude) - anchor_latitude) * EARTH_MEAN_RADIUS_M
        for latitude in latitudes
    )
    east = tuple(
        math.radians(float(longitude) - anchor_longitude)
        * EARTH_MEAN_RADIUS_M
        * math.cos(math.radians(anchor_latitude))
        for longitude in longitudes
    )
    return east, north


# ---------------------------------------------------------------------------
# IMU: deterministic acceleration / gyro trace
# ---------------------------------------------------------------------------


def imu_deterministic_trace(
    *,
    rate_hz: float = 100.0,
    sample_count: int = 200,
    amplitude_m_s2: float = 2.0,
    frequency_hz: float = 1.0,
    gyro_z_rad_s: float = 1.5,
) -> ModalityFixture:
    stream_id = make_stream_id(Modality.IMU, 1)
    rows: list[dict[str, Any]] = []
    accel_x: list[float] = []
    accel_z: list[float] = []
    gyro_z: list[float] = []

    for base in _identity_rows(
        count=sample_count,
        stream_id=stream_id,
        rate_hz=rate_hz,
        subject_id=SYNTHETIC_SUBJECT_ID,
        coordinate_frame_id=IMU_FRAME_ID,
    ):
        index = int(base["sample_index"])
        t_s = index / rate_hz
        ax = amplitude_m_s2 * math.sin(2.0 * math.pi * frequency_hz * t_s)
        az = STANDARD_GRAVITY_M_S2
        gz = gyro_z_rad_s
        rows.append(
            {
                **base,
                "accel_x_m_s2": ax,
                "accel_y_m_s2": 0.0,
                "accel_z_m_s2": az,
                "gyro_x_rad_s": 0.0,
                "gyro_y_rad_s": 0.0,
                "gyro_z_rad_s": gz,
                "mag_x_ut": None,
                "mag_y_ut": None,
                "mag_z_ut": None,
                "temperature_deg_c": None,
                "quality_flag": None,
            }
        )
        accel_x.append(ax)
        accel_z.append(az)
        gyro_z.append(gz)

    table = _build_table(Modality.IMU, rows, rate_hz=rate_hz)
    expected: dict[str, tuple[Any, ...]] = {
        "accel_x_m_s2": tuple(accel_x),
        "accel_y_m_s2": tuple(0.0 for _ in range(sample_count)),
        "accel_z_m_s2": tuple(accel_z),
        "gyro_x_rad_s": tuple(0.0 for _ in range(sample_count)),
        "gyro_y_rad_s": tuple(0.0 for _ in range(sample_count)),
        "gyro_z_rad_s": tuple(gyro_z),
        "mag_x_ut": tuple(None for _ in range(sample_count)),
    }
    return ModalityFixture(
        name="imu_deterministic_trace",
        modality=Modality.IMU,
        table=table,
        nominal_sampling_rate_hz=rate_hz,
        sample_count=sample_count,
        stream_id=stream_id,
        clock_id=SYNTHETIC_CLOCK_ID,
        synchronization_spec_id=SYNTHETIC_SYNC_SPEC_ID,
        subject_id=SYNTHETIC_SUBJECT_ID,
        coordinate_frame_id=IMU_FRAME_ID,
        expected=expected,
        tolerance=1e-12,
    )


# ---------------------------------------------------------------------------
# Force: static body-weight trace and a known dynamic trace
# ---------------------------------------------------------------------------


def force_bodyweight_static(
    *,
    mass_kg: float = 80.0,
    rate_hz: float = 1000.0,
    duration_s: float = 1.0,
    plate_id: str = "plate-1",
) -> ModalityFixture:
    """Constant vertical force equal to the participant's body weight."""
    sample_count = int(round(duration_s * rate_hz))
    stream_id = make_stream_id(Modality.FORCE, 1)
    body_weight_n = mass_kg * STANDARD_GRAVITY_M_S2
    rows: list[dict[str, Any]] = []

    for base in _identity_rows(
        count=sample_count,
        stream_id=stream_id,
        rate_hz=rate_hz,
        subject_id=SYNTHETIC_SUBJECT_ID,
        coordinate_frame_id=FORCE_FRAME_ID,
    ):
        rows.append(
            {
                **base,
                "plate_id": plate_id,
                "force_x_n": 0.0,
                "force_y_n": 0.0,
                "force_z_n": body_weight_n,
                "moment_x_n_m": None,
                "moment_y_n_m": None,
                "moment_z_n_m": None,
                "cop_x_m": 0.0,
                "cop_y_m": 0.0,
                "cop_z_m": None,
                "trigger_flag": None,
                "quality_flag": None,
            }
        )

    table = _build_table(Modality.FORCE, rows, rate_hz=rate_hz)
    expected: dict[str, tuple[Any, ...]] = {
        "force_x_n": tuple(0.0 for _ in range(sample_count)),
        "force_y_n": tuple(0.0 for _ in range(sample_count)),
        "force_z_n": tuple(body_weight_n for _ in range(sample_count)),
        "cop_x_m": tuple(0.0 for _ in range(sample_count)),
        "plate_id": tuple(plate_id for _ in range(sample_count)),
        "moment_z_n_m": tuple(None for _ in range(sample_count)),
    }
    return ModalityFixture(
        name="force_bodyweight_static",
        modality=Modality.FORCE,
        table=table,
        nominal_sampling_rate_hz=rate_hz,
        sample_count=sample_count,
        stream_id=stream_id,
        clock_id=SYNTHETIC_CLOCK_ID,
        synchronization_spec_id=SYNTHETIC_SYNC_SPEC_ID,
        subject_id=SYNTHETIC_SUBJECT_ID,
        coordinate_frame_id=FORCE_FRAME_ID,
        expected=expected,
        tolerance=1e-12,
    )


def force_dynamic_vertical(
    *,
    mass_kg: float = 80.0,
    rate_hz: float = 1000.0,
    duration_s: float = 1.0,
    frequency_hz: float = 1.0,
    mid_scale: float = 1.5,
    amplitude_scale: float = 1.0,
) -> ModalityFixture:
    """Vertical force ``BW * (mid_scale + amplitude_scale * sin(2*pi*f*t))``.

    A full cycle of the sinusoid over the window makes the impulse analytically
    known: ``mean(fz) = mid_scale * BW`` and ``impulse = mid_scale * BW * T``.
    """
    sample_count = int(round(duration_s * rate_hz))
    stream_id = make_stream_id(Modality.FORCE, 2)
    body_weight_n = mass_kg * STANDARD_GRAVITY_M_S2
    rows: list[dict[str, Any]] = []
    forces: list[float] = []

    for base in _identity_rows(
        count=sample_count,
        stream_id=stream_id,
        rate_hz=rate_hz,
        subject_id=SYNTHETIC_SUBJECT_ID,
        coordinate_frame_id=FORCE_FRAME_ID,
    ):
        index = int(base["sample_index"])
        t_s = index / rate_hz
        fz = body_weight_n * (
            mid_scale + amplitude_scale * math.sin(2.0 * math.pi * frequency_hz * t_s)
        )
        rows.append(
            {
                **base,
                "plate_id": "plate-1",
                "force_x_n": 0.0,
                "force_y_n": 0.0,
                "force_z_n": fz,
                "moment_x_n_m": None,
                "moment_y_n_m": None,
                "moment_z_n_m": None,
                "cop_x_m": None,
                "cop_y_m": None,
                "cop_z_m": None,
                "trigger_flag": index == 0,
                "quality_flag": None,
            }
        )
        forces.append(fz)

    table = _build_table(Modality.FORCE, rows, rate_hz=rate_hz)
    expected: dict[str, tuple[Any, ...]] = {
        "force_z_n": tuple(forces),
        "force_y_n": tuple(0.0 for _ in range(sample_count)),
        "cop_x_m": tuple(None for _ in range(sample_count)),
    }
    return ModalityFixture(
        name="force_dynamic_vertical",
        modality=Modality.FORCE,
        table=table,
        nominal_sampling_rate_hz=rate_hz,
        sample_count=sample_count,
        stream_id=stream_id,
        clock_id=SYNTHETIC_CLOCK_ID,
        synchronization_spec_id=SYNTHETIC_SYNC_SPEC_ID,
        subject_id=SYNTHETIC_SUBJECT_ID,
        coordinate_frame_id=FORCE_FRAME_ID,
        expected=expected,
        tolerance=1e-9,
    )


# ---------------------------------------------------------------------------
# LPT: known position trajectory with analytically known velocity
# ---------------------------------------------------------------------------


def lpt_constant_acceleration(
    *,
    rate_hz: float = 100.0,
    sample_count: int = 100,
    initial_position_m: float = 0.0,
    initial_velocity_m_s: float = 0.2,
    acceleration_m_s2: float = 1.5,
    load_kg: float = 20.0,
) -> ModalityFixture:
    """``s(t) = s0 + v0*t + a*t^2/2`` with ``v(t) = v0 + a*t``."""
    stream_id = make_stream_id(Modality.LPT, 1)
    rows: list[dict[str, Any]] = []
    positions: list[float] = []
    velocities: list[float] = []
    rep_indices: list[int | None] = []

    for base in _identity_rows(
        count=sample_count,
        stream_id=stream_id,
        rate_hz=rate_hz,
        subject_id=SYNTHETIC_SUBJECT_ID,
        coordinate_frame_id=None,
    ):
        index = int(base["sample_index"])
        t_s = index / rate_hz
        position = (
            initial_position_m + initial_velocity_m_s * t_s + 0.5 * acceleration_m_s2 * t_s**2
        )
        velocity = initial_velocity_m_s + acceleration_m_s2 * t_s
        rep_index = 0 if t_s < 0.5 else 1
        rows.append(
            {
                **base,
                "position_m": position,
                "velocity_m_s": velocity,
                "load_kg": load_kg,
                "load_n": None,
                "cable_angle_deg": None,
                "rep_index": rep_index,
                "quality_flag": None,
            }
        )
        positions.append(position)
        velocities.append(velocity)
        rep_indices.append(rep_index)

    table = _build_table(Modality.LPT, rows, rate_hz=rate_hz)
    expected: dict[str, tuple[Any, ...]] = {
        "position_m": tuple(positions),
        "velocity_m_s": tuple(velocities),
        "load_kg": tuple(load_kg for _ in range(sample_count)),
        "load_n": tuple(None for _ in range(sample_count)),
        "rep_index": tuple(rep_indices),
    }
    return ModalityFixture(
        name="lpt_constant_acceleration",
        modality=Modality.LPT,
        table=table,
        nominal_sampling_rate_hz=rate_hz,
        sample_count=sample_count,
        stream_id=stream_id,
        clock_id=SYNTHETIC_CLOCK_ID,
        synchronization_spec_id=SYNTHETIC_SYNC_SPEC_ID,
        subject_id=SYNTHETIC_SUBJECT_ID,
        expected=expected,
        tolerance=1e-12,
    )


# ---------------------------------------------------------------------------
# Tracking: multi-object stream (players + ball)
# ---------------------------------------------------------------------------


def tracking_multi_object(
    *,
    rate_hz: float = 25.0,
    frame_count: int = 50,
    player_speed_m_s: float = 4.0,
    ball_position_m: tuple[float, float] = (10.0, 5.0),
) -> ModalityFixture:
    """Two players moving at constant velocity and a stationary ball.

    The stream carries no single subject: identity lives per row, which is
    exactly why ``tracking_sample`` permits a null ``subject_id``.
    """
    stream_id = make_stream_id(Modality.TRACKING, 1)
    objects = (
        ("syn-player-01", "player", "syn-subject-0001", player_speed_m_s),
        ("syn-player-02", "player", "syn-subject-0002", -player_speed_m_s),
        ("syn-ball-01", "ball", None, 0.0),
    )
    rows: list[dict[str, Any]] = []
    sample_count = frame_count * len(objects)
    object_ids: list[str] = []
    x_values: list[float] = []
    y_values: list[float] = []
    subjects: list[str | None] = []
    groups: list[str | None] = []

    for frame in range(frame_count):
        t_s = frame / rate_hz
        for object_id, object_type, subject, speed in objects:
            if object_type == "ball":
                x_m, y_m = ball_position_m
            else:
                x_m, y_m = speed * t_s, 2.0 * speed * t_s
            rows.append(
                {
                    "dataset_id": SYNTHETIC_DATASET_ID,
                    "session_id": SYNTHETIC_SESSION_ID,
                    "trial_id": SYNTHETIC_TRIAL_ID,
                    "subject_id": subject,
                    "device_id": None,
                    "stream_id": stream_id,
                    "sample_index": frame * len(objects) + rows_offset(objects, object_id),
                    "t_rel_ns": round(frame * 1_000_000_000 / rate_hz),
                    "timestamp_utc_ns": None,
                    "nominal_sampling_rate_hz": rate_hz,
                    "measurement_class": SYNTHETIC_MEASUREMENT_CLASS,
                    "clock_id": SYNTHETIC_CLOCK_ID,
                    "synchronization_spec_id": SYNTHETIC_SYNC_SPEC_ID,
                    "coordinate_frame_id": TRACKING_FRAME_ID,
                    "object_id": object_id,
                    "object_type": object_type,
                    "group_id": None if object_type == "ball" else "team-home",
                    "x_m": x_m,
                    "y_m": y_m,
                    "z_m": None,
                    "vx_m_s": None,
                    "vy_m_s": None,
                    "vz_m_s": None,
                    "ax_m_s2": None,
                    "ay_m_s2": None,
                    "az_m_s2": None,
                    "is_detected": True,
                    "confidence": 0.95,
                }
            )
            object_ids.append(object_id)
            x_values.append(x_m)
            y_values.append(y_m)
            subjects.append(subject)
            groups.append(None if object_type == "ball" else "team-home")

    table = _build_table(Modality.TRACKING, rows, rate_hz=rate_hz)
    expected: dict[str, tuple[Any, ...]] = {
        "object_id": tuple(object_ids),
        "x_m": tuple(x_values),
        "y_m": tuple(y_values),
        "subject_id": tuple(subjects),
        "group_id": tuple(groups),
        "confidence": tuple(0.95 for _ in range(sample_count)),
    }
    return ModalityFixture(
        name="tracking_multi_object",
        modality=Modality.TRACKING,
        table=table,
        nominal_sampling_rate_hz=rate_hz,
        sample_count=sample_count,
        stream_id=stream_id,
        clock_id=SYNTHETIC_CLOCK_ID,
        synchronization_spec_id=SYNTHETIC_SYNC_SPEC_ID,
        subject_id=None,
        device_id=None,
        coordinate_frame_id=TRACKING_FRAME_ID,
        expected=expected,
        tolerance=1e-12,
    )


def rows_offset(objects: tuple[tuple[str, str, str | None, float], ...], object_id: str) -> int:
    for position, candidate in enumerate(objects):
        if candidate[0] == object_id:
            return position
    raise KeyError(object_id)


# ---------------------------------------------------------------------------
# Events: deterministic timestamps and context
# ---------------------------------------------------------------------------


def events_sequence() -> ModalityFixture:
    """Trigger-based records with no nominal sampling rate.

    ``kickoff`` and ``full_time`` carry no location or player, proving that the
    contract does not force concepts an event stream cannot provide.
    """
    stream_id = make_stream_id(Modality.EVENT, 1)
    definitions = (
        ("evt-kickoff", "kick_off", None, None, None, None, None, None),
        ("evt-pass-1", "pass", "pass", "team-home", "syn-player-01", 0.0, 0.0, "right"),
        ("evt-shot-1", "shot", "shot_on_target", "team-home", "syn-player-02", 50.0, 20.0, "left"),
        ("evt-goal-1", "goal", None, "team-home", "syn-player-02", 52.0, 21.0, None),
        ("evt-full-time", "full_time", None, None, None, None, None, None),
    )
    timestamps_s = (0.0, 2.5, 12.0, 13.0, 2700.0)
    rows: list[dict[str, Any]] = []
    event_ids: list[str] = []
    types: list[str] = []
    x_values: list[float | None] = []
    players: list[str | None] = []

    for index, (definition, t_s) in enumerate(zip(definitions, timestamps_s, strict=True)):
        (
            event_id,
            event_type,
            event_subtype,
            team_id,
            player_id,
            x_m,
            y_m,
            body_part,
        ) = definition
        rows.append(
            {
                "dataset_id": SYNTHETIC_DATASET_ID,
                "session_id": SYNTHETIC_SESSION_ID,
                "trial_id": SYNTHETIC_TRIAL_ID,
                "subject_id": None,
                "device_id": None,
                "stream_id": stream_id,
                "sample_index": index,
                "t_rel_ns": round(t_s * 1_000_000_000),
                "timestamp_utc_ns": None,
                "nominal_sampling_rate_hz": None,
                "measurement_class": MeasurementClass.SOURCE_DERIVED.value,
                "clock_id": SYNTHETIC_CLOCK_ID,
                "synchronization_spec_id": SYNTHETIC_SYNC_SPEC_ID,
                "coordinate_frame_id": TRACKING_FRAME_ID,
                "event_id": event_id,
                "event_type": event_type,
                "event_subtype": event_subtype,
                "provider_team_id": team_id,
                "provider_player_id": player_id,
                "x_m": x_m,
                "y_m": y_m,
                "body_part": body_part,
                "outcome": None,
                "provider_context_json": None,
            }
        )
        event_ids.append(event_id)
        types.append(event_type)
        x_values.append(x_m)
        players.append(player_id)

    table = _build_table(Modality.EVENT, rows, rate_hz=None)
    expected: dict[str, tuple[Any, ...]] = {
        "event_id": tuple(event_ids),
        "event_type": tuple(types),
        "x_m": tuple(x_values),
        "provider_player_id": tuple(players),
        "t_rel_ns": tuple(round(value * 1_000_000_000) for value in timestamps_s),
    }
    return ModalityFixture(
        name="events_sequence",
        modality=Modality.EVENT,
        table=table,
        nominal_sampling_rate_hz=None,
        sample_count=len(rows),
        stream_id=stream_id,
        clock_id=SYNTHETIC_CLOCK_ID,
        synchronization_spec_id=SYNTHETIC_SYNC_SPEC_ID,
        subject_id=None,
        device_id=None,
        coordinate_frame_id=TRACKING_FRAME_ID,
        measurement_class=MeasurementClass.SOURCE_DERIVED.value,
        expected=expected,
        tolerance=0.0,
    )


# ---------------------------------------------------------------------------
# Pose: small deterministic skeleton with confidence/error metadata
# ---------------------------------------------------------------------------


POSE_JOINTS: tuple[tuple[int, str, int | None], ...] = (
    (0, "pelvis", None),
    (1, "knee_right", 0),
    (2, "ankle_right", 1),
)


def pose_skeleton_trajectory(
    *,
    rate_hz: float = 25.0,
    frame_count: int = 50,
    amplitude_m: float = 0.05,
    frequency_hz: float = 0.5,
    unavailable_pattern: bool = False,
) -> ModalityFixture:
    """Deterministic lower-limb skeleton with an occluded low-confidence joint.

    ``unavailable_pattern`` turns the occluded frames into an explicit
    availability exercise: the source reports the joint as unavailable, the row
    carries null coordinates and no error estimate, and the coordinates are never
    imputed. The default remains a fully observed trajectory.
    """
    stream_id = make_stream_id(Modality.POSE, 1)
    rows: list[dict[str, Any]] = []
    joint_ids: list[int] = []
    z_values: list[float | None] = []
    confidences: list[float | None] = []
    sample_count = frame_count * len(POSE_JOINTS)

    for frame in range(frame_count):
        t_s = frame / rate_hz
        phase = math.sin(2.0 * math.pi * frequency_hz * t_s)
        for position, (joint_id, joint_name, parent_id) in enumerate(POSE_JOINTS):
            z_base = -0.45 * joint_id
            z_m = z_base + amplitude_m * phase * (1.0 if joint_id else 0.0)
            occluded = joint_id == 2 and frame % 10 == 0
            unavailable = unavailable_pattern and occluded
            confidence = 0.35 if occluded else 0.98
            rows.append(
                {
                    "dataset_id": SYNTHETIC_DATASET_ID,
                    "session_id": SYNTHETIC_SESSION_ID,
                    "trial_id": SYNTHETIC_TRIAL_ID,
                    "subject_id": SYNTHETIC_SUBJECT_ID,
                    "device_id": None,
                    "stream_id": stream_id,
                    "sample_index": frame * len(POSE_JOINTS) + position,
                    "t_rel_ns": round(frame * 1_000_000_000 / rate_hz),
                    "timestamp_utc_ns": None,
                    "nominal_sampling_rate_hz": rate_hz,
                    "measurement_class": MeasurementClass.MODEL_ESTIMATED.value,
                    "clock_id": SYNTHETIC_CLOCK_ID,
                    "synchronization_spec_id": SYNTHETIC_SYNC_SPEC_ID,
                    "coordinate_frame_id": POSE_FRAME_ID,
                    "skeleton_id": POSE_SKELETON_ID,
                    "joint_id": joint_id,
                    "joint_name": joint_name,
                    "parent_joint_id": parent_id,
                    "is_available": not unavailable,
                    "x_m": None if unavailable else 0.0,
                    "y_m": None if unavailable else 0.0,
                    "z_m": None if unavailable else z_m,
                    "confidence": confidence,
                    "error_m": (None if unavailable else (0.03 if occluded else None)),
                    "is_occluded": occluded,
                }
            )
            joint_ids.append(joint_id)
            z_values.append(None if unavailable else z_m)
            confidences.append(confidence)

    table = _build_table(Modality.POSE, rows, rate_hz=rate_hz)
    expected: dict[str, tuple[Any, ...]] = {
        "joint_id": tuple(joint_ids),
        "z_m": tuple(z_values),
        "confidence": tuple(confidences),
        "x_m": tuple(row["x_m"] for row in rows),
        "parent_joint_id": tuple(parent for _, _, parent in POSE_JOINTS * frame_count),
    }
    return ModalityFixture(
        name="pose_skeleton_trajectory",
        modality=Modality.POSE,
        table=table,
        nominal_sampling_rate_hz=rate_hz,
        sample_count=sample_count,
        stream_id=stream_id,
        clock_id=SYNTHETIC_CLOCK_ID,
        synchronization_spec_id=SYNTHETIC_SYNC_SPEC_ID,
        subject_id=SYNTHETIC_SUBJECT_ID,
        device_id=None,
        coordinate_frame_id=POSE_FRAME_ID,
        skeleton_id=POSE_SKELETON_ID,
        measurement_class=MeasurementClass.MODEL_ESTIMATED.value,
        expected=expected,
        tolerance=1e-12,
    )


def all_fixtures() -> tuple[ModalityFixture, ...]:
    """Every synthetic fixture, in modality order. Deterministic and repeatable."""
    return (
        gnss_constant_velocity(),
        imu_deterministic_trace(),
        force_bodyweight_static(),
        force_dynamic_vertical(),
        lpt_constant_acceleration(),
        tracking_multi_object(),
        events_sequence(),
        pose_skeleton_trajectory(),
    )


def fixtures_by_modality() -> dict[Modality, tuple[ModalityFixture, ...]]:
    grouped: dict[Modality, list[ModalityFixture]] = {}
    for fixture in all_fixtures():
        grouped.setdefault(fixture.modality, []).append(fixture)
    return {modality: tuple(items) for modality, items in grouped.items()}
