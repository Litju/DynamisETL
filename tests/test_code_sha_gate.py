"""Persisted scientific processor runs require a full code Git SHA.

Production/container execution injects ``DYNAMIS_CODE_GIT_SHA``; a development
machine may opt into unknown-SHA artifact work with
``DYNAMIS_ALLOW_UNKNOWN_CODE_SHA=1``, but such runs are visible in provenance and
the Gold serving publication gate refuses them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from dynamis.config import ENV_DB_SCHEMA, ENV_POSTGRES_URL, Settings, repository_root
from dynamis.processors.persistence import (
    ENV_ALLOW_UNKNOWN_CODE_SHA,
    assert_persistable_code_sha,
    dev_allow_unknown_code_sha,
    persist_processing_result,
)
from dynamis.processors.runtime import collect_input, execute_processor
from dynamis.processors.spec import (
    MetricDeclaration,
    ProcessorResult,
    ProcessorSpec,
    ScalarMetric,
)


def _result() -> ProcessorResult:
    spec = ProcessorSpec(
        algorithm_id="test.sha_gate",
        name="SHA gate test processor",
        version="1.0.0",
        description="Minimal result for the code-SHA persistence gate.",
        parameters={"window_s": 1.0},
    )
    return ProcessorResult(
        spec=spec,
        metrics=(
            ScalarMetric(
                declaration=MetricDeclaration(
                    metric_id="test.sha_gate.value",
                    name="SHA gate value",
                    si_unit="m",
                    description="Minimal metric.",
                ),
                value=1.0,
            ),
        ),
    )


def test_full_sha_is_required_and_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_ALLOW_UNKNOWN_CODE_SHA, raising=False)
    assert dev_allow_unknown_code_sha() is False
    with pytest.raises(ValueError, match="full 40-character code Git SHA"):
        assert_persistable_code_sha(None, allow_unknown=False)
    with pytest.raises(ValueError, match="40-character lower-case Git SHA"):
        assert_persistable_code_sha("A" * 40, allow_unknown=True)
    with pytest.raises(ValueError, match="40-character lower-case Git SHA"):
        assert_persistable_code_sha("abc", allow_unknown=True)
    accepted = assert_persistable_code_sha("f" * 40, allow_unknown=False)
    assert accepted is None


def test_development_flag_is_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_ALLOW_UNKNOWN_CODE_SHA, "1")
    assert dev_allow_unknown_code_sha() is True
    assert_persistable_code_sha(None, allow_unknown=True)
    monkeypatch.setenv(ENV_ALLOW_UNKNOWN_CODE_SHA, "no")
    assert dev_allow_unknown_code_sha() is False


def test_persist_refuses_unknown_sha_before_any_write() -> None:
    with pytest.raises(ValueError, match="code Git SHA"):
        persist_processing_result(
            None,
            dataset_id="white-cmj-acc-grf",
            run_id="run-sha-gate",
            result=_result(),
            input_checksums=("e" * 64,),
            computed_at=datetime.now(UTC),
            code_sha=None,
            allow_unknown_code_sha=False,
        )


def test_execute_processor_refuses_unknown_sha_before_materializing(
    tmp_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dynamis.processors.runtime as runtime

    monkeypatch.delenv(ENV_ALLOW_UNKNOWN_CODE_SHA, raising=False)
    monkeypatch.setattr(runtime, "code_git_sha", lambda *args, **kwargs: None)
    source = tmp_settings.dataset_root / "fixtures" / "input.bin"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"deterministic input")
    engine = create_engine("sqlite://", future=True)
    with pytest.raises(ValueError, match="code Git SHA"):
        execute_processor(
            tmp_settings,
            result=_result(),
            dataset_id="white-cmj-acc-grf",
            inputs=(collect_input(tmp_settings, source, role="fixture", row_count=1),),
            series_key="stream-1",
            engine=engine,
            allow_unknown_code_sha=False,
        )
    # The refusal happens before any artifact materialization.
    gold_root: Path = tmp_settings.dataset_root / "gold"
    assert not gold_root.exists()


@pytest.mark.postgres
def test_serving_publication_refuses_null_sha_processor_runs(
    postgres_url: str,
    test_db_schema: str,
    tmp_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from dynamis.gold.publish import assert_serving_code_sha
    from dynamis.storage.control_plane import control_plane_engine

    monkeypatch.setenv(ENV_POSTGRES_URL, postgres_url)
    monkeypatch.setenv(ENV_DB_SCHEMA, test_db_schema)
    root = repository_root()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "infra" / "migrations"))
    config.set_main_option("sqlalchemy.url", postgres_url.replace("%", "%%"))
    settings = Settings(
        dataset_root=tmp_settings.dataset_root,
        database_root=tmp_settings.database_root,
        duckdb_path=tmp_settings.duckdb_path,
        db_schema=test_db_schema,
    )
    control = control_plane_engine(settings, postgres_url)
    admin = create_engine(postgres_url, future=True)
    try:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        command.upgrade(config, "head")
        with control.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO license_policy (policy_id, identifier, status, "
                    "attribution_required, noncommercial_only, share_alike, redistribution, "
                    "local_only) VALUES ('white-cmj-acc-grf', 'CC BY 4.0', 'declared', true, "
                    "false, false, 'conditional', false)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO dataset_source (dataset_id, name, provider, upstream_urls, "
                    "domain, adapter_id, v1_role, initial_scope, license_policy_id) "
                    "VALUES ('white-cmj-acc-grf', 'White CMJ', 'test', '[\"https://x\"]'::jsonb, "
                    "'force', 'test-adapter', 'role', 'scope', 'white-cmj-acc-grf')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO algorithm_spec (algorithm_id, name, version, kind) "
                    "VALUES ('test.null_sha', 'Null SHA processor', '1.0.0', 'processor')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO processing_run (run_id, dataset_id, algorithm_id, status, "
                    "started_at, completed_at, input_checksums) VALUES "
                    "('run-null-sha', 'white-cmj-acc-grf', 'test.null_sha', 'completed', now(), "
                    "now(), '[\"e\"]'::jsonb)"
                )
            )
        with control.connect() as connection:
            assert_serving_code_sha(connection, allow_unknown=True)
            with pytest.raises(RuntimeError, match="without a code Git SHA"):
                assert_serving_code_sha(connection, allow_unknown=False)
    finally:
        control.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        admin.dispose()
