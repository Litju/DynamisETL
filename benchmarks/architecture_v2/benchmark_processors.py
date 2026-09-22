"""Profile existing NumPy/SciPy/PyArrow processors on bounded workloads."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
import tracemalloc
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from dynamis.config import settings
from dynamis.fixtures.synthetic import all_fixtures
from dynamis.processors.cross_sensor import process_cross_sensor
from dynamis.processors.force_cmj import process_force_cmj
from dynamis.processors.imu import process_imu
from dynamis.processors.locomotor import process_locomotor
from dynamis.processors.lpt import process_lpt
from dynamis.processors.pose import process_pose


def _revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _force_with_finite_ratio(table: pa.Table) -> pa.Table:
    index = table.schema.get_field_index("force_z_body_weight_ratio")
    return table.set_column(
        index,
        table.schema.field(index),
        pa.array(np.ones(table.num_rows, dtype=np.float64)),
    )


def _synthetic_operations() -> list[tuple[str, pa.Table, Callable[[], Any]]]:
    fixtures = {fixture.name: fixture for fixture in all_fixtures()}
    force = _force_with_finite_ratio(fixtures["force_bodyweight_static"].table)
    imu = fixtures["imu_deterministic_trace"].table
    pose = fixtures["pose_skeleton_trajectory"].table
    joint_names = pose.column("joint_name").unique().to_pylist()
    return [
        ("force_cmj", force, lambda: process_force_cmj(force)),
        ("imu", imu, lambda: process_imu(imu)),
        (
            "locomotor_gnss",
            fixtures["gnss_constant_velocity"].table,
            lambda: process_locomotor(
                fixtures["gnss_constant_velocity"].table,
                parameters={
                    "position_domain": "geodetic",
                    "distance_method": "haversine_wgs84_mean_radius",
                    "enu_method": "equirectangular_tangent_plane_wgs84_mean_radius",
                    "earth_radius_m": 6_371_008.8,
                    "derivative": {"edge_policy": "one_sided_first_order"},
                },
            ),
        ),
        (
            "locomotor_tracking",
            fixtures["tracking_multi_object"].table,
            lambda: process_locomotor(
                fixtures["tracking_multi_object"].table,
                parameters={
                    "position_domain": "planar",
                    "derivative": {"edge_policy": "one_sided_first_order"},
                },
            ),
        ),
        (
            "lpt",
            fixtures["lpt_constant_acceleration"].table,
            lambda: process_lpt(fixtures["lpt_constant_acceleration"].table),
        ),
        (
            "pose",
            pose,
            lambda: process_pose(
                pose,
                parameters={
                    "segments": [
                        {
                            "name": "fixture_segment",
                            "start_landmark": joint_names[0],
                            "end_landmark": joint_names[1],
                        }
                    ],
                    "angles": [],
                    "derivative": {"edge_policy": "one_sided_first_order"},
                },
            ),
        ),
        (
            "cross_sensor",
            imu,
            lambda: process_cross_sensor(imu, force),
        ),
    ]


def _run(
    name: str, table: pa.Table, operation: Callable[[], Any], iterations: int
) -> dict[str, Any]:
    durations: list[float] = []
    peaks: list[int] = []
    result: Any = None
    for _ in range(iterations):
        tracemalloc.start()
        started = time.perf_counter()
        result = operation()
        durations.append((time.perf_counter() - started) * 1000)
        _current, peak = tracemalloc.get_traced_memory()
        peaks.append(peak)
        tracemalloc.stop()
    series_rows = sum(series.table.num_rows for series in getattr(result, "series", ()))
    p95 = statistics.quantiles(durations, n=20, method="inclusive")[18] if len(durations) >= 20 else None
    return {
        "processor": name,
        "input_rows": table.num_rows,
        "wall_ms_median": statistics.median(durations),
        "wall_ms_p95": p95,
        "wall_ms_max_observed": max(durations),
        "percentile_method": "inclusive_quantile_p95" if len(durations) >= 20 else "not_claimed_below_20_runs",
        "peak_python_alloc_bytes_median": statistics.median(peaks),
        "output_metric_count": len(getattr(result, "metrics", ())),
        "output_series_rows": series_rows,
    }


def _real_operations(root: Path) -> list[tuple[str, pa.Table, Callable[[], Any]]]:
    def first(fragment: str) -> Path | None:
        paths = [
            path for path in (root / "silver").rglob("*.parquet") if fragment in path.as_posix()
        ]
        return paths[0] if paths else None

    operations: list[tuple[str, pa.Table, Callable[[], Any]]] = []
    force_path = first("white-cmj-acc-grf/modality=force")
    if force_path:
        table = pq.read_table(force_path)
        operations.append(("real_force_cmj", table, lambda table=table: process_force_cmj(table)))
    imu_path = first("white-cmj-acc-grf/modality=imu")
    if imu_path:
        table = pq.read_table(imu_path)
        operations.append(("real_imu", table, lambda table=table: process_imu(table)))
    tracking_path = first("dfl-sportec-idsse/modality=tracking")
    if tracking_path:
        table = pq.read_table(tracking_path).slice(0, 100_000)
        operations.append(
            (
                "real_locomotor_tracking",
                table,
                lambda table=table: process_locomotor(
                    table,
                    parameters={
                        "position_domain": "planar",
                        "derivative": {"edge_policy": "one_sided_first_order"},
                    },
                ),
            )
        )
    return operations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("synthetic", "real", "both"), default="both")
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    operations: list[tuple[str, pa.Table, Callable[[], Any]]] = []
    if args.mode in ("synthetic", "both"):
        operations.extend(_synthetic_operations())
    if args.mode in ("real", "both"):
        operations.extend(_real_operations(settings().dataset_root))
    results = []
    for name, table, operation in operations:
        results.append(_run(name, table, operation, args.iterations))
    receipt = {
        "schema_version": "architecture-v2-processor-benchmark-1",
        "git_revision": _revision(),
        "iterations": args.iterations,
        "results": results,
        "decision": "keep_python_numpy_scipy_pyarrow; no Polars or Rust/PyO3 trigger met",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "results": len(results)}))


if __name__ == "__main__":
    main()
