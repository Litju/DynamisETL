"""Preserve raw provider metadata on catalog entries.

Revision ID: 0010_provider_catalog_meta
Revises: 0009_multisport_semantic_catalog
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_provider_catalog_meta"
down_revision: str | None = "0009_multisport_semantic_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_catalog_entry",
        sa.Column(
            "provider_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("source_catalog_entry", "provider_metadata")
