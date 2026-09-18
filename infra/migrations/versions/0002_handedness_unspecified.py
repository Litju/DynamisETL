"""Coordinate frames may declare an explicitly unspecified handedness.

Revision ID: 0002_handedness_unspecified
Revises: 0001_bootstrap
Create Date: 2026-09-18 04:20:00.000000

A sensor or plate frame whose handedness is not documented by the source must be
representable honestly instead of being forced into ``right`` or ``left``. The
value is additive: existing ``right``/``left`` frames are untouched, and the
Pydantic contract requires an explicit description when handedness is declared
unspecified. The column widens from 8 to 16 characters so the new value fits,
and the distinct-axes check now matches the contract: two axes may coincide only
when the shared direction is explicitly undirected.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0002_handedness_unspecified"
down_revision: str | None = "0001_bootstrap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DISTINCT_AXES_RELAXED = (
    "("
    "x_direction <> y_direction OR x_direction IN ('unspecified','origin_dependent') "
    "OR y_direction IN ('unspecified','origin_dependent')"
    ") AND ("
    "x_direction <> z_direction OR x_direction IN ('unspecified','origin_dependent') "
    "OR z_direction IN ('unspecified','origin_dependent')"
    ") AND ("
    "y_direction <> z_direction OR y_direction IN ('unspecified','origin_dependent') "
    "OR z_direction IN ('unspecified','origin_dependent')"
    ")"
)

DISTINCT_AXES_STRICT = (
    "x_direction <> y_direction AND x_direction <> z_direction AND y_direction <> z_direction"
)


def upgrade() -> None:
    op.alter_column(
        "coordinate_frame",
        "handedness",
        existing_type=sa.String(length=8),
        type_=sa.String(length=16),
        existing_nullable=False,
    )
    op.drop_constraint(op.f("ck_coordinate_frame_handedness"), "coordinate_frame", type_="check")
    op.create_check_constraint(
        op.f("ck_coordinate_frame_handedness"),
        "coordinate_frame",
        "handedness IN ('right', 'left', 'unspecified')",
    )
    op.drop_constraint(op.f("ck_coordinate_frame_distinct_axes"), "coordinate_frame", type_="check")
    op.create_check_constraint(
        op.f("ck_coordinate_frame_distinct_axes"),
        "coordinate_frame",
        DISTINCT_AXES_RELAXED,
    )
    op.create_check_constraint(
        op.f("ck_coordinate_frame_unspecified_handedness_needs_description"),
        "coordinate_frame",
        "handedness <> 'unspecified' OR (description IS NOT NULL AND btrim(description) <> '')",
    )


def _incompatible_row_count() -> int:
    bind = op.get_bind()
    return int(
        bind.execute(
            sa.text(
                "SELECT count(*) FROM coordinate_frame WHERE handedness = 'unspecified' "
                "OR NOT ("
                "x_direction <> y_direction AND x_direction <> z_direction "
                "AND y_direction <> z_direction)"
            )
        ).scalar_one()
    )


def downgrade() -> None:
    # The pre-0002 constraints cannot represent an unspecified handedness or a
    # duplicated undirected axis. Refuse explicitly instead of silently
    # rewriting or dropping provenance rows; the operator must migrate them.
    if not context.is_offline_mode():
        incompatible = _incompatible_row_count()
        if incompatible:
            raise RuntimeError(
                f"cannot downgrade 0002_handedness_unspecified: {incompatible} "
                "coordinate_frame row(s) use unspecified handedness or a duplicated "
                "undirected axis. Migrate or explicitly delete those rows first."
            )
    op.drop_constraint(
        op.f("ck_coordinate_frame_unspecified_handedness_needs_description"),
        "coordinate_frame",
        type_="check",
    )
    op.drop_constraint(op.f("ck_coordinate_frame_distinct_axes"), "coordinate_frame", type_="check")
    op.create_check_constraint(
        op.f("ck_coordinate_frame_distinct_axes"),
        "coordinate_frame",
        DISTINCT_AXES_STRICT,
    )
    op.drop_constraint(op.f("ck_coordinate_frame_handedness"), "coordinate_frame", type_="check")
    op.create_check_constraint(
        op.f("ck_coordinate_frame_handedness"),
        "coordinate_frame",
        "handedness IN ('right', 'left')",
    )
    op.alter_column(
        "coordinate_frame",
        "handedness",
        existing_type=sa.String(length=16),
        type_=sa.String(length=8),
        existing_nullable=False,
    )
