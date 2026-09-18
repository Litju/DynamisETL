"""Canonical import of source-provided (provider-computed) scalar metrics.

Some providers distribute trials only as summary indicators --- per-rep peak
velocity, mean power, jump height and so on --- with no temporal signal. Those
values are scientific observations produced by the provider, not by DynamisData.
This module imports them through the existing ``MetricDefinition`` /
``DerivedMetric`` control-plane contract while making the origin unambiguous:

* ``measurement_class`` is ``SOURCE_DERIVED`` --- never ``PIPELINE_DERIVED``;
* the provenance JSON records ``origin = source-provided`` and
  ``imported_by = dynamis`` together with the exact source field, source key and
  Bronze checksum, so no reader can mistake the value for a DynamisData
  computation;
* identity is content-addressed and inserts are idempotent: re-running the same
  ingestion never duplicates a metric row.

No processor in this module computes a scientific value; it only validates and
persists values the source already supplies.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from dynamis.contracts import MeasurementClass, MetricValueKind
from dynamis.contracts.units import assert_si_unit
from dynamis.storage.metadata import build_metadata

_TABLES = build_metadata().tables
DERIVED_METRIC_TABLE = _TABLES["derived_metric"]
METRIC_DEFINITION_TABLE = _TABLES["metric_definition"]

#: This module imports provider-supplied values only; a pipeline computation has
#: its own processors and must never borrow the "source-provided" provenance.
_ALLOWED_MEASUREMENT_CLASSES = frozenset({MeasurementClass.SOURCE_DERIVED})


@dataclass(frozen=True, slots=True)
class SourceMetricObservation:
    """One scalar value supplied by the provider for one canonical trial.

    ``source_field`` and ``source_key`` are mandatory: an imported value without
    a locatable source field is not provenance, it is a rumour.
    """

    dataset_id: str
    metric_id: str
    name: str
    si_unit: str
    measurement_class: MeasurementClass
    value: float
    source_field: str
    source_key: str
    session_id: str | None = None
    subject_id: str | None = None
    trial_id: str | None = None
    stream_id: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        assert_si_unit(self.si_unit, field_name="SourceMetricObservation.si_unit")
        if self.measurement_class not in _ALLOWED_MEASUREMENT_CLASSES:
            raise ValueError(
                "an imported source metric cannot be "
                f"{self.measurement_class.value!r}; use SOURCE_DERIVED"
            )
        if not math.isfinite(self.value):
            raise ValueError(
                f"{self.metric_id}: source metric value must be finite, found {self.value!r}"
            )
        if not self.source_field.strip() or not self.source_key.strip():
            raise ValueError("a source metric observation requires source_field and source_key")

    @property
    def origin_provenance(self) -> dict[str, Any]:
        # Reserved origin keys win over caller provenance: a caller must never be
        # able to overwrite how the value was produced.
        payload = {
            **self.provenance,
            "origin": "source-provided",
            "imported_by": "dynamis",
            "source_field": self.source_field,
            "source_key": self.source_key,
        }
        return payload

    @property
    def derived_metric_id(self) -> str:
        identity = json.dumps(
            {
                "dataset_id": self.dataset_id,
                "metric_id": self.metric_id,
                "session_id": self.session_id,
                "subject_id": self.subject_id,
                "trial_id": self.trial_id,
                "stream_id": self.stream_id,
                "source_field": self.source_field,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return f"dm-{hashlib.sha256(identity).hexdigest()[:32]}"


def _assert_existing_definitions_match(connection, definitions: dict[str, dict[str, Any]]) -> None:
    """Refuse an import whose metric identity already means something else.

    ``ON CONFLICT DO NOTHING`` protects a definition from being overwritten; it
    would also silently accept a different unit or name under the same global
    metric id. Every existing row touched by this batch is therefore compared
    against the incoming definition before anything is inserted.
    """
    if not definitions:
        return
    existing_rows = connection.execute(
        sa.select(
            METRIC_DEFINITION_TABLE.c.metric_id,
            METRIC_DEFINITION_TABLE.c.name,
            METRIC_DEFINITION_TABLE.c.si_unit,
            METRIC_DEFINITION_TABLE.c.measurement_class,
            METRIC_DEFINITION_TABLE.c.value_kind,
        ).where(METRIC_DEFINITION_TABLE.c.metric_id.in_(sorted(definitions)))
    ).fetchall()
    for row in existing_rows:
        incoming = definitions[row.metric_id]
        conflicts = [
            field
            for field, value in (
                ("name", row.name),
                ("si_unit", row.si_unit),
                ("measurement_class", row.measurement_class),
                ("value_kind", row.value_kind),
            )
            if value != incoming[field]
        ]
        if conflicts:
            raise ValueError(
                f"metric definition {row.metric_id!r} already exists with different "
                f"{', '.join(conflicts)}; refusing to reuse a scientific definition"
            )


def persist_source_metrics(
    connection,
    *,
    dataset_id: str,
    run_id: str,
    observations: tuple[SourceMetricObservation, ...],
    input_checksums: tuple[str, ...],
    computed_at: datetime,
) -> dict[str, int]:
    """Idempotently import source-derived metric definitions and values."""
    written = {"metric_definition": 0, "derived_metric": 0}
    if not observations:
        return written
    usable_checksums = [checksum for checksum in input_checksums if len(checksum) == 64]
    if not usable_checksums:
        raise ValueError("source-derived metrics must cite at least one verified Bronze checksum")
    mismatched_datasets = sorted(
        {
            observation.dataset_id
            for observation in observations
            if observation.dataset_id != dataset_id
        }
    )
    if mismatched_datasets:
        raise ValueError(
            f"observations declare dataset(s) {mismatched_datasets} but the run is bound to "
            f"{dataset_id!r}; dataset identity must never be mixed"
        )
    definitions: dict[str, dict[str, Any]] = {}
    for observation in observations:
        existing = definitions.get(observation.metric_id)
        definition = {
            "metric_id": observation.metric_id,
            "name": observation.name,
            "si_unit": observation.si_unit,
            "measurement_class": observation.measurement_class.value,
            "value_kind": MetricValueKind.SCALAR.value,
            "description": (
                "Value supplied by the external source; imported by DynamisData without "
                "recomputation."
            ),
            "algorithm_id": None,
        }
        if existing is not None and existing != definition:
            raise ValueError(f"conflicting definitions for metric {observation.metric_id!r}")
        definitions[observation.metric_id] = definition
    _assert_existing_definitions_match(connection, definitions)
    inserted_definitions = connection.execute(
        pg_insert(METRIC_DEFINITION_TABLE)
        .values(list(definitions.values()))
        .on_conflict_do_nothing(index_elements=["metric_id"])
        .returning(METRIC_DEFINITION_TABLE.c.metric_id)
    ).fetchall()
    written["metric_definition"] = len(inserted_definitions)
    rows = [
        {
            "derived_metric_id": observation.derived_metric_id,
            "dataset_id": dataset_id,
            "metric_id": observation.metric_id,
            "run_id": run_id,
            "subject_id": observation.subject_id,
            "session_id": observation.session_id,
            "trial_id": observation.trial_id,
            "stream_id": observation.stream_id,
            "si_unit": observation.si_unit,
            "measurement_class": observation.measurement_class.value,
            "value_num": float(observation.value),
            # SQL NULL, not JSON 'null': the CHECK constraint distinguishes the
            # scalar form from the JSON form by SQL NULL-ness.
            "value_json": sa.null(),
            "computed_at": computed_at,
            "input_checksums": usable_checksums,
            "provenance": observation.origin_provenance,
        }
        for observation in observations
    ]
    inserted_metrics = connection.execute(
        pg_insert(DERIVED_METRIC_TABLE)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["derived_metric_id"])
        .returning(DERIVED_METRIC_TABLE.c.derived_metric_id)
    ).fetchall()
    written["derived_metric"] = len(inserted_metrics)
    return written


def source_metric_table_names() -> tuple[str, ...]:
    """Tables this module writes, for persistence tests and receipts."""
    return ("metric_definition", "derived_metric")


__all__ = [
    "SourceMetricObservation",
    "persist_source_metrics",
    "source_metric_table_names",
]
