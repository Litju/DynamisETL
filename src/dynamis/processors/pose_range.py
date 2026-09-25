"""Exact selected-range summaries over versioned Pose processor series."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pyarrow as pa

from dynamis.processors.spec import (
    MetricDeclaration,
    ProcessorResult,
    ProcessorSpec,
    ScalarMetric,
    code_git_sha,
)

ALGORITHM_ID = "pose.range_summary"
ALGORITHM_VERSION = "1.0.0"

ANGLE_BY_LANDMARK = {
    "lKnee": "left_knee",
    "rKnee": "right_knee",
    "lHip": "left_hip",
    "rHip": "right_hip",
}


def _numeric(table: pa.Table, name: str) -> np.ndarray:
    if name not in table.column_names:
        return np.asarray([], dtype=np.float64)
    values = table.column(name).combine_chunks().to_numpy(zero_copy_only=False)
    return np.asarray(values, dtype=np.float64)


def _strings(table: pa.Table, name: str) -> list[str]:
    if name not in table.column_names:
        return []
    return ["" if value is None else str(value) for value in table.column(name).to_pylist()]


def _metric(metric_id: str, name: str, unit: str, description: str) -> MetricDeclaration:
    return MetricDeclaration(metric_id=metric_id, name=name, si_unit=unit, description=description)


def process_pose_range(
    *,
    dataset_id: str,
    session_id: str,
    trial_id: str,
    stream_id: str,
    subject_id: str,
    from_ns: int,
    to_ns: int,
    landmark_name: str,
    geometry: pa.Table,
    landmark_series: pa.Table,
    quality_frames: pa.Table,
    dropout_intervals: pa.Table,
    source_pose: pa.Table,
    source_checksums: Mapping[str, str],
) -> ProcessorResult:
    """Summarize an exact range without using client-reduced plotting samples."""
    if not all((dataset_id, session_id, trial_id, stream_id, subject_id, landmark_name)):
        raise ValueError(
            f"{ALGORITHM_ID}: dataset/session/trial/stream/subject/landmark are required"
        )
    if from_ns < 0 or to_ns < from_ns:
        raise ValueError(f"{ALGORITHM_ID}: exact canonical range must satisfy 0 <= from <= to")

    quality_times = np.asarray(quality_frames.column("t_rel_ns").to_numpy(), dtype=np.int64)
    if quality_times.size == 0:
        raise ValueError(f"{ALGORITHM_ID}: selected range contains no cadence-grid frames")
    if np.any(np.diff(quality_times) <= 0):
        raise ValueError(f"{ALGORITHM_ID}: quality frame times must be unique and increasing")
    if not (int(quality_times[0]) >= from_ns and int(quality_times[-1]) <= to_ns):
        raise ValueError(f"{ALGORITHM_ID}: quality input contains rows outside the requested range")
    if quality_times.size > 1:
        step_ns = int(np.median(np.diff(quality_times)))
    else:
        rates = _numeric(source_pose, "nominal_sampling_rate_hz")
        finite_rates = rates[np.isfinite(rates) & (rates > 0)]
        if finite_rates.size == 0:
            raise ValueError(f"{ALGORITHM_ID}: a singleton range requires a declared sampling rate")
        step_ns = int(round(1e9 / float(finite_rates[0])))
    range_to_exclusive = to_ns + step_ns

    parameters = {
        "dataset_id": dataset_id,
        "session_id": session_id,
        "trial_id": trial_id,
        "stream_id": stream_id,
        "subject_id": subject_id,
        "from_ns": from_ns,
        "to_ns": to_ns,
        "landmark_name": landmark_name,
        "body_anchor_landmark": "midHip",
        "source_checksums": dict(source_checksums),
        "input_series": {
            "pose.geometry": "pose.translation_invariant_kinematics",
            "pose.landmark": "pose.landmark_kinematics",
            "pose.quality": "pose.analysis_quality",
        },
    }
    spec = ProcessorSpec(
        algorithm_id=ALGORITHM_ID,
        name="Pose exact-range summary",
        version=ALGORITHM_VERSION,
        description=(
            "Produces a selected-range report by aggregating exact samples from versioned Pose "
            "processor series and provider error-radius evidence. It never reads chart-reduced "
            "data."
        ),
        parameters=parameters,
    )
    provenance = {
        **parameters,
        "code_git_sha": code_git_sha(),
        "measurement_class": "PIPELINE_DERIVED",
        "provider_error_radius_semantics": (
            "source provider p90 predicted error radius; not probability or confidence"
        ),
        "range_end_convention": (
            "inclusive requested to_ns; one source cadence used for dropout overlap"
        ),
        "range_algorithm_id": ALGORITHM_ID,
        "range_algorithm_version": ALGORITHM_VERSION,
    }
    scope = {
        "session_id": session_id,
        "subject_id": subject_id,
        "trial_id": trial_id,
        "stream_id": stream_id,
        "entity_id": subject_id,
    }
    metrics: list[ScalarMetric] = []

    def add(metric_id: str, name: str, unit: str, value: float, description: str) -> None:
        metrics.append(
            ScalarMetric(
                declaration=_metric(metric_id, name, unit, description),
                value=float(value),
                provenance=provenance,
                **scope,
            )
        )

    any_present = _numeric(quality_frames, "any_pose_present")
    any_available = _numeric(quality_frames, "any_pose_available")
    expected_landmarks = _numeric(quality_frames, "expected_landmark_count")
    if any_present.size == quality_times.size:
        add(
            "pose.range.coverage.any_pose_present",
            "Pose presence fraction in selected range",
            "1",
            float(np.mean(any_present == 1)),
            "Fraction of cadence-expected frames with at least one source Pose row in the exact "
            "range.",
        )
    if any_available.size == quality_times.size:
        add(
            "pose.range.coverage.any_usable_pose",
            "Usable Pose frame fraction in selected range",
            "1",
            float(np.mean(any_available == 1)),
            "Fraction of cadence-expected frames with at least one available finite landmark in "
            "the exact range.",
        )
    if expected_landmarks.size == quality_times.size and np.all(expected_landmarks > 0):
        available_count = _numeric(quality_frames, "available_landmark_count")
        if available_count.size == quality_times.size:
            add(
                "pose.range.coverage.mean_available_landmarks",
                "Mean available landmark count in selected range",
                "1",
                float(np.mean(available_count)),
                "Mean count of available finite source landmarks per cadence-expected frame in "
                "the exact range.",
            )

    token = landmark_name
    landmark_columns = {
        "available": f"available_{token}",
        "x": f"relative_position_x_{token}_m",
        "y": f"relative_position_y_{token}_m",
        "z": f"relative_position_z_{token}_m",
        "speed": f"body_relative_speed_{token}_m_s",
        "segment": "temporal_segment_index",
    }
    landmark_times = np.asarray(landmark_series.column("t_rel_ns").to_numpy(), dtype=np.int64)
    if landmark_times.size:
        if np.any((landmark_times < from_ns) | (landmark_times > to_ns)):
            raise ValueError(
                f"{ALGORITHM_ID}: landmark input contains rows outside the requested range"
            )
        available = _numeric(landmark_series, landmark_columns["available"]) == 1
        position = np.column_stack(
            [_numeric(landmark_series, landmark_columns[axis]) for axis in ("x", "y", "z")]
        )
        available = available & np.all(np.isfinite(position), axis=1)
        if np.any(available):
            selected_positions = position[available]
            displacement = float(np.linalg.norm(selected_positions[-1] - selected_positions[0]))
            add(
                f"pose.range.landmark.displacement.{token}",
                f"Body-anchor-relative displacement in selected range for {landmark_name}",
                "m",
                displacement,
                "Distance from the first to last available body-anchor-relative position in the "
                "exact range.",
            )
        segment_indexes = _numeric(landmark_series, landmark_columns["segment"])
        if landmark_times.size > 1 and segment_indexes.size == landmark_times.size:
            steps = np.diff(position, axis=0)
            delta_ns = np.diff(landmark_times)
            continuous = (
                available[:-1]
                & available[1:]
                & np.isfinite(segment_indexes[:-1])
                & (segment_indexes[:-1] == segment_indexes[1:])
                & (delta_ns > 0)
                & (delta_ns <= 1.5 * step_ns)
            )
            path_length = float(np.sum(np.linalg.norm(steps[continuous], axis=1)))
            add(
                f"pose.range.landmark.path_length.{token}",
                f"Body-anchor-relative path length in selected range for {landmark_name}",
                "m",
                path_length,
                "Sum of exact consecutive body-anchor-relative displacement magnitudes; no "
                "segment gap is bridged.",
            )
        speed = _numeric(landmark_series, landmark_columns["speed"])
        finite_speed = speed[np.isfinite(speed)]
        if finite_speed.size:
            add(
                f"pose.range.landmark.speed_mean.{token}",
                f"Body-anchor-relative mean speed in selected range for {landmark_name}",
                "m/s",
                float(np.mean(finite_speed)),
                "Mean of the versioned body-anchor-relative hybrid-axis speed series in the "
                "exact range.",
            )
            add(
                f"pose.range.landmark.speed_peak.{token}",
                f"Body-anchor-relative peak speed in selected range for {landmark_name}",
                "m/s",
                float(np.max(finite_speed)),
                "Peak of the versioned body-anchor-relative hybrid-axis speed series in the "
                "exact range.",
            )
        add(
            f"pose.range.coverage.landmark.{token}",
            f"Available-frame fraction in selected range for {landmark_name}",
            "1",
            float(np.mean(available)),
            "Fraction of exact cadence-grid frames with this landmark and the body anchor "
            "available and finite.",
        )

    joint_names = _strings(dropout_intervals, "joint_name")
    starts = _numeric(dropout_intervals, "start_ns")
    ends = _numeric(dropout_intervals, "end_ns_exclusive")
    if starts.size == len(joint_names) and ends.size == len(joint_names):
        overlapping = [
            index
            for index, joint in enumerate(joint_names)
            if joint == landmark_name
            and starts[index] < range_to_exclusive
            and ends[index] > from_ns
        ]
        clipped_durations = [
            max(0.0, min(ends[index], range_to_exclusive) - max(starts[index], from_ns)) / 1e9
            for index in overlapping
        ]
        add(
            f"pose.range.dropout_count.{token}",
            f"Dropout interval count in selected range for {landmark_name}",
            "1",
            float(len(overlapping)),
            "Number of stored half-open landmark dropout intervals that overlap the exact range.",
        )
        add(
            f"pose.range.longest_dropout.{token}",
            f"Longest clipped dropout in selected range for {landmark_name}",
            "s",
            max(clipped_durations, default=0.0),
            "Longest duration of a dropout interval clipped to the exact requested range.",
        )

    source_joints = _strings(source_pose, "joint_name")
    source_available = _numeric(source_pose, "is_available") == 1
    source_errors = _numeric(source_pose, "error_m")
    selected_error = source_errors[
        np.asarray([joint == landmark_name for joint in source_joints], dtype=bool)
        & source_available
        & np.isfinite(source_errors)
        & (source_errors >= 0)
    ]
    if selected_error.size:
        for statistic, value in (
            ("mean", float(np.mean(selected_error))),
            ("median", float(np.median(selected_error))),
            ("p95", float(np.quantile(selected_error, 0.95, method="linear"))),
        ):
            add(
                f"pose.range.provider_error_radius_{statistic}.{token}",
                f"Provider p90 error-radius {statistic} in range for {landmark_name}",
                "m",
                value,
                "Distribution summary of provider p90 predicted error-radius samples in the exact "
                "range; no confidence interpretation.",
            )

    angle_name = ANGLE_BY_LANDMARK.get(landmark_name)
    if angle_name is not None:
        angle_values = _numeric(geometry, f"angle_{angle_name}_rad")
        finite_angle = angle_values[np.isfinite(angle_values)]
        if finite_angle.size >= 2:
            add(
                f"pose.range.angle_rom.{angle_name}",
                f"Geometric included-angle ROM in selected range for {angle_name}",
                "rad",
                float(np.max(finite_angle) - np.min(finite_angle)),
                "Max-minus-min of the explicitly named geometric included-angle processor series; "
                "not an anatomical joint angle.",
            )
        velocity = _numeric(geometry, f"angular_velocity_{angle_name}_rad_s")
        finite_velocity = velocity[np.isfinite(velocity)]
        if finite_velocity.size:
            add(
                f"pose.range.angular_velocity_peak.{angle_name}",
                f"Peak geometric angular velocity in selected range for {angle_name}",
                "rad/s",
                float(np.max(np.abs(finite_velocity))),
                "Peak absolute value of the versioned angular-velocity processor series in the "
                "exact range.",
            )

    return ProcessorResult(
        spec=spec,
        metrics=tuple(metrics),
        diagnostics={
            "algorithm_id": ALGORITHM_ID,
            "algorithm_version": ALGORITHM_VERSION,
            "code_git_sha": code_git_sha(),
            "dataset_id": dataset_id,
            "session_id": session_id,
            "trial_id": trial_id,
            "stream_id": stream_id,
            "subject_id": subject_id,
            "from_ns": from_ns,
            "to_ns": to_ns,
            "expected_frames": int(quality_times.size),
            "landmark_name": landmark_name,
            "metric_count": len(metrics),
            "series_inputs_are_exact": True,
            "display_reduction_used": False,
        },
    )


__all__ = ["ALGORITHM_ID", "ALGORITHM_VERSION", "ANGLE_BY_LANDMARK", "process_pose_range"]
