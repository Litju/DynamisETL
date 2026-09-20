"""Index the serving read paths so analytical surfaces stop sequentially scanning.

Revision ID: 0005_serving_read_indexes
Revises: 0004_skeleton_topology
Create Date: 2026-09-20 01:45:00.000000

The control plane was created with primary keys and uniqueness constraints only.
Several serving queries filter or aggregate on columns that no index covers, so
PostgreSQL resolves them with sequential scans over the largest authorities:

* ``GET /api/runs`` computes a per-run metric count with a correlated subquery
  over ``derived_metric``. With ~77k derived metrics and 200 runs per page that
  is 200 sequential scans; measured locally at 69 s for one page.
* ``GET /api/catalog/datasets`` aggregates eight per-dataset counts the same
  way; measured locally at 2.7 s.
* Session detail, quality filtering and provenance checksum resolution scan
  ``sensor_stream``, ``quality_issue``, ``sample_artifact`` and
  ``processing_artifact`` for the same reason.

RES-108 allows investigating this latency but forbids denormalizing the
scientific authorities to hide it. Indexes do neither: no column, constraint,
uniqueness rule or measurement semantic changes, and every table keeps exactly
the rows and keys it had before. Tables whose primary key already leads with the
filtered column (``session``, ``trial``, ``subject``, ``session_participant``,
``dataset_version``, ``dataset_source_modality``) are deliberately untouched.

Downgrade drops only the indexes this revision created, which is lossless.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005_serving_read_indexes"
down_revision: str | None = "0004_skeleton_topology"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (index name, table, columns) in creation order.
_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ix_derived_metric_dataset_session", "derived_metric", ("dataset_id", "session_id")),
    ("ix_derived_metric_run", "derived_metric", ("run_id",)),
    ("ix_derived_metric_metric", "derived_metric", ("metric_id",)),
    ("ix_derived_metric_stream", "derived_metric", ("stream_id",)),
    ("ix_processing_run_dataset", "processing_run", ("dataset_id",)),
    ("ix_processing_run_started_at", "processing_run", ("started_at",)),
    ("ix_processing_artifact_run", "processing_artifact", ("run_id",)),
    ("ix_processing_artifact_checksum", "processing_artifact", ("checksum_sha256",)),
    ("ix_quality_issue_dataset_session", "quality_issue", ("dataset_id", "session_id")),
    ("ix_sample_artifact_dataset_stream", "sample_artifact", ("dataset_id", "stream_id")),
    ("ix_sample_artifact_checksum", "sample_artifact", ("checksum_sha256",)),
    ("ix_sensor_stream_dataset_session", "sensor_stream", ("dataset_id", "session_id")),
)


def upgrade() -> None:
    for name, table, columns in _INDEXES:
        op.create_index(name, table, list(columns))


def downgrade() -> None:
    for name, table, _columns in reversed(_INDEXES):
        op.drop_index(name, table_name=table)
