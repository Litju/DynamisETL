"""Exact-range reports aggregate exact versioned Pose processor samples."""

from __future__ import annotations

import pyarrow as pa
import pytest

from dynamis.processors.pose_range import ALGORITHM_ID, process_pose_range


def _inputs():
    times = [0, 40_000_000, 80_000_000, 120_000_000]
    geometry = pa.table(
        {
            "entity_id": ["player-1"] * 4,
            "t_rel_ns": times,
            "angle_left_knee_rad": [0.5, 1.0, float("nan"), 1.5],
            "angular_velocity_left_knee_rad_s": [1.0, 0.5, float("nan"), 1.0],
        }
    )
    landmarks = pa.table(
        {
            "entity_id": ["player-1"] * 4,
            "t_rel_ns": times,
            "temporal_segment_index": [0, 0, 0, 0],
            "available_lKnee": [1, 1, 0, 1],
            "relative_position_x_lKnee_m": [0.0, 0.04, float("nan"), 0.12],
            "relative_position_y_lKnee_m": [0.0, 0.0, float("nan"), 0.0],
            "relative_position_z_lKnee_m": [0.0, 0.0, float("nan"), 0.0],
            "body_relative_speed_lKnee_m_s": [1.0, 1.0, float("nan"), 1.0],
        }
    )
    quality = pa.table(
        {
            "entity_id": ["player-1"] * 4,
            "t_rel_ns": times,
            "any_pose_present": [1, 1, 1, 1],
            "any_pose_available": [1, 1, 1, 1],
            "available_landmark_count": [2, 2, 1, 2],
            "expected_landmark_count": [2, 2, 2, 2],
        }
    )
    source_joints = [name for _time in times for name in ("midHip", "lKnee")]
    source_times = [time for time in times for _name in ("midHip", "lKnee")]
    source_knee_available = [True, True, False, True]
    source = pa.table(
        {
            "t_rel_ns": source_times,
            "joint_name": source_joints,
            "is_available": [
                flag for available in source_knee_available for flag in (True, available)
            ],
            "x_m": [
                0.0 if name == "midHip" else relative
                for relative, name in zip(
                    [position for position in (0.0, 0.04, 0.08, 0.12) for _ in range(2)],
                    source_joints,
                    strict=True,
                )
            ],
            "y_m": [0.0] * 8,
            "z_m": [0.0] * 8,
            "error_m": [radius for radius in (0.01, 0.01, 0.02, 0.02, 0.01, None, 0.01, 0.04)],
            "nominal_sampling_rate_hz": [25.0] * 8,
        }
    )
    bilateral = pa.table(
        {
            "entity_id": ["player-1"] * 4,
            "t_rel_ns": times,
            "left_knee_included_angle_rad": [0.5, 0.7, 0.9, 1.1],
            "right_knee_included_angle_rad": [0.6, 0.9, float("nan"), 1.2],
            "right_minus_left_knee_included_angle_rad": [0.1, 0.2, float("nan"), 0.1],
            "common_available_knee_included_angle": [1, 1, 0, 1],
        }
    )
    return geometry, landmarks, quality, source, bilateral


def _run(*, from_ns: int = 0, to_ns: int = 120_000_000):
    geometry, landmarks, quality, source, bilateral = _inputs()
    return process_pose_range(
        dataset_id="skillcorner-opendata",
        session_id="match-1",
        trial_id="period-1",
        stream_id="pose-period-1",
        subject_id="player-1",
        from_ns=from_ns,
        to_ns=to_ns,
        landmark_name="lKnee",
        sampling_rate_hz=25.0,
        grid_origin_ns=0,
        geometry=geometry,
        landmark_series=landmarks,
        quality_frames=quality,
        bilateral_series=bilateral,
        source_pose=source,
        source_checksums={"pose.landmark_kinematics": "a" * 64},
        input_series_versions={
            "pose.geometry": "1.0.0",
            "pose.landmark": "1.0.0",
            "pose.quality": "1.1.0",
            "pose.bilateral": "1.1.0",
        },
    )


def _value(result, metric_id: str) -> float:
    return next(
        metric.value for metric in result.metrics if metric.declaration.metric_id == metric_id
    )


def test_range_report_summarizes_exact_gapped_processor_and_source_series() -> None:
    result = _run()

    assert result.spec.algorithm_id == ALGORITHM_ID
    assert result.diagnostics["series_inputs_are_exact"] is True
    assert _value(result, "pose.range.coverage.any_pose_present") == 1.0
    assert _value(result, "pose.range.coverage.landmark.lKnee") == pytest.approx(0.75)
    assert _value(result, "pose.range.dropout_count.lKnee") == 1.0
    assert _value(result, "pose.range.longest_dropout.lKnee") == pytest.approx(0.04)
    assert _value(result, "pose.range.landmark.displacement.lKnee") == pytest.approx(0.12)
    assert _value(result, "pose.range.landmark.path_length.lKnee") == pytest.approx(0.04)
    assert _value(result, "pose.range.landmark.speed_mean.lKnee") == 1.0
    assert _value(result, "pose.range.angle_rom.left_knee") == pytest.approx(1.0)
    assert _value(result, "pose.range.angular_velocity_peak.left_knee") == 1.0
    assert _value(result, "pose.range.provider_error_radius_p95.lKnee") == pytest.approx(0.038)
    assert _value(result, "pose.range.bilateral.coverage.knee_included_angle") == pytest.approx(
        0.75
    )
    assert _value(
        result,
        "pose.range.bilateral.angle_difference_mean_absolute.knee_included_angle",
    ) == pytest.approx(0.4 / 3)
    assert all(metric.session_id == "match-1" for metric in result.metrics)


def test_range_report_rejects_rows_outside_the_canonical_selection() -> None:
    with pytest.raises(ValueError, match="outside the requested range"):
        _run(from_ns=40_000_000, to_ns=80_000_000)


def test_range_report_counts_cadence_ticks_outside_pose_observation_span() -> None:
    result = _run(to_ns=160_000_000)

    assert result.diagnostics["expected_frames"] == 5
    assert _value(result, "pose.range.coverage.any_pose_present") == pytest.approx(4 / 5)
    assert _value(result, "pose.range.coverage.landmark.lKnee") == pytest.approx(3 / 5)
    assert _value(result, "pose.range.dropout_count.lKnee") == 2
