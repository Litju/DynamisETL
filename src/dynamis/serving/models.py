"""Typed serving contracts for the DynamisData analytical API.

FastAPI OpenAPI is the schema authority; the browser client is generated from
it, so these models are the single source of API shape. Every model preserves the
scientific envelope: measurement class, units, algorithm identity, run identity,
quality and rights context are part of the response, never hidden defaults.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

ServingSource = Literal["gold", "control_plane"]


class LicenseView(BaseModel):
    """Declared license/rights policy as stored by the rights authority."""

    policy_id: str
    identifier: str | None
    status: str
    attribution_required: bool
    noncommercial_only: bool
    share_alike: bool
    redistribution: str
    local_only: bool
    restrictions: list[Any]
    notice: str


class DatasetVersionView(BaseModel):
    version: str
    release_date: str | None
    upstream_url: str
    citation: str | None
    retrieval_status: str
    retrieved_at: str | None


class DatasetSummary(BaseModel):
    dataset_id: str
    name: str
    provider: str
    domain: str
    doi: str | None
    upstream_urls: list[str]
    modalities: list[str]
    license: LicenseView
    version_count: int
    session_count: int
    subject_count: int
    trial_count: int
    stream_count: int
    metric_count: int
    quality_issue_count: int


class DatasetDetail(DatasetSummary):
    versions: list[DatasetVersionView]
    v1_role: str
    initial_scope: str
    adapter_id: str


class SubjectView(BaseModel):
    subject_id: str
    sex: str
    cohort: str | None


class TrialView(BaseModel):
    trial_id: str
    subject_id: str | None
    parent_trial_id: str | None
    label: str | None
    started_at: str | None
    ended_at: str | None


class StreamView(BaseModel):
    stream_id: str
    modality: str
    measurement_class: str
    subject_id: str | None
    trial_id: str | None
    device_id: str | None
    nominal_sampling_rate_hz: float | None
    si_units: list[str]
    source_unit: str | None
    coordinate_frame_id: str | None
    synchronization_spec_id: str
    clock_id: str
    skeleton_id: str | None
    sample_artifact_ids: list[str]
    sample_row_count: int


class SessionSummary(BaseModel):
    session_id: str
    kind: str
    label: str | None
    started_at: str | None
    ended_at: str | None
    participant_count: int
    trial_count: int
    stream_count: int


class SessionParticipantView(BaseModel):
    subject_id: str
    role: str
    group_label: str | None


class SessionDetail(BaseModel):
    dataset_id: str
    session: SessionSummary
    participants: list[SessionParticipantView]
    trials: list[TrialView]
    streams: list[StreamView]


class MetricValue(BaseModel):
    """One derived metric value with its full provenance envelope."""

    derived_metric_id: str
    dataset_id: str
    metric_id: str
    metric_name: str | None
    metric_description: str | None
    si_unit: str
    measurement_class: str
    value_kind: str
    value_num: float | None
    value_json: dict[str, Any] | None
    subject_id: str | None
    session_id: str | None
    trial_id: str | None
    stream_id: str | None
    entity_id: str | None
    algorithm_id: str | None
    algorithm_version: str | None
    parameters_hash: str | None
    code_git_sha: str | None
    run_id: str
    computed_at: str | None
    provenance: dict[str, Any]


class MetricPage(BaseModel):
    source: ServingSource
    total: int
    limit: int
    offset: int
    rows: list[MetricValue]


class MetricDefinitionView(BaseModel):
    metric_id: str
    name: str
    si_unit: str
    measurement_class: str
    value_kind: str
    description: str | None
    algorithm_id: str | None


class AlgorithmView(BaseModel):
    algorithm_id: str
    name: str
    version: str
    kind: str
    code_git_sha: str | None
    parameters_hash: str | None
    parameters: dict[str, Any]
    description: str | None
    citation: str | None


class MetricMethodology(BaseModel):
    metric: MetricDefinitionView
    algorithm: AlgorithmView | None
    measurement_class_semantics: str
    measurement_class_never_means: list[str]
    provenance_fields: list[str]


class ProvenanceNode(BaseModel):
    id: str
    kind: str
    label: str
    status: str | None = None
    measurement_class: str | None = None
    details: dict[str, Any]


class ProvenanceEdge(BaseModel):
    id: str
    source: str
    target: str
    label: str


class ProvenanceGraph(BaseModel):
    derived_metric_id: str
    nodes: list[ProvenanceNode]
    edges: list[ProvenanceEdge]
    provenance: dict[str, Any]
    lineage_note: str


class QualityIssueView(BaseModel):
    issue_id: str
    dataset_id: str
    run_id: str | None
    session_id: str | None
    stream_id: str | None
    subject_id: str | None
    trial_id: str | None
    sample_index: int | None
    rule: str
    severity: str
    state: str
    evidence: dict[str, Any]
    detected_at: str | None


class QualityIssuePage(BaseModel):
    total: int
    limit: int
    offset: int
    rows: list[QualityIssueView]


class RunView(BaseModel):
    run_id: str
    dataset_id: str
    algorithm_id: str
    algorithm_name: str | None
    algorithm_version: str | None
    kind: str | None
    status: str
    code_git_sha: str | None
    parameters_hash: str | None
    started_at: str | None
    completed_at: str | None
    input_checksums: list[str]
    metric_count: int
    artifact_count: int
    notes: str | None


class RunPage(BaseModel):
    total: int
    limit: int
    offset: int
    rows: list[RunView]


class RightsPolicyView(BaseModel):
    license: LicenseView
    dataset_ids: list[str]


class RightsPage(BaseModel):
    policies: list[RightsPolicyView]


class ReductionInfo(BaseModel):
    """Explicit display-reduction record; never a scientific transformation."""

    method: str
    parameters: dict[str, Any]
    source_points: int
    returned_points: int
    note: str


class ArtifactRefView(BaseModel):
    artifact_id: str
    dataset_id: str
    stream_id: str | None
    layer: str
    relative_path: str
    format: str
    compression: str | None
    checksum_sha256: str
    row_count: int
    byte_size: int | None
    artifact_kind: Literal["sample", "processing"]
    modality: str | None
    measurement_class: str | None
    si_units: list[str]
    coordinate_frame_id: str | None
    synchronization_spec_id: str | None


class DenseWindowMeta(BaseModel):
    artifact: ArtifactRefView
    from_ns: int
    to_ns: int
    columns: list[str]
    source_rows: int
    returned_rows: int
    canonical_time_min_ns: int | None
    canonical_time_max_ns: int | None
    reduction: ReductionInfo | None
    units: dict[str, str]
    coordinate_frame_id: str | None
    measurement_class: str | None
    display_note: str


class DenseWindow(BaseModel):
    meta: DenseWindowMeta
    rows: list[dict[str, Any]]


class ServingStatus(BaseModel):
    database: Literal["ok", "unavailable"]
    db_schema: str
    gold_schema: str
    gold_published: bool
    dataset_count: int
    metric_count: int
    run_count: int
    quality_issue_count: int


class HealthStatus(BaseModel):
    status: Literal["ok"]
    version: str

    model_config = ConfigDict(extra="forbid")
