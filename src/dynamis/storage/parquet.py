"""Parquet-first storage helpers for dense canonical scientific data.

Canonical dense signals, tracking and pose live in partitioned **Parquet with
Zstd compression**; they are never written into PostgreSQL. Every write is
atomic and returns the artifact checksum so provenance is recorded at the
moment of materialization.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from dynamis.contracts.schemas import schema_fingerprint
from dynamis.contracts.sports import DataGrain, grain_columns, with_grain_metadata
from dynamis.storage.atomic import atomic_write_path, sha256_file

DEFAULT_COMPRESSION = "zstd"
DEFAULT_COMPRESSION_LEVEL = 3
PARQUET_FORMAT_VERSION = "2.6"

#: Row-group authority for streaming writes. The writer holds at most one row
#: group plus one incoming batch in memory, never the whole stream.
DEFAULT_STREAMING_ROW_GROUP_SIZE = 1 << 18


@dataclass(frozen=True, slots=True)
class WrittenArtifact:
    """Result of one atomic Parquet materialization."""

    path: Path
    checksum_sha256: str
    byte_size: int
    row_count: int
    schema_fingerprint: str
    compression: str
    relative_path: str | None = None


def content_fingerprint(table: pa.Table) -> str:
    """Deterministic content hash of an Arrow table, including its schema metadata."""
    digest = hashlib.sha256()
    digest.update(pa.Schema.serialize(table.schema))
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    digest.update(sink.getvalue().to_pybytes())
    return digest.hexdigest()


def write_parquet_atomic(
    table: pa.Table,
    path: Path,
    *,
    compression: str = DEFAULT_COMPRESSION,
    compression_level: int = DEFAULT_COMPRESSION_LEVEL,
    relative_to: Path | None = None,
    row_group_size: int | None = None,
    grain: DataGrain | None = None,
) -> WrittenArtifact:
    """Write ``table`` to ``path`` as Parquet+Zstd, atomically."""
    if grain is not None:
        table = table.replace_schema_metadata(with_grain_metadata(table.schema, grain).metadata)
    target = Path(path)
    with atomic_write_path(target) as tmp:
        pq.write_table(
            table,
            tmp,
            compression=compression,
            compression_level=compression_level,
            version=PARQUET_FORMAT_VERSION,
            row_group_size=row_group_size,
            write_statistics=True,
        )
        if grain is not None:
            _validate_grain_file(tmp, grain)
    relative = None
    if relative_to is not None:
        relative = target.resolve().relative_to(Path(relative_to).resolve()).as_posix()
    return WrittenArtifact(
        path=target,
        checksum_sha256=sha256_file(target),
        byte_size=target.stat().st_size,
        row_count=table.num_rows,
        schema_fingerprint=schema_fingerprint(table.schema),
        compression=compression,
        relative_path=relative,
    )


def _write_row_groups(
    handle: pq.ParquetWriter,
    batches: Iterable[pa.RecordBatch],
    *,
    schema: pa.Schema,
    row_group_size: int,
) -> int:
    """Write ``batches`` as exactly ``row_group_size``-row groups.

    The buffer never exceeds one row group plus one incoming batch, so a
    multi-million-row stream is bounded by configuration, not by its size. Row
    groups are cut at exact multiples of ``row_group_size``, which makes the
    streaming artifact byte-identical to the table writer for the same schema
    and row-group policy.
    """
    buffer: list[pa.RecordBatch] = []
    buffered = 0
    written = 0
    for batch in batches:
        compatible = (
            batch.schema.remove_metadata() == schema.remove_metadata()
            if schema.metadata and b"dynamis.data_grain_kind" in schema.metadata
            else batch.schema == schema
        )
        if not compatible:
            raise ValueError(
                "streaming batch schema does not match the declared canonical schema: "
                f"batch={batch.schema.names} expected={schema.names}"
            )
        if batch.num_rows == 0:
            continue
        buffer.append(batch)
        buffered += batch.num_rows
        while buffered >= row_group_size:
            merged = pa.Table.from_batches(buffer, schema=schema).combine_chunks()
            handle.write_batch(merged.slice(0, row_group_size).to_batches()[0])
            remainder = merged.slice(row_group_size)
            buffered = remainder.num_rows
            buffer = remainder.to_batches() if buffered else []
            written += row_group_size
    if buffered:
        remainder = pa.Table.from_batches(buffer, schema=schema).combine_chunks()
        handle.write_batch(remainder.to_batches()[0])
        written += buffered
    return written


def write_parquet_streaming_atomic(
    batches: Iterable[pa.RecordBatch] | pa.RecordBatchReader,
    path: Path,
    *,
    schema: pa.Schema,
    row_group_size: int = DEFAULT_STREAMING_ROW_GROUP_SIZE,
    compression: str = DEFAULT_COMPRESSION,
    compression_level: int = DEFAULT_COMPRESSION_LEVEL,
    relative_to: Path | None = None,
    grain: DataGrain | None = None,
) -> WrittenArtifact:
    """Write a bounded Arrow batch stream to ``path`` as Parquet+Zstd, atomically.

    The canonical schema is fixed before the first row group; every batch must
    match it exactly, and a mismatch aborts the write, leaving no accepted
    artifact (the temporary sibling is removed by the atomic write context).
    """
    if row_group_size <= 0:
        raise ValueError("row_group_size must be positive")
    if grain is not None:
        schema = with_grain_metadata(schema, grain)
        grain_columns(grain, schema.names)
    target = Path(path)
    with atomic_write_path(target) as tmp:
        with pq.ParquetWriter(
            tmp,
            schema,
            compression=compression,
            compression_level=compression_level,
            version=PARQUET_FORMAT_VERSION,
            write_statistics=True,
        ) as writer:
            row_count = _write_row_groups(
                writer,
                batches,
                schema=schema,
                row_group_size=row_group_size,
            )
            if row_count == 0:
                # Parity with pq.write_table on an empty table: one empty row group.
                writer.write_table(pa.Table.from_batches([], schema=schema))
        if grain is not None:
            _validate_grain_file(tmp, grain)
    relative = None
    if relative_to is not None:
        relative = target.resolve().relative_to(Path(relative_to).resolve()).as_posix()
    return WrittenArtifact(
        path=target,
        checksum_sha256=sha256_file(target),
        byte_size=target.stat().st_size,
        row_count=row_count,
        schema_fingerprint=schema_fingerprint(schema),
        compression=compression,
        relative_path=relative,
    )


def read_parquet_schema(path: Path) -> pa.Schema:
    return pq.read_schema(Path(path))


def _validate_grain_file(path: Path, grain: DataGrain) -> None:
    """Check declared key uniqueness and completeness before atomic publication."""
    import duckdb

    columns = tuple(f'"{name}"' for name in grain_columns(grain, pq.read_schema(path).names))
    text_columns = ", ".join(f"CAST({column} AS VARCHAR)" for column in columns)
    non_null = " OR ".join(f"{column} IS NULL" for column in columns)
    with duckdb.connect(":memory:") as connection:
        missing = connection.execute(
            f"SELECT 1 FROM read_parquet(?) WHERE {non_null} LIMIT 1", [str(path)]
        ).fetchone()
        if missing is not None:
            raise ValueError(f"{grain.kind.value} artifact has a null grain axis")
        duplicate = connection.execute(
            f"SELECT 1 FROM (SELECT {text_columns} FROM read_parquet(?) "
            f"GROUP BY {text_columns} HAVING count(*) > 1 LIMIT 1)",
            [str(path)],
        ).fetchone()
        if duplicate is not None:
            raise ValueError(f"{grain.kind.value} artifact contains duplicate grain keys")


def read_parquet_table(path: Path, *, columns: list[str] | None = None) -> pa.Table:
    return pq.read_table(Path(path), columns=columns)


def file_row_count(path: Path) -> int:
    return int(pq.ParquetFile(Path(path)).metadata.num_rows)


def compression_codecs(path: Path) -> tuple[str, ...]:
    """Distinct Parquet compression codecs used by the column chunks of a file."""
    metadata = pq.ParquetFile(Path(path)).metadata
    codecs: set[str] = set()
    for row_group in range(metadata.num_row_groups):
        group = metadata.row_group(row_group)
        for column in range(group.num_columns):
            codecs.add(str(group.column(column).compression).upper())
    return tuple(sorted(codecs))


def column_null_counts(path: Path) -> dict[str, int]:
    """Aggregate null counts per column, read back from Parquet statistics."""
    metadata = pq.ParquetFile(Path(path)).metadata
    counts: dict[str, int] = {}
    for row_group in range(metadata.num_row_groups):
        group = metadata.row_group(row_group)
        for column in range(group.num_columns):
            chunk = group.column(column)
            path_in_schema = str(chunk.path_in_schema)
            statistics = chunk.statistics
            if statistics is None or statistics.null_count is None:
                continue
            counts[path_in_schema] = counts.get(path_in_schema, 0) + int(statistics.null_count)
    return counts


def fingerprint_schema_json(schema: pa.Schema) -> str:
    payload = json.dumps(
        {
            "fields": [
                {"name": field.name, "type": str(field.type), "nullable": field.nullable}
                for field in schema
            ],
            "fingerprint": schema_fingerprint(schema),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return payload
