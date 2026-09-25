"""Known-answer relative Pose position, path, speed, and acceleration tests."""

from __future__ import annotations

import pyarrow as pa
import pytest

from dynamis.contracts import POSE_SCHEMA
from dynamis.processors.pose_landmark import pose_landmark_spec, process_pose_landmark_kinematics


def _table(
    positions: list[float],
    *,
    times_ns: list[int] | None = None,
    provider_error_m: float = 0.02,
    available: bool = True,
) -> pa.Table:
    timestamps = (
        times_ns
        if times_ns is not None
        else [index * 40_000_000 for index in range(len(positions))]
    )
    rows: list[dict[str, object]] = []
    for index, (timestamp, relative_x) in enumerate(zip(timestamps, positions, strict=True)):
        root_x = 100.0 + index * 10.0
        for joint_id, (name, x) in enumerate((("midHip", root_x), ("lKnee", root_x + relative_x))):
            rows.append(
                {
                    "dataset_id": "skillcorner-opendata",
                    "session_id": "match-1",
                    "trial_id": "period-1",
                    "subject_id": "player-1",
                    "device_id": None,
                    "stream_id": "pose-period-1",
                    "sample_index": len(rows),
                    "t_rel_ns": timestamp,
                    "timestamp_utc_ns": None,
                    "nominal_sampling_rate_hz": 25.0,
                    "measurement_class": "MODEL_ESTIMATED",
                    "clock_id": "match-clock",
                    "synchronization_spec_id": "source-clock",
                    "coordinate_frame_id": "pose-hybrid-m",
                    "skeleton_id": "test-skeleton",
                    "joint_id": joint_id,
                    "joint_name": name,
                    "parent_joint_id": None,
                    "is_available": available,
                    "x_m": x if available else None,
                    "y_m": 0.0 if available else None,
                    "z_m": 0.2 if available else None,
                    "confidence": None,
                    "error_m": provider_error_m if available else None,
                    "is_occluded": None,
                }
            )
    return pa.Table.from_pylist(rows, schema=POSE_SCHEMA)


def _parameters(**updates: object) -> dict[str, object]:
    return {
        "landmark_names": ["lKnee"],
        "body_anchor_landmark": "midHip",
        "derivative": {"edge_policy": "one_sided_first_order"},
        **updates,
    }


def _value(result, metric_id: str) -> float:
    return next(
        metric.value for metric in result.metrics if metric.declaration.metric_id == metric_id
    )


def test_relative_kinematics_cancel_global_translation_and_report_path_and_speed() -> None:
    relative_positions = [0.5, 0.54, 0.58, 0.62]
    result = process_pose_landmark_kinematics(_table(relative_positions), parameters=_parameters())

    assert _value(result, "pose.landmark.coverage.lKnee") == 1.0
    assert _value(result, "pose.landmark.displacement_from_range_start.lKnee") == pytest.approx(
        0.12
    )
    assert _value(result, "pose.landmark.path_length.lKnee") == pytest.approx(0.12)
    assert _value(result, "pose.landmark.speed_mean.lKnee") == pytest.approx(1.0)
    assert _value(result, "pose.landmark.speed_peak.lKnee") == pytest.approx(1.0)
    series = result.series[0].table
    assert series.column("relative_position_x_lKnee_m").to_pylist() == pytest.approx(
        relative_positions
    )
    assert series.column("displacement_from_range_start_lKnee_m").to_pylist() == pytest.approx(
        [0.0, 0.04, 0.08, 0.12]
    )


def test_landmark_derivative_and_path_reset_at_explicit_source_time_gap() -> None:
    result = process_pose_landmark_kinematics(
        _table(
            [0.5, 0.54, 1.0, 1.04],
            times_ns=[0, 40_000_000, 160_000_000, 200_000_000],
        ),
        parameters=_parameters(),
    )
    series = result.series[0].table
    assert series.column("temporal_segment_index").to_pylist() == [0, 0, 1, 1]
    assert series.column("path_length_lKnee_m").to_pylist() == pytest.approx([0.0, 0.04, 0.0, 0.04])
    assert series.column("body_relative_speed_lKnee_m_s").to_pylist() == pytest.approx([1.0] * 4)
    assert _value(result, "pose.landmark.path_length.lKnee") == pytest.approx(0.08)


def test_acceleration_is_disabled_by_default_and_requires_radius_and_segment_gates() -> None:
    positions = [0.5 + (index * 0.04) ** 2 for index in range(6)]
    table = _table(positions)
    default = process_pose_landmark_kinematics(table, parameters=_parameters())
    assert "pose.landmark.acceleration_peak.lKnee" not in {
        metric.declaration.metric_id for metric in default.metrics
    }

    enabled = process_pose_landmark_kinematics(
        table,
        parameters=_parameters(
            acceleration={
                "enabled": True,
                "maximum_provider_error_radius_m": 0.05,
                "minimum_segment_frames": 5,
            }
        ),
    )
    assert _value(enabled, "pose.landmark.acceleration_peak.lKnee") == pytest.approx(2.0, abs=1e-9)

    gated = process_pose_landmark_kinematics(
        _table(positions, provider_error_m=0.2),
        parameters=_parameters(
            acceleration={
                "enabled": True,
                "maximum_provider_error_radius_m": 0.05,
                "minimum_segment_frames": 5,
            }
        ),
    )
    assert "pose.landmark.acceleration_peak.lKnee" not in {
        metric.declaration.metric_id for metric in gated.metrics
    }


def test_acceleration_configuration_fails_closed_without_provider_radius_gate() -> None:
    with pytest.raises(ValueError, match="maximum_provider_error_radius_m"):
        pose_landmark_spec(
            {
                "landmark_names": ["lKnee"],
                "acceleration": {"enabled": True, "minimum_segment_frames": 11},
            }
        )
