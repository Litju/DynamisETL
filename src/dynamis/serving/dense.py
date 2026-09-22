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
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from dynamis.config import Settings
from dynamis.contracts.schemas import SI_UNIT_KEY
from dynamis.serving.models import (
    ArtifactRefView,
    DenseWindowMeta,
    EntityObservationView,
    ReductionInfo,
)

ENV_DENSE_MAX_SOURCE_ROWS = "DYNAMIS_DENSE_MAX_SOURCE_ROWS"
DEFAULT_DENSE_MAX_SOURCE_ROWS = 5_000_000

TIME_COLUMN = "t_rel_ns"
TIME_COLUMNS = frozenset({TIME_COLUMN, "timestamp_utc_ns"})
#: Candidate entity columns, most specific first. A spatial artifact identifies
#: a tracked object by ``object_id``; a per-subject artifact (pose, IMU, force)
#: identifies it by ``subject_id``.
ENTITY_COLUMNS: tuple[str, ...] = ("object_id", "subject_id")
REDUCTION_METHOD = "min_max_envelope_per_time_bucket"
REDUCTION_NOTE = (
    "Display-only extrema-preserving reduction. Scientific metric values and processor "
    "results always come from canonical artifacts, never from this representation. "
    "When identity keys are interleaved, the max_points budget is divided across them."
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


def entity_column(schema: pa.Schema) -> str | None:
    """The column that identifies one tracked entity in this artifact."""
    names = set(schema.names)
    for candidate in ENTITY_COLUMNS:
        if candidate in names:
            return candidate
    return None


def _entity_predicate(schema: pa.Schema, entity_id: str | None) -> tuple[str, list[Any]]:
    """SQL fragment and parameters scoping a window to one entity."""
    if entity_id is None:
        return "", []
    column = entity_column(schema)
    if column is None:
        raise DenseWindowError(
            "this artifact declares no entity column, so it cannot be scoped to an entity"
        )
    return f' AND "{column}" = ?', [entity_id]


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
    entity_id: str | None = None,
) -> DenseWindowResult:
    """Read one bounded window and (optionally) reduce it for display.

    ``entity_id`` scopes the window to one tracked entity. A dense artifact
    interleaves every entity on the same time axis, so a viewer that renders one
    player or one subject would otherwise have to request every other entity's
    rows and discard them — which is exactly what pushes a pose window past the
    point budget and forces a display reduction the renderer cannot use.
    """
    path = resolve_artifact_path(settings, ref)
    schema = pq.read_schema(path)
    if TIME_COLUMN not in schema.names:
        raise DenseWindowError(f"artifact {ref.artifact_id!r} has no canonical {TIME_COLUMN} axis")
    selected = _validate_columns(schema, columns)
    entity_sql, entity_params = _entity_predicate(schema, entity_id)
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

    source_rows = _window_row_count(path, lower, upper, entity_sql, entity_params)
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
            entity_sql=entity_sql,
            entity_params=entity_params,
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
        table = _exact_window(
            path,
            from_ns=lower,
            to_ns=upper,
            selected=selected,
            entity_id=entity_id,
        )
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


def entity_cardinality(settings: Settings, ref: ArtifactRefView) -> int | None:
    """Number of distinct entities interleaved in one artifact.

    A dense artifact puts every entity on one time axis, so the rows a viewer
    receives per second of recording depend on how many entities share it. The
    laboratory divides by this to size a window that fits its point budget in a
    single request instead of discovering the overrun after a reduction.
    ``None`` when the artifact has no entity column.
    """
    path = resolve_artifact_path(settings, ref)
    column = entity_column(pq.read_schema(path))
    if column is None:
        return None
    connection = _connect()
    try:
        row = connection.execute(
            f'SELECT count(DISTINCT "{column}") FROM read_parquet(?)', [path.as_posix()]
        ).fetchone()
    finally:
        connection.close()
    return int(row[0]) if row and row[0] is not None else None


def entity_ids(settings: Settings, ref: ArtifactRefView) -> list[str] | None:
    """Return the stable distinct entity identities present in an artifact."""
    path = resolve_artifact_path(settings, ref)
    column = entity_column(pq.read_schema(path))
    if column is None:
        return None
    connection = _connect()
    try:
        rows = connection.execute(
            f'SELECT DISTINCT CAST("{column}" AS VARCHAR) AS entity_id '
            "FROM read_parquet(?) WHERE "
            f'"{column}" IS NOT NULL ORDER BY entity_id',
            [path.as_posix()],
        ).fetchall()
    finally:
        connection.close()
    return [str(row[0]) for row in rows if row[0] is not None]


def entity_observations(
    settings: Settings,
    ref: ArtifactRefView,
    *,
    from_ns: int | None = None,
    to_ns: int | None = None,
) -> list[EntityObservationView] | None:
    """Return observed Pose-frame bounds without shipping frontend row scans.

    The authority is derived from canonical rows with usable coordinates, not
    from session roster membership or unavailable landmark rows.
    """
    if ref.modality != "pose":
        return None
    path = resolve_artifact_path(settings, ref)
    schema = pq.read_schema(path)
    column = entity_column(schema)
    required = {TIME_COLUMN, "is_available", "x_m", "y_m", "z_m"}
    if column is None or not required.issubset(schema.names):
        return []
    bounds: list[Any] = []
    time_filter = ""
    if from_ns is not None:
        time_filter += f' AND "{TIME_COLUMN}" >= ?'
        bounds.append(from_ns)
    if to_ns is not None:
        time_filter += f' AND "{TIME_COLUMN}" <= ?'
        bounds.append(to_ns)
    connection = _connect()
    try:
        rows = connection.execute(
            f'SELECT CAST("{column}" AS VARCHAR) AS entity_id, '
            f'MIN("{TIME_COLUMN}") AS first_observed_ns, '
            f'MAX("{TIME_COLUMN}") AS last_observed_ns, '
            f'COUNT(DISTINCT "{TIME_COLUMN}") AS observation_count '
            "FROM read_parquet(?) "
            f'WHERE "{column}" IS NOT NULL AND is_available = true '
            'AND "x_m" IS NOT NULL AND "y_m" IS NOT NULL AND "z_m" IS NOT NULL'
            f"{time_filter} "
            f'GROUP BY "{column}" ORDER BY entity_id',
            [path.as_posix(), *bounds],
        ).fetchall()
    finally:
        connection.close()
    return [
        EntityObservationView(
            entity_id=str(row[0]),
            first_observed_ns=int(row[1]),
            last_observed_ns=int(row[2]),
            observation_count=int(row[3]),
        )
        for row in rows
    ]


def canonical_timespan(settings: Settings, ref: ArtifactRefView) -> tuple[int | None, int | None]:
    """Canonical ``t_rel_ns`` bounds of one artifact.

    The laboratory needs these before it can choose a first window: a viewer
    cannot pick a default playhead without knowing where the recording starts.
    Both bounds are ``None`` for an artifact with no observed samples.
    """
    return _canonical_time_range(resolve_artifact_path(settings, ref))


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


def _window_row_count(
    path: Path,
    lower: int,
    upper: int,
    entity_sql: str = "",
    entity_params: list[Any] | None = None,
) -> int:
    connection = _connect()
    try:
        row = connection.execute(
            f"SELECT count(*) FROM read_parquet(?) "
            f"WHERE {TIME_COLUMN} >= ? AND {TIME_COLUMN} <= ?{entity_sql}",
            [path.as_posix(), lower, upper, *(entity_params or [])],
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
    entity_id: str | None = None,
) -> pa.Table:
    predicate = (ds.field(TIME_COLUMN) >= from_ns) & (ds.field(TIME_COLUMN) <= to_ns)
    schema = pq.read_schema(path)
    column = entity_column(schema)
    if entity_id is not None:
        if column is None:
            raise DenseWindowError(
                "this artifact declares no entity column, so it cannot be scoped to an entity"
            )
        predicate = predicate & (ds.field(column) == entity_id)
    read_columns = list(selected) if TIME_COLUMN in selected else [*selected, TIME_COLUMN]
    table = ds.dataset(path, format="parquet").to_table(columns=read_columns, filter=predicate)
    if table.num_rows > 1:
        table = table.sort_by([(TIME_COLUMN, "ascending")])
    return table if TIME_COLUMN in selected else table.select(list(selected))


def _reduced_window(
    path: Path,
    *,
    source_rows: int,
    from_ns: int,
    to_ns: int,
    selected: tuple[str, ...],
    schema: pa.Schema,
    max_points: int,
    entity_sql: str = "",
    entity_params: list[Any] | None = None,
) -> pa.Table:
    if max_points < 1:
        raise DenseWindowError("max_points must be at least 1")
    identity = [field.name for field in schema if _is_identity_key(field)]
    measures = [name for name in selected if _is_measure(schema.field(name))]
    identity_count = _identity_count(
        path,
        from_ns=from_ns,
        to_ns=to_ns,
        identity=identity,
        entity_sql=entity_sql,
        entity_params=entity_params,
    )
    points_per_identity = max(1, max_points // identity_count)
    # One extra nanosecond makes the bucket count a hard bound of the per-key
    # budget even when the last observed sample sits exactly on a bucket boundary.
    span_ns = max(1, to_ns - from_ns + 1)
    bucket_ns = max(1, math.ceil(span_ns / points_per_identity))
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
        f"SELECT * FROM read_parquet(?) WHERE t_rel_ns >= ? AND t_rel_ns <= ?{entity_sql}"
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
            [path.as_posix(), from_ns, to_ns, *(entity_params or []), from_ns, bucket_ns],
        ).to_arrow_table()
    finally:
        connection.close()


def _identity_count(
    path: Path,
    *,
    from_ns: int,
    to_ns: int,
    identity: list[str],
    entity_sql: str,
    entity_params: list[Any] | None,
) -> int:
    if not identity:
        return 1
    key_sql = ", ".join(f'"{name}"' for name in identity)
    connection = _connect()
    try:
        row = connection.execute(
            "SELECT count(*) FROM ("
            f"SELECT DISTINCT {key_sql} FROM read_parquet(?) "
            f"WHERE t_rel_ns >= ? AND t_rel_ns <= ?{entity_sql}"
            ")",
            [path.as_posix(), from_ns, to_ns, *(entity_params or [])],
        ).fetchone()
    finally:
        connection.close()
    return max(1, int(row[0])) if row and row[0] is not None else 1


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
    entity_id: str | None = None,
    representation: str = "json",
) -> str:
    """Strong ETag derived from immutable artifact identity and query parameters."""
    identity = json.dumps(
        {
            "checksum_sha256": ref.checksum_sha256,
            "from_ns": from_ns,
            "to_ns": to_ns,
            "columns": sorted(columns),
            "max_points": max_points,
            "entity_id": entity_id,
            "representation": representation,
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
    "ENTITY_COLUMNS",
    "ArtifactPathError",
    "DenseWindowError",
    "DenseWindowResult",
    "DenseWindowTooLarge",
    "arrow_ipc_stream",
    "canonical_timespan",
    "default_max_source_rows",
    "entity_cardinality",
    "entity_column",
    "entity_ids",
    "entity_observations",
    "load_artifact_window",
    "resolve_artifact_path",
    "table_records",
    "window_etag",
    "window_metadata_header",
]
