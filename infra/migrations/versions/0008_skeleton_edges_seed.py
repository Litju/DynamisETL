"""Backfill the pinned SkillCorner display topology into existing rows.

Revision ID: 0008_skeleton_edges_seed
Revises: 0007_skeleton_display
Create Date: 2026-09-21 06:30:00.000000

Migration 0007 added the typed storage column, but installations that already
held the SkillCorner skeleton received the empty default. Seed only that empty
row; a non-empty declaration remains authoritative and is never overwritten.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_skeleton_edges_seed"
down_revision: str | None = "0007_skeleton_display"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SKILLCORNER_SKELETON_ID = "skillcorner-bodypose-29-landmarks"
_DISPLAY_CONNECTIONS = (
    ("nose", "neck"),
    ("nose", "lEye"),
    ("nose", "rEye"),
    ("lEye", "lEar"),
    ("rEye", "rEar"),
    ("neck", "lShoulder"),
    ("neck", "rShoulder"),
    ("neck", "midHip"),
    ("lShoulder", "lElbow"),
    ("lElbow", "lWrist"),
    ("rShoulder", "rElbow"),
    ("rElbow", "rWrist"),
    ("lWrist", "lThumb"),
    ("lWrist", "lPinky"),
    ("rWrist", "rThumb"),
    ("rWrist", "rPinky"),
    ("midHip", "lHip"),
    ("midHip", "rHip"),
    ("lHip", "lKnee"),
    ("lKnee", "lAnkle"),
    ("rHip", "rKnee"),
    ("rKnee", "rAnkle"),
    ("lAnkle", "lHeel"),
    ("lAnkle", "lBigToe"),
    ("lBigToe", "lSmallToe"),
    ("rAnkle", "rHeel"),
    ("rAnkle", "rBigToe"),
    ("rBigToe", "rSmallToe"),
)
_DISPLAY_CONNECTIONS_JSON = json.dumps(
    [{"start_joint_name": start, "end_joint_name": end} for start, end in _DISPLAY_CONNECTIONS],
    separators=(",", ":"),
)


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE skeleton_definition "
            "SET display_connections = CAST(:connections AS jsonb) "
            "WHERE skeleton_id = :skeleton_id AND display_connections = '[]'::jsonb"
        ).bindparams(
            connections=_DISPLAY_CONNECTIONS_JSON,
            skeleton_id=_SKILLCORNER_SKELETON_ID,
        )
    )


def downgrade() -> None:
    # The seed is additive and may have been superseded by a persisted typed
    # declaration; leave it intact when rolling back the schema column later.
    pass
