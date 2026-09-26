"""Versioned sports, catalog, grain, capability, space and clock contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from typing import Any

import pyarrow as pa
from pydantic import AwareDatetime, Field, HttpUrl, model_validator

from dynamis.contracts.base import Contract, Identifier, PositiveFloat


class EditionKind(StrEnum):
    LEAGUE_SEASON = "league_season"
    TOURNAMENT = "tournament"
    OTHER = "other"


class PeriodKind(StrEnum):
    HALF = "half"
    QUARTER = "quarter"
    PERIOD = "period"
    OVERTIME = "overtime"
    SET = "set"
    INNING = "inning"
    OTHER = "other"


class ContestSide(StrEnum):
    HOME = "home"
    AWAY = "away"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class SportsEntityKind(StrEnum):
    COMPETITION = "competition"
    EDITION = "edition"
    TEAM = "team"
    CONTEST = "contest"
    SUBJECT = "subject"


class DataGrainKind(StrEnum):
    FRAME_SERIES = "FRAME_SERIES"
    JOINT_FRAME_SERIES = "JOINT_FRAME_SERIES"
    EVENT_SERIES = "EVENT_SERIES"
    PLAY_BY_PLAY = "PLAY_BY_PLAY"
    GAME_SUMMARY = "GAME_SUMMARY"
    PLAYER_GAME = "PLAYER_GAME"
    TEAM_GAME = "TEAM_GAME"
    PLAYER_SEASON = "PLAYER_SEASON"
    TEAM_SEASON = "TEAM_SEASON"
    TRIAL_SERIES = "TRIAL_SERIES"
    SENSOR_SERIES = "SENSOR_SERIES"


GRAIN_AXES: dict[DataGrainKind, tuple[str, ...]] = {
    DataGrainKind.FRAME_SERIES: ("contest", "period", "canonical_time", "entity"),
    DataGrainKind.JOINT_FRAME_SERIES: ("contest", "period", "canonical_time", "subject", "joint"),
    DataGrainKind.EVENT_SERIES: ("contest", "period", "sequence_index"),
    DataGrainKind.PLAY_BY_PLAY: ("contest", "period", "sequence_index"),
    DataGrainKind.GAME_SUMMARY: ("contest",),
    DataGrainKind.PLAYER_GAME: ("subject", "contest"),
    DataGrainKind.TEAM_GAME: ("team", "contest"),
    DataGrainKind.PLAYER_SEASON: ("subject", "team", "competition_edition"),
    DataGrainKind.TEAM_SEASON: ("team", "competition_edition"),
    DataGrainKind.TRIAL_SERIES: ("subject", "trial", "sample_index"),
    DataGrainKind.SENSOR_SERIES: ("subject", "stream", "canonical_time"),
}

# Logical V4 axes map to existing canonical Arrow column names. Adapters may
# use the canonical axis name directly when a provider schema already has it.
GRAIN_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "contest": ("contest_id", "session_id"),
    "period": ("contest_period_id", "period_id", "trial_id"),
    "canonical_time": ("canonical_time_ns", "t_rel_ns"),
    "entity": ("entity_id", "object_id"),
    "subject": ("subject_id",),
    "joint": ("joint_id",),
    "sequence_index": ("sequence_index", "event_index", "event_id"),
    "team": ("team_id",),
    "competition_edition": ("competition_edition_id",),
    "trial": ("trial_id",),
    "sample_index": ("sample_index",),
    "stream": ("stream_id",),
    "position_group": ("position_group",),
}


class Sport(Contract):
    sport_id: Identifier
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str = Field(min_length=1)


class Competition(Contract):
    competition_id: Identifier
    sport_id: Identifier
    name: str = Field(min_length=1)


class CompetitionEdition(Contract):
    edition_id: Identifier
    competition_id: Identifier
    label: str = Field(min_length=1)
    kind: EditionKind
    starts_on: date | None = None
    ends_on: date | None = None

    @model_validator(mode="after")
    def check_date_order(self) -> CompetitionEdition:
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("competition edition ends before it starts")
        return self


class Team(Contract):
    team_id: Identifier
    sport_id: Identifier
    display_name: str = Field(min_length=1)


class Contest(Contract):
    contest_id: Identifier
    sport_id: Identifier
    competition_edition_id: Identifier | None = None
    scheduled_start_at: AwareDatetime | None = None
    actual_start_at: AwareDatetime | None = None
    venue: str | None = None
    home_away_supported: bool = False
    source_authority: str = Field(min_length=1)


class ContestTeam(Contract):
    contest_id: Identifier
    team_id: Identifier
    side: ContestSide
    side_order: int | None = Field(default=None, ge=0)
    score: int | None = Field(default=None, ge=0)


class ContestPeriod(Contract):
    contest_period_id: Identifier
    contest_id: Identifier
    source_period_number: Identifier
    kind: PeriodKind = PeriodKind.OTHER
    label: str | None = None
    provider_namespace: str | None = None
    start_ns: int | None = None
    end_ns: int | None = None

    @model_validator(mode="after")
    def check_time_order(self) -> ContestPeriod:
        if self.start_ns is not None and self.end_ns is not None and self.end_ns < self.start_ns:
            raise ValueError("contest period ends before it starts")
        return self


class TeamRosterMembership(Contract):
    dataset_id: Identifier
    subject_id: Identifier
    team_id: Identifier
    competition_edition_id: Identifier
    valid_from: date | None = None
    valid_to: date | None = None

    @model_validator(mode="after")
    def check_validity(self) -> TeamRosterMembership:
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("roster membership ends before it starts")
        return self


class SessionSportContext(Contract):
    dataset_id: Identifier
    session_id: Identifier
    contest_id: Identifier
    source_catalog_entry_id: Identifier | None = None


class ProviderIdentityCrosswalk(Contract):
    provider_namespace: Identifier
    entity_kind: SportsEntityKind
    provider_entity_id: Identifier
    canonical_entity_id: Identifier
    valid_from: AwareDatetime | None = None
    valid_to: AwareDatetime | None = None
    source_authority: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_validity(self) -> ProviderIdentityCrosswalk:
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("crosswalk validity ends before it starts")
        return self


class SportsContext(Contract):
    """One adapter-authoritative contest context over generic scientific rows."""

    sport: Sport
    competition: Competition | None = None
    edition: CompetitionEdition | None = None
    teams: tuple[Team, ...] = ()
    contest: Contest
    contest_teams: tuple[ContestTeam, ...] = ()
    periods: tuple[ContestPeriod, ...] = ()
    roster_memberships: tuple[TeamRosterMembership, ...] = ()
    session: SessionSportContext
    crosswalks: tuple[ProviderIdentityCrosswalk, ...] = ()

    @model_validator(mode="after")
    def check_references(self) -> SportsContext:
        if self.contest.sport_id != self.sport.sport_id:
            raise ValueError("contest sport does not match its SportsContext")
        if self.competition and self.competition.sport_id != self.sport.sport_id:
            raise ValueError("competition sport does not match its SportsContext")
        if self.edition:
            if (
                self.competition is None
                or self.edition.competition_id != self.competition.competition_id
            ):
                raise ValueError("competition edition requires its matching competition")
            if self.contest.competition_edition_id != self.edition.edition_id:
                raise ValueError("contest edition does not match its SportsContext")
        team_ids = {team.team_id for team in self.teams}
        if any(item.contest_id != self.contest.contest_id for item in self.contest_teams):
            raise ValueError("contest-team participation references another contest")
        if any(item.team_id not in team_ids for item in self.contest_teams):
            raise ValueError("contest-team participation references an undeclared team")
        if any(item.contest_id != self.contest.contest_id for item in self.periods):
            raise ValueError("contest period references another contest")
        if self.session.contest_id != self.contest.contest_id:
            raise ValueError("session sport context references another contest")
        return self


class DataGrain(Contract):
    kind: DataGrainKind
    axes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def check_axes(self) -> DataGrain:
        expected = GRAIN_AXES[self.kind]
        if not self.axes:
            object.__setattr__(self, "axes", expected)
        elif self.kind is DataGrainKind.TRIAL_SERIES:
            if (
                self.axes[: len(expected)] != expected
                or len(self.axes) > len(expected) + 1
                or any(axis != "joint" for axis in self.axes[len(expected) :])
            ):
                raise ValueError(
                    "TRIAL_SERIES axes are subject/trial/sample_index with optional joint"
                )
        elif self.kind is DataGrainKind.PLAYER_SEASON:
            if (
                self.axes[: len(expected)] != expected
                or len(self.axes) > len(expected) + 1
                or any(axis != "position_group" for axis in self.axes[len(expected) :])
            ):
                raise ValueError(
                    "PLAYER_SEASON axes are subject/team/competition_edition "
                    "with optional position_group"
                )
        elif self.axes != expected:
            raise ValueError(f"{self.kind.value} axes must be {expected}")
        if len(self.axes) != len(set(self.axes)):
            raise ValueError("data grain axes must be unique")
        return self


def validate_grain_rows(grain: DataGrain, rows: Iterable[Mapping[str, Any]]) -> None:
    """Reject missing/null axes and duplicate logical row keys."""
    seen: set[tuple[Any, ...]] = set()
    axes = grain.axes
    for index, row in enumerate(rows):
        missing = [axis for axis in axes if axis not in row]
        if missing:
            raise ValueError(f"{grain.kind.value} row {index} is missing axes {missing}")
        key = tuple(row[axis] for axis in axes)
        if any(value is None for value in key):
            raise ValueError(f"{grain.kind.value} row {index} has a null grain axis")
        try:
            duplicate = key in seen
            seen.add(key)
        except TypeError as exc:
            raise ValueError(f"{grain.kind.value} axes must be scalar values") from exc
        if duplicate:
            raise ValueError(f"duplicate {grain.kind.value} key: {key!r}")


def grain_columns(grain: DataGrain, column_names: Iterable[str]) -> tuple[str, ...]:
    names = set(column_names)
    resolved: list[str] = []
    for axis in grain.axes:
        column = next((name for name in GRAIN_COLUMN_ALIASES[axis] if name in names), None)
        if column is None:
            raise ValueError(f"{grain.kind.value} requires a column for axis {axis!r}")
        resolved.append(column)
    return tuple(resolved)


def grain_schema_metadata(grain: DataGrain) -> dict[bytes, bytes]:
    return {
        b"dynamis.data_grain_version": b"1",
        b"dynamis.data_grain_kind": grain.kind.value.encode("ascii"),
        b"dynamis.data_grain_axes": json.dumps(grain.axes, separators=(",", ":")).encode(),
    }


def with_grain_metadata(schema: pa.Schema, grain: DataGrain) -> pa.Schema:
    metadata = dict(schema.metadata or {})
    metadata.update(grain_schema_metadata(grain))
    return schema.with_metadata(metadata)


def grain_artifact_layout(grain: DataGrain) -> tuple[str, tuple[str, ...]]:
    """Return the natural immutable artifact boundary and useful partitions."""
    if grain.kind in {DataGrainKind.FRAME_SERIES, DataGrainKind.JOINT_FRAME_SERIES}:
        return "contest-period-modality", ("sport", "provider_family", "competition_edition")
    if grain.kind in {DataGrainKind.EVENT_SERIES, DataGrainKind.PLAY_BY_PLAY}:
        return "season-or-release", ("sport", "provider_family", "competition_edition")
    if grain.kind in {DataGrainKind.PLAYER_SEASON, DataGrainKind.TEAM_SEASON}:
        return "competition-edition-aggregate-family", ("sport", "provider_family")
    return "accepted-stream-or-trial", ("sport", "provider_family", "grain_family")


class SourceObjectKind(StrEnum):
    CONTEST = "contest"
    SEASON_DATASET = "season_dataset"
    RELEASE_ASSET = "release_asset"
    AGGREGATE = "aggregate"


class SourceCatalogState(StrEnum):
    UPSTREAM_AVAILABLE = "UPSTREAM_AVAILABLE"
    REGISTERED = "REGISTERED"
    ACQUIRED = "ACQUIRED"
    MATERIALIZED = "MATERIALIZED"
    READY = "READY"
    ACQUISITION_FAILED = "ACQUISITION_FAILED"
    MATERIALIZATION_FAILED = "MATERIALIZATION_FAILED"
    VALIDATION_FAILED = "VALIDATION_FAILED"


class SourceCatalogEntry(Contract):
    entry_id: Identifier
    provider: str = Field(min_length=1)
    dataset: str = Field(min_length=1)
    registry_dataset_id: str | None = None
    registry_version: str | None = None
    registry_file_key: str | None = None
    external_id: str = Field(min_length=1)
    object_kind: SourceObjectKind
    sport_id: Identifier | None = None
    competition_id: Identifier | None = None
    competition_edition_id: Identifier | None = None
    teams: tuple[str, ...] = ()
    upstream_url: HttpUrl
    upstream_revision: str | None = None
    asset_identity: str | None = None
    expected_size_bytes: int | None = Field(default=None, gt=0)
    rights: dict[str, Any]
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    upstream_capabilities: tuple[str, ...] = ()
    discovered_at: AwareDatetime
    availability_state: SourceCatalogState = SourceCatalogState.REGISTERED
    failure_stage: str | None = None
    failure_evidence: dict[str, Any] | None = None

    @model_validator(mode="after")
    def check_failure_evidence(self) -> SourceCatalogEntry:
        failed = self.availability_state in {
            SourceCatalogState.ACQUISITION_FAILED,
            SourceCatalogState.MATERIALIZATION_FAILED,
            SourceCatalogState.VALIDATION_FAILED,
        }
        if failed != bool(self.failure_stage and self.failure_evidence):
            raise ValueError(
                "catalog failure states require stage and evidence; other states forbid them"
            )
        registered = (self.registry_dataset_id, self.registry_version, self.registry_file_key)
        if any(value is not None for value in registered) and not all(
            value is not None for value in registered
        ):
            raise ValueError("registered catalog file references require dataset, version and key")
        return self

    def transition(
        self, state: SourceCatalogState, *, evidence: dict[str, Any] | None = None
    ) -> SourceCatalogEntry:
        allowed = {
            SourceCatalogState.UPSTREAM_AVAILABLE: {SourceCatalogState.REGISTERED},
            SourceCatalogState.REGISTERED: {
                SourceCatalogState.ACQUIRED,
                SourceCatalogState.ACQUISITION_FAILED,
            },
            SourceCatalogState.ACQUISITION_FAILED: {SourceCatalogState.REGISTERED},
            SourceCatalogState.ACQUIRED: {
                SourceCatalogState.MATERIALIZED,
                SourceCatalogState.MATERIALIZATION_FAILED,
            },
            SourceCatalogState.MATERIALIZATION_FAILED: {SourceCatalogState.ACQUIRED},
            SourceCatalogState.MATERIALIZED: {
                SourceCatalogState.READY,
                SourceCatalogState.VALIDATION_FAILED,
            },
            SourceCatalogState.VALIDATION_FAILED: {SourceCatalogState.MATERIALIZED},
            SourceCatalogState.READY: set(),
        }
        if state not in allowed[self.availability_state]:
            raise ValueError(
                f"invalid source catalog transition {self.availability_state.value} -> "
                f"{state.value}"
            )
        if (
            state
            in {
                SourceCatalogState.ACQUISITION_FAILED,
                SourceCatalogState.MATERIALIZATION_FAILED,
                SourceCatalogState.VALIDATION_FAILED,
            }
            and not evidence
        ):
            raise ValueError("a failed source catalog transition requires evidence")
        return self.model_copy(
            update={
                "availability_state": state,
                "failure_stage": state.value.removesuffix("_FAILED").lower() if evidence else None,
                "failure_evidence": evidence,
            }
        )


class Capability(StrEnum):
    TRACKING = "TRACKING"
    BALL_TRACKING = "BALL_TRACKING"
    POSE = "POSE"
    EVENTS = "EVENTS"
    PHASES = "PHASES"
    PLAY_BY_PLAY = "PLAY_BY_PLAY"
    BOX_SCORE = "BOX_SCORE"
    LINEUP = "LINEUP"
    LOCOMOTOR = "LOCOMOTOR"
    TACTICAL = "TACTICAL"
    SEASON_AGGREGATE = "SEASON_AGGREGATE"
    FORCE = "FORCE"
    IMU = "IMU"
    LPT = "LPT"
    GNSS = "GNSS"


class CapabilityOrigin(StrEnum):
    SOURCE_CATALOG = "SOURCE_CATALOG"
    REGISTERED_STREAM = "REGISTERED_STREAM"
    MATERIALIZED_ARTIFACT = "MATERIALIZED_ARTIFACT"
    ACCEPTED_PROCESSOR = "ACCEPTED_PROCESSOR"
    MODEL_ESTIMATED = "MODEL_ESTIMATED"


class CapabilityScope(StrEnum):
    UPSTREAM = "UPSTREAM"
    REGISTERED = "REGISTERED"
    LOCAL = "LOCAL"


class CapabilityEvidence(Contract):
    capability: Capability
    origin: CapabilityOrigin
    scope: CapabilityScope
    evidence_id: Identifier
    source_authority: str = Field(min_length=1)


class CapabilityProfile(Contract):
    evidence: tuple[CapabilityEvidence, ...] = ()

    @classmethod
    def derive(cls, evidence: Iterable[CapabilityEvidence]) -> CapabilityProfile:
        unique = {
            (item.capability.value, item.origin.value, item.scope.value, item.evidence_id): item
            for item in evidence
        }
        ordered = tuple(unique[key] for key in sorted(unique))
        return cls(evidence=ordered)

    @property
    def upstream_capabilities(self) -> tuple[Capability, ...]:
        return tuple(
            sorted(
                {
                    item.capability
                    for item in self.evidence
                    if item.scope is CapabilityScope.UPSTREAM
                },
                key=str,
            )
        )

    @property
    def local_capabilities(self) -> tuple[Capability, ...]:
        return tuple(
            sorted(
                {item.capability for item in self.evidence if item.scope is CapabilityScope.LOCAL},
                key=str,
            )
        )

    @property
    def registered_capabilities(self) -> tuple[Capability, ...]:
        return tuple(
            sorted(
                {
                    item.capability
                    for item in self.evidence
                    if item.scope is CapabilityScope.REGISTERED
                },
                key=str,
            )
        )

    @property
    def model_estimated_capabilities(self) -> tuple[Capability, ...]:
        return tuple(
            sorted(
                {
                    item.capability
                    for item in self.evidence
                    if item.origin is CapabilityOrigin.MODEL_ESTIMATED
                },
                key=str,
            )
        )


class ProductSurface(StrEnum):
    MATCHLAB = "MatchLab"
    GAMELAB = "GameLab"
    SEASONLAB = "SeasonLab"
    PERFORMANCELAB = "PerformanceLab"


class ProductRoute(Contract):
    product: ProductSurface
    ready: bool
    missing_capabilities: tuple[tuple[Capability, ...], ...] = ()
    missing_grains: tuple[tuple[DataGrainKind, ...], ...] = ()


def route_products(
    profile: CapabilityProfile, grains: Iterable[DataGrainKind]
) -> tuple[ProductRoute, ...]:
    """Resolve all product gates using local evidence and declared grains only."""
    local = set(profile.local_capabilities)
    available_grains = set(grains)
    gates: tuple[
        tuple[
            ProductSurface,
            tuple[tuple[Capability, ...], ...],
            tuple[tuple[DataGrainKind, ...], ...],
        ],
        ...,
    ] = (
        (ProductSurface.MATCHLAB, ((Capability.TRACKING,),), ((DataGrainKind.FRAME_SERIES,),)),
        (
            ProductSurface.GAMELAB,
            ((Capability.PLAY_BY_PLAY, Capability.EVENTS),),
            ((DataGrainKind.PLAY_BY_PLAY, DataGrainKind.EVENT_SERIES),),
        ),
        (
            ProductSurface.SEASONLAB,
            ((Capability.SEASON_AGGREGATE,),),
            ((DataGrainKind.PLAYER_SEASON, DataGrainKind.TEAM_SEASON),),
        ),
        (
            ProductSurface.PERFORMANCELAB,
            ((Capability.FORCE, Capability.IMU, Capability.LPT, Capability.GNSS),),
            ((DataGrainKind.TRIAL_SERIES, DataGrainKind.SENSOR_SERIES),),
        ),
    )
    routes: list[ProductRoute] = []
    for product, capability_alternatives, grain_alternatives in gates:
        missing_caps = tuple(
            option for option in capability_alternatives if not local.intersection(option)
        )
        missing_grains = tuple(
            option for option in grain_alternatives if not available_grains.intersection(option)
        )
        routes.append(
            ProductRoute(
                product=product,
                ready=not missing_caps and not missing_grains,
                missing_capabilities=missing_caps,
                missing_grains=missing_grains,
            )
        )
    return tuple(routes)


def derive_capability_profile(
    *,
    upstream: Iterable[tuple[Capability, str]] = (),
    registered: Iterable[tuple[Capability, str]] = (),
    materialized: Iterable[tuple[Capability, str]] = (),
    accepted_processors: Iterable[tuple[Capability, str]] = (),
    model_estimated: Iterable[tuple[Capability, str, CapabilityScope]] = (),
) -> CapabilityProfile:
    """Build stable evidence from catalog, stream, artifact and processor facts."""
    evidence = [
        CapabilityEvidence(
            capability=capability,
            origin=CapabilityOrigin.SOURCE_CATALOG,
            scope=CapabilityScope.UPSTREAM,
            evidence_id=evidence_id,
            source_authority="source catalog",
        )
        for capability, evidence_id in upstream
    ]
    evidence.extend(
        CapabilityEvidence(
            capability=capability,
            origin=CapabilityOrigin.REGISTERED_STREAM,
            scope=CapabilityScope.REGISTERED,
            evidence_id=evidence_id,
            source_authority="registered stream",
        )
        for capability, evidence_id in registered
    )
    evidence.extend(
        CapabilityEvidence(
            capability=capability,
            origin=CapabilityOrigin.MATERIALIZED_ARTIFACT,
            scope=CapabilityScope.LOCAL,
            evidence_id=evidence_id,
            source_authority="materialized artifact",
        )
        for capability, evidence_id in materialized
    )
    evidence.extend(
        CapabilityEvidence(
            capability=capability,
            origin=CapabilityOrigin.ACCEPTED_PROCESSOR,
            scope=CapabilityScope.LOCAL,
            evidence_id=evidence_id,
            source_authority="accepted processor",
        )
        for capability, evidence_id in accepted_processors
    )
    evidence.extend(
        CapabilityEvidence(
            capability=capability,
            origin=CapabilityOrigin.MODEL_ESTIMATED,
            scope=scope,
            evidence_id=evidence_id,
            source_authority="model estimate",
        )
        for capability, evidence_id, scope in model_estimated
    )
    return CapabilityProfile.derive(evidence)


def capability_profile_from_records(
    *,
    catalog_entries: Iterable[SourceCatalogEntry] = (),
    registered_streams: Iterable[Any] = (),
    materialized_artifacts: Iterable[tuple[Any, Any]] = (),
    accepted_processors: Iterable[tuple[Any, Iterable[Capability]]] = (),
) -> CapabilityProfile:
    """Derive profiles from catalog, stream, artifact and processor records."""
    modality_capabilities = {
        "tracking": Capability.TRACKING,
        "pose": Capability.POSE,
        "event": Capability.EVENTS,
        "force": Capability.FORCE,
        "imu": Capability.IMU,
        "lpt": Capability.LPT,
        "gnss": Capability.GNSS,
    }

    def value(record: Any, field: str, default: Any = None) -> Any:
        if isinstance(record, Mapping):
            return record.get(field, default)
        return getattr(record, field, default)

    def is_estimated(record: Any) -> bool:
        measurement_class = value(record, "measurement_class")
        return getattr(measurement_class, "value", measurement_class) == "MODEL_ESTIMATED"

    evidence: list[CapabilityEvidence] = []
    for entry in catalog_entries:
        for name in value(entry, "upstream_capabilities", ()):
            try:
                capability = Capability(name)
            except ValueError:
                continue
            evidence.append(
                CapabilityEvidence(
                    capability=capability,
                    origin=CapabilityOrigin.SOURCE_CATALOG,
                    scope=CapabilityScope.UPSTREAM,
                    evidence_id=str(value(entry, "entry_id")),
                    source_authority="source catalog",
                )
            )
    for stream in registered_streams:
        modality = value(stream, "modality")
        modality = getattr(modality, "value", modality)
        capability = modality_capabilities.get(str(modality))
        if capability is None:
            continue
        estimated = is_estimated(stream)
        evidence.append(
            CapabilityEvidence(
                capability=capability,
                origin=(
                    CapabilityOrigin.MODEL_ESTIMATED
                    if estimated
                    else CapabilityOrigin.REGISTERED_STREAM
                ),
                scope=CapabilityScope.REGISTERED,
                evidence_id=str(value(stream, "stream_id")),
                source_authority="registered stream",
            )
        )
    for stream, artifact in materialized_artifacts:
        modality = value(stream, "modality")
        modality = getattr(modality, "value", modality)
        capability = modality_capabilities.get(str(modality))
        if capability is None:
            continue
        estimated = is_estimated(stream)
        evidence.append(
            CapabilityEvidence(
                capability=capability,
                origin=(
                    CapabilityOrigin.MODEL_ESTIMATED
                    if estimated
                    else CapabilityOrigin.MATERIALIZED_ARTIFACT
                ),
                scope=CapabilityScope.LOCAL,
                evidence_id=str(value(artifact, "artifact_id")),
                source_authority="materialized artifact",
            )
        )
    for processor, capabilities in accepted_processors:
        processor_id = str(value(processor, "algorithm_id", value(processor, "name", "processor")))
        processor_version = str(value(processor, "version", "1"))
        for capability in capabilities:
            evidence.append(
                CapabilityEvidence(
                    capability=capability,
                    origin=CapabilityOrigin.ACCEPTED_PROCESSOR,
                    scope=CapabilityScope.LOCAL,
                    evidence_id=f"{processor_id}:{processor_version}:{capability.value}",
                    source_authority="accepted processor",
                )
            )
    return CapabilityProfile.derive(evidence)


class SpatialReference(Contract):
    spatial_reference_id: Identifier
    version: str = Field(min_length=1)
    units: str = Field(min_length=1)
    origin: dict[str, float]
    axis_orientation: dict[str, str]
    handedness: str = Field(min_length=1)
    canonical_display_transform: dict[str, Any]
    source_transform: dict[str, Any]
    period_direction_semantics: dict[str, Any] = Field(default_factory=dict)


class SurfaceGeometry(Contract):
    surface_id: Identifier
    version: str = Field(min_length=1)
    sport_id: Identifier
    name: str = Field(min_length=1)
    dimensions: dict[str, PositiveFloat]
    spatial_reference_id: Identifier
    spatial_reference_version: str = Field(min_length=1)
    source_authority: str = Field(min_length=1)


class ClockDirection(StrEnum):
    MONOTONIC = "monotonic"
    COUNT_UP = "count_up"
    COUNT_DOWN = "count_down"


class ClockKind(StrEnum):
    MEDIA_TIME = "media_time"
    WALL_TIME = "wall_time"
    GAME_CLOCK = "game_clock"
    SHOT_CLOCK = "shot_clock"
    POSSESSION_CLOCK = "possession_clock"


class ClockMapping(Contract):
    mapping_id: Identifier
    version: str = Field(min_length=1)
    clock_kind: ClockKind
    direction: ClockDirection
    source_unit: str = Field(min_length=1)
    scale_to_ns: PositiveFloat
    source_origin: float | None = Field(default=None, allow_inf_nan=False)
    period_origin_ns: int
    offset_ns: int = 0
    authority: str = Field(min_length=1)
    evidence: dict[str, Any]

    @model_validator(mode="after")
    def require_countdown_origin(self) -> ClockMapping:
        if self.direction is ClockDirection.COUNT_DOWN and self.source_origin is None:
            raise ValueError("countdown clocks require an explicit source origin")
        if not self.evidence:
            raise ValueError("clock mappings require source evidence")
        return self

    def to_canonical_ns(self, source_value: int | float) -> int:
        elapsed = (
            Decimal(str(self.source_origin)) - Decimal(str(source_value))
            if self.direction is ClockDirection.COUNT_DOWN and self.source_origin is not None
            else Decimal(str(source_value))
        )
        scaled = elapsed * Decimal(str(self.scale_to_ns))
        return (
            self.period_origin_ns
            + self.offset_ns
            + int(scaled.to_integral_value(rounding=ROUND_HALF_EVEN))
        )


class EventEnvelope(Contract):
    contest_id: Identifier
    contest_period_id: Identifier
    sequence_index: Identifier
    source_event_id: Identifier
    provider_namespace: Identifier
    provider_event_type: str = Field(min_length=1)
    canonical_time_ns: int | None = None
    source_clock_json: dict[str, Any] | None = None
    team_id: Identifier | None = None
    subject_id: Identifier | None = None
    location: dict[str, float] | None = None
    spatial_reference_id: Identifier | None = None
    attributes_json: dict[str, Any] = Field(default_factory=dict)
    attributes_schema_id: Identifier
    attributes_schema_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_location_reference(self) -> EventEnvelope:
        if self.location is not None and (
            self.spatial_reference_id is None or not {"x", "y"} <= self.location.keys()
        ):
            raise ValueError("event locations require x/y and a declared spatial reference")
        if self.location is not None and set(self.location) - {"x", "y", "z"}:
            raise ValueError("event location supports only x, y and z in its declared reference")
        return self


class EventAttributeType(StrEnum):
    STRING = "string"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"
    NULL = "null"


class EventAttributeSchema(Contract):
    schema_id: Identifier
    version: str = Field(min_length=1)
    properties: dict[str, EventAttributeType]
    required: tuple[str, ...] = ()
    additional_properties: bool = False

    @model_validator(mode="after")
    def check_required_properties(self) -> EventAttributeSchema:
        if set(self.required) - self.properties.keys():
            raise ValueError("required event attributes must declare their value type")
        return self


def validate_event_attributes(
    event: EventEnvelope, schemas: Mapping[tuple[str, str], EventAttributeSchema]
) -> None:
    schema = schemas.get((event.attributes_schema_id, event.attributes_schema_version))
    if schema is None:
        raise ValueError(
            f"unknown event attribute schema "
            f"{event.attributes_schema_id}@{event.attributes_schema_version}"
        )
    values = event.attributes_json
    missing = set(schema.required) - values.keys()
    unknown = values.keys() - schema.properties.keys()
    if missing:
        raise ValueError(f"event attributes are missing required properties {sorted(missing)}")
    if unknown and not schema.additional_properties:
        raise ValueError(f"event attributes contain undeclared properties {sorted(unknown)}")
    type_check = {
        EventAttributeType.STRING: lambda value: isinstance(value, str),
        EventAttributeType.NUMBER: lambda value: (
            isinstance(value, (int, float)) and not isinstance(value, bool)
        ),
        EventAttributeType.INTEGER: lambda value: (
            isinstance(value, int) and not isinstance(value, bool)
        ),
        EventAttributeType.BOOLEAN: lambda value: isinstance(value, bool),
        EventAttributeType.OBJECT: lambda value: isinstance(value, dict),
        EventAttributeType.ARRAY: lambda value: isinstance(value, list),
        EventAttributeType.NULL: lambda value: value is None,
    }
    for name, value in values.items():
        kind = schema.properties.get(name)
        if kind is not None and not type_check[kind](value):
            raise ValueError(f"event attribute {name!r} must be {kind.value}")


def canonical_sports_id(
    provider_namespace: str, entity_kind: SportsEntityKind, provider_id: str
) -> str:
    """Stable source-local canonical key; never reuse the provider ID as the key."""
    identity = f"{provider_namespace}:{entity_kind.value}:{provider_id}"
    digest = hashlib.md5(identity.encode(), usedforsecurity=False).hexdigest()[:24]
    return f"{entity_kind.value}-{digest}"


def provider_crosswalk_id(crosswalk: ProviderIdentityCrosswalk) -> str:
    identity = (
        f"{crosswalk.provider_namespace}:{crosswalk.entity_kind.value}:"
        f"{crosswalk.provider_entity_id}"
    )
    return "xw-" + hashlib.md5(identity.encode(), usedforsecurity=False).hexdigest()


def provider_crosswalk(
    *,
    provider_namespace: str,
    entity_kind: SportsEntityKind,
    provider_entity_id: str,
    source_authority: str,
    metadata: dict[str, Any] | None = None,
) -> ProviderIdentityCrosswalk:
    return ProviderIdentityCrosswalk(
        provider_namespace=provider_namespace,
        entity_kind=entity_kind,
        provider_entity_id=provider_entity_id,
        canonical_entity_id=canonical_sports_id(
            provider_namespace, entity_kind, provider_entity_id
        ),
        source_authority=source_authority,
        metadata=metadata or {},
    )


def _capability_or_none(name: str) -> Capability | None:
    try:
        return Capability(name)
    except ValueError:
        return None


def catalog_rows_for_source(source: Any, discovered_at: datetime) -> list[dict[str, Any]]:
    """Project registered registry files into metadata-only catalog rows."""
    modality_capabilities = {
        "tracking": Capability.TRACKING,
        "pose": Capability.POSE,
        "event": Capability.EVENTS,
        "force": Capability.FORCE,
        "imu": Capability.IMU,
        "lpt": Capability.LPT,
        "gnss": Capability.GNSS,
    }
    source_capabilities = sorted(
        {
            modality_capabilities[item.value]
            for item in source.modalities
            if item.value in modality_capabilities
        },
        key=str,
    )
    sport_id = (
        source.domain
        if source.domain in {"football", "basketball", "ice_hockey", "baseball"}
        else None
    )
    rows: list[dict[str, Any]] = []
    for version in source.versions:
        for file in version.retrieval.files:
            provider = file.upstream_provider or source.provider
            external_id = f"{source.dataset_id}/{version.version}/{file.key}"
            identity = f"registry:{source.dataset_id}:{version.version}:{file.key}"
            failed = version.retrieval.status.value == "failed"
            acquired = file.local_sha256 is not None
            capabilities: list[Capability] = source_capabilities
            if file.upstream_capabilities is not None:
                capabilities = sorted(
                    [
                        capability
                        for name in file.upstream_capabilities
                        if (capability := _capability_or_none(name)) is not None
                    ],
                    key=lambda item: item.value,
                )
            rows.append(
                {
                    "entry_id": "src-"
                    + hashlib.md5(identity.encode(), usedforsecurity=False).hexdigest(),
                    "provider": provider,
                    "dataset": source.dataset_id,
                    "registry_dataset_id": source.dataset_id,
                    "registry_version": version.version,
                    "registry_file_key": file.key,
                    "external_id": external_id,
                    "object_kind": SourceObjectKind.RELEASE_ASSET.value,
                    "sport_id": sport_id,
                    "competition_id": None,
                    "competition_edition_id": None,
                    "teams": [],
                    "upstream_url": str(version.upstream_url),
                    "upstream_revision": file.upstream_revision or version.version,
                    "asset_identity": file.key,
                    "expected_size_bytes": file.size_bytes,
                    "rights": source.license.model_dump(mode="json"),
                    "provider_metadata": {},
                    "upstream_capabilities": [item.value for item in capabilities],
                    "discovered_at": discovered_at,
                    "availability_state": (
                        SourceCatalogState.ACQUISITION_FAILED.value
                        if failed
                        else SourceCatalogState.ACQUIRED.value
                        if acquired
                        else SourceCatalogState.REGISTERED.value
                    ),
                    "failure_stage": "acquisition" if failed else None,
                    "failure_evidence": {"retrieval_status": "failed"} if failed else None,
                }
            )
    return rows


EVENT_ENVELOPE_SCHEMA = pa.schema(
    [
        pa.field("contest_id", pa.string(), nullable=False),
        pa.field("contest_period_id", pa.string(), nullable=False),
        pa.field("sequence_index", pa.string(), nullable=False),
        pa.field("source_event_id", pa.string(), nullable=False),
        pa.field("provider_namespace", pa.string(), nullable=False),
        pa.field("provider_event_type", pa.string(), nullable=False),
        pa.field("canonical_time_ns", pa.int64(), nullable=True),
        pa.field("source_clock_json", pa.string(), nullable=True),
        pa.field("team_id", pa.string(), nullable=True),
        pa.field("subject_id", pa.string(), nullable=True),
        pa.field(
            "location",
            pa.struct(
                [
                    pa.field("x", pa.float64(), nullable=False),
                    pa.field("y", pa.float64(), nullable=False),
                    pa.field("z", pa.float64(), nullable=True),
                ]
            ),
            nullable=True,
        ),
        pa.field("spatial_reference_id", pa.string(), nullable=True),
        pa.field("attributes_json", pa.string(), nullable=False),
        pa.field("attributes_schema_id", pa.string(), nullable=False),
        pa.field("attributes_schema_version", pa.string(), nullable=False),
    ],
    metadata={
        b"dynamis.contract": b"cross_sport_event_envelope",
        b"dynamis.schema_version": b"1",
    },
)


def event_envelope_table(
    events: Iterable[EventEnvelope],
    schemas: Mapping[tuple[str, str], EventAttributeSchema],
) -> pa.Table:
    """Encode validated provider-specific payloads in the portable Arrow envelope."""
    rows: list[dict[str, Any]] = []
    for event in events:
        validate_event_attributes(event, schemas)
        rows.append(
            {
                "contest_id": event.contest_id,
                "contest_period_id": event.contest_period_id,
                "sequence_index": event.sequence_index,
                "source_event_id": event.source_event_id,
                "provider_namespace": event.provider_namespace,
                "provider_event_type": event.provider_event_type,
                "canonical_time_ns": event.canonical_time_ns,
                "source_clock_json": (
                    json.dumps(event.source_clock_json, sort_keys=True, separators=(",", ":"))
                    if event.source_clock_json is not None
                    else None
                ),
                "team_id": event.team_id,
                "subject_id": event.subject_id,
                "location": event.location,
                "spatial_reference_id": event.spatial_reference_id,
                "attributes_json": json.dumps(
                    event.attributes_json, sort_keys=True, separators=(",", ":"), allow_nan=False
                ),
                "attributes_schema_id": event.attributes_schema_id,
                "attributes_schema_version": event.attributes_schema_version,
            }
        )
    return pa.Table.from_pylist(rows, schema=EVENT_ENVELOPE_SCHEMA)


def openlineage_job(
    *, namespace: str, algorithm_id: str, version: str, parameters_hash: str | None
) -> dict[str, Any]:
    return {
        "namespace": namespace,
        "name": f"{algorithm_id}:{version}",
        "facets": {
            "dynamis_algorithm_spec": {
                "_producer": "https://github.com/Litju/DynamisETL",
                "_schemaURL": "https://dynamisdata.local/openlineage/algorithm-spec-facet-1.json",
                "algorithmId": algorithm_id,
                "version": version,
                "parametersHash": parameters_hash,
            }
        },
    }


def openlineage_run(*, run_id: str, code_sha: str | None) -> dict[str, Any]:
    return {
        "runId": run_id,
        "facets": {
            "dynamis_run": {
                "_producer": "https://github.com/Litju/DynamisETL",
                "_schemaURL": "https://dynamisdata.local/openlineage/run-facet-1.json",
                "codeSha": code_sha,
            }
        },
    }


def openlineage_dataset(
    *, namespace: str, name: str, checksum_sha256: str, field_mappings: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "namespace": namespace,
        "name": name,
        "facets": {
            "dynamis_artifact": {
                "_producer": "https://github.com/Litju/DynamisETL",
                "_schemaURL": "https://dynamisdata.local/openlineage/artifact-facet-1.json",
                "checksumSha256": checksum_sha256,
                "fieldMappings": field_mappings or {},
            }
        },
    }


def openlineage_event(
    *,
    event_time: AwareDatetime,
    event_type: str,
    producer: str,
    job: Mapping[str, Any],
    run: Mapping[str, Any],
    inputs: Iterable[Mapping[str, Any]] = (),
    outputs: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    if event_type not in {"START", "COMPLETE", "FAIL", "ABORT"}:
        raise ValueError("OpenLineage event type must be START, COMPLETE, FAIL or ABORT")
    return {
        "eventTime": event_time.isoformat(),
        "producer": producer,
        "schemaURL": "https://openlineage.io/spec/2-0-2/OpenLineage.json#/$defs/RunEvent",
        "eventType": event_type,
        "job": dict(job),
        "run": dict(run),
        "inputs": [dict(item) for item in inputs],
        "outputs": [dict(item) for item in outputs],
    }


__all__ = [
    "GRAIN_AXES",
    "Capability",
    "CapabilityEvidence",
    "CapabilityOrigin",
    "CapabilityProfile",
    "CapabilityScope",
    "ClockDirection",
    "ClockKind",
    "ClockMapping",
    "Competition",
    "CompetitionEdition",
    "Contest",
    "ContestPeriod",
    "ContestSide",
    "ContestTeam",
    "DataGrain",
    "DataGrainKind",
    "EditionKind",
    "EventEnvelope",
    "PeriodKind",
    "ProductRoute",
    "ProductSurface",
    "ProviderIdentityCrosswalk",
    "SessionSportContext",
    "SourceCatalogEntry",
    "SourceCatalogState",
    "SourceObjectKind",
    "SpatialReference",
    "Sport",
    "SportsContext",
    "SportsEntityKind",
    "SurfaceGeometry",
    "Team",
    "TeamRosterMembership",
    "EVENT_ENVELOPE_SCHEMA",
    "EventAttributeSchema",
    "EventAttributeType",
    "capability_profile_from_records",
    "canonical_sports_id",
    "catalog_rows_for_source",
    "derive_capability_profile",
    "event_envelope_table",
    "grain_artifact_layout",
    "grain_columns",
    "grain_schema_metadata",
    "openlineage_dataset",
    "openlineage_event",
    "openlineage_job",
    "openlineage_run",
    "provider_crosswalk",
    "provider_crosswalk_id",
    "route_products",
    "validate_event_attributes",
    "validate_grain_rows",
    "with_grain_metadata",
]
