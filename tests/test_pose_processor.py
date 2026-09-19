"""Known-answer tests for translation-invariant pose kinematics."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import pyarrow as pa
import pytest

from dynamis.contracts import POSE_SCHEMA
from dynamis.processors.pose import (
    ERROR_POLICY_WORST_CASE,
    pose_spec,
    process_pose,
)

DATASET_ID = "skillcorner-opendata"


def _pose_table(
    frames: Mapping[str, Sequence[tuple[float, float, float, bool, float | None]]],
    *,
    rate_hz: int = 25,
    subject_id: str = "SC-P1",
) -> pa.Table:
    """Build a canonical pose table: frames maps landmark -> per-frame values."""
    frame_count = len(next(iter(frames.values())))
    step_ns = 1_000_000_000 // rate_hz
    rows = []
    for frame in range(frame_count):
        for joint_id, (name, values) in enumerate(frames.items()):
            x, y, z, available, error = values[frame]
            rows.append(
                {
                    "dataset_id": DATASET_ID,
                    "session_id": "1925299",
                    "trial_id": "period_1",
                    "subject_id": subject_id,
                    "device_id": None,
                    "stream_id": "pose-period-1",
                    "sample_index": frame * len(frames) + joint_id,
                    "t_rel_ns": frame * step_ns,
                    "timestamp_utc_ns": None,
                    "nominal_sampling_rate_hz": float(rate_hz),
                    "measurement_class": "MODEL_ESTIMATED",
                    "clock_id": "skillcorner-match-clock",
                    "synchronization_spec_id": "skillcorner-source-provided-match-clock",
                    "coordinate_frame_id": "skillcorner-pose-hybrid-m",
                    "skeleton_id": "skillcorner-bodypose-29-landmarks",
                    "joint_id": joint_id,
                    "joint_name": name,
                    "parent_joint_id": None,
                    "is_available": available,
                    "x_m": x if available else None,
                    "y_m": y if available else None,
                    "z_m": z if available else None,
                    "confidence": None,
                    "error_m": error,
                    "is_occluded": None,
                }
            )
    batch = pa.RecordBatch.from_pylist(rows, schema=POSE_SCHEMA)
    return pa.Table.from_batches([batch])


def _geometry_parameters(*, error_policy: str = "none", edge: str = "nan") -> dict:
    return {
        "segments": [
            {
                "name": "left_thigh",
                "start_landmark": "lHip",
                "end_landmark": "lKnee",
            }
        ],
        "angles": [
            {
                "name": "left_knee",
                "vertex_landmark": "lKnee",
                "first_landmark": "lHip",
                "second_landmark": "lAnkle",
            }
        ],
        "error_policy": error_policy,
        "derivative": {"edge_policy": edge},
    }


def _metric(result, metric_id: str) -> float:
    for metric in result.metrics:
        if metric.declaration.metric_id == metric_id:
            return metric.value
    raise AssertionError(f"metric {metric_id} not found")


def _frames(hip, knee, ankle, *, available=(True, True, True), errors=(None, None, None)):
    return {
        "lHip": [(*hip, available[0], errors[0])],
        "lKnee": [(*knee, available[1], errors[1])],
        "lAnkle": [(*ankle, available[2], errors[2])],
    }


def test_segment_length_is_translation_invariant() -> None:
    knee = (0.0, 0.0, -0.45)
    table = _pose_table(_frames((0.0, 0.0, 0.0), knee, (0.0, 0.1, -0.85)))
    translated = _pose_table(
        _frames((123.0, -45.0, 8.0), (123.0, -45.0, 7.55), (123.0, -44.9, 7.15))
    )
    first = process_pose(table, parameters=_geometry_parameters())
    second = process_pose(translated, parameters=_geometry_parameters())
    assert _metric(first, "pose.segment_length_mean.left_thigh") == pytest.approx(0.45, rel=1e-12)
    assert _metric(second, "pose.segment_length_mean.left_thigh") == pytest.approx(0.45, rel=1e-12)


def test_three_point_angle_matches_known_geometry() -> None:
    # Vertex at origin; first along +x, second along +y -> 90 degrees.
    table = _pose_table(_frames((1.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)))
    result = process_pose(table, parameters=_geometry_parameters())
    # A single frame has no ROM or derivative; the angle itself is in the series.
    assert "pose.angular_rom.left_knee" not in {
        metric.declaration.metric_id for metric in result.metrics
    }
    angle = result.series[0].table.column("angle_left_knee_rad")[0].as_py()
    assert angle == pytest.approx(math.pi / 2, rel=1e-12)


def test_unavailable_landmark_yields_no_result() -> None:
    table = _pose_table(
        _frames(
            (0.0, 0.0, 0.0),
            (0.0, 0.0, -0.45),
            (0.0, 0.1, -0.85),
            available=(True, True, False),
        )
    )
    result = process_pose(table, parameters=_geometry_parameters())
    assert _metric(result, "pose.segment_length_mean.left_thigh") == pytest.approx(0.45)
    assert "pose.angular_rom.left_knee" not in {
        metric.declaration.metric_id for metric in result.metrics
    }
    series = result.series[0].table
    value = series.column("angle_left_knee_rad")[0].as_py()
    assert value is None or math.isnan(value)


def test_rom_and_angular_velocity_follow_the_angle_series() -> None:
    rate_hz = 25
    samples = 21
    omega = 1.5  # rad/s
    frames = {"lHip": [], "lKnee": [], "lAnkle": []}
    for index in range(samples):
        t = index / rate_hz
        theta = omega * t
        frames["lHip"].append((1.0, 0.0, 0.0, True, None))
        frames["lKnee"].append((0.0, 0.0, 0.0, True, None))
        frames["lAnkle"].append((math.cos(theta), math.sin(theta), 0.0, True, None))
    result = process_pose(
        _pose_table(frames, rate_hz=rate_hz),
        parameters=_geometry_parameters(edge="one_sided_first_order"),
    )
    duration = (samples - 1) / rate_hz
    assert _metric(result, "pose.angular_rom.left_knee") == pytest.approx(
        omega * duration, rel=1e-9
    )
    assert _metric(result, "pose.angular_velocity_peak.left_knee") == pytest.approx(omega, rel=1e-9)
    assert _metric(result, "pose.angular_velocity_rms.left_knee") == pytest.approx(omega, rel=1e-9)


def test_worst_case_error_bound_is_additive_and_opt_in() -> None:
    frames = {
        "lHip": [(0.0, 0.0, 0.0, True, 0.02)],
        "lKnee": [(0.0, 0.0, -0.45, True, 0.03)],
        "lAnkle": [(0.0, 0.1, -0.85, True, 0.01)],
    }
    table = _pose_table(frames)
    without = process_pose(table, parameters=_geometry_parameters())
    assert "pose.segment_length_error_bound.left_thigh" not in {
        metric.declaration.metric_id for metric in without.metrics
    }
    with_bound = process_pose(
        table, parameters=_geometry_parameters(error_policy=ERROR_POLICY_WORST_CASE)
    )
    assert _metric(with_bound, "pose.segment_length_error_bound.left_thigh") == pytest.approx(
        0.05, rel=1e-12
    )
    assert _metric(with_bound, "pose.error_radius_mean.lHip") == pytest.approx(0.02)


def test_scientific_boundary_conventions_are_enforced() -> None:
    with pytest.raises(ValueError, match="absolute_height_interpretation"):
        pose_spec(
            {
                "segments": [{"name": "s", "start_landmark": "a", "end_landmark": "b"}],
                "absolute_height_interpretation": "com_height_from_z",
            }
        )
    with pytest.raises(ValueError, match="parent_tree"):
        pose_spec(
            {
                "segments": [{"name": "s", "start_landmark": "a", "end_landmark": "b"}],
                "parent_tree_created": True,
            }
        )


def test_missing_required_landmark_is_rejected() -> None:
    table = _pose_table(_frames((0.0, 0.0, 0.0), (0.0, 0.0, -0.45), (0.0, 0.1, -0.85)))
    with pytest.raises(ValueError, match="not present"):
        process_pose(
            table,
            parameters={
                "segments": [{"name": "x", "start_landmark": "lHip", "end_landmark": "nose"}],
                "angles": [],
            },
        )


def test_processor_is_deterministic() -> None:
    frames = {
        "lHip": [(0.0, 0.0, 0.0, True, None)] * 5,
        "lKnee": [(0.0, 0.0, -0.45, True, None)] * 5,
        "lAnkle": [(0.0, 0.02 * index, -0.85, True, None) for index in range(5)],
    }
    table = _pose_table(frames)
    first = process_pose(table, parameters=_geometry_parameters(edge="one_sided_first_order"))
    second = process_pose(table, parameters=_geometry_parameters(edge="one_sided_first_order"))
    assert first.series[0].table.equals(second.series[0].table)
    assert [metric.value for metric in first.metrics] == [metric.value for metric in second.metrics]
