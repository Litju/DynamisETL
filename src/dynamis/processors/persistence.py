"""Control-plane persistence for deterministic processor results.

Scalar processor metrics become ``PIPELINE_DERIVED`` ``DerivedMetric`` rows
bound to the input checksums, algorithm identity, parameters hash, code Git SHA
and processing run. Dense derived series never enter PostgreSQL: only their
external artifact metadata is registered here.

The writer is idempotent. A rerun over the same inputs, algorithm revision,
parameters and code revision derives the same run and metric identities, so
nothing duplicates; a rerun whose parameter or code revision changed derives new
identities instead of silently overwriting a scientific value.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import insert as pg_insert

from dynamis.contracts import AlgorithmKind
from dynamis.processors.spec import (
    ProcessorResult,
    ScalarMetric,
    derived_metric_id,
)
from dynamis.storage.metadata import build_metadata

_TABLES = build_metadata().tables
ALGORITHM_SPEC_TABLE = _TABLES["algorithm_spec"]
DERIVED_METRIC_TABLE = _TABLES["derived_metric"]
METRIC_DEFINITION_TABLE = _TABLES["metric_definition"]
PROCESSING_ARTIFACT_TABLE = _TABLES["processing_artifact"]
PROCESSING_RUN_TABLE = _TABLES["processing_run"]


def _upsert(
    connection,
    table: Table,
    rows: list[dict[str, Any]],
    *,
    update: bool = False,
) -> int:
    """Insert rows, optionally making the incoming row authoritative on conflict.

    ``update=True`` is used for derived metrics: when a corrected input changes
    only the input checksums, the derived-metric identity is unchanged but the
    run changes, and the stored value must converge to the corrected one instead
    of being silently discarded by ``DO NOTHING``.
    """
    if not rows:
        return 0
    primary_keys = [column.name for column in table.primary_key.columns]
    statement = pg_insert(table).values(rows)
    if update:
        statement = statement.on_conflict_do_update(
            index_elements=primary_keys,
            set_={
                column.name: statement.excluded[column.name]
                for column in table.columns
                if column.name not in primary_keys
            },
        )
    else:
        statement = statement.on_conflict_do_nothing(index_elements=primary_keys)
    statement = statement.returning(*table.primary_key.columns)
    return len(connection.execute(statement).fetchall())


def _upsert_algorithm(connection, result: ProcessorResult, *, code_sha: str | None) -> int:
    """Converge the global algorithm spec to the executed revision."""
    contract = result.spec.contract(code_sha=code_sha)
    statement = pg_insert(ALGORITHM_SPEC_TABLE).values(
        [
            {
                "algorithm_id": contract.algorithm_id,
                "name": contract.name,
                "version": contract.version,
                "kind": contract.kind.value,
                "code_git_sha": contract.code_git_sha,
                "parameters": dict(contract.parameters),
                "parameters_hash": contract.parameters_hash,
                "description": contract.description,
                "citation": contract.citation,
            }
        ]
    )
    statement = statement.on_conflict_do_update(
        index_elements=["algorithm_id"],
        set_={
            "name": statement.excluded.name,
            "version": statement.excluded.version,
            "kind": statement.excluded.kind,
            "code_git_sha": statement.excluded.code_git_sha,
            "parameters": statement.excluded.parameters,
            "parameters_hash": statement.excluded.parameters_hash,
            "description": statement.excluded.description,
            "citation": statement.excluded.citation,
        },
    )
    connection.execute(statement)
    return 1


def _assert_existing_definitions_match(connection, definitions: dict[str, dict[str, Any]]) -> None:
    """Refuse to reuse an existing metric id with a different definition."""
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
            name
            for name, value in (
                ("name", row.name),
                ("si_unit", row.si_unit),
                ("measurement_class", row.measurement_class),
                ("value_kind", row.value_kind),
            )
            if value != incoming[name]
        ]
        if conflicts:
            raise ValueError(
                f"metric definition {row.metric_id!r} already exists with different "
                f"{', '.join(conflicts)}; refusing to reuse a scientific definition"
            )


def _metric_rows(
    result: ProcessorResult,
    *,
    dataset_id: str,
    run_id: str,
    parameters_hash: str,
    code_sha: str | None,
    input_checksums: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Build one derived-metric row per scalar with its full provenance."""
    rows: list[dict[str, Any]] = []
    for metric in result.metrics:
        declaration = metric.declaration
        provenance = {
            "origin": "pipeline-computed",
            "algorithm_id": result.spec.algorithm_id,
            "algorithm_version": result.spec.version,
            "parameters_hash": parameters_hash,
            "code_git_sha": code_sha,
            "run_id": run_id,
            "input_checksums": list(input_checksums),
            "entity_id": metric.entity_id,
            **dict(metric.provenance),
        }
        rows.append(
            {
                "derived_metric_id": derived_metric_id(
                    dataset_id=dataset_id,
                    metric_id=declaration.metric_id,
                    algorithm_id=result.spec.algorithm_id,
                    algorithm_version=result.spec.version,
                    parameters_hash=parameters_hash,
                    code_sha=code_sha,
                    subject_id=metric.subject_id,
                    session_id=metric.session_id,
                    trial_id=metric.trial_id,
                    stream_id=metric.stream_id,
                    entity_id=metric.entity_id,
                ),
                "dataset_id": dataset_id,
                "metric_id": declaration.metric_id,
                "run_id": run_id,
                "subject_id": metric.subject_id,
                "session_id": metric.session_id,
                "trial_id": metric.trial_id,
                "stream_id": metric.stream_id,
                "si_unit": declaration.si_unit,
                "measurement_class": "PIPELINE_DERIVED",
                "value_num": float(metric.value),
                "value_json": sa.null(),
                "computed_at": None,
                "input_checksums": list(input_checksums),
                "provenance": provenance,
            }
        )
    return rows


def persist_processing_result(
    connection,
    *,
    dataset_id: str,
    run_id: str,
    result: ProcessorResult,
    input_checksums: tuple[str, ...],
    computed_at: datetime,
    code_sha: str | None,
    artifact_rows: tuple[dict[str, Any], ...] = (),
) -> dict[str, int]:
    """Persist one processor result; call inside a transaction."""
    written = {
        "algorithm_spec": 0,
        "metric_definition": 0,
        "derived_metric": 0,
        "processing_run": 0,
        "processing_artifact": 0,
    }
    malformed = [checksum for checksum in input_checksums if len(checksum) != 64]
    if malformed:
        raise ValueError(f"input checksums must be full sha256 hex digests; found {malformed!r}")
    usable_checksums = list(input_checksums)
    if not usable_checksums:
        raise ValueError("a processor result must cite at least one verified input checksum")
    if not result.metrics and not result.series:
        raise ValueError("a processor result must produce at least one metric or series")
    written["algorithm_spec"] = _upsert_algorithm(connection, result, code_sha=code_sha)
    parameters_hash = result.spec.parameters_hash
    run_statement = pg_insert(PROCESSING_RUN_TABLE).values(
        [
            {
                "run_id": run_id,
                "dataset_id": dataset_id,
                "algorithm_id": result.spec.algorithm_id,
                "status": "completed",
                "code_git_sha": code_sha,
                "parameters_hash": parameters_hash,
                "dagster_run_id": None,
                "started_at": computed_at,
                "completed_at": computed_at,
                "input_checksums": usable_checksums,
                "notes": (
                    f"DynamisData processor run; dataset={dataset_id}; "
                    f"algorithm={result.spec.algorithm_id}; version={result.spec.version}"
                ),
            }
        ]
    )
    run_statement = run_statement.on_conflict_do_update(
        index_elements=["run_id"],
        set_={
            "status": run_statement.excluded.status,
            "code_git_sha": run_statement.excluded.code_git_sha,
            "parameters_hash": run_statement.excluded.parameters_hash,
            "completed_at": run_statement.excluded.completed_at,
            "input_checksums": run_statement.excluded.input_checksums,
            "notes": run_statement.excluded.notes,
        },
    )
    connection.execute(run_statement)
    written["processing_run"] = 1

    definitions: dict[str, dict[str, Any]] = {}
    for metric in result.metrics:
        declaration = metric.declaration
        definition = {
            "metric_id": declaration.metric_id,
            "name": declaration.name,
            "si_unit": declaration.si_unit,
            "measurement_class": "PIPELINE_DERIVED",
            "value_kind": declaration.value_kind.value,
            "description": declaration.description,
            "algorithm_id": result.spec.algorithm_id,
        }
        existing = definitions.get(declaration.metric_id)
        if existing is not None and existing != definition:
            raise ValueError(
                f"conflicting definitions for metric {declaration.metric_id!r} in one result"
            )
        definitions[declaration.metric_id] = definition
    _assert_existing_definitions_match(connection, definitions)
    written["metric_definition"] = len(
        connection.execute(
            pg_insert(METRIC_DEFINITION_TABLE)
            .values(list(definitions.values()))
            .on_conflict_do_nothing(index_elements=["metric_id"])
            .returning(METRIC_DEFINITION_TABLE.c.metric_id)
        ).fetchall()
    )

    # A rerun of the same deterministic identity replaces the current values of
    # that run, so a corrected re-execution cannot leave stale rows behind.
    connection.execute(DERIVED_METRIC_TABLE.delete().where(DERIVED_METRIC_TABLE.c.run_id == run_id))
    metric_rows = _metric_rows(
        result,
        dataset_id=dataset_id,
        run_id=run_id,
        parameters_hash=parameters_hash,
        code_sha=code_sha,
        input_checksums=tuple(usable_checksums),
    )
    for row in metric_rows:
        row["computed_at"] = computed_at
    written["derived_metric"] = _upsert(connection, DERIVED_METRIC_TABLE, metric_rows, update=True)

    if artifact_rows:
        paths = sorted({str(row["relative_path"]) for row in artifact_rows})
        connection.execute(
            PROCESSING_ARTIFACT_TABLE.delete().where(
                sa.and_(
                    PROCESSING_ARTIFACT_TABLE.c.dataset_id == dataset_id,
                    PROCESSING_ARTIFACT_TABLE.c.relative_path.in_(paths),
                )
            )
        )
        written["processing_artifact"] = _upsert(
            connection, PROCESSING_ARTIFACT_TABLE, list(artifact_rows)
        )
    return written


def pipeline_measurement_class() -> str:
    """The measurement class every processor metric must carry."""
    return "PIPELINE_DERIVED"


def algorithm_kind_value() -> str:
    return AlgorithmKind.PROCESSOR.value


__all__ = [
    "persist_processing_result",
    "pipeline_measurement_class",
    "algorithm_kind_value",
    "ScalarMetric",
]
