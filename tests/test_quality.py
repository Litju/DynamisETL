"""Quality checks must reject schema, unit, timing and provenance violations."""

from __future__ import annotations

import pyarrow as pa
import pytest

from dynamis.config import Settings
from dynamis.contracts import Modality, Severity, get_schema
from dynamis.contracts.schemas import SI_UNIT_KEY, SOURCE_UNIT_KEY, axis_of
from dynamis.fixtures import force_bodyweight_static, gnss_constant_velocity
from dynamis.quality.checks import (
    QualityError,
    assert_valid,
    check_declared_authorities,
    check_identity,
    check_measurement_class,
    check_schema_conformance,
    check_time_monotonic,
    check_units,
    to_quality_issue,
    validate,
)


def _force_table() -> pa.Table:
    return force_bodyweight_static(rate_hz=1000.0, duration_s=0.008).table


def test_valid_table_has_no_violations() -> None:
    fixture = force_bodyweight_static(rate_hz=1000.0, duration_s=0.008)
    assert validate(fixture.table, fixture.schema) == ()
    assert assert_valid(fixture.table, fixture.schema) is fixture.table


def test_missing_column_is_detected() -> None:
    table = _force_table().drop_columns(["force_z_n"])
    violations = check_schema_conformance(table, get_schema(Modality.FORCE))
    assert any(item.rule == "schema.field.missing" for item in violations)


def test_unexpected_column_is_detected() -> None:
    table = _force_table().append_column("surprise", pa.array([1.0] * 8))
    violations = check_schema_conformance(table, get_schema(Modality.FORCE))
    assert any(item.rule == "schema.field.unexpected" for item in violations)


def _without_schema_metadata(table: pa.Table) -> pa.Table:
    """Rebuild a table whose Arrow schema carries no DynamisData metadata."""
    stripped = pa.schema([field_.with_metadata({}) for field_ in table.schema], metadata=None)
    return pa.Table.from_arrays(table.columns, schema=stripped)


def test_nullability_drift_is_detected() -> None:
    schema = get_schema(Modality.FORCE)
    # stream_id is non-nullable by contract; relaxing it must be rejected.
    relaxed = pa.schema(
        [field_.with_nullable(True) if field_.name == "stream_id" else field_ for field_ in schema],
        metadata=schema.metadata,
    )
    table = pa.Table.from_arrays(_force_table().columns, schema=relaxed)
    violations = check_schema_conformance(table, schema)
    assert any(
        item.rule == "schema.field.nullability" and item.evidence.get("column") == "stream_id"
        for item in violations
    )


def test_type_drift_is_detected() -> None:
    table = _force_table()
    index = table.schema.get_field_index("force_x_n")
    drifted = table.set_column(index, "force_x_n", pa.array([0] * 8, type=pa.int64()))
    violations = check_schema_conformance(drifted, get_schema(Modality.FORCE))
    assert any(item.rule == "schema.field.type" for item in violations)


def test_non_si_unit_metadata_is_rejected() -> None:
    schema = get_schema(Modality.FORCE)
    tampered = pa.schema(
        [
            field_.with_metadata({SI_UNIT_KEY: b"yard"}) if field_.name == "force_z_n" else field_
            for field_ in schema
        ],
        metadata=schema.metadata,
    )
    violations = check_units(_force_table(), tampered)
    assert any(item.rule == "units.not_si" for item in violations)


def test_unit_metadata_on_a_string_column_is_rejected() -> None:
    schema = get_schema(Modality.FORCE)
    tampered = pa.schema(
        [
            field_.with_metadata({SI_UNIT_KEY: b"1"}) if field_.name == "quality_flag" else field_
            for field_ in schema
        ],
        metadata=schema.metadata,
    )
    violations = check_units(_force_table(), tampered)
    assert any(item.rule == "units.non_numeric" for item in violations)


def test_non_monotonic_time_is_rejected() -> None:
    fixture = force_bodyweight_static(rate_hz=1000.0, duration_s=0.008)
    times = fixture.table.column("t_rel_ns").to_pylist()
    times[3] = times[2]
    table = fixture.table.set_column(
        fixture.table.schema.get_field_index("t_rel_ns"),
        "t_rel_ns",
        pa.array(times, type=pa.int64()),
    )
    violations = check_time_monotonic(table, get_schema(Modality.FORCE))
    assert any(item.rule == "time.monotonic" for item in violations)


def test_frame_streams_allow_repeated_frame_timestamps_but_require_order() -> None:
    from dynamis.fixtures import pose_skeleton_trajectory

    fixture = pose_skeleton_trajectory(frame_count=4)
    assert check_time_monotonic(fixture.table, fixture.schema) == ()

    times = fixture.table.column("t_rel_ns").to_pylist()
    times[-1] = -1
    table = fixture.table.set_column(
        fixture.table.schema.get_field_index("t_rel_ns"),
        "t_rel_ns",
        pa.array(times, type=pa.int64()),
    )
    violations = check_time_monotonic(table, fixture.schema)
    assert any(item.rule == "time.monotonic" for item in violations)


def test_non_contiguous_sample_index_is_rejected() -> None:
    fixture = force_bodyweight_static(rate_hz=1000.0, duration_s=0.008)
    indices = [0, 1, 2, 4, 5, 6, 7, 8]
    table = fixture.table.set_column(
        fixture.table.schema.get_field_index("sample_index"),
        "sample_index",
        pa.array(indices, type=pa.int64()),
    )
    violations = check_time_monotonic(table, fixture.schema)
    assert any(item.rule == "time.contiguous" for item in violations)


def test_missing_subject_identity_is_rejected_for_subject_modalities() -> None:
    fixture = gnss_constant_velocity(sample_count=5)
    subjects: list[str | None] = [None] * 5
    table = fixture.table.set_column(
        fixture.table.schema.get_field_index("subject_id"),
        "subject_id",
        pa.array(subjects, type=pa.string()),
    )
    violations = check_identity(table, get_schema(Modality.GNSS))
    assert any(item.rule == "identity.subject_required" for item in violations)


def test_mixed_coordinate_frames_in_one_file_are_rejected() -> None:
    fixture = force_bodyweight_static(rate_hz=1000.0, duration_s=0.006)
    frames = ["syn-frame-force-plate"] * 6
    frames[2] = "other-frame"
    table = fixture.table.set_column(
        fixture.table.schema.get_field_index("coordinate_frame_id"),
        "coordinate_frame_id",
        pa.array(frames, type=pa.string()),
    )
    violations = check_declared_authorities(table, get_schema(Modality.FORCE))
    assert any(item.rule == "authority.frame_multiple" for item in violations)


def _pose_table(*, unavailable: bool = False) -> pa.Table:
    from dynamis.fixtures import pose_skeleton_trajectory

    return pose_skeleton_trajectory(frame_count=4, unavailable_pattern=unavailable).table


def test_pose_availability_and_coordinates_must_agree() -> None:
    from dynamis.quality.checks import check_pose_payload_completeness

    table = _pose_table()
    schema = get_schema(Modality.POSE)
    assert check_pose_payload_completeness(table, schema) == ()

    # An available joint without coordinates is rejected (never imputed).
    x_index = table.schema.get_field_index("x_m")
    xs = table.column("x_m").to_pylist()
    xs[0] = None
    tampered = table.set_column(x_index, "x_m", pa.array(xs, type=pa.float64()))
    violations = check_pose_payload_completeness(tampered, schema)
    assert any(item.rule == "pose.payload.missing_coordinates" for item in violations)

    # An unavailable joint carrying coordinates is contradictory.
    unavailable_rows = _pose_table(unavailable=True)
    z_index = unavailable_rows.schema.get_field_index("z_m")
    zs = unavailable_rows.column("z_m").to_pylist()
    target = next(
        index
        for index, value in enumerate(unavailable_rows.column("is_available").to_pylist())
        if not value
    )
    zs[target] = 1.0
    tampered = unavailable_rows.set_column(z_index, "z_m", pa.array(zs, type=pa.float64()))
    violations = check_pose_payload_completeness(tampered, schema)
    assert any(item.rule == "pose.payload.unexpected_coordinates" for item in violations)


def test_pose_available_joint_requires_finite_coordinates() -> None:
    from dynamis.quality.checks import check_pose_payload_completeness

    table = _pose_table()
    x_index = table.schema.get_field_index("x_m")
    xs = table.column("x_m").to_pylist()
    xs[1] = float("nan")
    tampered = table.set_column(x_index, "x_m", pa.array(xs, type=pa.float64()))
    violations = check_pose_payload_completeness(tampered, get_schema(Modality.POSE))
    assert any(item.rule == "pose.payload.non_finite" for item in violations)


def test_pose_payload_checks_skip_structurally_incompatible_data() -> None:
    from dynamis.quality.checks import check_pose_payload_completeness

    table = _pose_table()
    schema = get_schema(Modality.POSE)
    index = table.schema.get_field_index("x_m")
    tampered = table.set_column(index, "x_m", pa.array([0] * table.num_rows, type=pa.int64()))
    # The structural violation is reported, and the payload kernels never run
    # against the incompatible column.
    assert check_pose_payload_completeness(tampered, schema) == ()
    assert any(
        item.rule == "schema.field.type" for item in check_schema_conformance(tampered, schema)
    )

    from dynamis.quality.streaming import StreamingValidator

    validator = StreamingValidator(schema)
    for batch in tampered.to_batches(max_chunksize=64):
        assert batch.schema.field("x_m").type == pa.int64()
        validator.observe(batch)
    assert isinstance(validator.finish(), tuple)


def test_null_frame_is_rejected_when_the_modality_requires_one() -> None:
    fixture = force_bodyweight_static(rate_hz=1000.0, duration_s=0.004)
    table = fixture.table.set_column(
        fixture.table.schema.get_field_index("coordinate_frame_id"),
        "coordinate_frame_id",
        pa.array([None] * 4, type=pa.string()),
    )
    violations = check_declared_authorities(table, get_schema(Modality.FORCE))
    assert any(item.rule == "authority.frame_required" for item in violations)


def test_illegal_measurement_class_is_rejected() -> None:
    fixture = force_bodyweight_static(rate_hz=1000.0, duration_s=0.004)
    table = fixture.table.set_column(
        fixture.table.schema.get_field_index("measurement_class"),
        "measurement_class",
        pa.array(["GUESSED"] * 4, type=pa.string()),
    )
    violations = check_measurement_class(table)
    assert any(item.rule == "measurement_class.illegal" for item in violations)


def test_missing_schema_metadata_is_rejected() -> None:
    violations = check_schema_conformance(
        _without_schema_metadata(_force_table()), get_schema(Modality.FORCE)
    )
    assert any(item.rule == "schema.metadata.missing" for item in violations)


def test_assert_valid_raises_with_all_violations() -> None:
    table = _without_schema_metadata(_force_table())
    with pytest.raises(QualityError) as error:
        assert_valid(table, get_schema(Modality.FORCE))
    assert error.value.violations


def test_violations_project_into_auditable_quality_issues() -> None:
    fixture = force_bodyweight_static(rate_hz=1000.0, duration_s=0.004)
    table = fixture.table.set_column(
        fixture.table.schema.get_field_index("measurement_class"),
        "measurement_class",
        pa.array(["GUESSED"] * 4, type=pa.string()),
    )
    (violation,) = check_measurement_class(table)
    issue = to_quality_issue(
        violation,
        issue_id="qi-1",
        dataset_id=fixture.dataset_id,
        session_id=fixture.session_id,
        stream_id=fixture.stream_id,
    )
    assert issue.rule == "measurement_class.illegal"
    assert issue.severity is Severity.ERROR
    assert issue.state.value == "QUARANTINED"
    assert issue.evidence
    assert issue.stream_id == fixture.stream_id

    # An unlocatable quarantine record is refused rather than stored blindly.
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        to_quality_issue(
            violation,
            issue_id="qi-2",
            dataset_id=fixture.dataset_id,
            session_id=fixture.session_id,
        )


def test_source_unit_provenance_metadata_is_preserved_independently(
    tmp_settings: Settings,
) -> None:
    from dynamis.contracts.schemas import source_scale_of, source_unit_of
    from dynamis.storage.parquet import read_parquet_schema, write_parquet_atomic

    fixture = force_bodyweight_static(rate_hz=1000.0, duration_s=0.004)
    field_ = fixture.schema.field("force_z_n")
    assert source_unit_of(field_) is None
    assert source_scale_of(field_) is None
    assert axis_of(field_) == "z"

    schema = pa.schema(
        [
            field_.with_metadata(
                {
                    SI_UNIT_KEY: b"N",
                    SOURCE_UNIT_KEY: b"kgf",
                    b"dynamis.source_to_si_scale": b"9.80665",
                }
            )
            if field_.name == "force_z_n"
            else field_
            for field_ in fixture.schema
        ],
        metadata=fixture.schema.metadata,
    )
    table = fixture.table.cast(schema)
    path = tmp_settings.dataset_root / "provenance.parquet"
    write_parquet_atomic(table, path)
    stored = read_parquet_schema(path).field("force_z_n")
    assert source_unit_of(stored) == "kgf"
    assert source_scale_of(stored) == pytest.approx(9.80665)
