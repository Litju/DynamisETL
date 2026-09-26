"""Canonical stream descriptors shared by provider adapters and the pipeline.

An adapter emits :class:`CanonicalStream` objects: a declared identity/authority
envelope plus a bounded iterator of Arrow batches for one canonical modality.
The mapper and writer never see provider column names.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import pyarrow as pa

from dynamis.contracts import (
    Clock,
    CoordinateFrame,
    Device,
    MeasurementClass,
    Modality,
    SensorStream,
    Session,
    SessionParticipant,
    SkeletonDefinition,
    Subject,
    SyncAlignment,
    SynchronizationSpec,
    Trial,
)
from dynamis.contracts.schemas import with_file_metadata
from dynamis.contracts.sports import (
    ClockMapping,
    DataGrain,
    SpatialReference,
    SportsContext,
    SurfaceGeometry,
    with_grain_metadata,
)

#: Batch authority: the maximum rows an adapter may hold before emitting a batch.
DEFAULT_BATCH_SIZE = 1 << 14
#: Row-group authority for streaming Silver writes.
DEFAULT_ROW_GROUP_SIZE = 1 << 16


@dataclass(slots=True)
class CanonicalStream:
    """One canonical stream: identity envelope, authorities, bounded batches."""

    dataset_id: str
    session_id: str
    stream_id: str
    modality: Modality
    measurement_class: MeasurementClass
    clock_id: str
    synchronization_spec_id: str
    batches: Iterable[pa.RecordBatch]
    schema: pa.Schema
    trial_id: str | None = None
    subject_id: str | None = None
    device_id: str | None = None
    coordinate_frame_id: str | None = None
    nominal_sampling_rate_hz: float | None = None
    source_unit: str | None = None
    stream_metadata: dict[str, Any] = field(default_factory=dict)
    grain: DataGrain | None = None

    @property
    def partition_modality(self) -> Modality:
        return self.modality

    def file_schema(self) -> pa.Schema:
        """Schema with file-level facts (rate, adapter provenance) attached."""
        extras = {
            "adapter": str(self.stream_metadata.get("adapter", "unknown")),
        }
        for key, value in self.stream_metadata.items():
            if key == "adapter":
                continue
            if isinstance(value, (str, int, float, bool)):
                extras[key] = str(value)
        schema = with_file_metadata(
            self.schema,
            nominal_sampling_rate_hz=self.nominal_sampling_rate_hz,
            extras=extras,
        )
        return with_grain_metadata(schema, self.grain) if self.grain is not None else schema


@dataclass(frozen=True, slots=True)
class SourceAuthorities:
    """Clock, synchronization, frame, skeleton and alignment records a provider declares.

    Adapters build these before emitting samples; the pipeline persists them to
    the control plane so no stream can reference an undeclared authority. Pose
    streams resolve their ``skeleton_id`` here, and skeleton definitions are
    persisted before the streams that reference them.
    """

    frames: tuple[CoordinateFrame, ...] = ()
    clocks: tuple[Clock, ...] = ()
    synchronizations: tuple[SynchronizationSpec, ...] = ()
    alignments: tuple[SyncAlignment, ...] = ()
    skeletons: tuple[SkeletonDefinition, ...] = ()
    spatial_references: tuple[SpatialReference, ...] = ()
    surface_geometries: tuple[SurfaceGeometry, ...] = ()
    clock_mappings: tuple[ClockMapping, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderDomain:
    """Canonical domain records for one provider slice.

    A slice normally belongs to one session (a match, a matchday). A provider
    whose source distributes independent per-subject laboratory trials without
    visit boundaries declares one session per subject instead, using
    ``sessions``; ``session`` stays the single-session form and must not be
    mixed with it.
    """

    session: Session | None
    subjects: tuple[Subject, ...]
    participants: tuple[SessionParticipant, ...]
    trials: tuple[Trial, ...]
    streams: tuple[SensorStream, ...]
    authorities: SourceAuthorities = SourceAuthorities()
    devices: tuple[Device, ...] = ()
    session_metadata: dict[str, Any] = field(default_factory=dict)
    participants_ignored: dict[str, int] = field(default_factory=dict)
    sessions: tuple[Session, ...] = ()
    sports_contexts: tuple[SportsContext, ...] = ()

    def __post_init__(self) -> None:
        if self.session is not None and self.sessions:
            raise ValueError("declare either session or sessions, not both")
        if self.session is None and not self.sessions:
            raise ValueError("a provider domain must declare at least one session")

    @property
    def all_sessions(self) -> tuple[Session, ...]:
        if self.sessions:
            return self.sessions
        assert self.session is not None  # enforced by __post_init__
        return (self.session,)
