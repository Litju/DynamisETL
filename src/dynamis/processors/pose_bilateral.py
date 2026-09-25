"""Bilateral comparisons of explicitly named geometric Pose angle series.

The processor only compares left/right series for the same subject at exactly
matching source timestamps. It emits descriptive differences and waveform
statistics, never normative or injury-risk labels.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

import numpy as np
import pyarrow as pa

from dynamis.processors.pose import process_pose
from dynamis.processors.spec import (
    MetricDeclaration,
    ProcessorResult,
    ProcessorSpec,
    ScalarMetric,
    SeriesOutput,
)

ALGORITHM_ID = "pose.bilateral_geometry"
ALGORITHM_VERSION = "1.0.0"
SERIES_NAME = "pose_bilateral_geometry"
_TOKEN = re.compile(r"[^A-Za-z0-9]+")

DEFAULT_PARAMETERS: dict[str, Any] = {
    "angles": [],
    "angle_pairs": [],
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
}


def _token(value: str) -> str:
    token = _TOKEN.sub("_", value.strip()).strip("_")
    if not token:
        raise ValueError(f"cannot derive a metric token from {value!r}")
    return token


def _metric(metric_id: str, name: str, unit: str, description: str) -> MetricDeclaration:
    return MetricDeclaration(
        metric_id=metric_id,
        name=name,
        si_unit=unit,
        description=description,
    )


def pose_bilateral_spec(parameters: Mapping[str, Any] | None = None) -> ProcessorSpec:
    resolved = {**DEFAULT_PARAMETERS, **dict(parameters or {})}
    angles = resolved["angles"]
    pairs = resolved["angle_pairs"]
    if not isinstance(angles, (list, tuple)) or not isinstance(pairs, (list, tuple)):
        raise ValueError("angles and angle_pairs must be arrays")
    angle_names: set[str] = set()
    for angle in angles:
        if not isinstance(angle, Mapping):
            raise ValueError("each bilateral angle must be a named geometric definition")
        name = str(angle.get("name", ""))
        if not name or name in angle_names:
            raise ValueError("angle names must be unique and non-empty")
        for key in ("vertex_landmark", "first_landmark", "second_landmark"):
            if not isinstance(angle.get(key), str) or not angle[key]:
                raise ValueError(f"angle {name!r} requires {key}")
        angle_names.add(name)
    if not angle_names:
        raise ValueError("at least one angle definition is required")
    if not pairs:
        raise ValueError("at least one bilateral angle pair is required")
    pair_names: set[str] = set()
    pair_tokens: set[str] = set()
    normalized_pairs: list[dict[str, str]] = []
    for pair in pairs:
        if not isinstance(pair, Mapping):
            raise ValueError("each angle pair must name left and right angle definitions")
        name = str(pair.get("name", ""))
        left = str(pair.get("left_angle", ""))
        right = str(pair.get("right_angle", ""))
        if not name or name in pair_names:
            raise ValueError("bilateral pair names must be unique and non-empty")
        if left not in angle_names or right not in angle_names or left == right:
            raise ValueError(f"bilateral pair {name!r} must reference distinct defined angles")
        token = _token(name)
        if token in pair_tokens:
            raise ValueError("bilateral pair names must map to unique metric tokens")
        pair_names.add(name)
        pair_tokens.add(token)
        normalized_pairs.append({"name": name, "left_angle": left, "right_angle": right})
    resolved["angles"] = [dict(angle) for angle in angles]
    resolved["angle_pairs"] = normalized_pairs
    resolved["derivative"] = dict(resolved["derivative"])
    return ProcessorSpec(
        algorithm_id=ALGORITHM_ID,
        name="Bilateral geometric Pose comparison",
        version=ALGORITHM_VERSION,
        description=(
            "Compares explicitly defined left/right geometric included-angle series at exact "
            "same-subject timestamps. Outputs remain descriptive and non-normative."
        ),
        parameters=resolved,
    )


def process_pose_bilateral(
    table: pa.Table,
    *,
    parameters: Mapping[str, Any] | None = None,
) -> ProcessorResult:
    """Compare homologous geometric angles within one subject and exact timebase."""
    spec = pose_bilateral_spec(parameters)
    pose_parameters = {
        "segments": [],
        "angles": list(spec.parameters["angles"]),
        "derivative": dict(spec.parameters["derivative"]),
    }
    upstream = process_pose(table, parameters=pose_parameters)
    if not upstream.series:
        raise ValueError(f"{ALGORITHM_ID}: upstream angle series is empty")
    source = upstream.series[0].table
    required = {"entity_id", "t_rel_ns"}
    if not required.issubset(source.column_names):
        raise ValueError(f"{ALGORITHM_ID}: upstream series lacks subject/time identity")

    entity_encoded = source.column("entity_id").combine_chunks().dictionary_encode()
    if entity_encoded.indices.null_count:
        raise ValueError(f"{ALGORITHM_ID}: entity_id cannot contain null values")
    entity_codes = np.asarray(entity_encoded.indices.to_numpy(zero_copy_only=False), dtype=np.int32)
    subjects = tuple(str(value) for value in entity_encoded.dictionary.to_pylist())
    times_ns = np.asarray(source.column("t_rel_ns").to_numpy(zero_copy_only=False), dtype=np.int64)
    angle_columns = {
        name: np.asarray(
            source.column(f"angle_{_token(name)}_rad").to_numpy(zero_copy_only=False),
            dtype=np.float64,
        )
        for name in angle_names(spec.parameters["angles"])
    }
    pairs = tuple(spec.parameters["angle_pairs"])
    metrics: list[ScalarMetric] = []
    series_parts: list[pa.Table] = []
    scope_base = {
        "session_id": table.column("session_id")[0].as_py()
        if "session_id" in table.column_names
        else None,
        "trial_id": table.column("trial_id")[0].as_py()
        if "trial_id" in table.column_names
        else None,
        "stream_id": table.column("stream_id")[0].as_py()
        if "stream_id" in table.column_names
        else None,
    }

    for subject_code, subject in enumerate(subjects):
        indexes = np.flatnonzero(entity_codes == subject_code)
        subject_times = times_ns[indexes]
        if np.any(np.diff(subject_times) <= 0):
            raise ValueError(
                f"{ALGORITHM_ID}: source times must be unique and increasing per subject"
            )
        subject_columns: dict[str, pa.Array] = {
            "entity_id": pa.array([subject] * indexes.size, type=pa.string()),
            "t_rel_ns": pa.array(subject_times, type=pa.int64()),
        }
        for pair in pairs:
            pair_name = str(pair["name"])
            left_name = str(pair["left_angle"])
            right_name = str(pair["right_angle"])
            left = angle_columns[left_name][indexes]
            right = angle_columns[right_name][indexes]
            valid = np.isfinite(left) & np.isfinite(right)
            difference = np.full(indexes.size, np.nan, dtype=np.float64)
            difference[valid] = right[valid] - left[valid]
            token = _token(pair_name)
            subject_columns[f"left_{token}_angle_rad"] = pa.array(left, type=pa.float64())
            subject_columns[f"right_{token}_angle_rad"] = pa.array(right, type=pa.float64())
            subject_columns[f"right_minus_left_{token}_rad"] = pa.array(
                difference, type=pa.float64()
            )
            subject_columns[f"common_available_{token}"] = pa.array(
                valid.astype(np.uint8), type=pa.uint8()
            )

            valid_difference = difference[valid]
            provenance = {
                "left_angle": left_name,
                "right_angle": right_name,
                "comparison": "right_minus_left",
                "alignment": "same subject and exact canonical timestamp",
                "common_frames": int(valid_difference.size),
                "source_measurement_class": "MODEL_ESTIMATED",
                "derived_measurement_class": "PIPELINE_DERIVED",
                "upstream_algorithm_id": upstream.spec.algorithm_id,
                "upstream_algorithm_version": upstream.spec.version,
                "normative_label": None,
            }
            metrics.append(
                ScalarMetric(
                    declaration=_metric(
                        f"pose.bilateral.coverage.{token}",
                        f"Bilateral common-frame coverage for {pair_name}",
                        "1",
                        "Fraction of same-subject exact timestamps with both geometric angles "
                        "available.",
                    ),
                    value=float(np.mean(valid)),
                    entity_id=subject,
                    provenance=provenance,
                    **scope_base,
                )
            )
            if valid_difference.size:
                summaries = (
                    (
                        "mean",
                        float(np.mean(valid_difference)),
                        "rad",
                        "Mean signed right-minus-left geometric angle difference.",
                    ),
                    (
                        "mean_absolute",
                        float(np.mean(np.abs(valid_difference))),
                        "rad",
                        "Mean absolute right-minus-left geometric angle difference.",
                    ),
                    (
                        "rms",
                        float(np.sqrt(np.mean(valid_difference**2))),
                        "rad",
                        "Root-mean-square right-minus-left geometric angle difference.",
                    ),
                )
                for statistic, value, unit, description in summaries:
                    metrics.append(
                        ScalarMetric(
                            declaration=_metric(
                                f"pose.bilateral.angle_difference_{statistic}.{token}",
                                f"Bilateral {statistic.replace('_', ' ')} for {pair_name}",
                                unit,
                                description,
                            ),
                            value=value,
                            entity_id=subject,
                            provenance=provenance,
                            **scope_base,
                        )
                    )
                if valid_difference.size >= 2:
                    metrics.append(
                        ScalarMetric(
                            declaration=_metric(
                                f"pose.bilateral.angle_difference_range.{token}",
                                f"Bilateral angle-difference range for {pair_name}",
                                "rad",
                                "Range of the right-minus-left geometric angle difference.",
                            ),
                            value=float(np.max(valid_difference) - np.min(valid_difference)),
                            entity_id=subject,
                            provenance=provenance,
                            **scope_base,
                        )
                    )
            if valid_difference.size >= 3:
                valid_left = left[valid]
                valid_right = right[valid]
                if np.std(valid_left) > 0 and np.std(valid_right) > 0:
                    correlation = float(np.corrcoef(valid_left, valid_right)[0, 1])
                    if math.isfinite(correlation):
                        metrics.append(
                            ScalarMetric(
                                declaration=_metric(
                                    f"pose.bilateral.waveform_correlation.{token}",
                                    f"Bilateral waveform correlation for {pair_name}",
                                    "1",
                                    "Descriptive Pearson correlation on common exact-time samples; "
                                    "no normative threshold is applied.",
                                ),
                                value=correlation,
                                entity_id=subject,
                                provenance=provenance,
                                **scope_base,
                            )
                        )
                left_max = np.max(valid_left)
                right_max = np.max(valid_right)
                if (
                    np.count_nonzero(valid_left == left_max) == 1
                    and np.count_nonzero(valid_right == right_max) == 1
                ):
                    left_peak = int(np.argmax(valid_left))
                    right_peak = int(np.argmax(valid_right))
                    common_times = subject_times[valid]
                    offset_s = float(common_times[right_peak] - common_times[left_peak]) / 1e9
                    metrics.append(
                        ScalarMetric(
                            declaration=_metric(
                                f"pose.bilateral.maximum_angle_time_offset.{token}",
                                f"Bilateral maximum-angle time offset for {pair_name}",
                                "s",
                                "Time of the right maximum included angle minus the left maximum, "
                                "when each maximum is unique over common available samples.",
                            ),
                            value=offset_s,
                            entity_id=subject,
                            provenance=provenance,
                            **scope_base,
                        )
                    )
        series_parts.append(pa.table(subject_columns))

    series = pa.concat_tables(series_parts) if len(series_parts) > 1 else series_parts[0]
    series = series.replace_schema_metadata(
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
                    "Same-subject exact-timestamp left/right geometric included-angle comparisons. "
                    "Differences are right minus left and remain descriptive."
                ),
            ),
        ),
        diagnostics={
            "entities": len(subjects),
            "frames": int(source.num_rows),
            "angle_pairs": len(pairs),
            "upstream_algorithm_id": upstream.spec.algorithm_id,
            "upstream_algorithm_version": upstream.spec.version,
            "normative_assessment": False,
        },
    )


def angle_names(angles: Any) -> tuple[str, ...]:
    """Extract validated angle names for the upstream series columns."""
    return tuple(str(angle["name"]) for angle in angles)


__all__ = [
    "ALGORITHM_ID",
    "ALGORITHM_VERSION",
    "DEFAULT_PARAMETERS",
    "SERIES_NAME",
    "pose_bilateral_spec",
    "process_pose_bilateral",
]
