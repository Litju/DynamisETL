"""The control-plane source mirror must track the current registry rights.

``dataset_source`` is registry authority, not immutable evidence: when a source
licence is clarified, a rerun must converge the stored link to the current
content-addressed policy instead of leaving the source bound to a superseded
one. The superseded policy row itself stays auditable.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from dynamis.config import ENV_DB_SCHEMA, ENV_POSTGRES_URL, Settings, repository_root
from dynamis.contracts import LicensePolicy, LicenseStatus, RedistributionPolicy


def _policy(identifier: str, *, noncommercial: bool) -> LicensePolicy:
    return LicensePolicy(
        identifier=identifier,
        status=LicenseStatus.DECLARED,
        attribution_required=True,
        noncommercial_only=noncommercial,
        share_alike=False,
        redistribution=RedistributionPolicy.CONDITIONAL,
        local_only=False,
        restrictions=("Attribution required.",) if not noncommercial else ("Non-commercial.",),
    )


@pytest.mark.postgres
def test_persist_source_converges_the_rights_authority_link(
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
    from dynamis.storage.metadata import build_metadata

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
    tables = build_metadata().tables
    base = source_by_id(validate_registry(), "white-cmj-acc-grf")
    first = base.model_copy(update={"license": _policy("CC-BY-4.0", noncommercial=False)})
    second = base.model_copy(update={"license": _policy("CC-BY-NC-4.0", noncommercial=True)})
    try:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        command.upgrade(config, "head")

        # Simulate a previously persisted source bound to a stale unclear policy.
        with control.begin() as connection:
            connection.execute(
                tables["license_policy"]
                .insert()
                .values(
                    policy_id="lic-stale",
                    identifier=None,
                    status="unclear",
                    attribution_required=True,
                    noncommercial_only=False,
                    share_alike=False,
                    redistribution="prohibited",
                    local_only=True,
                    restrictions=["stale policy"],
                )
            )
            connection.execute(
                tables["dataset_source"]
                .insert()
                .values(
                    dataset_id="white-cmj-acc-grf",
                    name="stale",
                    provider="stale",
                    upstream_urls=["https://example.invalid"],
                    doi=None,
                    domain="laboratory",
                    adapter_id="stale",
                    v1_role="stale",
                    initial_scope="stale",
                    license_policy_id="lic-stale",
                )
            )

        def linked() -> tuple[str, str | None, str]:
            with control.connect() as connection:
                row = connection.execute(
                    text(
                        "SELECT ds.name, lp.identifier, lp.status FROM dataset_source ds "
                        "JOIN license_policy lp ON lp.policy_id = ds.license_policy_id "
                        "WHERE ds.dataset_id = 'white-cmj-acc-grf'"
                    )
                ).one()
                return (str(row[0]), row[1], str(row[2]))

        assert linked() == ("stale", None, "unclear")

        with control.begin() as connection:
            persist_source(connection, first)
        assert linked() == (first.name, "CC-BY-4.0", "declared")

        # A later registry clarification must converge the same row, not add one.
        with control.begin() as connection:
            persist_source(connection, second)
        assert linked() == (second.name, "CC-BY-NC-4.0", "declared")

        with control.begin() as connection:
            persist_source(connection, second)
        assert linked() == (second.name, "CC-BY-NC-4.0", "declared")

        with control.connect() as connection:
            sources = connection.execute(
                text("SELECT count(*) FROM dataset_source WHERE dataset_id = 'white-cmj-acc-grf'")
            ).scalar_one()
            superseded = connection.execute(
                text("SELECT count(*) FROM license_policy WHERE policy_id = 'lic-stale'")
            ).scalar_one()
        assert int(sources) == 1
        assert int(superseded) == 1  # content-addressed policy stays auditable
    finally:
        control.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        admin.dispose()
