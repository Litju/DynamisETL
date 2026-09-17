"""Source-to-canonical reconciliation receipts.

The hard gate: for every provider the receipt proves the row-count relationship

    source = accepted canonical + quarantined + explicitly documented non-data records

and records schema/units/frame/time/identity/duplicate results. The receipt is
written as JSON under the external cache layer; the numbers in it are also what
the PR and the Linear completion receipt report.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from dynamis.config import Settings
from dynamis.storage.atomic import atomic_write_text
from dynamis.storage.paths import receipt_path


@dataclass(frozen=True, slots=True)
class StreamReconciliation:
    stream_id: str
    modality: str
    subject_id: str | None
    trial_id: str | None
    source_records: int
    canonical_rows: int
    quarantined_rows: int
    ignored_records: int
    ignored_reasons: dict[str, int] = field(default_factory=dict)
    source_time_min: str | None = None
    source_time_max: str | None = None
    canonical_time_min_ns: int | None = None
    canonical_time_max_ns: int | None = None
    null_counts: dict[str, int] = field(default_factory=dict)
    duplicate_identities: int = 0
    duplicate_timestamps: int = 0
    schema_valid: bool = True
    units_valid: bool = True
    coordinate_frame_id: str | None = None
    checks: dict[str, Any] = field(default_factory=dict)

    @property
    def balances(self) -> bool:
        return (
            self.canonical_rows + self.quarantined_rows + self.ignored_records
            == self.source_records
            and self.schema_valid
            and self.units_valid
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "stream_id": self.stream_id,
            "modality": self.modality,
            "subject_id": self.subject_id,
            "trial_id": self.trial_id,
            "source_records": self.source_records,
            "canonical_rows": self.canonical_rows,
            "quarantined_rows": self.quarantined_rows,
            "ignored_records": self.ignored_records,
            "ignored_reasons": self.ignored_reasons,
            "source_time_min": self.source_time_min,
            "source_time_max": self.source_time_max,
            "canonical_time_min_ns": self.canonical_time_min_ns,
            "canonical_time_max_ns": self.canonical_time_max_ns,
            "null_counts": self.null_counts,
            "duplicate_identities": self.duplicate_identities,
            "duplicate_timestamps": self.duplicate_timestamps,
            "schema_valid": self.schema_valid,
            "units_valid": self.units_valid,
            "coordinate_frame_id": self.coordinate_frame_id,
            "checks": self.checks,
            "balances": self.balances,
        }


@dataclass(frozen=True, slots=True)
class ReconciliationReceipt:
    dataset_id: str
    version: str
    session_id: str
    source_keys: tuple[str, ...]
    streams: tuple[StreamReconciliation, ...]
    domain: dict[str, Any] = field(default_factory=dict)
    silver_artifacts: tuple[dict[str, Any], ...] = ()
    quarantine_artifacts: tuple[dict[str, Any], ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def all_balanced(self) -> bool:
        return all(stream.balances for stream in self.streams)

    @property
    def explained_rows(self) -> int:
        return sum(
            stream.canonical_rows + stream.quarantined_rows + stream.ignored_records
            for stream in self.streams
        )

    @property
    def source_rows(self) -> int:
        return sum(stream.source_records for stream in self.streams)

    @property
    def canonical_rows(self) -> int:
        return sum(stream.canonical_rows for stream in self.streams)

    @property
    def quarantined_rows(self) -> int:
        return sum(stream.quarantined_rows for stream in self.streams)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "version": self.version,
            "session_id": self.session_id,
            "source_keys": list(self.source_keys),
            "source_rows": self.source_rows,
            "canonical_rows": self.canonical_rows,
            "quarantined_rows": self.quarantined_rows,
            "explained_rows": self.explained_rows,
            "all_balanced": self.all_balanced,
            "streams": [stream.to_dict() for stream in self.streams],
            "domain": self.domain,
            "silver_artifacts": list(self.silver_artifacts),
            "quarantine_artifacts": list(self.quarantine_artifacts),
            "notes": list(self.notes),
        }


def write_reconciliation_receipt(
    settings: Settings,
    receipt: ReconciliationReceipt,
    *,
    name: str,
) -> str:
    path = receipt_path(
        settings,
        dataset_id=receipt.dataset_id,
        kind="reconciliation",
        name=name,
    )
    atomic_write_text(
        path,
        json.dumps(receipt.to_dict(), indent=2, sort_keys=True) + "\n",
    )
    return path.as_posix()


def assert_reconciled(receipt: ReconciliationReceipt) -> None:
    """Hard gate: refuse to publish outputs for an unexplained imbalance."""
    if not receipt.all_balanced:
        offenders = [stream.stream_id for stream in receipt.streams if not stream.balances]
        raise AssertionError(
            "reconciliation is not balanced for stream(s): "
            + ", ".join(offenders)
            + f" (source={receipt.source_rows} explained={receipt.explained_rows})"
        )
