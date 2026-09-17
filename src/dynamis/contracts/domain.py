"""Canonical DynamisData domain contracts.

This module is the single domain authority. Every entity, value object and
invariant lives here exactly once; registry loading, SQLAlchemy tables, Arrow
schemas, adapters and processors all import from it.

Hierarchy (V1 Authority, section 3)::

    DatasetSource -> DatasetVersion -> Subject -> Session -> Trial/Period
        -> Device -> SensorStream -> SampleArtifact -> ProcessingRun
        -> DerivedMetric

Non-negotiable semantics encoded below:

* identities are dataset-scoped: subjects are never merged across unrelated
  datasets;
* a collective session (football match) carries many participants through
  :class:`SessionParticipant`, so one match identity is never duplicated per
  player;
* algorithm and metric definitions are global scientific definitions, not
  artifacts artificially owned by one dataset;
* every derived result binds input checksums, algorithm identity, parameters
  hash, code Git SHA and the processing-run identity.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any, Literal, Self
from uuid import uuid4

from pydantic import AwareDatetime, Field, HttpUrl, model_validator

from dynamis.contracts.base import (
    MD5,
    REGISTRY_SCHEMA_VERSION,
    SHA1,
    SHA256,
    Contract,
    DatasetId,
    GitSHA,
    Identifier,
)
from dynamis.contracts.enums import (
    AlgorithmKind,
    ArtifactFormat,
    ArtifactLayer,
    Compression,
    LicenseStatus,
    MeasurementClass,
    MetricValueKind,
    Modality,
    ParticipantRole,
    ProcessingStatus,
    QualityState,
    RedistributionPolicy,
    RetrievalStatus,
    SessionKind,
    Severity,
)
from dynamis.contracts.units import assert_si_unit

Md5Value = MD5 | Literal["unknown"]
Sha1Value = SHA1 | Literal["unknown"]
Sha256Value = SHA256 | Literal["unknown"]
Sex = Literal["male", "female", "unspecified"]

_JSON = dict[str, Any]


# ---------------------------------------------------------------------------
# Rights
# ---------------------------------------------------------------------------


class LicensePolicy(Contract):
    """Rights and redistribution policy for one external source.

    ``unclear`` rights are represented honestly: no asserted identifier, local
    use only, redistribution prohibited.
    """

    identifier: str | None
    status: LicenseStatus
    attribution_required: bool
    noncommercial_only: bool
    share_alike: bool
    redistribution: RedistributionPolicy
    local_only: bool
    restrictions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def check_rights(self) -> Self:
        if self.status is LicenseStatus.UNCLEAR:
            if self.identifier is not None or not self.local_only:
                raise ValueError("unclear rights require no asserted license and local-only use")
            if self.redistribution is not RedistributionPolicy.PROHIBITED:
                raise ValueError("unclear rights prohibit redistribution of source and derivatives")
        elif not self.identifier:
            raise ValueError("declared rights require a license identifier")
        if self.local_only and self.redistribution is not RedistributionPolicy.PROHIBITED:
            raise ValueError("local-only data cannot be redistributed")
        if self.identifier:
            if "NC" in self.identifier and not self.noncommercial_only:
                raise ValueError("an NC license requires the noncommercial restriction")
            if "SA" in self.identifier and not self.share_alike:
                raise ValueError("an SA license requires the share-alike restriction")
        return self

    @property
    def policy_id(self) -> str:
        """Content-addressed identity so identical policies are never duplicated."""
        digest = hashlib.sha256(self.model_dump_json().encode("utf-8")).hexdigest()
        return f"lic-{digest[:32]}"


# ---------------------------------------------------------------------------
# Registry: source, version, retrieval
# ---------------------------------------------------------------------------


class RetrievalFile(Contract):
    """One expected upstream file for a dataset version.

    Each checksum field carries only its own algorithm: a 40-hex value belongs in
    ``sha1`` (source-provided SHA-1 or git blob identity), never in ``sha256``.
    ``local_sha256`` is the checksum computed on this machine after acquisition.
    """

    key: str = Field(min_length=1)
    size_bytes: int | None = Field(default=None, gt=0)
    md5: Md5Value = "unknown"
    sha1: Sha1Value = "unknown"
    sha256: Sha256Value = "unknown"
    local_sha256: SHA256 | None = None
    retrieved_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def check_file(self) -> Self:
        if self.local_sha256 is not None and self.retrieved_at is None:
            raise ValueError("a locally computed checksum requires a retrieval timestamp")
        return self


class RetrievalState(Contract):
    status: RetrievalStatus = RetrievalStatus.NOT_FETCHED
    retrieved_at: AwareDatetime | None = None
    files: tuple[RetrievalFile, ...] = ()

    @model_validator(mode="after")
    def check_retrieval(self) -> Self:
        if self.status is RetrievalStatus.FETCHED:
            if self.retrieved_at is None:
                raise ValueError("a fetched dataset version requires retrieved_at")
            if not self.files:
                raise ValueError("a fetched dataset version requires at least one file record")
        if self.status is RetrievalStatus.NOT_FETCHED:
            if self.retrieved_at is not None:
                raise ValueError("a not-fetched dataset version cannot carry retrieved_at")
            if any(file.retrieved_at is not None for file in self.files):
                raise ValueError("a not-fetched dataset version cannot carry per-file retrieval")
            if any(file.local_sha256 is not None for file in self.files):
                raise ValueError("a not-fetched dataset version cannot carry local checksums")
        return self


class DatasetVersion(Contract):
    """One version/revision of a dataset source.

    ``dataset_id`` may be omitted inside a nested registry document, where the
    parent :class:`DatasetSource` supplies it; :class:`DatasetSource` normalizes
    every version to carry the dataset identity explicitly, because stand-alone
    versions (manifests, database rows) must never lose their dataset scope.
    """

    dataset_id: DatasetId | None = None
    version: Identifier
    release_date: date | None = None
    upstream_url: HttpUrl
    citation: str | None = None
    optional: bool = False
    retrieval: RetrievalState = RetrievalState()


class DatasetSource(Contract):
    dataset_id: DatasetId
    name: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    upstream_urls: tuple[HttpUrl, ...] = Field(min_length=1)
    doi: str | None = None
    domain: str = Field(min_length=1)
    modalities: tuple[Modality, ...] = Field(min_length=1)
    adapter_id: Identifier
    v1_role: str = Field(min_length=1)
    initial_scope: str = Field(min_length=1)
    license: LicensePolicy
    versions: tuple[DatasetVersion, ...] = ()

    @model_validator(mode="after")
    def check_source(self) -> Self:
        seen: set[str] = set()
        normalized: list[DatasetVersion] = []
        for version in self.versions:
            if version.dataset_id is None:
                version = version.model_copy(update={"dataset_id": self.dataset_id})
            elif version.dataset_id != self.dataset_id:
                raise ValueError(
                    f"version {version.version!r} declares dataset_id "
                    f"{version.dataset_id!r} != {self.dataset_id!r}"
                )
            if version.version in seen:
                raise ValueError(f"duplicate dataset version {version.version!r}")
            seen.add(version.version)
            normalized.append(version)
        if len(set(self.modalities)) != len(self.modalities):
            raise ValueError("duplicate modalities on a dataset source")
        if tuple(normalized) != self.versions:
            return self.model_copy(update={"versions": tuple(normalized)})
        return self

    def version(self, version: str) -> DatasetVersion:
        for candidate in self.versions:
            if candidate.version == version:
                return candidate
        raise KeyError(f"{self.dataset_id} has no version {version!r}")


class DatasetRegistry(Contract):
    schema_version: str = Field(default=REGISTRY_SCHEMA_VERSION, min_length=1)
    distribution_rule: str = ""
    sources: tuple[DatasetSource, ...] = ()

    @model_validator(mode="after")
    def check_registry(self) -> Self:
        identifiers = [source.dataset_id for source in self.sources]
        duplicates = sorted({item for item in identifiers if identifiers.count(item) > 1})
        if duplicates:
            raise ValueError(f"duplicate dataset_id values in registry: {duplicates}")
        return self

    def source(self, dataset_id: str) -> DatasetSource:
        for source in self.sources:
            if source.dataset_id == dataset_id:
                return source
        raise KeyError(dataset_id)


# ---------------------------------------------------------------------------
# Scientific structure
# ---------------------------------------------------------------------------


class Subject(Contract):
    """Dataset-scoped participant identity. Subjects are never merged across sources."""

    dataset_id: DatasetId
    subject_id: Identifier
    sex: Sex = "unspecified"
    cohort: str | None = None
    notes: str | None = None


class Protocol(Contract):
    protocol_id: Identifier
    name: str = Field(min_length=1)
    description: str | None = None
    spec: _JSON = Field(default_factory=dict)
    citation: str | None = None


class Session(Contract):
    """A session may be individual or collective.

    Collective sessions (a match, a team training day) carry their subjects
    through :class:`SessionParticipant`; the session itself never asserts a
    single ``subject_id``.
    """

    dataset_id: DatasetId
    session_id: Identifier
    kind: SessionKind = SessionKind.UNKNOWN
    protocol_id: Identifier | None = None
    label: str | None = None
    started_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    venue: str | None = None

    @model_validator(mode="after")
    def check_session(self) -> Self:
        if self.started_at is not None and self.ended_at is not None:
            if self.ended_at < self.started_at:
                raise ValueError("session ended_at cannot precede started_at")
        return self


class SessionParticipant(Contract):
    """Explicit many-to-many participation between sessions and subjects."""

    dataset_id: DatasetId
    session_id: Identifier
    subject_id: Identifier
    role: ParticipantRole = ParticipantRole.PARTICIPANT
    group_label: str | None = None


class Trial(Contract):
    """A trial, rep, period or half. ``subject_id`` stays optional because a match
    period is not owned by one participant."""

    dataset_id: DatasetId
    session_id: Identifier
    trial_id: Identifier
    subject_id: Identifier | None = None
    parent_trial_id: Identifier | None = None
    label: str | None = None
    started_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def check_trial(self) -> Self:
        if self.parent_trial_id == self.trial_id:
            raise ValueError("a trial cannot be its own parent")
        if self.started_at is not None and self.ended_at is not None:
            if self.ended_at < self.started_at:
                raise ValueError("trial ended_at cannot precede started_at")
        return self


class Device(Contract):
    dataset_id: DatasetId
    device_id: Identifier
    device_type: str | None = None
    vendor: str | None = None
    model: str | None = None
    specs: _JSON = Field(default_factory=dict)


class SensorStream(Contract):
    """A concrete stream of samples on a session, with declared clock, frame and
    synchronization. Multi-subject streams (optical tracking) leave
    ``subject_id`` unset and carry identity per sample."""

    dataset_id: DatasetId
    session_id: Identifier
    stream_id: Identifier
    modality: Modality
    measurement_class: MeasurementClass
    clock_id: Identifier
    synchronization_spec_id: Identifier
    trial_id: Identifier | None = None
    subject_id: Identifier | None = None
    device_id: Identifier | None = None
    coordinate_frame_id: Identifier | None = None
    skeleton_id: Identifier | None = None
    nominal_sampling_rate_hz: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    si_units: tuple[str, ...] = ()
    source_unit: str | None = None
    stream_metadata: _JSON = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_stream(self) -> Self:
        for unit in self.si_units:
            assert_si_unit(unit, field_name="SensorStream.si_units")
        if self.modality is Modality.POSE and self.skeleton_id is None:
            raise ValueError("a pose stream must declare the skeleton authority it uses")
        if self.modality is not Modality.POSE and self.skeleton_id is not None:
            raise ValueError("skeleton_id is only meaningful for pose streams")
        return self


class SampleArtifact(Contract):
    """A materialized canonical sample file plus its provenance."""

    artifact_id: Identifier
    dataset_id: DatasetId
    session_id: Identifier
    stream_id: Identifier
    layer: ArtifactLayer
    relative_path: str = Field(min_length=1)
    format: ArtifactFormat = ArtifactFormat.PARQUET
    compression: Compression = Compression.ZSTD
    row_count: int = Field(ge=0)
    byte_size: int = Field(gt=0)
    checksum_sha256: SHA256
    schema_version: str = Field(min_length=1)
    schema_fingerprint: SHA256 | None = None
    partition: dict[str, str] = Field(default_factory=dict)
    coordinate_frame_id: Identifier | None = None
    synchronization_spec_id: Identifier | None = None
    created_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def check_artifact(self) -> Self:
        if self.format is ArtifactFormat.PARQUET and self.compression is not Compression.ZSTD:
            raise ValueError(
                "canonical dense data is Parquet-first: a Parquet artifact must use Zstd "
                f"compression, not {self.compression.value!r}"
            )
        if self.layer is ArtifactLayer.GOLD and not self.partition:
            raise ValueError("a gold artifact must declare the partition it belongs to")
        return self


# ---------------------------------------------------------------------------
# Processing and provenance
# ---------------------------------------------------------------------------


class AlgorithmSpec(Contract):
    """Revision of a deterministic algorithm. Global, never dataset-owned."""

    algorithm_id: Identifier
    name: str = Field(min_length=1)
    version: Identifier
    kind: AlgorithmKind
    code_git_sha: GitSHA | None = None
    parameters: _JSON = Field(default_factory=dict)
    parameters_hash: SHA256 | None = None
    description: str | None = None
    citation: str | None = None

    @model_validator(mode="after")
    def check_algorithm(self) -> Self:
        if self.parameters and self.parameters_hash is None:
            raise ValueError(
                "an algorithm with parameters must bind a parameters_hash for reproducibility"
            )
        return self


class ProcessingInput(Contract):
    """One input bound to a processing run or derived metric, by checksum."""

    artifact_id: Identifier
    checksum_sha256: SHA256
    role: str = Field(min_length=1)


class ProcessingRun(Contract):
    run_id: Identifier
    dataset_id: DatasetId
    algorithm_id: Identifier
    status: ProcessingStatus = ProcessingStatus.RUNNING
    code_git_sha: GitSHA | None = None
    parameters_hash: SHA256 | None = None
    dagster_run_id: Identifier | None = None
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    inputs: tuple[ProcessingInput, ...] = Field(min_length=1)
    notes: str | None = None

    @model_validator(mode="after")
    def check_run(self) -> Self:
        if self.status is ProcessingStatus.COMPLETED and self.completed_at is None:
            raise ValueError("a completed processing run requires completed_at")
        if self.started_at is not None and self.completed_at is not None:
            if self.completed_at < self.started_at:
                raise ValueError("processing run completed_at cannot precede started_at")
        return self

    @staticmethod
    def new_run_id() -> str:
        return f"run-{uuid4().hex[:16]}"


class ProcessingArtifact(Contract):
    artifact_id: Identifier
    dataset_id: DatasetId
    run_id: Identifier
    artifact_type: str = Field(min_length=1)
    layer: ArtifactLayer
    relative_path: str = Field(min_length=1)
    checksum_sha256: SHA256
    byte_size: int | None = Field(default=None, gt=0)
    row_count: int | None = Field(default=None, ge=0)
    created_at: AwareDatetime | None = None
    artifact_metadata: _JSON = Field(default_factory=dict)


class QualityIssue(Contract):
    """A quarantined or flagged record. Invalid records are never silently dropped."""

    issue_id: Identifier
    dataset_id: DatasetId
    rule: str = Field(min_length=1)
    severity: Severity
    state: QualityState = QualityState.QUARANTINED
    run_id: Identifier | None = None
    session_id: Identifier | None = None
    stream_id: Identifier | None = None
    subject_id: Identifier | None = None
    trial_id: Identifier | None = None
    sample_index: int | None = Field(default=None, ge=0)
    evidence: _JSON = Field(default_factory=dict)
    detected_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def check_issue(self) -> Self:
        if not self.evidence:
            raise ValueError("a quality issue must carry evidence")
        if self.severity is Severity.INFO and self.state is QualityState.QUARANTINED:
            raise ValueError("informational findings are not quarantined; use WARNING or ERROR")
        if self.state is QualityState.QUARANTINED and self.sample_index is None:
            if self.stream_id is None:
                raise ValueError(
                    "a quarantined record must locate the offending stream or sample_index"
                )
        return self


class MetricDefinition(Contract):
    """Global scientific definition of a derivable metric."""

    metric_id: Identifier
    name: str = Field(min_length=1)
    si_unit: str = "1"
    measurement_class: MeasurementClass
    value_kind: MetricValueKind = MetricValueKind.SCALAR
    description: str | None = None
    algorithm_id: Identifier | None = None

    @model_validator(mode="after")
    def check_metric(self) -> Self:
        assert_si_unit(self.si_unit, field_name="MetricDefinition.si_unit")
        if self.measurement_class is MeasurementClass.RAW_MEASURED:
            raise ValueError(
                "a derived metric cannot be RAW_MEASURED; use SOURCE_DERIVED or PIPELINE_DERIVED"
            )
        return self


class DerivedMetric(Contract):
    """A computed metric value bound to its full provenance chain."""

    derived_metric_id: Identifier
    dataset_id: DatasetId
    metric_id: Identifier
    run_id: Identifier
    si_unit: str
    measurement_class: MeasurementClass
    value_num: float | None = None
    value_json: _JSON | None = None
    subject_id: Identifier | None = None
    session_id: Identifier | None = None
    trial_id: Identifier | None = None
    stream_id: Identifier | None = None
    computed_at: AwareDatetime | None = None
    inputs: tuple[ProcessingInput, ...] = Field(min_length=1)
    provenance: _JSON = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_metric_value(self) -> Self:
        assert_si_unit(self.si_unit, field_name="DerivedMetric.si_unit")
        if (self.value_num is None) == (self.value_json is None):
            raise ValueError("exactly one of value_num or value_json must be provided")
        if self.measurement_class is MeasurementClass.RAW_MEASURED:
            raise ValueError("a derived metric cannot be RAW_MEASURED")
        if self.computed_at is None:
            raise ValueError("a derived metric requires computed_at")
        return self

    @property
    def input_checksums(self) -> tuple[str, ...]:
        return tuple(item.checksum_sha256 for item in self.inputs)
