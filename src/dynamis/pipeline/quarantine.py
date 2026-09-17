"""Quarantine: malformed or scientifically invalid records never disappear.

Every rule has an explicit identifier. Quarantined evidence is written to the
external ``quarantine/`` layer as Parquet+Zstd, partitioned by rule, with enough
source context to diagnose the offending record without duplicating whole source
files.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import pyarrow as pa

from dynamis.config import Settings
from dynamis.contracts import Severity
from dynamis.storage.parquet import write_parquet_atomic
from dynamis.storage.paths import quarantine_parquet_path

#: Explicit rule identifiers. A rule may only quarantine what it names.
RULE_REQUIRED_FIELD_NULL = "required_field_null"
RULE_TIMESTAMP_UNPARSABLE = "timestamp_unparsable"
RULE_TIME_OUT_OF_RANGE = "time_out_of_range"
RULE_COORDINATE_OUT_OF_RANGE = "coordinate_out_of_range"
RULE_COORDINATE_MISSING = "coordinate_missing"
RULE_FRAME_TIME_MISMATCH = "frame_time_mismatch"
RULE_DUPLICATE_FRAME = "duplicate_frame"
RULE_UNKNOWN_PARTICIPANT = "unknown_participant"
RULE_SCHEMA_FAILURE = "schema_failure"

KNOWN_RULES = frozenset(
    {
        RULE_REQUIRED_FIELD_NULL,
        RULE_TIMESTAMP_UNPARSABLE,
        RULE_TIME_OUT_OF_RANGE,
        RULE_COORDINATE_OUT_OF_RANGE,
        RULE_COORDINATE_MISSING,
        RULE_FRAME_TIME_MISMATCH,
        RULE_DUPLICATE_FRAME,
        RULE_UNKNOWN_PARTICIPANT,
        RULE_SCHEMA_FAILURE,
    }
)

QUARANTINE_SCHEMA = pa.schema(
    [
        pa.field("rule", pa.string()),
        pa.field("severity", pa.string()),
        pa.field("dataset_id", pa.string()),
        pa.field("session_id", pa.string()),
        pa.field("stream_id", pa.string(), nullable=True),
        pa.field("subject_id", pa.string(), nullable=True),
        pa.field("source_record_id", pa.string(), nullable=True),
        pa.field("source_time", pa.string(), nullable=True),
        pa.field("detail", pa.string()),
        pa.field("evidence_json", pa.string()),
    ]
)


@dataclass(frozen=True, slots=True)
class QuarantinedRecord:
    rule: str
    detail: str
    dataset_id: str
    session_id: str
    stream_id: str | None = None
    subject_id: str | None = None
    source_record_id: str | None = None
    source_time: str | None = None
    severity: Severity = Severity.ERROR
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.rule not in KNOWN_RULES:
            raise ValueError(f"unknown quarantine rule id {self.rule!r}")

    def to_row(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "severity": self.severity.value,
            "dataset_id": self.dataset_id,
            "session_id": self.session_id,
            "stream_id": self.stream_id,
            "subject_id": self.subject_id,
            "source_record_id": self.source_record_id,
            "source_time": self.source_time,
            "detail": self.detail,
            "evidence_json": json.dumps(self.evidence, sort_keys=True, separators=(",", ":")),
        }


@dataclass(slots=True)
class QuarantineSink:
    """Accumulates quarantined records and materializes one file per rule.

    Records are buffered in memory by rule. Quarantine volumes are expected to
    be small; a violation of that expectation is itself a finding reported in
    the reconciliation receipt.
    """

    settings: Settings
    _records: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def add(self, record: QuarantinedRecord) -> None:
        self._records.setdefault(record.rule, []).append(record.to_row())

    def add_many(self, records: Iterable[QuarantinedRecord]) -> None:
        for record in records:
            self.add(record)

    @property
    def counts(self) -> dict[str, int]:
        return {rule: len(rows) for rule, rows in sorted(self._records.items())}

    @property
    def total(self) -> int:
        return sum(len(rows) for rows in self._records.values())

    def materialize(self, *, name: str) -> list[dict[str, Any]]:
        """Write one Parquet file per rule and return artifact descriptors."""
        written: list[dict[str, Any]] = []
        for rule, rows in sorted(self._records.items()):
            if not rows:
                continue
            dataset_id = str(rows[0]["dataset_id"])
            path = quarantine_parquet_path(
                self.settings, dataset_id=dataset_id, rule=rule, name=name
            )
            table = pa.Table.from_pylist(rows, schema=QUARANTINE_SCHEMA)
            artifact = write_parquet_atomic(table, path, relative_to=self.settings.dataset_root)
            written.append(
                {
                    "rule": rule,
                    "relative_path": artifact.relative_path,
                    "row_count": artifact.row_count,
                    "byte_size": artifact.byte_size,
                    "checksum_sha256": artifact.checksum_sha256,
                    "partition": {"dataset_id": dataset_id, "rule": rule},
                    "schema_fingerprint": artifact.schema_fingerprint,
                }
            )
        return written
