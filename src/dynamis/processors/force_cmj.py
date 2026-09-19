"""Deterministic countermovement-jump force processor (body-weight-ratio record).

The White CMJ release distributes a full per-trial pre-takeoff vertical ground
reaction force at 1000 Hz, already normalised by body weight: ``r = Fz / BW``,
dimensionless, ending exactly at the provider-annotated takeoff instant. The
provider's own preparation code defines the mechanics reproduced here:

* specific centre-of-mass acceleration ``a = g * (r - 1)``;
* velocity by trapezoidal integration of ``a``;
* displacement by trapezoidal integration of velocity;
* specific power ``P/m = g * r * v``;
* provider jump-height convention ``JHwd = v_takeoff^2 / (2 g) + s_takeoff``;
* peak power = maximum specific power over the record.

Nothing is re-detected. The distributed record is already trimmed from movement
onset to takeoff, so the processor never runs an onset detector and takes the
record boundary as the onset. No body mass is fabricated and no newton force is
fabricated: the input is dimensionless and every output is specific (per mass).
No flight-time metric is produced because the record ends at takeoff.

Pipeline metric identities are deliberately distinct from the provider's
``source_jump_height`` / ``source_peak_power_relative`` values; those remain
SOURCE_DERIVED reference metrics and are only used in a clearly labelled
comparison, never stored as pipeline output.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pyarrow as pa

from dynamis.processors.signals import (
    STANDARD_GRAVITY_M_S2,
    cumulative_trapezoid,
    trapezoid_integral,
    uniform_step_s,
)
from dynamis.processors.spec import (
    MetricDeclaration,
    ProcessorResult,
    ProcessorSpec,
    ScalarMetric,
    SeriesOutput,
)

ALGORITHM_ID = "force.cmj_body_weight_ratio_full_record"
ALGORITHM_VERSION = "1.0.0"
RATIO_FIELD = "force_z_body_weight_ratio"
TIME_FIELD = "t_rel_ns"

SUPPORTED_INTEGRATION = "trapezoid"
SUPPORTED_ONSET_POLICY = "none_source_trimmed_record"
SUPPORTED_TIMEBASE = "takeoff_relative_uniform_ns"
SUPPORTED_JUMP_HEIGHT = "v_takeoff_squared_over_2g_plus_displacement_to_takeoff"
SUPPORTED_POWER = "gravity_times_body_weight_ratio_times_velocity"
SUPPORTED_PEAK_POWER = "max_specific_power"

DEFAULT_PARAMETERS: dict[str, Any] = {
    "integration": SUPPORTED_INTEGRATION,
    "timebase": SUPPORTED_TIMEBASE,
    "movement_onset_detection": SUPPORTED_ONSET_POLICY,
    "jump_height_convention": SUPPORTED_JUMP_HEIGHT,
    "power_convention": SUPPORTED_POWER,
    "peak_power_definition": SUPPORTED_PEAK_POWER,
    "gravity_m_s2": STANDARD_GRAVITY_M_S2,
    "ratio_field": RATIO_FIELD,
    "record_trim": "source_pre_takeoff_full_record_ends_at_takeoff",
    "body_mass_required": False,
    "newton_force_produced": False,
    "flight_time_produced": False,
}

NET_IMPULSE_PER_MASS = MetricDeclaration(
    metric_id="cmj.net_impulse_per_mass",
    name="Countermovement jump net vertical impulse per body mass",
    si_unit="m/s",
    description=(
        "Integral of g*(r-1) dt over the distributed record, where r is the vertical "
        "ground reaction force divided by body weight. Expressed per unit mass because "
        "the source supplies no body mass; numerically equal to takeoff velocity for a "
        "rest-to-takeoff record and reported under its own identity."
    ),
)
TAKEOFF_VELOCITY = MetricDeclaration(
    metric_id="cmj.takeoff_velocity",
    name="Vertical centre-of-mass velocity at takeoff",
    si_unit="m/s",
    description="Trapezoidal integral of g*(r-1) over the distributed pre-takeoff record.",
)
COM_DISPLACEMENT = MetricDeclaration(
    metric_id="cmj.com_displacement_to_takeoff",
    name="Centre-of-mass displacement from record start to takeoff",
    si_unit="m",
    description=(
        "Trapezoidal integral of COM velocity over the distributed record. Signed: a "
        "countermovement dip is negative and the standing displacement is positive."
    ),
)
TAKEOFF_TO_APEX = MetricDeclaration(
    metric_id="cmj.takeoff_to_apex_height",
    name="Takeoff-to-apex rise (ballistic)",
    si_unit="m",
    description="v_takeoff^2 / (2g): the ballistic rise from the takeoff instant to apex.",
)
JUMP_HEIGHT_JHWD = MetricDeclaration(
    metric_id="cmj.jump_height_jhwd",
    name="Jump height, onset-to-apex (source JHwd convention)",
    si_unit="m",
    description=(
        "Provider companion convention v_takeoff^2/(2g) + s_takeoff: ballistic rise from "
        "takeoff plus the COM displacement accumulated from record start to takeoff."
    ),
)
PEAK_SPECIFIC_POWER = MetricDeclaration(
    metric_id="cmj.peak_specific_power",
    name="Peak specific power",
    si_unit="W/kg",
    description="Maximum of g * r * v over the distributed record (per unit body mass).",
)
PEAK_BODY_WEIGHT_RATIO = MetricDeclaration(
    metric_id="cmj.peak_body_weight_ratio",
    name="Peak vertical ground reaction force per body weight",
    si_unit="1",
    description="Maximum dimensionless r = Fz/BW observed in the distributed record.",
)

SERIES_NAME = "cmj_force_derived"


def force_cmj_spec(parameters: Mapping[str, Any] | None = None) -> ProcessorSpec:
    """Resolve the full explicit parameter set and its versioned identity."""
    resolved = {**DEFAULT_PARAMETERS, **dict(parameters or {})}
    checks = {
        "integration": SUPPORTED_INTEGRATION,
        "timebase": SUPPORTED_TIMEBASE,
        "movement_onset_detection": SUPPORTED_ONSET_POLICY,
        "jump_height_convention": SUPPORTED_JUMP_HEIGHT,
        "power_convention": SUPPORTED_POWER,
        "peak_power_definition": SUPPORTED_PEAK_POWER,
    }
    for name, expected in checks.items():
        if resolved.get(name) != expected:
            raise ValueError(
                f"{ALGORITHM_ID}: parameter {name!r}={resolved.get(name)!r} is not the "
                f"supported convention {expected!r}"
            )
    gravity = float(resolved["gravity_m_s2"])
    if not np.isfinite(gravity) or gravity <= 0:
        raise ValueError("gravity_m_s2 must be finite and positive")
    if not str(resolved.get("ratio_field", "")).strip():
        raise ValueError("ratio_field must be an explicit non-empty column name")
    return ProcessorSpec(
        algorithm_id=ALGORITHM_ID,
        name="CMJ full-record body-weight-ratio force processor",
        version=ALGORITHM_VERSION,
        description=(
            "Deterministic pre-takeoff CMJ mechanics over the distributed 1000 Hz "
            "body-weight-normalised vertical force record: a=g*(r-1), trapezoidal "
            "velocity/displacement integration, specific power g*r*v, provider JHwd "
            "jump-height convention. No onset re-detection, no body-mass fabrication, "
            "no newton force, no flight time."
        ),
        parameters=resolved,
        citation="White (2026) Zenodo 10.5281/zenodo.19136480; companion acc2grf-cmj",
    )


def _identity(table: pa.Table) -> dict[str, str | None]:
    """First-row identity scope of a single-entity canonical stream."""

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


def process_force_cmj(
    table: pa.Table,
    *,
    parameters: Mapping[str, Any] | None = None,
) -> ProcessorResult:
    """Compute the full-record CMJ metrics and dense derived series for one trial."""
    spec = force_cmj_spec(parameters)
    ratio_field = str(spec.parameters["ratio_field"])
    gravity = float(spec.parameters["gravity_m_s2"])
    for required in (TIME_FIELD, ratio_field):
        if required not in table.column_names:
            raise ValueError(f"{ALGORITHM_ID}: required canonical column {required!r} is absent")
    if table.num_rows < 2:
        raise ValueError(
            f"{ALGORITHM_ID}: a record requires at least two samples, found {table.num_rows}"
        )
    times = np.asarray(table.column(TIME_FIELD).to_numpy(zero_copy_only=False), dtype=np.int64)
    ratio = np.asarray(table.column(ratio_field).to_numpy(zero_copy_only=False), dtype=np.float64)
    if not np.isfinite(ratio).all():
        raise ValueError(f"{ALGORITHM_ID}: {ratio_field!r} contains non-finite values")

    step_s = uniform_step_s(times)
    acceleration = gravity * (ratio - 1.0)
    velocity = cumulative_trapezoid(acceleration, step_s)
    displacement = cumulative_trapezoid(velocity, step_s)
    power = gravity * ratio * velocity

    takeoff_velocity = float(velocity[-1])
    displacement_to_takeoff = float(displacement[-1])
    net_impulse_per_mass = trapezoid_integral(acceleration, step_s)
    takeoff_to_apex = takeoff_velocity**2 / (2.0 * gravity)
    jump_height_jhwd = takeoff_to_apex + displacement_to_takeoff
    peak_power = float(np.max(power))
    peak_ratio = float(np.max(ratio))

    scope = _identity(table)
    provenance = {
        "sample_count": int(table.num_rows),
        "step_s": float(step_s),
        "record_duration_s": float((table.num_rows - 1) * step_s),
        "t_rel_min_ns": int(times[0]),
        "t_rel_max_ns": int(times[-1]),
        "record_ends_at_takeoff": True,
        "onset_detector_ran": False,
        "body_mass_fabricated": False,
        "newton_force_produced": False,
        "flight_time_produced": False,
        "source_jump_height_is_reference_only": True,
    }
    metrics = (
        ScalarMetric(
            declaration=NET_IMPULSE_PER_MASS,
            value=net_impulse_per_mass,
            provenance={
                **provenance,
                "equals_takeoff_velocity": bool(
                    abs(net_impulse_per_mass - takeoff_velocity)
                    <= 1e-12 * max(1.0, abs(takeoff_velocity))
                ),
            },
            **scope,
        ),
        ScalarMetric(
            declaration=TAKEOFF_VELOCITY,
            value=takeoff_velocity,
            provenance=provenance,
            **scope,
        ),
        ScalarMetric(
            declaration=COM_DISPLACEMENT,
            value=displacement_to_takeoff,
            provenance=provenance,
            **scope,
        ),
        ScalarMetric(
            declaration=TAKEOFF_TO_APEX,
            value=takeoff_to_apex,
            provenance=provenance,
            **scope,
        ),
        ScalarMetric(
            declaration=JUMP_HEIGHT_JHWD,
            value=jump_height_jhwd,
            provenance={
                **provenance,
                "convention": SUPPORTED_JUMP_HEIGHT,
            },
            **scope,
        ),
        ScalarMetric(
            declaration=PEAK_SPECIFIC_POWER,
            value=peak_power,
            provenance=provenance,
            **scope,
        ),
        ScalarMetric(
            declaration=PEAK_BODY_WEIGHT_RATIO,
            value=peak_ratio,
            provenance=provenance,
            **scope,
        ),
    )
    series = pa.table(
        {
            "sample_index": pa.array(
                np.asarray(
                    table.column("sample_index").to_numpy(zero_copy_only=False), dtype=np.int64
                ),
                type=pa.int64(),
            ),
            TIME_FIELD: pa.array(times, type=pa.int64()),
            ratio_field: pa.array(ratio, type=pa.float64()),
            "acceleration_m_s2": pa.array(acceleration, type=pa.float64()),
            "velocity_m_s": pa.array(velocity, type=pa.float64()),
            "displacement_m": pa.array(displacement, type=pa.float64()),
            "power_w_kg": pa.array(power, type=pa.float64()),
        }
    )
    return ProcessorResult(
        spec=spec,
        metrics=metrics,
        series=(
            SeriesOutput(
                name=SERIES_NAME,
                table=series,
                description=(
                    "Per-sample derived CMJ mechanics: specific acceleration, velocity, "
                    "displacement and specific power over the distributed record."
                ),
            ),
        ),
        diagnostics={
            "sample_count": int(table.num_rows),
            "step_s": float(step_s),
            "rate_hz": float(1.0 / step_s),
            "t_rel_min_ns": int(times[0]),
            "t_rel_max_ns": int(times[-1]),
            "record_duration_s": float((table.num_rows - 1) * step_s),
        },
    )


def process_force_cmj_path(
    path: Any, *, parameters: Mapping[str, Any] | None = None
) -> ProcessorResult:
    """Convenience wrapper reading one canonical Parquet stream."""
    from dynamis.storage.parquet import read_parquet_table

    return process_force_cmj(read_parquet_table(path), parameters=parameters)


__all__ = [
    "ALGORITHM_ID",
    "ALGORITHM_VERSION",
    "COM_DISPLACEMENT",
    "JUMP_HEIGHT_JHWD",
    "NET_IMPULSE_PER_MASS",
    "PEAK_BODY_WEIGHT_RATIO",
    "PEAK_SPECIFIC_POWER",
    "TAKEOFF_TO_APEX",
    "TAKEOFF_VELOCITY",
    "force_cmj_spec",
    "process_force_cmj",
    "process_force_cmj_path",
]
