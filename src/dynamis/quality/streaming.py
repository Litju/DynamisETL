"""Streaming restatement of the canonical contract checks.

The table-oriented checks in :mod:`dynamis.quality.checks` are the authority for
CI fixtures, but a 3.36 M-row tracking stream must not be loaded into memory to
be validated. This module accumulates the same rule outcomes batch by batch,
using the same kernels (strict/non-decreasing) and the same rule identifiers; a
test proves it agrees with :func:`dynamis.quality.checks.validate` on synthetic
tables.
"""

from __future__ import annotations

from collections import Counter

import pyarrow as pa

from dynamis.contracts.enums import MeasurementClass
from dynamis.contracts.schemas import (
    MONOTONICITY_STRICT,
    contract_of,
    coordinate_frame_required,
    is_dense,
    subject_required,
    time_monotonicity,
)
from dynamis.quality import arrow_kernels as kernels
from dynamis.quality.checks import (
    Violation,
    check_schema_conformance,
    check_units,
)


class StreamingValidator:
    """Validates a bounded batch stream against one canonical schema."""

    def __init__(self, schema: pa.Schema, *, require_zero_based: bool = True) -> None:
        self._schema = schema
        self._require_zero_based = require_zero_based
        self._violations: list[Violation] = []
        self._initialized = False
        self._row_count = 0
        self.null_counts: Counter[str] = Counter()
        self._identity: dict[str, set[str]] = {
            "dataset_id": set(),
            "session_id": set(),
            "stream_id": set(),
        }
        self._identity_nulls: Counter[str] = Counter()
        self._subject_nulls = 0
        self._clock_nulls = 0
        self._sync_nulls = 0
        self._frame_nulls = 0
        self._clock_values: set[str] = set()
        self._sync_values: set[str] = set()
        self._frame_values: set[str] = set()
        self._class_nulls = 0
        self._class_values: set[str] = set()
        self._previous_sample_index: int | None = None
        self._previous_t_rel_ns: int | None = None
        self._first_sample_index: int | None = None
        self.t_rel_min_ns: int | None = None
        self.t_rel_max_ns: int | None = None

    @property
    def row_count(self) -> int:
        return self._row_count

    def observe(self, batch: pa.RecordBatch) -> None:
        if not self._initialized:
            table = pa.Table.from_batches([batch]).slice(0, 0)
            self._violations.extend(check_schema_conformance(table, self._schema))
            self._violations.extend(check_units(table, self._schema))
            self._initialized = True
        elif batch.schema.names != self._schema.names:
            self._violations.append(
                Violation(
                    rule="schema.field.missing",
                    detail="batch schema drifted from the frozen canonical schema",
                    evidence={"observed": batch.schema.names},
                )
            )
        self._row_count += batch.num_rows
        for name in batch.schema.names:
            self.null_counts[name] += batch.column(name).null_count
        self._observe_identity(batch)
        self._observe_authorities(batch)
        self._observe_measurement_class(batch)
        self._observe_time(batch)

    def _observe_identity(self, batch: pa.RecordBatch) -> None:
        for name, collected in self._identity.items():
            if name not in batch.schema.names:
                continue
            column = batch.column(name)
            self._identity_nulls[name] += column.null_count
            collected.update(
                str(value) for value in kernels.distinct_values(column) if value is not None
            )
        if subject_required(self._schema) and "subject_id" in batch.schema.names:
            self._subject_nulls += batch.column("subject_id").null_count

    def _observe_authorities(self, batch: pa.RecordBatch) -> None:
        for name in ("clock_id", "synchronization_spec_id", "coordinate_frame_id"):
            if name not in batch.schema.names:
                continue
            column = batch.column(name)
            null_count = column.null_count
            values = {str(value) for value in kernels.distinct_values(column)}
            if name == "clock_id":
                self._clock_nulls += null_count
                self._clock_values.update(values)
            elif name == "synchronization_spec_id":
                self._sync_nulls += null_count
                self._sync_values.update(values)
            else:
                self._frame_nulls += null_count
                self._frame_values.update(values)

    def _observe_measurement_class(self, batch: pa.RecordBatch) -> None:
        if "measurement_class" not in batch.schema.names:
            return
        column = batch.column("measurement_class")
        self._class_nulls += column.null_count
        self._class_values.update(str(v) for v in kernels.distinct_values(column))

    def _observe_time(self, batch: pa.RecordBatch) -> None:
        if batch.num_rows == 0:
            return
        if "t_rel_ns" in batch.schema.names and not batch.column("t_rel_ns").null_count:
            column = batch.column("t_rel_ns")
            first = int(column[0].as_py())
            last = int(column[-1].as_py())
            self.t_rel_min_ns = (
                first if self.t_rel_min_ns is None else min(self.t_rel_min_ns, first)
            )
            self.t_rel_max_ns = last if self.t_rel_max_ns is None else max(self.t_rel_max_ns, last)
        if not is_dense(self._schema):
            return
        strictness = time_monotonicity(self._schema)
        for name in ("sample_index", "t_rel_ns"):
            if name not in batch.schema.names:
                continue
            column = batch.column(name)
            if column.null_count:
                self._violations.append(
                    Violation(
                        rule="time.null",
                        detail=f"{name} must never be null for a dense stream",
                        evidence={"column": name, "null_count": column.null_count},
                    )
                )
                continue
            first = int(column[0].as_py())
            last = int(column[-1].as_py())
            if name == "sample_index":
                self._first_sample_index = (
                    first if self._first_sample_index is None else self._first_sample_index
                )
                if self._previous_sample_index is not None and first <= self._previous_sample_index:
                    self._violations.append(
                        Violation(
                            rule="time.monotonic",
                            detail="sample_index must be strictly increasing within a stream",
                            evidence={"column": name},
                        )
                    )
                self._previous_sample_index = last
            else:
                if self._previous_t_rel_ns is not None:
                    boundary_ok = (
                        first > self._previous_t_rel_ns
                        if strictness == MONOTONICITY_STRICT
                        else first >= self._previous_t_rel_ns
                    )
                    if not boundary_ok:
                        expected = (
                            "strictly increasing"
                            if strictness == MONOTONICITY_STRICT
                            else "non-decreasing"
                        )
                        self._violations.append(
                            Violation(
                                rule="time.monotonic",
                                detail=f"{name} must be {expected} within a stream",
                                evidence={"column": name, "monotonicity": strictness},
                            )
                        )
                self._previous_t_rel_ns = last
            if batch.num_rows > 1:
                ordered = (
                    kernels.is_strictly_increasing(column)
                    if name == "sample_index" or strictness == MONOTONICITY_STRICT
                    else kernels.is_non_decreasing(column)
                )
                if not ordered:
                    expected = (
                        "strictly increasing"
                        if name == "sample_index" or strictness == MONOTONICITY_STRICT
                        else "non-decreasing"
                    )
                    self._violations.append(
                        Violation(
                            rule="time.monotonic",
                            detail=f"{name} must be {expected} within a stream",
                            evidence={"column": name, "monotonicity": strictness},
                        )
                    )

    def finish(self) -> tuple[Violation, ...]:
        """Accumulated violations so far (the caller decides when to enforce)."""
        violations = list(self._violations)
        for name, values in self._identity.items():
            if self._identity_nulls[name]:
                violations.append(
                    Violation(
                        rule="identity.null",
                        detail=f"{name} must never be null in a canonical file",
                        evidence={"column": name, "null_count": self._identity_nulls[name]},
                    )
                )
            if len(values) > 1:
                violations.append(
                    Violation(
                        rule="identity.multiple",
                        detail=(
                            f"a canonical file must contain exactly one {name}; found {len(values)}"
                        ),
                        evidence={"column": name, "distinct": sorted(values)},
                    )
                )
        if self._subject_nulls:
            violations.append(
                Violation(
                    rule="identity.subject_required",
                    detail=(
                        f"contract {contract_of(self._schema)!r} requires subject identity "
                        "on every row"
                    ),
                    evidence={"null_subject_rows": self._subject_nulls},
                )
            )
        if self._clock_nulls:
            violations.append(
                Violation(
                    rule="authority.null",
                    detail="clock_id must be declared for every sample",
                    evidence={"null_count": self._clock_nulls},
                )
            )
        if len(self._clock_values) > 1:
            violations.append(
                Violation(
                    rule="authority.multiple",
                    detail="one canonical file must declare exactly one clock_id",
                    evidence={"distinct": sorted(self._clock_values)},
                )
            )
        if self._sync_nulls:
            violations.append(
                Violation(
                    rule="authority.null",
                    detail="synchronization_spec_id must be declared for every sample",
                    evidence={"null_count": self._sync_nulls},
                )
            )
        if len(self._sync_values) > 1:
            violations.append(
                Violation(
                    rule="authority.multiple",
                    detail="one canonical file must declare exactly one synchronization_spec_id",
                    evidence={"distinct": sorted(self._sync_values)},
                )
            )
        if coordinate_frame_required(self._schema):
            if self._frame_nulls:
                violations.append(
                    Violation(
                        rule="authority.frame_required",
                        detail="modality requires an explicit coordinate frame on every sample",
                        evidence={"null_rows": self._frame_nulls},
                    )
                )
            if len(self._frame_values) > 1:
                violations.append(
                    Violation(
                        rule="authority.frame_multiple",
                        detail="one canonical file must not mix coordinate frames",
                        evidence={"distinct": sorted(self._frame_values)},
                    )
                )
        allowed = {member.value for member in MeasurementClass}
        unknown = sorted(self._class_values - allowed - {""})
        if unknown:
            violations.append(
                Violation(
                    rule="measurement_class.illegal",
                    detail=f"measurement_class values outside the closed vocabulary: {unknown}",
                    evidence={"observed": sorted(self._class_values)},
                )
            )
        if self._class_nulls:
            violations.append(
                Violation(
                    rule="measurement_class.null",
                    detail="measurement_class must be present on every row",
                )
            )
        if self._require_zero_based and is_dense(self._schema):
            if self._row_count and self._first_sample_index != 0:
                violations.append(
                    Violation(
                        rule="time.zero_based",
                        detail=(
                            "sample_index must start at 0 for a canonical stream; "
                            f"found {self._first_sample_index}"
                        ),
                        evidence={"first_sample_index": self._first_sample_index},
                    )
                )
            if self._row_count and self._previous_sample_index != self._row_count - 1:
                violations.append(
                    Violation(
                        rule="time.contiguous",
                        detail=(
                            "sample_index must be contiguous from 0; last index "
                            f"{self._previous_sample_index} with {self._row_count} rows"
                        ),
                        evidence={
                            "last_sample_index": self._previous_sample_index,
                            "rows": self._row_count,
                        },
                    )
                )
        return tuple(violations)
