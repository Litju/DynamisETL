"""Frame- and landmark-level Pose coverage quality processor.

Provider p90 error-radius values remain provider evidence. This processor emits
separate pipeline coverage/dropout evidence over a cadence-derived expected
frame grid; missing rows and unavailable landmarks remain explicit gaps.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pyarrow as pa

from dynamis.processors.signals import DerivativeSpec
from dynamis.processors.spec import (
    MetricDeclaration,
    ProcessorResult,
    ProcessorSpec,
    ScalarMetric,
    SeriesOutput,
)

ALGORITHM_ID = "pose.analysis_quality"
ALGORITHM_VERSION = "1.0.0"
DEFAULT_MINIMUM_DERIVATIVE_SEGMENT_FRAMES = 3
SERIES_NAME = "pose_analysis_quality"
_TOKEN = re.compile(r"[^A-Za-z0-9]+")

DEFAULT_PARAMETERS: dict[str, Any] = {
    "expected_joint_names": [],
    "metric_requirements": {},
    "minimum_derivative_segment_frames": DEFAULT_MINIMUM_DERIVATIVE_SEGMENT_FRAMES,
    "derivative": {
        "filter": {
            "family": "none",
            "order": None,
            "cutoff_hz": None,
            "phase": "zero_phase",
            "padding": "odd",
            "padlen": None,
        },
        "edge_policy": "nan",
    },
    "frame_grid": "nominal_sampling_rate_hz_or_median_observed_step",
    "availability_rule": "is_available_and_finite_xyz",
    "error_radius_quantile_method": "linear",
}


def _token(value: str) -> str:
    token = _TOKEN.sub("_", value.strip()).strip("_")
    if not token:
        raise ValueError(f"cannot derive a metric token from {value!r}")
    return token


def _finite_float_column(table: pa.Table, name: str) -> np.ndarray:
    if name not in table.column_names:
        raise ValueError(f"{ALGORITHM_ID}: required column {name!r} is absent")
    values = table.column(name).combine_chunks().to_numpy(zero_copy_only=False)
    return np.asarray(values, dtype=np.float64)


def _encoded_strings(table: pa.Table, name: str) -> tuple[np.ndarray, tuple[str, ...]]:
    """Dictionary-encode repeated identities without per-row Python strings."""
    encoded = table.column(name).combine_chunks().dictionary_encode()
    if encoded.indices.null_count:
        raise ValueError(f"{ALGORITHM_ID}: {name} cannot contain null values")
    codes = np.asarray(encoded.indices.to_numpy(zero_copy_only=False), dtype=np.int32)
    dictionary = tuple(str(value) for value in encoded.dictionary.to_pylist())
    return codes, dictionary


def _rate_hz(
    subject_rows: np.ndarray,
    times_ns: np.ndarray,
    declared_rates: Sequence[float | None] | None,
) -> float:
    if declared_rates is not None:
        resolved_rates: set[float] = set()
        for declared_rate in declared_rates:
            if declared_rate is None:
                continue
            rate = float(declared_rate)
            if math.isfinite(rate) and rate > 0:
                resolved_rates.add(rate)
        rates = sorted(resolved_rates)
        if len(rates) > 1 and not np.allclose(rates, rates[0], rtol=0.0, atol=1e-9):
            raise ValueError(f"{ALGORITHM_ID}: one stream cannot have multiple sampling rates")
        if rates:
            return rates[0]
    unique_times = np.unique(times_ns[subject_rows])
    if unique_times.size < 2:
        raise ValueError(
            f"{ALGORITHM_ID}: a singleton Pose stream requires nominal_sampling_rate_hz"
        )
    steps = np.diff(unique_times).astype(np.float64)
    positive_steps = steps[steps > 0]
    if positive_steps.size == 0:
        raise ValueError(f"{ALGORITHM_ID}: Pose timestamps must increase")
    return 1e9 / float(np.median(positive_steps))


def _runs(mask: np.ndarray) -> tuple[tuple[int, int], ...]:
    """Return half-open runs of True values from a one-dimensional mask."""
    if mask.size == 0:
        return ()
    padded = np.concatenate(([False], mask, [False])).astype(np.int8)
    changes = np.diff(padded)
    starts = np.flatnonzero(changes == 1)
    stops = np.flatnonzero(changes == -1)
    return tuple((int(start), int(stop)) for start, stop in zip(starts, stops, strict=True))


def _declaration(metric_id: str, name: str, unit: str, description: str) -> MetricDeclaration:
    return MetricDeclaration(
        metric_id=metric_id,
        name=name,
        si_unit=unit,
        description=description,
    )


def pose_quality_spec(parameters: Mapping[str, Any] | None = None) -> ProcessorSpec:
    resolved = {**DEFAULT_PARAMETERS, **dict(parameters or {})}
    raw_names = resolved["expected_joint_names"]
    if not isinstance(raw_names, (list, tuple)):
        raise ValueError("expected_joint_names must be an array of landmark names")
    joint_names = tuple(str(name) for name in raw_names)
    if len(set(joint_names)) != len(joint_names) or any(not name for name in joint_names):
        raise ValueError("expected_joint_names must contain unique non-empty names")
    raw_requirements = resolved["metric_requirements"]
    if not isinstance(raw_requirements, Mapping):
        raise ValueError("metric_requirements must map metric names to landmark arrays")
    requirements: dict[str, list[str]] = {}
    for name, required in raw_requirements.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(required, (list, tuple)):
            raise ValueError("each metric requirement needs a name and landmark array")
        names = [str(item) for item in required]
        if not names or any(not item for item in names) or len(set(names)) != len(names):
            raise ValueError(f"metric requirement {name!r} needs unique landmark names")
        if joint_names and not set(names).issubset(joint_names):
            raise ValueError(f"metric requirement {name!r} references an unknown landmark")
        requirements[name] = names
    min_segment = int(resolved["minimum_derivative_segment_frames"])
    if min_segment < 2:
        raise ValueError("minimum_derivative_segment_frames must be at least 2")
    if resolved["frame_grid"] != DEFAULT_PARAMETERS["frame_grid"]:
        raise ValueError("frame_grid is a locked cadence-derived expected frame grid")
    if resolved["availability_rule"] != DEFAULT_PARAMETERS["availability_rule"]:
        raise ValueError("availability_rule is locked to finite available XYZ observations")
    if resolved["error_radius_quantile_method"] != "linear":
        raise ValueError("error_radius_quantile_method is locked to linear quantiles")
    derivative = dict(resolved["derivative"])
    DerivativeSpec.from_parameters(derivative)
    resolved["expected_joint_names"] = list(joint_names)
    resolved["metric_requirements"] = requirements
    resolved["minimum_derivative_segment_frames"] = min_segment
    resolved["derivative"] = derivative
    return ProcessorSpec(
        algorithm_id=ALGORITHM_ID,
        name="Pose coverage and analysis quality",
        version=ALGORITHM_VERSION,
        description=(
            "Computes cadence-grid landmark availability, Pose coverage, dropout, "
            "provider p90 error-radius distributions, and metric/derivative eligibility. "
            "Source error-radius evidence remains distinct from pipeline quality."
        ),
        parameters=resolved,
    )


def process_pose_quality(
    table: pa.Table,
    *,
    parameters: Mapping[str, Any] | None = None,
) -> ProcessorResult:
    """Summarize Pose quality without filling missing frames or landmarks."""
    spec = pose_quality_spec(parameters)
    for name in (
        "subject_id",
        "t_rel_ns",
        "joint_name",
        "is_available",
        "x_m",
        "y_m",
        "z_m",
        "error_m",
    ):
        if name not in table.column_names:
            raise ValueError(f"{ALGORITHM_ID}: required column {name!r} is absent")
    if table.num_rows == 0:
        raise ValueError(f"{ALGORITHM_ID}: empty Pose input has no quality denominator")

    subject_codes, subjects = _encoded_strings(table, "subject_id")
    joint_codes, joint_dictionary = _encoded_strings(table, "joint_name")
    available_values = np.asarray(
        table.column("is_available").combine_chunks().to_numpy(zero_copy_only=False),
        dtype=np.bool_,
    )
    times_ns = np.asarray(table.column("t_rel_ns").to_numpy(zero_copy_only=False), dtype=np.int64)
    x_values = _finite_float_column(table, "x_m")
    y_values = _finite_float_column(table, "y_m")
    z_values = _finite_float_column(table, "z_m")
    error_values = _finite_float_column(table, "error_m")
    declared_rates = (
        table.column("nominal_sampling_rate_hz").unique().to_pylist()
        if "nominal_sampling_rate_hz" in table.column_names
        else None
    )
    requirements = spec.parameters["metric_requirements"]
    configured_names = tuple(spec.parameters["expected_joint_names"])
    names = configured_names or tuple(sorted(joint_dictionary))
    if not names:
        raise ValueError(f"{ALGORITHM_ID}: no expected landmarks are available")
    joint_index = {name: index for index, name in enumerate(names)}
    joint_code_to_index = np.asarray(
        [joint_index.get(name, -1) for name in joint_dictionary],
        dtype=np.int32,
    )
    resolved_joint_indexes = joint_code_to_index[joint_codes]
    requirement_indexes = {
        metric: tuple(joint_index[name] for name in landmark_names)
        for metric, landmark_names in requirements.items()
        if all(name in joint_index for name in landmark_names)
    }
    unknown_requirements = set(requirements) - set(requirement_indexes)
    if unknown_requirements:
        raise ValueError(
            f"{ALGORITHM_ID}: metric requirements reference landmarks outside the skeleton: "
            f"{sorted(unknown_requirements)}"
        )

    metrics: list[ScalarMetric] = []
    series_parts: list[pa.Table] = []
    dropout_entity_ids: list[str] = []
    dropout_joint_names: list[str] = []
    dropout_start_ns: list[int] = []
    dropout_end_ns: list[int] = []
    dropout_missing_frames: list[int] = []
    dropout_duration_s: list[float] = []
    total_expected_frames = 0
    subject_codes_by_name = sorted(
        ((name, code) for code, name in enumerate(subjects)),
        key=lambda item: item[0],
    )
    if not subject_codes_by_name:
        raise ValueError(f"{ALGORITHM_ID}: no subject identity in Pose input")
    minimum_derivative_frames = int(spec.parameters["minimum_derivative_segment_frames"])

    for subject, subject_code in subject_codes_by_name:
        row_indexes = np.flatnonzero(subject_codes == subject_code)
        row_indexes = row_indexes[resolved_joint_indexes[row_indexes] >= 0]
        if row_indexes.size == 0:
            continue
        observed_times = np.unique(times_ns[row_indexes])
        first_ns = int(observed_times[0])
        last_ns = int(observed_times[-1])
        rate_hz = _rate_hz(row_indexes, times_ns, declared_rates)
        step_ns = int(round(1e9 / rate_hz))
        if step_ns <= 0:
            raise ValueError(f"{ALGORITHM_ID}: sampling rate does not resolve to nanoseconds")
        span_ns = last_ns - first_ns
        expected_count = int(round(span_ns / step_ns)) + 1
        if abs((expected_count - 1) * step_ns - span_ns) > 1:
            raise ValueError(
                f"{ALGORITHM_ID}: subject timestamps do not fit the declared cadence grid"
            )
        frame_times = first_ns + np.arange(expected_count, dtype=np.int64) * step_ns
        present = np.zeros((expected_count, len(names)), dtype=np.uint8)
        available = np.zeros_like(present)
        provider_error = np.full((expected_count, len(names)), np.nan, dtype=np.float64)

        delta_ns = times_ns[row_indexes] - first_ns
        frame_indexes = np.rint(delta_ns.astype(np.float64) / step_ns).astype(np.int64)
        if np.any(frame_indexes < 0) or np.any(frame_indexes >= expected_count):
            raise ValueError(f"{ALGORITHM_ID}: row falls outside the expected time grid")
        if np.any(np.abs(frame_times[frame_indexes] - times_ns[row_indexes]) > 1):
            raise ValueError(
                f"{ALGORITHM_ID}: timestamps are not aligned to the declared "
                f"{rate_hz:g} Hz frame grid"
            )
        landmark_indexes = resolved_joint_indexes[row_indexes].astype(np.int64)
        flat_indexes = frame_indexes * len(names) + landmark_indexes
        if np.unique(flat_indexes).size != flat_indexes.size:
            raise ValueError(f"{ALGORITHM_ID}: duplicate subject/time/landmark observation")
        present.reshape(-1)[flat_indexes] = 1
        finite_xyz = (
            np.isfinite(x_values[row_indexes])
            & np.isfinite(y_values[row_indexes])
            & np.isfinite(z_values[row_indexes])
        )
        usable_rows = available_values[row_indexes] & finite_xyz
        usable_flat_indexes = flat_indexes[usable_rows]
        available.reshape(-1)[usable_flat_indexes] = 1
        usable_errors = error_values[row_indexes[usable_rows]]
        finite_errors = np.isfinite(usable_errors) & (usable_errors >= 0)
        provider_error.reshape(-1)[usable_flat_indexes[finite_errors]] = usable_errors[
            finite_errors
        ]

        any_pose = np.any(present == 1, axis=1)
        any_usable_pose = np.any(available == 1, axis=1)
        total_expected_frames += expected_count
        scope = {
            "session_id": table.column("session_id")[int(row_indexes[0])].as_py()
            if "session_id" in table.column_names
            else None,
            "subject_id": subject,
            "trial_id": table.column("trial_id")[int(row_indexes[0])].as_py()
            if "trial_id" in table.column_names
            else None,
            "stream_id": table.column("stream_id")[int(row_indexes[0])].as_py()
            if "stream_id" in table.column_names
            else None,
        }
        provenance = {
            "source_range_from_ns": first_ns,
            "source_range_to_ns": last_ns,
            "expected_frames": expected_count,
            "observed_pose_frames": int(np.count_nonzero(any_pose)),
            "usable_pose_frames": int(np.count_nonzero(any_usable_pose)),
            "sampling_rate_hz": rate_hz,
            "expected_step_ns": step_ns,
            "availability_rule": spec.parameters["availability_rule"],
            "error_radius_semantics": (
                "provider p90 predicted error radius; not probability or confidence"
            ),
            "algorithm_id": ALGORITHM_ID,
            "algorithm_version": ALGORITHM_VERSION,
            "parameters": dict(spec.parameters),
            "derivative": dict(spec.parameters["derivative"]),
        }
        metrics.append(
            ScalarMetric(
                declaration=_declaration(
                    "pose.quality.coverage.any_pose_present",
                    "Pose quality frame-presence fraction",
                    "1",
                    "Fraction of cadence-expected frames with at least one provider Pose row, "
                    "within this subject's first-to-last observed time span.",
                ),
                value=float(np.mean(any_pose)),
                entity_id=subject,
                provenance=provenance,
                **scope,
            )
        )
        metrics.append(
            ScalarMetric(
                declaration=_declaration(
                    "pose.quality.coverage.any_usable_pose",
                    "Pose quality usable-frame fraction",
                    "1",
                    "Fraction of cadence-expected frames with at least one available finite "
                    "landmark, within this subject's first-to-last observed time span.",
                ),
                value=float(np.mean(any_usable_pose)),
                entity_id=subject,
                provenance=provenance,
                **scope,
            )
        )

        for name, index in joint_index.items():
            valid = available[:, index] == 1
            token = _token(name)
            metrics.append(
                ScalarMetric(
                    declaration=_declaration(
                        f"pose.quality.availability.{token}",
                        f"Pose quality cadence-grid availability for landmark {name}",
                        "1",
                        "Fraction of cadence-expected frames where the named landmark has "
                        "an available finite XYZ observation.",
                    ),
                    value=float(np.mean(valid)),
                    entity_id=subject,
                    provenance=provenance,
                    **scope,
                )
            )
            missing_runs = _runs(~valid)
            metrics.append(
                ScalarMetric(
                    declaration=_declaration(
                        f"pose.quality.dropout_count.{token}",
                        f"Pose quality dropout-interval count for landmark {name}",
                        "1",
                        "Number of contiguous missing/unavailable intervals on the explicit "
                        "cadence grid within the subject's observed span.",
                    ),
                    value=float(len(missing_runs)),
                    entity_id=subject,
                    provenance=provenance,
                    **scope,
                )
            )
            longest_frames = max((stop - start for start, stop in missing_runs), default=0)
            for start, stop in missing_runs:
                dropout_entity_ids.append(subject)
                dropout_joint_names.append(name)
                dropout_start_ns.append(int(frame_times[start]))
                dropout_end_ns.append(int(frame_times[stop - 1]) + step_ns)
                dropout_missing_frames.append(stop - start)
                dropout_duration_s.append((stop - start) * step_ns / 1e9)
            metrics.append(
                ScalarMetric(
                    declaration=_declaration(
                        f"pose.quality.longest_dropout.{token}",
                        f"Pose quality longest dropout for landmark {name}",
                        "s",
                        "Longest contiguous missing/unavailable interval on the explicit "
                        "cadence grid within the subject's observed span.",
                    ),
                    value=float(longest_frames * step_ns / 1e9),
                    entity_id=subject,
                    provenance=provenance,
                    **scope,
                )
            )
            error_values_for_joint = provider_error[:, index]
            finite_error = error_values_for_joint[np.isfinite(error_values_for_joint)]
            if finite_error.size:
                for statistic, value in (
                    ("mean", float(np.mean(finite_error))),
                    ("median", float(np.median(finite_error))),
                    ("p95", float(np.quantile(finite_error, 0.95, method="linear"))),
                ):
                    metrics.append(
                        ScalarMetric(
                            declaration=_declaration(
                                f"pose.quality.provider_error_radius_{statistic}.{token}",
                                f"Pose quality provider error-radius {statistic} "
                                f"for landmark {name}",
                                "m",
                                "Statistic over SkillCorner provider p90 predicted error-radius "
                                "samples; the p90 source meaning is preserved.",
                            ),
                            value=value,
                            entity_id=subject,
                            provenance=provenance,
                            **scope,
                        )
                    )

        for metric_name, indexes in requirement_indexes.items():
            usable = np.all(available[:, indexes] == 1, axis=1)
            token = _token(metric_name)
            metrics.append(
                ScalarMetric(
                    declaration=_declaration(
                        f"pose.quality.coverage.metric.{token}",
                        f"Pose quality usable-frame fraction for {metric_name}",
                        "1",
                        "Fraction of cadence-expected frames with all required landmarks "
                        "available and finite for the named metric.",
                    ),
                    value=float(np.mean(usable)),
                    entity_id=subject,
                    provenance={
                        **provenance,
                        "required_landmarks": list(requirements[metric_name]),
                    },
                    **scope,
                )
            )
            eligible = np.zeros(expected_count, dtype=bool)
            for start, stop in _runs(usable):
                if stop - start >= minimum_derivative_frames:
                    eligible[start:stop] = True
            metrics.append(
                ScalarMetric(
                    declaration=_declaration(
                        f"pose.quality.derivative_eligible_fraction.{token}",
                        f"Pose quality derivative-eligible fraction for {metric_name}",
                        "1",
                        "Fraction of expected frames belonging to a contiguous valid metric "
                        f"segment of at least {minimum_derivative_frames} frames.",
                    ),
                    value=float(np.mean(eligible)),
                    entity_id=subject,
                    provenance={
                        **provenance,
                        "required_landmarks": list(requirements[metric_name]),
                        "minimum_contiguous_frames": minimum_derivative_frames,
                    },
                    **scope,
                )
            )

        series_columns: dict[str, pa.Array] = {
            "entity_id": pa.array([subject] * expected_count, type=pa.string()),
            "t_rel_ns": pa.array(frame_times, type=pa.int64()),
            "any_pose_present": pa.array(any_pose, type=pa.uint8()),
            "any_pose_available": pa.array(any_usable_pose, type=pa.uint8()),
            "available_landmark_count": pa.array(
                np.sum(available, axis=1, dtype=np.uint16), type=pa.uint16()
            ),
            "expected_landmark_count": pa.array(
                np.full(expected_count, len(names), dtype=np.uint16), type=pa.uint16()
            ),
        }
        series_parts.append(pa.table(series_columns))

    series = pa.concat_tables(series_parts) if len(series_parts) > 1 else series_parts[0]
    series = series.replace_schema_metadata(
        {
            b"dynamis.measurement_class": b"PIPELINE_DERIVED",
            b"dynamis.algorithm_id": ALGORITHM_ID.encode(),
            b"dynamis.algorithm_version": ALGORITHM_VERSION.encode(),
        }
    )
    dropout_series = pa.table(
        {
            "entity_id": pa.array(dropout_entity_ids, type=pa.string()),
            "joint_name": pa.array(dropout_joint_names, type=pa.string()),
            "start_ns": pa.array(dropout_start_ns, type=pa.int64()),
            "end_ns_exclusive": pa.array(dropout_end_ns, type=pa.int64()),
            "missing_frames": pa.array(dropout_missing_frames, type=pa.uint32()),
            "duration_s": pa.array(dropout_duration_s, type=pa.float64()),
        }
    ).replace_schema_metadata(
        {
            b"dynamis.measurement_class": b"PIPELINE_DERIVED",
            b"dynamis.algorithm_id": ALGORITHM_ID.encode(),
            b"dynamis.algorithm_version": ALGORITHM_VERSION.encode(),
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
                    "Cadence-grid subject-level Pose presence and availability counts. "
                    "Missing samples are explicitly represented; no interpolation is performed."
                ),
            ),
            SeriesOutput(
                name="pose_quality_dropout_intervals",
                table=dropout_series,
                description=(
                    "Per-subject, per-landmark half-open dropout intervals on the cadence grid. "
                    "The end timestamp is exclusive."
                ),
            ),
        ),
        diagnostics={
            "entities": len(subject_codes_by_name),
            "expected_frames": total_expected_frames,
            "sampling_rate_strategy": spec.parameters["frame_grid"],
            "availability_rule": spec.parameters["availability_rule"],
            "minimum_derivative_segment_frames": minimum_derivative_frames,
            "error_radius_semantics": (
                "provider p90 predicted error radius; not probability or confidence"
            ),
        },
    )


__all__ = [
    "ALGORITHM_ID",
    "ALGORITHM_VERSION",
    "DEFAULT_PARAMETERS",
    "SERIES_NAME",
    "pose_quality_spec",
    "process_pose_quality",
]
