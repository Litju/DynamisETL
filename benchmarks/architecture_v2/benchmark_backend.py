"""Benchmark complete dense-window costs on local and synthetic Parquet.

The real mode reads only summary metadata and returns aggregate timings. It never
copies source rows into the repository or the receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import tempfile
import time
import tracemalloc
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from dynamis.config import Settings, settings
from dynamis.serving.dense import (
    TIME_COLUMN,
    arrow_ipc_stream,
    entity_column,
    load_artifact_window,
)
from dynamis.serving.models import ArtifactRefView


@dataclass(frozen=True)
class Case:
    name: str
    path: Path
    from_ns: int
    to_ns: int
    columns: tuple[str, ...]
    max_points: int | None = None
    entity_id: str | None = None


def _git_revision() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _time_bounds(path: Path) -> tuple[int, int]:
    parquet = pq.ParquetFile(path)
    minimum: int | None = None
    maximum: int | None = None
    index = parquet.schema_arrow.get_field_index(TIME_COLUMN)
    for row_group in range(parquet.metadata.num_row_groups):
        stats = parquet.metadata.row_group(row_group).column(index).statistics
        if stats is None or stats.min is None or stats.max is None:
            continue
        minimum = int(stats.min) if minimum is None else min(minimum, int(stats.min))
        maximum = int(stats.max) if maximum is None else max(maximum, int(stats.max))
    if minimum is not None and maximum is not None:
        return minimum, maximum
    values = pq.read_table(path, columns=[TIME_COLUMN])[TIME_COLUMN].to_numpy()
    return int(values.min()), int(values.max())


def _row_group_bytes(path: Path, lower: int, upper: int) -> int:
    parquet = pq.ParquetFile(path)
    time_index = parquet.schema_arrow.get_field_index(TIME_COLUMN)
    total = 0
    for row_group in range(parquet.metadata.num_row_groups):
        group = parquet.metadata.row_group(row_group)
        stats = group.column(time_index).statistics
        if stats is not None and (int(stats.max) < lower or int(stats.min) > upper):
            continue
        total += sum(
            group.column(column).total_compressed_size for column in range(group.num_columns)
        )
    return total or path.stat().st_size


def _numeric_columns(schema: pa.Schema) -> tuple[str, ...]:
    excluded = {TIME_COLUMN, "timestamp_utc_ns", "sample_index"}
    output: list[str] = []
    for field in schema:
        if field.name in excluded or field.name.endswith("_id"):
            continue
        if pa.types.is_integer(field.type) or pa.types.is_floating(field.type):
            output.append(field.name)
    return tuple(output[:4])


def _identity_columns(schema: pa.Schema) -> tuple[str, ...]:
    excluded = {TIME_COLUMN, "timestamp_utc_ns", "sample_index"}
    output: list[str] = []
    for field in schema:
        if field.name in excluded:
            continue
        if pa.types.is_string(field.type) or pa.types.is_boolean(field.type):
            output.append(field.name)
        elif (
            pa.types.is_integer(field.type) or pa.types.is_floating(field.type)
        ) and field.name.endswith("_id"):
            output.append(field.name)
    return tuple(output)


def _entity_value(path: Path, schema: pa.Schema) -> str | None:
    name = entity_column(schema)
    if name is None:
        return None
    value = pq.read_table(path, columns=[name]).column(0)[0].as_py()
    return str(value) if value is not None else None


def _ref(root: Path, path: Path) -> ArtifactRefView:
    parquet = pq.ParquetFile(path)
    relative = path.resolve().relative_to(root.resolve()).as_posix()
    return ArtifactRefView(
        artifact_id="benchmark-" + hashlib.sha1(relative.encode()).hexdigest()[:12],
        dataset_id="benchmark",
        stream_id="benchmark-stream",
        layer="silver",
        relative_path=relative,
        format="parquet",
        compression="zstd",
        checksum_sha256="benchmark-only",
        row_count=parquet.metadata.num_rows,
        byte_size=path.stat().st_size,
        artifact_kind="sample",
        modality="benchmark",
        measurement_class="SOURCE_MEASURED",
        si_units=[],
        coordinate_frame_id=None,
        synchronization_spec_id=None,
    )


def _query_pyarrow(path: Path, case: Case) -> pa.Table:
    schema = pq.read_schema(path)
    condition = (ds.field(TIME_COLUMN) >= case.from_ns) & (ds.field(TIME_COLUMN) <= case.to_ns)
    entity = entity_column(schema)
    if case.entity_id is not None and entity is not None:
        condition = condition & (ds.field(entity) == case.entity_id)
    columns = list(case.columns)
    if entity is not None and entity not in columns:
        columns.insert(0, entity)
    if TIME_COLUMN not in columns:
        columns.insert(0, TIME_COLUMN)
    return ds.dataset(path, format="parquet").to_table(columns=columns, filter=condition)


def _query_pyarrow_reduced(path: Path, case: Case) -> pa.Table:
    schema = pq.read_schema(path)
    identity = _identity_columns(schema)
    exact_case = Case(
        case.name,
        case.path,
        case.from_ns,
        case.to_ns,
        tuple(case.columns),
        entity_id=case.entity_id,
    )
    table = _query_pyarrow(path, exact_case)
    if table.num_rows <= int(case.max_points or 0):
        return table
    missing_identity = [name for name in identity if name not in table.column_names]
    if missing_identity:
        table = _query_pyarrow(
            path,
            Case(
                case.name,
                case.path,
                case.from_ns,
                case.to_ns,
                tuple((*case.columns, *missing_identity)),
                entity_id=case.entity_id,
            ),
        )
    identity_count = (
        table.group_by(list(identity)).aggregate([(TIME_COLUMN, "count")]).num_rows
        if identity
        else 1
    )
    points_per_identity = max(1, int(case.max_points or 1) // max(1, identity_count))
    span_ns = max(1, case.to_ns - case.from_ns + 1)
    bucket_ns = max(1, int(np.ceil(span_ns / points_per_identity)))
    offset = pc.subtract(table[TIME_COLUMN], pa.scalar(case.from_ns, type=pa.int64()))
    bucket = pc.cast(pc.floor(pc.divide(pc.cast(offset, pa.float64()), bucket_ns)), pa.int64())
    table = table.append_column("__bucket", bucket)
    keys = [*identity, "__bucket"]
    aggregates: list[tuple[str, str]] = [
        (TIME_COLUMN, "min"),
        (TIME_COLUMN, "max"),
        (TIME_COLUMN, "count"),
    ]
    aggregates.extend((name, aggregate) for name in case.columns for aggregate in ("min", "max"))
    return table.group_by(keys).aggregate(aggregates)


def _query_duckdb(path: Path, case: Case) -> pa.Table:
    schema = pq.read_schema(path)
    entity = entity_column(schema)
    columns = list(case.columns)
    if entity is not None and entity not in columns:
        columns.insert(0, entity)
    if TIME_COLUMN not in columns:
        columns.insert(0, TIME_COLUMN)
    projection = ", ".join('"' + column.replace('"', '""') + '"' for column in columns)
    sql = f'SELECT {projection} FROM read_parquet(?) WHERE "{TIME_COLUMN}" BETWEEN ? AND ?'
    parameters: list[Any] = [str(path), case.from_ns, case.to_ns]
    if case.entity_id is not None and entity is not None:
        sql += f' AND "{entity}" = ?'
        parameters.append(case.entity_id)
    with duckdb.connect(database=":memory:") as connection:
        return connection.execute(sql, parameters).to_arrow_table()


def _query_duckdb_reduced(path: Path, case: Case) -> pa.Table:
    exact = _query_duckdb(path, case)
    if exact.num_rows <= int(case.max_points or 0):
        return exact
    schema = pq.read_schema(path)
    identity = _identity_columns(schema)
    entity = entity_column(schema)
    columns = [*identity, TIME_COLUMN, *case.columns]
    columns = list(dict.fromkeys(columns))
    projection = ", ".join('"' + column.replace('"', '""') + '"' for column in columns)
    where = f'WHERE "{TIME_COLUMN}" BETWEEN ? AND ?'
    parameters: list[Any] = [str(path), case.from_ns, case.to_ns]
    if case.entity_id is not None and entity is not None:
        where += f' AND "{entity}" = ?'
        parameters.append(case.entity_id)
    with duckdb.connect(database=":memory:") as connection:
        if identity:
            identity_sql = ", ".join(f'"{name}"' for name in identity)
            identity_count = connection.execute(
                "SELECT count(*) FROM ("
                f"SELECT DISTINCT {identity_sql} FROM read_parquet(?) {where})",
                parameters,
            ).fetchone()[0]
        else:
            identity_count = 1
        points_per_identity = max(1, int(case.max_points or 1) // max(1, int(identity_count)))
        span_ns = max(1, case.to_ns - case.from_ns + 1)
        bucket_ns = max(1, int(np.ceil(span_ns / points_per_identity)))
        identity_select = f"{identity_sql}, " if identity else ""
        group_keys = f"{identity_sql}, __bucket" if identity else "__bucket"
        order_keys = f"{identity_sql}, " if identity else ""
        aggregates = [
            f'MIN("{TIME_COLUMN}") AS t_rel_ns_min',
            f'MAX("{TIME_COLUMN}") AS t_rel_ns_max',
            "COUNT(*) AS t_rel_ns_count",
        ]
        aggregates.extend(
            f'MIN("{name}") AS "{name}_min", MAX("{name}") AS "{name}_max"' for name in case.columns
        )
        sql = (
            f"WITH windowed AS (SELECT {projection} FROM read_parquet(?) {where}), "
            f'bucketed AS (SELECT *, FLOOR(("{TIME_COLUMN}" - ?) / ?) AS __bucket FROM windowed) '
            f"SELECT {identity_select}__bucket, {', '.join(aggregates)} "
            f"FROM bucketed GROUP BY {group_keys} ORDER BY {order_keys}__bucket"
        )
        return connection.execute(sql, [*parameters, case.from_ns, bucket_ns]).to_arrow_table()


def _timed(label: str, operation: Callable[[], pa.Table]) -> dict[str, Any]:
    tracemalloc.start()
    started = time.perf_counter()
    table = operation()
    elapsed_ms = (time.perf_counter() - started) * 1000
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    arrow_started = time.perf_counter()
    payload = arrow_ipc_stream(table)
    arrow_ms = (time.perf_counter() - arrow_started) * 1000
    return {
        "implementation": label,
        "wall_ms": elapsed_ms,
        "arrow_serialization_ms": arrow_ms,
        "arrow_bytes": len(payload),
        "rows": table.num_rows,
        "columns": table.num_columns,
        "peak_python_alloc_bytes": peak,
    }


def _summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    keys = ("wall_ms", "arrow_serialization_ms", "arrow_bytes", "rows", "peak_python_alloc_bytes")
    result: dict[str, Any] = {"implementation": runs[0]["implementation"], "runs": len(runs)}
    for key in keys:
        values = [float(run[key]) for run in runs]
        result[key + "_median"] = statistics.median(values)
        result[key + "_p95"] = (
            max(values) if len(values) < 20 else statistics.quantiles(values, n=20)[18]
        )
    return result


def _bench_case(root: Path, case: Case, iterations: int) -> dict[str, Any]:
    ref = _ref(root, case.path)
    case_meta = asdict(case)
    case_meta["path"] = case.path.relative_to(root).as_posix()
    case_meta["parquet_bytes"] = case.path.stat().st_size
    case_meta["estimated_row_group_bytes"] = _row_group_bytes(case.path, case.from_ns, case.to_ns)

    settings_for_case = Settings(
        dataset_root=root,
        database_root=root / "databases",
        duckdb_path=root / "databases" / "benchmark.duckdb",
    )
    operations: list[tuple[str, Callable[[], pa.Table]]] = [
        (
            "pyarrow_dataset_reduced" if case.max_points is not None else "pyarrow_dataset_exact",
            lambda: (
                _query_pyarrow_reduced(case.path, case)
                if case.max_points is not None
                else _query_pyarrow(case.path, case)
            ),
        ),
        (
            "duckdb_parquet_reduced" if case.max_points is not None else "duckdb_parquet_exact",
            lambda: (
                _query_duckdb_reduced(case.path, case)
                if case.max_points is not None
                else _query_duckdb(case.path, case)
            ),
        ),
        (
            "current_dense_service",
            lambda: (
                load_artifact_window(
                    settings_for_case,
                    ref,
                    from_ns=case.from_ns,
                    to_ns=case.to_ns,
                    columns=case.columns,
                    max_points=case.max_points,
                    entity_id=case.entity_id,
                ).table
            ),
        ),
    ]
    implementations: list[dict[str, Any]] = []
    for label, operation in operations:
        operation()
        implementations.append(_summary([_timed(label, operation) for _ in range(iterations)]))

    def concurrent_call() -> int:
        with ThreadPoolExecutor(max_workers=4) as pool:
            return sum(table.num_rows for table in pool.map(lambda _unused: operation(), range(4)))

    concurrent_started = time.perf_counter()
    concurrent_rows = concurrent_call()
    concurrent_ms = (time.perf_counter() - concurrent_started) * 1000
    return {
        "case": case_meta,
        "implementations": implementations,
        "four_request_concurrency": {
            "wall_ms": concurrent_ms,
            "rows": concurrent_rows,
            "requests": 4,
        },
    }


def _write_synthetic(root: Path) -> list[Path]:
    paths: list[Path] = []
    for name, rows, subjects in (
        ("signal-4k", 4096, 1),
        ("signal-20k", 20_000, 1),
        ("signal-100k", 100_000, 1),
        ("pose-23-subjects", 100_000, 23),
        ("dense-maximum-fixture", 500_000, 1),
    ):
        path = root / "silver" / f"{name}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        t = np.arange(rows, dtype=np.int64) * 1_000_000 - 2_000_000_000
        subject = np.array([f"subject-{index % subjects:02d}" for index in range(rows)])
        table = pa.table(
            {
                TIME_COLUMN: pa.array(t),
                "subject_id": pa.array(subject),
                "force_n": pa.array(np.sin(np.arange(rows) / 31.0) * 800.0 + 1200.0),
                "imu_x": pa.array(np.cos(np.arange(rows) / 17.0)),
                "imu_y": pa.array(np.sin(np.arange(rows) / 13.0)),
            }
        )
        pq.write_table(table, path, compression="zstd", row_group_size=10_000)
        paths.append(path)
    return paths


def _synthetic_cases(root: Path) -> list[Case]:
    paths = _write_synthetic(root)
    by_name = {path.stem: path for path in paths}
    return [
        Case(
            "synthetic_exact_4k",
            by_name["signal-4k"],
            -2_000_000_000,
            2_095_000_000,
            ("force_n", "imu_x", "imu_y"),
        ),
        Case(
            "synthetic_reduced_20k",
            by_name["signal-20k"],
            -2_000_000_000,
            17_999_000_000,
            ("force_n", "imu_x"),
            4_000,
        ),
        Case(
            "synthetic_reduced_100k",
            by_name["signal-100k"],
            -2_000_000_000,
            97_999_000_000,
            ("force_n", "imu_x"),
            10_000,
        ),
        Case(
            "synthetic_pose_entity_exact",
            by_name["pose-23-subjects"],
            -2_000_000_000,
            97_999_000_000,
            ("force_n", "imu_x"),
            entity_id="subject-07",
        ),
        Case(
            "synthetic_maximum_allowed",
            by_name["dense-maximum-fixture"],
            -2_000_000_000,
            497_999_000_000,
            ("force_n", "imu_x"),
            100_000,
        ),
    ]


def _real_cases(root: Path) -> list[Case]:
    candidates = list((root / "silver").rglob("*.parquet"))
    if not candidates:
        return []
    selections: list[tuple[str, str, int, str | None]] = [
        ("white_cmj", "white-cmj-acc-grf/modality=force", 4_000, None),
        ("gnss", "womens-soccer-positioning/modality=gnss", 20_000, None),
        ("dfl_tracking", "dfl-sportec-idsse/modality=tracking", 100_000, "entity"),
        ("skillcorner_pose", "skillcorner-opendata/modality=pose", 100_000, "entity"),
    ]
    cases: list[Case] = []
    for name, fragment, target_rows, entity_mode in selections:
        matching = [
            path for path in candidates if fragment in path.relative_to(root / "silver").as_posix()
        ]
        if not matching:
            continue
        path = min(
            matching, key=lambda item: abs(pq.ParquetFile(item).metadata.num_rows - target_rows)
        )
        parquet = pq.ParquetFile(path)
        schema = parquet.schema_arrow
        lower, upper = _time_bounds(path)
        span = max(1, upper - lower)
        row_count = max(1, parquet.metadata.num_rows)
        window = min(span, max(1, int(span * min(target_rows, row_count) / row_count)))
        entity_id = _entity_value(path, schema) if entity_mode == "entity" else None
        columns = _numeric_columns(schema)
        cases.append(
            Case(
                name=f"real_{name}",
                path=path,
                from_ns=lower,
                to_ns=lower + window,
                columns=columns,
                max_points=10_000 if target_rows >= 20_000 else None,
                entity_id=entity_id,
            )
        )
    if candidates:
        path = max(candidates, key=lambda item: pq.ParquetFile(item).metadata.num_rows)
        parquet = pq.ParquetFile(path)
        lower, upper = _time_bounds(path)
        span = max(1, upper - lower)
        # Keep a margin under the production 5M source-row cap because source
        # timestamps are not uniformly distributed across every artifact.
        window = min(span, max(1, int(span * 4_000_000 / max(1, parquet.metadata.num_rows))))
        cases.append(
            Case(
                "real_maximum_allowed",
                path,
                lower,
                lower + window,
                _numeric_columns(parquet.schema_arrow),
                max_points=100_000,
                entity_id=None,
            )
        )
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("synthetic", "real", "both"), default="both")
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.iterations < 1:
        raise SystemExit("--iterations must be positive")

    results: dict[str, Any] = {
        "schema_version": "architecture-v2-backend-benchmark-1",
        "git_revision": _git_revision(),
        "python": os.sys.version.split()[0],
        "iterations": args.iterations,
        "cases": [],
    }
    with tempfile.TemporaryDirectory(prefix="dynamis-res109-synthetic-") as temporary:
        synthetic_root = Path(temporary)
        if args.mode in ("synthetic", "both"):
            results["cases"].extend(
                {"workload": "synthetic", **_bench_case(synthetic_root, case, args.iterations)}
                for case in _synthetic_cases(synthetic_root)
            )
    if args.mode in ("real", "both"):
        real_root = settings().dataset_root
        results["real_root_summary"] = {"configured": True, "root_name": real_root.name}
        results["cases"].extend(
            {"workload": "real", **_bench_case(real_root, case, args.iterations)}
            for case in _real_cases(real_root)
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "cases": len(results["cases"]),
                "git_revision": results["git_revision"],
            }
        )
    )


if __name__ == "__main__":
    main()
