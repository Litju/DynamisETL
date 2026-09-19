"""Deterministic Parquet export of the control plane for dbt-duckdb.

dbt-duckdb must not attach PostgreSQL (that would require downloading a DuckDB
extension and would blur the serving/control-plane boundary). Instead the
control-plane rows are exported to immutable Parquet under ``gold/serving`` with
a fixed column order, a deterministic row order (primary key), explicit value
serialization for JSON and timestamps, and a checksum receipt. The same source
state therefore always yields byte-identical serving files.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import JSONB

from dynamis.config import Settings
from dynamis.storage.atomic import atomic_write_text
from dynamis.storage.metadata import build_metadata
from dynamis.storage.parquet import write_parquet_atomic
from dynamis.storage.paths import receipt_path, relative_posix

_TABLES = build_metadata().tables

#: Control-plane tables exported for relational Gold serving.
SERVING_TABLES: tuple[str, ...] = (
    "algorithm_spec",
    "dataset_source",
    "derived_metric",
    "metric_definition",
    "processing_artifact",
    "processing_run",
    "sample_artifact",
    "sensor_stream",
    "session",
    "subject",
    "sync_alignment",
    "trial",
)


@dataclass(frozen=True, slots=True)
class ServingExport:
    root: Path
    tables: dict[str, dict[str, Any]]
    receipt_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "tables": self.tables,
            "receipt_path": self.receipt_path,
        }


def serving_root(settings: Settings) -> Path:
    return settings.dataset_root / "gold" / "serving"


def _arrow_type(column: sa.Column) -> pa.DataType:
    if isinstance(column.type, JSONB):
        return pa.string()
    if isinstance(column.type, (sa.DateTime, sa.Date)):
        return pa.string()
    if isinstance(column.type, sa.Boolean):
        return pa.bool_()
    if isinstance(column.type, sa.Float):
        return pa.float64()
    if isinstance(column.type, (sa.Integer, sa.BigInteger)):
        return pa.int64()
    return pa.string()


def _serialize(column: sa.Column, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(column.type, JSONB):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def export_serving(
    settings: Settings,
    engine: Engine,
    *,
    tables: tuple[str, ...] = SERVING_TABLES,
) -> ServingExport:
    """Export the selected control-plane tables to deterministic Parquet."""
    root = serving_root(settings)
    root.mkdir(parents=True, exist_ok=True)
    summary: dict[str, dict[str, Any]] = {}
    with engine.connect() as connection:
        for name in tables:
            table = _TABLES[name]
            order = [table.c[column.name] for column in table.primary_key.columns]
            rows = (
                connection.execute(sa.select(table).order_by(*order)).mappings().all()
                if order
                else connection.execute(sa.select(table)).mappings().all()
            )
            columns = list(table.columns)
            arrow_schema = pa.schema(
                [pa.field(column.name, _arrow_type(column)) for column in columns]
            )
            payload = {
                column.name: [_serialize(column, row[column.name]) for row in rows]
                for column in columns
            }
            arrow_table = pa.Table.from_pydict(payload, schema=arrow_schema)
            artifact = write_parquet_atomic(
                arrow_table,
                root / f"{name}.parquet",
                relative_to=settings.dataset_root,
            )
            summary[name] = {
                "relative_path": artifact.relative_path,
                "row_count": artifact.row_count,
                "checksum_sha256": artifact.checksum_sha256,
            }
    receipt = {
        "kind": "gold_serving_export",
        "tables": summary,
    }
    target = receipt_path(settings, dataset_id="platform", kind="gold", name="serving-export")
    atomic_write_text(target, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return ServingExport(
        root=root,
        tables=summary,
        receipt_path=relative_posix(settings.dataset_root, target),
    )


__all__ = ["SERVING_TABLES", "ServingExport", "export_serving", "serving_root"]
