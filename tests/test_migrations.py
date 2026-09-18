"""Alembic: offline SQL generation and live PostgreSQL migration behaviour.

The PostgreSQL suite is skipped unless ``DYNAMIS_TEST_POSTGRES_URL`` is set. It
proves a clean database can be upgraded to head, that the intended schema and
tables exist, that downgrade/upgrade is symmetric, and that the head revision
matches the SQLAlchemy metadata with no autogenerate drift.
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from alembic.util import CommandError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from dynamis.config import ENV_DB_SCHEMA, ENV_POSTGRES_URL, repository_root
from dynamis.storage.tables import EXPECTED_TABLE_NAMES

HEAD_REVISION = "0002_handedness_unspecified"


def _alembic_config(url: str) -> Config:
    root = repository_root()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "infra" / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def _schema_tables(engine: Engine, schema: str) -> set[str]:
    return set(inspect(engine).get_table_names(schema=schema))


def _drop_schema(engine: Engine, schema: str) -> None:
    with engine.begin() as connection:
        connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


def test_offline_sql_is_self_contained_and_complete(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(ENV_DB_SCHEMA, "dynamis_offline_check")
    monkeypatch.delenv(ENV_POSTGRES_URL, raising=False)
    config = _alembic_config("postgresql+psycopg://placeholder/dynamis")

    command.upgrade(config, "head", sql=True)
    ddl = capsys.readouterr().out

    assert 'CREATE SCHEMA IF NOT EXISTS "dynamis_offline_check"' in ddl
    assert 'SET search_path TO "dynamis_offline_check", public' in ddl
    for table in sorted(EXPECTED_TABLE_NAMES):
        assert f"CREATE TABLE {table} " in ddl, table
    assert "DROP TABLE" not in ddl


@pytest.mark.postgres
def test_migration_lifecycle_on_postgresql(
    postgres_url: str,
    test_db_schema: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_POSTGRES_URL, postgres_url)
    monkeypatch.setenv(ENV_DB_SCHEMA, test_db_schema)
    config = _alembic_config(postgres_url)
    engine = create_engine(postgres_url, future=True)

    try:
        _drop_schema(engine, test_db_schema)

        # 1. Clean database -> head.
        command.upgrade(config, "head")
        tables = _schema_tables(engine, test_db_schema)
        assert EXPECTED_TABLE_NAMES <= tables
        assert "alembic_version" in tables
        assert len(tables) == len(EXPECTED_TABLE_NAMES) + 1

        with engine.connect() as connection:
            revision = connection.execute(
                text(f'SELECT version_num FROM "{test_db_schema}".alembic_version')
            ).scalar_one()
            schema_exists = connection.execute(
                text(
                    "SELECT count(*) FROM information_schema.schemata "
                    f"WHERE schema_name = '{test_db_schema}'"
                )
            ).scalar_one()
            check_count = int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM pg_constraint c "
                        "JOIN pg_namespace n ON n.oid = c.connamespace "
                        f"WHERE n.nspname = '{test_db_schema}' AND c.contype = 'c'"
                    )
                ).scalar_one()
            )
            foreign_keys = int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM pg_constraint c "
                        "JOIN pg_namespace n ON n.oid = c.connamespace "
                        f"WHERE n.nspname = '{test_db_schema}' AND c.contype = 'f'"
                    )
                ).scalar_one()
            )
        assert revision == HEAD_REVISION
        assert int(schema_exists) == 1
        assert check_count >= 60
        assert foreign_keys >= 40
        # The intended schema is the one that received the objects.
        assert not (EXPECTED_TABLE_NAMES & _schema_tables(engine, "public"))

        # 2. Downgrade symmetry.
        command.downgrade(config, "base")
        remaining = _schema_tables(engine, test_db_schema)
        assert not (EXPECTED_TABLE_NAMES & remaining), sorted(EXPECTED_TABLE_NAMES & remaining)

        # 3. Replay from clean state.
        command.upgrade(config, "head")
        assert EXPECTED_TABLE_NAMES <= _schema_tables(engine, test_db_schema)
    finally:
        _drop_schema(engine, test_db_schema)
        engine.dispose()


@pytest.mark.postgres
def test_head_revision_matches_metadata_without_drift(
    postgres_url: str,
    test_db_schema: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_POSTGRES_URL, postgres_url)
    monkeypatch.setenv(ENV_DB_SCHEMA, test_db_schema)
    config = _alembic_config(postgres_url)
    engine = create_engine(postgres_url, future=True)
    try:
        _drop_schema(engine, test_db_schema)
        command.upgrade(config, "head")
        try:
            command.check(config)
        except CommandError as exc:  # pragma: no cover - would indicate real drift
            raise AssertionError(f"migration drifted from metadata: {exc}") from exc
    finally:
        _drop_schema(engine, test_db_schema)
        engine.dispose()
