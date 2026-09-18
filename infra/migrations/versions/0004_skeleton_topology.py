"""Skeletons declare their topology instead of being forced into a tree.

Revision ID: 0004_skeleton_topology
Revises: 0003_sync_alignment
Create Date: 2026-09-18 20:30:00.000000

RES-99 ingests provider pose whose source publishes an ordered landmark/keypoint
list without any parent graph (football body pose, basketball markerless
keypoints). Forcing those rows into the single-root tree form would fabricate
anatomical parentage, so ``skeleton_definition`` gains an explicit ``topology``
column:

* ``tree`` (the server default) keeps the existing single-root parent-graph
  authority; every already-persisted row is a tree by construction;
* ``landmark_set`` records that the source declares no parent graph at all, and
  the Pydantic contract then forbids parent ids on its joints.

Downgrade refuses to drop the column while any ``landmark_set`` row exists,
because the pre-0004 schema cannot represent that topology and re-upgrading would
silently relabel the landmark list as a tree. Offline (``--sql``) mode cannot
inspect the persisted rows, so it refuses before emitting destructive DDL.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0004_skeleton_topology"
down_revision: str | None = "0003_sync_alignment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "skeleton_definition",
        sa.Column(
            "topology",
            sa.String(length=16),
            server_default=sa.text("'tree'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_skeleton_definition_topology"),
        "skeleton_definition",
        "topology IN ('tree', 'landmark_set')",
    )


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError(
            "cannot downgrade 0004_skeleton_topology in offline (--sql) mode: persisted "
            "landmark_set skeleton evidence cannot be inspected without a live database, "
            "so ALTER TABLE ... DROP COLUMN topology is refused. Run the downgrade against "
            "a live database where the persisted row count can be checked."
        )
    bind = op.get_bind()
    persisted = int(
        bind.execute(
            sa.text("SELECT count(*) FROM skeleton_definition WHERE topology = 'landmark_set'")
        ).scalar_one()
    )
    if persisted:
        raise RuntimeError(
            f"cannot downgrade 0004_skeleton_topology: {persisted} skeleton_definition "
            "row(s) declare landmark_set topology, which the pre-0004 schema cannot "
            "represent. Migrate or explicitly delete those rows first."
        )
    op.drop_constraint(
        op.f("ck_skeleton_definition_topology"), "skeleton_definition", type_="check"
    )
    op.drop_column("skeleton_definition", "topology")
