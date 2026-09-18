"""Local end-to-end ingestion: provider adapter -> validated Silver Parquet.

One canonical stream becomes exactly one partitioned Parquet+Zstd artifact whose
schema is validated while it streams (bounded memory), whose checksum/row count
come from the atomic writer, and whose provenance is captured in a
reconciliation receipt. Nothing is accepted if the reconciliation does not
balance.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa

from dynamis.adapters.gymaware_landmine.adapter import GymAwareAdapter
from dynamis.adapters.gymaware_landmine.authorities import GYMAWARE_DATASET_ID
from dynamis.adapters.gymaware_landmine.discovery import discover_gymaware_landmine
from dynamis.adapters.skillcorner.adapter import SkillCornerMatchAdapter
from dynamis.adapters.skillcorner.authorities import POSE_LANDMARKS, SKILLCORNER_DATASET_ID
from dynamis.adapters.skillcorner.discovery import discover_skillcorner
from dynamis.adapters.skillcorner.metadata import parse_match_metadata
from dynamis.adapters.spl.adapter import SplFreethrowAdapter, SplTrialSource
from dynamis.adapters.spl.authorities import SPL_DATASET_ID
from dynamis.adapters.spl.discovery import discover_spl
from dynamis.adapters.sportec_idsse.adapter import IdsseMatchAdapter
from dynamis.adapters.sportec_idsse.authorities import tracking_stream_id
from dynamis.adapters.sportec_idsse.discovery import discover_idsse
from dynamis.adapters.white_cmj.adapter import (
    WHITE_DATASET_ID,
    WhiteCmjAdapter,
    force_stream_id,
    imu_stream_id,
)
from dynamis.adapters.white_cmj.authorities import WHITE_NPZ_KEY
from dynamis.adapters.white_cmj.discovery import load_white_cmj_bundle
from dynamis.adapters.womens_soccer_positioning.adapter import canonical_gnss_streams
from dynamis.adapters.womens_soccer_positioning.authorities import (
    CANONICAL_DATUM,
    DATUM_AUTHORITY,
    SOURCE_COORDINATE_REPRESENTATION,
    SOURCE_DATUM_DECLARATION,
    WOMENS_DATASET_ID,
)
from dynamis.adapters.womens_soccer_positioning.discovery import discover_workbook
from dynamis.config import Settings
from dynamis.contracts import Modality
from dynamis.contracts.schemas import schema_fingerprint, schema_version_of
from dynamis.pipeline.quarantine import QuarantinedRecord, QuarantineSink
from dynamis.pipeline.reconcile import (
    ReconciliationReceipt,
    StreamReconciliation,
    assert_reconciled,
    write_reconciliation_receipt,
)
from dynamis.pipeline.source_metrics import SourceMetricObservation
from dynamis.pipeline.streams import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_ROW_GROUP_SIZE,
    CanonicalStream,
    ProviderDomain,
)
from dynamis.quality.checks import QualityError
from dynamis.quality.streaming import StreamingValidator
from dynamis.rights import assert_dataset_root_outside_repository
from dynamis.storage.parquet import write_parquet_streaming_atomic
from dynamis.storage.paths import (
    ensure_dataset_layout,
    partition_values,
    silver_parquet_path,
)


def assert_local_only_boundary(settings: Settings, dataset_id: str) -> None:
    """Refuse to materialize a local-only source inside the repository."""
    from dynamis.registry import source_by_id, validate_registry

    source = source_by_id(validate_registry(), dataset_id)
    assert_dataset_root_outside_repository(source, settings.dataset_root)


WORKBOOK_KEY_J01 = "J01.xlsx"


@dataclass(frozen=True, slots=True)
class IngestStreamResult:
    stream_id: str
    modality: str
    session_id: str
    subject_id: str | None
    trial_id: str | None
    relative_path: str
    absolute_path: Path
    row_count: int
    byte_size: int
    checksum_sha256: str
    schema_fingerprint: str
    contract_schema_fingerprint: str
    schema_version: str
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
            "session_id": self.session_id,
            "subject_id": self.subject_id,
            "trial_id": self.trial_id,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "byte_size": self.byte_size,
            "checksum_sha256": self.checksum_sha256,
            "schema_fingerprint": self.schema_fingerprint,
            "contract_schema_fingerprint": self.contract_schema_fingerprint,
            "schema_version": self.schema_version,
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
    provider_domain: ProviderDomain
    quarantine_records: tuple[QuarantinedRecord, ...] = ()
    domain: dict[str, Any] = field(default_factory=dict)
    source_metrics: tuple[SourceMetricObservation, ...] = ()

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


def write_discovery_receipts(
    settings: Settings,
    *,
    dataset_id: str,
    version: str,
    workbook_path: Path | None = None,
    match_information_path: Path | None = None,
    events_path: Path | None = None,
    positions_path: Path | None = None,
    npz_path: Path | None = None,
    archive_path: Path | None = None,
    skillcorner_metadata_path: Path | None = None,
    skillcorner_tracking_path: Path | None = None,
    skillcorner_pose_path: Path | None = None,
    spl_trial_paths: tuple[SplTrialSource, ...] = (),
    name: str,
) -> str:
    """Write the structural discovery receipt for a provider slice.

    Nothing here is assumed from memory: the receipt records sheets/rows/columns/
    null patterns for the workbook, namespaces/hierarchy/frames/entities/units
    and the undecoded vendor attributes for the XML set, NPZ member headers plus
    restricted-pickle safety results for the laboratory release, and the ZIP
    central directory plus structured-member hashes for the GymAware archive.
    """
    from dynamis.storage.atomic import atomic_write_text
    from dynamis.storage.paths import receipt_path

    if dataset_id == WOMENS_DATASET_ID:
        if workbook_path is None:
            raise ValueError("Women's discovery requires the workbook path")
        payload = discover_workbook(workbook_path).to_dict()
    elif dataset_id == WHITE_DATASET_ID:
        if npz_path is None:
            raise ValueError("White CMJ discovery requires the .npz path")
        from dynamis.adapters.white_cmj.discovery import discover_white_cmj_file

        payload = discover_white_cmj_file(npz_path).to_dict()
    elif dataset_id == GYMAWARE_DATASET_ID:
        if archive_path is None:
            raise ValueError("GymAware discovery requires the .zip path")
        payload = discover_gymaware_landmine(archive_path).to_dict()
    elif dataset_id == SKILLCORNER_DATASET_ID:
        if (
            skillcorner_metadata_path is None
            or skillcorner_tracking_path is None
            or (skillcorner_pose_path is None)
        ):
            raise ValueError(
                "SkillCorner discovery requires the match metadata, tracking and pose archive"
            )
        payload = discover_skillcorner(
            metadata=parse_match_metadata(skillcorner_metadata_path),
            tracking_path=skillcorner_tracking_path,
            pose_zip_path=skillcorner_pose_path,
        ).to_dict()
    elif dataset_id == SPL_DATASET_ID:
        if not spl_trial_paths:
            raise ValueError("SPL discovery requires at least one locked trial path")
        payload = discover_spl(tuple(spl_trial_paths)).to_dict()
    else:
        if match_information_path is None or events_path is None or positions_path is None:
            raise ValueError("IDSSE discovery requires the three XML paths")
        payload = discover_idsse(match_information_path, events_path, positions_path).to_dict()
    target = receipt_path(settings, dataset_id=dataset_id, kind="discovery", name=name)
    atomic_write_text(target, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return target.as_posix()


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
        session_id=stream.session_id,
        subject_id=stream.subject_id,
        trial_id=stream.trial_id,
        relative_path=artifact.relative_path or "",
        absolute_path=artifact.path,
        row_count=artifact.row_count,
        byte_size=artifact.byte_size,
        checksum_sha256=artifact.checksum_sha256,
        schema_fingerprint=artifact.schema_fingerprint,
        contract_schema_fingerprint=schema_fingerprint(stream.schema),
        schema_version=schema_version_of(stream.schema),
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
    assert_local_only_boundary(settings, WOMENS_DATASET_ID)
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
                    "source_coordinate_representation": SOURCE_COORDINATE_REPRESENTATION,
                    "source_datum": SOURCE_DATUM_DECLARATION,
                    "canonical_datum": CANONICAL_DATUM,
                    "datum_authority": DATUM_AUTHORITY,
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
            "geodetic_datum": {
                "source_coordinate_representation": SOURCE_COORDINATE_REPRESENTATION,
                "source_datum": SOURCE_DATUM_DECLARATION,
                "canonical_interpretation": CANONICAL_DATUM,
                "authority": DATUM_AUTHORITY,
                "transformation": "none; source coordinate values pass through unchanged",
            },
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
    sink_records = [
        record
        for subject in adapter.subject_streams()
        for record in adapter.counters(subject.sheet_name).quarantined
    ]
    return IngestResult(
        dataset_id=receipt.dataset_id,
        version=version,
        session_id=session_id,
        source_keys=(WORKBOOK_KEY_J01,),
        streams=tuple(results),
        quarantine_artifacts=quarantine_artifacts,
        reconciliation=receipt,
        receipt_path=receipt_path,
        provider_domain=adapter.domain(),
        quarantine_records=tuple(sink_records),
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
    assert_local_only_boundary(settings, "dfl-sportec-idsse")
    ensure_dataset_layout(settings)

    adapter = IdsseMatchAdapter(
        match_information_path=match_information_path,
        events_path=events_path,
        positions_path=positions_path,
        version=version,
        spill_dir=spill_dir,
        batch_size=batch_size or DEFAULT_BATCH_SIZE,
    )
    try:
        positions_summary = adapter.parse_positions()
        events_summary = adapter.parse_events()
        domain: ProviderDomain = adapter.domain()
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
            stream_id = tracking_stream_id(section.period_id)
            result = next(item for item in results if item.stream_id == stream_id)
            reconcile_streams.append(
                StreamReconciliation(
                    stream_id=stream_id,
                    modality=Modality.TRACKING.value,
                    subject_id=None,
                    trial_id=section.period_id,
                    source_records=section.frame_entity_observations,
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
                        "distinct_frame_ticks": section.distinct_frame_ticks,
                        "entity_frame_observations": section.frame_entity_observations,
                        "entities": section.entity_count,
                        "ball_object_id": section.ball_object_id,
                        "frame_major_ordering": True,
                        "unmapped_attributes": (
                            "D,A,M (no published semantics; kloppy ignores them)"
                        ),
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
    finally:
        # Spill files are temporary; a failed write must not leave the dataset
        # root growing run after run.
        adapter.cleanup()
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
    return IngestResult(
        dataset_id=adapter.dataset_id,
        version=version,
        session_id=session_id,
        source_keys=positions_keys,
        streams=tuple(results),
        quarantine_artifacts=quarantine_artifacts,
        reconciliation=receipt,
        receipt_path=receipt_path,
        provider_domain=domain,
        quarantine_records=tuple(quarantined),
        domain=dict(receipt.domain),
    )


def ingest_white_cmj(
    settings: Settings,
    *,
    npz_path: Path,
    version: str,
    row_group_size: int = DEFAULT_ROW_GROUP_SIZE,
) -> IngestResult:
    """White CMJ release -> per-trial canonical IMU + force Silver streams.

    The released arrays are canonicalized exactly as distributed: full-length
    accelerometer at 250 Hz into ``imu_sample`` (g -> m/s**2) and pre-takeoff
    vGRF at 1000 Hz into ``force_sample`` as a dimensionless body-weight ratio.
    Every trial is an independent takeoff-relative clock; nothing is
    concatenated and no biomechanical processor runs.
    """
    assert_local_only_boundary(settings, WHITE_DATASET_ID)
    ensure_dataset_layout(settings)
    bundle = load_white_cmj_bundle(npz_path)
    adapter = WhiteCmjAdapter(bundle)
    sink = QuarantineSink(settings)
    results: list[IngestStreamResult] = []
    reconciliations: list[StreamReconciliation] = []
    for trial in adapter.trials:
        acc = bundle.acc_signals[trial.row_index]
        grf = bundle.grf_signals[trial.row_index]
        valid = adapter.trial_is_valid(trial)
        for modality, source_samples, stream_id in (
            (Modality.IMU, int(acc.shape[0]), imu_stream_id(trial.trial_id)),
            (Modality.FORCE, int(grf.shape[0]), force_stream_id(trial.trial_id)),
        ):
            stream = adapter.canonical_stream(trial, modality)
            if valid:
                result = write_canonical_stream(settings, stream, row_group_size=row_group_size)
                results.append(result)
                canonical_rows = source_samples
                quarantined_rows = 0
            else:
                canonical_rows = 0
                quarantined_rows = source_samples
            if modality is Modality.IMU:
                ns_per_sample = 1_000_000_000 // bundle.acc_sampling_rate_hz
                first_index = 0
                last_index = source_samples - 1
                takeoff = int(bundle.acc_takeoff[trial.row_index])
            else:
                ns_per_sample = 1_000_000_000 // bundle.grf_sampling_rate_hz
                takeoff = source_samples - 1
                first_index = 0
                last_index = source_samples - 1
            reconciliations.append(
                StreamReconciliation(
                    stream_id=stream_id,
                    modality=modality.value,
                    subject_id=trial.subject_id,
                    trial_id=trial.trial_id,
                    source_records=source_samples,
                    canonical_rows=canonical_rows,
                    quarantined_rows=quarantined_rows,
                    ignored_records=0,
                    ignored_reasons={},
                    source_time_min=None,
                    source_time_max=None,
                    canonical_time_min_ns=(
                        (first_index - takeoff) * ns_per_sample if valid else None
                    ),
                    canonical_time_max_ns=(
                        (last_index - takeoff) * ns_per_sample if valid else None
                    ),
                    null_counts={},
                    schema_valid=True,
                    units_valid=True,
                    coordinate_frame_id=stream.coordinate_frame_id,
                    checks={
                        "measurement_class": "SOURCE_DERIVED",
                        "source_rate_hz": (
                            bundle.acc_sampling_rate_hz
                            if modality is Modality.IMU
                            else bundle.grf_sampling_rate_hz
                        ),
                        "source_samples": source_samples,
                        "condition": trial.condition,
                        "source_row_index": trial.row_index,
                        "takeoff_relative": True,
                        "quarantined_trial": not valid,
                    },
                )
            )
    valid_trials = sum(1 for trial in adapter.trials if adapter.trial_is_valid(trial))
    # Importing source metrics may add quarantine records for non-finite scalars;
    # collect every trial's findings once, then materialize.
    source_metric_observations = adapter.source_metrics()
    for trial in adapter.trials:
        sink.add_many(adapter.counters(trial.trial_id).quarantined)
    quarantine_artifacts = tuple(sink.materialize(name="white-cmj-trials")) if sink.total else ()
    domain_records = adapter.domain()
    receipt = ReconciliationReceipt(
        dataset_id=WHITE_DATASET_ID,
        version=version,
        session_id="white-cmj-release",
        source_keys=(WHITE_NPZ_KEY,),
        streams=tuple(reconciliations),
        domain={
            "source_key": WHITE_NPZ_KEY,
            "trial_count": len(adapter.trials),
            "valid_trials": valid_trials,
            "quarantined_trials": len(adapter.trials) - valid_trials,
            "subject_id_count": adapter.discovery.subject_id_count,
            "declared_n_subjects_member": bundle.declared_n_subjects,
            "condition_counts": adapter.discovery.condition_counts,
            "acc_rate_hz": bundle.acc_sampling_rate_hz,
            "grf_rate_hz": bundle.grf_sampling_rate_hz,
            "acc_sample_counts": adapter.discovery.acc_sample_counts,
            "grf_sample_counts": adapter.discovery.grf_sample_counts,
            "source_metric_observations": len(source_metric_observations),
            "sensor_placement": {
                "distributed_record": "L5",
                "original_paper": "L4",
                "authority": "conflicting source documentation",
            },
            "timing_convention": (
                "accelerometer t_rel_ns = (sample_index - acc_takeoff) * 4 ms; "
                "vGRF t_rel_ns = (sample_index - (samples-1)) * 1 ms (final sample = takeoff). "
                "The provider's grf_takeoff member is an original-source index and is not "
                "used to index the distributed curve."
            ),
            "released_form": (
                "The deposit distributes full signals, not the 500-sample 2000 ms window "
                "described by the record prose; the window extraction belongs to the "
                "reference consumer, so RES-98 canonicalizes the distributed arrays."
            ),
            "quarantine_by_rule": sink.counts,
        },
        silver_artifacts=tuple(result.to_dict() for result in results),
        quarantine_artifacts=quarantine_artifacts,
        notes=(
            "CC BY 4.0 source (attribution required; redistribution conditional): inputs "
            "and outputs stay outside Git.",
            "No RES-100 biomechanical processor runs; only canonicalization and unit conversion.",
            "Each CMJ is an independent takeoff-relative trial clock; no cross-trial "
            "concatenation exists.",
        ),
    )
    assert_reconciled(receipt)
    receipt_path = write_reconciliation_receipt(settings, receipt, name="white-cmj-release")
    return IngestResult(
        dataset_id=WHITE_DATASET_ID,
        version=version,
        session_id="white-cmj-release",
        source_keys=(WHITE_NPZ_KEY,),
        streams=tuple(results),
        quarantine_artifacts=quarantine_artifacts,
        reconciliation=receipt,
        receipt_path=receipt_path,
        provider_domain=domain_records,
        quarantine_records=tuple(sink.all_records()),
        domain=dict(receipt.domain),
        source_metrics=source_metric_observations,
    )


def ingest_skillcorner_match(
    settings: Settings,
    *,
    match_json_path: Path,
    tracking_path: Path,
    pose_zip_path: Path,
    version: str,
    row_group_size: int = DEFAULT_ROW_GROUP_SIZE,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> IngestResult:
    """One SkillCorner match -> 10 Hz tracking + 25 Hz pose Silver streams.

    The pose archive member is streamed directly from the ZIP; the ~3.3 GB
    plaintext file is never expanded and no match-sized Python structure is
    materialized. Provider/model-estimated coordinates stay labelled
    ``MODEL_ESTIMATED``; the provider match clock, hybrid pose geometry and
    p90 error-radius semantics are preserved exactly, and pose/tracking XY
    disagreement is measured at documented coincidences rather than corrected.
    """
    assert_local_only_boundary(settings, SKILLCORNER_DATASET_ID)
    ensure_dataset_layout(settings)

    adapter = SkillCornerMatchAdapter(
        match_json_path=match_json_path,
        tracking_path=tracking_path,
        pose_zip_path=pose_zip_path,
        version=version,
        batch_size=batch_size,
    )
    metadata = adapter.metadata
    source_keys = (
        f"data/matches/{metadata.match_id}/{metadata.match_id}_match.json",
        f"data/matches/{metadata.match_id}/{metadata.match_id}_tracking_extrapolated.jsonl",
        f"raw/{metadata.match_id}.jsonl.zip",
    )

    streams = (*adapter.tracking_streams(), *adapter.pose_streams())
    results: list[IngestStreamResult] = [
        write_canonical_stream(settings, stream, row_group_size=row_group_size)
        for stream in streams
    ]
    result_by_stream = {item.stream_id: item for item in results}

    coincidence = adapter.coincidence_report()
    sink = QuarantineSink(settings)
    sink.add_many(adapter.quarantined())
    quarantine_artifacts = tuple(sink.materialize(name=metadata.match_id)) if sink.total else ()

    reconciliations: list[StreamReconciliation] = []
    tracking_summaries: dict[str, dict[str, Any]] = {}
    pose_summaries: dict[str, dict[str, Any]] = {}
    declared_player_ids = {player.player_id for player in metadata.players}
    observed_player_ids: set[str] = set()
    for period in metadata.periods:
        tracking = adapter.tracking_summary(period.period)
        pose = adapter.pose_summary(period.period)
        observed_player_ids |= tracking.seen_player_ids | pose.seen_player_ids
        tracking_summaries[tracking.stream_id] = tracking.to_dict()
        pose_summaries[pose.stream_id] = pose.to_dict()
        tracking_result = result_by_stream[tracking.stream_id]
        pose_result = result_by_stream[pose.stream_id]
        reconciliations.append(
            StreamReconciliation(
                stream_id=tracking.stream_id,
                modality=Modality.TRACKING.value,
                subject_id=None,
                trial_id=period.name,
                source_records=tracking.source_records,
                canonical_rows=tracking.canonical_rows,
                quarantined_rows=tracking.quarantined_rows,
                ignored_records=tracking.ignored_ball_without_coordinates,
                ignored_reasons={
                    "ball entries with no coordinates at all (explicit non-observation)": (
                        tracking.ignored_ball_without_coordinates
                    )
                },
                canonical_time_min_ns=tracking_result.t_rel_min_ns,
                canonical_time_max_ns=tracking_result.t_rel_max_ns,
                null_counts=tracking_result.null_counts,
                schema_valid=True,
                units_valid=True,
                coordinate_frame_id=tracking_result.coordinate_frame_id,
                checks={
                    **tracking.to_dict(),
                    "frame_range": [period.start_frame, period.end_frame],
                    "provider_is_detected_semantics": (
                        "true = detected on screen; false = provider extrapolation"
                    ),
                },
            )
        )
        reconciliations.append(
            StreamReconciliation(
                stream_id=pose.stream_id,
                modality=Modality.POSE.value,
                subject_id=None,
                trial_id=period.name,
                source_records=pose.source_records,
                canonical_rows=pose.canonical_rows,
                quarantined_rows=pose.quarantined_rows,
                ignored_records=0,
                ignored_reasons={},
                canonical_time_min_ns=pose_result.t_rel_min_ns,
                canonical_time_max_ns=pose_result.t_rel_max_ns,
                null_counts=pose_result.null_counts,
                schema_valid=True,
                units_valid=True,
                coordinate_frame_id=pose_result.coordinate_frame_id,
                checks={
                    **pose.to_dict(),
                    "frame_range": [period.start_frame, period.end_frame],
                    "landmark_order_authority": (
                        "data/bodypose/README.md at the pinned SkillCorner revision"
                    ),
                    "error_source_field": "p90_mae_cm",
                    "error_source_to_si_scale": 0.01,
                    "error_semantics": (
                        "90th-percentile predicted error radius; never a probability or confidence"
                    ),
                    "player_frames_without_pose": (
                        pose.player_frames - pose.player_frames_with_pose
                    ),
                    "missing_joints_imputed": False,
                    "unavailable_joint_rows": pose.unavailable_joints,
                },
            )
        )

    unmatched_player_ids = sorted(declared_player_ids - observed_player_ids)
    receipt = ReconciliationReceipt(
        dataset_id=SKILLCORNER_DATASET_ID,
        version=version,
        session_id=metadata.session_id,
        source_keys=source_keys,
        streams=tuple(reconciliations),
        domain={
            "match_id": metadata.match_id,
            "title": metadata.title,
            "kickoff_utc": metadata.kickoff_utc.isoformat(),
            "pitch_size_m": [metadata.pitch_length_m, metadata.pitch_width_m],
            "stadium": metadata.stadium,
            "periods": [period.to_dict() for period in metadata.periods],
            "declared_players": len(metadata.players),
            "observed_player_ids": len(observed_player_ids),
            "unmatched_declared_player_ids": unmatched_player_ids,
            "tracking": tracking_summaries,
            "pose": pose_summaries,
            "pose_tracking_sync": coincidence.to_dict(),
            "measurement_classes": {
                "tracking": "MODEL_ESTIMATED",
                "pose": "MODEL_ESTIMATED",
            },
            "geometry": {
                "tracking": "pitch-centred X/Y metres; source Z preserved unchanged",
                "pose": (
                    "hybrid: pitch-global X/Y with source Z relative to the player centroid, "
                    "not pitch-registered"
                ),
                "hidden_corrections": False,
                "absolute_height_interpretation": False,
            },
            "quarantine_by_rule": sink.counts,
            "landmark_order": list(POSE_LANDMARKS),
        },
        silver_artifacts=tuple(result.to_dict() for result in results),
        quarantine_artifacts=quarantine_artifacts,
        notes=(
            "MIT source (attribution requested): inputs and outputs stay outside Git.",
            "Pose and tracking coordinates are provider broadcast-video model estimates "
            "(MODEL_ESTIMATED), never raw instrument measurements.",
            "Provider Z is preserved exactly: no global pitch registration for pose Z, no "
            "absolute player-height interpretation, no hidden transform.",
            "Player frames with joints=null remain explicit coverage counts; individual "
            "missing joints would stay is_available=false rows; nothing is imputed.",
            "No smoothing, interpolation, joint angle, angular velocity, ROM or inverse "
            "dynamics runs in RES-99.",
        ),
    )
    assert_reconciled(receipt)
    receipt_path = write_reconciliation_receipt(
        settings, receipt, name=f"{metadata.match_id}-match"
    )
    return IngestResult(
        dataset_id=SKILLCORNER_DATASET_ID,
        version=version,
        session_id=metadata.session_id,
        source_keys=source_keys,
        streams=tuple(results),
        quarantine_artifacts=quarantine_artifacts,
        reconciliation=receipt,
        receipt_path=receipt_path,
        provider_domain=adapter.domain(),
        quarantine_records=tuple(sink.all_records()),
        domain=dict(receipt.domain),
    )


def ingest_spl_trials(
    settings: Settings,
    *,
    trials: tuple[SplTrialSource, ...],
    version: str,
    row_group_size: int = DEFAULT_ROW_GROUP_SIZE,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> IngestResult:
    """Locked SPL free-throw trials -> canonical pose Silver streams.

    The same dataset participant is carried across sessions as one identity while
    the sessions and their clocks stay distinct. Coordinates are converted from
    the source's feet to metres with the exact 0.3048 factor; session-specific
    keypoint availability is preserved with explicit unavailable rows, and no
    parent graph is invented.
    """
    if not trials:
        raise ValueError("SPL ingestion requires at least one locked trial")
    assert_local_only_boundary(settings, SPL_DATASET_ID)
    ensure_dataset_layout(settings)

    adapter = SplFreethrowAdapter(trials=trials, version=version, batch_size=batch_size)
    source_keys = tuple(source.key for source in trials)
    # The receipt identity names the participant slice, not one session: the same
    # participant is deliberately present in every accepted session.
    participant_ids = sorted({identity.participant_id for identity in adapter.identities()})
    receipt_scope = participant_ids[0] if len(participant_ids) == 1 else "spl-freethrow"

    results: list[IngestStreamResult] = [
        write_canonical_stream(settings, stream, row_group_size=row_group_size)
        for stream in adapter.streams()
    ]
    result_by_stream = {item.stream_id: item for item in results}

    sink = QuarantineSink(settings)
    sink.add_many(adapter.quarantined())
    quarantine_artifacts = tuple(sink.materialize(name=receipt_scope)) if sink.total else ()

    reconciliations: list[StreamReconciliation] = []
    trial_receipts: list[dict[str, Any]] = []
    canonicalizers = adapter.canonicalizers()
    for source in trials:
        canonicalizer = canonicalizers[source.key]
        summary = canonicalizer.summary()
        result = result_by_stream[summary.stream_id]
        checks = {
            **summary.to_dict(),
            "skeleton_id": canonicalizer.skeleton_id,
            "source_length_unit": "ft",
            "source_to_si_scale": 0.3048,
            "conversion": "value_m = value_ft * 0.3048 (exact documented factor)",
            "topology": "landmark_set (source publishes no parent graph)",
            "missing_keypoints_imputed": False,
            "ball_not_canonicalized": (
                "ball trajectory and shot-result context are not pose concepts in RES-99 "
                "and remain in immutable Bronze"
            ),
        }
        trial_receipts.append(checks)
        reconciliations.append(
            StreamReconciliation(
                stream_id=summary.stream_id,
                modality=Modality.POSE.value,
                subject_id=summary.identity.participant_id,
                trial_id=summary.identity.trial_id,
                source_records=summary.source_records,
                canonical_rows=summary.canonical_rows,
                quarantined_rows=summary.quarantined_rows,
                ignored_records=0,
                ignored_reasons={},
                canonical_time_min_ns=result.t_rel_min_ns,
                canonical_time_max_ns=result.t_rel_max_ns,
                null_counts=result.null_counts,
                schema_valid=True,
                units_valid=True,
                coordinate_frame_id=result.coordinate_frame_id,
                checks=checks,
            )
        )

    receipt = ReconciliationReceipt(
        dataset_id=SPL_DATASET_ID,
        version=version,
        session_id=receipt_scope,
        source_keys=source_keys,
        streams=tuple(reconciliations),
        domain={
            "participant_ids": participant_ids,
            "participant_identity_consistent_across_sessions": True,
            "sessions": sorted({identity.session_date for identity in adapter.identities()}),
            "rates_hz": {
                summary.identity.session_date: summary.sampling_rate_hz
                for summary in adapter.summaries()
            },
            "trials": trial_receipts,
            "ball_observations_by_trial": {
                summary.stream_id: summary.ball_observations for summary in adapter.summaries()
            },
            "feet_to_metre_scale": 0.3048,
            "cross_session_synchronization": False,
            "quarantine_by_rule": sink.counts,
            "skeletons": [
                {
                    "skeleton_id": skeleton.skeleton_id,
                    "topology": skeleton.topology.value,
                    "joint_count": skeleton.joint_count,
                    "joints": [joint.joint_name for joint in skeleton.joints],
                }
                for skeleton in adapter.source_authorities().skeletons
            ],
        },
        silver_artifacts=tuple(result.to_dict() for result in results),
        quarantine_artifacts=quarantine_artifacts,
        notes=(
            "CC BY-NC-SA 4.0 plus the role-dependent exclusion: inputs and outputs stay "
            "outside Git; NC/SA obligations are never overridden.",
            "Pose keypoints are provider model estimates (MODEL_ESTIMATED), never raw "
            "instrument measurements.",
            "Session-specific keypoint availability is preserved: null/absent keypoints are "
            "explicit is_available=false rows and are never imputed.",
            "No parent graph is invented for a source that publishes none.",
            "No smoothing, interpolation, joint angle, angular velocity, ROM or inverse "
            "dynamics runs in RES-99.",
        ),
    )
    assert_reconciled(receipt)
    receipt_path = write_reconciliation_receipt(settings, receipt, name=f"{receipt_scope}-pose")
    return IngestResult(
        dataset_id=SPL_DATASET_ID,
        version=version,
        session_id=receipt_scope,
        source_keys=source_keys,
        streams=tuple(results),
        quarantine_artifacts=quarantine_artifacts,
        reconciliation=receipt,
        receipt_path=receipt_path,
        provider_domain=adapter.domain(),
        quarantine_records=tuple(sink.all_records()),
        domain=dict(receipt.domain),
    )


def _identity_for_source(source: SplTrialSource):
    from dynamis.adapters.spl.trial import identity_from_key

    return identity_from_key(source.key)


def ingest_gymaware_landmine(
    settings: Settings,
    *,
    zip_path: Path,
    version: str,
) -> IngestResult:
    """GymAware landmine archive -> source-derived trial metrics only.

    Discovery proves the archive distributes no sample-level LPT trajectory, so
    no dense stream is fabricated. Rep-level GymAware indicators and the
    populated vision-workbook values are imported as source-derived scalar
    observations; pairing is proved by the source inclusion number and rep id.
    """
    assert_local_only_boundary(settings, GYMAWARE_DATASET_ID)
    ensure_dataset_layout(settings)
    discovery = discover_gymaware_landmine(zip_path)
    adapter = GymAwareAdapter(discovery)
    observations = adapter.observations()
    sink = QuarantineSink(settings)
    sink.add_many(adapter.counters.quarantined)
    quarantine_artifacts = tuple(sink.materialize(name="gymaware-landmine")) if sink.total else ()
    gymaware_source_values = sum(
        len(rep.values) for item in discovery.gymaware_sets for rep in item.reps
    )
    gymaware_observations = len(
        [item for item in observations if item.metric_id.startswith("gymaware_")]
    )
    vision_observations = len(
        [item for item in observations if item.metric_id.startswith("vision_")]
    )
    stream_rows = (
        StreamReconciliation(
            stream_id="gymaware-sets",
            modality=Modality.LPT.value,
            subject_id=None,
            trial_id=None,
            source_records=adapter.counters.source_sets,
            canonical_rows=adapter.counters.gymaware_sets,
            quarantined_rows=0,
            ignored_records=len(adapter.excluded_sets),
            ignored_reasons={
                "vision workbook rows without a GymAware export and without any "
                "distributed numeric value (documented exclusions)": len(adapter.excluded_sets)
            },
            checks={"excluded_sets": sorted(adapter.excluded_sets)},
        ),
        StreamReconciliation(
            stream_id="gymaware-rep-rows",
            modality=Modality.LPT.value,
            subject_id=None,
            trial_id=None,
            source_records=adapter.counters.source_rep_rows,
            canonical_rows=adapter.counters.canonical_trials,
            quarantined_rows=adapter.counters.quarantined_rep_rows,
            ignored_records=0,
            ignored_reasons={},
        ),
        StreamReconciliation(
            stream_id="gymaware-metric-values",
            modality=Modality.LPT.value,
            subject_id=None,
            trial_id=None,
            source_records=gymaware_source_values,
            canonical_rows=gymaware_observations,
            quarantined_rows=gymaware_source_values - gymaware_observations,
            ignored_records=0,
            ignored_reasons={},
            checks={"method_radius_m": 2.05, "correction_applied": False},
        ),
        StreamReconciliation(
            stream_id="vision-metric-values",
            modality=Modality.LPT.value,
            subject_id=None,
            trial_id=None,
            source_records=discovery.vision.populated_value_count,
            canonical_rows=vision_observations,
            quarantined_rows=discovery.vision.populated_value_count - vision_observations,
            ignored_records=0,
            ignored_reasons={},
            checks={"method_radius_m": 2.20, "correction_applied": False},
        ),
    )
    receipt = ReconciliationReceipt(
        dataset_id=GYMAWARE_DATASET_ID,
        version=version,
        session_id="gymaware-landmine-release",
        source_keys=(discovery.inspection.archive_name,),
        streams=stream_rows,
        domain={
            "archive": discovery.inspection.to_dict()["archive"],
            "gymaware_sets": len(discovery.gymaware_sets),
            "gymaware_rep_rows": discovery.gymaware_rep_rows,
            "canonical_trials": adapter.counters.canonical_trials,
            "vision_workbook_rows": discovery.vision.populated_row_count,
            "vision_populated_values": discovery.vision.populated_value_count,
            "source_metric_observations": len(observations),
            "dense_lpt_stream_present": False,
            "method_metadata": {
                "vision_effective_radius_m": 2.20,
                "gymaware_effective_radius_m": 2.05,
                "correction_applied": False,
            },
            "quarantine_by_rule": sink.counts,
        },
        silver_artifacts=(),
        quarantine_artifacts=quarantine_artifacts,
        notes=(
            "CC BY 4.0 source (attribution required; redistribution conditional): inputs "
            "and outputs stay outside Git.",
            "The archive exposes summary indicators only; no dense LPT stream exists and "
            "none is fabricated.",
            "No cross-method correction (Deming, bias, scaling, smoothing) is applied; "
            "method radii are preserved as metadata.",
        ),
    )
    assert_reconciled(receipt)
    receipt_path = write_reconciliation_receipt(settings, receipt, name="gymaware-landmine-release")
    return IngestResult(
        dataset_id=GYMAWARE_DATASET_ID,
        version=version,
        session_id="gymaware-landmine-release",
        source_keys=(discovery.inspection.archive_name,),
        streams=(),
        quarantine_artifacts=quarantine_artifacts,
        reconciliation=receipt,
        receipt_path=receipt_path,
        provider_domain=adapter.domain(),
        quarantine_records=tuple(adapter.counters.quarantined),
        domain=dict(receipt.domain),
        source_metrics=observations,
    )
