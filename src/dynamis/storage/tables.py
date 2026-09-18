"""SQLAlchemy 2 metadata schema for the control/provenance plane.

Design corrections relative to the pre-RES-96 draft:

* ``session`` no longer carries ``subject_id``: a football match is one session
  with many participants (:class:`SessionParticipant`), so a match identity is
  never duplicated per player;
* ``CoordinateFrame``, ``FrameTransform``, ``SynchronizationSpec``,
  ``SkeletonDefinition`` and ``SampleArtifact`` are first-class tables instead
  of loose string columns;
* ``AlgorithmSpec`` and ``MetricDefinition`` are **global** scientific
  definitions, not artifacts artificially owned by one dataset;
* dense samples never enter PostgreSQL: there is no per-sample ``frame`` table.
  Canonical signals live in Parquet and only their artifact metadata is stored
  here;
* provenance is bound by checksum through ``input_checksums`` with a
  ``NOT-empty`` CHECK, so a derived value cannot exist without its inputs.

Invariants that require a subquery (for example "a collective session must have
at least two participants", or "a frame with a parent must have a transform")
are enforced by the frozen Pydantic contracts in
:mod:`dynamis.contracts.invariants`, which are exercised by the test-suite.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from dynamis.storage.metadata import metadata

MEASUREMENT_CLASS_SQL = (
    "measurement_class IN ('RAW_MEASURED', 'SOURCE_DERIVED', 'PIPELINE_DERIVED', 'MODEL_ESTIMATED')"
)
LAYER_SQL = "layer IN ('bronze', 'silver', 'gold', 'quarantine', 'cache', 'tmp')"
FORMAT_SQL = "format IN ('parquet', 'arrow_ipc', 'json', 'csv', 'text', 'native')"


class Base(DeclarativeBase):
    metadata = metadata


def _ck(table: str, name: str, condition: str) -> CheckConstraint:
    """Named check constraint.

    ``table`` documents the owning table; the ``ck_<table>_`` DDL prefix is
    supplied by the metadata naming convention, so the explicit name passed here
    is only the descriptive suffix.
    """
    del table
    return CheckConstraint(condition, name=name)


JSON_EMPTY_OBJECT = text("'{}'::jsonb")
JSON_EMPTY_ARRAY = text("'[]'::jsonb")


class LicensePolicy(Base):
    __tablename__ = "license_policy"

    policy_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    identifier: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attribution_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    noncommercial_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    share_alike: Mapped[bool] = mapped_column(Boolean, nullable=False)
    redistribution: Mapped[str] = mapped_column(String(16), nullable=False)
    local_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    restrictions: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_ARRAY
    )

    __table_args__ = (
        _ck("license_policy", "status", "status IN ('declared', 'unclear')"),
        _ck("license_policy", "redistribution", "redistribution IN ('conditional', 'prohibited')"),
        _ck(
            "license_policy",
            "declared_needs_identifier",
            "status = 'unclear' OR identifier IS NOT NULL",
        ),
        _ck(
            "license_policy",
            "unclear_is_local_only",
            "status = 'declared' OR (identifier IS NULL AND local_only)",
        ),
        _ck(
            "license_policy",
            "local_only_prohibits_redistribution",
            "NOT local_only OR redistribution = 'prohibited'",
        ),
        _ck(
            "license_policy",
            "nc_needs_noncommercial",
            "identifier IS NULL OR identifier NOT LIKE '%NC%' OR noncommercial_only",
        ),
        _ck(
            "license_policy",
            "sa_needs_share_alike",
            "identifier IS NULL OR identifier NOT LIKE '%SA%' OR share_alike",
        ),
    )


class DatasetSource(Base):
    __tablename__ = "dataset_source"

    dataset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    upstream_urls: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    doi: Mapped[str | None] = mapped_column(String(160))
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    adapter_id: Mapped[str] = mapped_column(String(128), nullable=False)
    v1_role: Mapped[str] = mapped_column(Text, nullable=False)
    initial_scope: Mapped[str] = mapped_column(Text, nullable=False)
    license_policy_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("license_policy.policy_id"), nullable=False
    )

    __table_args__ = (
        _ck("dataset_source", "has_upstream_url", "jsonb_array_length(upstream_urls) > 0"),
    )


class DatasetSourceModality(Base):
    """Normalized modality list; a source declares at least one modality."""

    __tablename__ = "dataset_source_modality"

    dataset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("dataset_source.dataset_id"), primary_key=True
    )
    modality: Mapped[str] = mapped_column(String(16), primary_key=True)

    __table_args__ = (
        _ck(
            "dataset_source_modality",
            "modality",
            "modality IN ('gnss', 'imu', 'force', 'lpt', 'tracking', 'event', 'pose')",
        ),
    )


class DatasetVersion(Base):
    __tablename__ = "dataset_version"

    dataset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("dataset_source.dataset_id"), primary_key=True
    )
    version: Mapped[str] = mapped_column(String(128), primary_key=True)
    release_date: Mapped[date | None] = mapped_column(Date)
    upstream_url: Mapped[str] = mapped_column(Text, nullable=False)
    citation: Mapped[str | None] = mapped_column(Text)
    optional: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    retrieval_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'not_fetched'")
    )
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        _ck(
            "dataset_version",
            "retrieval_status",
            "retrieval_status IN ('not_fetched', 'fetched', 'failed')",
        ),
        _ck(
            "dataset_version",
            "fetched_needs_retrieved_at",
            "retrieval_status <> 'fetched' OR retrieved_at IS NOT NULL",
        ),
    )


class DatasetVersionFile(Base):
    __tablename__ = "dataset_version_file"

    dataset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[str] = mapped_column(String(128), primary_key=True)
    key: Mapped[str] = mapped_column(String(512), primary_key=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    upstream_md5: Mapped[str | None] = mapped_column(String(32))
    upstream_sha256: Mapped[str | None] = mapped_column(String(64))
    local_sha256: Mapped[str | None] = mapped_column(String(64))
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "version"],
            ["dataset_version.dataset_id", "dataset_version.version"],
        ),
        _ck("dataset_version_file", "positive_size", "size_bytes IS NULL OR size_bytes > 0"),
        _ck(
            "dataset_version_file",
            "local_checksum_needs_retrieval",
            "local_sha256 IS NULL OR retrieved_at IS NOT NULL",
        ),
    )


class Subject(Base):
    """Dataset-scoped participant identity; never merged across datasets."""

    __tablename__ = "subject"

    dataset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("dataset_source.dataset_id"), primary_key=True
    )
    subject_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    sex: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'unspecified'")
    )
    cohort: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (_ck("subject", "sex", "sex IN ('male', 'female', 'unspecified')"),)


class Protocol(Base):
    __tablename__ = "protocol"

    protocol_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    spec: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_OBJECT
    )
    citation: Mapped[str | None] = mapped_column(Text)


class Session(Base):
    """Individual or collective session. Participants live in a join table."""

    __tablename__ = "session"

    dataset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("dataset_source.dataset_id"), primary_key=True
    )
    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'unknown'"))
    protocol_id: Mapped[str | None] = mapped_column(String(128), ForeignKey("protocol.protocol_id"))
    label: Mapped[str | None] = mapped_column(String(256))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    venue: Mapped[str | None] = mapped_column(String(256))

    __table_args__ = (
        _ck(
            "session",
            "kind",
            "kind IN ('individual', 'team', 'match', 'laboratory', 'longitudinal', 'unknown')",
        ),
        _ck(
            "session",
            "time_order",
            "ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at",
        ),
    )


class SessionParticipant(Base):
    """Many-to-many session participation for multi-subject matches and teams."""

    __tablename__ = "session_participant"

    dataset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'participant'")
    )
    group_label: Mapped[str | None] = mapped_column(String(128))

    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "session_id"],
            ["session.dataset_id", "session.session_id"],
        ),
        ForeignKeyConstraint(
            ["dataset_id", "subject_id"],
            ["subject.dataset_id", "subject.subject_id"],
        ),
        _ck(
            "session_participant",
            "role",
            "role IN ('athlete', 'player', 'goalkeeper', 'patient', 'participant', "
            "'operator', 'unknown')",
        ),
    )


class Device(Base):
    __tablename__ = "device"

    dataset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("dataset_source.dataset_id"), primary_key=True
    )
    device_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    device_type: Mapped[str | None] = mapped_column(String(64))
    vendor: Mapped[str | None] = mapped_column(String(128))
    model: Mapped[str | None] = mapped_column(String(128))
    specs: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_OBJECT
    )


class Clock(Base):
    """Global timebase definition (utc, gnss_utc, device_monotonic, ...)."""

    __tablename__ = "clock"

    clock_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    timebase: Mapped[str] = mapped_column(String(32), nullable=False)
    frequency_hz: Mapped[float | None] = mapped_column(Float)
    epoch_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    drift_ppm: Mapped[float | None] = mapped_column(Float)
    rollover_period_s: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        _ck(
            "clock",
            "timebase",
            "timebase IN ('utc', 'gnss_utc', 'device_monotonic', 'session_monotonic', "
            "'gps_week_time', 'unknown')",
        ),
        _ck("clock", "positive_frequency", "frequency_hz IS NULL OR frequency_hz > 0"),
        _ck(
            "clock",
            "monotonic_has_no_epoch",
            "timebase NOT IN ('device_monotonic', 'session_monotonic') OR epoch_utc IS NULL",
        ),
    )


class CoordinateFrame(Base):
    """Declared geometric reference; no axis convention is ever implicit."""

    __tablename__ = "coordinate_frame"

    frame_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    handedness: Mapped[str] = mapped_column(String(16), nullable=False)
    x_direction: Mapped[str] = mapped_column(String(32), nullable=False)
    y_direction: Mapped[str] = mapped_column(String(32), nullable=False)
    z_direction: Mapped[str] = mapped_column(String(32), nullable=False)
    origin_description: Mapped[str] = mapped_column(Text, nullable=False)
    length_unit: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'m'"))
    parent_frame_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("coordinate_frame.frame_id")
    )
    description: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        _ck(
            "coordinate_frame",
            "kind",
            "kind IN ('world_geodetic', 'local_enu', 'pitch', 'body', 'sensor', 'camera', "
            "'laboratory', 'joint_local', 'unknown')",
        ),
        _ck(
            "coordinate_frame",
            "handedness",
            "handedness IN ('right', 'left', 'unspecified')",
        ),
        # Mirror the contract's semantic rule: two axes may share a direction only
        # when that direction is explicitly undirected (unspecified/origin-dependent).
        _ck(
            "coordinate_frame",
            "distinct_axes",
            "("
            "x_direction <> y_direction OR x_direction IN ('unspecified','origin_dependent') "
            "OR y_direction IN ('unspecified','origin_dependent')"
            ") AND ("
            "x_direction <> z_direction OR x_direction IN ('unspecified','origin_dependent') "
            "OR z_direction IN ('unspecified','origin_dependent')"
            ") AND ("
            "y_direction <> z_direction OR y_direction IN ('unspecified','origin_dependent') "
            "OR z_direction IN ('unspecified','origin_dependent')"
            ")",
        ),
        _ck(
            "coordinate_frame",
            "no_self_parent",
            "parent_frame_id IS NULL OR parent_frame_id <> frame_id",
        ),
        _ck(
            "coordinate_frame",
            "unknown_needs_description",
            "kind <> 'unknown' OR description IS NOT NULL",
        ),
        _ck(
            "coordinate_frame",
            "unspecified_handedness_needs_description",
            "handedness <> 'unspecified' OR (description IS NOT NULL AND btrim(description) <> '')",
        ),
    )


class AlgorithmSpec(Base):
    """Global deterministic algorithm revision; never dataset-owned."""

    __tablename__ = "algorithm_spec"

    algorithm_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    code_git_sha: Mapped[str | None] = mapped_column(String(40))
    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_OBJECT
    )
    parameters_hash: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    citation: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_algorithm_spec_name_version"),
        _ck(
            "algorithm_spec",
            "kind",
            "kind IN ('adapter', 'canonicalizer', 'qc_rule', 'processor', 'metric', 'exporter')",
        ),
        _ck(
            "algorithm_spec",
            "parameters_need_hash",
            "parameters = '{}'::jsonb OR parameters_hash IS NOT NULL",
        ),
    )


class FrameTransform(Base):
    """Explicit parent-child frame transform with an algorithm or justification."""

    __tablename__ = "frame_transform"

    transform_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_frame_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("coordinate_frame.frame_id"), nullable=False
    )
    target_frame_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("coordinate_frame.frame_id"), nullable=False
    )
    translation_x_m: Mapped[float] = mapped_column(Float, nullable=False)
    translation_y_m: Mapped[float] = mapped_column(Float, nullable=False)
    translation_z_m: Mapped[float] = mapped_column(Float, nullable=False)
    rotation_x: Mapped[float] = mapped_column(Float, nullable=False)
    rotation_y: Mapped[float] = mapped_column(Float, nullable=False)
    rotation_z: Mapped[float] = mapped_column(Float, nullable=False)
    rotation_w: Mapped[float] = mapped_column(Float, nullable=False)
    algorithm_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("algorithm_spec.algorithm_id")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "source_frame_id", "target_frame_id", name="uq_frame_transform_source_target"
        ),
        _ck("frame_transform", "not_self_referential", "source_frame_id <> target_frame_id"),
        _ck(
            "frame_transform",
            "explained_transform",
            "algorithm_id IS NOT NULL OR notes IS NOT NULL",
        ),
    )


class SynchronizationSpec(Base):
    """Explicit synchronization method with quantified residual where claimed."""

    __tablename__ = "synchronization_spec"

    sync_spec_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_clock_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("clock.clock_id"), nullable=False
    )
    uncertainty_ms: Mapped[float | None] = mapped_column(Float)
    residual_max_abs_ms: Mapped[float | None] = mapped_column(Float)
    residual_rms_ms: Mapped[float | None] = mapped_column(Float)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_artifact_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("processing_artifact.artifact_id")
    )
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        _ck(
            "synchronization_spec",
            "method",
            "method IN ('source_provided', 'hardware_synchronized', 'event_aligned', "
            "'cross_correlation_aligned', 'software_timestamped', 'unknown')",
        ),
        _ck(
            "synchronization_spec",
            "nonnegative_uncertainty",
            "COALESCE(uncertainty_ms, 0) >= 0 AND COALESCE(residual_max_abs_ms, 0) >= 0 "
            "AND COALESCE(residual_rms_ms, 0) >= 0",
        ),
        _ck(
            "synchronization_spec",
            "rms_bounded_by_max",
            "residual_rms_ms IS NULL OR residual_max_abs_ms IS NULL "
            "OR residual_rms_ms <= residual_max_abs_ms",
        ),
        _ck(
            "synchronization_spec",
            "unknown_makes_no_claim",
            "method <> 'unknown' OR (NOT verified AND uncertainty_ms IS NULL "
            "AND residual_max_abs_ms IS NULL AND residual_rms_ms IS NULL)",
        ),
        _ck(
            "synchronization_spec",
            "verified_needs_evidence",
            "NOT verified OR (verified_at IS NOT NULL AND evidence_artifact_id IS NOT NULL)",
        ),
    )


class SkeletonDefinition(Base):
    """Joint topology authority; pose joint indices are meaningless without it."""

    __tablename__ = "skeleton_definition"

    skeleton_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    joint_count: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (_ck("skeleton_definition", "positive_joint_count", "joint_count > 0"),)


class SkeletonJoint(Base):
    __tablename__ = "skeleton_joint"

    skeleton_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("skeleton_definition.skeleton_id"), primary_key=True
    )
    joint_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    joint_name: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_joint_id: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        ForeignKeyConstraint(
            ["skeleton_id", "parent_joint_id"],
            ["skeleton_joint.skeleton_id", "skeleton_joint.joint_id"],
        ),
        UniqueConstraint("skeleton_id", "joint_name", name="uq_skeleton_joint_name"),
        _ck("skeleton_joint", "nonnegative_joint_id", "joint_id >= 0"),
        _ck(
            "skeleton_joint",
            "parent_precedes_child",
            "parent_joint_id IS NULL OR parent_joint_id < joint_id",
        ),
    )


class Trial(Base):
    """Trial, rep, period or half. ``subject_id`` stays optional."""

    __tablename__ = "trial"

    dataset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    trial_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    subject_id: Mapped[str | None] = mapped_column(String(128))
    parent_trial_id: Mapped[str | None] = mapped_column(String(128))
    label: Mapped[str | None] = mapped_column(String(256))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "session_id"],
            ["session.dataset_id", "session.session_id"],
        ),
        ForeignKeyConstraint(
            ["dataset_id", "subject_id"],
            ["subject.dataset_id", "subject.subject_id"],
        ),
        ForeignKeyConstraint(
            ["dataset_id", "session_id", "parent_trial_id"],
            ["trial.dataset_id", "trial.session_id", "trial.trial_id"],
        ),
        _ck("trial", "no_self_parent", "parent_trial_id IS NULL OR parent_trial_id <> trial_id"),
        _ck(
            "trial",
            "time_order",
            "ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at",
        ),
    )


class SensorStream(Base):
    """Declared stream of samples with clock, synchronization and frame authority."""

    __tablename__ = "sensor_stream"

    dataset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    stream_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trial_id: Mapped[str | None] = mapped_column(String(128))
    subject_id: Mapped[str | None] = mapped_column(String(128))
    device_id: Mapped[str | None] = mapped_column(String(128))
    modality: Mapped[str] = mapped_column(String(16), nullable=False)
    measurement_class: Mapped[str] = mapped_column(String(32), nullable=False)
    clock_id: Mapped[str] = mapped_column(String(128), ForeignKey("clock.clock_id"), nullable=False)
    synchronization_spec_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("synchronization_spec.sync_spec_id"), nullable=False
    )
    coordinate_frame_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("coordinate_frame.frame_id")
    )
    skeleton_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("skeleton_definition.skeleton_id")
    )
    nominal_sampling_rate_hz: Mapped[float | None] = mapped_column(Float)
    si_units: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_ARRAY
    )
    source_unit: Mapped[str | None] = mapped_column(String(64))
    stream_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_OBJECT
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "session_id"],
            ["session.dataset_id", "session.session_id"],
        ),
        ForeignKeyConstraint(
            ["dataset_id", "subject_id"],
            ["subject.dataset_id", "subject.subject_id"],
        ),
        ForeignKeyConstraint(
            ["dataset_id", "device_id"],
            ["device.dataset_id", "device.device_id"],
        ),
        _ck(
            "sensor_stream",
            "modality",
            "modality IN ('gnss', 'imu', 'force', 'lpt', 'tracking', 'event', 'pose')",
        ),
        _ck("sensor_stream", "measurement_class", MEASUREMENT_CLASS_SQL),
        _ck(
            "sensor_stream",
            "positive_sampling_rate",
            "nominal_sampling_rate_hz IS NULL OR nominal_sampling_rate_hz > 0",
        ),
        _ck(
            "sensor_stream",
            "pose_requires_skeleton",
            "(modality = 'pose') = (skeleton_id IS NOT NULL)",
        ),
    )


class SyncAlignment(Base):
    """Declared affine alignment between two streams of one dataset.

    ``t_target = t_source * scale + offset_ns``. The row is a *declaration*,
    never a timing-accuracy claim: a scale of 1 and an offset of 0 state that the
    two streams share a released time coordinate, not that the original
    instruments had zero synchronization error. Both stream references are
    dataset-scoped composite foreign keys, so an alignment can never pair
    streams across datasets.
    """

    __tablename__ = "sync_alignment"

    dataset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_stream_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    target_stream_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    sync_spec_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("synchronization_spec.sync_spec_id"), primary_key=True
    )
    offset_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scale: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("1.0"))
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "source_stream_id"],
            ["sensor_stream.dataset_id", "sensor_stream.stream_id"],
            name="fk_sync_alignment_source_stream",
        ),
        ForeignKeyConstraint(
            ["dataset_id", "target_stream_id"],
            ["sensor_stream.dataset_id", "sensor_stream.stream_id"],
            name="fk_sync_alignment_target_stream",
        ),
        _ck("sync_alignment", "not_self_referential", "source_stream_id <> target_stream_id"),
        # PostgreSQL orders NaN above every other float and accepts Infinity, so
        # a bare "scale > 0" would admit both; reject them explicitly.
        _ck(
            "sync_alignment",
            "positive_finite_scale",
            "scale > 0 AND scale <> 'NaN'::double precision "
            "AND scale <> 'Infinity'::double precision",
        ),
    )


class SampleArtifact(Base):
    """Materialized canonical sample file (Parquet+Zstd) for one stream."""

    __tablename__ = "sample_artifact"

    artifact_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    stream_id: Mapped[str] = mapped_column(String(128), nullable=False)
    layer: Mapped[str] = mapped_column(String(16), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'parquet'")
    )
    compression: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'zstd'")
    )
    row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    schema_fingerprint: Mapped[str | None] = mapped_column(String(64))
    partition: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_OBJECT
    )
    coordinate_frame_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("coordinate_frame.frame_id")
    )
    synchronization_spec_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("synchronization_spec.sync_spec_id")
    )
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "stream_id"],
            ["sensor_stream.dataset_id", "sensor_stream.stream_id"],
        ),
        UniqueConstraint("dataset_id", "relative_path", name="uq_sample_artifact_path"),
        _ck("sample_artifact", "layer", LAYER_SQL),
        _ck("sample_artifact", "format", FORMAT_SQL),
        _ck(
            "sample_artifact",
            "compression",
            "compression IN ('none', 'zstd', 'snappy')",
        ),
        _ck("sample_artifact", "nonnegative_rows", "row_count >= 0"),
        _ck("sample_artifact", "positive_size", "byte_size > 0"),
        _ck(
            "sample_artifact",
            "parquet_is_zstd",
            "format <> 'parquet' OR compression = 'zstd'",
        ),
    )


class ProcessingRun(Base):
    __tablename__ = "processing_run"

    run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("dataset_source.dataset_id"), nullable=False
    )
    algorithm_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("algorithm_spec.algorithm_id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'running'")
    )
    code_git_sha: Mapped[str | None] = mapped_column(String(40))
    parameters_hash: Mapped[str | None] = mapped_column(String(64))
    dagster_run_id: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_checksums: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        _ck("processing_run", "status", "status IN ('running', 'completed', 'failed')"),
        _ck(
            "processing_run",
            "completed_needs_timestamp",
            "status <> 'completed' OR completed_at IS NOT NULL",
        ),
        _ck(
            "processing_run",
            "time_order",
            "completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at",
        ),
        _ck(
            "processing_run",
            "provenance_requires_inputs",
            "jsonb_array_length(input_checksums) > 0",
        ),
    )


class ProcessingArtifact(Base):
    __tablename__ = "processing_artifact"

    artifact_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("dataset_source.dataset_id"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("processing_run.run_id"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    layer: Mapped[str] = mapped_column(String(16), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_OBJECT
    )

    __table_args__ = (
        UniqueConstraint("dataset_id", "relative_path", name="uq_processing_artifact_path"),
        _ck("processing_artifact", "layer", LAYER_SQL),
        _ck("processing_artifact", "positive_size", "byte_size IS NULL OR byte_size > 0"),
        _ck("processing_artifact", "nonnegative_rows", "row_count IS NULL OR row_count >= 0"),
    )


class QualityIssue(Base):
    """Flagged or quarantined record with mandatory evidence."""

    __tablename__ = "quality_issue"

    issue_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("dataset_source.dataset_id"), nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(String(128), ForeignKey("processing_run.run_id"))
    session_id: Mapped[str | None] = mapped_column(String(128))
    stream_id: Mapped[str | None] = mapped_column(String(128))
    subject_id: Mapped[str | None] = mapped_column(String(128))
    trial_id: Mapped[str | None] = mapped_column(String(128))
    sample_index: Mapped[int | None] = mapped_column(BigInteger)
    rule: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'QUARANTINED'")
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "stream_id"],
            ["sensor_stream.dataset_id", "sensor_stream.stream_id"],
        ),
        _ck("quality_issue", "severity", "severity IN ('INFO', 'WARNING', 'ERROR')"),
        _ck("quality_issue", "state", "state IN ('VALID', 'QUARANTINED')"),
        _ck("quality_issue", "evidence_required", "evidence <> '{}'::jsonb"),
        _ck(
            "quality_issue",
            "info_is_not_quarantined",
            "severity <> 'INFO' OR state <> 'QUARANTINED'",
        ),
        _ck(
            "quality_issue",
            "quarantine_is_located",
            "state <> 'QUARANTINED' OR stream_id IS NOT NULL OR sample_index IS NOT NULL",
        ),
        _ck(
            "quality_issue",
            "nonnegative_sample_index",
            "sample_index IS NULL OR sample_index >= 0",
        ),
    )


class MetricDefinition(Base):
    """Global scientific metric definition; never dataset-owned."""

    __tablename__ = "metric_definition"

    metric_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    si_unit: Mapped[str] = mapped_column(String(32), nullable=False)
    measurement_class: Mapped[str] = mapped_column(String(32), nullable=False)
    value_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'scalar'")
    )
    description: Mapped[str | None] = mapped_column(Text)
    algorithm_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("algorithm_spec.algorithm_id")
    )

    __table_args__ = (
        UniqueConstraint("name", name="uq_metric_definition_name"),
        _ck("metric_definition", "measurement_class", MEASUREMENT_CLASS_SQL),
        _ck(
            "metric_definition",
            "value_kind",
            "value_kind IN ('scalar', 'series', 'categorical', 'vector')",
        ),
        _ck("metric_definition", "not_raw", "measurement_class <> 'RAW_MEASURED'"),
    )


class DerivedMetric(Base):
    """Computed metric bound to checksums, algorithm, run and code revision."""

    __tablename__ = "derived_metric"

    derived_metric_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("dataset_source.dataset_id"), nullable=False
    )
    metric_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("metric_definition.metric_id"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("processing_run.run_id"), nullable=False
    )
    subject_id: Mapped[str | None] = mapped_column(String(128))
    session_id: Mapped[str | None] = mapped_column(String(128))
    trial_id: Mapped[str | None] = mapped_column(String(128))
    stream_id: Mapped[str | None] = mapped_column(String(128))
    si_unit: Mapped[str] = mapped_column(String(32), nullable=False)
    measurement_class: Mapped[str] = mapped_column(String(32), nullable=False)
    value_num: Mapped[float | None] = mapped_column(Float)
    value_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_checksums: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_OBJECT
    )

    __table_args__ = (
        _ck("derived_metric", "measurement_class", MEASUREMENT_CLASS_SQL),
        _ck("derived_metric", "not_raw", "measurement_class <> 'RAW_MEASURED'"),
        _ck(
            "derived_metric",
            "single_value_form",
            "(value_num IS NULL) <> (value_json IS NULL)",
        ),
        _ck(
            "derived_metric",
            "provenance_requires_inputs",
            "jsonb_array_length(input_checksums) > 0",
        ),
    )


EXPECTED_TABLE_NAMES = frozenset(
    {
        "algorithm_spec",
        "clock",
        "coordinate_frame",
        "dataset_source",
        "dataset_source_modality",
        "dataset_version",
        "dataset_version_file",
        "derived_metric",
        "device",
        "frame_transform",
        "license_policy",
        "metric_definition",
        "processing_artifact",
        "processing_run",
        "protocol",
        "quality_issue",
        "sample_artifact",
        "sensor_stream",
        "session",
        "session_participant",
        "skeleton_definition",
        "skeleton_joint",
        "subject",
        "sync_alignment",
        "synchronization_spec",
        "trial",
    }
)
