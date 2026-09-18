"""Synchronized force/IMU association diagnostic for one persisted sync pair.

This is deliberately a *descriptive association*, not an equivalence or
validation claim: the two devices measure different physical quantities at
different locations, and vendor equivalence is never asserted.

Pairing rules:

* only samples whose ``t_rel_ns`` exists exactly in both streams are paired; no
  interpolation or resampling is performed;
* both streams must belong to the same dataset/session/trial/stream pair as
  declared by the caller, and the caller is responsible for selecting only
  persisted ``SyncAlignment`` pairs;
* force is read as the dimensionless body-weight ratio and converted to
  specific force ``g * (r - 1)`` with an explicit gravity parameter, because no
  body mass exists in the release.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np
import pyarrow as pa

from dynamis.processors.signals import STANDARD_GRAVITY_M_S2
from dynamis.processors.spec import (
    MetricDeclaration,
    ProcessorResult,
    ProcessorSpec,
    ScalarMetric,
)

ALGORITHM_ID = "cross_sensor.resultant_force_association"
ALGORITHM_VERSION = "1.0.0"

SENSOR_FRAME_DISCLAIMER = (
    "The Delsys Trigno sensor axes have undocumented anatomical orientation; the "
    "resultant is a sensor-frame quantity and no axis is labelled anatomically."
)
EQUIVALENCE_DISCLAIMER = (
    "Force and accelerometry are different measurement modalities at different "
    "locations; a correlation is a descriptive association and never an equivalence, "
    "calibration or validation claim."
)

DEFAULT_PARAMETERS: dict[str, Any] = {
    "pairing": "exact_t_rel_ns_matches_only",
    "interpolation": "none",
    "resampling": "none",
    "force_representation": "force_z_body_weight_ratio",
    "specific_force_convention": "gravity_times_(ratio_minus_one)",
    "gravity_m_s2": STANDARD_GRAVITY_M_S2,
    "statistic": "pearson_product_moment",
    "sensor_frame_disclaimer": SENSOR_FRAME_DISCLAIMER,
    "equivalence_disclaimer": EQUIVALENCE_DISCLAIMER,
}

PAIRED_SAMPLE_COUNT = MetricDeclaration(
    metric_id="cross_sensor.paired_sample_count",
    name="Exactly coincident force/IMU sample pairs",
    si_unit="1",
    description=(
        "Number of samples whose takeoff-relative timestamp exists exactly in both "
        "streams; no interpolation is used to increase it."
    ),
)
PEARSON_R = MetricDeclaration(
    metric_id="cross_sensor.resultant_force_pearson_r",
    name="Association between sensor-frame resultant and specific force",
    si_unit="1",
    description=(
        "Pearson product-moment correlation over exactly coincident samples between the "
        "sensor-frame resultant proper acceleration and g*(r-1). Descriptive only: it is "
        "not agreement, equivalence or device validation."
    ),
)


def cross_sensor_spec(parameters: Mapping[str, Any] | None = None) -> ProcessorSpec:
    resolved = {**DEFAULT_PARAMETERS, **dict(parameters or {})}
    for name in ("pairing", "interpolation", "resampling", "statistic"):
        if resolved[name] != DEFAULT_PARAMETERS[name]:
            raise ValueError(
                f"cross-sensor parameter {name!r}={resolved[name]!r} is not the supported "
                f"convention {DEFAULT_PARAMETERS[name]!r}"
            )
    gravity = float(resolved["gravity_m_s2"])
    if not math.isfinite(gravity) or gravity <= 0:
        raise ValueError("gravity_m_s2 must be finite and positive")
    return ProcessorSpec(
        algorithm_id=ALGORITHM_ID,
        name="Force/IMU synchronized association diagnostic",
        version=ALGORITHM_VERSION,
        description=(
            "Descriptive association between the sensor-frame resultant proper "
            "acceleration and specific force over exactly coincident takeoff-relative "
            "samples of one persisted White CMJ sync pair. No interpolation, no "
            "equivalence claim."
        ),
        parameters=resolved,
    )


def _identity(table: pa.Table) -> tuple[str | None, ...]:
    values = []
    for name in ("dataset_id", "session_id", "trial_id", "subject_id", "stream_id"):
        value = table.column(name)[0].as_py() if name in table.column_names else None
        values.append(None if value is None else str(value))
    return tuple(values)


def process_cross_sensor(
    imu_table: pa.Table,
    force_table: pa.Table,
    *,
    parameters: Mapping[str, Any] | None = None,
) -> ProcessorResult:
    """Compute the explicit pairing diagnostic for one force/IMU sync pair."""
    spec = cross_sensor_spec(parameters)
    gravity = float(spec.parameters["gravity_m_s2"])
    ratio_field = str(spec.parameters["force_representation"])
    for name in ("t_rel_ns", "accel_x_m_s2", "accel_y_m_s2", "accel_z_m_s2"):
        if name not in imu_table.column_names:
            raise ValueError(f"{ALGORITHM_ID}: IMU column {name!r} is absent")
    if ratio_field not in force_table.column_names:
        raise ValueError(f"{ALGORITHM_ID}: force column {ratio_field!r} is absent")
    imu_identity = _identity(imu_table)
    force_identity = _identity(force_table)
    for index, label in enumerate(("dataset_id", "session_id", "trial_id", "subject_id")):
        if imu_identity[index] != force_identity[index]:
            raise ValueError(
                f"{ALGORITHM_ID}: {label} differs between the paired streams "
                f"({imu_identity[index]!r} vs {force_identity[index]!r})"
            )
    if imu_table.num_rows < 2 or force_table.num_rows < 2:
        raise ValueError(f"{ALGORITHM_ID}: both streams need at least two samples")

    force_times = np.asarray(
        force_table.column("t_rel_ns").to_numpy(zero_copy_only=False), dtype=np.int64
    )
    force_lookup = {int(value): index for index, value in enumerate(force_times)}
    imu_times = np.asarray(
        imu_table.column("t_rel_ns").to_numpy(zero_copy_only=False), dtype=np.int64
    )
    imu_indices: list[int] = []
    force_indices: list[int] = []
    for index, value in enumerate(imu_times):
        match = force_lookup.get(int(value))
        if match is not None:
            imu_indices.append(index)
            force_indices.append(match)
    if len(imu_indices) < 2:
        raise ValueError(
            f"{ALGORITHM_ID}: fewer than two exactly coincident samples; no interpolation is "
            "used to manufacture pairs"
        )
    imu_index = np.asarray(imu_indices, dtype=np.int64)
    force_index = np.asarray(force_indices, dtype=np.int64)
    axes = [
        np.asarray(imu_table.column(name).to_numpy(zero_copy_only=False), dtype=np.float64)[
            imu_index
        ]
        for name in ("accel_x_m_s2", "accel_y_m_s2", "accel_z_m_s2")
    ]
    if any(not np.isfinite(axis).all() for axis in axes):
        raise ValueError(f"{ALGORITHM_ID}: the IMU pair contains non-finite acceleration")
    ratio = np.asarray(
        force_table.column(ratio_field).to_numpy(zero_copy_only=False), dtype=np.float64
    )[force_index]
    if not np.isfinite(ratio).all():
        raise ValueError(f"{ALGORITHM_ID}: the force pair contains a non-finite ratio")
    resultant = np.sqrt(sum(axis**2 for axis in axes))
    specific_force = gravity * (ratio - 1.0)
    var_a = float(np.var(resultant))
    var_b = float(np.var(specific_force))
    pearson: float | None = None
    if var_a > 0 and var_b > 0:
        pearson = float(
            np.mean((resultant - resultant.mean()) * (specific_force - specific_force.mean()))
            / math.sqrt(var_a * var_b)
        )
    scope = {
        "session_id": imu_identity[1],
        "subject_id": imu_identity[3],
        "trial_id": imu_identity[2],
        "stream_id": imu_identity[4],
    }
    provenance = {
        "imu_stream_id": imu_identity[4],
        "force_stream_id": force_identity[4],
        "pairing": str(spec.parameters["pairing"]),
        "statistic": str(spec.parameters["statistic"]),
        "imu_samples": int(imu_table.num_rows),
        "force_samples": int(force_table.num_rows),
        "paired_samples": int(imu_index.size),
        "imu_variance": var_a,
        "force_variance": var_b,
        "sensor_frame_disclaimer": SENSOR_FRAME_DISCLAIMER,
        "equivalence_disclaimer": EQUIVALENCE_DISCLAIMER,
        "equivalence_claimed": False,
    }
    metrics = [
        ScalarMetric(
            declaration=PAIRED_SAMPLE_COUNT,
            value=float(imu_index.size),
            provenance=provenance,
            **scope,
        )
    ]
    if pearson is not None:
        metrics.append(
            ScalarMetric(
                declaration=PEARSON_R,
                value=pearson,
                provenance=provenance,
                **scope,
            )
        )
    return ProcessorResult(
        spec=spec,
        metrics=tuple(metrics),
        diagnostics={
            "paired_samples": int(imu_index.size),
            "pearson_r": pearson,
            "equivalence_claimed": False,
        },
    )


__all__ = [
    "ALGORITHM_ID",
    "ALGORITHM_VERSION",
    "EQUIVALENCE_DISCLAIMER",
    "PAIRED_SAMPLE_COUNT",
    "PEARSON_R",
    "SENSOR_FRAME_DISCLAIMER",
    "cross_sensor_spec",
    "process_cross_sensor",
]
