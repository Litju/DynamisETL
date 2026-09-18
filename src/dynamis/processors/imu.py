"""Deterministic IMU processor: sensor-frame resultant and explicit derivatives.

The source sensor axes have an undocumented anatomical orientation. This
processor therefore never relabels an axis as vertical/AP/ML: the resultant is
named a *sensor-frame* resultant, and every axis keeps its source identity.

Filtering and differentiation are explicit parameters (family, order, cutoff,
phase, padding, derivative edge policy). If no filter is configured, ``none``
means the signal is used untouched; there is no hidden or double filtering.
Documented time-domain features (mean, RMS and peak of the resultant, plus
derived jerk features) are the only outputs.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np
import pyarrow as pa

from dynamis.processors.signals import (
    EDGE_NAN,
    DerivativeSpec,
    derivative_variable,
)
from dynamis.processors.spec import (
    MetricDeclaration,
    ProcessorResult,
    ProcessorSpec,
    ScalarMetric,
    SeriesOutput,
)

ALGORITHM_ID = "imu.sensor_frame_features"
ALGORITHM_VERSION = "1.0.0"

DEFAULT_AXES = ("accel_x_m_s2", "accel_y_m_s2", "accel_z_m_s2")

DEFAULT_PARAMETERS: dict[str, Any] = {
    "axes": list(DEFAULT_AXES),
    "resultant_semantics": "sensor_frame_euclidean_norm_of_proper_acceleration",
    "anatomical_orientation": "undocumented_preserved",
    "derivative": {
        "filter": {
            "family": "none",
            "order": None,
            "cutoff_hz": None,
            "phase": "zero_phase",
            "padding": "odd",
            "padlen": None,
        },
        "edge_policy": EDGE_NAN,
    },
    "jerk_definition": "second_time_derivative_of_resultant_acceleration_after_configured_filter",
}

RESULTANT_MEAN = MetricDeclaration(
    metric_id="imu.resultant_acceleration_mean",
    name="Mean sensor-frame resultant proper acceleration",
    si_unit="m/s**2",
    description="Mean Euclidean norm of the three sensor-frame proper-acceleration axes.",
)
RESULTANT_RMS = MetricDeclaration(
    metric_id="imu.resultant_acceleration_rms",
    name="RMS sensor-frame resultant proper acceleration",
    si_unit="m/s**2",
    description="Root-mean-square Euclidean norm of the sensor-frame acceleration axes.",
)
RESULTANT_PEAK = MetricDeclaration(
    metric_id="imu.resultant_acceleration_peak",
    name="Peak sensor-frame resultant proper acceleration",
    si_unit="m/s**2",
    description="Maximum Euclidean norm of the sensor-frame acceleration axes.",
)
JERK_RMS = MetricDeclaration(
    metric_id="imu.jerk_rms",
    name="RMS of the resultant-acceleration derivative",
    si_unit="m/s**3",
    description=(
        "Root-mean-square of the first time derivative of the sensor-frame resultant "
        "acceleration, computed with the configured derivative specification."
    ),
)
JERK_PEAK = MetricDeclaration(
    metric_id="imu.jerk_peak",
    name="Peak magnitude of the resultant-acceleration derivative",
    si_unit="m/s**3",
    description=(
        "Maximum absolute first time derivative of the sensor-frame resultant "
        "acceleration, computed with the configured derivative specification."
    ),
)

SERIES_NAME = "imu_sensor_frame_derived"


def imu_spec(parameters: Mapping[str, Any] | None = None) -> ProcessorSpec:
    resolved = {**DEFAULT_PARAMETERS, **dict(parameters or {})}
    axes = tuple(str(name) for name in resolved["axes"])
    if len(axes) != 3 or len(set(axes)) != 3:
        raise ValueError("exactly three distinct accelerometer axes are required")
    if resolved["resultant_semantics"] != DEFAULT_PARAMETERS["resultant_semantics"]:
        raise ValueError(
            "resultant_semantics must remain the sensor-frame Euclidean norm; the pipeline "
            "never relabels sensor axes anatomically"
        )
    if resolved["anatomical_orientation"] != "undocumented_preserved":
        raise ValueError("anatomical_orientation must remain 'undocumented_preserved'")
    if resolved["jerk_definition"] != DEFAULT_PARAMETERS["jerk_definition"]:
        raise ValueError("jerk_definition must remain the explicit derivative of the resultant")
    derivative = DerivativeSpec.from_parameters(dict(resolved["derivative"]))
    if derivative.edge_policy not in {EDGE_NAN, "one_sided_first_order"}:
        raise ValueError(f"unsupported derivative edge policy {derivative.edge_policy!r}")
    resolved["axes"] = list(axes)
    return ProcessorSpec(
        algorithm_id=ALGORITHM_ID,
        name="IMU sensor-frame resultant and derivative features",
        version=ALGORITHM_VERSION,
        description=(
            "Deterministic sensor-frame resultant acceleration and explicitly specified "
            "derivative (jerk) features. Source axes are never given anatomical meanings, "
            "and any filter is fully described by family/order/cutoff/phase/padding."
        ),
        parameters=resolved,
    )


def _finite(values: np.ndarray, *, name: str) -> np.ndarray:
    if not np.isfinite(values).all():
        raise ValueError(f"{ALGORITHM_ID}: {name!r} contains non-finite samples")
    return values


def process_imu(
    table: pa.Table,
    *,
    parameters: Mapping[str, Any] | None = None,
) -> ProcessorResult:
    """Compute sensor-frame resultant and derivative features for one IMU stream."""
    spec = imu_spec(parameters)
    axes = tuple(str(name) for name in spec.parameters["axes"])
    derivative_spec = DerivativeSpec.from_parameters(dict(spec.parameters["derivative"]))
    for name in ("t_rel_ns", *axes):
        if name not in table.column_names:
            raise ValueError(f"{ALGORITHM_ID}: required column {name!r} is absent")
    if table.num_rows < 2:
        raise ValueError(f"{ALGORITHM_ID}: at least two samples are required")

    t = np.asarray(table.column("t_rel_ns").to_numpy(zero_copy_only=False), dtype=np.int64)
    rate_hz = _rate_hz(table, t)
    components = [
        _finite(
            np.asarray(table.column(name).to_numpy(zero_copy_only=False), dtype=np.float64),
            name=name,
        )
        for name in axes
    ]
    filtered = [
        derivative_spec.filter.apply(component, rate_hz=rate_hz) for component in components
    ]
    resultant = np.sqrt(sum(component**2 for component in filtered))
    jerk = derivative_variable(resultant, t, edge_policy=derivative_spec.edge_policy)

    scope = _scope(table)
    provenance = {
        "axes": list(axes),
        "resultant_semantics": str(spec.parameters["resultant_semantics"]),
        "anatomical_orientation": str(spec.parameters["anatomical_orientation"]),
        "derivative": derivative_spec.parameters(),
        "samples": int(table.num_rows),
        "rate_hz": float(rate_hz),
        "filter_applied": derivative_spec.filter.family != "none",
    }
    finite_jerk = jerk[np.isfinite(jerk)]
    metrics = [
        ScalarMetric(
            declaration=RESULTANT_MEAN,
            value=float(np.mean(resultant)),
            provenance=provenance,
            **scope,
        ),
        ScalarMetric(
            declaration=RESULTANT_RMS,
            value=float(np.sqrt(np.mean(resultant**2))),
            provenance=provenance,
            **scope,
        ),
        ScalarMetric(
            declaration=RESULTANT_PEAK,
            value=float(np.max(resultant)),
            provenance=provenance,
            **scope,
        ),
    ]
    if finite_jerk.size:
        metrics.extend(
            [
                ScalarMetric(
                    declaration=JERK_RMS,
                    value=float(np.sqrt(np.mean(finite_jerk**2))),
                    provenance=provenance,
                    **scope,
                ),
                ScalarMetric(
                    declaration=JERK_PEAK,
                    value=float(np.max(np.abs(finite_jerk))),
                    provenance=provenance,
                    **scope,
                ),
            ]
        )
    series = pa.table(
        {
            "sample_index": pa.array(
                np.asarray(
                    table.column("sample_index").to_numpy(zero_copy_only=False), dtype=np.int64
                ),
                type=pa.int64(),
            ),
            "t_rel_ns": pa.array(t, type=pa.int64()),
            f"filtered_{axes[0]}": pa.array(filtered[0], type=pa.float64()),
            f"filtered_{axes[1]}": pa.array(filtered[1], type=pa.float64()),
            f"filtered_{axes[2]}": pa.array(filtered[2], type=pa.float64()),
            "resultant_m_s2": pa.array(resultant, type=pa.float64()),
            "resultant_jerk_m_s3": pa.array(jerk, type=pa.float64()),
        }
    )
    return ProcessorResult(
        spec=spec,
        metrics=tuple(metrics),
        series=(
            SeriesOutput(
                name=SERIES_NAME,
                table=series,
                description=(
                    "Per-sample filtered sensor-frame axes, Euclidean resultant and its "
                    "explicit derivative."
                ),
            ),
        ),
        diagnostics={
            "samples": int(table.num_rows),
            "rate_hz": float(rate_hz),
            "axes": list(axes),
            "filter": derivative_spec.filter.parameters(),
            "anatomical_orientation": str(spec.parameters["anatomical_orientation"]),
        },
    )


def _rate_hz(table: pa.Table, t: np.ndarray) -> float:
    if "nominal_sampling_rate_hz" in table.column_names:
        declared = table.column("nominal_sampling_rate_hz")[0].as_py()
        if declared is not None and math.isfinite(float(declared)) and float(declared) > 0:
            return float(declared)
    if t.size >= 2:
        steps = np.diff(t).astype(np.float64) / 1e9
        if np.all(steps > 0):
            return float(1.0 / np.median(steps))
    raise ValueError(f"{ALGORITHM_ID}: no usable sampling rate is declared or derivable")


def _scope(table: pa.Table) -> dict[str, str | None]:
    def single(name: str) -> str | None:
        if name not in table.column_names:
            return None
        value = table.column(name)[0].as_py()
        return None if value is None else str(value)

    return {
        "session_id": single("session_id"),
        "subject_id": single("subject_id"),
        "trial_id": single("trial_id"),
        "stream_id": single("stream_id"),
    }


__all__ = [
    "ALGORITHM_ID",
    "ALGORITHM_VERSION",
    "DEFAULT_AXES",
    "JERK_PEAK",
    "JERK_RMS",
    "RESULTANT_MEAN",
    "RESULTANT_PEAK",
    "RESULTANT_RMS",
    "imu_spec",
    "process_imu",
]
