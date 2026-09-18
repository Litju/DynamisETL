"""Streaming restatement of the canonical contract checks.

The table-oriented checks in :mod:`dynamis.quality.checks` are the authority for
CI fixtures, but a 3.36 M-row tracking stream must not be loaded into memory to
be validated. This module accumulates the same rule outcomes batch by batch,
using the same kernels (strict/non-decreasing) and the same rule identifiers; a
test proves it agrees with :func:`dynamis.quality.checks.validate` on synthetic
tables.

One deliberate difference: the streaming validator may report the same rule once
per offending batch (and once at a batch boundary), where the table authority
reports it once for the whole column. The rule vocabulary and verdicts are
identical; only the multiplicity differs.
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
    FORCE_BODY_WEIGHT_RATIO_FIELD,
    FORCE_NEWTON_FIELDS,
    POSE_AVAILABILITY_FIELD,
    POSE_COORDINATE_FIELDS,
    POSE_ERROR_FIELD,
    Violation,
    check_schema_conformance,
    check_units,
    force_payload_fields,
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
        self._force_payload_fields = force_payload_fields(schema)
        self._pose_payload = (
            contract_of(schema) == "pose_joint_sample"
            and POSE_AVAILABILITY_FIELD in schema.names
            and all(name in schema.names for name in POSE_COORDINATE_FIELDS)
        )
        self.t_rel_min_ns: int | None = None
        self.t_rel_max_ns: int | None = None

    @property
    def row_count(self) -> int:
        return self._row_count

    def observe(self, batch: pa.RecordBatch) -> None:
        if batch.num_rows == 0:
            # An empty batch carries no evidence; treating it as a stream prefix
            # would report "no identity/authority observed" against a stream that
            # simply has not started yet.
            return
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
        self._observe_payload_completeness(batch)
        self._observe_pose_payload(batch)
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

    def _observe_payload_completeness(self, batch: pa.RecordBatch) -> None:
        """Force rows must carry a newton component or the explicit BW ratio."""
        if not self._force_payload_fields:
            return
        names = set(batch.schema.names)
        newton_fields = [name for name in FORCE_NEWTON_FIELDS if name in names]
        ratio_present = FORCE_BODY_WEIGHT_RATIO_FIELD in names
        newton_valid = (
            kernels.any_non_null([batch.column(name) for name in newton_fields])
            if newton_fields
            else None
        )
        ratio_valid = (
            kernels.any_non_null([batch.column(FORCE_BODY_WEIGHT_RATIO_FIELD)])
            if ratio_present
            else None
        )
        if newton_valid is None and ratio_valid is None:
            return
        if newton_valid is None:
            assert ratio_valid is not None
            valid = ratio_valid
            both: pa.Array | None = None
        elif ratio_valid is None:
            valid = newton_valid
            both = None
        else:
            valid = kernels.or_(newton_valid, ratio_valid)
            both = kernels.and_(newton_valid, ratio_valid)
        valid_rows = kernels.count_true(valid)
        if valid_rows != batch.num_rows:
            self._violations.append(
                Violation(
                    rule="force.payload.missing",
                    detail=(
                        "a force sample must provide at least one newton component or "
                        "force_z_body_weight_ratio"
                    ),
                    evidence={
                        "rows_without_payload": batch.num_rows - valid_rows,
                        "rows": batch.num_rows,
                    },
                )
            )
        if both is not None:
            both_rows = kernels.count_true(both)
            if both_rows:
                self._violations.append(
                    Violation(
                        rule="force.payload.ambiguous",
                        detail=(
                            "a force sample must not carry newton components and "
                            "force_z_body_weight_ratio at the same time"
                        ),
                        evidence={
                            "rows_with_both_representations": both_rows,
                            "rows": batch.num_rows,
                        },
                    )
                )

    def _observe_pose_payload(self, batch: pa.RecordBatch) -> None:
        """Availability gates pose coordinates batch by batch (same rules as tables)."""
        if not self._pose_payload:
            return
        names = set(batch.schema.names)
        expected_types = {
            POSE_AVAILABILITY_FIELD: pa.bool_(),
            **{name: pa.float64() for name in POSE_COORDINATE_FIELDS},
        }
        if POSE_ERROR_FIELD in names:
            expected_types[POSE_ERROR_FIELD] = pa.float64()
        if any(name not in names for name in expected_types):
            return
        if any(
            batch.schema.field(name).type != expected for name, expected in expected_types.items()
        ):
            return
        availability = batch.column(POSE_AVAILABILITY_FIELD)
        if availability.null_count:
            self._violations.append(
                Violation(
                    rule="pose.availability.null",
                    detail="every pose row must declare whether its joint is available",
                    evidence={"null_rows": availability.null_count, "rows": batch.num_rows},
                )
            )
        observed = kernels.fill_null_false(availability)
        coordinates = [batch.column(name) for name in POSE_COORDINATE_FIELDS]
        observed_valid = kernels.all_valid(coordinates)
        missing_coordinates = kernels.count_true(
            kernels.and_(observed, kernels.invert(observed_valid))
        )
        if missing_coordinates:
            self._violations.append(
                Violation(
                    rule="pose.payload.missing_coordinates",
                    detail=(
                        "an available joint must carry finite x/y/z; missing joints are "
                        "declared unavailable instead of imputed"
                    ),
                    evidence={
                        "rows_without_coordinates": missing_coordinates,
                        "rows": batch.num_rows,
                    },
                )
            )
        presented = kernels.any_non_null(coordinates)
        unavailable_with_coordinates = kernels.count_true(
            kernels.and_(kernels.invert(observed), presented)
        )
        if unavailable_with_coordinates:
            self._violations.append(
                Violation(
                    rule="pose.payload.unexpected_coordinates",
                    detail="an unavailable joint must not carry coordinates",
                    evidence={
                        "rows_with_coordinates": unavailable_with_coordinates,
                        "rows": batch.num_rows,
                    },
                )
            )
        finite = kernels.is_finite(coordinates[0])
        for column in coordinates[1:]:
            finite = kernels.and_(finite, kernels.is_finite(column))
        non_finite = kernels.count_true(observed) - kernels.count_true(
            kernels.and_(observed, finite)
        )
        if non_finite:
            self._violations.append(
                Violation(
                    rule="pose.payload.non_finite",
                    detail="an available joint must carry finite coordinates",
                    evidence={"non_finite_rows": non_finite, "rows": batch.num_rows},
                )
            )
        if POSE_ERROR_FIELD in names:
            error = batch.column(POSE_ERROR_FIELD)
            valid_error = kernels.and_(kernels.is_finite(error), kernels.greater_equal(error, 0))
            invalid_error = kernels.count_true(
                kernels.and_(kernels.any_non_null([error]), kernels.invert(valid_error))
            )
            if invalid_error:
                self._violations.append(
                    Violation(
                        rule="pose.error.invalid",
                        detail="a provided pose error estimate must be finite and non-negative",
                        evidence={"invalid_rows": invalid_error, "rows": batch.num_rows},
                    )
                )

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
        """Accumulated violations for the prefix observed so far.

        Aggregate checks (identity, authorities, measurement class, zero-based
        time) only make sense once at least one row exists; an empty stream is
        reported by the caller's own emptiness contract, not as a false
        "multiple identities" finding.
        """
        violations = list(self._violations)
        if self._row_count == 0:
            return tuple(violations)
        for name, values in self._identity.items():
            if self._identity_nulls[name]:
                violations.append(
                    Violation(
                        rule="identity.null",
                        detail=f"{name} must never be null in a canonical file",
                        evidence={"column": name, "null_count": self._identity_nulls[name]},
                    )
                )
            if len(values) != 1:
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
        if len(self._clock_values) != 1:
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
        if len(self._sync_values) != 1:
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
            if len(self._frame_values) != 1:
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
