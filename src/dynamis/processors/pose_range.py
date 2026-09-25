"""Exact selected-range summaries over versioned Pose processor series."""

from __future__ import annotations

import math
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
ALGORITHM_VERSION = "1.1.0"

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


def _runs(mask: np.ndarray) -> tuple[tuple[int, int], ...]:
    if mask.size == 0:
        return ()
    padded = np.concatenate(([False], mask, [False])).astype(np.int8)
    changes = np.diff(padded)
    starts = np.flatnonzero(changes == 1)
    stops = np.flatnonzero(changes == -1)
    return tuple((int(start), int(stop)) for start, stop in zip(starts, stops, strict=True))


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
    sampling_rate_hz: float,
    grid_origin_ns: int,
    geometry: pa.Table,
    landmark_series: pa.Table,
    quality_frames: pa.Table,
    bilateral_series: pa.Table | None,
    source_pose: pa.Table,
    source_checksums: Mapping[str, str],
    input_series_versions: Mapping[str, str],
) -> ProcessorResult:
    """Summarize an exact range without using client-reduced plotting samples."""
    if not all((dataset_id, session_id, trial_id, stream_id, subject_id, landmark_name)):
        raise ValueError(
            f"{ALGORITHM_ID}: dataset/session/trial/stream/subject/landmark are required"
        )
    if from_ns < 0 or to_ns < from_ns:
        raise ValueError(f"{ALGORITHM_ID}: exact canonical range must satisfy 0 <= from <= to")
    if not math.isfinite(sampling_rate_hz) or sampling_rate_hz <= 0:
        rates = _numeric(source_pose, "nominal_sampling_rate_hz")
        finite_rates = rates[np.isfinite(rates) & (rates > 0)]
        if finite_rates.size:
            sampling_rate_hz = float(finite_rates[0])
        else:
            quality_times_for_rate = _numeric(quality_frames, "t_rel_ns")
            if quality_times_for_rate.size < 2:
                raise ValueError(f"{ALGORITHM_ID}: a registered Pose sampling rate is required")
            sampling_rate_hz = 1e9 / float(np.median(np.diff(quality_times_for_rate)))
    step_ns = int(round(1e9 / sampling_rate_hz))
    if step_ns <= 0:
        raise ValueError(f"{ALGORITHM_ID}: sampling rate does not resolve to nanoseconds")
    grid_origin = grid_origin_ns % step_ns
    first_tick = -((-(from_ns - grid_origin)) // step_ns)
    last_tick = (to_ns - grid_origin) // step_ns
    if last_tick < first_tick:
        raise ValueError(f"{ALGORITHM_ID}: selected range contains no cadence-grid frame")
    expected_count = int(last_tick - first_tick + 1)

    parameters = {
        "dataset_id": dataset_id,
        "session_id": session_id,
        "trial_id": trial_id,
        "stream_id": stream_id,
        "subject_id": subject_id,
        "from_ns": from_ns,
        "to_ns": to_ns,
        "landmark_name": landmark_name,
        "sampling_rate_hz": sampling_rate_hz,
        "grid_origin_ns": grid_origin,
        "body_anchor_landmark": "midHip",
        "source_checksums": dict(source_checksums),
        "input_series": {
            "pose.geometry": {
                "algorithm_id": "pose.translation_invariant_kinematics",
                "version": input_series_versions.get("pose.geometry"),
            },
            "pose.landmark": {
                "algorithm_id": "pose.landmark_kinematics",
                "version": input_series_versions.get("pose.landmark"),
            },
            "pose.quality": {
                "algorithm_id": "pose.analysis_quality",
                "version": input_series_versions.get("pose.quality"),
            },
            "pose.bilateral": (
                {
                    "algorithm_id": "pose.bilateral_geometry",
                    "version": input_series_versions.get("pose.bilateral"),
                }
                if bilateral_series is not None
                else None
            ),
            "pose.source": "canonical pose_joint_sample",
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
            "inclusive requested to_ns; only cadence ticks inside the selected range are counted"
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

    quality_times = _numeric(quality_frames, "t_rel_ns").astype(np.int64)
    quality_present = np.zeros(expected_count, dtype=bool)
    quality_available = np.zeros(expected_count, dtype=bool)
    quality_available_count = np.zeros(expected_count, dtype=np.float64)
    if quality_times.size:
        quality_indexes = np.rint(
            (quality_times - grid_origin).astype(np.float64) / step_ns
        ).astype(np.int64)
        inside = (quality_indexes >= first_tick) & (quality_indexes <= last_tick)
        aligned_times = grid_origin + quality_indexes * step_ns
        if np.any(np.abs(aligned_times - quality_times) > 1):
            raise ValueError(
                f"{ALGORITHM_ID}: quality frames are not aligned to the selected cadence grid"
            )
        quality_indexes = quality_indexes[inside] - first_tick
        if np.any(np.diff(quality_times[inside]) <= 0):
            raise ValueError(f"{ALGORITHM_ID}: quality frame times must be unique and increasing")
        present_values = _numeric(quality_frames, "any_pose_present")[inside]
        available_values = _numeric(quality_frames, "any_pose_available")[inside]
        available_counts = _numeric(quality_frames, "available_landmark_count")[inside]
        quality_present[quality_indexes] = present_values == 1
        quality_available[quality_indexes] = available_values == 1
        quality_available_count[quality_indexes] = available_counts
    add(
        "pose.range.coverage.any_pose_present",
        "Pose presence fraction in selected range",
        "1",
        float(np.mean(quality_present)),
        "Fraction of cadence-expected frames with at least one source Pose row in the exact "
        "range; ticks outside the subject's observed source span remain absent.",
    )
    add(
        "pose.range.coverage.any_usable_pose",
        "Usable Pose frame fraction in selected range",
        "1",
        float(np.mean(quality_available)),
        "Fraction of cadence-expected frames with at least one available finite landmark in "
        "the exact range.",
    )
    add(
        "pose.range.coverage.mean_available_landmarks",
        "Mean available landmark count in selected range",
        "1",
        float(np.mean(quality_available_count)),
        "Mean count of available finite source landmarks per cadence-expected frame in the "
        "exact range; absent ticks contribute zero.",
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
    source_times = _numeric(source_pose, "t_rel_ns").astype(np.int64)
    source_joints = _strings(source_pose, "joint_name")
    source_available = _numeric(source_pose, "is_available") == 1
    source_x = _numeric(source_pose, "x_m")
    source_y = _numeric(source_pose, "y_m")
    source_z = _numeric(source_pose, "z_m")
    source_valid_xyz = np.isfinite(source_x) & np.isfinite(source_y) & np.isfinite(source_z)
    landmark_available_in_range = np.zeros(expected_count, dtype=bool)
    anchor_available_in_range = np.zeros(expected_count, dtype=bool)
    if source_times.size:
        source_indexes = np.rint((source_times - grid_origin).astype(np.float64) / step_ns).astype(
            np.int64
        )
        source_inside = (
            (source_indexes >= first_tick)
            & (source_indexes <= last_tick)
            & np.asarray(
                [joint == landmark_name or joint == "midHip" for joint in source_joints],
                dtype=bool,
            )
            & source_available
            & source_valid_xyz
        )
        aligned_source_times = grid_origin + source_indexes * step_ns
        if np.any(np.abs(aligned_source_times[source_inside] - source_times[source_inside]) > 1):
            raise ValueError(
                f"{ALGORITHM_ID}: source landmarks are not aligned to the selected cadence grid"
            )
        landmark_rows = source_inside & np.asarray(
            [joint == landmark_name for joint in source_joints], dtype=bool
        )
        anchor_rows = source_inside & np.asarray(
            [joint == "midHip" for joint in source_joints], dtype=bool
        )
        landmark_available_in_range[source_indexes[landmark_rows] - first_tick] = True
        anchor_available_in_range[source_indexes[anchor_rows] - first_tick] = True
    landmark_available_in_range &= anchor_available_in_range
    add(
        f"pose.range.coverage.landmark.{landmark_name}",
        f"Available-frame fraction in selected range for {landmark_name}",
        "1",
        float(np.mean(landmark_available_in_range)),
        "Fraction of cadence-expected source ticks with the named landmark and body anchor "
        "available and finite; unobserved ticks count as unavailable.",
    )
    missing_runs = _runs(~landmark_available_in_range)
    dropout_durations_s = [float((stop - start) * step_ns / 1e9) for start, stop in missing_runs]
    add(
        f"pose.range.dropout_count.{landmark_name}",
        f"Source-unavailable interval count in selected range for {landmark_name}",
        "1",
        float(len(missing_runs)),
        "Number of contiguous cadence-grid intervals without a usable landmark observation "
        "in the selected range; no tracking-presence inference is made.",
    )
    add(
        f"pose.range.longest_dropout.{landmark_name}",
        f"Longest source-unavailable interval in selected range for {landmark_name}",
        "s",
        max(dropout_durations_s, default=0.0),
        "Longest contiguous unavailable cadence-grid interval in the exact range.",
    )
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
    source_errors = _numeric(source_pose, "error_m")
    source_in_range = (source_times >= from_ns) & (source_times <= to_ns)
    selected_error = source_errors[
        np.asarray([joint == landmark_name for joint in source_joints], dtype=bool)
        & source_available
        & np.isfinite(source_errors)
        & (source_errors >= 0)
        & source_in_range
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

    bilateral_pair = (
        "knee_included_angle"
        if landmark_name in {"lKnee", "rKnee"}
        else "hip_included_angle"
        if landmark_name in {"lHip", "rHip"}
        else None
    )
    if bilateral_series is not None and bilateral_pair is not None:
        left = _numeric(bilateral_series, f"left_{bilateral_pair}_rad")
        right = _numeric(bilateral_series, f"right_{bilateral_pair}_rad")
        difference = _numeric(bilateral_series, f"right_minus_left_{bilateral_pair}_rad")
        common = _numeric(bilateral_series, f"common_available_{bilateral_pair}") == 1
        common &= np.isfinite(left) & np.isfinite(right) & np.isfinite(difference)
        bilateral_times = _numeric(bilateral_series, "t_rel_ns").astype(np.int64)
        bilateral_indexes = np.rint(
            (bilateral_times - grid_origin).astype(np.float64) / step_ns
        ).astype(np.int64)
        bilateral_inside = (bilateral_indexes >= first_tick) & (bilateral_indexes <= last_tick)
        common_grid = np.zeros(expected_count, dtype=bool)
        common_grid[bilateral_indexes[bilateral_inside] - first_tick] = common[bilateral_inside]
        if np.any(common):
            common_difference = difference[common]
            add(
                f"pose.range.bilateral.coverage.{bilateral_pair}",
                f"Bilateral common-frame coverage in range for {bilateral_pair}",
                "1",
                float(np.mean(common_grid)),
                "Fraction of same-subject exact-time samples with both homologous geometric "
                "angles in the selected range.",
            )
            for statistic, value, description in (
                (
                    "mean_absolute",
                    float(np.mean(np.abs(common_difference))),
                    "Mean absolute right-minus-left geometric angle difference on exact common "
                    "samples.",
                ),
                (
                    "rms",
                    float(np.sqrt(np.mean(common_difference**2))),
                    "Root-mean-square right-minus-left geometric angle difference on exact "
                    "common samples.",
                ),
            ):
                add(
                    f"pose.range.bilateral.angle_difference_{statistic}.{bilateral_pair}",
                    f"Bilateral angle difference {statistic.replace('_', ' ')} in range for "
                    f"{bilateral_pair}",
                    "rad",
                    value,
                    description,
                )
            common_left = left[common]
            common_right = right[common]
            if (
                np.count_nonzero(common) >= 3
                and np.std(common_left) > 0
                and np.std(common_right) > 0
            ):
                correlation = float(np.corrcoef(common_left, common_right)[0, 1])
                if math.isfinite(correlation):
                    add(
                        f"pose.range.bilateral.waveform_correlation.{bilateral_pair}",
                        f"Bilateral waveform correlation in range for {bilateral_pair}",
                        "1",
                        correlation,
                        "Descriptive Pearson correlation on common exact-time samples; no "
                        "normative threshold.",
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
            "expected_frames": expected_count,
            "landmark_name": landmark_name,
            "metric_count": len(metrics),
            "series_inputs_are_exact": True,
            "display_reduction_used": False,
        },
    )


__all__ = ["ALGORITHM_ID", "ALGORITHM_VERSION", "ANGLE_BY_LANDMARK", "process_pose_range"]
