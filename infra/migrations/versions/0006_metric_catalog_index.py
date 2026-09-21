"""Widen the derived-metric metric index to cover metric/dataset discovery.

Revision ID: 0006_metric_catalog_index
Revises: 0005_serving_read_indexes
Create Date: 2026-09-20 03:10:00.000000

The metric catalog that drives comparison and methodology discovery reports,
for each registered metric, which datasets actually serve it. That question is
a distinct scan over ``(metric_id, dataset_id)``, which the single-column index
from 0005 cannot answer without reading every matching row: measured at 224 ms
for the whole catalog, or 489 ms when expressed as a DISTINCT inside the
aggregate.

Widening the existing index to ``(metric_id, dataset_id)`` makes that an
index-only scan and still serves every lookup the narrower index served, since
``metric_id`` remains the leading column. It replaces the old index rather than
adding a second one.

Downgrade restores the single-column form, which is lossless.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_metric_catalog_index"
down_revision: str | None = "0005_serving_read_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NARROW = "ix_derived_metric_metric"
_WIDE = "ix_derived_metric_metric_dataset"


def upgrade() -> None:
    op.create_index(_WIDE, "derived_metric", ["metric_id", "dataset_id"])
    op.drop_index(_NARROW, table_name="derived_metric")


def downgrade() -> None:
    op.create_index(_NARROW, "derived_metric", ["metric_id"])
    op.drop_index(_WIDE, table_name="derived_metric")
