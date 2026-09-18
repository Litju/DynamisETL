"""Real-source acceptance harness for processor runs.

This module executes processors over already-acquired canonical Silver corpora,
proves checksum-deterministic reruns and reports paired agreement against
source-provided reference values. It never downloads anything and never claims
a source value is physical ground truth: reference metrics are labelled
SOURCE_DERIVED, the comparison is descriptive, and no automatic scientific
verdict is emitted.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Engine

from dynamis.config import Settings
from dynamis.processors.corpus import SilverStreamRef, list_silver_streams, load_silver
from dynamis.processors.force_cmj import process_force_cmj
from dynamis.processors.runtime import ProcessorRunResult, execute_processor
from dynamis.processors.statistics import bland_altman, paired_comparison
from dynamis.storage.atomic import atomic_write_text
from dynamis.storage.metadata import build_metadata
from dynamis.storage.paths import receipt_path, relative_posix

_TABLES = build_metadata().tables
DERIVED_METRIC_TABLE = _TABLES["derived_metric"]

WHITE_DATASET_ID = "white-cmj-acc-grf"
REFERENCE_JUMP_HEIGHT = "source_jump_height"
REFERENCE_PEAK_POWER = "source_peak_power_relative"
PIPELINE_JUMP_HEIGHT = "cmj.jump_height_jhwd"
PIPELINE_PEAK_POWER = "cmj.peak_specific_power"


@dataclass(frozen=True, slots=True)
class DatasetProcessing:
    """Outcome of processing one canonical corpus with one processor."""

    dataset_id: str
    algorithm_id: str
    streams: int
    runs: int
    series_checksums: dict[str, str]
    metric_values: dict[str, float]
    metric_units: dict[str, str]
    processed_stream_ids: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "algorithm_id": self.algorithm_id,
            "streams": self.streams,
            "runs": self.runs,
            "series_checksums": self.series_checksums,
            "metric_count": len(self.metric_values),
            "processed_stream_ids": list(self.processed_stream_ids),
            "diagnostics": self.diagnostics,
        }


def _reference_values(
    connection,
    *,
    dataset_id: str,
    metric_ids: tuple[str, ...],
) -> dict[str, dict[str, float]]:
    rows = connection.execute(
        sa.select(
            DERIVED_METRIC_TABLE.c.metric_id,
            DERIVED_METRIC_TABLE.c.trial_id,
            DERIVED_METRIC_TABLE.c.stream_id,
            DERIVED_METRIC_TABLE.c.value_num,
        ).where(
            DERIVED_METRIC_TABLE.c.dataset_id == dataset_id,
            DERIVED_METRIC_TABLE.c.metric_id.in_(metric_ids),
        )
    ).fetchall()
    values: dict[str, dict[str, float]] = {metric_id: {} for metric_id in metric_ids}
    for row in rows:
        key = row.trial_id or row.stream_id
        if key is None:
            continue
        values[row.metric_id][key] = float(row.value_num)
    return values


def _collect_pipeline_values(
    runs: dict[str, ProcessorRunResult],
    *,
    stream_to_key: dict[str, str],
    metric_ids: tuple[str, ...],
) -> dict[str, dict[str, float]]:
    """In-memory pipeline values of this execution, keyed by trial/stream.

    Reading the values from the executed results (instead of re-querying every
    historical revision of the algorithm) keeps the comparison bound to exactly
    the code revision and parameters that produced the receipt.
    """
    values: dict[str, dict[str, float]] = {metric_id: {} for metric_id in metric_ids}
    for stream_id, run in runs.items():
        key = stream_to_key[stream_id]
        for metric in run.metrics.metrics:
            if metric.declaration.metric_id in values:
                values[metric.declaration.metric_id][key] = metric.value
    return values


def _paired(
    pipeline: dict[str, float],
    reference: dict[str, float],
    *,
    tolerance: float,
) -> dict[str, Any]:
    keys = sorted(set(pipeline) & set(reference))
    if not keys:
        return {"n": 0, "paired_keys": []}
    comparison = paired_comparison(
        [pipeline[key] for key in keys],
        [reference[key] for key in keys],
        tolerance=tolerance,
    )
    payload = comparison.to_dict()
    payload["paired_keys"] = keys
    payload["within_tolerance_fraction"] = (
        comparison.within_tolerance / comparison.n
        if comparison.within_tolerance is not None
        else None
    )
    bands = bland_altman([pipeline[key] for key in keys], [reference[key] for key in keys])
    payload["bland_altman"] = None if bands is None else bands.to_dict()
    payload["reference_semantics"] = (
        "source-derived reference metric supplied by the provider; not physical ground truth"
    )
    payload["verdict"] = None
    return payload


def white_force_acceptance(
    settings: Settings,
    engine: Engine,
    *,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Process all registered White CMJ force streams and compare references."""
    with engine.connect() as connection:
        refs = list_silver_streams(connection, dataset_id=WHITE_DATASET_ID, modality="force")
    if not refs:
        raise ValueError(f"{WHITE_DATASET_ID}: no registered force streams to process")

    def process(ref: SilverStreamRef) -> ProcessorRunResult:
        table, processor_input = load_silver(settings, ref)
        result = process_force_cmj(table)
        return execute_processor(
            settings,
            result=result,
            dataset_id=WHITE_DATASET_ID,
            inputs=(processor_input,),
            series_key=ref.stream_id,
            engine=engine,
        )

    first_pass: dict[str, ProcessorRunResult] = {}
    for index, ref in enumerate(refs):
        first_pass[ref.stream_id] = process(ref)
        if progress is not None:
            progress(index + 1, len(refs))

    checksums = {
        stream_id: run.series[0].artifact.checksum_sha256
        for stream_id, run in first_pass.items()
        if run.series
    }
    # Deterministic rerun: the same code revision over the same verified inputs
    # must reproduce byte-identical artifacts and identical metric values, and
    # must not duplicate a single control-plane row.
    second_pass: dict[str, ProcessorRunResult] = {}
    for ref in refs:
        second_pass[ref.stream_id] = process(ref)
    rerun_matches = sum(
        1
        for stream_id, run in second_pass.items()
        if run.series and run.series[0].artifact.checksum_sha256 == checksums.get(stream_id)
    )
    run_ids_stable = all(
        second_pass[stream_id].run_id == first_pass[stream_id].run_id for stream_id in first_pass
    )

    pipeline = _collect_pipeline_values(
        first_pass,
        stream_to_key={ref.stream_id: ref.trial_id or ref.stream_id for ref in refs},
        metric_ids=(PIPELINE_JUMP_HEIGHT, PIPELINE_PEAK_POWER),
    )
    with engine.connect() as connection:
        reference = _reference_values(
            connection,
            dataset_id=WHITE_DATASET_ID,
            metric_ids=(REFERENCE_JUMP_HEIGHT, REFERENCE_PEAK_POWER),
        )
        # Persistence proof for the executed runs: every stream's metrics must be
        # present in the control plane exactly once under its deterministic run.
        metric_rows = connection.execute(
            sa.select(sa.func.count())
            .select_from(DERIVED_METRIC_TABLE)
            .where(
                DERIVED_METRIC_TABLE.c.dataset_id == WHITE_DATASET_ID,
                DERIVED_METRIC_TABLE.c.run_id.in_(
                    sorted({run.run_id for run in first_pass.values()})
                ),
            )
        ).scalar_one()
        provenance_rows = connection.execute(
            sa.select(DERIVED_METRIC_TABLE.c.provenance)
            .where(
                DERIVED_METRIC_TABLE.c.run_id == first_pass[refs[0].stream_id].run_id,
                DERIVED_METRIC_TABLE.c.metric_id == PIPELINE_JUMP_HEIGHT,
            )
            .limit(1)
        ).fetchone()
    provenance = dict(provenance_rows.provenance) if provenance_rows else {}
    expected_metric_rows = len(refs) * 7
    if metric_rows != expected_metric_rows:
        raise ValueError(
            f"{WHITE_DATASET_ID}: expected {expected_metric_rows} persisted metric rows for "
            f"the executed runs, found {metric_rows}"
        )
    if provenance.get("parameters_hash") != first_pass[refs[0].stream_id].parameters_hash:
        raise ValueError("persisted metric provenance does not carry the executed parameters hash")
    if provenance.get("code_git_sha") != first_pass[refs[0].stream_id].code_git_sha:
        raise ValueError("persisted metric provenance does not carry the executed code Git SHA")

    jump_height = _paired(
        pipeline[PIPELINE_JUMP_HEIGHT], reference[REFERENCE_JUMP_HEIGHT], tolerance=1e-3
    )
    peak_power = _paired(
        pipeline[PIPELINE_PEAK_POWER], reference[REFERENCE_PEAK_POWER], tolerance=0.1
    )
    receipt = {
        "dataset_id": WHITE_DATASET_ID,
        "algorithm_id": first_pass[refs[0].stream_id].spec.algorithm_id,
        "algorithm_version": first_pass[refs[0].stream_id].spec.version,
        "parameters_hash": first_pass[refs[0].stream_id].parameters_hash,
        "code_git_sha": first_pass[refs[0].stream_id].code_git_sha,
        "streams": len(refs),
        "runs": len(first_pass),
        "metric_rows_total": int(metric_rows),
        "persisted_provenance_parameters_hash": provenance.get("parameters_hash"),
        "persisted_provenance_code_git_sha": provenance.get("code_git_sha"),
        "rerun_series_matches": rerun_matches,
        "rerun_run_ids_stable": run_ids_stable,
        "jump_height_comparison": jump_height,
        "peak_power_comparison": peak_power,
        "reference_semantics": (
            "source_jump_height and source_peak_power_relative remain SOURCE_DERIVED provider "
            "values; the pipeline metrics carry distinct PIPELINE_DERIVED identities"
        ),
        "no_body_mass_fabricated": True,
        "no_flight_time_metric": True,
        "full_record_used": True,
        "onset_redetection": False,
    }
    target = receipt_path(
        settings, dataset_id=WHITE_DATASET_ID, kind="acceptance", name="res100-white-force"
    )
    atomic_write_text(target, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    receipt["receipt_path"] = relative_posix(settings.dataset_root, target)
    return receipt


@dataclass(frozen=True, slots=True)
class StreamProcessorPlan:
    """One corpus to process with one pure function."""

    dataset_id: str
    modality: str
    processor: Callable[[Any], Any]
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "modality": self.modality,
            "session_id": self.session_id,
        }


def process_corpus(
    settings: Settings,
    engine: Engine,
    *,
    plan: StreamProcessorPlan,
    progress: Callable[[int, int], None] | None = None,
) -> DatasetProcessing:
    """Process every registered stream of one dataset/modality deterministically."""
    with engine.connect() as connection:
        refs = list_silver_streams(
            connection,
            dataset_id=plan.dataset_id,
            modality=plan.modality,
            session_id=plan.session_id,
        )
    if not refs:
        raise ValueError(f"{plan.dataset_id}/{plan.modality}: no registered streams to process")
    checksums: dict[str, str] = {}
    metric_values: dict[str, float] = {}
    metric_units: dict[str, str] = {}
    run_ids: set[str] = set()
    algorithm_id = ""
    diagnostics: dict[str, Any] = {}
    for index, ref in enumerate(refs):
        table, processor_input = load_silver(settings, ref)
        result = plan.processor(table)
        algorithm_id = result.spec.algorithm_id
        run = execute_processor(
            settings,
            result=result,
            dataset_id=plan.dataset_id,
            inputs=(processor_input,),
            series_key=ref.stream_id,
            engine=engine,
        )
        run_ids.add(run.run_id)
        for series in run.series:
            checksums[f"{ref.stream_id}.{series.name}"] = series.artifact.checksum_sha256
        for metric in result.metrics:
            key = f"{ref.stream_id}|{metric.declaration.metric_id}|{metric.subject_id or ''}"
            metric_values[key] = metric.value
            metric_units[metric.declaration.metric_id] = metric.declaration.si_unit
        diagnostics.update(dict(result.diagnostics))
        if progress is not None:
            progress(index + 1, len(refs))
    return DatasetProcessing(
        dataset_id=plan.dataset_id,
        algorithm_id=algorithm_id,
        streams=len(refs),
        runs=len(run_ids),
        series_checksums=checksums,
        metric_values=metric_values,
        metric_units=metric_units,
        processed_stream_ids=tuple(ref.stream_id for ref in refs),
        diagnostics=diagnostics,
    )


__all__ = [
    "DatasetProcessing",
    "StreamProcessorPlan",
    "process_corpus",
    "white_force_acceptance",
]
