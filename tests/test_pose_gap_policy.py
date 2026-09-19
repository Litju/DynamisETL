"""Pose angular velocity must never differentiate across an observation gap.

Provider/model pose is observation-limited: a subject may disappear and later
resume. The locked V1 policy splits observed frames into contiguous temporal
segments, restarts filter/derivative state at every boundary and never
interpolates. These tests pin the gap policy, its visible provenance and the
absence of cross-gap differences.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import pyarrow as pa
import pytest

from dynamis.contracts import POSE_SCHEMA
from dynamis.processors.pose import (
    DEFAULT_MAX_GAP_FACTOR,
    GAP_POLICY_CONTIGUOUS_SEGMENTS,
    pose_spec,
    process_pose,
)

DATASET_ID = "skillcorner-opendata"
RATE_HZ = 25
STEP_NS = 1_000_000_000 // RATE_HZ


def _pose_table(
    frames: Mapping[str, Sequence[tuple[float, float, float, bool, float | None]]],
    *,
    times_ns: Sequence[int],
    rate_hz: int = RATE_HZ,
) -> pa.Table:
    rows = []
    for frame, t_rel_ns in enumerate(times_ns):
        for joint_id, (name, values) in enumerate(frames.items()):
            x, y, z, available, error = values[frame]
            rows.append(
                {
                    "dataset_id": DATASET_ID,
                    "session_id": "1925299",
                    "trial_id": "period_1",
                    "subject_id": "SC-P1",
                    "device_id": None,
                    "stream_id": "pose-period-1",
                    "sample_index": frame * len(frames) + joint_id,
                    "t_rel_ns": int(t_rel_ns),
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


def _angle_frames(theta: Sequence[float]) -> dict[str, list[tuple]]:
    return {
        "lHip": [(1.0, 0.0, 0.0, True, None)] * len(theta),
        "lKnee": [(0.0, 0.0, 0.0, True, None)] * len(theta),
        "lAnkle": [(math.cos(value), math.sin(value), 0.0, True, None) for value in theta],
    }


def _parameters(*, edge: str = "one_sided_first_order") -> dict:
    return {
        "angles": [
            {
                "name": "left_knee",
                "vertex_landmark": "lKnee",
                "first_landmark": "lHip",
                "second_landmark": "lAnkle",
            }
        ],
        "derivative": {"edge_policy": edge},
    }


def _metric(result, metric_id: str) -> float:
    for metric in result.metrics:
        if metric.declaration.metric_id == metric_id:
            return metric.value
    raise AssertionError(f"metric {metric_id} not found")


def test_gap_splits_segments_and_never_bridges_a_derivative() -> None:
    # Two contiguous blocks of three frames with an observation gap between
    # them; the true angle restarts with a 2 rad offset after the gap.
    times_ns = [0, STEP_NS, 2 * STEP_NS, 4 * STEP_NS, 5 * STEP_NS, 6 * STEP_NS]
    theta = [0.04 * i for i in range(3)] + [2.04 + 0.04 * i for i in range(3)]
    result = process_pose(
        _pose_table(_angle_frames(theta), times_ns=times_ns),
        parameters=_parameters(),
    )
    series = result.series[0].table
    assert series.column("segment_index").to_pylist() == [0, 0, 0, 1, 1, 1]
    velocity = series.column("angular_velocity_left_knee_rad_s").to_pylist()
    # Every within-segment difference is exactly 1 rad/s; a cross-gap central
    # difference at the boundary would report roughly 17.7 rad/s.
    assert all(value == pytest.approx(1.0, rel=1e-9) for value in velocity)
    assert _metric(result, "pose.angular_velocity_peak.left_knee") == pytest.approx(1.0, rel=1e-9)


def test_gap_policy_is_exposed_in_parameters_provenance_and_diagnostics() -> None:
    times_ns = [0, STEP_NS, 2 * STEP_NS, 4 * STEP_NS, 5 * STEP_NS, 6 * STEP_NS]
    result = process_pose(
        _pose_table(_angle_frames([0.0, 0.04, 0.08, 1.0, 1.04, 1.08]), times_ns=times_ns),
        parameters=_parameters(),
    )
    spec = pose_spec(_parameters())
    assert spec.parameters["gap_policy"] == {
        "strategy": GAP_POLICY_CONTIGUOUS_SEGMENTS,
        "max_gap_factor": DEFAULT_MAX_GAP_FACTOR,
    }
    diagnostics = dict(result.diagnostics)
    assert diagnostics["gap_policy"]["strategy"] == GAP_POLICY_CONTIGUOUS_SEGMENTS
    for metric in result.metrics:
        gap_policy = metric.provenance["gap_policy"]
        assert gap_policy["pose_segments"] == 2
        assert gap_policy["max_gap_factor"] == DEFAULT_MAX_GAP_FACTOR
        assert "no derivative is taken across a gap" in gap_policy["semantics"]


def test_uniform_series_is_one_segment_with_finite_velocity() -> None:
    times_ns = [STEP_NS * index for index in range(8)]
    result = process_pose(
        _pose_table(_angle_frames([0.04 * index for index in range(8)]), times_ns=times_ns),
        parameters=_parameters(),
    )
    series = result.series[0].table
    assert series.column("segment_index").to_pylist() == [0] * 8
    for value in series.column("angular_velocity_left_knee_rad_s").to_pylist():
        assert value == pytest.approx(1.0, rel=1e-9)


def test_gap_policy_configuration_is_locked_and_validated() -> None:
    with pytest.raises(ValueError, match="gap_policy.strategy"):
        pose_spec(
            {
                **_parameters(),
                "gap_policy": {"strategy": "interpolate", "max_gap_factor": 1.5},
            }
        )
    with pytest.raises(ValueError, match="max_gap_factor"):
        pose_spec(
            {
                **_parameters(),
                "gap_policy": {"strategy": GAP_POLICY_CONTIGUOUS_SEGMENTS, "max_gap_factor": 0.5},
            }
        )
    spec = pose_spec(_parameters())
    assert spec.parameters["gap_policy"]["max_gap_factor"] == DEFAULT_MAX_GAP_FACTOR
