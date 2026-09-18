"""Known-answer tests for the locomotor processor.

Truth is independent synthetic geometry: straight-line constant velocity,
circular motion, known zone/effort profiles and an explicit spherical-geodesy
construction. Tolerances follow the discretization (central differences are
exact for degree <= 1 and O(h^2) for sinusoids).
"""

from __future__ import annotations

import math

import numpy as np
import pyarrow as pa
import pytest

from dynamis.contracts import GNSS_SCHEMA, TRACKING_SCHEMA
from dynamis.processors.locomotor import (
    DISTANCE_TOTAL,
    MAX_SPEED,
    MEAN_SPEED,
    locomotor_spec,
    process_locomotor,
)
from dynamis.processors.signals import WGS84_MEAN_RADIUS_M

DATASET_ID = "womens-soccer-positioning"


def _gnss_table(
    latitude: np.ndarray,
    longitude: np.ndarray,
    *,
    rate_hz: int = 10,
    stream_id: str = "gnss-1",
) -> pa.Table:
    samples = latitude.size
    step_ns = 1_000_000_000 // rate_hz
    rows = []
    for index in range(samples):
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "session_id": "J01",
                "trial_id": None,
                "subject_id": "s1",
                "device_id": None,
                "stream_id": stream_id,
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


def _tracking_table(
    positions: dict[str, tuple[np.ndarray, np.ndarray]],
    *,
    rate_hz: int = 10,
    is_detected: bool | None = True,
) -> pa.Table:
    step_ns = 1_000_000_000 // rate_hz
    rows = []
    for object_id, (x, y) in positions.items():
        for index in range(x.size):
            rows.append(
                {
                    "dataset_id": "skillcorner-opendata",
                    "session_id": "match-1",
                    "trial_id": "period-1",
                    "subject_id": None,
                    "device_id": None,
                    "stream_id": "tracking-period-1",
                    "sample_index": index * len(positions) + list(positions).index(object_id),
                    "t_rel_ns": index * step_ns,
                    "timestamp_utc_ns": None,
                    "nominal_sampling_rate_hz": float(rate_hz),
                    "measurement_class": "SOURCE_DERIVED",
                    "clock_id": "skillcorner-match-clock",
                    "synchronization_spec_id": "skillcorner-sync",
                    "coordinate_frame_id": "skillcorner-pitch-long-short-m",
                    "object_id": object_id,
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
                    "is_detected": is_detected,
                    "confidence": None,
                }
            )
    rows.sort(key=lambda row: (row["t_rel_ns"], row["sample_index"]))
    batch = pa.RecordBatch.from_pylist(rows, schema=TRACKING_SCHEMA)
    return pa.Table.from_batches([batch])


def _metric(result, declaration, entity_id: str | None = None) -> float:
    for metric in result.metrics:
        if metric.declaration.metric_id == declaration.metric_id and (
            entity_id is None or metric.entity_id == entity_id
        ):
            return metric.value
    raise AssertionError(f"metric {declaration.metric_id} not found")


def _planar_parameters(**overrides) -> dict:
    base = {
        "position_domain": "planar",
        "derivative": {"edge_policy": "one_sided_first_order"},
    }
    base.update(overrides)
    return base


def test_constant_position_yields_zero_distance_and_speed() -> None:
    samples = 50
    x = np.full(samples, 3.0)
    y = np.full(samples, -2.0)
    result = process_locomotor(
        _tracking_table({"player-1": (x, y)}), parameters=_planar_parameters()
    )
    assert _metric(result, DISTANCE_TOTAL) == pytest.approx(0.0, abs=1e-12)
    assert _metric(result, MAX_SPEED) == pytest.approx(0.0, abs=1e-12)
    assert _metric(result, MEAN_SPEED) == pytest.approx(0.0, abs=1e-12)


def test_constant_velocity_straight_line_is_exact() -> None:
    samples = 101
    rate_hz = 10
    speed = 6.5
    times = np.arange(samples) / rate_hz
    x = speed * times
    y = np.zeros(samples)
    result = process_locomotor(
        _tracking_table({"player-1": (x, y)}), parameters=_planar_parameters()
    )
    duration = (samples - 1) / rate_hz
    assert _metric(result, DISTANCE_TOTAL) == pytest.approx(speed * duration, rel=1e-12)
    assert _metric(result, MAX_SPEED) == pytest.approx(speed, rel=1e-12)
    assert _metric(result, MEAN_SPEED) == pytest.approx(speed, rel=1e-12)


def test_circular_motion_speed_converges_second_order() -> None:
    rate_hz = 100
    radius = 8.0
    omega = 0.7
    samples = 1001
    times = np.arange(samples) / rate_hz
    x = radius * np.cos(omega * times)
    y = radius * np.sin(omega * times)
    result = process_locomotor(
        _tracking_table({"player-1": (x, y)}, rate_hz=rate_hz),
        parameters=_planar_parameters(),
    )
    h = 1.0 / rate_hz
    # Central difference of a sinusoid has O(h^2) phase error; the bound below is
    # the second-order remainder of the difference operator.
    tolerance = (omega * h) ** 2 / 6.0 * radius * omega
    assert _metric(result, MAX_SPEED) == pytest.approx(radius * omega, abs=tolerance * 1.1)


def test_zones_and_efforts_use_explicit_configuration() -> None:
    rate_hz = 10
    step_ns = 1_000_000_000 // rate_hz
    segment_fast = int(3 * rate_hz)
    segment_slow = int(2 * rate_hz)
    positions = [0.0]
    speeds = [0.0] * segment_slow + [5.0] * segment_fast + [0.0] * segment_slow
    for speed in speeds[1:]:
        positions.append(positions[-1] + speed / rate_hz)
    x = np.asarray(positions)
    y = np.zeros_like(x)
    del step_ns
    parameters = _planar_parameters(
        zones=[
            {"name": "low", "lower_m_s": 0.0, "upper_m_s": 1.0},
            {"name": "high", "lower_m_s": 4.0, "upper_m_s": None},
        ],
        effort={
            "threshold_m_s": 4.0,
            "min_duration_s": 0.5,
            "merge_gap_s": 0.0,
            "hysteresis_m_s": 0.0,
        },
    )
    result = process_locomotor(_tracking_table({"player-1": (x, y)}), parameters=parameters)
    by_id = {metric.declaration.metric_id: metric.value for metric in result.metrics}
    # The central difference at the first fast sample spans the slow and fast
    # step, so that single boundary step (0.5 m) is attributed below the zone
    # threshold; the remaining 29 fast steps cover 14.5 m.
    assert by_id["locomotor.distance_zone.high"] == pytest.approx(14.5, rel=1e-12)
    assert by_id["locomotor.peak_speed_zone.high"] == pytest.approx(5.0, rel=1e-12)
    assert by_id["locomotor.effort_count"] == 1
    assert by_id["locomotor.effort_peak_speed"] == pytest.approx(5.0, rel=1e-12)


def test_rolling_peak_is_window_limited() -> None:
    rate_hz = 10
    speed = 4.0
    samples = 101
    times = np.arange(samples) / rate_hz
    x = speed * times
    y = np.zeros(samples)
    result = process_locomotor(
        _tracking_table({"player-1": (x, y)}),
        parameters=_planar_parameters(rolling_windows_s=[2.0, 5.0]),
    )
    by_id = {metric.declaration.metric_id: metric.value for metric in result.metrics}
    assert by_id["locomotor.rolling_peak_distance.2s"] == pytest.approx(8.0, rel=1e-12)
    assert by_id["locomotor.rolling_peak_distance.5s"] == pytest.approx(20.0, rel=1e-12)
    assert by_id["locomotor.rolling_peak_mean_speed.5s"] == pytest.approx(4.0, rel=1e-12)


def test_geodetic_distance_is_haversine_with_declared_radius() -> None:
    rate_hz = 10
    samples = 101
    latitude = np.full(samples, 40.0)
    delta_lon = 1e-4
    longitude = np.arange(samples) * delta_lon
    result = process_locomotor(
        _gnss_table(latitude, longitude, rate_hz=rate_hz),
        parameters={
            "position_domain": "geodetic",
            "distance_method": "haversine_wgs84_mean_radius",
            "enu_method": "equirectangular_tangent_plane_wgs84_mean_radius",
            "earth_radius_m": WGS84_MEAN_RADIUS_M,
            "derivative": {"edge_policy": "one_sided_first_order"},
        },
    )
    expected_distance = (
        WGS84_MEAN_RADIUS_M * math.cos(math.radians(40.0)) * math.radians(delta_lon) * (samples - 1)
    )
    expected_speed = expected_distance / ((samples - 1) / rate_hz)
    assert _metric(result, DISTANCE_TOTAL) == pytest.approx(expected_distance, rel=1e-12)
    assert _metric(result, MAX_SPEED) == pytest.approx(expected_speed, rel=1e-12)
    provenance = result.metrics[0].provenance
    assert provenance["distance_method"] == "haversine_wgs84_mean_radius"
    assert provenance["enu_method"] == "equirectangular_tangent_plane_wgs84_mean_radius"
    assert provenance["earth_radius_m"] == WGS84_MEAN_RADIUS_M


def test_geodetic_domain_requires_geodetic_methods() -> None:
    with pytest.raises(ValueError, match="distance_method"):
        locomotor_spec({"position_domain": "geodetic"})
    with pytest.raises(ValueError, match="enu_method"):
        locomotor_spec(
            {
                "position_domain": "geodetic",
                "distance_method": "haversine_wgs84_mean_radius",
            }
        )


def test_silent_resampling_and_interpolation_are_rejected() -> None:
    with pytest.raises(ValueError, match="resample_method"):
        locomotor_spec({"resample_method": "linear"})
    with pytest.raises(ValueError, match="interpolation"):
        locomotor_spec({"interpolation": "cubic"})


def test_multi_object_stream_produces_per_entity_metrics() -> None:
    samples = 21
    times = np.arange(samples) / 10.0
    fast_x = 8.0 * times
    slow_x = 2.0 * times
    table = _tracking_table(
        {
            "player-fast": (fast_x, np.zeros(samples)),
            "player-slow": (slow_x, np.zeros(samples)),
        }
    )
    result = process_locomotor(table, parameters=_planar_parameters())
    fast = _metric(result, MAX_SPEED, entity_id="player-fast")
    slow = _metric(result, MAX_SPEED, entity_id="player-slow")
    assert fast == pytest.approx(8.0, rel=1e-12)
    assert slow == pytest.approx(2.0, rel=1e-12)
    assert len({metric.entity_id for metric in result.metrics}) == 2


def test_step_speed_gate_can_exclude_implausible_steps_from_distance() -> None:
    samples = 30
    x = np.arange(samples) * 0.5
    x[15:] += 100.0  # a single coordinate re-acquisition teleport
    y = np.zeros(samples)
    table = _tracking_table({"player-1": (x, y)})
    kept = process_locomotor(
        table,
        parameters=_planar_parameters(
            step_speed_gate={"max_m_s": 15.0, "excluded_step_policy": "keep_step_in_distance"}
        ),
    )
    dropped = process_locomotor(
        table,
        parameters=_planar_parameters(
            step_speed_gate={"max_m_s": 15.0, "excluded_step_policy": "drop_step_from_distance"}
        ),
    )
    assert _metric(kept, DISTANCE_TOTAL) == pytest.approx(29 * 0.5 + 100.0, rel=1e-12)
    # The teleport segment is dropped whole, leaving the 28 ordinary 0.5 m steps.
    assert _metric(dropped, DISTANCE_TOTAL) == pytest.approx(28 * 0.5, rel=1e-12)
    provenance = next(
        metric.provenance
        for metric in dropped.metrics
        if metric.declaration.metric_id == DISTANCE_TOTAL.metric_id
    )
    assert provenance["excluded_steps"] == 1
    assert provenance["excluded_step_distance_policy"] == "drop_step_from_distance"
    assert provenance["distance_gated"] is True


def test_step_speed_gate_masks_kinematics_but_not_distance() -> None:
    samples = 30
    rate_hz = 10
    x = np.arange(samples) * 0.5
    x[15] += 8.0  # one provider position glitch of 8 m in a single frame
    y = np.zeros(samples)
    table = _tracking_table({"player-1": (x, y)}, rate_hz=rate_hz)
    ungated = process_locomotor(table, parameters=_planar_parameters())
    gated = process_locomotor(
        table,
        parameters=_planar_parameters(step_speed_gate={"max_m_s": 15.0}),
    )
    ungated_speed = _metric(ungated, MAX_SPEED)
    gated_speed = _metric(gated, MAX_SPEED)
    assert ungated_speed > 15.0
    assert gated_speed <= 15.0
    # Distance is explicitly not gated: the source path length is preserved.
    assert _metric(gated, DISTANCE_TOTAL) == pytest.approx(
        _metric(ungated, DISTANCE_TOTAL), rel=1e-12
    )
    provenance = next(
        metric.provenance
        for metric in gated.metrics
        if metric.declaration.metric_id == MAX_SPEED.metric_id
    )
    assert provenance["step_speed_gate"] == {"max_m_s": 15.0}
    assert provenance["invalid_samples"] > 0
    assert provenance["distance_gated"] is False


def test_detection_gate_requires_a_populated_flag() -> None:
    with pytest.raises(ValueError, match="cannot be honored"):
        process_locomotor(
            _tracking_table(
                {"player-1": (np.arange(10.0), np.zeros(10))},
                is_detected=None,
            ),
            parameters=_planar_parameters(detection_gate="require_is_detected"),
        )
    # A declared flag is honored: an undetected sample breaks the speed series.
    x = np.arange(10.0) * 0.5
    table = _tracking_table({"player-1": (x, np.zeros(10))})
    detected = process_locomotor(
        table, parameters=_planar_parameters(detection_gate="require_is_detected")
    )
    assert _metric(detected, MAX_SPEED) == pytest.approx(5.0, rel=1e-12)


def test_processor_is_deterministic() -> None:
    samples = 60
    times = np.arange(samples) / 10.0
    table = _tracking_table({"player-1": (4.0 * times, 1.5 * times)})
    first = process_locomotor(table, parameters=_planar_parameters())
    second = process_locomotor(table, parameters=_planar_parameters())
    assert first.series[0].table.equals(second.series[0].table)
    assert [metric.value for metric in first.metrics] == [metric.value for metric in second.metrics]
    assert first.diagnostics == second.diagnostics
