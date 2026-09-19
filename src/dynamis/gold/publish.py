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
from dynamis.processors.persistence import dev_allow_unknown_code_sha
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


def assert_serving_code_sha(connection, *, allow_unknown: bool) -> None:
    """Refuse serving publication while a processor run has no code Git SHA.

    A completed processor run with a null revision is development state; serving
    tables must always resolve to an exact code revision that produced them.
    """
    if allow_unknown:
        return
    unknown_runs = connection.execute(
        sa.text(
            "SELECT r.run_id FROM processing_run r "
            "JOIN algorithm_spec a ON a.algorithm_id = r.algorithm_id "
            "WHERE a.kind = 'processor' AND r.code_git_sha IS NULL"
        )
    ).fetchall()
    if unknown_runs:
        raise RuntimeError(
            "refusing to publish Gold serving tables: "
            f"{len(unknown_runs)} processor run(s) without a code Git SHA are present "
            f"(for example {unknown_runs[0][0]!r}); execute the pipeline with "
            "DYNAMIS_CODE_GIT_SHA set to a full Git revision, or set "
            "DYNAMIS_ALLOW_UNKNOWN_CODE_SHA=1 for development-only serving"
        )


def publish_gold(
    settings: Settings,
    engine: Engine,
    *,
    duckdb_path: Path | None = None,
    marts: tuple[str, ...] = MART_NAMES,
    allow_unknown_code_sha: bool | None = None,
) -> dict[str, Any]:
    """Rebuild every Gold serving table from the current DuckDB marts.

    Serving publication is refused while a completed processor run without a
    full code Git SHA is present in the control plane: development-only
    unknown-SHA state must not silently reach the serving schema. The
    development-only ``DYNAMIS_ALLOW_UNKNOWN_CODE_SHA`` flag is honoured for
    local artifact work.
    """
    path = duckdb_path or gold_duckdb_path(settings)
    if not path.is_file():
        raise FileNotFoundError(f"Gold DuckDB database is missing: {path}; run the build first")
    schema = resolve_gold_schema()
    if allow_unknown_code_sha is None:
        allow_unknown_code_sha = dev_allow_unknown_code_sha()
    published: dict[str, int] = {}
    with engine.begin() as connection:
        assert_serving_code_sha(connection, allow_unknown=allow_unknown_code_sha)
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


__all__ = [
    "ENV_GOLD_SCHEMA",
    "GOLD_SCHEMA",
    "assert_serving_code_sha",
    "publish_gold",
    "resolve_gold_schema",
]
