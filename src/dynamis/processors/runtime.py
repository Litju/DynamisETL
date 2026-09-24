"""Deterministic execution and materialization of processor results.

The runtime is the only place where a processor result touches the filesystem or
the control plane. It:

1. computes the input checksums and a deterministic processing-run identity;
2. materializes every dense series as an external Parquet+Zstd artifact;
3. registers the run, artifacts and ``PIPELINE_DERIVED`` scalar metrics;
4. writes a deterministic JSON receipt under the cache layer.

Artifacts are checksum-addressed by content: re-running the same revision over
the same inputs must reproduce byte-identical Parquet files. The receipt
includes the execution timestamp (evidence, not artifact identity) while the
artifact checksums and metric values stay deterministic.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from dynamis.config import Settings
from dynamis.processors.persistence import (
    assert_persistable_code_sha,
    dev_allow_unknown_code_sha,
    persist_processing_result,
)
from dynamis.processors.spec import (
    ProcessorResult,
    ProcessorSpec,
    code_git_sha,
    deterministic_run_id,
)
from dynamis.storage.atomic import atomic_write_text, sha256_file
from dynamis.storage.parquet import WrittenArtifact, write_parquet_atomic
from dynamis.storage.paths import (
    processing_series_path,
    receipt_path,
    relative_posix,
)


@dataclass(frozen=True, slots=True)
class ProcessorInput:
    """One canonical input artifact bound by its verified checksum."""

    role: str
    path: Path
    relative_path: str
    checksum_sha256: str
    row_count: int

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable descriptor of this input artifact."""
        return {
            "role": self.role,
            "relative_path": self.relative_path,
            "checksum_sha256": self.checksum_sha256,
            "row_count": self.row_count,
        }


@dataclass(frozen=True, slots=True)
class ProcessedSeries:
    """One materialized dense series artifact with its deterministic identity."""

    name: str
    artifact: WrittenArtifact

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable descriptor of this materialized series."""
        return {
            "name": self.name,
            "relative_path": self.artifact.relative_path,
            "checksum_sha256": self.artifact.checksum_sha256,
            "row_count": self.artifact.row_count,
            "byte_size": self.artifact.byte_size,
            "compression": self.artifact.compression,
        }


@dataclass(frozen=True, slots=True)
class ProcessorRunResult:
    """Complete descriptor of one executed processor run."""

    run_id: str
    dataset_id: str
    spec: ProcessorSpec
    parameters_hash: str
    code_git_sha: str | None
    input_checksums: tuple[str, ...]
    inputs: tuple[ProcessorInput, ...]
    metrics: ProcessorResult
    series: tuple[ProcessedSeries, ...]
    receipt_path: str | None
    persisted: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "dataset_id": self.dataset_id,
            "algorithm_id": self.spec.algorithm_id,
            "algorithm_version": self.spec.version,
            "parameters_hash": self.parameters_hash,
            "code_git_sha": self.code_git_sha,
            "input_checksums": list(self.input_checksums),
            "inputs": [item.to_dict() for item in self.inputs],
            "metric_count": len(self.metrics.metrics),
            "metrics": [
                {
                    "metric_id": metric.declaration.metric_id,
                    "si_unit": metric.declaration.si_unit,
                    "value": metric.value,
                    "subject_id": metric.subject_id,
                    "session_id": metric.session_id,
                    "trial_id": metric.trial_id,
                    "stream_id": metric.stream_id,
                    "entity_id": metric.entity_id,
                }
                for metric in self.metrics.metrics
            ],
            "series": [item.to_dict() for item in self.series],
            "diagnostics": dict(self.metrics.diagnostics),
            "receipt_path": self.receipt_path,
            "persisted": dict(self.persisted),
        }


def collect_input(
    settings: Settings,
    path: Path,
    *,
    role: str,
    row_count: int,
) -> ProcessorInput:
    """Hash one canonical input file and report it relative to the dataset root."""
    target = Path(path)
    return ProcessorInput(
        role=role,
        path=target,
        relative_path=relative_posix(settings.dataset_root, target),
        checksum_sha256=sha256_file(target),
        row_count=row_count,
    )


def execute_processor(
    settings: Settings,
    *,
    result: ProcessorResult,
    dataset_id: str,
    inputs: Sequence[ProcessorInput],
    series_key: str,
    engine: Engine | None = None,
    code_sha: str | None = None,
    computed_at: datetime | None = None,
    persist: bool = True,
    allow_unknown_code_sha: bool | None = None,
) -> ProcessorRunResult:
    """Materialize one processor result and (optionally) persist its provenance.

    ``series_key`` makes the external artifact path unique per input scope (for
    example a stream id or trial id) while remaining deterministic. A persisted
    run requires a full code Git SHA (see
    :func:`dynamis.processors.persistence.assert_persistable_code_sha`); the
    development-only ``DYNAMIS_ALLOW_UNKNOWN_CODE_SHA`` flag is honoured, and the
    Gold serving publication gate refuses null-SHA processor runs.
    """
    if not inputs:
        raise ValueError("a processor run requires at least one input artifact")
    if not series_key.strip():
        raise ValueError("a processor run requires a deterministic series key")
    if persist and engine is None:
        raise ValueError(
            "persist=True requires a control-plane engine; use persist=False for an "
            "artifact-only execution"
        )
    timestamp = computed_at or datetime.now(UTC)
    resolved_code_sha = code_sha if code_sha is not None else code_git_sha()
    resolved_allow_unknown = allow_unknown_code_sha
    if persist:
        if resolved_allow_unknown is None:
            resolved_allow_unknown = dev_allow_unknown_code_sha()
        # Fail before materializing artifacts or touching the control plane.
        assert_persistable_code_sha(resolved_code_sha, allow_unknown=resolved_allow_unknown)
    parameters_hash = result.spec.parameters_hash
    input_checksums = tuple(item.checksum_sha256 for item in inputs)
    run_id = deterministic_run_id(
        dataset_id=dataset_id,
        algorithm_id=result.spec.algorithm_id,
        version=result.spec.version,
        parameters_hash=parameters_hash,
        input_checksums=input_checksums,
        code_sha=resolved_code_sha,
    )
    processed: list[ProcessedSeries] = []
    for series in result.series:
        target = processing_series_path(
            settings,
            dataset_id=dataset_id,
            algorithm_id=result.spec.algorithm_id,
            parameters_hash=parameters_hash,
            name=f"{series_key}.{series.name}",
        )
        artifact = write_parquet_atomic(series.table, target, relative_to=settings.dataset_root)
        processed.append(ProcessedSeries(name=series.name, artifact=artifact))

    persisted: dict[str, int] = {}
    if persist and engine is not None:
        series_by_name = {series.name: series for series in result.series}
        tactical_level = result.diagnostics.get("level")
        is_tactical = result.spec.algorithm_id.startswith("tactical.")
        input_measurement_class = result.diagnostics.get("input_measurement_class")
        if input_measurement_class is None and result.diagnostics.get("input_measurement_classes"):
            input_measurement_class = json.dumps(
                result.diagnostics["input_measurement_classes"],
                sort_keys=True,
                separators=(",", ":"),
            )
        elif input_measurement_class is not None and not isinstance(input_measurement_class, str):
            input_measurement_class = json.dumps(
                input_measurement_class, sort_keys=True, separators=(",", ":")
            )

        def first_value(series_name: str, column: str) -> Any:
            table = series_by_name[series_name].table
            if column not in table.column_names or table.num_rows == 0:
                return None
            return table.column(column)[0].as_py()

        def series_measurement_class(series_name: str) -> str | None:
            metadata = series_by_name[series_name].table.schema.metadata or {}
            declared = metadata.get(b"dynamis.measurement_class")
            if declared is not None:
                return declared.decode("utf-8")
            if not is_tactical:
                return None
            return "MODEL_ESTIMATED" if tactical_level == "C" else "PIPELINE_DERIVED"

        artifact_rows = tuple(
            {
                "artifact_id": f"proc-{run_id}-{item.name}"[:128],
                "dataset_id": dataset_id,
                "run_id": run_id,
                "artifact_type": f"processed_series.{item.name}"[:64],
                "layer": "gold",
                "relative_path": item.artifact.relative_path or "",
                "checksum_sha256": item.artifact.checksum_sha256,
                "byte_size": item.artifact.byte_size,
                "row_count": item.artifact.row_count,
                "created_at": timestamp,
                "artifact_metadata": {
                    "algorithm_id": result.spec.algorithm_id,
                    "algorithm_version": result.spec.version,
                    "parameters_hash": parameters_hash,
                    "code_git_sha": resolved_code_sha,
                    "series_name": item.name,
                    "series_key": series_key,
                    "stream_id": series_key if is_tactical else None,
                    "session_id": first_value(item.name, "session_id"),
                    "trial_id": first_value(item.name, "trial_id"),
                    "tactical_level": tactical_level if is_tactical else None,
                    "measurement_class": series_measurement_class(item.name),
                    "input_measurement_class": input_measurement_class,
                    "coordinate_frame_id": result.diagnostics.get("coordinate_frame_id"),
                    "quality": result.diagnostics.get("quality", {}),
                },
            }
            for item in processed
        )
        with engine.begin() as connection:
            persisted = persist_processing_result(
                connection,
                dataset_id=dataset_id,
                run_id=run_id,
                result=result,
                input_checksums=input_checksums,
                computed_at=timestamp,
                code_sha=resolved_code_sha,
                artifact_rows=artifact_rows,
                allow_unknown_code_sha=bool(resolved_allow_unknown),
            )

    receipt = {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "algorithm_id": result.spec.algorithm_id,
        "algorithm_name": result.spec.name,
        "algorithm_version": result.spec.version,
        "parameters": dict(result.spec.parameters),
        "parameters_hash": parameters_hash,
        "code_git_sha": resolved_code_sha,
        "computed_at": timestamp.isoformat(),
        "inputs": [item.to_dict() for item in inputs],
        "input_checksums": list(input_checksums),
        "metrics": sorted(
            (
                {
                    "metric_id": metric.declaration.metric_id,
                    "si_unit": metric.declaration.si_unit,
                    "measurement_class": "PIPELINE_DERIVED",
                    "value": metric.value,
                    "subject_id": metric.subject_id,
                    "session_id": metric.session_id,
                    "trial_id": metric.trial_id,
                    "stream_id": metric.stream_id,
                    "entity_id": metric.entity_id,
                    "provenance": dict(metric.provenance),
                }
                for metric in result.metrics
            ),
            key=lambda item: (
                item["metric_id"],
                item["session_id"] or "",
                item["subject_id"] or "",
                item["trial_id"] or "",
                item["stream_id"] or "",
                item["entity_id"] or "",
            ),
        ),
        "series": [item.to_dict() for item in processed],
        "diagnostics": dict(result.diagnostics),
        "persisted": dict(persisted),
    }
    receipt_target = receipt_path(settings, dataset_id=dataset_id, kind="processing", name=run_id)
    atomic_write_text(
        receipt_target,
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
    )
    return ProcessorRunResult(
        run_id=run_id,
        dataset_id=dataset_id,
        spec=result.spec,
        parameters_hash=parameters_hash,
        code_git_sha=resolved_code_sha,
        input_checksums=input_checksums,
        inputs=tuple(inputs),
        metrics=result,
        series=tuple(processed),
        receipt_path=relative_posix(settings.dataset_root, receipt_target),
        persisted=persisted,
    )


def read_series_checksums(result: ProcessorRunResult) -> dict[str, str]:
    """Series name to artifact checksum, for deterministic-rerun assertions."""
    return {item.name: item.artifact.checksum_sha256 for item in result.series}


__all__ = [
    "ProcessorInput",
    "ProcessedSeries",
    "ProcessorRunResult",
    "collect_input",
    "execute_processor",
    "read_series_checksums",
]
