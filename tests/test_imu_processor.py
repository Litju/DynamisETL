"""Known-answer tests for the IMU and cross-sensor processors."""

from __future__ import annotations

import math

import numpy as np
import pyarrow as pa
import pytest

from dynamis.contracts import FORCE_SCHEMA, IMU_SCHEMA
from dynamis.processors.cross_sensor import (
    PAIRED_SAMPLE_COUNT,
    PEARSON_R,
    process_cross_sensor,
)
from dynamis.processors.imu import (
    JERK_PEAK,
    RESULTANT_PEAK,
    RESULTANT_RMS,
    imu_spec,
    process_imu,
)
from dynamis.processors.signals import STANDARD_GRAVITY_M_S2

DATASET_ID = "white-cmj-acc-grf"


def _imu_table(
    axes: tuple[np.ndarray, np.ndarray, np.ndarray],
    *,
    rate_hz: int = 1000,
    trial_id: str = "white-s001-arms-t00",
) -> pa.Table:
    samples = axes[0].size
    step_ns = 1_000_000_000 // rate_hz
    rows = []
    for index in range(samples):
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "session_id": "white-s001",
                "trial_id": trial_id,
                "subject_id": "white-s001",
                "device_id": "white-delsys-trigno",
                "stream_id": f"imu-{trial_id}",
                "sample_index": index,
                "t_rel_ns": (index - (samples - 1)) * step_ns,
                "timestamp_utc_ns": None,
                "nominal_sampling_rate_hz": float(rate_hz),
                "measurement_class": "SOURCE_DERIVED",
                "clock_id": "white-takeoff-relative",
                "synchronization_spec_id": "white-source-provided-takeoff-aligned",
                "coordinate_frame_id": "white-delsys-trigno-sensor",
                "accel_x_m_s2": float(axes[0][index]),
                "accel_y_m_s2": float(axes[1][index]),
                "accel_z_m_s2": float(axes[2][index]),
                "gyro_x_rad_s": None,
                "gyro_y_rad_s": None,
                "gyro_z_rad_s": None,
                "mag_x_ut": None,
                "mag_y_ut": None,
                "mag_z_ut": None,
                "temperature_deg_c": None,
                "quality_flag": None,
            }
        )
    batch = pa.RecordBatch.from_pylist(rows, schema=IMU_SCHEMA)
    return pa.Table.from_batches([batch])


def _force_table(
    ratio: np.ndarray,
    *,
    rate_hz: int = 1000,
    trial_id: str = "white-s001-arms-t00",
) -> pa.Table:
    samples = ratio.size
    step_ns = 1_000_000_000 // rate_hz
    rows = []
    for index in range(samples):
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "session_id": "white-s001",
                "trial_id": trial_id,
                "subject_id": "white-s001",
                "device_id": "white-kistler-platforms",
                "stream_id": f"force-{trial_id}",
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
    return next(
        metric.value
        for metric in result.metrics
        if metric.declaration.metric_id == declaration.metric_id
    )


def test_constant_acceleration_has_zero_jerk() -> None:
    samples = 200
    zeros = np.zeros(samples)
    axes = (zeros, zeros, np.full(samples, STANDARD_GRAVITY_M_S2))
    result = process_imu(_imu_table(axes))
    assert _metric(result, RESULTANT_RMS) == pytest.approx(STANDARD_GRAVITY_M_S2, rel=1e-12)
    assert _metric(result, RESULTANT_PEAK) == pytest.approx(STANDARD_GRAVITY_M_S2, rel=1e-12)
    assert _metric(result, JERK_PEAK) == pytest.approx(0.0, abs=1e-12)


def test_sinusoidal_resultant_rms_peak_and_jerk_match_analytic_values() -> None:
    rate_hz = 1000
    amplitude = 4.0
    frequency = 2.0
    samples = 2001
    times = np.arange(samples) / rate_hz
    signal = amplitude * np.sin(2 * math.pi * frequency * times)
    zeros = np.zeros(samples)
    result = process_imu(_imu_table((signal, zeros, zeros), rate_hz=rate_hz))
    omega = 2 * math.pi * frequency
    h = 1.0 / rate_hz
    assert _metric(result, RESULTANT_RMS) == pytest.approx(amplitude / math.sqrt(2), rel=1e-3)
    assert _metric(result, RESULTANT_PEAK) == pytest.approx(amplitude, rel=1e-6)
    sinc = math.sin(omega * h) / (omega * h)
    # The sampled maximum sits near, not exactly at, the analytic cosine peak, so
    # the discrete peak carries the same O((omega*h)^2) remainder as the operator.
    assert _metric(result, JERK_PEAK) == pytest.approx(amplitude * omega * sinc, rel=1e-3)
    provenance = result.metrics[0].provenance
    assert provenance["resultant_semantics"] == "sensor_frame_euclidean_norm_of_proper_acceleration"
    assert provenance["anatomical_orientation"] == "undocumented_preserved"
    assert provenance["filter_applied"] is False


def test_configured_filter_attenuates_a_high_frequency_component() -> None:
    rate_hz = 250
    samples = 2500
    times = np.arange(samples) / rate_hz
    low = 3.0 * np.sin(2 * math.pi * 2.0 * times)
    high = 3.0 * np.sin(2 * math.pi * 60.0 * times)
    zeros = np.zeros(samples)
    raw = process_imu(_imu_table((low + high, zeros, zeros), rate_hz=rate_hz))
    filtered = process_imu(
        _imu_table((low + high, zeros, zeros), rate_hz=rate_hz),
        parameters={
            "derivative": {
                "filter": {
                    "family": "butterworth",
                    "order": 4,
                    "cutoff_hz": 15.0,
                    "phase": "zero_phase",
                    "padding": "odd",
                    "padlen": None,
                },
                "edge_policy": "nan",
            }
        },
    )
    # The 60 Hz component sits far above the 15 Hz cutoff, so the filtered RMS
    # approaches the low-frequency-only RMS of 3/sqrt(2).
    assert _metric(filtered, RESULTANT_RMS) == pytest.approx(3.0 / math.sqrt(2.0), rel=0.05)
    assert _metric(filtered, RESULTANT_RMS) < _metric(raw, RESULTANT_RMS) * 0.8
    parameters = filtered.metrics[0].provenance["derivative"]["filter"]
    assert parameters == {
        "family": "butterworth",
        "order": 4,
        "cutoff_hz": 15.0,
        "phase": "zero_phase",
        "padding": "odd",
        "padlen": None,
    }


def test_filter_above_nyquist_is_rejected() -> None:
    with pytest.raises(ValueError, match="Nyquist"):
        process_imu(
            _imu_table((np.zeros(10), np.zeros(10), np.zeros(10))),
            parameters={
                "derivative": {
                    "filter": {
                        "family": "butterworth",
                        "order": 2,
                        "cutoff_hz": 600.0,
                        "phase": "causal",
                        "padding": "none",
                        "padlen": None,
                    },
                    "edge_policy": "nan",
                }
            },
        )


def test_axis_relabelling_is_rejected() -> None:
    with pytest.raises(ValueError, match="anatomical"):
        imu_spec({"anatomical_orientation": "vertical_z"})


def test_non_finite_acceleration_is_rejected() -> None:
    signal = np.zeros(50)
    signal[10] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        process_imu(_imu_table((signal, np.zeros(50), np.zeros(50))))


def test_cross_sensor_pairs_exactly_coincident_samples() -> None:
    force_rate = 1000
    samples = 801
    times = np.arange(samples) / force_rate
    ratio = 1.25 + 0.1 * np.sin(2 * math.pi * 1.5 * times)
    force = _force_table(ratio, rate_hz=force_rate)
    specific_force = STANDARD_GRAVITY_M_S2 * (ratio - 1.0)
    subsample = np.arange(0, samples, 4)
    axes = (specific_force[subsample], np.zeros(subsample.size), np.zeros(subsample.size))
    imu = _imu_table(axes, rate_hz=250)
    result = process_cross_sensor(imu, force)
    assert _metric(result, PAIRED_SAMPLE_COUNT) == float(subsample.size)
    assert _metric(result, PEARSON_R) == pytest.approx(1.0, abs=1e-12)
    provenance = result.metrics[0].provenance
    assert provenance["equivalence_claimed"] is False
    assert provenance["pairing"] == "exact_t_rel_ns_matches_only"


def test_cross_sensor_rejects_mismatched_trials() -> None:
    ratio = np.full(101, 1.1)
    force = _force_table(ratio, trial_id="white-s001-arms-t00")
    imu = _imu_table(
        (np.zeros(26), np.zeros(26), np.zeros(26)),
        rate_hz=250,
        trial_id="white-s001-arms-t01",
    )
    with pytest.raises(ValueError, match="trial_id differs"):
        process_cross_sensor(imu, force)


def test_cross_sensor_refuses_to_manufacture_pairs() -> None:
    ratio = np.full(101, 1.1)
    force = _force_table(ratio)
    imu = _imu_table((np.zeros(26), np.zeros(26), np.zeros(26)), rate_hz=250)
    shifted = imu.set_column(
        imu.schema.get_field_index("t_rel_ns"),
        imu.schema.field("t_rel_ns"),
        pa.array([value + 1 for value in imu.column("t_rel_ns").to_pylist()], type=pa.int64()),
    )
    with pytest.raises(ValueError, match="exactly coincident"):
        process_cross_sensor(shifted, force)
