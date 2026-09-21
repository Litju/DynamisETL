"""Persist provider-published skeleton display connections.

Revision ID: 0007_skeleton_display_connections
Revises: 0006_metric_catalog_index
Create Date: 2026-09-21 00:00:00.000000

The display topology is distinct from ``skeleton_joint.parent_joint_id``:
landmark-set providers may publish drawable pairs without publishing an
anatomical parent graph.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_skeleton_display_connections"
down_revision: str | None = "0006_metric_catalog_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "skeleton_definition",
        sa.Column(
            "display_connections",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("skeleton_definition", "display_connections")
