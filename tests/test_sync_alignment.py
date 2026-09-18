"""Durable sync-alignment authority: contract -> domain -> PostgreSQL -> query.

The PostgreSQL part is gated on ``DYNAMIS_TEST_POSTGRES_URL``. The synthetic
White fixture proves that only *accepted* trials produce alignments, that every
alignment survives persistence with all declared fields intact, and that a rerun
never duplicates rows.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

import synthetic_lab_providers as providers
from dynamis.config import ENV_DB_SCHEMA, ENV_POSTGRES_URL, Settings, repository_root
from dynamis.contracts import (
    MeasurementClass,
    Modality,
    SensorStream,
    Session,
    SyncAlignment,
)
from dynamis.pipeline.ingest import ingest_white_cmj
from dynamis.pipeline.streams import ProviderDomain, SourceAuthorities
from dynamis.registry import source_by_id, validate_registry

CHECKSUM = "b" * 64
SYNC_ALIGNMENT_COLUMNS = (
    "dataset_id",
    "source_stream_id",
    "target_stream_id",
    "sync_spec_id",
    "offset_ns",
    "scale",
    "notes",
)


def _alignment(source: str, target: str, **overrides: object) -> SyncAlignment:
    payload: dict[str, object] = {
        "source_stream_id": source,
        "target_stream_id": target,
        "offset_ns": 123_456,
        "scale": 1.25,
        "sync_spec_id": "sync-spec-declared",
        "notes": "declared alignment for round-trip",
    }
    payload.update(overrides)
    return SyncAlignment.model_validate(payload)


def test_contract_rejects_self_alignment_and_invalid_scales() -> None:
    with pytest.raises(ValueError, match="itself"):
        _alignment("stream-a", "stream-a")
    with pytest.raises(ValueError):
        _alignment("stream-a", "stream-b", scale=0.0)
    with pytest.raises(ValueError):
        _alignment("stream-a", "stream-b", scale=-1.0)
    with pytest.raises(ValueError):
        _alignment("stream-a", "stream-b", scale=float("nan"))
    with pytest.raises(ValueError):
        _alignment("stream-a", "stream-b", scale=float("inf"))


def _sensor_stream(dataset_id: str, stream_id: str, modality: Modality) -> SensorStream:
    return SensorStream(
        dataset_id=dataset_id,
        session_id="session-a",
        stream_id=stream_id,
        modality=modality,
        measurement_class=MeasurementClass.SOURCE_DERIVED,
        clock_id="clock-a",
        synchronization_spec_id="sync-a",
    )


def _domain(alignment: SyncAlignment, *, same_dataset: bool = False) -> ProviderDomain:
    return ProviderDomain(
        session=None,
        sessions=(Session(dataset_id="dataset-a", session_id="session-a"),),
        subjects=(),
        participants=(),
        trials=(),
        streams=(
            _sensor_stream("dataset-a", "stream-a", Modality.FORCE),
            _sensor_stream("dataset-a" if same_dataset else "dataset-b", "stream-b", Modality.IMU),
        ),
        authorities=SourceAuthorities(alignments=(alignment,)),
    )


def test_alignment_rows_reject_dangling_and_cross_dataset_references() -> None:
    from dynamis.pipeline.persist import _alignment_rows

    with pytest.raises(ValueError, match="outside the domain"):
        _alignment_rows(_domain(_alignment("stream-a", "stream-missing")))
    with pytest.raises(ValueError, match="spans datasets"):
        _alignment_rows(_domain(_alignment("stream-a", "stream-b")))

    built = _alignment_rows(_domain(_alignment("stream-a", "stream-b"), same_dataset=True))
    assert built == [
        {
            "dataset_id": "dataset-a",
            "source_stream_id": "stream-a",
            "target_stream_id": "stream-b",
            "sync_spec_id": "sync-spec-declared",
            "offset_ns": 123_456,
            "scale": 1.25,
            "notes": "declared alignment for round-trip",
        }
    ]


@pytest.mark.postgres
def test_white_synthetic_alignments_round_trip_and_are_idempotent(
    postgres_url: str,
    test_db_schema: str,
    tmp_settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    from dynamis.pipeline.persist import persist_domain, persist_source
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
    try:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        command.upgrade(config, "head")

        npz = providers.write_white_npz(tmp_path / "cmj_dataset_synthetic.npz")
        result = ingest_white_cmj(settings, npz_path=npz, version="v1")
        domain = result.provider_domain
        valid_trials = int(result.domain["valid_trials"])
        assert valid_trials == 3
        assert len(domain.authorities.alignments) == valid_trials

        with control.begin() as connection:
            source = source_by_id(validate_registry(), "white-cmj-acc-grf")
            persist_source(connection, source)
            first = persist_domain(connection, domain)
            assert first["sync_alignment"] == valid_trials
            second = persist_domain(connection, domain)

        with control.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT dataset_id, source_stream_id, target_stream_id, sync_spec_id, "
                    "offset_ns, scale, notes FROM sync_alignment "
                    "ORDER BY source_stream_id, target_stream_id"
                )
            ).fetchall()
            stream_endpoints = connection.execute(
                text("SELECT stream_id FROM sensor_stream WHERE dataset_id = 'white-cmj-acc-grf'")
            ).scalars()

        assert second["sync_alignment"] == valid_trials  # refreshed, never duplicated
        assert len(rows) == valid_trials
        endpoints = set(stream_endpoints)
        expected = {
            (
                "white-cmj-acc-grf",
                alignment.source_stream_id,
                alignment.target_stream_id,
                alignment.sync_spec_id,
                alignment.offset_ns,
                alignment.scale,
                alignment.notes,
            )
            for alignment in domain.authorities.alignments
        }
        observed = {tuple(row) for row in rows}
        assert observed == expected
        for row in rows:
            assert row[0] == "white-cmj-acc-grf"
            assert row[1].startswith("force-")
            assert row[2].startswith("imu-")
            assert row[1].removeprefix("force-") == row[2].removeprefix("imu-")
            assert row[3] == "white-source-provided-takeoff-aligned"
            assert row[4] == 0
            assert row[5] == 1.0
            assert row[1] in endpoints and row[2] in endpoints

        # The dataset-scoped composite foreign keys make reusing a real stream
        # identity under another dataset impossible.
        with pytest.raises(IntegrityError):
            with control.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO sync_alignment (dataset_id, source_stream_id, "
                        "target_stream_id, sync_spec_id, offset_ns, scale) VALUES "
                        "('other-dataset', 'force-white-s000-noarms-t00', "
                        "'imu-white-s000-noarms-t00', 'white-source-provided-takeoff-aligned', "
                        "0, 1.0)"
                    )
                )
    finally:
        control.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        admin.dispose()


@pytest.mark.postgres
def test_postgresql_enforces_alignment_invariants(
    postgres_url: str,
    test_db_schema: str,
    tmp_settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    from dynamis.pipeline.persist import persist_domain, persist_source
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
    try:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        command.upgrade(config, "head")

        npz = providers.write_white_npz(tmp_path / "cmj_dataset_synthetic.npz")
        domain = ingest_white_cmj(settings, npz_path=npz, version="v1").provider_domain
        alignment = domain.authorities.alignments[0]
        with control.begin() as connection:
            persist_source(connection, source_by_id(validate_registry(), "white-cmj-acc-grf"))
            persist_domain(connection, domain)

        def attempt(sql: str) -> None:
            with pytest.raises(IntegrityError):
                with control.begin() as connection:
                    connection.execute(text(sql))

        base = (
            "INSERT INTO sync_alignment (dataset_id, source_stream_id, target_stream_id, "
            "sync_spec_id, offset_ns, scale) VALUES "
        )
        pair = (
            f"('white-cmj-acc-grf', '{alignment.source_stream_id}', "
            f"'{alignment.target_stream_id}', '{alignment.sync_spec_id}', 0, "
        )
        # source == target violates the self-reference check.
        attempt(
            "INSERT INTO sync_alignment (dataset_id, source_stream_id, target_stream_id, "
            "sync_spec_id, offset_ns, scale) VALUES "
            f"('white-cmj-acc-grf', '{alignment.source_stream_id}', "
            f"'{alignment.source_stream_id}', '{alignment.sync_spec_id}', 0, 1.0)"
        )
        attempt(base + pair + "0.0)")
        attempt(base + pair + "'NaN'::double precision)")
        attempt(base + pair + "'Infinity'::double precision)")
        # Duplicate deterministic identity is rejected by the primary key.
        attempt(base + pair + "1.0)")
    finally:
        control.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        admin.dispose()


@pytest.mark.postgres
def test_sync_alignment_downgrade_refuses_persisted_evidence(
    postgres_url: str,
    test_db_schema: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    monkeypatch.setenv(ENV_POSTGRES_URL, postgres_url)
    monkeypatch.setenv(ENV_DB_SCHEMA, test_db_schema)
    root = repository_root()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "infra" / "migrations"))
    config.set_main_option("sqlalchemy.url", postgres_url.replace("%", "%%"))
    engine = create_engine(postgres_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(text(f'SET search_path TO "{test_db_schema}", public'))
            connection.execute(
                text(
                    "INSERT INTO license_policy (policy_id, identifier, status, "
                    "attribution_required, noncommercial_only, share_alike, redistribution, "
                    "local_only, restrictions) VALUES "
                    "('lic-test', 'CC-BY-4.0', 'declared', true, false, false, "
                    "'conditional', false, '[]'::jsonb)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO dataset_source (dataset_id, name, provider, upstream_urls, "
                    "doi, domain, adapter_id, v1_role, initial_scope, license_policy_id) "
                    "VALUES ('dataset-a', 'test', 'test', '[\"https://example.invalid\"]'::jsonb, "
                    "NULL, 'laboratory', 'adapter', 'role', 'scope', 'lic-test')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO session (dataset_id, session_id, kind) "
                    "VALUES ('dataset-a', 'session-a', 'laboratory')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO clock (clock_id, timebase) VALUES ('clock-a', 'device_monotonic')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO synchronization_spec (sync_spec_id, method, reference_clock_id, "
                    "notes) VALUES ('sync-a', 'source_provided', 'clock-a', 'declared')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO sensor_stream (dataset_id, stream_id, session_id, modality, "
                    "measurement_class, clock_id, synchronization_spec_id) VALUES "
                    "('dataset-a', 'force-a', 'session-a', 'force', 'SOURCE_DERIVED', "
                    "'clock-a', 'sync-a'), "
                    "('dataset-a', 'imu-a', 'session-a', 'imu', 'SOURCE_DERIVED', "
                    "'clock-a', 'sync-a')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO sync_alignment (dataset_id, source_stream_id, "
                    "target_stream_id, sync_spec_id, offset_ns, scale, notes) VALUES "
                    "('dataset-a', 'force-a', 'imu-a', 'sync-a', 0, 1.0, "
                    "'persisted evidence')"
                )
            )

        with pytest.raises(RuntimeError, match="cannot downgrade"):
            command.downgrade(config, "0002_handedness_unspecified")

        with engine.begin() as connection:
            connection.execute(text(f'SET search_path TO "{test_db_schema}", public'))
            connection.execute(text("DELETE FROM sync_alignment"))
        command.downgrade(config, "0002_handedness_unspecified")
        with engine.connect() as connection:
            revision = connection.execute(
                text(f'SELECT version_num FROM "{test_db_schema}".alembic_version')
            ).scalar_one()
            remaining = connection.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    f"WHERE table_schema = '{test_db_schema}' AND table_name = 'sync_alignment'"
                )
            ).scalar_one()
        assert revision == "0002_handedness_unspecified"
        assert int(remaining) == 0
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        engine.dispose()
