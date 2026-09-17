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
    Subject,
    SyncAlignment,
    SynchronizationSpec,
    Trial,
)
from dynamis.contracts.schemas import with_file_metadata

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
        return with_file_metadata(
            self.schema,
            nominal_sampling_rate_hz=self.nominal_sampling_rate_hz,
            extras=extras,
        )


@dataclass(frozen=True, slots=True)
class SourceAuthorities:
    """Clock, synchronization, frame and alignment records a provider declares.

    Adapters build these before emitting samples; the pipeline persists them to
    the control plane so no stream can reference an undeclared authority.
    """

    frames: tuple[CoordinateFrame, ...] = ()
    clocks: tuple[Clock, ...] = ()
    synchronizations: tuple[SynchronizationSpec, ...] = ()
    alignments: tuple[SyncAlignment, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderDomain:
    """Canonical domain records for one provider session (match, matchday, ...)."""

    session: Session
    subjects: tuple[Subject, ...]
    participants: tuple[SessionParticipant, ...]
    trials: tuple[Trial, ...]
    streams: tuple[SensorStream, ...]
    authorities: SourceAuthorities = SourceAuthorities()
    devices: tuple[Device, ...] = ()
    session_metadata: dict[str, Any] = field(default_factory=dict)
    participants_ignored: dict[str, int] = field(default_factory=dict)
