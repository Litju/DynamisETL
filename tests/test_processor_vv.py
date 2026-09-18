"""Property-based V&V for the deterministic processor kernels.

Primary truth is independent synthetic signals: constant/polynomial trajectories,
rigid landmark geometry and exact segmentations. Tolerances follow the
discretization (trapezoidal/central-difference leading error terms) rather than a
corpus maximum. Missing-data cases prove that no processor imputes a value.
"""

from __future__ import annotations

import math

import numpy as np
import pyarrow as pa
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from dynamis.contracts import FORCE_SCHEMA, GNSS_SCHEMA, POSE_SCHEMA
from dynamis.processors.force_cmj import process_force_cmj
from dynamis.processors.locomotor import (
    DISTANCE_TOTAL,
    MAX_SPEED,
    process_locomotor,
)
from dynamis.processors.pose import process_pose
from dynamis.processors.signals import (
    EDGE_ONE_SIDED_FIRST_ORDER,
    SpeedZone,
    cumulative_trapezoid,
    derivative,
    effort_segments,
    rolling_peak_window,
    zone_statistics,
)

HYPOTHESIS_SETTINGS = settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


def _gnss_table(latitude: np.ndarray, longitude: np.ndarray, *, rate_hz: int = 10) -> pa.Table:
    samples = latitude.size
    step_ns = 1_000_000_000 // rate_hz
    rows = []
    for index in range(samples):
        rows.append(
            {
                "dataset_id": "womens-soccer-positioning",
                "session_id": "J01",
                "trial_id": None,
                "subject_id": "s1",
                "device_id": None,
                "stream_id": "gnss-vv",
                "sample_index": index,
                "t_rel_ns": index * step_ns,
                "timestamp_utc_ns": None,
                "nominal_sampling_rate_hz": float(rate_hz),
                "measurement_class": "SOURCE_DERIVED",
                "clock_id": "womens-clock",
                "synchronization_spec_id": "womens-sync",
                "coordinate_frame_id": None,
                "latitude_deg": float(latitude[index]),
                "longitude_deg": float(longitude[index]),
                "ellipsoidal_height_m": None,
                "ecef_x_m": None,
                "ecef_y_m": None,
                "ecef_z_m": None,
                "speed_m_s": None,
                "course_deg": None,
                "horizontal_accuracy_m": None,
                "vertical_accuracy_m": None,
                "hdop": None,
                "satellites_used": None,
                "fix_type": None,
                "quality_flag": None,
            }
        )
    batch = pa.RecordBatch.from_pylist(rows, schema=GNSS_SCHEMA)
    return pa.Table.from_batches([batch])


def _force_table(ratio: np.ndarray, *, rate_hz: int = 1000) -> pa.Table:
    samples = ratio.size
    step_ns = 1_000_000_000 // rate_hz
    rows = []
    for index in range(samples):
        rows.append(
            {
                "dataset_id": "white-cmj-acc-grf",
                "session_id": "white-s001",
                "trial_id": "white-s001-arms-t00",
                "subject_id": "white-s001",
                "device_id": "white-kistler-platforms",
                "stream_id": "force-vv",
                "sample_index": index,
                "t_rel_ns": (index - (samples - 1)) * step_ns,
                "timestamp_utc_ns": None,
                "nominal_sampling_rate_hz": float(rate_hz),
                "measurement_class": "SOURCE_DERIVED",
                "clock_id": "white-takeoff-relative",
                "synchronization_spec_id": "white-source-provided-takeoff-aligned",
                "coordinate_frame_id": "white-kistler-plate-vertical",
                "plate_id": None,
                "force_x_n": None,
                "force_y_n": None,
                "force_z_n": None,
                "force_z_body_weight_ratio": float(ratio[index]),
                "moment_x_n_m": None,
                "moment_y_n_m": None,
                "moment_z_n_m": None,
                "cop_x_m": None,
                "cop_y_m": None,
                "cop_z_m": None,
                "trigger_flag": None,
                "quality_flag": None,
            }
        )
    batch = pa.RecordBatch.from_pylist(rows, schema=FORCE_SCHEMA)
    return pa.Table.from_batches([batch])


def _tables_equal(left: pa.Table, right: pa.Table) -> bool:
    """Logical table equality that treats NaN in the same position as equal."""
    if left.column_names != right.column_names or left.num_rows != right.num_rows:
        return False
    for name in left.column_names:
        a = np.asarray(left.column(name).to_numpy(zero_copy_only=False))
        b = np.asarray(right.column(name).to_numpy(zero_copy_only=False))
        if np.issubdtype(a.dtype, np.floating):
            if not np.array_equal(a, b, equal_nan=True):
                return False
        elif not np.array_equal(a, b):
            return False
    return True


def _rotation_matrix(ax: float, ay: float, az: float) -> np.ndarray:
    cx, sx = math.cos(ax), math.sin(ax)
    cy, sy = math.cos(ay), math.sin(ay)
    cz, sz = math.cos(az), math.sin(az)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rz @ ry @ rx


def _pose_table(points: dict[str, list[tuple[float, float, float]]]) -> pa.Table:
    names = list(points)
    frame_count = len(points[names[0]])
    rows = []
    for frame in range(frame_count):
        for joint_id, name in enumerate(names):
            x, y, z = points[name][frame]
            rows.append(
                {
                    "dataset_id": "skillcorner-opendata",
                    "session_id": "1925299",
                    "trial_id": "period_1",
                    "subject_id": "SC-P1",
                    "device_id": None,
                    "stream_id": "pose-vv",
                    "sample_index": frame * len(names) + joint_id,
                    "t_rel_ns": frame * 40_000_000,
                    "timestamp_utc_ns": None,
                    "nominal_sampling_rate_hz": 25.0,
                    "measurement_class": "MODEL_ESTIMATED",
                    "clock_id": "skillcorner-match-clock",
                    "synchronization_spec_id": "skillcorner-source-provided-match-clock",
                    "coordinate_frame_id": "skillcorner-pose-hybrid-m",
                    "skeleton_id": "skillcorner-bodypose-29-landmarks",
                    "joint_id": joint_id,
                    "joint_name": name,
                    "parent_joint_id": None,
                    "is_available": True,
                    "x_m": x,
                    "y_m": y,
                    "z_m": z,
                    "confidence": None,
                    "error_m": None,
                    "is_occluded": None,
                }
            )
    batch = pa.RecordBatch.from_pylist(rows, schema=POSE_SCHEMA)
    return pa.Table.from_batches([batch])


@HYPOTHESIS_SETTINGS
@given(
    ratio=st.floats(min_value=0.2, max_value=3.0, allow_nan=False, allow_infinity=False),
    samples=st.integers(min_value=20, max_value=400),
)
def test_force_identities_hold_for_any_constant_ratio(ratio: float, samples: int) -> None:
    """Net impulse/mass equals takeoff velocity and JHwd equals apex + displacement."""
    result = process_force_cmj(_force_table(np.full(samples, ratio)))
    by_id = {metric.declaration.metric_id: metric.value for metric in result.metrics}
    assert by_id["cmj.net_impulse_per_mass"] == pytest.approx(
        by_id["cmj.takeoff_velocity"], rel=1e-12
    )
    assert by_id["cmj.jump_height_jhwd"] == pytest.approx(
        by_id["cmj.takeoff_to_apex_height"] + by_id["cmj.com_displacement_to_takeoff"],
        rel=1e-12,
    )
    assert result.series[0].table.num_rows == samples


@HYPOTHESIS_SETTINGS
@given(
    speed=st.floats(min_value=0.1, max_value=12.0, allow_nan=False),
    angle=st.floats(min_value=-math.pi, max_value=math.pi, allow_nan=False),
    samples=st.integers(min_value=10, max_value=200),
)
def test_locomotor_constant_velocity_is_exact(speed: float, angle: float, samples: int) -> None:
    rate_hz = 10
    earth_radius_m = 6_371_008.8
    times = np.arange(samples) / rate_hz
    vx, vy = speed * math.cos(angle), speed * math.sin(angle)
    # Exact inverse of the processor's own equirectangular tangent-plane ENU:
    # longitude/latitude increments are built in radians with the same radius, so
    # the tangent-plane velocity is the constructed velocity to floating point.
    latitude = 40.0 + np.degrees((vy * times) / earth_radius_m)
    longitude = -3.0 + np.degrees((vx * times) / (earth_radius_m * math.cos(math.radians(40.0))))
    result = process_locomotor(
        _gnss_table(latitude, longitude, rate_hz=rate_hz),
        parameters={
            "position_domain": "geodetic",
            "distance_method": "haversine_wgs84_mean_radius",
            "enu_method": "equirectangular_tangent_plane_wgs84_mean_radius",
            "earth_radius_m": earth_radius_m,
            "derivative": {"edge_policy": EDGE_ONE_SIDED_FIRST_ORDER},
        },
    )
    duration = (samples - 1) / rate_hz
    distance = next(
        metric.value
        for metric in result.metrics
        if metric.declaration.metric_id == DISTANCE_TOTAL.metric_id
    )
    max_speed = next(
        metric.value
        for metric in result.metrics
        if metric.declaration.metric_id == MAX_SPEED.metric_id
    )
    # Tangent-plane velocity agrees to degrees<->radians rounding (rel ~1e-9
    # observed). The haversine distance differs from the tangent-plane path by
    # the latitude dependence of the east component; the worst case of this
    # construction is (speed * duration * tan(lat0) / R) < 4e-5, so the
    # tolerance is explicit rather than fitted.
    assert distance == pytest.approx(speed * duration, rel=1e-4)
    assert max_speed == pytest.approx(speed, rel=1e-7)


@HYPOTHESIS_SETTINGS
@given(ax=st.floats(-3, 3), ay=st.floats(-3, 3), az=st.floats(-3, 3))
def test_pose_segment_lengths_and_angles_are_rigid_invariant(
    ax: float, ay: float, az: float
) -> None:
    hip = np.array([0.11, -0.03, -0.51])
    knee = np.array([0.10, -0.02, -0.06])
    ankle = np.array([0.09, 0.04, 0.02])
    rotation = _rotation_matrix(ax, ay, az)
    translation = np.array([12.0, -7.0, 3.0])
    moved = {
        name: (rotation @ point + translation)
        for name, point in (
            ("lHip", hip),
            ("lKnee", knee),
            ("lAnkle", ankle),
        )
    }
    parameters = {
        "segments": [
            {"name": "left_thigh", "start_landmark": "lHip", "end_landmark": "lKnee"},
            {"name": "left_shank", "start_landmark": "lKnee", "end_landmark": "lAnkle"},
        ],
        "angles": [
            {
                "name": "left_knee",
                "vertex_landmark": "lKnee",
                "first_landmark": "lHip",
                "second_landmark": "lAnkle",
            }
        ],
        "derivative": {"edge_policy": EDGE_ONE_SIDED_FIRST_ORDER},
    }
    first = process_pose(
        _pose_table({name: [tuple(point)] for name, point in moved.items()}),
        parameters=parameters,
    )
    second = process_pose(
        _pose_table({name: [tuple(point)] for name, point in moved.items()}),
        parameters=parameters,
    )
    assert _tables_equal(first.series[0].table, second.series[0].table)
    by_id = {metric.declaration.metric_id: metric.value for metric in second.metrics}
    assert by_id["pose.segment_length_mean.left_thigh"] == pytest.approx(
        np.linalg.norm(knee - hip), rel=1e-9
    )
    assert by_id["pose.segment_length_mean.left_shank"] == pytest.approx(
        np.linalg.norm(ankle - knee), rel=1e-9
    )
    angle = second.series[0].table.column("angle_left_knee_rad")[0].as_py()
    u = hip - knee
    v = ankle - knee
    expected = math.acos(float(np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v))))
    assert angle == pytest.approx(expected, rel=1e-9)


@HYPOTHESIS_SETTINGS
@given(
    speed=st.floats(min_value=0.0, max_value=4.0, allow_nan=False),
    samples=st.integers(min_value=3, max_value=200),
)
def test_constant_position_has_zero_distance_and_speed(speed: float, samples: int) -> None:
    del speed  # the signal is constant by construction
    latitude = np.full(samples, 40.0)
    longitude = np.full(samples, -3.0)
    result = process_locomotor(
        _gnss_table(latitude, longitude),
        parameters={
            "position_domain": "geodetic",
            "distance_method": "haversine_wgs84_mean_radius",
            "enu_method": "equirectangular_tangent_plane_wgs84_mean_radius",
            "derivative": {"edge_policy": EDGE_ONE_SIDED_FIRST_ORDER},
        },
    )
    by_id = {metric.declaration.metric_id: metric.value for metric in result.metrics}
    assert by_id[DISTANCE_TOTAL.metric_id] == pytest.approx(0.0, abs=1e-9)
    assert by_id[MAX_SPEED.metric_id] == pytest.approx(0.0, abs=1e-9)


@HYPOTHESIS_SETTINGS
@given(
    step=st.floats(min_value=1e-6, max_value=1.0, allow_nan=False),
    samples=st.integers(min_value=2, max_value=100),
)
def test_cumulative_trapezoid_is_exact_for_linear_integrands(step: float, samples: int) -> None:
    values = 3.0 * np.arange(samples, dtype=np.float64)
    cumulative = cumulative_trapezoid(values, step)
    expected = 0.5 * 3.0 * (np.arange(samples, dtype=np.float64) ** 2) * step
    assert np.allclose(cumulative, expected, rtol=1e-12, atol=1e-12)


@HYPOTHESIS_SETTINGS
@given(
    amplitude=st.floats(min_value=0.1, max_value=5.0, allow_nan=False),
    frequency=st.floats(min_value=0.5, max_value=8.0, allow_nan=False),
)
def test_derivative_of_sinusoid_has_analytic_amplitude(amplitude: float, frequency: float) -> None:
    rate_hz = 1000
    samples = 2001
    h = 1.0 / rate_hz
    times = np.arange(samples) * h
    omega = 2 * math.pi * frequency
    values = amplitude * np.sin(omega * times)
    observed = derivative(values, h, edge_policy="nan")
    interior = observed[1:-1]
    sinc = math.sin(omega * h) / (omega * h)
    # The sampled maximum sits at a grid sample, not exactly at the analytic
    # peak, so the comparison carries the O((omega*h)^2) operator remainder.
    assert np.max(np.abs(interior)) == pytest.approx(amplitude * omega * sinc, rel=1e-4)


@HYPOTHESIS_SETTINGS
@given(
    speed=st.floats(min_value=1.0, max_value=9.0, allow_nan=False),
    duration_s=st.floats(min_value=0.5, max_value=5.0, allow_nan=False),
)
def test_effort_duration_matches_the_constructed_span(speed: float, duration_s: float) -> None:
    rate_hz = 10
    step_s = 1.0 / rate_hz
    high_samples = int(round(duration_s * rate_hz)) + 1
    values = np.concatenate([np.zeros(5), np.full(high_samples, speed), np.zeros(5)])
    distance_step = np.concatenate(([0.0], values[1:] * step_s))
    times = np.arange(values.size) * step_s
    durations = np.full(values.size, step_s)
    parameters = type(
        "P",
        (),
        {
            "threshold_m_s": speed * 0.8,
            "min_duration_s": 0.3,
            "merge_gap_s": 0.0,
            "hysteresis_m_s": 0.0,
        },
    )()
    efforts = effort_segments(
        values, distance_step, times_s=times, sample_duration_s=durations, parameters=parameters
    )
    assert len(efforts) == 1
    assert efforts[0].duration_s == pytest.approx(high_samples * step_s, rel=1e-9)


@HYPOTHESIS_SETTINGS
@given(window=st.floats(min_value=0.5, max_value=20.0, allow_nan=False))
def test_rolling_peak_is_bounded_by_window_times_speed(window: float) -> None:
    rate_hz = 10
    speed = 4.0
    samples = 200
    step_s = 1.0 / rate_hz
    distance = np.arange(samples) * speed * step_s
    times = np.arange(samples) * step_s
    peak, end_index = rolling_peak_window(distance, times, window_s=window)
    if math.isnan(peak):
        # A window longer than the series is never extrapolated.
        assert times[-1] - times[0] < window
        assert end_index == -1
        return
    assert peak <= window * speed + 1e-9
    assert end_index >= 0


def test_missing_position_data_is_never_imputed() -> None:
    latitude = np.full(10, 40.0)
    latitude[5] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        process_locomotor(
            _gnss_table(latitude, np.full(10, -3.0)),
            parameters={
                "position_domain": "geodetic",
                "distance_method": "haversine_wgs84_mean_radius",
                "enu_method": "equirectangular_tangent_plane_wgs84_mean_radius",
            },
        )


@HYPOTHESIS_SETTINGS
@given(
    threshold=st.floats(min_value=0.5, max_value=3.0, allow_nan=False),
    speed=st.floats(min_value=3.0, max_value=8.0, allow_nan=False),
)
def test_step_gate_never_increases_peak_speed(threshold: float, speed: float) -> None:
    rate_hz = 10
    samples = 50
    x = np.full(samples, 20.0)
    x[25:] += 500.0  # teleport
    y = np.zeros(samples)
    parameters = {
        "position_domain": "planar",
        "derivative": {"edge_policy": EDGE_ONE_SIDED_FIRST_ORDER},
    }
    ungated = process_locomotor(
        _tracking_table_for_vv(x, y, rate_hz=rate_hz), parameters=parameters
    )
    gated = process_locomotor(
        _tracking_table_for_vv(x, y, rate_hz=rate_hz),
        parameters={**parameters, "step_speed_gate": {"max_m_s": threshold}},
    )
    peak_ungated = next(
        metric.value
        for metric in ungated.metrics
        if metric.declaration.metric_id == MAX_SPEED.metric_id
    )
    peak_gated = next(
        metric.value
        for metric in gated.metrics
        if metric.declaration.metric_id == MAX_SPEED.metric_id
    )
    assert peak_gated <= min(peak_ungated, threshold) + 1e-9


def _tracking_table_for_vv(x: np.ndarray, y: np.ndarray, *, rate_hz: int = 10) -> pa.Table:
    from dynamis.contracts import TRACKING_SCHEMA

    step_ns = 1_000_000_000 // rate_hz
    rows = []
    for index in range(x.size):
        rows.append(
            {
                "dataset_id": "skillcorner-opendata",
                "session_id": "match-1",
                "trial_id": "period-1",
                "subject_id": None,
                "device_id": None,
                "stream_id": "tracking-vv",
                "sample_index": index,
                "t_rel_ns": index * step_ns,
                "timestamp_utc_ns": None,
                "nominal_sampling_rate_hz": float(rate_hz),
                "measurement_class": "SOURCE_DERIVED",
                "clock_id": "skillcorner-match-clock",
                "synchronization_spec_id": "skillcorner-sync",
                "coordinate_frame_id": "skillcorner-pitch-long-short-m",
                "object_id": "player-1",
                "object_type": "player",
                "group_id": None,
                "x_m": float(x[index]),
                "y_m": float(y[index]),
                "z_m": None,
                "vx_m_s": None,
                "vy_m_s": None,
                "vz_m_s": None,
                "ax_m_s2": None,
                "ay_m_s2": None,
                "az_m_s2": None,
                "is_detected": True,
                "confidence": None,
            }
        )
    batch = pa.RecordBatch.from_pylist(rows, schema=TRACKING_SCHEMA)
    return pa.Table.from_batches([batch])


def test_zone_statistics_partition_distance() -> None:
    speed = np.array([0.5, 1.5, 3.5, 7.0, 7.2, 2.0])
    distance_step = np.array([0.1, 0.2, 0.3, 0.5, 0.6, 0.2])
    durations = np.full(speed.size, 0.1)
    zones = (
        SpeedZone("low", 0.0, 2.0),
        SpeedZone("medium", 2.0, 5.0),
        SpeedZone("high", 5.0, None),
    )
    stats = zone_statistics(speed, distance_step, zones=zones, sample_duration_s=durations)
    total = sum(item["distance_m"] for item in stats.values())
    assert total == pytest.approx(float(np.sum(distance_step)), rel=1e-12)
