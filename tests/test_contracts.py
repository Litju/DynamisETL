"""Canonical vocabulary and contract invariants."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from dynamis.contracts import (
    AlgorithmKind,
    AlgorithmSpec,
    ArtifactFormat,
    ArtifactLayer,
    Clock,
    Compression,
    CoordinateFrame,
    DerivedMetric,
    FrameKind,
    Handedness,
    LicensePolicy,
    LicenseStatus,
    MeasurementClass,
    MetricDefinition,
    Modality,
    ProcessingStatus,
    QualityIssue,
    RedistributionPolicy,
    SampleArtifact,
    Severity,
    SynchronizationMethod,
    Timebase,
    make_stream_id,
)

VALID_SHA = "a" * 64
VALID_GIT_SHA = "b" * 40


def test_measurement_class_is_exactly_the_four_declared_values() -> None:
    assert [member.value for member in MeasurementClass] == [
        "RAW_MEASURED",
        "SOURCE_DERIVED",
        "PIPELINE_DERIVED",
        "MODEL_ESTIMATED",
    ]


def test_modality_covers_required_v1_modalities() -> None:
    values = {member.value for member in Modality}
    assert {"gnss", "imu", "force", "lpt", "tracking", "event", "pose"} <= values
    assert values == {"gnss", "imu", "force", "lpt", "tracking", "event", "pose"}


def test_stream_id_is_deterministic_and_rejects_negative_ordinals() -> None:
    assert make_stream_id(Modality.GNSS, 1) == "gnss-00000001"
    assert make_stream_id(Modality.POSE, 42) == "pose-00000042"
    with pytest.raises(ValueError):
        make_stream_id(Modality.IMU, -1)


# ---------------------------------------------------------------------------
# Rights
# ---------------------------------------------------------------------------


def _policy(**overrides: object) -> LicensePolicy:
    base: dict[str, object] = {
        "identifier": "CC-BY-4.0",
        "status": LicenseStatus.DECLARED,
        "attribution_required": True,
        "noncommercial_only": False,
        "share_alike": False,
        "redistribution": RedistributionPolicy.CONDITIONAL,
        "local_only": False,
        "restrictions": ("Attribution required.",),
    }
    base.update(overrides)
    return LicensePolicy.model_validate(base)


def test_unclear_rights_are_local_only_and_prohibit_redistribution() -> None:
    policy = _policy(
        identifier=None,
        status=LicenseStatus.UNCLEAR,
        redistribution=RedistributionPolicy.PROHIBITED,
        local_only=True,
    )
    assert policy.policy_id.startswith("lic-")

    with pytest.raises(ValidationError):
        _policy(status=LicenseStatus.UNCLEAR)
    with pytest.raises(ValidationError):
        _policy(
            status=LicenseStatus.UNCLEAR,
            redistribution=RedistributionPolicy.CONDITIONAL,
            local_only=True,
        )
    with pytest.raises(ValidationError):
        _policy(
            status=LicenseStatus.UNCLEAR,
            redistribution=RedistributionPolicy.PROHIBITED,
            local_only=False,
        )


def test_declared_rights_require_identifier_and_respect_nc_sa() -> None:
    with pytest.raises(ValidationError):
        _policy(identifier=None)
    with pytest.raises(ValidationError):
        _policy(identifier="CC-BY-NC-SA-4.0", noncommercial_only=False)
    with pytest.raises(ValidationError):
        _policy(identifier="CC-BY-NC-SA-4.0", noncommercial_only=True, share_alike=False)
    assert _policy(identifier="CC-BY-NC-SA-4.0", noncommercial_only=True, share_alike=True)


def test_local_only_implies_prohibited_redistribution() -> None:
    with pytest.raises(ValidationError):
        _policy(local_only=True, redistribution=RedistributionPolicy.CONDITIONAL)


def test_policy_id_is_content_addressed() -> None:
    assert _policy().policy_id == _policy().policy_id
    assert _policy().policy_id != _policy(identifier="MIT").policy_id


# ---------------------------------------------------------------------------
# Processing and provenance
# ---------------------------------------------------------------------------


def _algorithm(**overrides: object) -> AlgorithmSpec:
    base: dict[str, object] = {
        "algorithm_id": "alg-cmj-onset",
        "name": "CMJ onset detection",
        "version": "1.0.0",
        "kind": AlgorithmKind.PROCESSOR,
    }
    base.update(overrides)
    return AlgorithmSpec.model_validate(base)


def test_algorithm_parameters_require_a_hash() -> None:
    assert _algorithm().parameters_hash is None
    with pytest.raises(ValidationError):
        _algorithm(parameters={"threshold_n": 20.0})


def _processing_input() -> dict[str, str]:
    return {"artifact_id": "art-1", "checksum_sha256": VALID_SHA, "role": "input"}


def test_derived_metric_binds_inputs_and_exactly_one_value_form() -> None:
    common: dict[str, object] = {
        "derived_metric_id": "dm-1",
        "dataset_id": "synthetic-foundation",
        "metric_id": "metric-jump-height",
        "run_id": "run-1",
        "si_unit": "m",
        "measurement_class": MeasurementClass.PIPELINE_DERIVED,
        "computed_at": "2026-09-17T12:00:00+00:00",
        "inputs": (_processing_input(),),
    }
    metric = DerivedMetric.model_validate({**common, "value_num": 0.42})
    assert metric.input_checksums == (VALID_SHA,)

    with pytest.raises(ValidationError):
        DerivedMetric.model_validate(common)
    with pytest.raises(ValidationError):
        DerivedMetric.model_validate({**common, "value_num": 0.42, "value_json": {"a": 1}})
    with pytest.raises(ValidationError):
        DerivedMetric.model_validate({**common, "value_num": 0.42, "inputs": ()})
    with pytest.raises(ValidationError):
        DerivedMetric.model_validate(
            {
                **common,
                "value_num": 0.42,
                "si_unit": "furlong",
            }
        )
    with pytest.raises(ValidationError):
        DerivedMetric.model_validate(
            {
                **common,
                "value_num": 0.42,
                "measurement_class": MeasurementClass.RAW_MEASURED,
            }
        )


def test_metric_definition_cannot_be_raw_measured() -> None:
    with pytest.raises(ValidationError):
        MetricDefinition(
            metric_id="m1",
            name="bad",
            si_unit="m",
            measurement_class=MeasurementClass.RAW_MEASURED,
        )
    with pytest.raises(ValidationError):
        MetricDefinition(
            metric_id="m2",
            name="bad unit",
            si_unit="furlong",
            measurement_class=MeasurementClass.PIPELINE_DERIVED,
        )
    assert MetricDefinition(
        metric_id="m3",
        name="Peak vertical force",
        si_unit="N",
        measurement_class=MeasurementClass.PIPELINE_DERIVED,
    )


def test_quality_issue_requires_evidence_and_location() -> None:
    base: dict[str, object] = {
        "issue_id": "qi-1",
        "dataset_id": "synthetic-foundation",
        "rule": "time.monotonic",
        "severity": Severity.ERROR,
    }
    with pytest.raises(ValidationError):
        QualityIssue.model_validate(base)
    with pytest.raises(ValidationError):
        QualityIssue.model_validate({**base, "evidence": {"detail": "x"}})
    located = QualityIssue.model_validate(
        {**base, "evidence": {"detail": "x"}, "stream_id": "gnss-00000001"}
    )
    assert located.state.value == "QUARANTINED"
    with pytest.raises(ValidationError):
        QualityIssue.model_validate(
            {
                **base,
                "severity": Severity.INFO,
                "evidence": {"detail": "x"},
                "stream_id": "gnss-00000001",
            }
        )


def test_processing_run_status_and_time_order() -> None:
    from dynamis.contracts import ProcessingRun

    base: dict[str, object] = {
        "run_id": "run-1",
        "dataset_id": "synthetic-foundation",
        "algorithm_id": "alg-cmj-onset",
        "inputs": (_processing_input(),),
    }
    with pytest.raises(ValidationError):
        ProcessingRun.model_validate({**base, "status": ProcessingStatus.COMPLETED})
    run = ProcessingRun.model_validate(
        {
            **base,
            "status": ProcessingStatus.COMPLETED,
            "started_at": "2026-09-17T12:00:00+00:00",
            "completed_at": "2026-09-17T12:00:01+00:00",
        }
    )
    assert run.status is ProcessingStatus.COMPLETED
    assert ProcessingRun.new_run_id().startswith("run-")


def test_sample_artifact_is_parquet_first() -> None:
    base: dict[str, object] = {
        "artifact_id": "art-1",
        "dataset_id": "synthetic-foundation",
        "session_id": "syn-session-0001",
        "stream_id": "gnss-00000001",
        "layer": ArtifactLayer.SILVER,
        "relative_path": "silver/dataset_id=x/part.parquet",
        "row_count": 10,
        "byte_size": 1024,
        "checksum_sha256": VALID_SHA,
        "schema_version": "1",
    }
    artifact = SampleArtifact.model_validate(base)
    assert artifact.compression is Compression.ZSTD

    with pytest.raises(ValidationError):
        SampleArtifact.model_validate(
            {**base, "format": ArtifactFormat.PARQUET, "compression": Compression.SNAPPY}
        )
    with pytest.raises(ValidationError):
        SampleArtifact.model_validate({**base, "layer": ArtifactLayer.GOLD})


# ---------------------------------------------------------------------------
# Time and synchronization
# ---------------------------------------------------------------------------


def test_clock_rejects_epoch_on_monotonic_timebases() -> None:
    with pytest.raises(ValidationError):
        Clock(clock_id="c1", timebase=Timebase.UNKNOWN)
    with pytest.raises(ValidationError):
        Clock(
            clock_id="c2",
            timebase=Timebase.DEVICE_MONOTONIC,
            epoch_utc=datetime(2026, 9, 17, 12, 0, tzinfo=UTC),
        )
    assert Clock(clock_id="c3", timebase=Timebase.SESSION_MONOTONIC)


def test_synchronization_is_explicit_not_free_text() -> None:
    from dynamis.contracts import SynchronizationSpec

    base: dict[str, object] = {
        "sync_spec_id": "sync-1",
        "reference_clock_id": "clock-1",
    }
    with pytest.raises(ValidationError):
        SynchronizationSpec.model_validate(
            {**base, "method": SynchronizationMethod.UNKNOWN, "uncertainty_ms": 1.0}
        )
    with pytest.raises(ValidationError):
        SynchronizationSpec.model_validate(
            {
                **base,
                "method": SynchronizationMethod.UNKNOWN,
                "verified": True,
                "verified_at": "2026-09-17T12:00:00+00:00",
                "evidence_artifact_id": "art-1",
            }
        )
    with pytest.raises(ValidationError):
        SynchronizationSpec.model_validate(
            {**base, "method": SynchronizationMethod.HARDWARE_SYNCHRONIZED}
        )
    justified = SynchronizationSpec.model_validate(
        {
            **base,
            "method": SynchronizationMethod.HARDWARE_SYNCHRONIZED,
            "notes": "vendor documents a shared trigger line",
        }
    )
    assert justified.verified is False

    quantified = SynchronizationSpec.model_validate(
        {
            **base,
            "method": SynchronizationMethod.EVENT_ALIGNED,
            "residual_max_abs_ms": 8.0,
            "residual_rms_ms": 3.0,
        }
    )
    assert quantified.residual_rms_ms == 3.0

    with pytest.raises(ValidationError):
        SynchronizationSpec.model_validate(
            {**base, "method": SynchronizationMethod.EVENT_ALIGNED, "verified": True}
        )
    with pytest.raises(ValidationError):
        SynchronizationSpec.model_validate(
            {
                **base,
                "method": SynchronizationMethod.EVENT_ALIGNED,
                "residual_max_abs_ms": 3.0,
                "residual_rms_ms": 8.0,
            }
        )


def test_sync_alignment_applies_declared_affine_offset() -> None:
    from dynamis.contracts import SyncAlignment

    alignment = SyncAlignment(
        source_stream_id="gnss-00000001",
        target_stream_id="imu-00000001",
        offset_ns=1_500_000,
        scale=1.0,
        sync_spec_id="sync-1",
    )
    assert alignment.apply(0) == 1_500_000
    assert alignment.apply(1_000) == 1_501_000


# ---------------------------------------------------------------------------
# Coordinate frames and skeletons
# ---------------------------------------------------------------------------


def _frame(**overrides: object) -> CoordinateFrame:
    base: dict[str, object] = {
        "frame_id": "syn-frame-imu-body",
        "name": "IMU body frame",
        "kind": FrameKind.SENSOR,
        "handedness": Handedness.RIGHT,
        "x_direction": "forward",
        "y_direction": "left",
        "z_direction": "up",
        "origin_description": "IMU enclosure centre",
    }
    base.update(overrides)
    return CoordinateFrame.model_validate(base)


def test_coordinate_frame_requires_explicit_transform_for_parent() -> None:
    assert _frame().parent_frame_id is None
    with pytest.raises(ValidationError):
        _frame(parent_frame_id="parent-frame")
    with pytest.raises(ValidationError):
        _frame(kind=FrameKind.UNKNOWN)
    with pytest.raises(ValidationError):
        _frame(y_direction="forward", z_direction="forward")
    with pytest.raises(ValidationError):
        _frame(length_unit="yard")


def test_frame_transform_must_be_explained_and_unit_norm() -> None:
    from dynamis.contracts import FrameTransform

    base: dict[str, object] = {
        "source_frame_id": "a",
        "target_frame_id": "b",
        "translation_m": (1.0, 2.0, 3.0),
        "rotation_xyzw": (0.0, 0.0, 0.0, 1.0),
    }
    with pytest.raises(ValidationError):
        FrameTransform.model_validate(base)
    explained = FrameTransform.model_validate({**base, "notes": "axes verified by hand"})
    assert explained.notes is not None
    with pytest.raises(ValidationError):
        FrameTransform.model_validate({**base, "notes": "x", "rotation_xyzw": (1.0, 1.0, 1.0, 1.0)})
    with pytest.raises(ValidationError):
        FrameTransform.model_validate({**base, "notes": "x", "source_frame_id": "b"})


def test_declared_parent_must_match_transform_target() -> None:
    with pytest.raises(ValidationError):
        _frame(
            parent_frame_id="parent-frame",
            transform={
                "source_frame_id": "syn-frame-imu-body",
                "target_frame_id": "other-frame",
                "translation_m": (0.0, 0.0, 0.0),
                "rotation_xyzw": (0.0, 0.0, 0.0, 1.0),
                "notes": "explicit",
            },
        )


def test_transform_points_is_explicit_math() -> None:
    from dynamis.contracts import FrameTransform, transform_points

    identity = FrameTransform(
        source_frame_id="a",
        target_frame_id="b",
        translation_m=(0.0, 0.0, 0.0),
        rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
        notes="identity",
    )
    point = (1.0, 2.0, 3.0)
    (image,) = transform_points(identity, (point,))
    assert image == pytest.approx(point)

    quarter_turn_z = FrameTransform(
        source_frame_id="a",
        target_frame_id="b",
        translation_m=(0.0, 0.0, 0.0),
        rotation_xyzw=(0.0, 0.0, 0.7071067811865476, 0.7071067811865476),
        notes="90 degrees about z",
    )
    (rotated,) = transform_points(quarter_turn_z, ((1.0, 0.0, 0.0),))
    assert rotated == pytest.approx((0.0, 1.0, 0.0), abs=1e-12)


def test_skeleton_topology_is_validated() -> None:
    from dynamis.contracts import JointDefinition, SkeletonDefinition

    joints = (
        JointDefinition(joint_id=0, joint_name="pelvis", parent_joint_id=None),
        JointDefinition(joint_id=1, joint_name="knee", parent_joint_id=0),
    )
    skeleton = SkeletonDefinition(
        skeleton_id="syn-skeleton", name="lower limb", joint_count=2, joints=joints
    )
    assert skeleton.joint_count == 2

    with pytest.raises(ValidationError):
        SkeletonDefinition(skeleton_id="s", name="bad", joint_count=3, joints=joints)
    with pytest.raises(ValidationError):
        SkeletonDefinition(
            skeleton_id="s",
            name="bad",
            joint_count=2,
            joints=(
                JointDefinition(joint_id=0, joint_name="a", parent_joint_id=1),
                JointDefinition(joint_id=1, joint_name="b", parent_joint_id=None),
            ),
        )
    with pytest.raises(ValidationError):
        SkeletonDefinition(
            skeleton_id="s",
            name="two roots",
            joint_count=2,
            joints=(
                JointDefinition(joint_id=0, joint_name="a", parent_joint_id=None),
                JointDefinition(joint_id=1, joint_name="b", parent_joint_id=None),
            ),
        )
    with pytest.raises(ValidationError):
        SkeletonDefinition(
            skeleton_id="s",
            name="dup",
            joint_count=2,
            joints=(
                JointDefinition(joint_id=0, joint_name="a", parent_joint_id=None),
                JointDefinition(joint_id=1, joint_name="a", parent_joint_id=0),
            ),
        )


def test_landmark_set_skeleton_declares_no_parent_graph() -> None:
    from dynamis.contracts import (
        JointDefinition,
        SkeletonDefinition,
        SkeletonDisplayConnection,
        SkeletonTopology,
    )

    landmarks = (
        JointDefinition(joint_id=0, joint_name="left_ankle", parent_joint_id=None),
        JointDefinition(joint_id=1, joint_name="right_ankle", parent_joint_id=None),
    )
    skeleton = SkeletonDefinition(
        skeleton_id="syn-skeleton-landmarks",
        name="29-landmark body pose",
        topology=SkeletonTopology.LANDMARK_SET,
        joint_count=2,
        joints=landmarks,
        description="Source publishes an ordered landmark list without a parent graph.",
    )
    assert skeleton.topology is SkeletonTopology.LANDMARK_SET
    assert all(joint.parent_joint_id is None for joint in skeleton.joints)

    display = SkeletonDisplayConnection(start_joint_name="left_ankle", end_joint_name="right_ankle")
    with_display = SkeletonDefinition(
        skeleton_id="syn-skeleton-landmarks-with-display",
        name="landmark set with display edges",
        topology=SkeletonTopology.LANDMARK_SET,
        joint_count=2,
        joints=landmarks,
        display_connections=(display,),
        description="Source publishes drawable pairs without a parent graph.",
    )
    assert with_display.display_connections == (display,)
    with pytest.raises(ValidationError, match="unknown landmark"):
        SkeletonDefinition(
            skeleton_id="s",
            name="bad display edge",
            topology=SkeletonTopology.LANDMARK_SET,
            joint_count=2,
            joints=landmarks,
            display_connections=(
                SkeletonDisplayConnection(start_joint_name="left_ankle", end_joint_name="nose"),
            ),
            description="documented",
        )

    # Parent ids must not be fabricated for a landmark set.
    with pytest.raises(ValidationError, match="landmark_set"):
        SkeletonDefinition(
            skeleton_id="s",
            name="invented tree",
            topology=SkeletonTopology.LANDMARK_SET,
            joint_count=2,
            joints=(
                JointDefinition(joint_id=0, joint_name="a", parent_joint_id=None),
                JointDefinition(joint_id=1, joint_name="b", parent_joint_id=0),
            ),
            description="documented",
        )
    # A landmark set is a deliberate declaration and must be documented.
    with pytest.raises(ValidationError, match="description"):
        SkeletonDefinition(
            skeleton_id="s",
            name="undocumented landmarks",
            topology=SkeletonTopology.LANDMARK_SET,
            joint_count=2,
            joints=landmarks,
        )
    # The tree form still enforces exactly one root and earlier parents.
    with pytest.raises(ValidationError, match="exactly one root"):
        SkeletonDefinition(
            skeleton_id="s",
            name="two roots",
            topology=SkeletonTopology.TREE,
            joint_count=2,
            joints=landmarks,
        )
