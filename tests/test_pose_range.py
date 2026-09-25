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
    dropouts = pa.table(
        {
            "entity_id": ["player-1"],
            "joint_name": ["lKnee"],
            "t_rel_ns": [40_000_000],
            "start_ns": [40_000_000],
            "end_ns_exclusive": [80_000_000],
            "missing_frames": [1],
            "duration_s": [0.04],
        }
    )
    source = pa.table(
        {
            "joint_name": ["lKnee"] * 4,
            "is_available": [True, True, False, True],
            "error_m": [0.01, 0.02, None, 0.04],
            "nominal_sampling_rate_hz": [25.0] * 4,
        }
    )
    return geometry, landmarks, quality, dropouts, source


def _run(*, from_ns: int = 0, to_ns: int = 120_000_000):
    geometry, landmarks, quality, dropouts, source = _inputs()
    return process_pose_range(
        dataset_id="skillcorner-opendata",
        session_id="match-1",
        trial_id="period-1",
        stream_id="pose-period-1",
        subject_id="player-1",
        from_ns=from_ns,
        to_ns=to_ns,
        landmark_name="lKnee",
        geometry=geometry,
        landmark_series=landmarks,
        quality_frames=quality,
        dropout_intervals=dropouts,
        source_pose=source,
        source_checksums={"pose.landmark_kinematics": "a" * 64},
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
    assert all(metric.session_id == "match-1" for metric in result.metrics)


def test_range_report_rejects_rows_outside_the_canonical_selection() -> None:
    with pytest.raises(ValueError, match="outside the requested range"):
        _run(from_ns=40_000_000, to_ns=80_000_000)
