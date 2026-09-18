"""Known-answer tests for the full-record CMJ force processor.

Primary truth is independent synthetic signals with closed-form mechanics, not
agreement with the source's own summary values. Tolerances are justified by the
discretization: the trapezoidal rule is exact for the piecewise-linear
integrands of the constant-acceleration cases, and its ``O(h^2)`` error is
bounded explicitly for the linear-ramp case.
"""

from __future__ import annotations

import math

import numpy as np
import pyarrow as pa
import pytest

from dynamis.contracts import FORCE_SCHEMA
from dynamis.processors.force_cmj import (
    DEFAULT_PARAMETERS,
    JUMP_HEIGHT_JHWD,
    PEAK_SPECIFIC_POWER,
    force_cmj_spec,
    process_force_cmj,
)
from dynamis.processors.signals import STANDARD_GRAVITY_M_S2

DATASET_ID = "white-cmj-acc-grf"


def _force_table(
    ratio: np.ndarray,
    *,
    rate_hz: int = 1000,
    session_id: str = "white-s001",
) -> pa.Table:
    step_ns = 1_000_000_000 // rate_hz
    samples = ratio.size
    rows = []
    for index in range(samples):
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "session_id": session_id,
                "trial_id": f"{session_id}-arms-t00",
                "subject_id": session_id,
                "device_id": "white-kistler-platforms",
                "stream_id": f"force-{session_id}-arms-t00",
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


def _metric(result, declaration) -> float:
    by_id = {metric.declaration.metric_id: metric.value for metric in result.metrics}
    return by_id[declaration.metric_id]


def test_constant_body_weight_is_zero_mechanics() -> None:
    ratio = np.ones(100, dtype=np.float64)
    result = process_force_cmj(_force_table(ratio))
    for declaration in (
        JUMP_HEIGHT_JHWD,
        PEAK_SPECIFIC_POWER,
    ):
        assert _metric(result, declaration) == pytest.approx(0.0, abs=1e-12)
    velocity = next(
        metric.value
        for metric in result.metrics
        if metric.declaration.metric_id == "cmj.takeoff_velocity"
    )
    assert velocity == pytest.approx(0.0, abs=1e-12)


def test_constant_net_acceleration_matches_closed_form() -> None:
    """A constant net acceleration has exact trapezoidal integrals."""
    samples = 101
    rate_hz = 1000
    duration = (samples - 1) / rate_hz
    ratio = np.full(samples, 1.25, dtype=np.float64)
    result = process_force_cmj(_force_table(ratio, rate_hz=rate_hz))
    acceleration = STANDARD_GRAVITY_M_S2 * 0.25
    expected_velocity = acceleration * duration
    expected_displacement = 0.5 * acceleration * duration**2
    expected_jhwd = expected_velocity**2 / (2 * STANDARD_GRAVITY_M_S2) + expected_displacement
    expected_power = STANDARD_GRAVITY_M_S2 * 1.25 * expected_velocity

    by_id = {metric.declaration.metric_id: metric.value for metric in result.metrics}
    assert by_id["cmj.net_impulse_per_mass"] == pytest.approx(
        expected_velocity, rel=1e-12, abs=1e-12
    )
    assert by_id["cmj.takeoff_velocity"] == pytest.approx(expected_velocity, rel=1e-12)
    assert by_id["cmj.com_displacement_to_takeoff"] == pytest.approx(
        expected_displacement, rel=1e-12
    )
    assert by_id["cmj.takeoff_to_apex_height"] == pytest.approx(
        expected_velocity**2 / (2 * STANDARD_GRAVITY_M_S2), rel=1e-12
    )
    assert by_id["cmj.jump_height_jhwd"] == pytest.approx(expected_jhwd, rel=1e-12)
    assert by_id["cmj.peak_specific_power"] == pytest.approx(expected_power, rel=1e-12)
    assert by_id["cmj.peak_body_weight_ratio"] == pytest.approx(1.25, rel=1e-12)


def test_linear_ratio_ramp_second_order_error_bound() -> None:
    """The trapezoidal displacement error is bounded by T*h^2*max|v''|/12."""
    slope_per_s = 0.5  # dimensionless ratio per second
    for samples in (101, 1001):
        rate_hz = 1000
        duration = (samples - 1) / rate_hz
        times = np.linspace(0.0, duration, samples)
        ratio = 1.0 + slope_per_s * times
        result = process_force_cmj(_force_table(ratio, rate_hz=rate_hz))
        # a(t) = g*slope*t; v(t) = g*slope*t^2/2; s(T) = g*slope*T^3/6 with the
        # synthetic origin at the first sample of the ramp.
        c = STANDARD_GRAVITY_M_S2 * slope_per_s
        exact_displacement = c * duration**3 / 6.0
        observed = next(
            metric.value
            for metric in result.metrics
            if metric.declaration.metric_id == "cmj.com_displacement_to_takeoff"
        )
        h = 1.0 / rate_hz
        bound = duration * h**2 * c / 12.0
        assert abs(observed - exact_displacement) <= bound * 1.001 + 1e-12


def test_trapezoid_refinement_quadruples_accuracy() -> None:
    """Halving the step must divide the O(h^2) displacement error by about four."""
    slope_per_s = 0.8

    def displacement_error(samples: int) -> float:
        duration = 1.0
        rate_hz = samples - 1
        times = np.linspace(0.0, duration, samples)
        ratio = 1.0 + slope_per_s * times
        result = process_force_cmj(_force_table(ratio, rate_hz=rate_hz))
        observed = next(
            metric.value
            for metric in result.metrics
            if metric.declaration.metric_id == "cmj.com_displacement_to_takeoff"
        )
        c = STANDARD_GRAVITY_M_S2 * slope_per_s
        return abs(observed - c * duration**3 / 6.0)

    coarse = displacement_error(501)
    fine = displacement_error(1001)
    assert coarse > 0 and fine > 0
    assert 3.5 <= coarse / fine <= 4.5


def test_series_reproduces_scalar_metrics() -> None:
    rate_hz = 1000
    samples = 200
    times = np.arange(samples) / rate_hz
    ratio = 1.0 + 0.2 * np.sin(2 * math.pi * 2.0 * times)
    result = process_force_cmj(_force_table(ratio, rate_hz=rate_hz))
    series = result.series[0].table
    assert series.num_rows == samples
    takeoff_velocity = next(
        metric.value
        for metric in result.metrics
        if metric.declaration.metric_id == "cmj.takeoff_velocity"
    )
    assert series.column("velocity_m_s")[-1].as_py() == pytest.approx(takeoff_velocity, rel=1e-12)
    peak = max(series.column("power_w_kg").to_pylist())
    assert _metric(result, PEAK_SPECIFIC_POWER) == pytest.approx(peak, rel=1e-12)


def test_processor_is_deterministic() -> None:
    times = np.arange(300) / 1000.0
    ratio = 1.0 + 0.15 * np.sin(2 * math.pi * 1.5 * times)
    table = _force_table(ratio)
    first = process_force_cmj(table)
    second = process_force_cmj(table)
    assert first.series[0].table.equals(second.series[0].table)
    assert [metric.value for metric in first.metrics] == [metric.value for metric in second.metrics]


def test_non_finite_ratio_is_rejected() -> None:
    ratio = np.ones(100, dtype=np.float64)
    ratio[10] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        process_force_cmj(_force_table(ratio))


def test_unsupported_convention_parameters_are_rejected() -> None:
    with pytest.raises(ValueError, match="movement_onset_detection"):
        force_cmj_spec({"movement_onset_detection": "threshold_detector"})
    with pytest.raises(ValueError, match="integration"):
        force_cmj_spec({"integration": "simpson"})
    with pytest.raises(ValueError, match="gravity"):
        force_cmj_spec({"gravity_m_s2": 0.0})


def test_metric_ids_are_distinct_from_source_metric_ids() -> None:
    result = process_force_cmj(_force_table(np.ones(100, dtype=np.float64)))
    emitted = {metric.declaration.metric_id for metric in result.metrics}
    assert emitted.isdisjoint({"source_jump_height", "source_peak_power_relative"})
    assert "flight_time" not in " ".join(emitted)
    assert DEFAULT_PARAMETERS["body_mass_required"] is False
    assert DEFAULT_PARAMETERS["newton_force_produced"] is False
