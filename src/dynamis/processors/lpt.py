"""Generic deterministic LPT processor (synthetic known-answer validation only).

The real GymAware archive is summary-only, so this processor makes **no**
GymAware validation claim and is never run over fabricated dense GymAware data.
It is a generic rep-segmentation/ROM/velocity/velocity-loss implementation whose
truth is established exclusively against synthetic known-answer signals.

Segmentation is an explicit direction-reversal algorithm with declared
parameters: a reversal is accepted only after the position retraces at least
``reversal_m`` from the running extremum; candidate reps shorter than
``min_rep_duration_s`` or with a range below ``min_rep_range_m`` are discarded.
An optional filter is applied to the position series first and is fully
described by family/order/cutoff/phase/padding.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pyarrow as pa

from dynamis.processors.signals import (
    EDGE_ONE_SIDED_FIRST_ORDER,
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

ALGORITHM_ID = "lpt.rep_segmentation_velocity"
ALGORITHM_VERSION = "1.0.0"

VALIDATION_SCOPE = "synthetic_known_answer_only"

DEFAULT_PARAMETERS: dict[str, Any] = {
    "segmentation": "position_direction_reversal_hysteresis",
    "reversal_m": 0.005,
    "min_rep_range_m": 0.05,
    "min_rep_duration_s": 0.3,
    "derivative": {
        "filter": {
            "family": "none",
            "order": None,
            "cutoff_hz": None,
            "phase": "zero_phase",
            "padding": "odd",
            "padlen": None,
        },
        "edge_policy": EDGE_ONE_SIDED_FIRST_ORDER,
    },
    "velocity_loss_definition": "first_to_last_rep_peak_speed_fraction",
    "validation_scope": VALIDATION_SCOPE,
    "gymaware_validation_claimed": False,
}

REP_COUNT = MetricDeclaration(
    metric_id="lpt.rep_count",
    name="Accepted repetition count",
    si_unit="1",
    description="Repetitions surviving the configured range and duration minimums.",
)
REP_ROM_MEAN = MetricDeclaration(
    metric_id="lpt.rep_rom_mean",
    name="Mean repetition range of motion",
    si_unit="m",
    description="Mean position range (max - min) over accepted repetitions.",
)
REP_ROM_MAX = MetricDeclaration(
    metric_id="lpt.rep_rom_max",
    name="Maximum repetition range of motion",
    si_unit="m",
    description="Largest position range over accepted repetitions.",
)
REP_DURATION_MEAN = MetricDeclaration(
    metric_id="lpt.rep_duration_mean",
    name="Mean repetition duration",
    si_unit="s",
    description="Mean duration between consecutive accepted direction reversals.",
)
REP_MEAN_SPEED_MEAN = MetricDeclaration(
    metric_id="lpt.rep_mean_speed_mean",
    name="Mean repetition speed",
    si_unit="m/s",
    description="Mean over repetitions of ROM divided by repetition duration.",
)
REP_PEAK_SPEED_MAX = MetricDeclaration(
    metric_id="lpt.rep_peak_speed_max",
    name="Maximum repetition peak speed",
    si_unit="m/s",
    description="Largest absolute cable speed observed inside an accepted repetition.",
)
VELOCITY_LOSS_FRACTION = MetricDeclaration(
    metric_id="lpt.velocity_loss_fraction",
    name="Repetition velocity loss fraction",
    si_unit="1",
    description=(
        "First-to-last relative drop in repetition peak speed: "
        "(first - last) / first. Emitted only when at least two repetitions exist and the "
        "first peak speed is positive."
    ),
)

SERIES_NAME = "lpt_reps"


def lpt_spec(parameters: Mapping[str, Any] | None = None) -> ProcessorSpec:
    """Resolve and validate the LPT processor parameters."""
    resolved = {**DEFAULT_PARAMETERS, **dict(parameters or {})}
    if resolved["segmentation"] != DEFAULT_PARAMETERS["segmentation"]:
        raise ValueError("unsupported segmentation algorithm")
    if resolved["validation_scope"] != VALIDATION_SCOPE:
        raise ValueError(
            "this processor is validated against synthetic known-answer signals only; "
            "the scope cannot be widened here"
        )
    if resolved["gymaware_validation_claimed"] is not False:
        raise ValueError("no GymAware validation claim may be made")
    if resolved["velocity_loss_definition"] != DEFAULT_PARAMETERS["velocity_loss_definition"]:
        raise ValueError("unsupported velocity_loss_definition")
    for name in ("reversal_m", "min_rep_range_m", "min_rep_duration_s"):
        value = float(resolved[name])
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and non-negative")
    resolved["derivative"] = DerivativeSpec.from_parameters(
        dict(resolved["derivative"])
    ).parameters()
    return ProcessorSpec(
        algorithm_id=ALGORITHM_ID,
        name="LPT rep segmentation and velocity processor",
        version=ALGORITHM_VERSION,
        description=(
            "Deterministic direction-reversal repetition segmentation with explicit "
            "hysteresis, minimum range/duration, ROM, mean/peak speed, duration and "
            "first-to-last velocity loss. Validated on synthetic known-answer signals "
            "only; real GymAware data stays summary-only and no GymAware validation is "
            "claimed."
        ),
        parameters=resolved,
    )


@dataclass(frozen=True, slots=True)
class Rep:
    start_index: int
    end_index: int
    start_time_ns: int
    end_time_ns: int
    start_position_m: float
    end_position_m: float
    rom_m: float
    duration_s: float
    mean_speed_m_s: float
    peak_speed_m_s: float


def _segment(
    position: np.ndarray,
    time_ns: np.ndarray,
    *,
    reversal_m: float,
    min_rep_range_m: float,
    min_rep_duration_s: float,
) -> tuple[Rep, ...]:
    if position.size < 3:
        return ()
    # The first sample seeds the reversal list so a repetition is a complete
    # same-direction extremum-to-extremum excursion (up and down), and the
    # configured range/duration minimums filter a partial leading excursion.
    reversals: list[int] = [0]
    direction = 0
    extreme_index = 0
    extreme_value = float(position[0])
    for index in range(1, position.size):
        value = float(position[index])
        if direction >= 0 and value > extreme_value:
            extreme_value = value
            extreme_index = index
        elif direction <= 0 and value < extreme_value:
            extreme_value = value
            extreme_index = index
        if direction == 0:
            if value > float(position[0]) + reversal_m:
                direction = 1
                extreme_value = value
                extreme_index = index
            elif value < float(position[0]) - reversal_m:
                direction = -1
                extreme_value = value
                extreme_index = index
            continue
        if direction == 1 and value <= extreme_value - reversal_m:
            reversals.append(extreme_index)
            direction = -1
            extreme_value = value
            extreme_index = index
        elif direction == -1 and value >= extreme_value + reversal_m:
            reversals.append(extreme_index)
            direction = 1
            extreme_value = value
            extreme_index = index
    reps: list[Rep] = []
    for start, end in zip(reversals[:-2:2], reversals[2::2], strict=True):
        window = position[start : end + 1]
        rom = float(np.max(window) - np.min(window))
        duration = float(time_ns[end] - time_ns[start]) / 1e9
        if rom < min_rep_range_m or duration < min_rep_duration_s or duration <= 0:
            continue
        mean_speed = rom / duration
        reps.append(
            Rep(
                start_index=start,
                end_index=end,
                start_time_ns=int(time_ns[start]),
                end_time_ns=int(time_ns[end]),
                start_position_m=float(position[start]),
                end_position_m=float(position[end]),
                rom_m=rom,
                duration_s=duration,
                mean_speed_m_s=mean_speed,
                peak_speed_m_s=0.0,
            )
        )
    return tuple(reps)


def process_lpt(
    table: pa.Table,
    *,
    parameters: Mapping[str, Any] | None = None,
) -> ProcessorResult:
    """Segment repetitions and compute ROM/velocity features for one LPT stream."""
    spec = lpt_spec(parameters)
    resolved = spec.parameters
    derivative_spec = DerivativeSpec.from_parameters(dict(resolved["derivative"]))
    for name in ("t_rel_ns", "position_m"):
        if name not in table.column_names:
            raise ValueError(f"{ALGORITHM_ID}: required column {name!r} is absent")
    if table.num_rows < 3:
        raise ValueError(f"{ALGORITHM_ID}: at least three samples are required")
    time_ns = np.asarray(table.column("t_rel_ns").to_numpy(zero_copy_only=False), dtype=np.int64)
    position = np.asarray(
        table.column("position_m").to_numpy(zero_copy_only=False), dtype=np.float64
    )
    if not np.isfinite(position).all():
        raise ValueError(f"{ALGORITHM_ID}: position contains non-finite samples")

    rate_hz = _rate_hz(table, time_ns)
    filtered = derivative_spec.filter.apply(position, rate_hz=rate_hz)
    velocity = derivative_variable(filtered, time_ns, edge_policy=derivative_spec.edge_policy)
    reps = _segment(
        filtered,
        time_ns,
        reversal_m=float(resolved["reversal_m"]),
        min_rep_range_m=float(resolved["min_rep_range_m"]),
        min_rep_duration_s=float(resolved["min_rep_duration_s"]),
    )
    completed: list[Rep] = []
    rep_rows: list[dict[str, Any]] = []
    for rep_index, rep in enumerate(reps):
        window = velocity[rep.start_index : rep.end_index + 1]
        finite = window[np.isfinite(window)]
        peak = float(np.max(np.abs(finite))) if finite.size else 0.0
        completed.append(
            Rep(
                start_index=rep.start_index,
                end_index=rep.end_index,
                start_time_ns=rep.start_time_ns,
                end_time_ns=rep.end_time_ns,
                start_position_m=rep.start_position_m,
                end_position_m=rep.end_position_m,
                rom_m=rep.rom_m,
                duration_s=rep.duration_s,
                mean_speed_m_s=rep.mean_speed_m_s,
                peak_speed_m_s=peak,
            )
        )
        rep_rows.append(
            {
                "rep_index": rep_index,
                "start_sample_index": int(table.column("sample_index")[rep.start_index].as_py()),
                "end_sample_index": int(table.column("sample_index")[rep.end_index].as_py()),
                "start_time_ns": rep.start_time_ns,
                "end_time_ns": rep.end_time_ns,
                "start_position_m": rep.start_position_m,
                "end_position_m": rep.end_position_m,
                "rom_m": rep.rom_m,
                "duration_s": rep.duration_s,
                "mean_speed_m_s": rep.mean_speed_m_s,
                "peak_speed_m_s": peak,
            }
        )

    scope = _scope(table)
    provenance = {
        "validation_scope": VALIDATION_SCOPE,
        "gymaware_validation_claimed": False,
        "real_gymaware_dense_data_used": False,
        "segmentation": str(resolved["segmentation"]),
        "reversal_m": float(resolved["reversal_m"]),
        "min_rep_range_m": float(resolved["min_rep_range_m"]),
        "min_rep_duration_s": float(resolved["min_rep_duration_s"]),
        "derivative": derivative_spec.parameters(),
        "filter_applied": derivative_spec.filter.family != "none",
        "samples": int(table.num_rows),
        "rate_hz": float(rate_hz),
    }
    metrics: list[ScalarMetric] = [
        ScalarMetric(
            declaration=REP_COUNT,
            value=float(len(completed)),
            provenance=provenance,
            **scope,
        )
    ]
    if completed:
        metrics.extend(
            [
                ScalarMetric(
                    declaration=REP_ROM_MEAN,
                    value=float(np.mean([rep.rom_m for rep in completed])),
                    provenance=provenance,
                    **scope,
                ),
                ScalarMetric(
                    declaration=REP_ROM_MAX,
                    value=float(np.max([rep.rom_m for rep in completed])),
                    provenance=provenance,
                    **scope,
                ),
                ScalarMetric(
                    declaration=REP_DURATION_MEAN,
                    value=float(np.mean([rep.duration_s for rep in completed])),
                    provenance=provenance,
                    **scope,
                ),
                ScalarMetric(
                    declaration=REP_MEAN_SPEED_MEAN,
                    value=float(np.mean([rep.mean_speed_m_s for rep in completed])),
                    provenance=provenance,
                    **scope,
                ),
                ScalarMetric(
                    declaration=REP_PEAK_SPEED_MAX,
                    value=float(np.max([rep.peak_speed_m_s for rep in completed])),
                    provenance=provenance,
                    **scope,
                ),
            ]
        )
        if len(completed) >= 2 and completed[0].peak_speed_m_s > 0:
            first = completed[0].peak_speed_m_s
            last = completed[-1].peak_speed_m_s
            metrics.append(
                ScalarMetric(
                    declaration=VELOCITY_LOSS_FRACTION,
                    value=float((first - last) / first),
                    provenance=provenance,
                    **scope,
                )
            )
    series = (
        pa.Table.from_pylist(
            rep_rows,
            schema=pa.schema(
                [
                    pa.field("rep_index", pa.int64()),
                    pa.field("start_sample_index", pa.int64()),
                    pa.field("end_sample_index", pa.int64()),
                    pa.field("start_time_ns", pa.int64()),
                    pa.field("end_time_ns", pa.int64()),
                    pa.field("start_position_m", pa.float64()),
                    pa.field("end_position_m", pa.float64()),
                    pa.field("rom_m", pa.float64()),
                    pa.field("duration_s", pa.float64()),
                    pa.field("mean_speed_m_s", pa.float64()),
                    pa.field("peak_speed_m_s", pa.float64()),
                ]
            ),
        )
        if rep_rows
        else None
    )
    outputs: list[SeriesOutput] = []
    if series is not None:
        outputs.append(
            SeriesOutput(
                name=SERIES_NAME,
                table=series,
                description="Per-repetition ROM, duration and velocity features.",
            )
        )
    return ProcessorResult(
        spec=spec,
        metrics=tuple(metrics),
        series=tuple(outputs),
        diagnostics={
            "reps": len(completed),
            "samples": int(table.num_rows),
            "validation_scope": VALIDATION_SCOPE,
            "gymaware_validation_claimed": False,
        },
    )


def _rate_hz(table: pa.Table, time_ns: np.ndarray) -> float:
    if "nominal_sampling_rate_hz" in table.column_names:
        declared = table.column("nominal_sampling_rate_hz")[0].as_py()
        if declared is not None and math.isfinite(float(declared)) and float(declared) > 0:
            return float(declared)
    if time_ns.size >= 2:
        steps = np.diff(time_ns).astype(np.float64) / 1e9
        if np.all(steps > 0):
            return float(1.0 / np.median(steps))
    return 0.0


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
    "REP_COUNT",
    "REP_DURATION_MEAN",
    "REP_MEAN_SPEED_MEAN",
    "REP_PEAK_SPEED_MAX",
    "REP_ROM_MAX",
    "REP_ROM_MEAN",
    "VALIDATION_SCOPE",
    "VELOCITY_LOSS_FRACTION",
    "lpt_spec",
    "process_lpt",
]
