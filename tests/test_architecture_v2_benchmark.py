from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from benchmarks.architecture_v2.benchmark_backend import (
    _bench_case,
    _entity_value,
    _synthetic_cases,
)


def test_synthetic_benchmark_preserves_reduced_row_budget(tmp_path: Path) -> None:
    cases = _synthetic_cases(tmp_path)
    result = _bench_case(tmp_path, next(case for case in cases if case.max_points == 4_000), 1)

    rows = {item["implementation"]: item["rows_median"] for item in result["implementations"]}
    assert (
        rows["pyarrow_dataset_reduced"]
        == rows["duckdb_parquet_reduced"]
        == rows["current_dense_service"]
        == 4_000
    )
    assert set(result["semantic_equivalence"]["validated"]) == {
        "pyarrow_dataset_reduced",
        "duckdb_parquet_reduced",
        "current_dense_service",
    }
    assert all("complete_ms_median" in item for item in result["implementations"])


def test_benchmark_entity_selection_reads_a_single_row_batch(tmp_path: Path) -> None:
    path = tmp_path / "pose.parquet"
    table = pa.table({"subject_id": ["first", "second", "third"], "t_rel_ns": [0, 1, 2]})
    pq.write_table(table, path, row_group_size=1)

    assert _entity_value(path, table.schema) == "first"
