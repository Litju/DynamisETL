"""Runtime helpers shared by Alembic ``env.py`` and the bootstrap migration.

The PostgreSQL schema is applied through the connection ``search_path`` so the
SQLAlchemy metadata can stay schema-unqualified and identical in development,
tests and CI. Both the environment and the bootstrap migration call
:func:`bootstrap_schema`, so ``alembic upgrade head`` works even when a caller
connects without a pre-configured search path.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import MetaData, text

from dynamis.config import resolve_db_schema


def current_schema(env: Mapping[str, str] | None = None) -> str:
    return resolve_db_schema(env)


def create_schema_sql(schema: str) -> str:
    return f'CREATE SCHEMA IF NOT EXISTS "{schema}"'


def search_path_sql(schema: str) -> str:
    return f'SET search_path TO "{schema}", public'


def bootstrap_schema(bind: Any) -> str:
    """Create the target schema and point ``search_path`` at it.

    Returns the active schema name so callers can assert it in tests and logs.
    """
    schema = current_schema()
    bind.execute(text(create_schema_sql(schema)))
    bind.execute(text(search_path_sql(schema)))
    return schema


def target_metadata() -> MetaData:
    from dynamis.storage import tables as _tables

    return _tables.Base.metadata
