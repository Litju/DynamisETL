"""Local end-to-end ingestion: provider adapter -> validated Silver Parquet.

One canonical stream becomes exactly one partitioned Parquet+Zstd artifact whose
schema is validated while it streams (bounded memory), whose checksum/row count
come from the atomic writer, and whose provenance is captured in a
reconciliation receipt. Nothing is accepted if the reconciliation does not
balance.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa

from dynamis.adapters.sportec_idsse.adapter import IdsseDomain, IdsseMatchAdapter
from dynamis.adapters.womens_soccer_positioning.adapter import canonical_gnss_streams
from dynamis.adapters.womens_soccer_positioning.authorities import WOMENS_DATASET_ID
from dynamis.adapters.womens_soccer_positioning.discovery import discover_workbook
from dynamis.config import Settings
from dynamis.contracts import Modality
from dynamis.contracts.schemas import schema_fingerprint
from dynamis.pipeline.quarantine import QuarantineSink
from dynamis.pipeline.reconcile import (
    ReconciliationReceipt,
    StreamReconciliation,
    assert_reconciled,
    write_reconciliation_receipt,
)
from dynamis.pipeline.streams import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_ROW_GROUP_SIZE,
    CanonicalStream,
)
from dynamis.quality.checks import QualityError
from dynamis.quality.streaming import StreamingValidator
from dynamis.storage.parquet import write_parquet_streaming_atomic
from dynamis.storage.paths import (
    ensure_dataset_layout,
    partition_values,
    silver_parquet_path,
)

WORKBOOK_KEY_J01 = "J01.xlsx"


@dataclass(frozen=True, slots=True)
class IngestStreamResult:
    stream_id: str
    modality: str
    subject_id: str | None
    trial_id: str | None
    relative_path: str
    absolute_path: Path
    row_count: int
    byte_size: int
    checksum_sha256: str
    schema_fingerprint: str
    contract_schema_fingerprint: str
    partition: dict[str, str]
    coordinate_frame_id: str | None
    synchronization_spec_id: str
    clock_id: str
    t_rel_min_ns: int | None
    t_rel_max_ns: int | None
    null_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stream_id": self.stream_id,
            "modality": self.modality,
            "subject_id": self.subject_id,
            "trial_id": self.trial_id,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "byte_size": self.byte_size,
            "checksum_sha256": self.checksum_sha256,
            "schema_fingerprint": self.schema_fingerprint,
            "contract_schema_fingerprint": self.contract_schema_fingerprint,
            "partition": self.partition,
            "coordinate_frame_id": self.coordinate_frame_id,
            "synchronization_spec_id": self.synchronization_spec_id,
            "clock_id": self.clock_id,
            "t_rel_min_ns": self.t_rel_min_ns,
            "t_rel_max_ns": self.t_rel_max_ns,
            "null_counts": self.null_counts,
        }


@dataclass(frozen=True, slots=True)
class IngestResult:
    dataset_id: str
    version: str
    session_id: str
    source_keys: tuple[str, ...]
    streams: tuple[IngestStreamResult, ...]
    quarantine_artifacts: tuple[dict[str, Any], ...]
    reconciliation: ReconciliationReceipt
    receipt_path: str
    domain: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "version": self.version,
            "session_id": self.session_id,
            "source_keys": list(self.source_keys),
            "streams": [stream.to_dict() for stream in self.streams],
            "quarantine_artifacts": list(self.quarantine_artifacts),
            "receipt_path": self.receipt_path,
            "domain": self.domain,
            "reconciliation": self.reconciliation.to_dict(),
        }


def write_canonical_stream(
    settings: Settings,
    stream: CanonicalStream,
    *,
    row_group_size: int = DEFAULT_ROW_GROUP_SIZE,
) -> IngestStreamResult:
    """Validate and write one canonical stream as partitioned Parquet+Zstd."""
    file_schema = stream.file_schema()
    validator = StreamingValidator(file_schema)
    target = silver_parquet_path(
        settings,
        dataset_id=stream.dataset_id,
        modality=stream.modality,
        session_id=stream.session_id,
        stream_id=stream.stream_id,
    )

    def observed() -> Iterator[pa.RecordBatch]:
        for batch in stream.batches:
            validator.observe(batch)
            violations = validator.finish()
            if violations:
                raise QualityError(violations)
            yield batch

    artifact = write_parquet_streaming_atomic(
        observed(),
        target,
        schema=file_schema,
        row_group_size=row_group_size,
        relative_to=settings.dataset_root,
    )
    violations = validator.finish()
    if violations:
        raise QualityError(violations)
    return IngestStreamResult(
        stream_id=stream.stream_id,
        modality=stream.modality.value,
        subject_id=stream.subject_id,
        trial_id=stream.trial_id,
        relative_path=artifact.relative_path or "",
        absolute_path=artifact.path,
        row_count=artifact.row_count,
        byte_size=artifact.byte_size,
        checksum_sha256=artifact.checksum_sha256,
        schema_fingerprint=artifact.schema_fingerprint,
        contract_schema_fingerprint=schema_fingerprint(stream.schema),
        partition=partition_values(
            stream.dataset_id, modality=stream.modality, session_id=stream.session_id
        ),
        coordinate_frame_id=stream.coordinate_frame_id,
        synchronization_spec_id=stream.synchronization_spec_id,
        clock_id=stream.clock_id,
        t_rel_min_ns=validator.t_rel_min_ns,
        t_rel_max_ns=validator.t_rel_max_ns,
        null_counts=dict(validator.null_counts),
    )


def ingest_womens_j01(
    settings: Settings,
    *,
    workbook_path: Path,
    version: str,
    session_id: str,
    row_group_size: int = DEFAULT_ROW_GROUP_SIZE,
) -> IngestResult:
    """Women's ``J01.xlsx`` -> canonical GNSS Silver streams + reconciliation."""
    ensure_dataset_layout(settings)
    discovery = discover_workbook(workbook_path, workbook_key=WORKBOOK_KEY_J01)
    adapter, streams = canonical_gnss_streams(workbook_path, discovery)
    results: list[IngestStreamResult] = []
    reconciliations: list[StreamReconciliation] = []
    sink = QuarantineSink(settings)
    for subject in adapter.subject_streams():
        stream = adapter.canonical_stream(subject)
        result = write_canonical_stream(settings, stream, row_group_size=row_group_size)
        results.append(result)
        counters = adapter.counters(subject.sheet_name)
        quarantined = len(counters.quarantined)
        sink.add_many(counters.quarantined)
        reconciliations.append(
            StreamReconciliation(
                stream_id=subject.stream_id,
                modality=Modality.GNSS.value,
                subject_id=subject.subject_id,
                trial_id=None,
                source_records=counters.source_rows,
                canonical_rows=counters.canonical_rows,
                quarantined_rows=quarantined,
                ignored_records=0,
                ignored_reasons={},
                source_time_min=counters.first_source_time,
                source_time_max=counters.last_source_time,
                canonical_time_min_ns=counters.first_t_rel_ns,
                canonical_time_max_ns=counters.last_t_rel_ns,
                null_counts=result.null_counts,
                schema_valid=True,
                units_valid=True,
                coordinate_frame_id=stream.coordinate_frame_id,
                checks={
                    "nominal_rate_hz": subject.nominal_rate_hz,
                    "speed_source_unit": "km/h",
                    "speed_source_to_si_scale": 1.0 / 3.6,
                    "timestamp_representation": "provider local wall-clock text",
                    "identity_representation": "sheet name is the provider athlete id",
                },
            )
        )
    quarantine_artifacts = tuple(sink.materialize(name=session_id)) if sink.total else ()
    receipt = ReconciliationReceipt(
        dataset_id=WOMENS_DATASET_ID,
        version=version,
        session_id=session_id,
        source_keys=(WORKBOOK_KEY_J01,),
        streams=tuple(reconciliations),
        domain={
            "workbook_key": WORKBOOK_KEY_J01,
            "sheet_count": len(discovery.sheet_names),
            "sheet_names": list(discovery.sheet_names),
            "total_source_rows": discovery.total_rows,
            "unmapped_columns": ["hr(bpm)"],
            "unmapped_column_evidence": (
                "hr(bpm) has no canonical GNSS destination in V1; the verified workbook "
                "contains no non-null value in that column"
            ),
            "session_origin_local": adapter.session_origin.isoformat(sep=" "),
            "sheet_rows": {
                subject.sheet_name: subject.row_count for subject in adapter.subject_streams()
            },
        },
        silver_artifacts=tuple(result.to_dict() for result in results),
        quarantine_artifacts=quarantine_artifacts,
        notes=(
            "CC BY-NC 4.0 source: all inputs and outputs stay local; nothing is committed.",
            "No locomotor metric is computed; speed is unit-converted source data only.",
        ),
    )
    assert_reconciled(receipt)
    receipt_path = write_reconciliation_receipt(settings, receipt, name=f"{session_id}-gnss")
    return IngestResult(
        dataset_id=receipt.dataset_id,
        version=version,
        session_id=session_id,
        source_keys=(WORKBOOK_KEY_J01,),
        streams=tuple(results),
        quarantine_artifacts=quarantine_artifacts,
        reconciliation=receipt,
        receipt_path=receipt_path,
        domain=dict(receipt.domain),
    )


def ingest_dfl_match(
    settings: Settings,
    *,
    match_information_path: Path,
    events_path: Path,
    positions_path: Path,
    version: str,
    session_id: str,
    spill_dir: Path,
    batch_size: int | None = None,
    row_group_size: int = DEFAULT_ROW_GROUP_SIZE,
) -> IngestResult:
    """One complete IDSSE match -> tracking + event Silver streams + reconciliation."""
    ensure_dataset_layout(settings)

    adapter = IdsseMatchAdapter(
        match_information_path=match_information_path,
        events_path=events_path,
        positions_path=positions_path,
        version=version,
        spill_dir=spill_dir,
        batch_size=batch_size or DEFAULT_BATCH_SIZE,
    )
    positions_summary = adapter.parse_positions()
    events_summary = adapter.parse_events()
    domain: IdsseDomain = adapter.domain()
    positions_keys = (
        match_information_path.name,
        events_path.name,
        positions_path.name,
    )

    results: list[IngestStreamResult] = []
    for stream in adapter.tracking_streams():
        results.append(write_canonical_stream(settings, stream, row_group_size=row_group_size))
    results.append(
        write_canonical_stream(settings, adapter.event_stream(), row_group_size=row_group_size)
    )

    sink = QuarantineSink(settings)
    quarantined = adapter.quarantined()
    sink.add_many(quarantined)
    quarantine_by_rule = sink.counts
    quarantine_by_stream: dict[str, int] = {}
    for record in quarantined:
        key = record.stream_id or "unscoped"
        quarantine_by_stream[key] = quarantine_by_stream.get(key, 0) + 1
    quarantine_artifacts = tuple(sink.materialize(name=session_id)) if sink.total else ()

    reconcile_streams: list[StreamReconciliation] = []
    for section in positions_summary.sections:
        stream_id = f"tracking-{section.period_id}"
        result = next(item for item in results if item.stream_id == stream_id)
        reconcile_streams.append(
            StreamReconciliation(
                stream_id=stream_id,
                modality=Modality.TRACKING.value,
                subject_id=None,
                trial_id=section.period_id,
                source_records=section.source_frames,
                canonical_rows=section.canonical_rows,
                quarantined_rows=quarantine_by_stream.get(stream_id, 0),
                ignored_records=0,
                ignored_reasons={},
                source_time_min=None,
                source_time_max=None,
                canonical_time_min_ns=result.t_rel_min_ns,
                canonical_time_max_ns=result.t_rel_max_ns,
                null_counts=result.null_counts,
                schema_valid=True,
                units_valid=True,
                coordinate_frame_id=result.coordinate_frame_id,
                checks={
                    "frame_number_range": [section.frame_first, section.frame_last],
                    "frame_count": section.frame_count,
                    "entities": section.entity_count,
                    "ball_object_id": section.ball_object_id,
                    "frame_major_ordering": True,
                    "unmapped_attributes": "D,A,M (no published semantics; kloppy ignores them)",
                },
            )
        )
    events_result = next(item for item in results if item.stream_id == "events")
    reconcile_streams.append(
        StreamReconciliation(
            stream_id="events",
            modality=Modality.EVENT.value,
            subject_id=None,
            trial_id=None,
            source_records=events_summary.source_events,
            canonical_rows=events_summary.canonical_rows,
            quarantined_rows=len(events_summary.quarantined),
            ignored_records=events_summary.deleted_events,
            ignored_reasons={
                "provider Delete retraction events (explicitly excluded)": (
                    events_summary.deleted_events
                )
            },
            source_time_min=events_summary.source_time_min,
            source_time_max=events_summary.source_time_max,
            canonical_time_min_ns=events_summary.t_rel_min_ns,
            canonical_time_max_ns=events_summary.t_rel_max_ns,
            null_counts=events_result.null_counts,
            schema_valid=True,
            units_valid=True,
            coordinate_frame_id=events_result.coordinate_frame_id,
            checks={
                "event_types": events_summary.event_types,
                "source_order_chronological": False,
                "events_reordered": events_summary.events_reordered,
                "duplicate_timestamps": events_summary.duplicate_timestamps,
                "periods": [period.to_dict() for period in events_summary.periods],
            },
        )
    )
    receipt = ReconciliationReceipt(
        dataset_id=adapter.dataset_id,
        version=version,
        session_id=session_id,
        source_keys=positions_keys,
        streams=tuple(reconcile_streams),
        domain={
            **domain.session_metadata,
            "periods": [period.to_dict() for period in events_summary.periods],
            "quarantine_by_rule": quarantine_by_rule,
            "positions": positions_summary.to_dict(),
            "events": events_summary.to_dict(),
            "participants_registered": len(domain.participants),
            "participants_ignored": domain.participants_ignored,
        },
        silver_artifacts=tuple(result.to_dict() for result in results),
        quarantine_artifacts=quarantine_artifacts,
        notes=(
            "CC BY 4.0 source: sources and outputs stay local; nothing is committed.",
            "Tracking is frame-major with repeated t_rel_ns across entities of a frame.",
            "Source scalar speed/acceleration (S/A) have no canonical tracking field and are "
            "not fabricated; they remain in immutable Bronze.",
        ),
    )
    assert_reconciled(receipt)
    receipt_path = write_reconciliation_receipt(settings, receipt, name=f"{session_id}-match")
    adapter.cleanup()
    return IngestResult(
        dataset_id=adapter.dataset_id,
        version=version,
        session_id=session_id,
        source_keys=positions_keys,
        streams=tuple(results),
        quarantine_artifacts=quarantine_artifacts,
        reconciliation=receipt,
        receipt_path=receipt_path,
        domain=dict(receipt.domain),
    )
