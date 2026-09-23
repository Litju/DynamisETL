"""PostgreSQL integration for the serving repository and API.

Builds the control plane from registered fixtures only, then exercises the real
SQL paths: catalog aggregates, session/stream explorer, current-revision metrics
(control plane and published Gold), methodology, provenance lineage, quality,
runs, rights, and a bounded dense window over a canonical sample artifact.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from dynamis.config import ENV_DB_SCHEMA, ENV_POSTGRES_URL, Settings, repository_root
from dynamis.serving.app import PostgresServingBackend, create_app


@pytest.mark.postgres
def test_postgres_serving_end_to_end(
    postgres_url: str,
    test_db_schema: str,
    tmp_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alembic import command
    from alembic.config import Config

    from dynamis.gold.build import build_gold
    from dynamis.gold.export import export_serving
    from dynamis.gold.publish import ENV_GOLD_SCHEMA, publish_gold
    from dynamis.pipeline.persist import persist_source
    from dynamis.processors import MetricDeclaration, ProcessorResult, ProcessorSpec, ScalarMetric
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
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{gold_schema}" CASCADE'))
        command.upgrade(config, "head")
        with control.begin() as connection:
            persist_source(connection, source_by_id(validate_registry(), "white-cmj-acc-grf"))
        spec = ProcessorSpec(
            algorithm_id="test.serving",
            name="Serving test processor",
            version="1.0.0",
            description="Serving integration fixture.",
            parameters={"window_s": 5.0},
        )
        result = ProcessorResult(
            spec=spec,
            metrics=(
                ScalarMetric(
                    declaration=MetricDeclaration(
                        metric_id="test.serving.distance",
                        name="Serving distance",
                        si_unit="m",
                        description="Serving integration metric.",
                    ),
                    value=42.0,
                    session_id="session-1",
                    subject_id="subject-1",
                    stream_id="lpt-1",
                    provenance={"gap_policy": {"strategy": "contiguous_segments"}},
                ),
            ),
        )
        with control.begin() as connection:
            persist_processing_result(
                connection,
                dataset_id="white-cmj-acc-grf",
                run_id="run-serving",
                result=result,
                input_checksums=("a" * 64,),
                computed_at=datetime(2026, 9, 18, tzinfo=UTC),
                code_sha="b" * 40,
            )
            _insert_explorer_rows(connection, tmp_settings.dataset_root)
        backend = PostgresServingBackend(settings, control)
        client = TestClient(create_app(backend=backend))

        status = client.get("/api/serving/status")
        assert status.status_code == 200
        assert status.json()["gold_published"] is False

        datasets = client.get("/api/catalog/datasets").json()
        assert [item["dataset_id"] for item in datasets] == ["white-cmj-acc-grf"]
        assert "attribution required" in datasets[0]["license"]["notice"]
        assert datasets[0]["metric_count"] == 1

        sessions = client.get("/api/catalog/datasets/white-cmj-acc-grf/sessions").json()
        assert sessions[0]["session_id"] == "serving-session"
        assert sessions[0]["participant_count"] == 1
        detail = client.get("/api/catalog/datasets/white-cmj-acc-grf/sessions/serving-session")
        assert detail.status_code == 200
        payload = detail.json()
        assert payload["streams"][0]["modality"] == "lpt"
        # RES-112 S-07: registered human labels are served with the participant.
        assert payload["participants"][0]["cohort"] == "Fixture cohort"
        assert payload["participants"][0]["notes"] == "shirt 7 (Fixture Athlete)"
        assert payload["streams"][0]["si_units"] == ["m"]
        assert payload["streams"][0]["sample_artifact_ids"] == ["serving-sample"]

        metrics = client.get("/api/metrics", params={"metric_id": "test.serving.distance"}).json()
        assert metrics["source"] == "control_plane"
        assert metrics["total"] == 1
        metric = metrics["rows"][0]
        assert metric["measurement_class"] == "PIPELINE_DERIVED"
        assert metric["code_git_sha"] == "b" * 40
        assert metric["run_id"] == "run-serving"
        assert metric["provenance"]["gap_policy"]["strategy"] == "contiguous_segments"

        methodology = client.get("/api/metrics/methodology/test.serving.distance").json()
        assert methodology["algorithm"]["algorithm_id"] == "test.serving"
        assert methodology["algorithm"]["code_git_sha"] == "b" * 40

        provenance = client.get(
            f"/api/derived-metrics/{metric['derived_metric_id']}/provenance"
        ).json()
        kinds = {node["kind"] for node in provenance["nodes"]}
        assert {"dataset", "algorithm", "processing_run", "derived_metric", "gold_row"} <= kinds
        assert any(node["kind"] == "input_checksum" for node in provenance["nodes"])
        assert provenance["provenance"]["code_git_sha"] == "b" * 40

        quality = client.get("/api/quality").json()
        assert quality["total"] == 1
        assert quality["rows"][0]["state"] == "VALID"

        runs = client.get("/api/runs").json()
        assert runs["rows"][0]["run_id"] == "run-serving"
        assert runs["rows"][0]["code_git_sha"] == "b" * 40

        rights = client.get("/api/rights").json()
        assert rights["policies"][0]["dataset_ids"] == ["white-cmj-acc-grf"]

        window = client.get(
            "/api/artifacts/serving-sample/window",
            params={"from_ns": 0, "to_ns": 20_000_000, "max_points": 2},
        )
        assert window.status_code == 200
        window_body = window.json()
        assert window_body["meta"]["source_rows"] == 3
        assert window_body["meta"]["reduction"]["method"] == "min_max_envelope_per_time_bucket"
        assert window_body["meta"]["units"] == {}  # fixture Parquet carries no contract metadata

        # Publish Gold and confirm the metrics path switches to the serving mart.
        export_serving(settings, control)
        built = build_gold(settings)
        assert built.success
        publish_gold(settings, control)
        gold_metrics = client.get(
            "/api/metrics", params={"metric_id": "test.serving.distance"}
        ).json()
        assert gold_metrics["source"] == "gold"
        assert gold_metrics["rows"][0]["run_id"] == "run-serving"
        assert gold_metrics["rows"][0]["code_git_sha"] == "b" * 40
        published_status = client.get("/api/serving/status").json()
        assert published_status["gold_published"] is True
    finally:
        control.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{gold_schema}" CASCADE'))
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        admin.dispose()


def _insert_explorer_rows(connection, dataset_root: Path) -> None:
    """One subject/session/trial/stream plus a canonical Parquet sample artifact."""
    relative = Path("silver") / "dataset_id=white-cmj-acc-grf" / "lpt" / "serving-sample.parquet"
    target = dataset_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "dataset_id": pa.array(["white-cmj-acc-grf"] * 3, type=pa.string()),
            "session_id": pa.array(["serving-session"] * 3, type=pa.string()),
            "trial_id": pa.array(["serving-trial"] * 3, type=pa.string()),
            "subject_id": pa.array(["subject-1"] * 3, type=pa.string()),
            "device_id": pa.array([None, None, None], type=pa.string()),
            "stream_id": pa.array(["lpt-1"] * 3, type=pa.string()),
            "sample_index": pa.array([0, 1, 2], type=pa.int64()),
            "t_rel_ns": pa.array([0, 10_000_000, 20_000_000], type=pa.int64()),
            "timestamp_utc_ns": pa.array([None, None, None], type=pa.int64()),
            "nominal_sampling_rate_hz": pa.array([100.0] * 3, type=pa.float64()),
            "measurement_class": pa.array(["RAW_MEASURED"] * 3, type=pa.string()),
            "clock_id": pa.array(["serving-clock"] * 3, type=pa.string()),
            "synchronization_spec_id": pa.array(["serving-sync"] * 3, type=pa.string()),
            "coordinate_frame_id": pa.array(["serving-frame"] * 3, type=pa.string()),
            "x_m": pa.array([0.0, 1.0, 2.0], type=pa.float64()),
            "y_m": pa.array([0.0, 0.5, 1.0], type=pa.float64()),
            "z_m": pa.array([0.0, 0.0, 0.0], type=pa.float64()),
        }
    )
    pq.write_table(table, target, compression="zstd")
    byte_size = target.stat().st_size
    connection.execute(
        text("INSERT INTO clock (clock_id, timebase) VALUES ('serving-clock', 'session_monotonic')")
    )
    connection.execute(
        text(
            "INSERT INTO coordinate_frame (frame_id, name, kind, handedness, x_direction, "
            "y_direction, z_direction, origin_description) VALUES "
            "('serving-frame', 'Serving frame', 'laboratory', 'right', 'x', 'y', 'z', "
            "'fixture origin')"
        )
    )
    connection.execute(
        text(
            "INSERT INTO synchronization_spec (sync_spec_id, method, reference_clock_id) "
            "VALUES ('serving-sync', 'unknown', 'serving-clock')"
        )
    )
    connection.execute(
        text(
            "INSERT INTO subject (dataset_id, subject_id, sex, cohort, notes) "
            "VALUES ('white-cmj-acc-grf', 'subject-1', 'unspecified', 'Fixture cohort', "
            "'shirt 7 (Fixture Athlete)')"
        )
    )
    connection.execute(
        text(
            'INSERT INTO "session" (dataset_id, session_id, kind) '
            "VALUES ('white-cmj-acc-grf', 'serving-session', 'laboratory')"
        )
    )
    connection.execute(
        text(
            "INSERT INTO session_participant (dataset_id, session_id, subject_id, role) "
            "VALUES ('white-cmj-acc-grf', 'serving-session', 'subject-1', 'participant')"
        )
    )
    connection.execute(
        text(
            "INSERT INTO trial (dataset_id, session_id, trial_id, subject_id) "
            "VALUES ('white-cmj-acc-grf', 'serving-session', 'serving-trial', 'subject-1')"
        )
    )
    connection.execute(
        text(
            "INSERT INTO sensor_stream (dataset_id, stream_id, session_id, trial_id, subject_id, "
            "modality, measurement_class, clock_id, synchronization_spec_id, "
            "coordinate_frame_id, nominal_sampling_rate_hz, si_units, source_unit) VALUES "
            "('white-cmj-acc-grf', 'lpt-1', 'serving-session', 'serving-trial', 'subject-1', "
            "'lpt', 'RAW_MEASURED', 'serving-clock', 'serving-sync', 'serving-frame', 100.0, "
            "'[\"m\"]'::jsonb, 'm')"
        )
    )
    connection.execute(
        text(
            "INSERT INTO sample_artifact (artifact_id, dataset_id, session_id, stream_id, layer, "
            "relative_path, format, compression, row_count, byte_size, checksum_sha256, "
            "schema_version, coordinate_frame_id, synchronization_spec_id) VALUES "
            "('serving-sample', 'white-cmj-acc-grf', 'serving-session', 'lpt-1', 'silver', "
            ":relative_path, 'parquet', 'zstd', 3, :byte_size, :checksum, '1', "
            "'serving-frame', 'serving-sync')"
        ),
        {
            "relative_path": relative.as_posix(),
            "byte_size": byte_size,
            "checksum": "c" * 64,
        },
    )
    connection.execute(
        text(
            "INSERT INTO quality_issue (issue_id, dataset_id, session_id, stream_id, rule, "
            "severity, state, evidence, detected_at) VALUES "
            "('issue-1', 'white-cmj-acc-grf', 'serving-session', 'lpt-1', "
            "'lpt.axis_drop', 'WARNING', 'VALID', '{\"dropped\": 2}'::jsonb, now())"
        )
    )
