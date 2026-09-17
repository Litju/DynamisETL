"""Alembic environment.

The target PostgreSQL schema is applied through the connection ``search_path``
(:func:`dynamis.storage.migration_support.bootstrap_schema`), so the SQLAlchemy
metadata stays schema-unqualified.

Typing notes: ``context.configure`` accepts a ``MetaData`` instance, so the
target metadata is returned as a typed ``MetaData`` instead of ``object``. That
removes the need for broad Pyright suppression in this file.
"""

from __future__ import annotations

from typing import Any

from alembic import context
from sqlalchemy import MetaData, engine_from_config, pool

from dynamis.config import ENV_POSTGRES_URL, resolve_db_schema, resolved_environ
from dynamis.storage import tables as _tables

VERSION_TABLE_NAME = "alembic_version"

config = context.config

_target: MetaData = _tables.Base.metadata
schema_name: str = resolve_db_schema()

if config.config_file_name is not None:
    _url = resolved_environ().get(ENV_POSTGRES_URL, "").strip()
    if _url.startswith("postgresql://"):
        _url = "postgresql+psycopg://" + _url.removeprefix("postgresql://")
    if _url:
        # Escape percent signs: ConfigParser interpolation would otherwise break.
        config.set_main_option("sqlalchemy.url", _url.replace("%", "%%"))


def include_object(
    object_: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """Keep Alembic's own bookkeeping table out of autogenerate comparisons."""
    if type_ == "table" and name == VERSION_TABLE_NAME:
        return False
    return True


def run_migrations_offline() -> None:
    from dynamis.storage.migration_support import create_schema_sql, search_path_sql

    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=_target,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=VERSION_TABLE_NAME,
        version_table_schema=schema_name,
        include_schemas=False,
        include_object=include_object,
    )
    with context.begin_transaction():
        # Offline mode cannot rely on the connection search_path, so the emitted
        # script carries the schema bootstrap explicitly and stays self-contained.
        context.execute(create_schema_sql(schema_name))
        context.execute(search_path_sql(schema_name))
        context.run_migrations()


def run_migrations_online() -> None:
    from dynamis.storage.migration_support import bootstrap_schema

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        bootstrap_schema(connection)
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=_target,
            version_table=VERSION_TABLE_NAME,
            version_table_schema=schema_name,
            include_schemas=False,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
