"""Deterministic scientific processor layer.

Processors consume canonical Silver streams and emit scalar
``PIPELINE_DERIVED`` metrics plus external dense derived series. Provider
adapters live in :mod:`dynamis.adapters` and never import from this package;
processors never import an adapter, so the dependency direction is enforced by
construction.
"""

from dynamis.processors.runtime import (
    ProcessedSeries,
    ProcessorInput,
    ProcessorRunResult,
    collect_input,
    execute_processor,
    read_series_checksums,
)
from dynamis.processors.spec import (
    MetricDeclaration,
    ProcessorResult,
    ProcessorSpec,
    ScalarMetric,
    SeriesOutput,
    canonical_parameters,
    code_git_sha,
    derived_metric_id,
    deterministic_run_id,
    parameters_hash,
)

__all__ = [
    "MetricDeclaration",
    "ProcessedSeries",
    "ProcessorInput",
    "ProcessorResult",
    "ProcessorRunResult",
    "ProcessorSpec",
    "ScalarMetric",
    "SeriesOutput",
    "canonical_parameters",
    "code_git_sha",
    "collect_input",
    "derived_metric_id",
    "deterministic_run_id",
    "execute_processor",
    "parameters_hash",
    "read_series_checksums",
]
