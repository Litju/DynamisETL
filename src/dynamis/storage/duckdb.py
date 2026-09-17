"""DuckDB access layer for local analytical scans over canonical Parquet.

DuckDB is the validation and research engine over Parquet files; it holds no
authoritative state. Paths are always interpolated through :func:`sql_literal`
so Windows separators and quoting cannot corrupt a statement.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

DEFAULT_DATABASE = ":memory:"


def sql_literal(value: str) -> str:
    """Quote a Python string as a SQL literal (single quotes doubled)."""
    return "'" + value.replace("'", "''") + "'"


def connect(database: str | Path = DEFAULT_DATABASE, *, read_only: bool = False):
    """Open a DuckDB connection. ``:memory:`` keeps analytical scans local."""
    target = str(database)
    return duckdb.connect(target, read_only=read_only)


def parquet_source(path: str | Path) -> str:
    return f"read_parquet({sql_literal(str(Path(path).as_posix()))})"


def query(connection: Any, sql: str, params: Sequence[Any] | None = None) -> pa.Table:
    """Execute a statement and materialize the result as an Arrow table."""
    if params is None:
        return connection.execute(sql).to_arrow_table()
    return connection.execute(sql, list(params)).to_arrow_table()


def scalar(connection: Any, sql: str, params: Sequence[Any] | None = None) -> Any:
    if params is None:
        row = connection.execute(sql).fetchone()
    else:
        row = connection.execute(sql, list(params)).fetchone()
    return None if row is None else row[0]


def row_count(connection: Any, path: str | Path, *, where: str | None = None) -> int:
    sql = f"SELECT count(*) FROM {parquet_source(path)}"
    if where:
        sql = f"SELECT count(*) FROM {parquet_source(path)} WHERE {where}"
    return int(scalar(connection, sql))


def column_names(connection: Any, path: str | Path) -> tuple[str, ...]:
    table = query(connection, f"SELECT * FROM {parquet_source(path)} LIMIT 0")
    return tuple(table.column_names)


def compression_codecs(connection: Any, path: str | Path) -> tuple[str, ...]:
    rows = query(
        connection,
        "SELECT DISTINCT compression FROM parquet_metadata("
        f"{sql_literal(str(Path(path).as_posix()))})",
    ).to_pylist()
    return tuple(sorted({_text(row["compression"]).upper() for row in rows}))


def schema_columns(connection: Any, path: str | Path) -> dict[str, str]:
    """Logical column names and DuckDB types read back from the Parquet footer."""
    rows = query(
        connection,
        "SELECT name, type FROM parquet_schema("
        f"{sql_literal(str(Path(path).as_posix()))}) WHERE num_children IS NULL",
    ).to_pylist()
    return {_text(row["name"]): _text(row["type"]) for row in rows}


def _text(value: Any) -> str:
    """Normalize Parquet metadata values, which DuckDB may return as BLOB."""
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", "replace")
    return str(value)


def key_value_metadata(connection: Any, path: str | Path) -> dict[str, str]:
    """File-level Parquet key/value metadata (where schema metadata is stored)."""
    rows = query(
        connection,
        f"SELECT key, value FROM parquet_kv_metadata({sql_literal(str(Path(path).as_posix()))})",
    ).to_pylist()
    return {_text(row["key"]): _text(row["value"]) for row in rows}


def row_group_count(connection: Any, path: str | Path) -> int:
    return int(
        scalar(
            connection,
            "SELECT count(DISTINCT row_group_id) FROM parquet_metadata("
            f"{sql_literal(str(Path(path).as_posix()))})",
        )
    )


@dataclass(frozen=True, slots=True)
class ParquetObservation:
    """Everything DuckDB can independently report about a materialized artifact."""

    path: str
    row_count: int
    codecs: tuple[str, ...]
    columns: Mapping[str, str]
    metadata: Mapping[str, str]
    row_groups: int

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(self.columns)


def observe_parquet(connection: Any, path: str | Path) -> ParquetObservation:
    target = Path(path)
    return ParquetObservation(
        path=str(target),
        row_count=row_count(connection, target),
        codecs=compression_codecs(connection, target),
        columns=schema_columns(connection, target),
        metadata=key_value_metadata(connection, target),
        row_groups=row_group_count(connection, target),
    )


def distinct_values(connection: Any, path: str | Path, column: str) -> tuple[Any, ...]:
    rows = query(
        connection,
        f"SELECT DISTINCT {column} FROM {parquet_source(path)} ORDER BY {column}",
    ).to_pylist()
    return tuple(row[column] for row in rows)


def null_counts(connection: Any, path: str | Path, columns: Iterable[str]) -> dict[str, int]:
    projection = ", ".join(f"count(*) - count({name}) AS {name}" for name in columns)
    table = query(connection, f"SELECT {projection} FROM {parquet_source(path)}")
    row = table.to_pylist()[0]
    return {name: int(value) for name, value in row.items()}
