"""Windowed dense-artifact reads with explicit display reduction.

Canonical and derived dense signals live in external Parquet files. The API never
offers "the whole stream": windows are bounded by ``from_ns``/``to_ns`` and a
display reduction that preserves extrema. Scientific values always come from the
canonical artifact; a reduced window is a display representation whose method and
parameters are returned with the payload.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from dynamis.config import Settings
from dynamis.contracts.schemas import SI_UNIT_KEY
from dynamis.serving.models import (
    ArtifactRefView,
    DenseWindowMeta,
    ReductionInfo,
)

ENV_DENSE_MAX_SOURCE_ROWS = "DYNAMIS_DENSE_MAX_SOURCE_ROWS"
DEFAULT_DENSE_MAX_SOURCE_ROWS = 5_000_000

TIME_COLUMN = "t_rel_ns"
TIME_COLUMNS = frozenset({TIME_COLUMN, "timestamp_utc_ns"})
REDUCTION_METHOD = "min_max_envelope_per_time_bucket"
REDUCTION_NOTE = (
    "Display-only extrema-preserving reduction. Scientific metric values and processor "
    "results always come from canonical artifacts, never from this representation."
)
EXACT_WINDOW_NOTE = (
    "Exact canonical samples in the requested time window; no display reduction was applied."
)


class DenseWindowError(RuntimeError):
    """Base class for dense-window request failures."""


class DenseWindowTooLarge(DenseWindowError):
    """The requested window exceeds the bounded source-row cap."""


class ArtifactPathError(DenseWindowError):
    """The registered artifact path is missing or escapes the dataset root."""


@dataclass(frozen=True, slots=True)
class DenseWindowResult:
    table: pa.Table
    meta: DenseWindowMeta


def default_max_source_rows() -> int:
    raw = os.environ.get(ENV_DENSE_MAX_SOURCE_ROWS, "").strip()
    if not raw:
        return DEFAULT_DENSE_MAX_SOURCE_ROWS
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{ENV_DENSE_MAX_SOURCE_ROWS} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{ENV_DENSE_MAX_SOURCE_ROWS} must be positive")
    return value


def resolve_artifact_path(settings: Settings, ref: ArtifactRefView) -> Path:
    """Resolve a registered artifact under the dataset root; reject traversal."""
    root = settings.dataset_root.resolve()
    relative = Path(ref.relative_path)
    if relative.is_absolute():
        raise ArtifactPathError(
            f"artifact {ref.artifact_id!r} has an absolute registered path; refusing to read"
        )
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise ArtifactPathError(
            f"artifact {ref.artifact_id!r} resolves outside the dataset root; refusing to read"
        )
    if not candidate.is_file():
        raise ArtifactPathError(f"artifact {ref.artifact_id!r} is missing at its registered path")
    if candidate.suffix.lower() != ".parquet":
        raise ArtifactPathError(
            f"artifact {ref.artifact_id!r} is not a Parquet artifact; dense windows require Parquet"
        )
    return candidate


def _schema_units(schema: pa.Schema) -> dict[str, str]:
    units: dict[str, str] = {}
    for field in schema:
        raw = (field.metadata or {}).get(SI_UNIT_KEY)
        if raw is not None:
            units[field.name] = raw.decode()
    return units


def _is_identity_key(field: pa.Field) -> bool:
    if field.name in TIME_COLUMNS or field.name == "sample_index":
        return False
    if pa.types.is_string(field.type) or pa.types.is_boolean(field.type):
        return True
    if pa.types.is_integer(field.type) or pa.types.is_floating(field.type):
        return field.name.endswith("_id")
    return False


def _is_measure(field: pa.Field) -> bool:
    if field.name in TIME_COLUMNS or field.name == "sample_index":
        return False
    if _is_identity_key(field):
        return False
    return bool(pa.types.is_integer(field.type) or pa.types.is_floating(field.type))


def _validate_columns(schema: pa.Schema, columns: tuple[str, ...]) -> tuple[str, ...]:
    if not columns:
        return tuple(field.name for field in schema)
    known = {field.name for field in schema}
    unknown = sorted(set(columns) - known)
    if unknown:
        raise DenseWindowError(f"requested columns are absent from the artifact: {unknown}")
    return tuple(columns)


def load_artifact_window(
    settings: Settings,
    ref: ArtifactRefView,
    *,
    from_ns: int | None = None,
    to_ns: int | None = None,
    columns: tuple[str, ...] = (),
    max_points: int | None = None,
    max_source_rows: int | None = None,
) -> DenseWindowResult:
    """Read one bounded window and (optionally) reduce it for display."""
    path = resolve_artifact_path(settings, ref)
    schema = pq.read_schema(path)
    if TIME_COLUMN not in schema.names:
        raise DenseWindowError(f"artifact {ref.artifact_id!r} has no canonical {TIME_COLUMN} axis")
    selected = _validate_columns(schema, columns)
    units = _schema_units(schema)
    canonical_min, canonical_max = _canonical_time_range(path)
    if canonical_min is None or canonical_max is None:
        empty = pa.table({name: pa.array([], type=schema.field(name).type) for name in selected})
        meta = DenseWindowMeta(
            artifact=ref,
            from_ns=int(from_ns or 0),
            to_ns=int(to_ns or 0),
            columns=list(empty.column_names),
            source_rows=0,
            returned_rows=0,
            canonical_time_min_ns=None,
            canonical_time_max_ns=None,
            reduction=None,
            units=units,
            coordinate_frame_id=ref.coordinate_frame_id,
            measurement_class=ref.measurement_class,
            display_note=EXACT_WINDOW_NOTE,
        )
        return DenseWindowResult(table=empty, meta=meta)
    lower = canonical_min if from_ns is None else int(from_ns)
    upper = canonical_max if to_ns is None else int(to_ns)
    if upper < lower:
        raise DenseWindowError("to_ns must not be earlier than from_ns")
    cap = default_max_source_rows() if max_source_rows is None else int(max_source_rows)
    if cap <= 0:
        raise DenseWindowError("max_source_rows must be positive")

    source_rows = _window_row_count(path, lower, upper)
    if source_rows > cap:
        raise DenseWindowTooLarge(
            f"dense window holds {source_rows} source rows, above the {cap} row cap; "
            "request a narrower from_ns/to_ns range"
        )

    reduction: ReductionInfo | None = None
    if max_points is not None and source_rows > max_points:
        table = _reduced_window(
            path,
            source_rows=source_rows,
            from_ns=lower,
            to_ns=upper,
            selected=selected,
            schema=schema,
            max_points=int(max_points),
        )
        reduction = ReductionInfo(
            method=REDUCTION_METHOD,
            parameters={
                "from_ns": lower,
                "to_ns": upper,
                "max_points": int(max_points),
                "bucket_count": table.num_rows,
            },
            source_points=source_rows,
            returned_points=table.num_rows,
            note=REDUCTION_NOTE,
        )
    else:
        table = _exact_window(path, from_ns=lower, to_ns=upper, selected=selected)
    meta = DenseWindowMeta(
        artifact=ref,
        from_ns=lower,
        to_ns=upper,
        columns=list(table.column_names),
        source_rows=source_rows,
        returned_rows=table.num_rows,
        canonical_time_min_ns=canonical_min,
        canonical_time_max_ns=canonical_max,
        reduction=reduction,
        units=units,
        coordinate_frame_id=ref.coordinate_frame_id,
        measurement_class=ref.measurement_class,
        display_note=REDUCTION_NOTE if reduction else EXACT_WINDOW_NOTE,
    )
    return DenseWindowResult(table=table, meta=meta)


def _connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect()


def _canonical_time_range(path: Path) -> tuple[int | None, int | None]:
    connection = _connect()
    try:
        row = connection.execute(
            f"SELECT min({TIME_COLUMN}), max({TIME_COLUMN}) FROM read_parquet(?)",
            [path.as_posix()],
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return None, None
    return (int(row[0]), int(row[1])) if row[0] is not None else (None, None)


def _window_row_count(path: Path, lower: int, upper: int) -> int:
    connection = _connect()
    try:
        row = connection.execute(
            f"SELECT count(*) FROM read_parquet(?) WHERE {TIME_COLUMN} >= ? AND {TIME_COLUMN} <= ?",
            [path.as_posix(), lower, upper],
        ).fetchone()
    finally:
        connection.close()
    return int(row[0]) if row else 0


def _exact_window(
    path: Path,
    *,
    from_ns: int,
    to_ns: int,
    selected: tuple[str, ...],
) -> pa.Table:
    projection = ", ".join(f'"{name}"' for name in selected)
    connection = _connect()
    try:
        return connection.execute(
            f"SELECT {projection} FROM read_parquet(?) "
            f"WHERE {TIME_COLUMN} >= ? AND {TIME_COLUMN} <= ? ORDER BY {TIME_COLUMN}",
            [path.as_posix(), from_ns, to_ns],
        ).to_arrow_table()
    finally:
        connection.close()


def _reduced_window(
    path: Path,
    *,
    source_rows: int,
    from_ns: int,
    to_ns: int,
    selected: tuple[str, ...],
    schema: pa.Schema,
    max_points: int,
) -> pa.Table:
    if max_points < 1:
        raise DenseWindowError("max_points must be at least 1")
    identity = [field.name for field in schema if _is_identity_key(field)]
    measures = [name for name in selected if _is_measure(schema.field(name))]
    # One extra nanosecond makes the bucket count a hard bound of max_points even
    # when the last observed sample sits exactly on a bucket boundary.
    span_ns = max(1, to_ns - from_ns + 1)
    bucket_ns = max(1, math.ceil(span_ns / max_points))
    key_sql = ", ".join(f'"{name}"' for name in identity)
    select_keys = f"{key_sql}, " if identity else ""
    group_keys = f"{key_sql}, __bucket" if identity else "__bucket"
    order_keys = (
        ", ".join(f'"{name}"' for name in identity) + ", " if identity else ""
    ) + "__bucket"
    aggregates = [
        "min(t_rel_ns) AS t_start_ns",
        "max(t_rel_ns) AS t_end_ns",
        "count(*) AS bucket_rows",
    ]
    for name in measures:
        aggregates.append(f'min("{name}") AS "{name}_min"')
        aggregates.append(f'max("{name}") AS "{name}_max"')
    aggregate_sql = ", ".join(aggregates)
    sql = (
        "WITH windowed AS ("
        f"SELECT * FROM read_parquet(?) WHERE t_rel_ns >= ? AND t_rel_ns <= ?"
        "), bucketed AS ("
        "SELECT *, CAST(floor((t_rel_ns - ?) / ?) AS BIGINT) AS __bucket FROM windowed"
        ")"
        f" SELECT {select_keys}__bucket, {aggregate_sql}"
        " FROM bucketed"
        f" GROUP BY {group_keys}"
        f" ORDER BY {order_keys}"
    )
    connection = _connect()
    try:
        return connection.execute(
            sql,
            [path.as_posix(), from_ns, to_ns, from_ns, bucket_ns],
        ).to_arrow_table()
    finally:
        connection.close()


def arrow_ipc_stream(table: pa.Table) -> bytes:
    """Serialize a window table as Apache Arrow IPC stream (dense transport)."""
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()


def window_etag(
    ref: ArtifactRefView,
    *,
    from_ns: int | None,
    to_ns: int | None,
    columns: tuple[str, ...],
    max_points: int | None,
) -> str:
    """Strong ETag derived from immutable artifact identity and query parameters."""
    identity = json.dumps(
        {
            "checksum_sha256": ref.checksum_sha256,
            "from_ns": from_ns,
            "to_ns": to_ns,
            "columns": sorted(columns),
            "max_points": max_points,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f'"{hashlib.sha256(identity).hexdigest()}"'


def window_metadata_header(meta: DenseWindowMeta) -> str:
    """Compact metadata envelope for Arrow responses (JSON header)."""
    return json.dumps(
        meta.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )


def table_records(table: pa.Table) -> list[dict[str, Any]]:
    """Row-wise JSON records for small/bounded windows."""
    return table.to_pylist()


__all__ = [
    "DEFAULT_DENSE_MAX_SOURCE_ROWS",
    "ENV_DENSE_MAX_SOURCE_ROWS",
    "REDUCTION_METHOD",
    "TIME_COLUMN",
    "ArtifactPathError",
    "DenseWindowError",
    "DenseWindowResult",
    "DenseWindowTooLarge",
    "arrow_ipc_stream",
    "default_max_source_rows",
    "load_artifact_window",
    "resolve_artifact_path",
    "table_records",
    "window_etag",
    "window_metadata_header",
]
