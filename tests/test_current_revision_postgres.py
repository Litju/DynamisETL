"""Run-scoped current revision on the control-plane serving paths.

A processor run is authoritative for its whole scope. When a corrected newer run
of the same algorithm covers a stream, identities the older run emitted but the
newer run no longer emits (RES-112 D-03: the ball as a locomotor entity) must
not stay current, and a tactical series name must resolve to one artifact.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text

from dynamis.config import ENV_DB_SCHEMA, ENV_POSTGRES_URL, Settings, repository_root


@pytest.mark.postgres
def test_newer_run_supersedes_its_whole_scope(
    postgres_url: str,
    test_db_schema: str,
    tmp_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alembic import command
    from alembic.config import Config

    from dynamis.pipeline.persist import persist_source
    from dynamis.processors import MetricDeclaration, ProcessorResult, ProcessorSpec, ScalarMetric
    from dynamis.processors.persistence import persist_processing_result
    from dynamis.registry import source_by_id, validate_registry
    from dynamis.serving.repository import MetricFilters, list_tactical_artifacts, query_metrics
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
    distance = MetricDeclaration(
        metric_id="test.revision.distance",
        name="Revision distance",
        si_unit="m",
        description="Run-scoped revision fixture.",
    )

    def result(parameters: dict, entities: tuple[str, ...]) -> ProcessorResult:
        return ProcessorResult(
            spec=ProcessorSpec(
                algorithm_id="test.revision",
                name="Revision test processor",
                version="1.0.0",
                description="Run-scoped revision fixture.",
                parameters=parameters,
            ),
            metrics=tuple(
                ScalarMetric(
                    declaration=distance,
                    value=float(index + 1),
                    session_id="session-1",
                    stream_id="tracking-1",
                    entity_id=entity,
                )
                for index, entity in enumerate(entities)
            ),
        )

    def tactical_artifact(run_id: str, parameters_hash: str) -> tuple[dict, ...]:
        return (
            {
                "artifact_id": f"{run_id}-team_geometry",
                "dataset_id": "white-cmj-acc-grf",
                "run_id": run_id,
                "artifact_type": "processed_series",
                "layer": "gold",
                "relative_path": f"gold/test/{parameters_hash}/tracking-1.team_geometry.parquet",
                "checksum_sha256": parameters_hash[0] * 64,
                "byte_size": 1,
                "row_count": 1,
                "artifact_metadata": {
                    "tactical_level": "A",
                    "series_name": "team_geometry",
                    "session_id": "session-1",
                    "stream_id": "tracking-1",
                },
            },
        )

    try:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        command.upgrade(config, "head")
        with control.begin() as connection:
            persist_source(connection, source_by_id(validate_registry(), "white-cmj-acc-grf"))
            old = result({"entity_object_types": None}, ("player-1", "ball"))
            new = result({"entity_object_types": ["player"]}, ("player-1",))
            persist_processing_result(
                connection,
                dataset_id="white-cmj-acc-grf",
                run_id="run-old",
                result=old,
                input_checksums=("a" * 64,),
                computed_at=datetime(2026, 9, 1, tzinfo=UTC),
                code_sha="b" * 40,
                artifact_rows=tactical_artifact("run-old", old.spec.parameters_hash),
            )
            persist_processing_result(
                connection,
                dataset_id="white-cmj-acc-grf",
                run_id="run-new",
                result=new,
                input_checksums=("a" * 64,),
                computed_at=datetime(2026, 9, 2, tzinfo=UTC),
                code_sha="c" * 40,
                artifact_rows=tactical_artifact("run-new", new.spec.parameters_hash),
            )
        with control.connect() as connection:
            page = query_metrics(
                connection,
                gold_schema=f"{test_db_schema}_gold_absent",
                filters=MetricFilters(dataset_id="white-cmj-acc-grf"),
                limit=50,
                offset=0,
            )
            artifacts = list_tactical_artifacts(connection, dataset_id="white-cmj-acc-grf")
        assert page.source == "control_plane"
        assert [(row.entity_id, row.run_id) for row in page.rows] == [("player-1", "run-new")]
        assert page.total == 1
        assert [item.artifact_id for item in artifacts] == ["run-new-team_geometry"]
    finally:
        control.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        admin.dispose()
