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

HEAD_REVISION = "0009_multisport_semantic_catalog"


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


def test_offline_downgrade_of_0003_refuses_before_destructive_sql(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Offline mode cannot inspect persisted alignment evidence, so it refuses.

    The online row-count guard is covered by the PostgreSQL regression in
    ``test_sync_alignment.py``; this test proves the ``--sql`` path never emits
    the destructive drop for 0003.
    """
    monkeypatch.setenv(ENV_DB_SCHEMA, "dynamis_offline_check")
    monkeypatch.delenv(ENV_POSTGRES_URL, raising=False)
    config = _alembic_config("postgresql+psycopg://placeholder/dynamis")

    capsys.readouterr()  # discard any prior command output
    with pytest.raises(RuntimeError, match="offline"):
        command.downgrade(config, "0003_sync_alignment:0002_handedness_unspecified", sql=True)

    emitted = capsys.readouterr().out
    assert "DROP TABLE" not in emitted
    assert "alembic_version SET" not in emitted


def test_offline_downgrade_of_0004_refuses_before_destructive_sql(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The topology column cannot be dropped offline; landmark evidence is invisible."""
    monkeypatch.setenv(ENV_DB_SCHEMA, "dynamis_offline_check")
    monkeypatch.delenv(ENV_POSTGRES_URL, raising=False)
    config = _alembic_config("postgresql+psycopg://placeholder/dynamis")

    capsys.readouterr()
    with pytest.raises(RuntimeError, match="offline"):
        command.downgrade(config, "head:0003_sync_alignment", sql=True)

    emitted = capsys.readouterr().out
    assert "DROP COLUMN topology" not in emitted
    # Revisions above 0004 are lossless (index-only) and may stamp down to
    # 0004 before the refusal. What must never happen offline is stamping
    # past 0004, because that would claim the topology column was dropped.
    assert "version_num='0003_sync_alignment'" not in emitted


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
def test_v4_backfill_keeps_laboratory_sources_neutral_and_existing_sessions(
    postgres_url: str,
    test_db_schema: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_POSTGRES_URL, postgres_url)
    monkeypatch.setenv(ENV_DB_SCHEMA, test_db_schema)
    config = _alembic_config(postgres_url)
    engine = create_engine(postgres_url, future=True)

    sources = (
        ("dfl-sportec-idsse", "DFL", "football", "sportec_idsse", "match"),
        ("skillcorner-opendata", "SkillCorner", "football", "skillcorner_opendata", "match"),
        ("womens-soccer-positioning", "Zenodo", "football", "zenodo_wsoccer_positioning", "match"),
        ("spl-open-data", "SPL", "basketball", "spl_freethrow", "laboratory"),
        ("white-cmj-acc-grf", "Zenodo", "laboratory", "zenodo_white_cmj", "laboratory"),
        (
            "gymaware-landmine-vision",
            "Zenodo",
            "laboratory",
            "zenodo_gymaware_landmine",
            "laboratory",
        ),
    )
    try:
        _drop_schema(engine, test_db_schema)
        command.upgrade(config, "0008_skeleton_edges_seed")
        with engine.begin() as connection:
            connection.execute(
                text(
                    f'INSERT INTO "{test_db_schema}".license_policy '
                    "(policy_id, identifier, status, attribution_required, noncommercial_only, "
                    "share_alike, redistribution, local_only, restrictions) "
                    "VALUES ('test-license', 'CC-BY-4.0', 'declared', true, false, false, "
                    "'conditional', false, '[]'::jsonb)"
                )
            )
            for dataset_id, provider, domain, adapter, session_kind in sources:
                connection.execute(
                    text(
                        f'INSERT INTO "{test_db_schema}".dataset_source '
                        "(dataset_id, name, provider, upstream_urls, domain, adapter_id, "
                        "v1_role, initial_scope, license_policy_id) "
                        "VALUES (:dataset_id, :dataset_id, :provider, "
                        "'[\"https://example.org\"]'::jsonb, :domain, "
                        ":adapter, 'test source', 'test slice', 'test-license')"
                    ),
                    {
                        "dataset_id": dataset_id,
                        "provider": provider,
                        "domain": domain,
                        "adapter": adapter,
                    },
                )
                connection.execute(
                    text(
                        f'INSERT INTO "{test_db_schema}".dataset_version '
                        "(dataset_id, version, upstream_url) "
                        "VALUES (:dataset_id, 'v1', 'https://example.org/v1')"
                    ),
                    {"dataset_id": dataset_id},
                )
                connection.execute(
                    text(
                        f'INSERT INTO "{test_db_schema}".dataset_version_file '
                        "(dataset_id, version, key, size_bytes) "
                        "VALUES (:dataset_id, 'v1', 'release.json', 1)"
                    ),
                    {"dataset_id": dataset_id},
                )
                if session_kind == "match":
                    connection.execute(
                        text(
                            f'INSERT INTO "{test_db_schema}".session '
                            "(dataset_id, session_id, kind, label) "
                            "VALUES (:dataset_id, 'session-1', 'match', 'accepted match')"
                        ),
                        {"dataset_id": dataset_id},
                    )
            for dataset_id, team_suffix in (
                ("dfl-sportec-idsse", "dfl"),
                ("skillcorner-opendata", "sc"),
            ):
                for suffix in ("home", "away"):
                    subject_id = f"{team_suffix}-{suffix}"
                    team_id = f"{team_suffix}-team-{suffix}"
                    connection.execute(
                        text(
                            f'INSERT INTO "{test_db_schema}".subject '
                            "(dataset_id, subject_id, sex, cohort) "
                            "VALUES (:dataset_id, :subject_id, 'unspecified', :team_id)"
                        ),
                        {"dataset_id": dataset_id, "subject_id": subject_id, "team_id": team_id},
                    )
                    connection.execute(
                        text(
                            f'INSERT INTO "{test_db_schema}".session_participant '
                            "(dataset_id, session_id, subject_id, role, group_label) "
                            "VALUES (:dataset_id, 'session-1', :subject_id, 'player', :team_id)"
                        ),
                        {"dataset_id": dataset_id, "subject_id": subject_id, "team_id": team_id},
                    )
                connection.execute(
                    text(
                        f'INSERT INTO "{test_db_schema}".trial '
                        "(dataset_id, session_id, trial_id, label) "
                        "VALUES (:dataset_id, 'session-1', 'period-1', 'source period 1')"
                    ),
                    {"dataset_id": dataset_id},
                )
            connection.execute(
                text(
                    f'INSERT INTO "{test_db_schema}".clock '
                    "(clock_id, timebase) VALUES ('dfl-clock', 'session_monotonic')"
                )
            )
            connection.execute(
                text(
                    f'INSERT INTO "{test_db_schema}".synchronization_spec '
                    "(sync_spec_id, method, reference_clock_id) "
                    "VALUES ('dfl-sync', 'source_provided', 'dfl-clock')"
                )
            )
            connection.execute(
                text(
                    f'INSERT INTO "{test_db_schema}".sensor_stream '
                    "(dataset_id, stream_id, session_id, trial_id, modality, measurement_class, "
                    "clock_id, synchronization_spec_id, nominal_sampling_rate_hz) "
                    "VALUES ('dfl-sportec-idsse', 'tracking-1', 'session-1', 'period-1', "
                    "'tracking', 'RAW_MEASURED', 'dfl-clock', 'dfl-sync', 25.0)"
                )
            )
            connection.execute(
                text(
                    f'INSERT INTO "{test_db_schema}".sample_artifact '
                    "(artifact_id, dataset_id, session_id, stream_id, layer, relative_path, "
                    "format, compression, row_count, byte_size, checksum_sha256, schema_version) "
                    "VALUES ('dfl-artifact', 'dfl-sportec-idsse', 'session-1', 'tracking-1', "
                    "'silver', 'silver/tracking.parquet', 'parquet', 'zstd', 1, 1, :checksum, '1')"
                ),
                {"checksum": "a" * 64},
            )

        command.upgrade(config, "head")
        with engine.connect() as connection:
            session_count = connection.execute(
                text(f'SELECT count(*) FROM "{test_db_schema}".session')
            ).scalar_one()
            subject_count = connection.execute(
                text(f'SELECT count(*) FROM "{test_db_schema}".subject')
            ).scalar_one()
            catalog_rows = connection.execute(
                text(
                    f"SELECT dataset, sport_id, availability_state "
                    f'FROM "{test_db_schema}".source_catalog_entry ORDER BY dataset'
                )
            ).all()
            contests = connection.execute(
                text(
                    f'SELECT count(*) FROM "{test_db_schema}".contest '
                    "WHERE competition_edition_id IS NULL"
                )
            ).scalar_one()
            contest_ids = {
                row[0]
                for row in connection.execute(
                    text(
                        f'SELECT contest_id FROM "{test_db_schema}".contest '
                        "WHERE contest_id IS NOT NULL"
                    )
                )
            }
            team_ids = {
                row[0]
                for row in connection.execute(text(f'SELECT team_id FROM "{test_db_schema}".team'))
            }
            contexts = connection.execute(
                text(f'SELECT count(*) FROM "{test_db_schema}".session_sport_context')
            ).scalar_one()
            periods = connection.execute(
                text(f'SELECT count(*) FROM "{test_db_schema}".contest_period')
            ).scalar_one()
            grain = connection.execute(
                text(
                    "SELECT s.data_grain_kind, s.data_grain_axes, "
                    "a.data_grain_kind, a.data_grain_axes "
                    f'FROM "{test_db_schema}".sensor_stream s '
                    f'JOIN "{test_db_schema}".sample_artifact a '
                    "USING (dataset_id, stream_id) WHERE s.stream_id = 'tracking-1'"
                )
            ).one()
            sport_codes = {
                row[0]
                for row in connection.execute(text(f'SELECT code FROM "{test_db_schema}".sport'))
            }
        assert session_count == 3
        assert subject_count == 4
        assert contests == 2
        from dynamis.contracts.sports import SportsEntityKind, canonical_sports_id

        assert contest_ids == {
            canonical_sports_id(namespace, SportsEntityKind.CONTEST, "session-1")
            for namespace in ("sportec_idsse", "skillcorner_opendata")
        }
        assert team_ids == {
            canonical_sports_id(namespace, SportsEntityKind.TEAM, f"{prefix}-team-{side}")
            for namespace, prefix in (("sportec_idsse", "dfl"), ("skillcorner_opendata", "sc"))
            for side in ("home", "away")
        }
        assert contexts == 2
        assert periods == 2
        assert grain.data_grain_kind == "FRAME_SERIES"
        assert grain.data_grain_axes == ["contest", "period", "canonical_time", "entity"]
        assert grain[2] == "FRAME_SERIES"
        assert grain[3] == grain.data_grain_axes
        assert sport_codes == {"football", "basketball"}
        catalog_by_dataset = {row.dataset: row for row in catalog_rows}
        assert len(catalog_by_dataset) == len(sources)
        assert catalog_by_dataset["white-cmj-acc-grf"].sport_id is None
        assert catalog_by_dataset["gymaware-landmine-vision"].sport_id is None
        assert catalog_by_dataset["spl-open-data"].sport_id == "basketball"
        assert all(row.availability_state == "REGISTERED" for row in catalog_rows)
    finally:
        _drop_schema(engine, test_db_schema)
        engine.dispose()


@pytest.mark.postgres
def test_handedness_downgrade_refuses_rows_it_cannot_represent(
    postgres_url: str,
    test_db_schema: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_POSTGRES_URL, postgres_url)
    monkeypatch.setenv(ENV_DB_SCHEMA, test_db_schema)
    config = _alembic_config(postgres_url)
    engine = create_engine(postgres_url, future=True)

    def insert_frame(
        frame_id: str,
        handedness: str,
        description: str | None,
        axes: tuple[str, str, str] = ("unspecified", "unspecified", "unspecified"),
    ) -> None:
        with engine.begin() as connection:
            connection.execute(
                text(
                    f'INSERT INTO "{test_db_schema}".coordinate_frame '
                    "(frame_id, name, kind, handedness, x_direction, y_direction, "
                    "z_direction, origin_description, length_unit, description) "
                    "VALUES (:frame_id, 'test frame', 'sensor', :handedness, :x, :y, :z, "
                    "'origin', 'm', :description)"
                ),
                {
                    "frame_id": frame_id,
                    "handedness": handedness,
                    "description": description,
                    "x": axes[0],
                    "y": axes[1],
                    "z": axes[2],
                },
            )

    try:
        _drop_schema(engine, test_db_schema)
        command.upgrade(config, "head")
        insert_frame("refuse-downgrade", "unspecified", "explicitly undocumented")
        with pytest.raises(RuntimeError, match="cannot downgrade"):
            command.downgrade(config, "0001_bootstrap")

        with engine.begin() as connection:
            connection.execute(text(f'DELETE FROM "{test_db_schema}".coordinate_frame'))
        insert_frame("clean-downgrade", "right", None, axes=("east", "north", "up"))
        command.downgrade(config, "0001_bootstrap")
        with engine.connect() as connection:
            revision = connection.execute(
                text(f'SELECT version_num FROM "{test_db_schema}".alembic_version')
            ).scalar_one()
        assert revision == "0001_bootstrap"
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
