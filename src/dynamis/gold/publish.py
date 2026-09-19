"""Publish curated Gold marts from DuckDB into PostgreSQL serving tables.

The publication target is a dedicated PostgreSQL ``gold`` schema that contains
serving copies only; the control-plane schema and its provenance remain the
authority. Every mart is rebuilt (drop/create/insert) inside one transaction, so
a failed publication cannot leave a partially updated serving table, and the
same DuckDB build always publishes identical rows.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import sqlalchemy as sa
from sqlalchemy import Engine

from dynamis.config import Settings
from dynamis.gold.build import MART_NAMES, gold_duckdb_path
from dynamis.storage.atomic import atomic_write_text
from dynamis.storage.paths import receipt_path, relative_posix

ENV_GOLD_SCHEMA = "DYNAMIS_GOLD_SCHEMA"
GOLD_SCHEMA = "gold"
_SCHEMA_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def resolve_gold_schema() -> str:
    """Serving schema name; environment-overridable so tests never touch `gold`."""
    value = os.environ.get(ENV_GOLD_SCHEMA, "").strip() or GOLD_SCHEMA
    if not _SCHEMA_PATTERN.match(value):
        raise ValueError(f"{ENV_GOLD_SCHEMA}={value!r} is not a valid PostgreSQL schema name")
    return value


def _pg_type(dtype: pa.DataType) -> str:
    if pa.types.is_integer(dtype):
        return "BIGINT"
    if pa.types.is_floating(dtype):
        return "DOUBLE PRECISION"
    if pa.types.is_boolean(dtype):
        return "BOOLEAN"
    if pa.types.is_timestamp(dtype):
        return "TIMESTAMPTZ"
    if pa.types.is_list(dtype) or pa.types.is_large_list(dtype):
        return "JSONB"
    return "TEXT"


def _serialize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, list):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def publish_gold(
    settings: Settings,
    engine: Engine,
    *,
    duckdb_path: Path | None = None,
    marts: tuple[str, ...] = MART_NAMES,
) -> dict[str, Any]:
    """Rebuild every Gold serving table from the current DuckDB marts."""
    path = duckdb_path or gold_duckdb_path(settings)
    if not path.is_file():
        raise FileNotFoundError(f"Gold DuckDB database is missing: {path}; run the build first")
    schema = resolve_gold_schema()
    published: dict[str, int] = {}
    with engine.begin() as connection:
        connection.execute(sa.text(f"CREATE SCHEMA IF NOT EXISTS {_quote(schema)}"))
        for mart in marts:
            # Read-write (no write is issued): a read-only handle can conflict
            # with an existing read-write connection in the same process.
            connection_read = duckdb.connect(str(path))
            try:
                table: pa.Table = connection_read.execute(
                    f'SELECT * FROM "{mart}"'
                ).to_arrow_table()
            finally:
                connection_read.close()
            target = f"{_quote(schema)}.{_quote(mart)}"
            connection.execute(sa.text(f"DROP TABLE IF EXISTS {target}"))
            columns = ", ".join(
                f"{_quote(field.name)} {_pg_type(field.type)}" for field in table.schema
            )
            connection.execute(sa.text(f"CREATE TABLE {target} ({columns})"))
            if table.num_rows:
                names = [field.name for field in table.schema]
                placeholders = ", ".join(f":{name}" for name in names)
                insert = sa.text(
                    f"INSERT INTO {target} ({', '.join(_quote(name) for name in names)}) "
                    f"VALUES ({placeholders})"
                )
                rows = [
                    {name: _serialize(value) for name, value in zip(names, row, strict=True)}
                    for row in zip(*(table.column(name).to_pylist() for name in names), strict=True)
                ]
                connection.execute(insert, rows)
            published[mart] = table.num_rows
    receipt = {
        "kind": "gold_publish",
        "schema": schema,
        "marts": published,
    }
    target = receipt_path(settings, dataset_id="platform", kind="gold", name="publish")
    atomic_write_text(target, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return {
        **receipt,
        "receipt_path": relative_posix(settings.dataset_root, target),
    }


__all__ = ["ENV_GOLD_SCHEMA", "GOLD_SCHEMA", "publish_gold", "resolve_gold_schema"]
