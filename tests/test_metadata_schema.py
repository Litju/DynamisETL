"""SQLAlchemy metadata: corrected session semantics and decoupled definitions."""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from dynamis.storage.metadata import build_metadata, metadata
from dynamis.storage.tables import EXPECTED_TABLE_NAMES


def test_metadata_contains_exactly_the_expected_tables() -> None:
    built = build_metadata()
    assert frozenset(built.tables) == EXPECTED_TABLE_NAMES
    assert len(EXPECTED_TABLE_NAMES) == 26


def test_dense_samples_never_enter_postgresql() -> None:
    built = build_metadata()
    assert "frame" not in built.tables
    assert "sample_artifact" in built.tables
    assert "sensor_stream" in built.tables


def test_metadata_is_schema_unqualified_so_search_path_applies() -> None:
    assert build_metadata().schema is None
    assert metadata.schema is None


def test_session_does_not_force_a_single_subject() -> None:
    session = build_metadata().tables["session"]
    assert "subject_id" not in session.columns
    participants = build_metadata().tables["session_participant"]
    assert {"dataset_id", "session_id", "subject_id"} <= set(participants.columns.keys())


def test_algorithm_and_metric_definitions_are_global() -> None:
    built = build_metadata()
    assert "dataset_id" not in built.tables["algorithm_spec"].columns
    assert "dataset_id" not in built.tables["metric_definition"].columns
    assert "dataset_id" in built.tables["processing_run"].columns
    assert "dataset_id" in built.tables["derived_metric"].columns


def test_first_class_support_authorities_exist() -> None:
    built = build_metadata()
    for table in (
        "license_policy",
        "coordinate_frame",
        "frame_transform",
        "synchronization_spec",
        "skeleton_definition",
        "skeleton_joint",
        "sample_artifact",
    ):
        assert table in built.tables


def test_every_table_declares_a_primary_key() -> None:
    for name, table in build_metadata().tables.items():
        assert table.primary_key.columns, f"{name} has no primary key"


def test_every_foreign_key_targets_an_existing_table() -> None:
    built = build_metadata()
    for table in built.tables.values():
        for foreign_key in table.foreign_keys:
            target = foreign_key.column.table.name
            assert target in built.tables, f"{table.name} -> missing {target}"


def test_provenance_checks_are_present_in_the_ddl() -> None:
    built = build_metadata()
    relevant = {
        table.name: {constraint.name for constraint in table.constraints}
        for table in built.tables.values()
    }
    assert "ck_processing_run_provenance_requires_inputs" in relevant["processing_run"]
    assert "ck_derived_metric_provenance_requires_inputs" in relevant["derived_metric"]
    assert "ck_sample_artifact_parquet_is_zstd" in relevant["sample_artifact"]
    assert "ck_quality_issue_evidence_required" in relevant["quality_issue"]
    assert "ck_frame_transform_explained_transform" in relevant["frame_transform"]
    assert "ck_sensor_stream_pose_requires_skeleton" in relevant["sensor_stream"]
    assert "ck_skeleton_definition_topology" in relevant["skeleton_definition"]
    assert "ck_skeleton_joint_parent_precedes_child" in relevant["skeleton_joint"]


def test_ddl_compiles_for_postgresql() -> None:
    dialect = postgresql.dialect()
    ddl = "\n".join(
        str(CreateTable(table).compile(dialect=dialect)) for table in build_metadata().sorted_tables
    )
    assert "CREATE TABLE" in ddl
    assert "JSONB" in ddl
    assert "TIMESTAMP WITH TIME ZONE" in ddl
    assert "alembic_version" not in ddl


def test_metadata_is_a_single_shared_object() -> None:
    from dynamis.storage import tables

    assert tables.Base.metadata is metadata
    assert isinstance(metadata, MetaData)


def test_check_constraint_names_are_not_double_prefixed() -> None:
    for table in build_metadata().tables.values():
        for constraint in table.constraints:
            name = constraint.name
            if isinstance(name, str) and name.startswith("ck_"):
                prefix = f"ck_{table.name}_"
                assert name.startswith(prefix), name
                assert not name.removeprefix(prefix).startswith("ck_"), name
