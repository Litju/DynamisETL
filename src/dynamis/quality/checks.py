"""Deterministic scientific quality checks over canonical Arrow tables.

These checks are the executable acceptance surface for CI: schema conformance,
SI units, monotonic time, deterministic identity, single-frame/single-clock
declarations and measurement-class legality. A violation is never silently
dropped: it is reported with rule, severity, location and evidence, and can be
projected into a :class:`~dynamis.contracts.domain.QualityIssue` for quarantine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pyarrow as pa

from dynamis.contracts.domain import QualityIssue
from dynamis.contracts.enums import MeasurementClass, Modality, Severity
from dynamis.contracts.schemas import (
    CONTRACT_KEY,
    MEASUREMENT_CLASS_KEY,
    MODALITY_KEY,
    MONOTONICITY_STRICT,
    SCHEMA_VERSION_KEY,
    UNITS_KEY,
    contract_of,
    coordinate_frame_required,
    get_schema,
    is_dense,
    si_unit_of,
    subject_required,
    time_monotonicity,
)
from dynamis.contracts.units import is_si_unit
from dynamis.quality import arrow_kernels as kernels


@dataclass(frozen=True, slots=True)
class Violation:
    rule: str
    detail: str
    severity: Severity = Severity.ERROR
    stream_id: str | None = None
    sample_index: int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


class QualityError(ValueError):
    """Raised when a canonical table violates one or more contract rules."""

    def __init__(self, violations: tuple[Violation, ...]) -> None:
        self.violations = violations
        summary = "; ".join(f"{item.rule}: {item.detail}" for item in violations[:5])
        extra = "" if len(violations) <= 5 else f" (+{len(violations) - 5} more)"
        super().__init__(f"{len(violations)} quality violation(s): {summary}{extra}")


def _distinct_values(table: pa.Table, name: str) -> list[Any]:
    if name not in table.column_names:
        return []
    return kernels.distinct_values(table.column(name))


def check_schema_metadata(schema: pa.Schema) -> tuple[Violation, ...]:
    """Schema-level provenance must be complete for a canonical modality schema."""
    violations: list[Violation] = []
    metadata = schema.metadata or {}
    for key, label in (
        (SCHEMA_VERSION_KEY, "schema_version"),
        (CONTRACT_KEY, "contract"),
        (MODALITY_KEY, "modality"),
        (UNITS_KEY, "units"),
        (MEASUREMENT_CLASS_KEY, "measurement_class"),
    ):
        if key not in metadata:
            violations.append(
                Violation(
                    rule="schema.metadata.missing",
                    detail=f"schema metadata key {label!r} is absent",
                    evidence={"key": label},
                )
            )
    if metadata.get(UNITS_KEY) not in {b"SI", None}:
        violations.append(
            Violation(
                rule="schema.metadata.units",
                detail="canonical schemas must declare SI units",
                evidence={"units": str(metadata.get(UNITS_KEY))},
            )
        )
    return tuple(violations)


def check_schema_conformance(table: pa.Table, schema: pa.Schema) -> tuple[Violation, ...]:
    """Field names, types, nullability and SI metadata must match exactly."""
    violations: list[Violation] = list(check_schema_metadata(table.schema))
    expected = {item.name: item for item in schema}
    actual = {item.name: item for item in table.schema}
    for name in expected:
        if name not in actual:
            violations.append(
                Violation(
                    rule="schema.field.missing",
                    detail=f"required column {name!r} is absent",
                    evidence={"column": name},
                )
            )
    for name in actual:
        if name not in expected:
            violations.append(
                Violation(
                    rule="schema.field.unexpected",
                    detail=f"column {name!r} is not part of the canonical contract",
                    evidence={"column": name},
                )
            )
    for name, expected_field in expected.items():
        actual_field = actual.get(name)
        if actual_field is None:
            continue
        if actual_field.type != expected_field.type:
            violations.append(
                Violation(
                    rule="schema.field.type",
                    detail=(
                        f"column {name!r} has type {actual_field.type} but the contract "
                        f"requires {expected_field.type}"
                    ),
                    evidence={"column": name, "expected": str(expected_field.type)},
                )
            )
        if actual_field.nullable != expected_field.nullable:
            violations.append(
                Violation(
                    rule="schema.field.nullability",
                    detail=(
                        f"column {name!r} nullable={actual_field.nullable} but the contract "
                        f"requires nullable={expected_field.nullable}"
                    ),
                    evidence={"column": name},
                )
            )
    return tuple(violations)


def check_units(table: pa.Table, schema: pa.Schema) -> tuple[Violation, ...]:
    """Every declared unit must be canonical SI and attached to a numeric column."""
    violations: list[Violation] = []
    for name in table.column_names:
        field_ = schema.field(name) if name in schema.names else table.schema.field(name)
        unit = si_unit_of(field_)
        if unit is None:
            continue
        if not is_si_unit(unit):
            violations.append(
                Violation(
                    rule="units.not_si",
                    detail=f"column {name!r} declares non-SI unit {unit!r}",
                    evidence={"column": name, "unit": unit},
                )
            )
        if not (pa.types.is_floating(field_.type) or pa.types.is_integer(field_.type)):
            violations.append(
                Violation(
                    rule="units.non_numeric",
                    detail=f"column {name!r} declares unit {unit!r} but is not numeric",
                    evidence={"column": name, "type": str(field_.type)},
                )
            )
    return tuple(violations)


def check_identity(table: pa.Table, schema: pa.Schema) -> tuple[Violation, ...]:
    """One file carries one dataset/session/stream identity, with required subject."""
    violations: list[Violation] = []
    for name in ("dataset_id", "session_id", "stream_id"):
        if name not in table.column_names:
            continue
        column = table.column(name)
        if column.null_count:
            violations.append(
                Violation(
                    rule="identity.null",
                    detail=f"{name} must never be null in a canonical file",
                    evidence={"column": name, "null_count": column.null_count},
                )
            )
        distinct = kernels.count_distinct(column)
        if distinct != 1:
            violations.append(
                Violation(
                    rule="identity.multiple",
                    detail=(f"a canonical file must contain exactly one {name}; found {distinct}"),
                    evidence={"column": name, "distinct": _distinct_values(table, name)},
                )
            )
    if subject_required(schema) and "subject_id" in table.column_names:
        nulls = table.column("subject_id").null_count
        if nulls:
            violations.append(
                Violation(
                    rule="identity.subject_required",
                    detail=(
                        f"contract {contract_of(schema)!r} requires subject identity on every row"
                    ),
                    evidence={"null_subject_rows": nulls},
                )
            )
    return tuple(violations)


def check_time_monotonic(
    table: pa.Table,
    schema: pa.Schema,
    *,
    require_zero_based: bool = True,
) -> tuple[Violation, ...]:
    """Dense streams require zero-based, contiguous sample timing.

    ``t_rel_ns`` is strictly increasing for single-entity streams and
    non-decreasing for frame streams (tracking, pose), where all entities of one
    frame legitimately share one timestamp. ``sample_index`` is always the
    strictly increasing row ordinal.
    """
    if not is_dense(schema):
        return ()
    violations: list[Violation] = []
    strictness = time_monotonicity(schema)
    for name in ("sample_index", "t_rel_ns"):
        if name not in table.column_names or table.num_rows <= 1:
            continue
        column = table.column(name)
        if column.null_count:
            violations.append(
                Violation(
                    rule="time.null",
                    detail=f"{name} must never be null for a dense stream",
                    evidence={"column": name, "null_count": column.null_count},
                )
            )
            continue

        strictly_increasing = name == "sample_index" or strictness == MONOTONICITY_STRICT
        ordered = (
            kernels.is_strictly_increasing(column)
            if strictly_increasing
            else kernels.is_non_decreasing(column)
        )
        if not ordered:
            expected = "strictly increasing" if strictly_increasing else "non-decreasing"
            violations.append(
                Violation(
                    rule="time.monotonic",
                    detail=f"{name} must be {expected} within a stream",
                    evidence={"column": name, "monotonicity": strictness},
                )
            )
    if require_zero_based and "sample_index" in table.column_names and table.num_rows:
        first = table.column("sample_index")[0].as_py()
        if first != 0:
            violations.append(
                Violation(
                    rule="time.zero_based",
                    detail=f"sample_index must start at 0 for a canonical stream; found {first}",
                    evidence={"first_sample_index": first},
                )
            )
        expected = table.num_rows - 1
        last = table.column("sample_index")[-1].as_py()
        if last != expected:
            violations.append(
                Violation(
                    rule="time.contiguous",
                    detail=(
                        f"sample_index must be contiguous from 0; last index {last} "
                        f"with {table.num_rows} rows"
                    ),
                    evidence={"last_sample_index": last, "rows": table.num_rows},
                )
            )
    return tuple(violations)


def check_declared_authorities(table: pa.Table, schema: pa.Schema) -> tuple[Violation, ...]:
    """One file declares exactly one clock, sync spec and coordinate frame."""
    violations: list[Violation] = []
    for name in ("clock_id", "synchronization_spec_id"):
        if name not in table.column_names:
            continue
        column = table.column(name)
        if column.null_count:
            violations.append(
                Violation(
                    rule="authority.null",
                    detail=f"{name} must be declared for every sample",
                    evidence={"column": name},
                )
            )
        distinct = kernels.count_distinct(column)
        if distinct != 1:
            violations.append(
                Violation(
                    rule="authority.multiple",
                    detail=f"one canonical file must declare exactly one {name}",
                    evidence={"column": name, "distinct": _distinct_values(table, name)},
                )
            )
    if coordinate_frame_required(schema):
        if "coordinate_frame_id" not in table.column_names:
            violations.append(
                Violation(
                    rule="authority.frame_missing_column",
                    detail="modality requires a coordinate frame but the column is absent",
                )
            )
        else:
            column = table.column("coordinate_frame_id")
            if column.null_count:
                violations.append(
                    Violation(
                        rule="authority.frame_required",
                        detail=(
                            "modality requires an explicit coordinate frame on every sample; "
                            "nulls mean the frame is unspecified"
                        ),
                        evidence={"null_rows": column.null_count},
                    )
                )
            if kernels.count_distinct(column) != 1:
                violations.append(
                    Violation(
                        rule="authority.frame_multiple",
                        detail="one canonical file must not mix coordinate frames",
                    )
                )
    return tuple(violations)


def check_measurement_class(table: pa.Table) -> tuple[Violation, ...]:
    if "measurement_class" not in table.column_names:
        return ()
    allowed = {member.value for member in MeasurementClass}
    observed = {
        value
        for value in kernels.distinct_values(table.column("measurement_class"))
        if value is not None
    }
    unknown = sorted(observed - allowed)
    if unknown:
        return (
            Violation(
                rule="measurement_class.illegal",
                detail=f"measurement_class values outside the closed vocabulary: {unknown}",
                evidence={"observed": sorted(observed)},
            ),
        )
    if table.column("measurement_class").null_count:
        return (
            Violation(
                rule="measurement_class.null",
                detail="measurement_class must be present on every row",
            ),
        )
    return ()


def validate(table: pa.Table, schema: pa.Schema) -> tuple[Violation, ...]:
    """Run every contract check for one canonical table."""
    violations: list[Violation] = []
    violations.extend(check_schema_conformance(table, schema))
    violations.extend(check_units(table, schema))
    violations.extend(check_identity(table, schema))
    violations.extend(check_declared_authorities(table, schema))
    violations.extend(check_time_monotonic(table, schema))
    violations.extend(check_measurement_class(table))
    return tuple(violations)


def validate_modality(table: pa.Table, modality: Modality | str) -> tuple[Violation, ...]:
    return validate(table, get_schema(modality))


def assert_valid(table: pa.Table, schema: pa.Schema) -> pa.Table:
    """Raise :class:`QualityError` unless the table satisfies its contract."""
    violations = validate(table, schema)
    if violations:
        raise QualityError(violations)
    return table


def to_quality_issue(
    violation: Violation,
    *,
    issue_id: str,
    dataset_id: str,
    session_id: str | None = None,
    stream_id: str | None = None,
    run_id: str | None = None,
) -> QualityIssue:
    """Project a violation into a persistable, auditable quality record.

    A quarantined record must be locatable, so the caller supplies the stream (or
    the violation itself carries a sample index). Omitting both raises.
    """
    return QualityIssue(
        issue_id=issue_id,
        dataset_id=dataset_id,
        rule=violation.rule,
        severity=violation.severity,
        run_id=run_id,
        session_id=session_id,
        stream_id=stream_id or violation.stream_id,
        sample_index=violation.sample_index,
        evidence=dict(violation.evidence) or {"detail": violation.detail},
    )
