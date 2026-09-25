"""Known-answer bilateral geometry using same-subject exact-time samples."""

from __future__ import annotations

import math

import pyarrow as pa
import pytest

from dynamis.contracts import POSE_SCHEMA
from dynamis.processors.pose_bilateral import pose_bilateral_spec, process_pose_bilateral


def _table(*, unavailable_right_angle_frame: int | None = None) -> pa.Table:
    left_degrees = [40.0, 60.0, 90.0, 135.0]
    right_degrees = [55.0, 90.0, 120.0, 150.0]
    rows: list[dict[str, object]] = []
    landmarks = (
        ("lHip", "left", "first"),
        ("lKnee", "left", "vertex"),
        ("lAnkle", "left", "second"),
        ("rHip", "right", "first"),
        ("rKnee", "right", "vertex"),
        ("rAnkle", "right", "second"),
    )
    for frame in range(4):
        for joint, side, role in landmarks:
            angle = left_degrees[frame] if side == "left" else right_degrees[frame]
            if role == "vertex":
                x, y, z = 0.0, 0.0, 0.0
            elif role == "first":
                x, y, z = 1.0, 0.0, 0.0
            else:
                radians = math.radians(angle)
                x, y, z = math.cos(radians), math.sin(radians), 0.0
            available = not (unavailable_right_angle_frame == frame and joint == "rAnkle")
            rows.append(
                {
                    "dataset_id": "skillcorner-opendata",
                    "session_id": "match-1",
                    "trial_id": "period-1",
                    "subject_id": "player-1",
                    "device_id": None,
                    "stream_id": "pose-period-1",
                    "sample_index": len(rows),
                    "t_rel_ns": frame * 40_000_000,
                    "timestamp_utc_ns": None,
                    "nominal_sampling_rate_hz": 25.0,
                    "measurement_class": "MODEL_ESTIMATED",
                    "clock_id": "match-clock",
                    "synchronization_spec_id": "source-clock",
                    "coordinate_frame_id": "pose-hybrid-m",
                    "skeleton_id": "test-skeleton",
                    "joint_id": len(rows) % len(landmarks),
                    "joint_name": joint,
                    "parent_joint_id": None,
                    "is_available": available,
                    "x_m": x if available else None,
                    "y_m": y if available else None,
                    "z_m": z if available else None,
                    "confidence": None,
                    "error_m": 0.02 if available else None,
                    "is_occluded": None,
                }
            )
    return pa.Table.from_pylist(rows, schema=POSE_SCHEMA)


def _parameters() -> dict[str, object]:
    return {
        "angles": [
            {
                "name": "left_knee",
                "vertex_landmark": "lKnee",
                "first_landmark": "lHip",
                "second_landmark": "lAnkle",
            },
            {
                "name": "right_knee",
                "vertex_landmark": "rKnee",
                "first_landmark": "rHip",
                "second_landmark": "rAnkle",
            },
        ],
        "angle_pairs": [{"name": "knee", "left_angle": "left_knee", "right_angle": "right_knee"}],
    }


def _value(result, metric_id: str) -> float:
    return next(
        metric.value for metric in result.metrics if metric.declaration.metric_id == metric_id
    )


def test_bilateral_difference_uses_right_minus_left_at_exact_subject_times() -> None:
    result = process_pose_bilateral(_table(), parameters=_parameters())

    assert _value(result, "pose.bilateral.coverage.knee") == 1.0
    assert _value(result, "pose.bilateral.angle_difference_mean.knee") == pytest.approx(
        math.radians(22.5), abs=1e-12
    )
    assert _value(result, "pose.bilateral.angle_difference_mean_absolute.knee") == pytest.approx(
        math.radians(22.5), abs=1e-12
    )
    assert _value(result, "pose.bilateral.angle_difference_range.knee") == pytest.approx(
        math.radians(15.0), abs=1e-12
    )
    assert _value(result, "pose.bilateral.maximum_angle_time_offset.knee") == 0.0
    assert _value(result, "pose.bilateral.waveform_correlation.knee") > 0.95
    series = result.series[0].table
    assert series.column("t_rel_ns").to_pylist() == [0, 40_000_000, 80_000_000, 120_000_000]
    assert series.column("common_available_knee").to_pylist() == [1, 1, 1, 1]
    assert series.column("right_minus_left_knee_rad").to_pylist() == pytest.approx(
        [math.radians(value) for value in (15.0, 30.0, 30.0, 15.0)]
    )


def test_bilateral_quality_uses_common_frames_and_fails_closed_on_no_common_data() -> None:
    result = process_pose_bilateral(
        _table(unavailable_right_angle_frame=1),
        parameters=_parameters(),
    )
    assert _value(result, "pose.bilateral.coverage.knee") == pytest.approx(0.75)
    series = result.series[0].table
    assert series.column("common_available_knee").to_pylist() == [1, 0, 1, 1]


def test_bilateral_contract_rejects_undefined_or_self_pairs() -> None:
    with pytest.raises(ValueError, match="at least one bilateral angle pair"):
        pose_bilateral_spec({"angles": _parameters()["angles"], "angle_pairs": []})
    with pytest.raises(ValueError, match="distinct defined angles"):
        pose_bilateral_spec(
            {
                "angles": _parameters()["angles"],
                "angle_pairs": [
                    {"name": "bad", "left_angle": "left_knee", "right_angle": "left_knee"}
                ],
            }
        )
