"""Synthetic known-answer tests for the generic LPT processor.

No real GymAware dense stream exists and none is fabricated; these tests are the
only validation surface for rep segmentation, ROM and velocity features.
"""

from __future__ import annotations

import math

import numpy as np
import pyarrow as pa
import pytest

from dynamis.contracts import LPT_SCHEMA
from dynamis.processors.lpt import (
    REP_COUNT,
    REP_DURATION_MEAN,
    REP_MEAN_SPEED_MEAN,
    REP_ROM_MAX,
    VELOCITY_LOSS_FRACTION,
    lpt_spec,
    process_lpt,
)


def _lpt_table(position: np.ndarray, *, rate_hz: int = 100) -> pa.Table:
    samples = position.size
    step_ns = 1_000_000_000 // rate_hz
    rows = []
    for index in range(samples):
        rows.append(
            {
                "dataset_id": "synthetic-lpt",
                "session_id": "synthetic-session",
                "trial_id": "synthetic-trial",
                "subject_id": "synthetic-subject",
                "device_id": None,
                "stream_id": "lpt-synthetic-1",
                "sample_index": index,
                "t_rel_ns": index * step_ns,
                "timestamp_utc_ns": None,
                "nominal_sampling_rate_hz": float(rate_hz),
                "measurement_class": "PIPELINE_DERIVED",
                "clock_id": "synthetic-clock",
                "synchronization_spec_id": "synthetic-sync",
                "coordinate_frame_id": None,
                "position_m": float(position[index]),
                "velocity_m_s": None,
                "load_kg": None,
                "load_n": None,
                "cable_angle_deg": None,
                "rep_index": None,
                "quality_flag": None,
            }
        )
    batch = pa.RecordBatch.from_pylist(rows, schema=LPT_SCHEMA)
    return pa.Table.from_batches([batch])


def _metric(result, declaration) -> float:
    return next(
        metric.value
        for metric in result.metrics
        if metric.declaration.metric_id == declaration.metric_id
    )


def test_triangle_wave_is_one_repetition_with_exact_features() -> None:
    rate_hz = 100
    rise = np.linspace(0.0, 1.0, rate_hz + 1)
    fall = np.linspace(1.0, 0.0, rate_hz + 1)[1:]
    position = np.concatenate([rise, fall, np.array([0.01])])
    result = process_lpt(_lpt_table(position, rate_hz=rate_hz))
    assert _metric(result, REP_COUNT) == 1.0
    assert _metric(result, REP_ROM_MAX) == pytest.approx(1.0, rel=1e-9)
    # The rep spans the seeded first sample (t=0) to the accepted trough
    # extremum (t=2.0); the trailing 0.01 m sample only confirms the reversal.
    assert _metric(result, REP_DURATION_MEAN) == pytest.approx(2.0, rel=1e-9)
    assert _metric(result, REP_MEAN_SPEED_MEAN) == pytest.approx(0.5, rel=1e-9)
    series = result.series[0].table
    assert series.num_rows == 1
    assert series.column("peak_speed_m_s")[0].as_py() == pytest.approx(1.0, rel=1e-9)


def test_sinusoid_yields_known_rom_and_peak_speed() -> None:
    rate_hz = 100
    amplitude = 0.6
    frequency = 1.0
    periods = 4
    samples = int(periods / frequency * rate_hz) + 1
    times = np.arange(samples) / rate_hz
    omega = 2 * math.pi * frequency
    position = -amplitude * np.cos(omega * times)
    result = process_lpt(_lpt_table(position, rate_hz=rate_hz))
    # Reversals at each half-period extremum; repetitions pair same-direction
    # extrema, so four periods produce three complete repetitions.
    assert _metric(result, REP_COUNT) == 3.0
    assert _metric(result, REP_ROM_MAX) == pytest.approx(2 * amplitude, abs=0.005)
    series = result.series[0].table
    peak = max(series.column("peak_speed_m_s").to_pylist())
    assert peak == pytest.approx(amplitude * omega, rel=5e-3)
    assert series.column("duration_s")[0].as_py() == pytest.approx(1.0 / frequency, abs=0.03)


def test_decaying_amplitude_produces_positive_velocity_loss() -> None:
    rate_hz = 100
    periods = 6
    samples = int(periods * rate_hz) + 1
    times = np.arange(samples) / rate_hz
    omega = 2 * math.pi
    envelope = np.exp(-0.25 * times)
    position = -0.7 * envelope * np.cos(omega * times)
    result = process_lpt(_lpt_table(position, rate_hz=rate_hz))
    loss = _metric(result, VELOCITY_LOSS_FRACTION)
    assert 0.05 < loss < 0.95


def test_range_minimum_discards_noise_repetitions() -> None:
    rate_hz = 100
    samples = 400
    times = np.arange(samples) / rate_hz
    position = 0.01 * np.sin(2 * math.pi * 2.0 * times)
    result = process_lpt(_lpt_table(position, rate_hz=rate_hz))
    assert _metric(result, REP_COUNT) == 0.0
    assert all(
        metric.declaration.metric_id != VELOCITY_LOSS_FRACTION.metric_id
        for metric in result.metrics
    )


def test_gymaware_validation_claim_is_rejected() -> None:
    with pytest.raises(ValueError, match="GymAware"):
        lpt_spec({"gymaware_validation_claimed": True})
    with pytest.raises(ValueError, match="synthetic"):
        lpt_spec({"validation_scope": "validated_against_gymaware"})


def test_processor_is_deterministic() -> None:
    times = np.arange(600) / 100.0
    position = -0.5 * np.cos(2 * math.pi * times)
    table = _lpt_table(position)
    first = process_lpt(table)
    second = process_lpt(table)
    assert first.series[0].table.equals(second.series[0].table)
    assert [metric.value for metric in first.metrics] == [metric.value for metric in second.metrics]
    provenance = first.metrics[0].provenance
    assert provenance["validation_scope"] == "synthetic_known_answer_only"
    assert provenance["gymaware_validation_claimed"] is False
    assert provenance["real_gymaware_dense_data_used"] is False
