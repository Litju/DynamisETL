"""Pipeline metrics must resolve to their full provenance chain in PostgreSQL.

Acceptance for RES-100: every accepted metric resolves to input checksum(s),
algorithm/version, parameters hash, code SHA and processing run. This test
persists a real processor result through the control plane twice and proves the
chain is complete and idempotent.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

from dynamis.config import (
    ENV_DB_SCHEMA,
    ENV_POSTGRES_URL,
    Settings,
    repository_root,
)
from dynamis.processors import (
    MetricDeclaration,
    ProcessorResult,
    ProcessorSpec,
    ScalarMetric,
    SeriesOutput,
)
from dynamis.processors.persistence import (
    MAX_UPSERT_BIND_PARAMETERS,
    METRIC_DEFINITION_TABLE,
    _upsert,
    persist_processing_result,
)


def test_large_metric_upsert_is_batched_below_driver_parameter_limit() -> None:
    class Result:
        def __init__(self, row_count: int) -> None:
            self.row_count = row_count

        def fetchall(self) -> list[tuple[int]]:
            return [(index,) for index in range(self.row_count)]

    class Connection:
        def __init__(self) -> None:
            self.parameter_counts: list[int] = []
            self.row_counts: list[int] = []

        def execute(self, statement):
            compiled = statement.compile(dialect=postgresql.dialect())
            count = len(compiled.params)
            self.parameter_counts.append(count)
            rows = count // len(METRIC_DEFINITION_TABLE.columns)
            self.row_counts.append(rows)
            return Result(rows)

    rows = [
        {
            "metric_id": f"test.pose.quality.{index}",
            "name": f"Test Pose quality metric {index}",
            "si_unit": "m",
            "measurement_class": "PIPELINE_DERIVED",
            "value_kind": "scalar",
            "description": "Batch persistence known answer.",
            "algorithm_id": "test.persistence",
        }
        for index in range(6_000)
    ]
    connection = Connection()

    written = _upsert(connection, METRIC_DEFINITION_TABLE, rows)

    assert written == len(rows)
    assert len(connection.parameter_counts) == 2
    assert max(connection.parameter_counts) <= MAX_UPSERT_BIND_PARAMETERS
    assert sum(connection.row_counts) == len(rows)


def _spec() -> ProcessorSpec:
    return ProcessorSpec(
        algorithm_id="test.persistence",
        name="Persistence test processor",
        version="1.0.0",
        description="PostgreSQL persistence fixture.",
        parameters={"window_s": 5.0},
    )


def _series() -> SeriesOutput:
    import pyarrow as pa

    return SeriesOutput(
        name="derived",
        table=pa.table({"sample_index": pa.array([0, 1, 2], type=pa.int64())}),
    )


def _result(*, value: float = 2.5) -> ProcessorResult:
    return ProcessorResult(
        spec=_spec(),
        metrics=(
            ScalarMetric(
                declaration=MetricDeclaration(
                    metric_id="test.persistence.scalar",
                    name="Persistence scalar",
                    si_unit="m",
                    description="Persistence test scalar.",
                ),
                value=value,
                session_id="session-1",
                stream_id="stream-1",
                provenance={"window_s": 5.0},
            ),
        ),
        series=(_series(),),
    )


def _dense_only_result() -> ProcessorResult:
    return ProcessorResult(spec=_spec(), metrics=(), series=(_series(),))


@pytest.mark.postgres
def test_pipeline_metric_provenance_is_complete_and_idempotent(
    postgres_url: str,
    test_db_schema: str,
    tmp_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    from dynamis.pipeline.persist import persist_source
    from dynamis.registry import source_by_id, validate_registry
    from dynamis.storage.control_plane import control_plane_engine

    monkeypatch.setenv(ENV_POSTGRES_URL, postgres_url)
    monkeypatch.setenv(ENV_DB_SCHEMA, test_db_schema)
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
    checked_at = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
    artifact_rows = (
        {
            "artifact_id": "proc-run-test.derived",
            "dataset_id": "white-cmj-acc-grf",
            "run_id": "run-test",
            "artifact_type": "processed_series.derived",
            "layer": "gold",
            "relative_path": "gold/white-cmj-acc-grf/processing/x/derived.parquet",
            "checksum_sha256": "d" * 64,
            "byte_size": 1024,
            "row_count": 3,
            "created_at": checked_at,
            "artifact_metadata": {"series_name": "derived"},
        },
    )
    try:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        command.upgrade(config, "head")
        registry = validate_registry()
        with control.begin() as connection:
            persist_source(connection, source_by_id(registry, "white-cmj-acc-grf"))

        def persist_once() -> dict[str, int]:
            with control.begin() as connection:
                return persist_processing_result(
                    connection,
                    dataset_id="white-cmj-acc-grf",
                    run_id="run-test",
                    result=_result(),
                    input_checksums=("e" * 64,),
                    computed_at=checked_at,
                    code_sha="f" * 40,
                    artifact_rows=artifact_rows,
                )

        first = persist_once()
        second = persist_once()
        assert first["algorithm_spec"] == 1
        assert first["derived_metric"] == 1
        assert first["processing_artifact"] == 1
        assert first["metric_definition"] == 1
        assert second["derived_metric"] == 1
        assert second["processing_artifact"] == 1
        assert second["metric_definition"] == 0

        with control.begin() as connection:
            dense_only = persist_processing_result(
                connection,
                dataset_id="white-cmj-acc-grf",
                run_id="run-test-dense-only",
                result=_dense_only_result(),
                input_checksums=("h" * 64,),
                computed_at=checked_at,
                code_sha="f" * 40,
            )
        assert dense_only["metric_definition"] == 0
        assert dense_only["derived_metric"] == 0

        with control.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT derived_metric_id, dataset_id, metric_id, run_id, si_unit, "
                    "measurement_class, value_num, input_checksums, provenance "
                    "FROM derived_metric ORDER BY derived_metric_id"
                )
            ).fetchall()
            run = connection.execute(
                text(
                    "SELECT run_id, dataset_id, algorithm_id, status, code_git_sha, "
                    "parameters_hash, input_checksums FROM processing_run "
                    "WHERE run_id = 'run-test'"
                )
            ).fetchall()
            # The dense-only run is persisted as a run with no scalar metrics.
            dense_only_runs = connection.execute(
                text("SELECT count(*) FROM processing_run WHERE run_id = 'run-test-dense-only'")
            ).scalar_one()
            metric_rows = connection.execute(
                text("SELECT count(*) FROM derived_metric")
            ).scalar_one()
            artifact_count = connection.execute(
                text("SELECT count(*) FROM processing_artifact")
            ).scalar_one()

        assert metric_rows == 1
        assert artifact_count == 1
        assert len(rows) == 1
        assert len(run) == 1
        assert dense_only_runs == 1
        metric = rows[0]
        assert metric.dataset_id == "white-cmj-acc-grf"
        assert metric.metric_id == "test.persistence.scalar"
        assert metric.measurement_class == "PIPELINE_DERIVED"
        assert metric.value_num == pytest.approx(2.5)
        assert metric.si_unit == "m"
        assert metric.input_checksums == ["e" * 64]
        provenance = metric.provenance
        assert provenance["origin"] == "pipeline-computed"
        assert provenance["algorithm_id"] == "test.persistence"
        assert provenance["algorithm_version"] == "1.0.0"
        assert provenance["parameters_hash"] == _spec().parameters_hash
        assert provenance["code_git_sha"] == "f" * 40
        assert provenance["run_id"] == "run-test"
        assert provenance["input_checksums"] == ["e" * 64]
        assert provenance["window_s"] == 5.0

        run_row = run[0]
        assert run_row.algorithm_id == "test.persistence"
        assert run_row.status == "completed"
        assert run_row.code_git_sha == "f" * 40
        assert run_row.parameters_hash == _spec().parameters_hash
        assert run_row.input_checksums == ["e" * 64]

        # A corrected input changes the run but not the metric identity; the
        # stored row must converge to the corrected value instead of being
        # silently discarded by DO NOTHING.
        with control.begin() as connection:
            corrected = persist_processing_result(
                connection,
                dataset_id="white-cmj-acc-grf",
                run_id="run-test-corrected",
                result=_result(value=3.5),
                input_checksums=("g" * 64,),
                computed_at=checked_at,
                code_sha="f" * 40,
            )
        assert corrected["derived_metric"] == 1
        with control.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT count(*), max(value_num), max(run_id), max(input_checksums::text) "
                    "FROM derived_metric"
                )
            ).fetchone()
        assert row is not None
        assert row[0] == 1
        assert row[1] == pytest.approx(3.5)
        assert row[2] == "run-test-corrected"
        assert '"' + "g" * 64 + '"' in row[3]
    finally:
        control.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        admin.dispose()
