"""Processing-run provenance must be generic, deterministic and issue-agnostic.

A run recorded by any adapter (DFL, White, GymAware, and later ones) must say
what actually ran --- dataset, session, algorithm --- and never encode the Linear
issue that commissioned the code, which would silently mislabel every later
rerun.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from dynamis.config import ENV_DB_SCHEMA, ENV_POSTGRES_URL, Settings, repository_root
from dynamis.contracts import Session
from dynamis.pipeline.ingest import IngestResult
from dynamis.pipeline.persist import processing_run_notes
from dynamis.pipeline.reconcile import ReconciliationReceipt
from dynamis.pipeline.streams import ProviderDomain


def _domain(dataset_id: str, session_id: str) -> ProviderDomain:
    """Minimal real domain: the run writer only needs a typed envelope."""
    return ProviderDomain(
        session=None,
        sessions=(Session(dataset_id=dataset_id, session_id=session_id),),
        subjects=(),
        participants=(),
        trials=(),
        streams=(),
    )


def _empty_result(dataset_id: str, session_id: str) -> IngestResult:
    return IngestResult(
        dataset_id=dataset_id,
        version="v1",
        session_id=session_id,
        source_keys=(),
        streams=(),
        quarantine_artifacts=(),
        reconciliation=ReconciliationReceipt(
            dataset_id=dataset_id,
            version="v1",
            session_id=session_id,
            source_keys=(),
            streams=(),
        ),
        receipt_path="",
        provider_domain=_domain(dataset_id, session_id),
    )


CHECKSUM = "c" * 64

ADAPTER_CASES = (
    ("dfl-sportec-idsse", "DFL-MAT-J03WPY", "sportec_idsse_adapter"),
    ("white-cmj-acc-grf", "white-cmj-release", "white_cmj_adapter"),
    ("gymaware-landmine-vision", "gymaware-landmine-release", "gymaware_landmine_adapter"),
)


def test_processing_run_notes_are_issue_agnostic() -> None:
    for dataset_id, session_id, algorithm_id in ADAPTER_CASES:
        note = processing_run_notes(
            dataset_id=dataset_id, session_id=session_id, algorithm_id=algorithm_id
        )
        assert "RES-97" not in note
        assert "RES-98" not in note
        assert "RES-99" not in note
        assert f"dataset={dataset_id}" in note
        assert f"session={session_id}" in note
        assert f"algorithm={algorithm_id}" in note


@pytest.mark.postgres
def test_persisted_processing_run_notes_are_generic_and_idempotent(
    postgres_url: str,
    test_db_schema: str,
    tmp_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    from dynamis.adapters.gymaware_landmine.adapter import (
        adapter_algorithm_spec as gymaware_algorithm_spec,
    )
    from dynamis.adapters.sportec_idsse.adapter import (
        adapter_algorithm_spec as idsse_algorithm_spec,
    )
    from dynamis.adapters.white_cmj.adapter import (
        adapter_algorithm_spec as white_algorithm_spec,
    )
    from dynamis.pipeline.persist import persist_ingest_run, persist_source
    from dynamis.registry import source_by_id, validate_registry
    from dynamis.storage.control_plane import control_plane_engine

    algorithms = {
        "dfl-sportec-idsse": idsse_algorithm_spec(),
        "white-cmj-acc-grf": white_algorithm_spec(),
        "gymaware-landmine-vision": gymaware_algorithm_spec(),
    }

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
    registry = validate_registry()
    try:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        command.upgrade(config, "head")

        def persist_all() -> None:
            with control.begin() as connection:
                for dataset_id, session_id, algorithm_id in ADAPTER_CASES:
                    algorithm = algorithms[dataset_id]
                    assert algorithm.algorithm_id == algorithm_id
                    persist_source(connection, source_by_id(registry, dataset_id))
                    persist_ingest_run(
                        connection,
                        dataset_id=dataset_id,
                        result=_empty_result(dataset_id, session_id),
                        domain=_domain(dataset_id, session_id),
                        algorithm=algorithm,
                        source_checksums=(CHECKSUM,),
                        run_id=f"run-{dataset_id}",
                    )

        persist_all()
        persist_all()  # a rerun refreshes the note and never duplicates the run

        with control.connect() as connection:
            rows = connection.execute(
                text("SELECT run_id, dataset_id, notes FROM processing_run ORDER BY run_id")
            ).fetchall()
        assert len(rows) == len(ADAPTER_CASES)
        for run_id, dataset_id, notes in rows:
            assert "RES-97" not in notes
            assert f"dataset={dataset_id}" in notes
            session_id = next(case[1] for case in ADAPTER_CASES if case[0] == dataset_id)
            assert f"session={session_id}" in notes
            assert "algorithm=" in notes
            assert run_id == f"run-{dataset_id}"
    finally:
        control.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        admin.dispose()
