"""Read-only access to already-materialized canonical Silver artifacts.

Processors never read raw provider payloads and never import an adapter. They
consume canonical streams that were materialized by an ingestion run and
registered in the control plane. This module is the read boundary:

* the control plane lists exactly which Silver artifacts exist (one row per
  canonical stream, with its checksum);
* loading verifies the file on disk against that registered checksum before a
  single sample is processed, so a processor can never compute over a file that
  silently changed after ingestion;
* the returned :class:`ProcessorInput` carries the verified checksum into the
  processing-run provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pyarrow as pa
import sqlalchemy as sa

from dynamis.config import Settings
from dynamis.processors.runtime import ProcessorInput
from dynamis.storage.metadata import build_metadata
from dynamis.storage.parquet import read_parquet_table

_TABLES = build_metadata().tables
SAMPLE_ARTIFACT_TABLE = _TABLES["sample_artifact"]
SENSOR_STREAM_TABLE = _TABLES["sensor_stream"]
SYNC_ALIGNMENT_TABLE = _TABLES["sync_alignment"]


@dataclass(frozen=True, slots=True)
class SyncPairRef:
    """One declared dataset-scoped alignment between two canonical streams."""

    dataset_id: str
    source_stream_id: str
    target_stream_id: str
    sync_spec_id: str


def list_sync_pairs(connection, *, dataset_id: str) -> tuple[SyncPairRef, ...]:
    """Declared synchronizations in deterministic order (never inferred)."""
    rows = connection.execute(
        sa.select(
            SYNC_ALIGNMENT_TABLE.c.dataset_id,
            SYNC_ALIGNMENT_TABLE.c.source_stream_id,
            SYNC_ALIGNMENT_TABLE.c.target_stream_id,
            SYNC_ALIGNMENT_TABLE.c.sync_spec_id,
        )
        .where(SYNC_ALIGNMENT_TABLE.c.dataset_id == dataset_id)
        .order_by(SYNC_ALIGNMENT_TABLE.c.source_stream_id, SYNC_ALIGNMENT_TABLE.c.target_stream_id)
    ).fetchall()
    return tuple(
        SyncPairRef(
            dataset_id=row.dataset_id,
            source_stream_id=row.source_stream_id,
            target_stream_id=row.target_stream_id,
            sync_spec_id=row.sync_spec_id,
        )
        for row in rows
    )


@dataclass(frozen=True, slots=True)
class SilverStreamRef:
    """One registered canonical Silver stream."""

    dataset_id: str
    session_id: str
    stream_id: str
    modality: str
    trial_id: str | None
    subject_id: str | None
    relative_path: str
    checksum_sha256: str
    row_count: int
    nominal_sampling_rate_hz: float | None
    coordinate_frame_id: str | None
    stream_metadata: dict[str, Any]


def list_silver_streams(
    connection,
    *,
    dataset_id: str,
    modality: str | None = None,
    session_id: str | None = None,
) -> tuple[SilverStreamRef, ...]:
    """List registered Silver streams in deterministic order."""
    query = (
        sa.select(
            SAMPLE_ARTIFACT_TABLE.c.dataset_id,
            SAMPLE_ARTIFACT_TABLE.c.session_id,
            SAMPLE_ARTIFACT_TABLE.c.stream_id,
            SAMPLE_ARTIFACT_TABLE.c.relative_path,
            SAMPLE_ARTIFACT_TABLE.c.checksum_sha256,
            SAMPLE_ARTIFACT_TABLE.c.row_count,
            SENSOR_STREAM_TABLE.c.modality,
            SENSOR_STREAM_TABLE.c.trial_id,
            SENSOR_STREAM_TABLE.c.subject_id,
            SENSOR_STREAM_TABLE.c.nominal_sampling_rate_hz,
            SENSOR_STREAM_TABLE.c.coordinate_frame_id,
            SENSOR_STREAM_TABLE.c.stream_metadata,
        )
        .select_from(
            SAMPLE_ARTIFACT_TABLE.join(
                SENSOR_STREAM_TABLE,
                sa.and_(
                    SENSOR_STREAM_TABLE.c.dataset_id == SAMPLE_ARTIFACT_TABLE.c.dataset_id,
                    SENSOR_STREAM_TABLE.c.stream_id == SAMPLE_ARTIFACT_TABLE.c.stream_id,
                ),
            )
        )
        .where(SAMPLE_ARTIFACT_TABLE.c.dataset_id == dataset_id)
        .order_by(SAMPLE_ARTIFACT_TABLE.c.session_id, SAMPLE_ARTIFACT_TABLE.c.stream_id)
    )
    if modality is not None:
        query = query.where(SENSOR_STREAM_TABLE.c.modality == modality)
    if session_id is not None:
        query = query.where(SAMPLE_ARTIFACT_TABLE.c.session_id == session_id)
    rows = connection.execute(query).fetchall()
    return tuple(
        SilverStreamRef(
            dataset_id=row.dataset_id,
            session_id=row.session_id,
            stream_id=row.stream_id,
            modality=row.modality,
            trial_id=row.trial_id,
            subject_id=row.subject_id,
            relative_path=row.relative_path,
            checksum_sha256=row.checksum_sha256,
            row_count=int(row.row_count),
            nominal_sampling_rate_hz=row.nominal_sampling_rate_hz,
            coordinate_frame_id=row.coordinate_frame_id,
            stream_metadata=dict(row.stream_metadata or {}),
        )
        for row in rows
    )


def load_silver(
    settings: Settings,
    ref: SilverStreamRef,
    *,
    columns: list[str] | None = None,
) -> tuple[pa.Table, ProcessorInput]:
    """Read one Silver stream after verifying its registered checksum.

    ``columns`` projects the Parquet read (for example a pose stream whose full
    table would be tens of millions of rows); the checksum is always computed on
    the complete file, never on the projection.
    """
    from dynamis.storage.atomic import sha256_file

    path = settings.dataset_root / ref.relative_path
    if not path.is_file():
        raise FileNotFoundError(
            f"registered Silver artifact is absent from disk: {ref.relative_path}"
        )
    observed = sha256_file(path)
    if observed != ref.checksum_sha256:
        raise ValueError(
            f"Silver artifact {ref.relative_path} checksum mismatch: registered "
            f"{ref.checksum_sha256[:12]}... but disk holds {observed[:12]}...; refusing to "
            "process a mutated canonical input"
        )
    table = read_parquet_table(path, columns=columns)
    if table.num_rows != ref.row_count:
        raise ValueError(
            f"Silver artifact {ref.relative_path} holds {table.num_rows} rows but the control "
            f"plane registered {ref.row_count}"
        )
    return table, ProcessorInput(
        role=f"silver_{ref.modality}",
        path=path,
        relative_path=ref.relative_path,
        checksum_sha256=observed,
        row_count=table.num_rows,
    )


__all__ = [
    "SilverStreamRef",
    "SyncPairRef",
    "list_silver_streams",
    "list_sync_pairs",
    "load_silver",
]
