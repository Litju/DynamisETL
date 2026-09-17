"""Parquet-first storage helpers for dense canonical scientific data.

Canonical dense signals, tracking and pose live in partitioned **Parquet with
Zstd compression**; they are never written into PostgreSQL. Every write is
atomic and returns the artifact checksum so provenance is recorded at the
moment of materialization.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from dynamis.contracts.schemas import schema_fingerprint
from dynamis.storage.atomic import atomic_write_path, sha256_file

DEFAULT_COMPRESSION = "zstd"
DEFAULT_COMPRESSION_LEVEL = 3
PARQUET_FORMAT_VERSION = "2.6"


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
) -> WrittenArtifact:
    """Write ``table`` to ``path`` as Parquet+Zstd, atomically."""
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


def read_parquet_schema(path: Path) -> pa.Schema:
    return pq.read_schema(Path(path))


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
