"""Source-derived metric import: honest provenance and idempotent persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from dynamis.config import ENV_DB_SCHEMA, ENV_POSTGRES_URL, repository_root
from dynamis.contracts import MeasurementClass
from dynamis.pipeline.source_metrics import SourceMetricObservation, persist_source_metrics

CHECKSUM = "a" * 64


def _observation(**overrides) -> SourceMetricObservation:
    payload = {
        "dataset_id": "white-cmj-acc-grf",
        "metric_id": "source_jump_height",
        "name": "Source-provided countermovement jump height",
        "si_unit": "m",
        "measurement_class": MeasurementClass.SOURCE_DERIVED,
        "value": 0.42,
        "source_field": "jump_height",
        "source_key": "cmj_dataset_both.npz",
        "session_id": "white-s000",
        "subject_id": "white-s000",
        "trial_id": "white-s000-noarms-t00",
        "provenance": {"recomputed_by_dynamis": False},
    }
    payload.update(overrides)
    return SourceMetricObservation(**payload)  # type: ignore[arg-type]


def test_observation_rejects_non_source_classes() -> None:
    with pytest.raises(ValueError, match="SOURCE_DERIVED"):
        _observation(measurement_class=MeasurementClass.RAW_MEASURED)
    with pytest.raises(ValueError, match="SOURCE_DERIVED"):
        _observation(measurement_class=MeasurementClass.MODEL_ESTIMATED)


def test_observation_rejects_non_finite_values_and_bad_units() -> None:
    with pytest.raises(ValueError, match="finite"):
        _observation(value=float("nan"))
    with pytest.raises(ValueError):
        _observation(si_unit="BW")


def test_observation_provenance_marks_provider_origin() -> None:
    provenance = _observation().origin_provenance
    assert provenance["origin"] == "source-provided"
    assert provenance["imported_by"] == "dynamis"
    assert provenance["source_field"] == "jump_height"
    assert provenance["source_key"] == "cmj_dataset_both.npz"


def test_identity_is_content_addressed_and_stable() -> None:
    first = _observation()
    second = _observation(value=0.99)
    other_trial = _observation(trial_id="white-s000-arms-t00")
    assert first.derived_metric_id == second.derived_metric_id
    assert first.derived_metric_id != other_trial.derived_metric_id


def test_persistence_requires_a_verified_input_checksum() -> None:
    class _Connection:
        def execute(self, *_args, **_kwargs):  # pragma: no cover - must not be reached
            raise AssertionError("no statement may run without verified checksums")

    with pytest.raises(ValueError, match="Bronze checksum"):
        persist_source_metrics(
            _Connection(),
            dataset_id="white-cmj-acc-grf",
            run_id="run-x",
            observations=(_observation(),),
            input_checksums=("bad",),
            computed_at=datetime(2026, 9, 18, tzinfo=UTC),
        )


@pytest.mark.postgres
def test_source_metric_persistence_is_idempotent(
    postgres_url: str, test_db_schema: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    from dynamis.storage.control_plane import control_plane_engine
    from dynamis.storage.metadata import build_metadata

    monkeypatch.setenv(ENV_POSTGRES_URL, postgres_url)
    monkeypatch.setenv(ENV_DB_SCHEMA, test_db_schema)
    root = repository_root()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "infra" / "migrations"))
    config.set_main_option("sqlalchemy.url", postgres_url.replace("%", "%%"))
    engine = create_engine(postgres_url, future=True)
    tables = build_metadata().tables
    try:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        command.upgrade(config, "head")
        from dynamis.config import Settings

        settings = Settings(
            dataset_root=Path("."),
            database_root=Path("."),
            duckdb_path=Path("d.duckdb"),
            db_schema=test_db_schema,
        )
        control = control_plane_engine(settings, postgres_url)
        with control.begin() as connection:
            connection.execute(
                tables["license_policy"]
                .insert()
                .values(
                    policy_id="lic-test",
                    identifier=None,
                    status="unclear",
                    attribution_required=True,
                    noncommercial_only=False,
                    share_alike=False,
                    redistribution="prohibited",
                    local_only=True,
                    restrictions=["test"],
                )
            )
            connection.execute(
                tables["dataset_source"]
                .insert()
                .values(
                    dataset_id="white-cmj-acc-grf",
                    name="test",
                    provider="test",
                    upstream_urls=["https://example.invalid"],
                    doi=None,
                    domain="laboratory",
                    adapter_id="test",
                    v1_role="test",
                    initial_scope="test",
                    license_policy_id="lic-test",
                )
            )
            connection.execute(
                tables["algorithm_spec"]
                .insert()
                .values(
                    algorithm_id="white_cmj_adapter",
                    name="test",
                    version="1",
                    kind="adapter",
                    parameters={},
                    parameters_hash=None,
                )
            )
            connection.execute(
                tables["processing_run"]
                .insert()
                .values(
                    run_id="run-test",
                    dataset_id="white-cmj-acc-grf",
                    algorithm_id="white_cmj_adapter",
                    status="completed",
                    started_at=datetime(2026, 9, 18, tzinfo=UTC),
                    completed_at=datetime(2026, 9, 18, tzinfo=UTC),
                    input_checksums=[CHECKSUM],
                )
            )
            observations = (_observation(),)
            first = persist_source_metrics(
                connection,
                dataset_id="white-cmj-acc-grf",
                run_id="run-test",
                observations=observations,
                input_checksums=(CHECKSUM,),
                computed_at=datetime(2026, 9, 18, tzinfo=UTC),
            )
            second = persist_source_metrics(
                connection,
                dataset_id="white-cmj-acc-grf",
                run_id="run-test",
                observations=observations,
                input_checksums=(CHECKSUM,),
                computed_at=datetime(2026, 9, 18, tzinfo=UTC),
            )
            derived = connection.execute(text("SELECT count(*) FROM derived_metric")).scalar_one()
            definitions = connection.execute(
                text("SELECT count(*) FROM metric_definition")
            ).scalar_one()
            provenance = connection.execute(
                text("SELECT provenance FROM derived_metric LIMIT 1")
            ).scalar_one()
        control.dispose()
        assert first["derived_metric"] == 1
        assert second["derived_metric"] == 0  # idempotent on the same identity
        assert int(derived) == 1
        assert int(definitions) == 1
        assert provenance["origin"] == "source-provided"
        assert provenance["imported_by"] == "dynamis"
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        engine.dispose()
