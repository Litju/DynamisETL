"""Known-answer coverage, dropout, and provider-error summaries for Pose."""

from __future__ import annotations

import pyarrow as pa
import pytest

from dynamis.contracts import POSE_SCHEMA
from dynamis.processors.pose_quality import pose_quality_spec, process_pose_quality


def _quality_table(*, misaligned: bool = False, duplicate: bool = False) -> pa.Table:
    rows: list[dict[str, object]] = []
    times = [0, 40_000_000, 80_000_000, 160_000_000, 200_000_000, 240_000_000]
    for frame, timestamp in enumerate(times):
        if timestamp == 80_000_000:
            joint_rows = [("a", True, 0.03), ("b", False, None)]
        else:
            radius = [0.01, 0.02, 0.04, 0.05, 0.06][frame if frame < 2 else frame - 1]
            joint_rows = [("a", True, radius), ("b", True, radius + 0.01)]
        for joint, available, error in joint_rows:
            row: dict[str, object] = {
                "dataset_id": "skillcorner-opendata",
                "session_id": "session-1",
                "trial_id": "period-1",
                "subject_id": "player-1",
                "device_id": None,
                "stream_id": "pose-period-1",
                "sample_index": len(rows),
                "t_rel_ns": timestamp
                + (1_000_000 if misaligned and timestamp == 80_000_000 else 0),
                "timestamp_utc_ns": None,
                "nominal_sampling_rate_hz": 25.0,
                "measurement_class": "MODEL_ESTIMATED",
                "clock_id": "match-clock",
                "synchronization_spec_id": "source-clock",
                "coordinate_frame_id": "pose-hybrid-m",
                "skeleton_id": "test-skeleton",
                "joint_id": 0 if joint == "a" else 1,
                "joint_name": joint,
                "parent_joint_id": None,
                "is_available": available,
                "x_m": float(frame) if available else None,
                "y_m": 0.0 if available else None,
                "z_m": 0.1 if available else None,
                "confidence": None,
                "error_m": error,
                "is_occluded": None,
            }
            rows.append(row)
            if duplicate and timestamp == 0 and joint == "a":
                rows.append(dict(row, sample_index=len(rows)))
    return pa.Table.from_pylist(rows, schema=POSE_SCHEMA)


def _parameters() -> dict[str, object]:
    return {
        "expected_joint_names": ["a", "b"],
        "metric_requirements": {"two_point_metric": ["a", "b"]},
        "minimum_derivative_segment_frames": 3,
    }


def _value(result, metric_id: str) -> float:
    return next(
        metric.value for metric in result.metrics if metric.declaration.metric_id == metric_id
    )


def test_quality_uses_explicit_cadence_grid_and_preserves_dropout_gaps() -> None:
    result = process_pose_quality(_quality_table(), parameters=_parameters())
    metric_names = [metric.declaration.name for metric in result.metrics]
    assert len(metric_names) == len(set(metric_names))

    assert _value(result, "pose.quality.coverage.any_pose_present") == pytest.approx(6 / 7)
    assert _value(result, "pose.quality.coverage.any_usable_pose") == pytest.approx(6 / 7)
    assert _value(result, "pose.quality.availability.a") == pytest.approx(6 / 7)
    assert _value(result, "pose.quality.availability.b") == pytest.approx(5 / 7)
    assert _value(result, "pose.quality.dropout_count.b") == 1
    assert _value(result, "pose.quality.longest_dropout.b") == pytest.approx(0.08)
    assert _value(result, "pose.quality.coverage.metric.two_point_metric") == pytest.approx(5 / 7)
    assert _value(
        result, "pose.quality.derivative_eligible_fraction.two_point_metric"
    ) == pytest.approx(3 / 7)

    series = result.series[0].table
    assert series.column("t_rel_ns").to_pylist() == [
        0,
        40_000_000,
        80_000_000,
        120_000_000,
        160_000_000,
        200_000_000,
        240_000_000,
    ]
    assert series.column("any_pose_present").to_pylist() == [1, 1, 1, 0, 1, 1, 1]
    assert series.column("available_landmark_count").to_pylist() == [2, 2, 1, 0, 2, 2, 2]
    assert series.schema.metadata[b"dynamis.measurement_class"] == b"PIPELINE_DERIVED"
    dropouts = result.series[1].table
    b_mask = pa.array(
        [joint == "b" for joint in dropouts.column("joint_name").to_pylist()],
        type=pa.bool_(),
    )
    b_dropout = dropouts.filter(b_mask)
    assert b_dropout.column("start_ns").to_pylist() == [80_000_000]
    assert b_dropout.column("end_ns_exclusive").to_pylist() == [160_000_000]
    assert b_dropout.column("missing_frames").to_pylist() == [2]


def test_quality_keeps_provider_radius_distribution_labeled_as_source_evidence() -> None:
    result = process_pose_quality(_quality_table(), parameters=_parameters())

    mean = _value(result, "pose.quality.provider_error_radius_mean.a")
    median = _value(result, "pose.quality.provider_error_radius_median.a")
    p95 = _value(result, "pose.quality.provider_error_radius_p95.a")
    assert mean == pytest.approx((0.01 + 0.02 + 0.03 + 0.04 + 0.05 + 0.06) / 6)
    assert median == pytest.approx(0.035)
    assert p95 == pytest.approx(0.0575)
    metric = next(
        item
        for item in result.metrics
        if item.declaration.metric_id.endswith("provider_error_radius_p95.a")
    )
    assert "provider p90 predicted error-radius" in metric.declaration.description
    assert metric.provenance["sampling_rate_hz"] == 25.0
    assert metric.provenance["source_range_to_ns"] == 240_000_000


def test_quality_rejects_cadence_misalignment_and_duplicate_observations() -> None:
    with pytest.raises(ValueError, match="not aligned"):
        process_pose_quality(_quality_table(misaligned=True), parameters=_parameters())
    with pytest.raises(ValueError, match="duplicate subject/time/landmark"):
        process_pose_quality(_quality_table(duplicate=True), parameters=_parameters())


def test_quality_spec_rejects_unknown_landmarks_and_weak_derivative_segments() -> None:
    with pytest.raises(ValueError, match="unknown landmark"):
        pose_quality_spec({"expected_joint_names": ["a"], "metric_requirements": {"m": ["b"]}})
    with pytest.raises(ValueError, match="at least 2"):
        pose_quality_spec({"minimum_derivative_segment_frames": 1})
