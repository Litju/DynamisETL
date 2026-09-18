"""Persist explicit cross-stream synchronisation alignments.

Revision ID: 0003_sync_alignment
Revises: 0002_handedness_unspecified
Create Date: 2026-09-18 12:00:00.000000

RES-98 constructs one explicit force -> IMU :class:`SyncAlignment` per accepted
White trial on the released takeoff-relative axis, but PostgreSQL previously
dropped ``SourceAuthorities.alignments`` at persistence time. This revision adds
the additive first-class ``sync_alignment`` control-plane table:

* dataset-scoped composite foreign keys to ``sensor_stream`` for both endpoints,
  so an alignment can never pair streams across datasets;
* a foreign key to ``synchronization_spec``, so an alignment cannot exist
  without its declared synchronization authority;
* a deterministic primary key
  (``dataset_id``, ``source_stream_id``, ``target_stream_id``, ``sync_spec_id``)
  with no random identity;
* checks for a strict source != target pair and a positive, finite scale.

The table is a declaration, not an accuracy claim: scale 1 / offset 0 states a
shared released coordinate, never zero original-instrument timing error.

Downgrade drops the additive table only while it is empty; persisted alignment
evidence is never silently discarded. Offline (``--sql``) downgrade is refused
outright because the persisted evidence cannot be inspected without a live
connection, so no destructive DDL is ever emitted for this revision offline.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0003_sync_alignment"
down_revision: str | None = "0002_handedness_unspecified"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sync_alignment",
        sa.Column("dataset_id", sa.String(length=64), nullable=False),
        sa.Column("source_stream_id", sa.String(length=128), nullable=False),
        sa.Column("target_stream_id", sa.String(length=128), nullable=False),
        sa.Column("sync_spec_id", sa.String(length=128), nullable=False),
        sa.Column("offset_ns", sa.BigInteger(), nullable=False),
        sa.Column("scale", sa.Float(), server_default=sa.text("1.0"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "source_stream_id <> target_stream_id",
            name=op.f("ck_sync_alignment_not_self_referential"),
        ),
        sa.CheckConstraint(
            "scale > 0 AND scale <> 'NaN'::double precision "
            "AND scale <> 'Infinity'::double precision",
            name=op.f("ck_sync_alignment_positive_finite_scale"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "source_stream_id"],
            ["sensor_stream.dataset_id", "sensor_stream.stream_id"],
            name="fk_sync_alignment_source_stream",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "target_stream_id"],
            ["sensor_stream.dataset_id", "sensor_stream.stream_id"],
            name="fk_sync_alignment_target_stream",
        ),
        sa.ForeignKeyConstraint(
            ["sync_spec_id"],
            ["synchronization_spec.sync_spec_id"],
            name=op.f("fk_sync_alignment_sync_spec_id_synchronization_spec"),
        ),
        sa.PrimaryKeyConstraint(
            "dataset_id",
            "source_stream_id",
            "target_stream_id",
            "sync_spec_id",
            name=op.f("pk_sync_alignment"),
        ),
    )


def downgrade() -> None:
    # The revision is purely additive, but its rows are persisted synchronization
    # evidence. Offline mode cannot inspect them, so refuse before any destructive
    # DDL is emitted; online, refuse while any row is still present. In both cases
    # the operator must delete the rows deliberately (or re-run the deterministic
    # ingestion after downgrading).
    if context.is_offline_mode():
        raise RuntimeError(
            "cannot downgrade 0003_sync_alignment in offline (--sql) mode: persisted "
            "synchronization evidence cannot be inspected without a live database, so "
            "DROP TABLE sync_alignment is refused. Run the downgrade against a live "
            "database where the persisted row count can be checked."
        )
    bind = op.get_bind()
    persisted = int(bind.execute(sa.text("SELECT count(*) FROM sync_alignment")).scalar_one())
    if persisted:
        raise RuntimeError(
            f"cannot downgrade 0003_sync_alignment: {persisted} sync_alignment "
            "row(s) hold persisted synchronization evidence. Delete or migrate "
            "those rows deliberately before downgrading."
        )
    op.drop_table("sync_alignment")
