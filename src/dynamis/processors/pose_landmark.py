"""Body-anchor-relative landmark kinematics and gap-safe derivatives."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

import numpy as np
import pyarrow as pa

from dynamis.processors.signals import DerivativeSpec, derivative_variable
from dynamis.processors.spec import (
    MetricDeclaration,
    ProcessorResult,
    ProcessorSpec,
    ScalarMetric,
    SeriesOutput,
)

ALGORITHM_ID = "pose.landmark_kinematics"
ALGORITHM_VERSION = "1.0.0"
SERIES_NAME = "pose_landmark_kinematics"
_TOKEN = re.compile(r"[^A-Za-z0-9]+")

DEFAULT_PARAMETERS: dict[str, Any] = {
    "landmark_names": [],
    "body_anchor_landmark": "midHip",
    "max_gap_factor": 1.5,
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
    "acceleration": {
        "enabled": False,
        "maximum_provider_error_radius_m": None,
        "minimum_segment_frames": 11,
    },
}

HYBRID_RELATIVE_SEMANTICS = (
    "Position is landmark XYZ minus the named same-frame body anchor. X/Y retain the source "
    "pitch axes; Z is centroid-relative. Displacement, path and speed describe this "
    "body-relative hybrid coordinate only, never global landmark travel or absolute vertical "
    "motion."
)


def _token(value: str) -> str:
    token = _TOKEN.sub("_", value.strip()).strip("_")
    if not token:
        raise ValueError(f"cannot derive a metric token from {value!r}")
    return token


def _encoded_strings(table: pa.Table, name: str) -> tuple[np.ndarray, tuple[str, ...]]:
    encoded = table.column(name).combine_chunks().dictionary_encode()
    if encoded.indices.null_count:
        raise ValueError(f"{ALGORITHM_ID}: {name} cannot contain null values")
    codes = np.asarray(encoded.indices.to_numpy(zero_copy_only=False), dtype=np.int32)
    return codes, tuple(str(value) for value in encoded.dictionary.to_pylist())


def _float_column(table: pa.Table, name: str) -> np.ndarray:
    values = table.column(name).combine_chunks().to_numpy(zero_copy_only=False)
    return np.asarray(values, dtype=np.float64)


def _rate_hz(
    table: pa.Table,
    subject_rows: np.ndarray,
    times_ns: np.ndarray,
) -> float:
    if "nominal_sampling_rate_hz" in table.column_names:
        rates = {
            float(value)
            for value in table.column("nominal_sampling_rate_hz").unique().to_pylist()
            if value is not None and math.isfinite(float(value)) and float(value) > 0
        }
        if len(rates) > 1:
            raise ValueError(f"{ALGORITHM_ID}: one stream cannot have multiple sampling rates")
        if rates:
            return next(iter(rates))
    unique_times = np.unique(times_ns[subject_rows])
    if unique_times.size < 2:
        return 0.0
    steps = np.diff(unique_times).astype(np.float64)
    positive = steps[steps > 0]
    return 0.0 if positive.size == 0 else 1e9 / float(np.median(positive))


def _valid_runs(
    valid: np.ndarray,
    times_ns: np.ndarray,
    *,
    maximum_gap_ns: float,
) -> tuple[tuple[int, int], ...]:
    if valid.size == 0:
        return ()
    gaps = np.zeros(valid.size, dtype=bool)
    if valid.size > 1:
        gaps[1:] = np.diff(times_ns).astype(np.float64) > maximum_gap_ns
    starts_mask = valid & np.concatenate(([True], (~valid[:-1]) | gaps[1:]))
    ends_mask = valid & np.concatenate(((~valid[1:]) | gaps[1:], [True]))
    starts = np.flatnonzero(starts_mask)
    stops = np.flatnonzero(ends_mask) + 1
    return tuple((int(start), int(stop)) for start, stop in zip(starts, stops, strict=True))


def pose_landmark_spec(parameters: Mapping[str, Any] | None = None) -> ProcessorSpec:
    resolved = {**DEFAULT_PARAMETERS, **dict(parameters or {})}
    raw_names = resolved["landmark_names"]
    if not isinstance(raw_names, (list, tuple)):
        raise ValueError("landmark_names must be an array")
    names = tuple(str(name) for name in raw_names)
    anchor = str(resolved["body_anchor_landmark"])
    if not anchor:
        raise ValueError("body_anchor_landmark must be non-empty")
    if len(set(names)) != len(names) or any(not name for name in names):
        raise ValueError("landmark_names must contain unique non-empty names")
    if len({_token(name) for name in names}) != len(names):
        raise ValueError("landmark_names must map to unique metric tokens")
    max_gap_factor = float(resolved["max_gap_factor"])
    if not math.isfinite(max_gap_factor) or max_gap_factor < 1.0:
        raise ValueError("max_gap_factor must be finite and at least 1.0")
    derivative = dict(resolved["derivative"])
    derivative_spec = DerivativeSpec.from_parameters(derivative)
    acceleration = dict(resolved["acceleration"])
    enabled = acceleration.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("acceleration.enabled must be boolean")
    minimum_acceleration_frames = int(acceleration.get("minimum_segment_frames", 11))
    if minimum_acceleration_frames < 5:
        raise ValueError("acceleration.minimum_segment_frames must be at least 5")
    maximum_error = acceleration.get("maximum_provider_error_radius_m")
    if enabled and (
        maximum_error is None
        or not math.isfinite(float(maximum_error))
        or float(maximum_error) <= 0
    ):
        raise ValueError(
            "enabled acceleration requires a positive maximum_provider_error_radius_m gate"
        )
    resolved["landmark_names"] = list(names)
    resolved["body_anchor_landmark"] = anchor
    resolved["max_gap_factor"] = max_gap_factor
    resolved["derivative"] = derivative_spec.parameters()
    resolved["acceleration"] = {
        "enabled": enabled,
        "maximum_provider_error_radius_m": (
            float(maximum_error) if enabled and maximum_error is not None else None
        ),
        "minimum_segment_frames": minimum_acceleration_frames,
    }
    return ProcessorSpec(
        algorithm_id=ALGORITHM_ID,
        name="Body-anchor-relative Pose landmark kinematics",
        version=ALGORITHM_VERSION,
        description=(
            "Computes named body-anchor-relative landmark positions, displacement, path, and "
            "gap-safe speed. Acceleration is disabled by default and requires an explicit "
            "provider-radius and minimum-segment gate. Source hybrid-frame semantics are preserved."
        ),
        parameters=resolved,
    )


def process_pose_landmark_kinematics(
    table: pa.Table,
    *,
    parameters: Mapping[str, Any] | None = None,
) -> ProcessorResult:
    """Compute geometric landmark motion relative to a named same-frame anchor."""
    spec = pose_landmark_spec(parameters)
    for column in (
        "subject_id",
        "joint_name",
        "t_rel_ns",
        "is_available",
        "x_m",
        "y_m",
        "z_m",
        "error_m",
    ):
        if column not in table.column_names:
            raise ValueError(f"{ALGORITHM_ID}: required column {column!r} is absent")
    if table.num_rows == 0:
        raise ValueError(f"{ALGORITHM_ID}: empty Pose input has no kinematics")

    subject_codes, subjects = _encoded_strings(table, "subject_id")
    joint_codes, joint_dictionary = _encoded_strings(table, "joint_name")
    names = tuple(spec.parameters["landmark_names"]) or tuple(
        name for name in joint_dictionary if name != spec.parameters["body_anchor_landmark"]
    )
    anchor_name = str(spec.parameters["body_anchor_landmark"])
    if anchor_name not in joint_dictionary:
        raise ValueError(f"{ALGORITHM_ID}: body anchor {anchor_name!r} is absent from the stream")
    if not names:
        raise ValueError(f"{ALGORITHM_ID}: no requested landmarks are available")
    required_names = tuple(dict.fromkeys((*names, anchor_name)))
    joint_index = {name: index for index, name in enumerate(required_names)}
    code_to_joint = np.asarray(
        [joint_index.get(name, -1) for name in joint_dictionary], dtype=np.int32
    )
    row_joint_index = code_to_joint[joint_codes]
    times_all = np.asarray(table.column("t_rel_ns").to_numpy(zero_copy_only=False), dtype=np.int64)
    x_all = _float_column(table, "x_m")
    y_all = _float_column(table, "y_m")
    z_all = _float_column(table, "z_m")
    error_all = _float_column(table, "error_m")
    available_all = np.asarray(
        table.column("is_available").combine_chunks().to_numpy(zero_copy_only=False),
        dtype=np.bool_,
    )

    metrics: list[ScalarMetric] = []
    series_parts: list[pa.Table] = []
    total_frames = 0
    filter_ineligible_segments = 0
    maximum_gap_factor = float(spec.parameters["max_gap_factor"])
    derivative_spec = DerivativeSpec.from_parameters(dict(spec.parameters["derivative"]))
    acceleration = dict(spec.parameters["acceleration"])
    acceleration_enabled = bool(acceleration["enabled"])
    acceleration_max_error = acceleration["maximum_provider_error_radius_m"]
    acceleration_minimum_frames = int(acceleration["minimum_segment_frames"])
    anchor_index = joint_index[anchor_name]
    output_names = tuple(name for name in names if name != anchor_name)
    output_indices = {name: joint_index[name] for name in output_names}

    for subject_code, subject in enumerate(subjects):
        source_rows = np.flatnonzero(subject_codes == subject_code)
        source_rows = source_rows[row_joint_index[source_rows] >= 0]
        frame_times, frame_index = np.unique(times_all[source_rows], return_inverse=True)
        if frame_times.size == 0:
            continue
        rate_hz = _rate_hz(table, source_rows, times_all)
        if rate_hz > 0:
            expected_step_ns = 1e9 / rate_hz
        elif frame_times.size > 1:
            expected_step_ns = float(np.median(np.diff(frame_times)))
        else:
            expected_step_ns = math.inf
        maximum_gap_ns = maximum_gap_factor * expected_step_ns
        frames = int(frame_times.size)
        total_frames += frames
        matrix_size = frames * len(required_names)
        positions = np.full((matrix_size, 3), np.nan, dtype=np.float64)
        provider_error = np.full(matrix_size, np.nan, dtype=np.float64)
        available = np.zeros(matrix_size, dtype=np.uint8)
        subject_joint_indexes = row_joint_index[source_rows].astype(np.int64)
        flat = frame_index.astype(np.int64) * len(required_names) + subject_joint_indexes
        if np.unique(flat).size != flat.size:
            raise ValueError(f"{ALGORITHM_ID}: duplicate subject/time/landmark observation")
        source_positions = np.column_stack(
            (x_all[source_rows], y_all[source_rows], z_all[source_rows])
        )
        finite_xyz = np.all(np.isfinite(source_positions), axis=1)
        positions[flat] = source_positions
        available[flat] = (available_all[source_rows] & finite_xyz).astype(np.uint8)
        errors = error_all[source_rows]
        provider_error[flat] = np.where(np.isfinite(errors) & (errors >= 0), errors, np.nan)
        positions = positions.reshape(frames, len(required_names), 3)
        provider_error = provider_error.reshape(frames, len(required_names))
        available = available.reshape(frames, len(required_names)).astype(bool)
        anchor_positions = positions[:, anchor_index, :]
        anchor_available = available[:, anchor_index]
        anchor_error = provider_error[:, anchor_index]

        columns: dict[str, pa.Array] = {
            "entity_id": pa.array([subject] * frames, type=pa.string()),
            "t_rel_ns": pa.array(frame_times, type=pa.int64()),
            "temporal_segment_index": pa.array(
                _temporal_segment_indexes(frame_times, maximum_gap_ns), type=pa.int32()
            ),
        }
        scope = {
            "session_id": table.column("session_id")[int(source_rows[0])].as_py()
            if "session_id" in table.column_names
            else None,
            "subject_id": subject,
            "trial_id": table.column("trial_id")[int(source_rows[0])].as_py()
            if "trial_id" in table.column_names
            else None,
            "stream_id": table.column("stream_id")[int(source_rows[0])].as_py()
            if "stream_id" in table.column_names
            else None,
        }
        provenance = {
            "body_anchor_landmark": anchor_name,
            "coordinate_semantics": HYBRID_RELATIVE_SEMANTICS,
            "sampling_rate_hz": rate_hz,
            "max_gap_factor": maximum_gap_factor,
            "derivative": dict(spec.parameters["derivative"]),
            "acceleration_gate": dict(acceleration),
            "measurement_class": "PIPELINE_DERIVED",
        }

        for landmark in output_names:
            token = _token(landmark)
            landmark_index = output_indices[landmark]
            valid = available[:, landmark_index] & anchor_available
            relative = positions[:, landmark_index, :] - anchor_positions
            relative[~valid] = np.nan
            displacement = np.full(frames, np.nan, dtype=np.float64)
            path_length = np.full(frames, np.nan, dtype=np.float64)
            speed = np.full(frames, np.nan, dtype=np.float64)
            landmark_acceleration = np.full(frames, np.nan, dtype=np.float64)
            if np.any(valid):
                first_valid = int(np.flatnonzero(valid)[0])
                displacement[valid] = np.linalg.norm(
                    relative[valid] - relative[first_valid], axis=1
                )
            segments = _valid_runs(valid, frame_times, maximum_gap_ns=maximum_gap_ns)
            total_path = 0.0
            speed_values: list[np.ndarray] = []
            acceleration_values: list[np.ndarray] = []
            for start, stop in segments:
                run = slice(start, stop)
                points = relative[run]
                steps = np.linalg.norm(np.diff(points, axis=0), axis=1)
                run_path = np.concatenate(([0.0], np.cumsum(steps)))
                path_length[run] = run_path
                total_path += float(run_path[-1]) if run_path.size else 0.0
                if rate_hz <= 0 or stop - start < 2:
                    continue
                try:
                    filtered = np.column_stack(
                        [
                            derivative_spec.filter.apply(points[:, axis], rate_hz=rate_hz)
                            for axis in range(3)
                        ]
                    )
                except ValueError:
                    filter_ineligible_segments += 1
                    continue
                velocity = np.column_stack(
                    [
                        derivative_variable(
                            filtered[:, axis],
                            frame_times[run],
                            edge_policy=derivative_spec.edge_policy,
                        )
                        for axis in range(3)
                    ]
                )
                run_speed = np.linalg.norm(velocity, axis=1)
                run_speed[~np.all(np.isfinite(velocity), axis=1)] = np.nan
                speed[run] = run_speed
                speed_values.append(run_speed[np.isfinite(run_speed)])

                if not acceleration_enabled or stop - start < acceleration_minimum_frames:
                    continue
                landmark_error = provider_error[run, landmark_index]
                anchor_run_error = anchor_error[run]
                error_valid = (
                    np.isfinite(landmark_error)
                    & np.isfinite(anchor_run_error)
                    & (landmark_error <= float(acceleration_max_error))
                    & (anchor_run_error <= float(acceleration_max_error))
                )
                if not np.all(error_valid):
                    continue
                second = np.column_stack(
                    [
                        derivative_variable(
                            velocity[:, axis],
                            frame_times[run],
                            edge_policy=derivative_spec.edge_policy,
                        )
                        for axis in range(3)
                    ]
                )
                run_acceleration = np.linalg.norm(second, axis=1)
                run_acceleration[~np.all(np.isfinite(second), axis=1)] = np.nan
                landmark_acceleration[run] = run_acceleration
                acceleration_values.append(run_acceleration[np.isfinite(run_acceleration)])

            columns[f"relative_position_x_{token}_m"] = pa.array(relative[:, 0], type=pa.float64())
            columns[f"relative_position_y_{token}_m"] = pa.array(relative[:, 1], type=pa.float64())
            columns[f"relative_position_z_{token}_m"] = pa.array(relative[:, 2], type=pa.float64())
            columns[f"displacement_from_range_start_{token}_m"] = pa.array(
                displacement, type=pa.float64()
            )
            columns[f"path_length_{token}_m"] = pa.array(path_length, type=pa.float64())
            columns[f"body_relative_speed_{token}_m_s"] = pa.array(speed, type=pa.float64())
            columns[f"available_{token}"] = pa.array(valid.astype(np.uint8), type=pa.uint8())
            if acceleration_enabled:
                columns[f"body_relative_acceleration_{token}_m_s2"] = pa.array(
                    landmark_acceleration, type=pa.float64()
                )

            token_provenance = {**provenance, "landmark_name": landmark}
            metrics.append(
                ScalarMetric(
                    declaration=_metric(
                        f"pose.landmark.coverage.{token}",
                        f"Body-anchor-relative coverage for {landmark}",
                        "1",
                        f"Fraction of source frames where {landmark} and {anchor_name} are both "
                        "available.",
                    ),
                    value=float(np.mean(valid)),
                    entity_id=subject,
                    provenance=token_provenance,
                    **scope,
                )
            )
            if segments:
                metrics.append(
                    ScalarMetric(
                        declaration=_metric(
                            f"pose.landmark.path_length.{token}",
                            f"Body-anchor-relative path length for {landmark}",
                            "m",
                            "Sum of observed consecutive displacement magnitudes within valid "
                            "contiguous segments; path resets at gaps.",
                        ),
                        value=total_path,
                        entity_id=subject,
                        provenance=token_provenance,
                        **scope,
                    )
                )
            valid_displacement = displacement[np.isfinite(displacement)]
            if valid_displacement.size:
                last_valid_index = int(np.flatnonzero(np.isfinite(displacement))[-1])
                metrics.append(
                    ScalarMetric(
                        declaration=_metric(
                            f"pose.landmark.displacement_from_range_start.{token}",
                            f"Body-anchor-relative displacement from range start for {landmark}",
                            "m",
                            "Distance at the last available observation in the requested range "
                            "from the first available body-anchor-relative point.",
                        ),
                        value=float(valid_displacement[-1]),
                        entity_id=subject,
                        provenance={
                            **token_provenance,
                            "last_available_time_ns": int(frame_times[last_valid_index]),
                        },
                        **scope,
                    )
                )
            finite_speed = (
                np.concatenate(speed_values) if speed_values else np.asarray([], dtype=np.float64)
            )
            if finite_speed.size:
                for statistic, value in (
                    ("mean", float(np.mean(finite_speed))),
                    ("peak", float(np.max(finite_speed))),
                ):
                    metrics.append(
                        ScalarMetric(
                            declaration=_metric(
                                f"pose.landmark.speed_{statistic}.{token}",
                                f"Body-anchor-relative speed {statistic} for {landmark}",
                                "m/s",
                                "Norm of the versioned derivative of body-anchor-relative "
                                "coordinates in the provider hybrid axes; not global "
                                "landmark speed.",
                            ),
                            value=value,
                            entity_id=subject,
                            provenance=token_provenance,
                            **scope,
                        )
                    )
            if acceleration_enabled:
                finite_acceleration = (
                    np.concatenate(acceleration_values)
                    if acceleration_values
                    else np.asarray([], dtype=np.float64)
                )
                if finite_acceleration.size:
                    metrics.append(
                        ScalarMetric(
                            declaration=_metric(
                                f"pose.landmark.acceleration_peak.{token}",
                                f"Body-anchor-relative acceleration peak for {landmark}",
                                "m/s^2",
                                "Peak norm of the second derivative; emitted only for contiguous "
                                "runs meeting the configured minimum length and "
                                "provider-radius gate.",
                            ),
                            value=float(np.max(finite_acceleration)),
                            entity_id=subject,
                            provenance=token_provenance,
                            **scope,
                        )
                    )

        series_parts.append(pa.table(columns))

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
                description=HYBRID_RELATIVE_SEMANTICS,
            ),
        ),
        diagnostics={
            "entities": len(subjects),
            "frames": total_frames,
            "landmarks": list(output_names),
            "body_anchor_landmark": anchor_name,
            "filter_ineligible_segments": filter_ineligible_segments,
            "acceleration_enabled": acceleration_enabled,
            "coordinate_semantics": HYBRID_RELATIVE_SEMANTICS,
        },
    )


def _metric(metric_id: str, name: str, unit: str, description: str) -> MetricDeclaration:
    return MetricDeclaration(
        metric_id=metric_id,
        name=name,
        si_unit=unit,
        description=description,
    )


def _temporal_segment_indexes(times_ns: np.ndarray, maximum_gap_ns: float) -> np.ndarray:
    segments = np.zeros(times_ns.size, dtype=np.int32)
    if times_ns.size > 1:
        segments[1:] = np.cumsum(np.diff(times_ns).astype(np.float64) > maximum_gap_ns)
    return segments


__all__ = [
    "ALGORITHM_ID",
    "ALGORITHM_VERSION",
    "DEFAULT_PARAMETERS",
    "HYBRID_RELATIVE_SEMANTICS",
    "SERIES_NAME",
    "pose_landmark_spec",
    "process_pose_landmark_kinematics",
]
