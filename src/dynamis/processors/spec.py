"""Deterministic processor identity and result contracts.

A processor is a pure scientific computation over canonical inputs. It is
separate from a provider adapter by construction:

* the adapter translates a provider payload into canonical Silver streams;
* the processor consumes canonical streams and emits derived metrics/series.

Every processor carries a :class:`ProcessorSpec` with a stable ``algorithm_id``,
a version, an explicit parameter mapping and a deterministic SHA-256 parameters
hash. The code Git SHA is captured by the runtime at execution time, never
hard-coded here, so the same specification can be re-executed by a different
code revision and still record what actually ran.

A scalar result is a :class:`ScalarMetric` and is persisted as a
``PIPELINE_DERIVED`` metric. A dense result is a :class:`SeriesOutput` and is
materialized as an external Parquet artifact; dense samples never enter
PostgreSQL.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa

from dynamis.contracts import (
    AlgorithmKind,
    AlgorithmSpec,
    MetricValueKind,
)
from dynamis.contracts.sports import DataGrain
from dynamis.contracts.units import assert_si_unit

#: Stable, human-readable algorithm identity: lower-case segments joined by dots.
ALGORITHM_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")

ENV_CODE_GIT_SHA = "DYNAMIS_CODE_GIT_SHA"


def canonical_parameters(parameters: Mapping[str, Any]) -> str:
    """Canonical JSON text for a parameter mapping.

    Parameters must be exactly representable as JSON: NaN/Infinity and
    non-serializable objects raise instead of silently entering a run identity.
    Keys are sorted and separators are compact so the text is deterministic
    across processes and platforms.
    """
    try:
        return json.dumps(
            dict(parameters),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"processor parameters must be canonical JSON: {exc}") from exc


def parameters_hash(parameters: Mapping[str, Any]) -> str:
    """Deterministic SHA-256 over the canonical parameter text."""
    return hashlib.sha256(canonical_parameters(parameters).encode("utf-8")).hexdigest()


def code_git_sha(repository_root: Path | None = None) -> str | None:
    """Best-effort Git revision of the executing source tree.

    Resolution order:

    1. ``DYNAMIS_CODE_GIT_SHA`` (an explicit, already-verified revision, for
       environments without a Git executable);
    2. ``git rev-parse HEAD`` in the repository root.

    Returns ``None`` when neither is available; a caller must never fabricate a
    revision, so ``None`` is a truthful "unknown" rather than a placeholder.
    """
    explicit = os.environ.get(ENV_CODE_GIT_SHA, "").strip().lower()
    if explicit:
        if not re.fullmatch(r"[0-9a-f]{40}", explicit):
            raise ValueError(f"{ENV_CODE_GIT_SHA} must be a full 40-character Git SHA")
        return explicit
    if repository_root is None:
        from dynamis.config import repository_root as resolve_root

        repository_root = resolve_root()
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except OSError:
        return None
    candidate = completed.stdout.strip().lower()
    return candidate if re.fullmatch(r"[0-9a-f]{40}", candidate) else None


@dataclass(frozen=True, slots=True)
class ProcessorSpec:
    """Stable identity of one deterministic processor revision."""

    algorithm_id: str
    name: str
    version: str
    description: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    citation: str | None = None

    def __post_init__(self) -> None:
        if not ALGORITHM_ID_PATTERN.match(self.algorithm_id):
            raise ValueError(
                f"algorithm_id {self.algorithm_id!r} must be a dotted lower-case identity"
            )
        if not self.version.strip():
            raise ValueError("a processor spec requires an explicit version")
        if not self.name.strip():
            raise ValueError("a processor spec requires a name")
        # A parameter mapping that cannot be hashed is not a reproducible
        # revision; compute eagerly so construction fails loudly.
        parameters_hash(self.parameters)

    @property
    def parameters_hash(self) -> str:
        return parameters_hash(self.parameters)

    def contract(self, *, code_sha: str | None = None) -> AlgorithmSpec:
        """Project this spec into the global control-plane ``AlgorithmSpec``."""
        return AlgorithmSpec(
            algorithm_id=self.algorithm_id,
            name=self.name,
            version=self.version,
            kind=AlgorithmKind.PROCESSOR,
            code_git_sha=code_sha,
            parameters=dict(self.parameters),
            parameters_hash=self.parameters_hash,
            description=self.description,
            citation=self.citation,
        )


@dataclass(frozen=True, slots=True)
class MetricDeclaration:
    """Global scientific definition of a scalar metric a processor emits."""

    metric_id: str
    name: str
    si_unit: str
    description: str
    value_kind: MetricValueKind = MetricValueKind.SCALAR

    def __post_init__(self) -> None:
        if not self.metric_id.strip() or not self.name.strip():
            raise ValueError("a metric declaration requires an id and a name")
        assert_si_unit(self.si_unit, field_name=f"MetricDeclaration[{self.metric_id}].si_unit")


@dataclass(frozen=True, slots=True)
class ScalarMetric:
    """One computed scalar with its identity scope and local provenance.

    The value is always finite: a metric that cannot be computed is absent from
    the result instead of being represented as NaN, so a reader can never mistake
    a missing computation for a measured zero.
    """

    declaration: MetricDeclaration
    value: float
    subject_id: str | None = None
    session_id: str | None = None
    trial_id: str | None = None
    stream_id: str | None = None
    #: Entity discriminator within a multi-object stream (for example a tracking
    #: object id). ``None`` for single-entity streams.
    entity_id: str | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not math.isfinite(self.value):
            raise ValueError(
                f"{self.declaration.metric_id}: a scalar metric must be finite, "
                f"found {self.value!r}"
            )


@dataclass(frozen=True, slots=True)
class SeriesOutput:
    """One dense derived table materialized externally as Parquet+Zstd."""

    name: str
    table: pa.Table
    description: str = ""
    grain: DataGrain | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("a series output requires a name")
        if "/" in self.name or "\\" in self.name:
            raise ValueError(f"series name {self.name!r} must be a single path component")


@dataclass(frozen=True, slots=True)
class ProcessorResult:
    """Everything one deterministic processor produced for one input scope."""

    spec: ProcessorSpec
    metrics: tuple[ScalarMetric, ...] = ()
    series: tuple[SeriesOutput, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


def derived_metric_id(
    *,
    dataset_id: str,
    metric_id: str,
    algorithm_id: str,
    algorithm_version: str,
    parameters_hash: str,
    code_sha: str | None = None,
    subject_id: str | None = None,
    session_id: str | None = None,
    trial_id: str | None = None,
    stream_id: str | None = None,
    entity_id: str | None = None,
) -> str:
    """Content-addressed identity of one pipeline-derived metric value.

    Algorithm id, algorithm version, parameters hash and code revision are part
    of the identity, so a changed algorithm, parameter or code revision produces
    a *new* metric row bound to its own run instead of silently overwriting a
    value that a different revision produced. Re-running the same inputs with
    the same code revision and parameters is therefore idempotent, and every
    stored row resolves to exactly one code revision and processing run.
    """
    identity = json.dumps(
        {
            "dataset_id": dataset_id,
            "metric_id": metric_id,
            "algorithm_id": algorithm_id,
            "algorithm_version": algorithm_version,
            "parameters_hash": parameters_hash,
            "code_sha": code_sha,
            "subject_id": subject_id,
            "session_id": session_id,
            "trial_id": trial_id,
            "stream_id": stream_id,
            "entity_id": entity_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"dm-{hashlib.sha256(identity).hexdigest()[:32]}"


def deterministic_run_id(
    *,
    dataset_id: str,
    algorithm_id: str,
    version: str,
    parameters_hash: str,
    input_checksums: tuple[str, ...],
    code_sha: str | None = None,
) -> str:
    """Content-addressed processing-run identity.

    A rerun over the same inputs, algorithm revision, parameters and code
    revision converges on the same run identity, which is what makes artifact
    and metric persistence idempotent.
    """
    identity = json.dumps(
        {
            "dataset_id": dataset_id,
            "algorithm_id": algorithm_id,
            "version": version,
            "parameters_hash": parameters_hash,
            "input_checksums": sorted(input_checksums),
            "code_sha": code_sha,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"run-{hashlib.sha256(identity).hexdigest()[:16]}"
