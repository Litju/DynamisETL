"""Additive V4 sports semantics, source catalog and grain annotations.

Revision ID: 0009_multisport_semantic_catalog
Revises: 0008_skeleton_edges_seed
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_multisport_semantic_catalog"
down_revision: str | None = "0008_skeleton_edges_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRAIN_KINDS = (
    "'FRAME_SERIES', 'JOINT_FRAME_SERIES', 'EVENT_SERIES', 'PLAY_BY_PLAY', "
    "'GAME_SUMMARY', 'PLAYER_GAME', 'TEAM_GAME', 'PLAYER_SEASON', 'TEAM_SEASON', "
    "'TRIAL_SERIES', 'SENSOR_SERIES'"
)


def upgrade() -> None:
    op.add_column("dataset_version_file", sa.Column("upstream_provider", sa.String(128)))
    op.add_column("dataset_version_file", sa.Column("upstream_revision", sa.String(256)))
    for table in ("sample_artifact", "processing_artifact"):
        op.add_column(table, sa.Column("data_grain_kind", sa.String(32)))
        op.add_column(
            table,
            sa.Column("data_grain_axes", postgresql.JSONB(astext_type=sa.Text())),
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_grain_kind"),
            table,
            f"data_grain_kind IS NULL OR data_grain_kind IN ({GRAIN_KINDS})",
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_grain_axes_pair"),
            table,
            "(data_grain_kind IS NULL AND data_grain_axes IS NULL) OR "
            "(data_grain_kind IS NOT NULL AND data_grain_axes IS NOT NULL AND "
            "jsonb_typeof(data_grain_axes) = 'array' AND jsonb_array_length(data_grain_axes) > 0)",
        )
    op.add_column("sensor_stream", sa.Column("data_grain_kind", sa.String(32)))
    op.add_column(
        "sensor_stream",
        sa.Column("data_grain_axes", postgresql.JSONB(astext_type=sa.Text())),
    )
    op.create_check_constraint(
        op.f("ck_sensor_stream_grain_kind"),
        "sensor_stream",
        f"data_grain_kind IS NULL OR data_grain_kind IN ({GRAIN_KINDS})",
    )
    op.create_check_constraint(
        op.f("ck_sensor_stream_grain_axes_pair"),
        "sensor_stream",
        "(data_grain_kind IS NULL AND data_grain_axes IS NULL) OR "
        "(data_grain_kind IS NOT NULL AND data_grain_axes IS NOT NULL AND "
        "jsonb_typeof(data_grain_axes) = 'array' AND jsonb_array_length(data_grain_axes) > 0)",
    )

    op.create_table(
        "sport",
        sa.Column("sport_id", sa.String(64), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.CheckConstraint("code ~ '^[a-z][a-z0-9_]*$'", name=op.f("ck_sport_code")),
        sa.PrimaryKeyConstraint("sport_id", name=op.f("pk_sport")),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "competition",
        sa.Column("competition_id", sa.String(128), nullable=False),
        sa.Column("sport_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.ForeignKeyConstraint(
            ["sport_id"], ["sport.sport_id"], name=op.f("fk_competition_sport_id_sport")
        ),
        sa.PrimaryKeyConstraint("competition_id", name=op.f("pk_competition")),
    )
    op.create_table(
        "competition_edition",
        sa.Column("edition_id", sa.String(128), nullable=False),
        sa.Column("competition_id", sa.String(128), nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("starts_on", sa.Date()),
        sa.Column("ends_on", sa.Date()),
        sa.CheckConstraint(
            "kind IN ('league_season', 'tournament', 'other')",
            name=op.f("ck_competition_edition_kind"),
        ),
        sa.CheckConstraint(
            "starts_on IS NULL OR ends_on IS NULL OR ends_on >= starts_on",
            name=op.f("ck_competition_edition_date_order"),
        ),
        sa.ForeignKeyConstraint(
            ["competition_id"],
            ["competition.competition_id"],
            name=op.f("fk_competition_edition_competition_id_competition"),
        ),
        sa.PrimaryKeyConstraint("edition_id", name=op.f("pk_competition_edition")),
        sa.UniqueConstraint("competition_id", "label", name="uq_competition_edition_label"),
    )
    op.create_table(
        "team",
        sa.Column("team_id", sa.String(128), nullable=False),
        sa.Column("sport_id", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.ForeignKeyConstraint(
            ["sport_id"], ["sport.sport_id"], name=op.f("fk_team_sport_id_sport")
        ),
        sa.PrimaryKeyConstraint("team_id", name=op.f("pk_team")),
    )
    op.create_table(
        "contest",
        sa.Column("contest_id", sa.String(128), nullable=False),
        sa.Column("sport_id", sa.String(64), nullable=False),
        sa.Column("competition_edition_id", sa.String(128)),
        sa.Column("scheduled_start_at", sa.DateTime(timezone=True)),
        sa.Column("actual_start_at", sa.DateTime(timezone=True)),
        sa.Column("venue", sa.String(256)),
        sa.Column(
            "home_away_supported", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("source_authority", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["competition_edition_id"],
            ["competition_edition.edition_id"],
            name=op.f("fk_contest_competition_edition_id_competition_edition"),
        ),
        sa.ForeignKeyConstraint(
            ["sport_id"], ["sport.sport_id"], name=op.f("fk_contest_sport_id_sport")
        ),
        sa.PrimaryKeyConstraint("contest_id", name=op.f("pk_contest")),
    )
    op.create_table(
        "contest_team",
        sa.Column("contest_id", sa.String(128), nullable=False),
        sa.Column("team_id", sa.String(128), nullable=False),
        sa.Column("side", sa.String(16), nullable=False),
        sa.Column("side_order", sa.Integer()),
        sa.Column("score", sa.Integer()),
        sa.CheckConstraint(
            "side IN ('home', 'away', 'neutral', 'unknown')", name=op.f("ck_contest_team_side")
        ),
        sa.CheckConstraint(
            "side_order IS NULL OR side_order >= 0", name=op.f("ck_contest_team_nonnegative_order")
        ),
        sa.CheckConstraint(
            "score IS NULL OR score >= 0", name=op.f("ck_contest_team_nonnegative_score")
        ),
        sa.ForeignKeyConstraint(
            ["contest_id"], ["contest.contest_id"], name=op.f("fk_contest_team_contest_id_contest")
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["team.team_id"], name=op.f("fk_contest_team_team_id_team")
        ),
        sa.PrimaryKeyConstraint("contest_id", "team_id", name=op.f("pk_contest_team")),
    )
    op.create_table(
        "contest_period",
        sa.Column("contest_period_id", sa.String(128), nullable=False),
        sa.Column("contest_id", sa.String(128), nullable=False),
        sa.Column("source_period_number", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), server_default=sa.text("'other'"), nullable=False),
        sa.Column("label", sa.String(128)),
        sa.Column("provider_namespace", sa.String(128)),
        sa.Column("start_ns", sa.BigInteger()),
        sa.Column("end_ns", sa.BigInteger()),
        sa.CheckConstraint(
            "kind IN ('half', 'quarter', 'period', 'overtime', 'set', 'inning', 'other')",
            name=op.f("ck_contest_period_kind"),
        ),
        sa.CheckConstraint(
            "start_ns IS NULL OR end_ns IS NULL OR end_ns >= start_ns",
            name=op.f("ck_contest_period_time_order"),
        ),
        sa.ForeignKeyConstraint(
            ["contest_id"],
            ["contest.contest_id"],
            name=op.f("fk_contest_period_contest_id_contest"),
        ),
        sa.PrimaryKeyConstraint("contest_period_id", name=op.f("pk_contest_period")),
        sa.UniqueConstraint(
            "contest_id",
            "provider_namespace",
            "source_period_number",
            name="uq_contest_period_source_number",
        ),
    )
    op.create_table(
        "provider_identity_crosswalk",
        sa.Column("crosswalk_id", sa.String(128), nullable=False),
        sa.Column("provider_namespace", sa.String(128), nullable=False),
        sa.Column("entity_kind", sa.String(24), nullable=False),
        sa.Column("provider_entity_id", sa.String(256), nullable=False),
        sa.Column("canonical_entity_id", sa.String(256), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("source_authority", sa.Text(), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "entity_kind IN ('competition', 'edition', 'team', 'contest', 'subject')",
            name=op.f("ck_provider_identity_crosswalk_entity_kind"),
        ),
        sa.CheckConstraint(
            "valid_from IS NULL OR valid_to IS NULL OR valid_to >= valid_from",
            name=op.f("ck_provider_identity_crosswalk_validity_order"),
        ),
        sa.PrimaryKeyConstraint("crosswalk_id", name=op.f("pk_provider_identity_crosswalk")),
        sa.UniqueConstraint(
            "provider_namespace",
            "entity_kind",
            "provider_entity_id",
            "valid_from",
            name="uq_provider_crosswalk_alias_interval",
        ),
    )
    op.create_table(
        "source_catalog_entry",
        sa.Column("entry_id", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("dataset", sa.String(128), nullable=False),
        sa.Column("registry_dataset_id", sa.String(64)),
        sa.Column("registry_version", sa.String(128)),
        sa.Column("registry_file_key", sa.String(512)),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("object_kind", sa.String(24), nullable=False),
        sa.Column("sport_id", sa.String(64)),
        sa.Column("competition_id", sa.String(128)),
        sa.Column("competition_edition_id", sa.String(128)),
        sa.Column(
            "teams",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("upstream_url", sa.Text(), nullable=False),
        sa.Column("upstream_revision", sa.String(256)),
        sa.Column("asset_identity", sa.Text()),
        sa.Column("expected_size_bytes", sa.BigInteger()),
        sa.Column("rights", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "upstream_capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("availability_state", sa.String(32), nullable=False),
        sa.Column("failure_stage", sa.String(24)),
        sa.Column("failure_evidence", postgresql.JSONB(astext_type=sa.Text())),
        sa.CheckConstraint(
            "object_kind IN ('contest', 'season_dataset', 'release_asset', 'aggregate')",
            name=op.f("ck_source_catalog_entry_object_kind"),
        ),
        sa.CheckConstraint(
            "expected_size_bytes IS NULL OR expected_size_bytes > 0",
            name=op.f("ck_source_catalog_entry_positive_expected_size"),
        ),
        sa.CheckConstraint(
            "(registry_dataset_id IS NULL AND registry_version IS NULL AND registry_file_key IS NULL) OR (registry_dataset_id IS NOT NULL AND registry_version IS NOT NULL AND registry_file_key IS NOT NULL)",
            name=op.f("ck_source_catalog_entry_registry_file_reference_pair"),
        ),
        sa.CheckConstraint(
            "availability_state IN ('UPSTREAM_AVAILABLE', 'REGISTERED', 'ACQUIRED', 'MATERIALIZED', 'READY', 'ACQUISITION_FAILED', 'MATERIALIZATION_FAILED', 'VALIDATION_FAILED')",
            name=op.f("ck_source_catalog_entry_availability_state"),
        ),
        sa.CheckConstraint(
            "(availability_state LIKE '%_FAILED' AND failure_stage IS NOT NULL AND failure_evidence IS NOT NULL AND failure_evidence <> '{}'::jsonb) OR (availability_state NOT LIKE '%_FAILED' AND failure_stage IS NULL AND failure_evidence IS NULL)",
            name=op.f("ck_source_catalog_entry_failure_state_evidence"),
        ),
        sa.ForeignKeyConstraint(
            ["competition_edition_id"],
            ["competition_edition.edition_id"],
            name=op.f("fk_source_catalog_entry_competition_edition_id_competition_edition"),
        ),
        sa.ForeignKeyConstraint(
            ["competition_id"],
            ["competition.competition_id"],
            name=op.f("fk_source_catalog_entry_competition_id_competition"),
        ),
        sa.ForeignKeyConstraint(
            ["registry_dataset_id", "registry_version", "registry_file_key"],
            [
                "dataset_version_file.dataset_id",
                "dataset_version_file.version",
                "dataset_version_file.key",
            ],
            name=op.f("fk_source_catalog_entry_registry_dataset_id_dataset_version_file"),
        ),
        sa.ForeignKeyConstraint(
            ["sport_id"], ["sport.sport_id"], name=op.f("fk_source_catalog_entry_sport_id_sport")
        ),
        sa.PrimaryKeyConstraint("entry_id", name=op.f("pk_source_catalog_entry")),
        sa.UniqueConstraint(
            "provider", "dataset", "external_id", name="uq_source_catalog_external_identity"
        ),
    )
    op.create_index(
        "ix_source_catalog_sport_state", "source_catalog_entry", ["sport_id", "availability_state"]
    )
    op.create_table(
        "team_roster_membership",
        sa.Column("membership_id", sa.String(128), nullable=False),
        sa.Column("dataset_id", sa.String(64), nullable=False),
        sa.Column("subject_id", sa.String(128), nullable=False),
        sa.Column("team_id", sa.String(128), nullable=False),
        sa.Column("competition_edition_id", sa.String(128), nullable=False),
        sa.Column("valid_from", sa.Date()),
        sa.Column("valid_to", sa.Date()),
        sa.CheckConstraint(
            "valid_from IS NULL OR valid_to IS NULL OR valid_to >= valid_from",
            name=op.f("ck_team_roster_membership_date_order"),
        ),
        sa.ForeignKeyConstraint(
            ["competition_edition_id"],
            ["competition_edition.edition_id"],
            name=op.f("fk_team_roster_membership_competition_edition_id_competition_edition"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "subject_id"],
            ["subject.dataset_id", "subject.subject_id"],
            name=op.f("fk_team_roster_membership_dataset_id_subject"),
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["team.team_id"], name=op.f("fk_team_roster_membership_team_id_team")
        ),
        sa.PrimaryKeyConstraint("membership_id", name=op.f("pk_team_roster_membership")),
        sa.UniqueConstraint(
            "dataset_id",
            "subject_id",
            "team_id",
            "competition_edition_id",
            "valid_from",
            name="uq_team_roster_membership_scope",
        ),
    )
    op.create_table(
        "session_sport_context",
        sa.Column("dataset_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("contest_id", sa.String(128), nullable=False),
        sa.Column("source_catalog_entry_id", sa.String(128)),
        sa.ForeignKeyConstraint(
            ["contest_id"],
            ["contest.contest_id"],
            name=op.f("fk_session_sport_context_contest_id_contest"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "session_id"],
            ["session.dataset_id", "session.session_id"],
            name=op.f("fk_session_sport_context_dataset_id_session"),
        ),
        sa.ForeignKeyConstraint(
            ["source_catalog_entry_id"],
            ["source_catalog_entry.entry_id"],
            name=op.f("fk_session_sport_context_source_catalog_entry_id_source_catalog_entry"),
        ),
        sa.PrimaryKeyConstraint("dataset_id", "session_id", name=op.f("pk_session_sport_context")),
    )
    op.create_table(
        "spatial_reference",
        sa.Column("spatial_reference_id", sa.String(128), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("units", sa.String(32), nullable=False),
        sa.Column("origin", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("axis_orientation", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("handedness", sa.String(16), nullable=False),
        sa.Column(
            "canonical_display_transform", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("source_transform", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "period_direction_semantics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "handedness IN ('right', 'left', 'unspecified')",
            name=op.f("ck_spatial_reference_handedness"),
        ),
        sa.PrimaryKeyConstraint(
            "spatial_reference_id", "version", name=op.f("pk_spatial_reference")
        ),
    )
    op.create_table(
        "surface_geometry",
        sa.Column("surface_id", sa.String(128), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("sport_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("dimensions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("spatial_reference_id", sa.String(128), nullable=False),
        sa.Column("spatial_reference_version", sa.String(32), nullable=False),
        sa.Column("source_authority", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["spatial_reference_id", "spatial_reference_version"],
            ["spatial_reference.spatial_reference_id", "spatial_reference.version"],
            name=op.f("fk_surface_geometry_spatial_reference_id_spatial_reference"),
        ),
        sa.ForeignKeyConstraint(
            ["sport_id"], ["sport.sport_id"], name=op.f("fk_surface_geometry_sport_id_sport")
        ),
        sa.PrimaryKeyConstraint("surface_id", "version", name=op.f("pk_surface_geometry")),
    )
    op.create_table(
        "clock_mapping",
        sa.Column("mapping_id", sa.String(128), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("clock_kind", sa.String(24), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("source_unit", sa.String(24), nullable=False),
        sa.Column("scale_to_ns", sa.Float(), nullable=False),
        sa.Column("source_origin", sa.Float()),
        sa.Column("period_origin_ns", sa.BigInteger(), nullable=False),
        sa.Column("offset_ns", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("authority", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "clock_kind IN ('media_time', 'wall_time', 'game_clock', 'shot_clock', 'possession_clock')",
            name=op.f("ck_clock_mapping_clock_kind"),
        ),
        sa.CheckConstraint(
            "direction IN ('monotonic', 'count_up', 'count_down')",
            name=op.f("ck_clock_mapping_direction"),
        ),
        sa.CheckConstraint(
            "scale_to_ns > 0 AND scale_to_ns <> 'NaN'::double precision AND scale_to_ns <> 'Infinity'::double precision",
            name=op.f("ck_clock_mapping_positive_finite_scale"),
        ),
        sa.CheckConstraint(
            "direction <> 'count_down' OR source_origin IS NOT NULL",
            name=op.f("ck_clock_mapping_countdown_origin"),
        ),
        sa.CheckConstraint(
            "evidence <> '{}'::jsonb", name=op.f("ck_clock_mapping_evidence_required")
        ),
        sa.PrimaryKeyConstraint("mapping_id", "version", name=op.f("pk_clock_mapping")),
    )

    op.execute(
        "INSERT INTO sport (sport_id, code, display_name) "
        "SELECT DISTINCT domain, domain, CASE domain WHEN 'football' THEN 'Football' "
        "WHEN 'basketball' THEN 'Basketball' WHEN 'ice_hockey' THEN 'Ice hockey' "
        "WHEN 'baseball' THEN 'Baseball' END FROM dataset_source "
        "WHERE domain IN ('football', 'basketball', 'ice_hockey', 'baseball') "
        "ON CONFLICT (sport_id) DO NOTHING"
    )
    op.execute(
        "INSERT INTO source_catalog_entry (entry_id, provider, dataset, registry_dataset_id, "
        "registry_version, registry_file_key, external_id, object_kind, sport_id, teams, "
        "upstream_url, upstream_revision, asset_identity, expected_size_bytes, rights, "
        "upstream_capabilities, discovered_at, availability_state, failure_stage, failure_evidence) "
        "SELECT 'src-' || md5('registry:' || ds.dataset_id || ':' || dvf.version || ':' || dvf.key), "
        "coalesce(dvf.upstream_provider, ds.provider), ds.dataset_id, ds.dataset_id, dvf.version, "
        "dvf.key, ds.dataset_id || '/' || dvf.version || '/' || dvf.key, 'release_asset', "
        "CASE WHEN ds.domain IN ('football', 'basketball', 'ice_hockey', 'baseball') THEN ds.domain END, "
        "'[]'::jsonb, dv.upstream_url, coalesce(dvf.upstream_revision, dvf.version), dvf.key, "
        "dvf.size_bytes, jsonb_build_object('identifier', lp.identifier, 'status', lp.status, "
        "'attribution_required', lp.attribution_required, 'noncommercial_only', lp.noncommercial_only, "
        "'share_alike', lp.share_alike, 'redistribution', lp.redistribution, 'local_only', lp.local_only, "
        "'restrictions', lp.restrictions), "
        "coalesce((SELECT jsonb_agg(DISTINCT CASE m.modality WHEN 'tracking' THEN 'TRACKING' "
        "WHEN 'pose' THEN 'POSE' WHEN 'event' THEN 'EVENTS' WHEN 'force' THEN 'FORCE' "
        "WHEN 'imu' THEN 'IMU' WHEN 'lpt' THEN 'LPT' WHEN 'gnss' THEN 'GNSS' END) "
        "FROM dataset_source_modality m WHERE m.dataset_id = ds.dataset_id), '[]'::jsonb), "
        "coalesce(dvf.retrieved_at, dv.retrieved_at, now()), "
        "CASE WHEN dv.retrieval_status = 'failed' THEN 'ACQUISITION_FAILED' "
        "WHEN dvf.local_sha256 IS NOT NULL THEN 'ACQUIRED' ELSE 'REGISTERED' END, "
        "CASE WHEN dv.retrieval_status = 'failed' THEN 'acquisition' END, "
        "CASE WHEN dv.retrieval_status = 'failed' THEN jsonb_build_object('retrieval_status', 'failed') END "
        "FROM dataset_version_file dvf JOIN dataset_version dv USING (dataset_id, version) "
        "JOIN dataset_source ds USING (dataset_id) JOIN license_policy lp ON lp.policy_id = ds.license_policy_id "
        "ON CONFLICT (entry_id) DO NOTHING"
    )
    _backfill_existing_match_contexts()
    _backfill_existing_data_grains()


def _backfill_existing_match_contexts() -> None:
    """Backfill only contest facts already present in accepted match metadata."""
    op.execute(
        "INSERT INTO contest (contest_id, sport_id, actual_start_at, venue, "
        "home_away_supported, source_authority) "
        "SELECT 'contest-' || substr(md5(ds.adapter_id || ':contest:' || s.session_id), 1, 24), "
        "ds.domain, s.started_at, s.venue, false, 'persisted Session.kind=match backfill' "
        "FROM session s JOIN dataset_source ds USING (dataset_id) "
        "WHERE s.kind = 'match' AND ds.adapter_id IN ('sportec_idsse', 'skillcorner_opendata') "
        "ON CONFLICT (contest_id) DO NOTHING"
    )


def _backfill_existing_data_grains() -> None:
    """Classify accepted streams from declared modality and their real scope."""
    op.execute(
        "UPDATE sensor_stream SET data_grain_kind = 'FRAME_SERIES', "
        'data_grain_axes = \'["contest","period","canonical_time","entity"]\'::jsonb '
        "WHERE modality = 'tracking' AND dataset_id IN ('dfl-sportec-idsse', 'skillcorner-opendata')"
    )
    op.execute(
        "UPDATE sensor_stream SET data_grain_kind = 'JOINT_FRAME_SERIES', "
        'data_grain_axes = \'["contest","period","canonical_time","subject","joint"]\'::jsonb '
        "WHERE modality = 'pose' AND dataset_id = 'skillcorner-opendata'"
    )
    op.execute(
        "UPDATE sensor_stream SET data_grain_kind = 'TRIAL_SERIES', "
        'data_grain_axes = \'["subject","trial","sample_index","joint"]\'::jsonb '
        "WHERE modality = 'pose' AND dataset_id = 'spl-open-data' AND trial_id IS NOT NULL"
    )
    op.execute(
        "UPDATE sensor_stream SET data_grain_kind = 'EVENT_SERIES', "
        'data_grain_axes = \'["contest","period","sequence_index"]\'::jsonb '
        "WHERE modality = 'event' AND dataset_id = 'dfl-sportec-idsse'"
    )
    op.execute(
        "UPDATE sensor_stream SET data_grain_kind = 'TRIAL_SERIES', "
        'data_grain_axes = \'["subject","trial","sample_index"]\'::jsonb '
        "WHERE modality IN ('force', 'imu', 'lpt') AND trial_id IS NOT NULL"
    )
    op.execute(
        "UPDATE sensor_stream SET data_grain_kind = 'SENSOR_SERIES', "
        'data_grain_axes = \'["subject","stream","canonical_time"]\'::jsonb '
        "WHERE modality = 'gnss' AND subject_id IS NOT NULL"
    )
    op.execute(
        "UPDATE sample_artifact a SET data_grain_kind = s.data_grain_kind, "
        "data_grain_axes = s.data_grain_axes FROM sensor_stream s "
        "WHERE a.dataset_id = s.dataset_id AND a.stream_id = s.stream_id "
        "AND a.data_grain_kind IS NULL AND s.data_grain_kind IS NOT NULL"
    )
    op.execute(
        "UPDATE processing_artifact a SET data_grain_kind = s.data_grain_kind, "
        "data_grain_axes = s.data_grain_axes FROM sensor_stream s "
        "WHERE a.dataset_id = s.dataset_id "
        "AND a.artifact_metadata ->> 'stream_id' = s.stream_id "
        "AND a.data_grain_kind IS NULL AND s.data_grain_kind IS NOT NULL"
    )
    op.execute(
        "INSERT INTO team (team_id, sport_id, display_name) "
        "SELECT DISTINCT 'team-' || substr(md5(ds.adapter_id || ':team:' || p.group_label), 1, 24), "
        "ds.domain, coalesce(max(nullif(sub.cohort, '')), p.group_label) "
        "FROM session_participant p JOIN session s USING (dataset_id, session_id) "
        "JOIN dataset_source ds USING (dataset_id) "
        "LEFT JOIN subject sub USING (dataset_id, subject_id) "
        "WHERE s.kind = 'match' AND ds.adapter_id IN ('sportec_idsse', 'skillcorner_opendata') "
        "AND p.group_label IS NOT NULL "
        "GROUP BY p.dataset_id, p.group_label, ds.domain, ds.adapter_id "
        "ON CONFLICT (team_id) DO NOTHING"
    )
    op.execute(
        "INSERT INTO contest_team (contest_id, team_id, side, side_order, score) "
        "SELECT DISTINCT 'contest-' || substr(md5(ds.adapter_id || ':contest:' || p.session_id), 1, 24), "
        "'team-' || substr(md5(ds.adapter_id || ':team:' || p.group_label), 1, 24), "
        "'unknown', NULL::integer, NULL::integer "
        "FROM session_participant p JOIN session s USING (dataset_id, session_id) "
        "JOIN dataset_source ds USING (dataset_id) "
        "WHERE s.kind = 'match' AND ds.adapter_id IN ('sportec_idsse', 'skillcorner_opendata') "
        "AND p.group_label IS NOT NULL ON CONFLICT DO NOTHING"
    )
    op.execute(
        "INSERT INTO contest_period (contest_period_id, contest_id, source_period_number, "
        "kind, label, provider_namespace) "
        "SELECT 'contest-' || substr(md5(ds.adapter_id || ':contest:' || s.session_id), 1, 24) "
        "|| ':period:' || CASE WHEN ds.adapter_id = 'skillcorner_opendata' "
        "AND t.label ~ '^period [0-9]+$' THEN regexp_replace(t.label, '^period ', '') "
        "ELSE t.trial_id END, "
        "'contest-' || substr(md5(ds.adapter_id || ':contest:' || s.session_id), 1, 24), "
        "CASE WHEN ds.adapter_id = 'skillcorner_opendata' AND t.label ~ '^period [0-9]+$' "
        "THEN regexp_replace(t.label, '^period ', '') ELSE t.trial_id END, "
        "'other', t.label, ds.adapter_id FROM trial t JOIN session s USING (dataset_id, session_id) "
        "JOIN dataset_source ds USING (dataset_id) "
        "WHERE s.kind = 'match' AND ds.adapter_id IN ('sportec_idsse', 'skillcorner_opendata') "
        "ON CONFLICT (contest_period_id) DO NOTHING"
    )
    op.execute(
        "INSERT INTO session_sport_context (dataset_id, session_id, contest_id) "
        "SELECT s.dataset_id, s.session_id, 'contest-' || substr(md5(ds.adapter_id || ':contest:' || s.session_id), 1, 24) "
        "FROM session s JOIN dataset_source ds USING (dataset_id) "
        "WHERE s.kind = 'match' AND ds.adapter_id IN ('sportec_idsse', 'skillcorner_opendata') "
        "ON CONFLICT (dataset_id, session_id) DO NOTHING"
    )
    op.execute(
        "INSERT INTO provider_identity_crosswalk (crosswalk_id, provider_namespace, entity_kind, "
        "provider_entity_id, canonical_entity_id, source_authority) "
        "SELECT 'xw-' || substr(md5(ds.adapter_id || ':contest:' || s.session_id), 1, 32), "
        "ds.adapter_id, 'contest', s.session_id, 'contest-' || substr(md5(ds.adapter_id || ':contest:' || s.session_id), 1, 24), "
        "'persisted Session.kind=match source identity backfill' FROM session s "
        "JOIN dataset_source ds USING (dataset_id) WHERE s.kind = 'match' "
        "AND ds.adapter_id IN ('sportec_idsse', 'skillcorner_opendata') ON CONFLICT DO NOTHING"
    )
    op.execute(
        "INSERT INTO provider_identity_crosswalk (crosswalk_id, provider_namespace, entity_kind, "
        "provider_entity_id, canonical_entity_id, source_authority) "
        "SELECT 'xw-' || substr(md5(ds.adapter_id || ':team:' || p.group_label), 1, 32), "
        "ds.adapter_id, 'team', p.group_label, 'team-' || substr(md5(ds.adapter_id || ':team:' || p.group_label), 1, 24), "
        "'persisted participant team alias backfill' FROM session_participant p "
        "JOIN session s USING (dataset_id, session_id) JOIN dataset_source ds USING (dataset_id) "
        "WHERE s.kind = 'match' AND ds.adapter_id IN ('sportec_idsse', 'skillcorner_opendata') "
        "AND p.group_label IS NOT NULL ON CONFLICT DO NOTHING"
    )
    op.execute(
        "INSERT INTO provider_identity_crosswalk (crosswalk_id, provider_namespace, entity_kind, "
        "provider_entity_id, canonical_entity_id, source_authority) "
        "SELECT 'xw-' || substr(md5(ds.adapter_id || ':subject:' || p.subject_id), 1, 32), "
        "ds.adapter_id, 'subject', p.subject_id, p.dataset_id || '/' || p.subject_id, "
        "'existing dataset-scoped Subject identity backfill' FROM session_participant p "
        "JOIN session s USING (dataset_id, session_id) JOIN dataset_source ds USING (dataset_id) "
        "WHERE s.kind = 'match' AND ds.adapter_id IN ('sportec_idsse', 'skillcorner_opendata') "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table("clock_mapping")
    op.drop_table("surface_geometry")
    op.drop_table("spatial_reference")
    op.drop_table("session_sport_context")
    op.drop_table("team_roster_membership")
    op.drop_index("ix_source_catalog_sport_state", table_name="source_catalog_entry")
    op.drop_table("source_catalog_entry")
    op.drop_table("provider_identity_crosswalk")
    op.drop_table("contest_period")
    op.drop_table("contest_team")
    op.drop_table("contest")
    op.drop_table("team")
    op.drop_table("competition_edition")
    op.drop_table("competition")
    op.drop_table("sport")
    op.drop_constraint(op.f("ck_sensor_stream_grain_axes_pair"), "sensor_stream", type_="check")
    op.drop_constraint(op.f("ck_sensor_stream_grain_kind"), "sensor_stream", type_="check")
    op.drop_column("sensor_stream", "data_grain_axes")
    op.drop_column("sensor_stream", "data_grain_kind")
    for table in ("processing_artifact", "sample_artifact"):
        op.drop_constraint(op.f(f"ck_{table}_grain_axes_pair"), table, type_="check")
        op.drop_constraint(op.f(f"ck_{table}_grain_kind"), table, type_="check")
        op.drop_column(table, "data_grain_axes")
        op.drop_column(table, "data_grain_kind")
    op.drop_column("dataset_version_file", "upstream_revision")
    op.drop_column("dataset_version_file", "upstream_provider")
