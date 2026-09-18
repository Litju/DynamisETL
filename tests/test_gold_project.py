"""Gold serving must rebuild deterministically and reconcile with its source.

CI builds the dbt project over a synthetic serving export (no PostgreSQL, no
downloads). A postgres-gated test proves the real export -> build -> publish
path against a migrated test schema.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pytest

from dynamis.config import Settings, repository_root
from dynamis.gold.build import MART_NAMES, build_gold
from dynamis.storage.parquet import write_parquet_atomic

ANALYTICS_DIR = repository_root() / "analytics"


def _write(root: Path, name: str, table: pa.Table) -> None:
    write_parquet_atomic(table, root / f"{name}.parquet")


def _string_table(rows: list[dict], columns: list[str]) -> pa.Table:
    schema = pa.schema([pa.field(name, pa.string()) for name in columns])
    return pa.Table.from_pylist(rows, schema=schema)


def _synthetic_serving(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _write(
        root,
        "algorithm_spec",
        _string_table(
            [
                {"algorithm_id": "locomotor.speed_effort_kinematics", "version": "1.0.0"},
                {"algorithm_id": "force.cmj_body_weight_ratio_full_record", "version": "1.0.0"},
                {"algorithm_id": "pose.translation_invariant_kinematics", "version": "1.0.0"},
            ],
            ["algorithm_id", "version"],
        ),
    )
    _write(
        root,
        "processing_run",
        _string_table(
            [
                {"run_id": "run-loco", "dataset_id": "womens-soccer-positioning"},
                {"run_id": "run-loco-old", "dataset_id": "womens-soccer-positioning"},
                {"run_id": "run-cmj", "dataset_id": "white-cmj-acc-grf"},
                {"run_id": "run-pose", "dataset_id": "skillcorner-opendata"},
            ],
            ["run_id", "dataset_id"],
        ),
    )
    _write(
        root,
        "processing_artifact",
        _string_table(
            [{"artifact_id": "art-1", "run_id": "run-loco", "artifact_type": "processed_series"}],
            ["artifact_id", "run_id", "artifact_type"],
        ),
    )
    _write(
        root,
        "metric_definition",
        _string_table(
            [
                {
                    "metric_id": "locomotor.distance_total",
                    "name": "distance",
                    "si_unit": "m",
                    "description": "distance",
                },
                {
                    "metric_id": "locomotor.max_speed",
                    "name": "max speed",
                    "si_unit": "m/s",
                    "description": "max speed",
                },
                {
                    "metric_id": "cmj.jump_height_jhwd",
                    "name": "jump height",
                    "si_unit": "m",
                    "description": "jump height",
                },
                {
                    "metric_id": "pose.angular_rom.left_knee",
                    "name": "knee ROM",
                    "si_unit": "rad",
                    "description": "knee ROM",
                },
            ],
            ["metric_id", "name", "si_unit", "description"],
        ),
    )
    provenance = json.dumps(
        {
            "origin": "pipeline-computed",
            "algorithm_id": "locomotor.speed_effort_kinematics",
            "algorithm_version": "1.0.0",
            "parameters_hash": "a" * 64,
            "code_git_sha": "b" * 40,
            "entity_id": "P1",
        },
        sort_keys=True,
    )
    stale_provenance = json.dumps(
        {
            "origin": "pipeline-computed",
            "algorithm_id": "locomotor.speed_effort_kinematics",
            "algorithm_version": "1.0.0",
            "parameters_hash": "a" * 64,
            "code_git_sha": "c" * 40,
            "entity_id": "P1",
        },
        sort_keys=True,
    )
    cmj_provenance = json.dumps(
        {
            "origin": "pipeline-computed",
            "algorithm_id": "force.cmj_body_weight_ratio_full_record",
            "algorithm_version": "1.0.0",
            "parameters_hash": "d" * 64,
            "code_git_sha": "b" * 40,
        },
        sort_keys=True,
    )
    pose_provenance = json.dumps(
        {
            "origin": "pipeline-computed",
            "algorithm_id": "pose.translation_invariant_kinematics",
            "algorithm_version": "1.0.0",
            "parameters_hash": "e" * 64,
            "code_git_sha": "b" * 40,
            "entity_id": "P1",
        },
        sort_keys=True,
    )
    metric_rows = [
        {
            "derived_metric_id": "dm-loco-distance-old",
            "dataset_id": "womens-soccer-positioning",
            "metric_id": "locomotor.distance_total",
            "run_id": "run-loco-old",
            "subject_id": "P1",
            "session_id": "J01",
            "trial_id": None,
            "stream_id": "gnss-1",
            "si_unit": "m",
            "measurement_class": "PIPELINE_DERIVED",
            "value_num": 100.0,
            "computed_at": "2026-01-01T00:00:00+00:00",
            "input_checksums": '["aa"]',
            "provenance": stale_provenance,
        },
        {
            "derived_metric_id": "dm-loco-distance",
            "dataset_id": "womens-soccer-positioning",
            "metric_id": "locomotor.distance_total",
            "run_id": "run-loco",
            "subject_id": "P1",
            "session_id": "J01",
            "trial_id": None,
            "stream_id": "gnss-1",
            "si_unit": "m",
            "measurement_class": "PIPELINE_DERIVED",
            "value_num": 5000.0,
            "computed_at": "2026-01-02T00:00:00+00:00",
            "input_checksums": '["aa"]',
            "provenance": provenance,
        },
        {
            "derived_metric_id": "dm-loco-speed",
            "dataset_id": "womens-soccer-positioning",
            "metric_id": "locomotor.max_speed",
            "run_id": "run-loco",
            "subject_id": "P1",
            "session_id": "J01",
            "trial_id": None,
            "stream_id": "gnss-1",
            "si_unit": "m/s",
            "measurement_class": "PIPELINE_DERIVED",
            "value_num": 7.2,
            "computed_at": "2026-01-02T00:00:00+00:00",
            "input_checksums": '["aa"]',
            "provenance": provenance,
        },
        {
            "derived_metric_id": "dm-cmj-height",
            "dataset_id": "white-cmj-acc-grf",
            "metric_id": "cmj.jump_height_jhwd",
            "run_id": "run-cmj",
            "subject_id": "white-s001",
            "session_id": "white-s001",
            "trial_id": "white-s001-arms-t00",
            "stream_id": "force-white-s001-arms-t00",
            "si_unit": "m",
            "measurement_class": "PIPELINE_DERIVED",
            "value_num": 0.44,
            "computed_at": "2026-01-03T00:00:00+00:00",
            "input_checksums": '["bb"]',
            "provenance": cmj_provenance,
        },
        {
            "derived_metric_id": "dm-pose-rom",
            "dataset_id": "skillcorner-opendata",
            "metric_id": "pose.angular_rom.left_knee",
            "run_id": "run-pose",
            "subject_id": "SC-P1",
            "session_id": "1925299",
            "trial_id": "period_1",
            "stream_id": "pose-period-1",
            "si_unit": "rad",
            "measurement_class": "PIPELINE_DERIVED",
            "value_num": 2.7,
            "computed_at": "2026-01-04T00:00:00+00:00",
            "input_checksums": '["cc"]',
            "provenance": pose_provenance,
        },
    ]
    metric_schema = pa.schema(
        [
            pa.field("derived_metric_id", pa.string()),
            pa.field("dataset_id", pa.string()),
            pa.field("metric_id", pa.string()),
            pa.field("run_id", pa.string()),
            pa.field("subject_id", pa.string()),
            pa.field("session_id", pa.string()),
            pa.field("trial_id", pa.string()),
            pa.field("stream_id", pa.string()),
            pa.field("si_unit", pa.string()),
            pa.field("measurement_class", pa.string()),
            pa.field("value_num", pa.float64()),
            pa.field("computed_at", pa.string()),
            pa.field("input_checksums", pa.string()),
            pa.field("provenance", pa.string()),
        ]
    )
    _write(root, "derived_metric", pa.Table.from_pylist(metric_rows, schema=metric_schema))
    for name in (
        "dataset_source",
        "sample_artifact",
        "sensor_stream",
        "session",
        "subject",
        "sync_alignment",
        "trial",
    ):
        _write(root, name, _string_table([], ["dataset_id"]))


def test_gold_build_selects_current_revision_and_reconciles(tmp_settings: Settings) -> None:
    serving = tmp_settings.dataset_root / "gold" / "serving"
    _synthetic_serving(serving)
    first = build_gold(tmp_settings, project_dir=ANALYTICS_DIR, serving_root=serving)
    assert first.success
    assert set(first.marts) == set(MART_NAMES)

    import duckdb

    def scalar(connection: duckdb.DuckDBPyConnection, sql: str) -> object:
        row = connection.execute(sql).fetchone()
        assert row is not None
        return row[0]

    connection = duckdb.connect(str(first.duckdb_path))
    try:
        trial_metrics = scalar(connection, "SELECT count(*) FROM gold_trial_metrics")
        stale = scalar(
            connection,
            "SELECT count(*) FROM gold_trial_metrics "
            "WHERE derived_metric_id = 'dm-loco-distance-old'",
        )
        distance = scalar(connection, "SELECT distance_total_m FROM gold_session_player_load")
        jump = scalar(connection, "SELECT jump_height_jhwd_m FROM gold_cmj_metrics")
        rom = scalar(connection, "SELECT max_angular_rom_rad FROM gold_pose_kinematics_summary")
        provenance = scalar(connection, "SELECT count(*) FROM gold_processing_provenance")
    finally:
        connection.close()
    # The older revision of the same identity is historical, not served.
    assert trial_metrics == 4
    assert stale == 0
    assert distance == pytest.approx(5000.0)
    assert jump == pytest.approx(0.44)
    assert rom == pytest.approx(2.7)
    assert provenance == 3

    # Deterministic rebuild: a second build over the same serving export
    # reproduces the identical mart content fingerprints.
    second = build_gold(tmp_settings, project_dir=ANALYTICS_DIR, serving_root=serving)
    for mart in MART_NAMES:
        assert (
            second.marts[mart]["content_fingerprint"] == first.marts[mart]["content_fingerprint"]
        ), mart


@pytest.mark.postgres
def test_gold_export_build_publish_round_trip(
    postgres_url: str,
    test_db_schema: str,
    tmp_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    from dynamis.config import ENV_DB_SCHEMA, ENV_POSTGRES_URL
    from dynamis.gold.export import export_serving
    from dynamis.gold.publish import ENV_GOLD_SCHEMA, publish_gold
    from dynamis.pipeline.persist import persist_source
    from dynamis.processors import (
        MetricDeclaration,
        ProcessorResult,
        ProcessorSpec,
        ScalarMetric,
    )
    from dynamis.processors.persistence import persist_processing_result
    from dynamis.registry import source_by_id, validate_registry
    from dynamis.storage.control_plane import control_plane_engine

    monkeypatch.setenv(ENV_POSTGRES_URL, postgres_url)
    monkeypatch.setenv(ENV_DB_SCHEMA, test_db_schema)
    gold_schema = f"{test_db_schema}_gold"
    monkeypatch.setenv(ENV_GOLD_SCHEMA, gold_schema)
    root = repository_root()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "infra" / "migrations"))
    config.set_main_option("sqlalchemy.url", postgres_url.replace("%", "%%"))
    admin = create_engine(postgres_url, future=True)
    settings = Settings(
        dataset_root=tmp_settings.dataset_root,
        database_root=tmp_settings.database_root,
        duckdb_path=tmp_settings.duckdb_path,
        db_schema=test_db_schema,
    )
    control = control_plane_engine(settings, postgres_url)
    try:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        command.upgrade(config, "head")
        spec = ProcessorSpec(
            algorithm_id="test.gold",
            name="Gold test processor",
            version="1.0.0",
            description="Gold round-trip fixture.",
            parameters={"window_s": 5.0},
        )
        result = ProcessorResult(
            spec=spec,
            metrics=(
                ScalarMetric(
                    declaration=MetricDeclaration(
                        metric_id="test.gold.distance",
                        name="Gold distance",
                        si_unit="m",
                        description="Gold round-trip metric.",
                    ),
                    value=123.0,
                    session_id="session-1",
                    stream_id="stream-1",
                ),
            ),
        )
        with control.begin() as connection:
            persist_source(connection, source_by_id(validate_registry(), "white-cmj-acc-grf"))
            persist_processing_result(
                connection,
                dataset_id="white-cmj-acc-grf",
                run_id="run-gold-test",
                result=result,
                input_checksums=("f" * 64,),
                computed_at=datetime(2026, 9, 18, tzinfo=UTC),
                code_sha="a" * 40,
            )
        export = export_serving(settings, control)
        assert export.tables["derived_metric"]["row_count"] == 1
        built = build_gold(settings)
        assert built.success
        published = publish_gold(settings, control)
        assert published["marts"]["gold_trial_metrics"] == 1
        with control.connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT metric_id, value_num, run_id, parameters_hash, code_git_sha "
                    f'FROM "{gold_schema}".gold_trial_metrics'
                )
            ).fetchall()
            provenance_rows = connection.execute(
                text(f'SELECT count(*) FROM "{gold_schema}".gold_processing_provenance')
            ).scalar_one()
        assert len(rows) == 1
        assert rows[0].metric_id == "test.gold.distance"
        assert rows[0].value_num == pytest.approx(123.0)
        assert rows[0].run_id == "run-gold-test"
        assert rows[0].parameters_hash == spec.parameters_hash
        assert rows[0].code_git_sha == "a" * 40
        assert provenance_rows == 1
    finally:
        control.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{gold_schema}" CASCADE'))
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        admin.dispose()
