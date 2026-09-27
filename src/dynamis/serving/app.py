"""FastAPI application factory for the DynamisData analytical API.

The API serves precomputed science: registry/catalog metadata, quality and rights
context, current-revision Gold metrics with exact provenance, and bounded dense
windows over immutable Parquet artifacts. It never triggers a processor run and
never recomputes a scientific value.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Annotated, Any, Literal, Protocol, cast

import pyarrow as pa
import pyarrow.parquet as pq
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from dynamis.adapters.skillcorner_basketball import authorities as basketball_authorities
from dynamis.config import ConfigurationError, Settings
from dynamis.config import settings as resolve_settings
from dynamis.gold.publish import resolve_gold_schema
from dynamis.serving import basketball as basketball_reader
from dynamis.serving import games as game_model
from dynamis.serving import repository
from dynamis.serving import season as season_model
from dynamis.serving import tactical as tactical_authority
from dynamis.serving.dense import (
    ArtifactPathError,
    DenseWindowError,
    DenseWindowResult,
    DenseWindowTooLarge,
    arrow_ipc_stream,
    canonical_timespan,
    entity_cardinality,
    entity_column,
    entity_ids,
    entity_observations,
    load_artifact_window,
    resolve_artifact_path,
    table_records,
    window_etag,
    window_metadata_header,
)
from dynamis.serving.models import (
    ArtifactDetail,
    ArtifactRefView,
    BasketballEventPage,
    BasketballFramePage,
    BasketballSpatialGameView,
    DatasetDetail,
    DatasetSummary,
    DenseWindow,
    EntityObservationView,
    GameBoxFamilyView,
    GameBoxView,
    GameDetailView,
    GameEditionView,
    GamePage,
    GamePeriodView,
    GamePlayPage,
    GamePlayView,
    HealthStatus,
    LicenseView,
    MetricCatalogEntry,
    MetricMethodology,
    MetricPage,
    PoseRangeMetricView,
    PoseRangeReportView,
    ProvenanceGraph,
    QualityIssuePage,
    RightsPage,
    RightsPolicyView,
    RunPage,
    RunView,
    SeasonEditionView,
    SeasonFamilyRef,
    SeasonFamilyView,
    SeasonMetricView,
    SeasonPlayerLinksView,
    SeasonPositionView,
    SeasonProfileView,
    SeasonRowPage,
    SeasonRowView,
    SeasonTeamView,
    ServingStatus,
    SessionDetail,
    SessionSummary,
    SourceCapabilityView,
    SportsCatalogMatchView,
    TacticalCapabilityView,
    TacticalEventPage,
    TacticalEventView,
    TacticalMethodologyPage,
    TacticalQualityView,
    TacticalSeriesMeta,
    TacticalSeriesView,
)
from dynamis.storage.control_plane import control_plane_engine

API_VERSION = "0.1.0"
ACCESS_LOG = logging.getLogger("dynamis.access")
DEFAULT_PAGE_LIMIT = 100
MAX_PAGE_LIMIT = 1000
MAX_SEASON_METRICS = 160

#: ``local`` serves every registered source to the operator's own machine;
#: ``public`` refuses scientific payloads of local-only sources (metadata stays
#: browsable). Unknown values fail closed to ``public``.
ENV_SERVING_EXPOSURE = "DYNAMIS_SERVING_EXPOSURE"
SERVING_EXPOSURES = ("local", "public")


class RightsRestricted(RuntimeError):
    """A local-only source's payload was requested in public exposure."""


def serving_exposure() -> str:
    raw = os.environ.get(ENV_SERVING_EXPOSURE, "local").strip().lower() or "local"
    return raw if raw in SERVING_EXPOSURES else "public"


ARROW_MEDIA_TYPE = "application/vnd.apache.arrow.stream"


class ServingBackend(Protocol):
    """Everything the HTTP layer needs; implemented over PostgreSQL + Parquet."""

    def status(self) -> ServingStatus: ...

    def datasets(self) -> list[DatasetSummary]: ...

    def dataset(self, dataset_id: str) -> DatasetDetail | None: ...

    def source_capabilities(self, dataset_id: str) -> list[SourceCapabilityView]: ...

    def sports_catalog_matches(self) -> list[SportsCatalogMatchView]: ...

    def sessions(self, dataset_id: str) -> list[SessionSummary]: ...

    def session(self, dataset_id: str, session_id: str) -> SessionDetail | None: ...

    def metrics(self, filters: repository.MetricFilters, limit: int, offset: int) -> MetricPage: ...

    def methodology(self, metric_id: str) -> MetricMethodology | None: ...

    def metric_definitions(self) -> list[MetricCatalogEntry]: ...

    def provenance(self, derived_metric_id: str) -> ProvenanceGraph | None: ...

    def quality(
        self,
        dataset_id: str | None,
        session_id: str | None,
        severity: str | None,
        limit: int,
        offset: int,
    ) -> QualityIssuePage: ...

    def runs(
        self, dataset_id: str | None, limit: int, offset: int
    ) -> tuple[int, list[RunView]]: ...

    def licenses(self) -> list[RightsPolicyView]: ...

    def artifact(self, artifact_id: str) -> ArtifactRefView | None: ...

    def artifact_detail(self, artifact_id: str) -> ArtifactDetail | None: ...

    def artifact_observations(
        self, artifact_id: str, *, from_ns: int | None, to_ns: int | None
    ) -> list[EntityObservationView] | None: ...

    def window(
        self,
        artifact_id: str,
        *,
        from_ns: int | None,
        to_ns: int | None,
        columns: tuple[str, ...],
        max_points: int | None,
        entity_id: str | None = None,
    ) -> DenseWindowResult: ...

    def tactical_artifacts(
        self,
        dataset_id: str,
        session_id: str | None = None,
        stream_id: str | None = None,
        series_name: str | None = None,
    ) -> list[ArtifactRefView]: ...

    def processing_artifacts(
        self,
        dataset_id: str,
        session_id: str | None = None,
        stream_id: str | None = None,
        algorithm_id: str | None = None,
        series_name: str | None = None,
    ) -> list[ArtifactRefView]: ...

    def pose_range_report(
        self,
        dataset_id: str,
        session_id: str,
        stream_id: str,
        subject_id: str,
        from_ns: int,
        to_ns: int,
        landmark_name: str,
    ) -> PoseRangeReportView | None: ...

    def tactical_capability(self, dataset_id: str) -> TacticalCapabilityView | None: ...

    def tactical_methodology(self) -> TacticalMethodologyPage: ...

    def tactical_quality(self, dataset_id: str) -> TacticalQualityView | None: ...

    def season_editions(self) -> list[SeasonEditionView]: ...

    def season_family(self, edition_id: str, family: str) -> SeasonFamilyView | None: ...

    def season_rows(
        self,
        edition_id: str,
        family: str,
        *,
        metrics: list[str],
        filters: season_model.SeasonRowFilter,
        limit: int,
        offset: int,
    ) -> SeasonRowPage | None: ...

    def season_profile(
        self,
        edition_id: str,
        family: str,
        *,
        subject_id: str,
        team_id: str | None,
        position_group: str | None,
        scope: season_model.PopulationScope,
        min_matches: int | None,
        metrics: list[str],
        population_team_id: str | None = None,
        population_position_group: str | None = None,
    ) -> SeasonProfileView | None: ...

    def season_player_links(
        self, edition_id: str, subject_id: str
    ) -> SeasonPlayerLinksView | None: ...

    def game_editions(self) -> list[GameEditionView]: ...

    def games(
        self, edition_id: str, *, team_id: str | None, limit: int, offset: int
    ) -> GamePage | None: ...

    def game(self, contest_id: str) -> GameDetailView | None: ...

    def game_plays(
        self,
        contest_id: str,
        *,
        period: int | None,
        limit: int,
        offset: int,
        source_columns: tuple[str, ...] = (),
    ) -> GamePlayPage | None: ...

    def game_box(self, contest_id: str, grain: Literal["player", "team"]) -> GameBoxView | None: ...

    def game_license(self, contest_id: str) -> LicenseView | None: ...

    def basketball_spatial_game(self, contest_id: str) -> BasketballSpatialGameView | None: ...

    def basketball_frames(
        self, contest_id: str, *, period: int, from_frame: int, limit: int
    ) -> BasketballFramePage | None: ...

    def basketball_events(
        self, contest_id: str, *, period: int | None, limit: int, offset: int
    ) -> BasketballEventPage | None: ...


class PostgresServingBackend:
    """Serving backend over the PostgreSQL control plane and Gold serving schema."""

    def __init__(self, settings: Settings, engine: Engine | None = None) -> None:
        self.settings = settings
        self._engine = engine
        self.gold_schema = resolve_gold_schema()

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self._engine = control_plane_engine(self.settings)
        return self._engine

    def _connect(self):
        return self.engine.connect()

    def status(self) -> ServingStatus:
        with self._connect() as connection:
            raw = repository.serving_status(
                connection, gold_schema=self.gold_schema, db_schema=self.settings.db_schema
            )
        return ServingStatus(**raw)

    def datasets(self) -> list[DatasetSummary]:
        with self._connect() as connection:
            return repository.list_datasets(connection, gold_schema=self.gold_schema)

    def dataset(self, dataset_id: str) -> DatasetDetail | None:
        with self._connect() as connection:
            return repository.dataset_detail(connection, dataset_id, gold_schema=self.gold_schema)

    def source_capabilities(self, dataset_id: str) -> list[SourceCapabilityView]:
        with self._connect() as connection:
            return repository.list_source_capabilities(connection, dataset_id)

    def sports_catalog_matches(self) -> list[SportsCatalogMatchView]:
        with self._connect() as connection:
            return repository.list_sports_catalog_matches(connection)

    def sessions(self, dataset_id: str) -> list[SessionSummary]:
        with self._connect() as connection:
            return repository.list_sessions(connection, dataset_id)

    def session(self, dataset_id: str, session_id: str) -> SessionDetail | None:
        with self._connect() as connection:
            return repository.session_detail(connection, dataset_id, session_id)

    def metrics(self, filters: repository.MetricFilters, limit: int, offset: int) -> MetricPage:
        with self._connect() as connection:
            return repository.query_metrics(
                connection,
                gold_schema=self.gold_schema,
                filters=filters,
                limit=limit,
                offset=offset,
            )

    def methodology(self, metric_id: str) -> MetricMethodology | None:
        with self._connect() as connection:
            return repository.metric_methodology(connection, metric_id)

    def provenance(self, derived_metric_id: str) -> ProvenanceGraph | None:
        with self._connect() as connection:
            return repository.provenance_graph(connection, derived_metric_id)

    def quality(
        self,
        dataset_id: str | None,
        session_id: str | None,
        severity: str | None,
        limit: int,
        offset: int,
    ) -> QualityIssuePage:
        with self._connect() as connection:
            return repository.list_quality_issues(
                connection,
                dataset_id=dataset_id,
                session_id=session_id,
                severity=severity,
                limit=limit,
                offset=offset,
            )

    def runs(self, dataset_id: str | None, limit: int, offset: int) -> tuple[int, list[RunView]]:
        with self._connect() as connection:
            return repository.list_runs(
                connection, dataset_id=dataset_id, limit=limit, offset=offset
            )

    def metric_definitions(self) -> list[MetricCatalogEntry]:
        with self._connect() as connection:
            return repository.list_metric_definitions(connection)

    def licenses(self) -> list[RightsPolicyView]:
        with self._connect() as connection:
            return repository.list_licenses(connection)

    def artifact(self, artifact_id: str) -> ArtifactRefView | None:
        with self._connect() as connection:
            return repository.resolve_artifact(connection, artifact_id)

    def artifact_detail(self, artifact_id: str) -> ArtifactDetail | None:
        ref = self.artifact(artifact_id)
        if ref is None:
            return None
        minimum, maximum = canonical_timespan(self.settings, ref)
        path = resolve_artifact_path(self.settings, ref)
        return ArtifactDetail(
            **ref.model_dump(),
            canonical_time_min_ns=minimum,
            canonical_time_max_ns=maximum,
            entity_column=entity_column(pq.read_schema(path)),
            entity_count=entity_cardinality(self.settings, ref),
            entity_ids=entity_ids(self.settings, ref),
            entity_observations=entity_observations(self.settings, ref),
        )

    def artifact_observations(
        self, artifact_id: str, *, from_ns: int | None, to_ns: int | None
    ) -> list[EntityObservationView] | None:
        ref = self.artifact(artifact_id)
        if ref is None:
            return None
        return entity_observations(self.settings, ref, from_ns=from_ns, to_ns=to_ns) or []

    def window(
        self,
        artifact_id: str,
        *,
        from_ns: int | None,
        to_ns: int | None,
        columns: tuple[str, ...],
        max_points: int | None,
        entity_id: str | None = None,
    ) -> DenseWindowResult:
        ref = self.artifact(artifact_id)
        if ref is None:
            raise ArtifactPathError(f"artifact {artifact_id!r} is not registered")
        return load_artifact_window(
            self.settings,
            ref,
            from_ns=from_ns,
            to_ns=to_ns,
            columns=columns,
            max_points=max_points,
            entity_id=entity_id,
        )

    def tactical_artifacts(
        self,
        dataset_id: str,
        session_id: str | None = None,
        stream_id: str | None = None,
        series_name: str | None = None,
    ) -> list[ArtifactRefView]:
        with self._connect() as connection:
            return repository.list_tactical_artifacts(
                connection,
                dataset_id=dataset_id,
                session_id=session_id,
                stream_id=stream_id,
                series_name=series_name,
            )

    def processing_artifacts(
        self,
        dataset_id: str,
        session_id: str | None = None,
        stream_id: str | None = None,
        algorithm_id: str | None = None,
        series_name: str | None = None,
    ) -> list[ArtifactRefView]:
        with self._connect() as connection:
            return repository.list_processing_artifacts(
                connection,
                dataset_id=dataset_id,
                session_id=session_id,
                stream_id=stream_id,
                algorithm_id=algorithm_id,
                series_name=series_name,
            )

    def pose_range_report(
        self,
        dataset_id: str,
        session_id: str,
        stream_id: str,
        subject_id: str,
        from_ns: int,
        to_ns: int,
        landmark_name: str,
    ) -> PoseRangeReportView | None:
        from dynamis.processors.pose_range import process_pose_range

        session = self.session(dataset_id, session_id)
        if session is None:
            return None
        stream = next(
            (
                candidate
                for candidate in session.streams
                if candidate.stream_id == stream_id and candidate.modality == "pose"
            ),
            None,
        )
        if stream is None or not stream.sample_artifact_ids:
            return None
        artifacts = self.processing_artifacts(
            dataset_id,
            session_id=session_id,
            stream_id=stream_id,
        )
        by_series = {
            (artifact.algorithm_id, artifact.artifact_metadata.get("series_name")): artifact
            for artifact in artifacts
        }
        geometry_ref = by_series.get(
            ("pose.translation_invariant_kinematics", "pose_translation_invariant_kinematics")
        )
        landmark_ref = by_series.get(("pose.landmark_kinematics", "pose_landmark_kinematics"))
        quality_ref = by_series.get(("pose.analysis_quality", "pose_analysis_quality"))
        bilateral_ref = by_series.get(("pose.bilateral_geometry", "pose_bilateral_geometry"))
        if geometry_ref is None or landmark_ref is None or quality_ref is None:
            return None
        source_ref = self.artifact(stream.sample_artifact_ids[0])
        source_detail = self.artifact_detail(stream.sample_artifact_ids[0])
        if source_ref is None or source_detail is None:
            return None

        token = landmark_name
        angle_name = {
            "lKnee": "left_knee",
            "rKnee": "right_knee",
            "lHip": "left_hip",
            "rHip": "right_hip",
        }.get(landmark_name)
        geometry_columns = ["t_rel_ns"]
        if angle_name is not None:
            geometry_columns.extend(
                [f"angle_{angle_name}_rad", f"angular_velocity_{angle_name}_rad_s"]
            )
        landmark_columns = [
            "entity_id",
            "t_rel_ns",
            "temporal_segment_index",
            f"available_{token}",
            f"relative_position_x_{token}_m",
            f"relative_position_y_{token}_m",
            f"relative_position_z_{token}_m",
            f"body_relative_speed_{token}_m_s",
        ]
        quality_columns = [
            "t_rel_ns",
            "any_pose_present",
            "any_pose_available",
            "available_landmark_count",
            "expected_landmark_count",
        ]
        source_columns = [
            "t_rel_ns",
            "joint_name",
            "is_available",
            "error_m",
            "x_m",
            "y_m",
            "z_m",
            "nominal_sampling_rate_hz",
        ]

        def exact_window(
            artifact: ArtifactRefView,
            columns: list[str],
            *,
            lower: int | None = from_ns,
            upper: int | None = to_ns,
        ) -> pa.Table:
            result = self.window(
                artifact.artifact_id,
                from_ns=lower,
                to_ns=upper,
                columns=tuple(columns),
                max_points=None,
                entity_id=subject_id,
            )
            if result.meta.reduction is not None:
                raise ValueError("selected range report requires exact processor samples")
            return result.table

        source_table = exact_window(source_ref, source_columns)
        geometry_table = exact_window(geometry_ref, geometry_columns)
        landmark_table = exact_window(landmark_ref, landmark_columns)
        quality_table = exact_window(quality_ref, quality_columns)
        source_checksums = {
            "source_pose": source_ref.checksum_sha256,
            "pose_geometry": geometry_ref.checksum_sha256,
            "pose_landmarks": landmark_ref.checksum_sha256,
            "pose_quality": quality_ref.checksum_sha256,
        }
        bilateral_pair = (
            "knee_included_angle"
            if landmark_name in {"lKnee", "rKnee"}
            else "hip_included_angle"
            if landmark_name in {"lHip", "rHip"}
            else None
        )
        bilateral_table = None
        if bilateral_ref is not None and bilateral_pair is not None:
            bilateral_table = exact_window(
                bilateral_ref,
                [
                    "t_rel_ns",
                    f"left_{bilateral_pair}_rad",
                    f"right_{bilateral_pair}_rad",
                    f"right_minus_left_{bilateral_pair}_rad",
                    f"common_available_{bilateral_pair}",
                ],
            )
            source_checksums["pose_bilateral"] = bilateral_ref.checksum_sha256
        result = process_pose_range(
            dataset_id=dataset_id,
            session_id=session_id,
            trial_id=stream.trial_id or "",
            stream_id=stream_id,
            subject_id=subject_id,
            from_ns=from_ns,
            to_ns=to_ns,
            landmark_name=landmark_name,
            sampling_rate_hz=stream.nominal_sampling_rate_hz or 0.0,
            grid_origin_ns=source_detail.canonical_time_min_ns or 0,
            geometry=geometry_table,
            landmark_series=landmark_table,
            quality_frames=quality_table,
            bilateral_series=bilateral_table,
            source_pose=source_table,
            source_checksums=source_checksums,
            input_series_versions={
                "pose.geometry": geometry_ref.algorithm_version or "unknown",
                "pose.landmark": landmark_ref.algorithm_version or "unknown",
                "pose.quality": quality_ref.algorithm_version or "unknown",
                **(
                    {"pose.bilateral": bilateral_ref.algorithm_version or "unknown"}
                    if bilateral_ref is not None
                    else {}
                ),
            },
        )
        return PoseRangeReportView(
            algorithm_id=result.spec.algorithm_id,
            algorithm_version=result.spec.version,
            parameters_hash=result.spec.parameters_hash,
            code_git_sha=result.diagnostics.get("code_git_sha"),
            dataset_id=dataset_id,
            session_id=session_id,
            trial_id=stream.trial_id or "",
            stream_id=stream_id,
            subject_id=subject_id,
            from_ns=from_ns,
            to_ns=to_ns,
            input_artifact_checksums=source_checksums,
            metrics=[
                PoseRangeMetricView(
                    metric_id=metric.declaration.metric_id,
                    metric_name=metric.declaration.name,
                    si_unit=metric.declaration.si_unit,
                    value_num=metric.value,
                    description=metric.declaration.description,
                    provenance=dict(metric.provenance),
                )
                for metric in result.metrics
            ],
            display_note=(
                "Range summaries aggregate exact versioned processor samples. Provider p90 "
                "error-radius evidence remains source evidence; no display-reduced samples "
                "or normative labels are used."
            ),
        )

    def tactical_capability(self, dataset_id: str) -> TacticalCapabilityView | None:
        return tactical_authority.tactical_capability(dataset_id)

    def tactical_methodology(self) -> TacticalMethodologyPage:
        return tactical_authority.tactical_methodology()

    def tactical_quality(self, dataset_id: str) -> TacticalQualityView | None:
        return tactical_authority.tactical_quality(dataset_id)

    # -- SeasonLab -----------------------------------------------------------

    def season_editions(self) -> list[SeasonEditionView]:
        with self._connect() as connection:
            return repository.list_season_editions(connection)

    def _season_scope(
        self, edition_id: str, family: str
    ) -> tuple[SeasonEditionView, SeasonFamilyRef, Any] | None:
        edition = next(
            (item for item in self.season_editions() if item.edition_id == edition_id), None
        )
        if edition is None:
            return None
        ref = next((item for item in edition.families if item.family == family), None)
        if ref is None:
            return None
        artifact = self.artifact(ref.artifact_id)
        if artifact is None:
            return None
        return edition, ref, resolve_artifact_path(self.settings, artifact)

    def season_family(self, edition_id: str, family: str) -> SeasonFamilyView | None:
        scope = self._season_scope(edition_id, family)
        if scope is None:
            return None
        edition, ref, path = scope
        specs = season_model.family_metrics(family, season_model.artifact_columns(path))
        summary = season_model.population_summary(path)
        return SeasonFamilyView(
            edition=edition,
            family=ref,
            metrics=[SeasonMetricView(**item) for item in season_model.metric_views(specs)],
            population_rows=summary.rows,
            population_subjects=summary.subjects,
            teams=[
                SeasonTeamView(team_id=team_id, display_name=name, rows=count)
                for team_id, name, count in summary.teams
            ],
            position_groups=[
                SeasonPositionView(position_group=group, rows=count)
                for group, count in summary.position_groups
            ],
        )

    def season_rows(
        self,
        edition_id: str,
        family: str,
        *,
        metrics: list[str],
        filters: season_model.SeasonRowFilter,
        limit: int,
        offset: int,
    ) -> SeasonRowPage | None:
        scope = self._season_scope(edition_id, family)
        if scope is None:
            return None
        _, _, path = scope
        _, columns = season_model.resolve_metric_columns(family, path, metrics)
        total, rows = season_model.read_rows(
            path, family=family, metrics=columns, filters=filters, limit=limit, offset=offset
        )
        return SeasonRowPage(
            total=total,
            limit=limit,
            offset=offset,
            metrics=columns,
            rows=[
                SeasonRowView(**season_model.row_view(row, family=family, metrics=columns))
                for row in rows
            ],
        )

    def season_profile(
        self,
        edition_id: str,
        family: str,
        *,
        subject_id: str,
        team_id: str | None,
        position_group: str | None,
        scope: season_model.PopulationScope,
        min_matches: int | None,
        metrics: list[str],
        population_team_id: str | None = None,
        population_position_group: str | None = None,
    ) -> SeasonProfileView | None:
        resolved = self._season_scope(edition_id, family)
        if resolved is None:
            return None
        edition, ref, path = resolved
        payload = season_model.profile_payload(
            path,
            family=family,
            subject_id=subject_id,
            team_id=team_id,
            position_group=position_group,
            scope=scope,
            min_matches=min_matches,
            requested_metrics=metrics,
            edition_label=edition.edition_label,
            competition_name=edition.competition_name,
            population_team_id=population_team_id,
            population_position_group=population_position_group,
        )
        if payload is None:
            return None
        return SeasonProfileView(edition=edition, family=ref, **payload)

    # -- Games (PLAY_BY_PLAY / PLAYER_GAME / TEAM_GAME) -------------------------

    def game_editions(self) -> list[GameEditionView]:
        with self._connect() as connection:
            return repository.list_game_editions(connection)

    def _game_edition(self, edition_id: str | None) -> GameEditionView | None:
        if edition_id is None:
            return None
        return next((item for item in self.game_editions() if item.edition_id == edition_id), None)

    def _family_path(self, edition: GameEditionView, family: str) -> tuple[str, Any] | None:
        ref = next((item for item in edition.families if item.family == family), None)
        if ref is None:
            return None
        artifact = self.artifact(ref.artifact_id)
        if artifact is None:
            return None
        return ref.artifact_id, resolve_artifact_path(self.settings, artifact)

    def games(
        self, edition_id: str, *, team_id: str | None, limit: int, offset: int
    ) -> GamePage | None:
        if self._game_edition(edition_id) is None:
            return None
        with self._connect() as connection:
            total, rows = repository.list_games(
                connection, edition_id=edition_id, team_id=team_id, limit=limit, offset=offset
            )
        return GamePage(total=total, limit=limit, offset=offset, rows=rows)

    def game(self, contest_id: str) -> GameDetailView | None:
        with self._connect() as connection:
            summary = repository.game_summary(connection, contest_id)
            if summary is None:
                return None
            periods = repository.game_periods(connection, contest_id)
        edition = self._game_edition(summary.edition_id)
        if edition is None:
            return None
        pbp = self._family_path(edition, "pbp")
        counts = game_model.period_event_counts(pbp[1], contest_id=contest_id) if pbp else {}
        subject_ids: set[str] = set()
        for family in ("player_game", "skater_game", "goalie_game"):
            located = self._family_path(edition, family)
            if located is None:
                continue
            _, rows = game_model.read_box(located[1], contest_id=contest_id)
            subject_ids.update(str(row["subject_id"]) for row in rows if row.get("subject_id"))
        with self._connect() as connection:
            subjects = repository.subject_display_names(connection, sorted(subject_ids))
        return GameDetailView(
            summary=summary,
            edition=edition,
            periods=[
                GamePeriodView(
                    contest_period_id=str(row["contest_period_id"]),
                    number=int(row["source_period_number"]),
                    kind=str(row["kind"]),
                    label=row["label"],
                    start_ns=row["start_ns"],
                    end_ns=row["end_ns"],
                    event_count=counts.get(int(row["source_period_number"]), 0),
                )
                for row in periods
            ],
            subjects=subjects,
            teams_by_id={team.team_id: team.display_name for team in summary.teams},
        )

    def game_license(self, contest_id: str) -> LicenseView | None:
        with self._connect() as connection:
            summary = repository.game_summary(connection, contest_id)
        edition = self._game_edition(summary.edition_id) if summary else None
        return edition.license if edition else None

    def game_plays(
        self,
        contest_id: str,
        *,
        period: int | None,
        limit: int,
        offset: int,
        source_columns: tuple[str, ...] = (),
    ) -> GamePlayPage | None:
        with self._connect() as connection:
            summary = repository.game_summary(connection, contest_id)
        if summary is None:
            return None
        edition = self._game_edition(summary.edition_id)
        located = self._family_path(edition, "pbp") if edition else None
        if located is None:
            return None
        total, rows = game_model.read_plays(
            located[1],
            contest_id=contest_id,
            period=period,
            limit=limit,
            offset=offset,
            extra_columns=source_columns,
        )
        return GamePlayPage(
            contest_id=contest_id,
            period=period,
            total=total,
            limit=limit,
            offset=offset,
            rows=[GamePlayView(**row) for row in rows],
        )

    def game_box(self, contest_id: str, grain: Literal["player", "team"]) -> GameBoxView | None:
        with self._connect() as connection:
            summary = repository.game_summary(connection, contest_id)
        if summary is None:
            return None
        edition = self._game_edition(summary.edition_id)
        if edition is None:
            return None
        wanted = (
            ("player_game", "skater_game", "goalie_game") if grain == "player" else ("team_game",)
        )
        families: list[GameBoxFamilyView] = []
        for family in wanted:
            located = self._family_path(edition, family)
            if located is None:
                continue
            ref = next(item for item in edition.families if item.family == family)
            columns, rows = game_model.read_box(located[1], contest_id=contest_id)
            families.append(
                GameBoxFamilyView(
                    family=family,
                    grain_kind=ref.grain_kind,
                    artifact_id=ref.artifact_id,
                    columns=columns,
                    rows=rows,
                )
            )
        return GameBoxView(contest_id=contest_id, grain=grain, families=families)

    def basketball_spatial_game(self, contest_id: str) -> BasketballSpatialGameView | None:
        detail = self.game(contest_id)
        if detail is None or detail.summary.sport_id != "basketball":
            return None
        with self._connect() as connection:
            artifacts = repository.basketball_spatial_artifacts(connection, contest_id)
            if artifacts is None:
                return None
            roster = repository.basketball_roster(
                connection,
                dataset_id=artifacts["dataset_id"],
                session_id=artifacts["provider_game_id"],
                contest_id=contest_id,
                edition_id=detail.summary.edition_id or "",
            )
        clock = artifacts["frame_clock"]
        periods = basketball_reader.period_ranges(self.settings, clock) if clock else []
        reference = basketball_authorities.spatial_reference()
        surface = basketball_authorities.surface_geometry()
        return BasketballSpatialGameView(
            game=detail,
            dataset_id=artifacts["dataset_id"],
            source_revision=artifacts["registry_version"],
            frame_rate_hz=basketball_authorities.FRAME_RATE_HZ,
            spatial_reference_id=reference.spatial_reference_id,
            units=reference.units,
            origin=reference.origin,
            axis_orientation=reference.axis_orientation,
            court_dimensions=surface.dimensions,
            tracking_materialized=bool(artifacts["tracking"] and clock),
            events_materialized=artifacts["events"] is not None,
            periods=periods,
            players=roster,
        )

    def basketball_frames(
        self, contest_id: str, *, period: int, from_frame: int, limit: int
    ) -> BasketballFramePage | None:
        with self._connect() as connection:
            artifacts = repository.basketball_spatial_artifacts(connection, contest_id)
            if artifacts is None or not artifacts["frame_clock"] or not artifacts["tracking"]:
                return None
            detail = repository.game_summary(connection, contest_id)
            if detail is None or detail.edition_id is None:
                return None
            roster = repository.basketball_roster(
                connection,
                dataset_id=artifacts["dataset_id"],
                session_id=artifacts["provider_game_id"],
                contest_id=contest_id,
                edition_id=detail.edition_id,
            )
        return basketball_reader.read_frames(
            self.settings,
            contest_id=contest_id,
            period=period,
            from_frame=from_frame,
            limit=limit,
            frame_clock=artifacts["frame_clock"],
            tracking=artifacts["tracking"],
            roster=roster,
        )

    def basketball_events(
        self, contest_id: str, *, period: int | None, limit: int, offset: int
    ) -> BasketballEventPage | None:
        with self._connect() as connection:
            artifacts = repository.basketball_spatial_artifacts(connection, contest_id)
        if artifacts is None or artifacts["events"] is None:
            return None
        return basketball_reader.read_events(
            self.settings,
            contest_id=contest_id,
            period=period,
            limit=limit,
            offset=offset,
            artifact=artifacts["events"],
        )

    def season_player_links(self, edition_id: str, subject_id: str) -> SeasonPlayerLinksView | None:
        edition = next(
            (item for item in self.season_editions() if item.edition_id == edition_id), None
        )
        if edition is None:
            return None
        team_ids: set[str] = set()
        for ref in edition.families:
            artifact = self.artifact(ref.artifact_id)
            if artifact is None:
                continue
            path = resolve_artifact_path(self.settings, artifact)
            _, rows = season_model.read_rows(
                path,
                family=ref.family,
                metrics=[],
                filters=season_model.SeasonRowFilter(subject_ids=(subject_id,)),
                limit=64,
            )
            team_ids.update(str(row["team_id"]) for row in rows)
        if not team_ids:
            return None
        with self._connect() as connection:
            return repository.season_player_links(
                connection,
                dataset_id=edition.dataset_id,
                subject_id=subject_id,
                team_ids=sorted(team_ids),
            )


def _backend_from_app(request: Request) -> ServingBackend:
    backend = getattr(request.app.state, "backend", None)
    if backend is None:
        raise HTTPException(status_code=503, detail="serving backend is not configured")
    return backend


def get_backend(request: Request) -> ServingBackend:
    """FastAPI dependency; override in tests with a deterministic backend."""
    return _backend_from_app(request)


#: Annotated dependency alias; keeps FastAPI's dependency call out of defaults.
BackendDependency = Annotated[ServingBackend, Depends(get_backend)]


def _parse_columns(columns: str | None) -> tuple[str, ...]:
    if not columns:
        return ()
    return tuple(part.strip() for part in columns.split(",") if part.strip())


def create_app(
    *,
    settings: Settings | None = None,
    backend: Any | None = None,
    exposure: str | None = None,
) -> FastAPI:
    """Build the API application.

    ``backend`` exists for tests and embedding; production resolves settings from
    the environment and connects lazily, so importing the module has no side
    effects.
    """
    app = FastAPI(
        title="DynamisData Analytical API",
        version=API_VERSION,
        description=(
            "Precomputed, provenance-explicit serving of the DynamisData gold/metadata "
            "plane. Dense windows are bounded and display-reduced; scientific values are "
            "never recomputed here."
        ),
    )
    if backend is not None:
        app.state.backend = backend
    else:

        def _lazy_settings() -> Settings:
            return settings if settings is not None else resolve_settings()

        class _LazyBackend:
            """Defers engine construction until the first request."""

            def __init__(self) -> None:
                self._backend: PostgresServingBackend | None = None

            def _resolved(self) -> PostgresServingBackend:
                if self._backend is None:
                    resolved = _lazy_settings()
                    engine = control_plane_engine(resolved)
                    self._backend = PostgresServingBackend(resolved, engine)
                return self._backend

            def __getattr__(self, name: str) -> Any:
                return getattr(self._resolved(), name)

        app.state.backend = _LazyBackend()

    @app.middleware("http")
    async def bounded_access_log(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        if os.environ.get("DYNAMIS_ACCESS_LOG", "0") == "1":
            ACCESS_LOG.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "method": request.method,
                        "path": request.url.path,
                        "status": response.status_code,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                    },
                    separators=(",", ":"),
                )
            )
        return response

    @app.exception_handler(SQLAlchemyError)
    async def _database_error(_request, exc: SQLAlchemyError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "database unavailable",
                "state": "api_error",
                "error": type(exc).__name__,
            },
        )

    @app.exception_handler(ConfigurationError)
    async def _configuration_error(_request, exc: ConfigurationError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": str(exc), "state": "unavailable_for_source"},
        )

    exposure_mode = exposure if exposure in SERVING_EXPOSURES else serving_exposure()
    app.state.exposure = exposure_mode

    @app.exception_handler(RightsRestricted)
    async def _rights_restricted(_request, exc: RightsRestricted) -> JSONResponse:
        return JSONResponse(
            status_code=451, content={"detail": str(exc), "state": "rights_restricted"}
        )

    def _require_payload_rights(service: ServingBackend, contest_id: str) -> None:
        if exposure_mode != "public":
            return
        license = service.game_license(contest_id)
        if license is None or license.local_only:
            notice = license.notice if license else "rights unknown"
            raise RightsRestricted(
                f"contest {contest_id!r} comes from a local-only source; its play-by-play and "
                f"box-score payloads are not served in public exposure ({notice})"
            )

    @app.exception_handler(DenseWindowTooLarge)
    async def _window_too_large(_request, exc: DenseWindowTooLarge) -> JSONResponse:
        return JSONResponse(
            status_code=413, content={"detail": str(exc), "state": "dense_window_too_large"}
        )

    @app.exception_handler(DenseWindowError)
    async def _window_error(_request, exc: DenseWindowError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc), "state": "api_error"})

    @app.exception_handler(ArtifactPathError)
    async def _artifact_error(_request, exc: ArtifactPathError) -> JSONResponse:
        return JSONResponse(
            status_code=404, content={"detail": str(exc), "state": "unavailable_for_source"}
        )

    @app.get("/api/health", response_model=HealthStatus, tags=["system"])
    def health() -> HealthStatus:
        return HealthStatus(status="ok", version=API_VERSION)

    @app.get("/api/ready", response_model=HealthStatus, tags=["system"])
    def ready(service: BackendDependency) -> HealthStatus:
        service.status()
        return HealthStatus(status="ok", version=API_VERSION)

    @app.get("/api/serving/status", response_model=ServingStatus, tags=["system"])
    def serving_status(service: BackendDependency) -> ServingStatus:
        return service.status()

    @app.get("/api/catalog/datasets", response_model=list[DatasetSummary], tags=["catalog"])
    def list_datasets(service: BackendDependency) -> list[DatasetSummary]:
        return service.datasets()

    @app.get(
        "/api/catalog/source-capabilities",
        response_model=list[SourceCapabilityView],
        tags=["catalog"],
    )
    def source_capabilities(
        dataset_id: str, service: BackendDependency
    ) -> list[SourceCapabilityView]:
        if service.dataset(dataset_id) is None:
            raise HTTPException(status_code=404, detail=f"dataset {dataset_id!r} is not registered")
        return service.source_capabilities(dataset_id)

    @app.get(
        "/api/catalog/sports/matches",
        response_model=list[SportsCatalogMatchView],
        tags=["catalog"],
    )
    def sports_catalog_matches(service: BackendDependency) -> list[SportsCatalogMatchView]:
        return service.sports_catalog_matches()

    def _metric_list(raw: str | None) -> list[str]:
        items = [item.strip() for item in (raw or "").split(",") if item.strip()]
        if len(items) > MAX_SEASON_METRICS:
            raise HTTPException(
                status_code=422, detail=f"at most {MAX_SEASON_METRICS} metrics per request"
            )
        return items

    def _season_failure(exc: season_model.SeasonDataError) -> HTTPException:
        return HTTPException(status_code=422, detail=str(exc))

    @app.get("/api/season/editions", response_model=list[SeasonEditionView], tags=["season"])
    def season_editions(service: BackendDependency) -> list[SeasonEditionView]:
        return service.season_editions()

    @app.get(
        "/api/season/editions/{edition_id}/families/{family}",
        response_model=SeasonFamilyView,
        tags=["season"],
    )
    def season_family(edition_id: str, family: str, service: BackendDependency) -> SeasonFamilyView:
        try:
            found = service.season_family(edition_id, family)
        except season_model.SeasonDataError as exc:
            raise _season_failure(exc) from exc
        if found is None:
            raise HTTPException(
                status_code=404,
                detail=f"season family {family!r} is not materialized for {edition_id!r}",
            )
        return found

    @app.get(
        "/api/season/editions/{edition_id}/families/{family}/rows",
        response_model=SeasonRowPage,
        tags=["season"],
    )
    def season_rows(
        edition_id: str,
        family: str,
        service: BackendDependency,
        metrics: str | None = Query(default=None, description="Comma-separated metric columns"),
        team_id: str | None = Query(default=None),
        position_group: str | None = Query(default=None),
        subject_id: Annotated[list[str] | None, Query()] = None,
        min_matches: int | None = Query(default=None, ge=1, le=100),
        limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
        offset: int = Query(default=0, ge=0),
    ) -> SeasonRowPage:
        filters = season_model.SeasonRowFilter(
            team_id=team_id,
            position_group=position_group,
            subject_ids=tuple(subject_id or ()),
            min_matches=min_matches,
        )
        try:
            found = service.season_rows(
                edition_id,
                family,
                metrics=_metric_list(metrics),
                filters=filters,
                limit=limit,
                offset=offset,
            )
        except season_model.SeasonDataError as exc:
            raise _season_failure(exc) from exc
        if found is None:
            raise HTTPException(
                status_code=404,
                detail=f"season family {family!r} is not materialized for {edition_id!r}",
            )
        return found

    @app.get(
        "/api/season/editions/{edition_id}/families/{family}/profile",
        response_model=SeasonProfileView,
        tags=["season"],
    )
    def season_profile(
        edition_id: str,
        family: str,
        service: BackendDependency,
        subject_id: str = Query(min_length=1, max_length=256),
        team_id: str | None = Query(default=None),
        position_group: str | None = Query(default=None),
        population: Literal["edition", "position", "team"] = Query(default="position"),
        min_matches: int | None = Query(default=None, ge=1, le=100),
        metrics: str | None = Query(default=None, description="Comma-separated metric columns"),
        population_team_id: str | None = Query(
            default=None, description="Rank against this team's rows instead of the row's own"
        ),
        population_position_group: str | None = Query(
            default=None, description="Rank against this position group instead of the row's own"
        ),
    ) -> SeasonProfileView:
        try:
            found = service.season_profile(
                edition_id,
                family,
                subject_id=subject_id,
                team_id=team_id,
                position_group=position_group,
                scope=population,
                min_matches=min_matches,
                metrics=_metric_list(metrics),
                population_team_id=population_team_id,
                population_position_group=population_position_group,
            )
        except season_model.SeasonDataError as exc:
            raise _season_failure(exc) from exc
        if found is None:
            raise HTTPException(
                status_code=404,
                detail=f"no {family!r} season row for {subject_id!r} in {edition_id!r}",
            )
        return found

    @app.get(
        "/api/season/editions/{edition_id}/links",
        response_model=SeasonPlayerLinksView,
        tags=["season"],
    )
    def season_player_links(
        edition_id: str,
        service: BackendDependency,
        subject_id: str = Query(min_length=1, max_length=256),
    ) -> SeasonPlayerLinksView:
        found = service.season_player_links(edition_id, subject_id)
        if found is None:
            raise HTTPException(
                status_code=404, detail=f"no season row for {subject_id!r} in {edition_id!r}"
            )
        return found

    @app.get("/api/games/editions", response_model=list[GameEditionView], tags=["games"])
    def game_editions(service: BackendDependency) -> list[GameEditionView]:
        return service.game_editions()

    @app.get("/api/games", response_model=GamePage, tags=["games"])
    def games(
        service: BackendDependency,
        edition_id: str = Query(min_length=1, max_length=256),
        team_id: str | None = Query(default=None),
        limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
        offset: int = Query(default=0, ge=0),
    ) -> GamePage:
        found = service.games(edition_id, team_id=team_id, limit=limit, offset=offset)
        if found is None:
            raise HTTPException(status_code=404, detail=f"no game data for {edition_id!r}")
        return found

    @app.get("/api/games/{contest_id}", response_model=GameDetailView, tags=["games"])
    def game(contest_id: str, service: BackendDependency) -> GameDetailView:
        found = service.game(contest_id)
        if found is None:
            raise HTTPException(status_code=404, detail=f"contest {contest_id!r} has no game data")
        return found

    @app.get("/api/games/{contest_id}/plays", response_model=GamePlayPage, tags=["games"])
    def game_plays(
        contest_id: str,
        service: BackendDependency,
        period: int | None = Query(default=None, ge=1, le=20),
        limit: int = Query(default=500, ge=1, le=MAX_PAGE_LIMIT),
        offset: int = Query(default=0, ge=0),
        source_columns: str | None = Query(
            default=None, description="Comma-separated preserved provider columns"
        ),
    ) -> GamePlayPage:
        _require_payload_rights(service, contest_id)
        extra = tuple(item.strip() for item in (source_columns or "").split(",") if item.strip())
        try:
            found = service.game_plays(
                contest_id, period=period, limit=limit, offset=offset, source_columns=extra
            )
        except game_model.GameDataError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if found is None:
            raise HTTPException(
                status_code=404, detail=f"contest {contest_id!r} has no play-by-play"
            )
        return found

    @app.get("/api/games/{contest_id}/box", response_model=GameBoxView, tags=["games"])
    def game_box(
        contest_id: str,
        service: BackendDependency,
        grain: Literal["player", "team"] = Query(default="player"),
    ) -> GameBoxView:
        _require_payload_rights(service, contest_id)
        found = service.game_box(contest_id, grain)
        if found is None:
            raise HTTPException(status_code=404, detail=f"contest {contest_id!r} has no box score")
        return found

    @app.get(
        "/api/basketball/contests/{contest_id}",
        response_model=BasketballSpatialGameView,
        tags=["basketball"],
    )
    def basketball_spatial_game(
        contest_id: str, service: BackendDependency
    ) -> BasketballSpatialGameView:
        found = service.basketball_spatial_game(contest_id)
        if found is None:
            raise HTTPException(
                status_code=404, detail=f"basketball contest {contest_id!r} is not catalogued"
            )
        return found

    @app.get(
        "/api/basketball/contests/{contest_id}/frames",
        response_model=BasketballFramePage,
        tags=["basketball"],
    )
    def basketball_frames(
        contest_id: str,
        service: BackendDependency,
        period: int = Query(ge=1, le=20),
        from_frame: int = Query(default=0, ge=0),
        limit: int = Query(default=125, ge=1, le=250),
    ) -> BasketballFramePage:
        _require_payload_rights(service, contest_id)
        found = service.basketball_frames(
            contest_id, period=period, from_frame=from_frame, limit=limit
        )
        if found is None:
            raise HTTPException(
                status_code=404,
                detail=f"basketball tracking for contest {contest_id!r} is not materialized",
            )
        return found

    @app.get(
        "/api/basketball/contests/{contest_id}/events",
        response_model=BasketballEventPage,
        tags=["basketball"],
    )
    def basketball_events(
        contest_id: str,
        service: BackendDependency,
        period: int | None = Query(default=None, ge=1, le=20),
        limit: int = Query(default=250, ge=1, le=MAX_PAGE_LIMIT),
        offset: int = Query(default=0, ge=0),
    ) -> BasketballEventPage:
        _require_payload_rights(service, contest_id)
        found = service.basketball_events(contest_id, period=period, limit=limit, offset=offset)
        if found is None:
            raise HTTPException(
                status_code=404,
                detail=f"basketball events for contest {contest_id!r} are not materialized",
            )
        return found

    @app.get("/api/catalog/datasets/{dataset_id}", response_model=DatasetDetail, tags=["catalog"])
    def dataset_detail(dataset_id: str, service: BackendDependency) -> DatasetDetail:
        found = service.dataset(dataset_id)
        if found is None:
            raise HTTPException(status_code=404, detail=f"dataset {dataset_id!r} is not registered")
        return found

    @app.get(
        "/api/catalog/datasets/{dataset_id}/sessions",
        response_model=list[SessionSummary],
        tags=["catalog"],
    )
    def list_sessions(dataset_id: str, service: BackendDependency) -> list[SessionSummary]:
        if service.dataset(dataset_id) is None:
            raise HTTPException(status_code=404, detail=f"dataset {dataset_id!r} is not registered")
        return service.sessions(dataset_id)

    @app.get(
        "/api/catalog/datasets/{dataset_id}/sessions/{session_id}",
        response_model=SessionDetail,
        tags=["catalog"],
    )
    def session_detail(
        dataset_id: str, session_id: str, service: BackendDependency
    ) -> SessionDetail:
        found = service.session(dataset_id, session_id)
        if found is None:
            raise HTTPException(status_code=404, detail=f"session {session_id!r} is not registered")
        return found

    @app.get("/api/metrics", response_model=MetricPage, tags=["metrics"])
    def metrics(
        service: BackendDependency,
        dataset_id: str | None = None,
        session_id: str | None = None,
        subject_id: str | None = None,
        trial_id: str | None = None,
        stream_id: str | None = None,
        metric_id: str | None = None,
        entity_id: str | None = None,
        limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
        offset: int = Query(default=0, ge=0),
    ) -> MetricPage:
        return service.metrics(
            repository.MetricFilters(
                dataset_id=dataset_id,
                session_id=session_id,
                subject_id=subject_id,
                trial_id=trial_id,
                stream_id=stream_id,
                metric_id=metric_id,
                entity_id=entity_id,
            ),
            limit=limit,
            offset=offset,
        )

    # Declared before the `{metric_id:path}` route so the literal path is not
    # captured as a metric id.
    @app.get(
        "/api/metrics/definitions",
        response_model=list[MetricCatalogEntry],
        tags=["metrics"],
    )
    def metric_definitions(service: BackendDependency) -> list[MetricCatalogEntry]:
        return service.metric_definitions()

    @app.get(
        "/api/metrics/methodology/{metric_id:path}",
        response_model=MetricMethodology,
        tags=["metrics"],
    )
    def methodology(metric_id: str, service: BackendDependency) -> MetricMethodology:
        found = service.methodology(metric_id)
        if found is None:
            raise HTTPException(
                status_code=404, detail=f"metric definition {metric_id!r} is not registered"
            )
        return found

    @app.get(
        "/api/derived-metrics/{derived_metric_id}/provenance",
        response_model=ProvenanceGraph,
        tags=["provenance"],
    )
    def provenance(derived_metric_id: str, service: BackendDependency) -> ProvenanceGraph:
        found = service.provenance(derived_metric_id)
        if found is None:
            raise HTTPException(
                status_code=404,
                detail=f"derived metric {derived_metric_id!r} is not registered",
            )
        return found

    @app.get("/api/quality", response_model=QualityIssuePage, tags=["quality"])
    def quality(
        service: BackendDependency,
        dataset_id: str | None = None,
        session_id: str | None = None,
        severity: str | None = Query(default=None, pattern="^(INFO|WARNING|ERROR)$"),
        limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
        offset: int = Query(default=0, ge=0),
    ) -> QualityIssuePage:
        return service.quality(dataset_id, session_id, severity, limit, offset)

    @app.get("/api/runs", response_model=RunPage, tags=["provenance"])
    def runs(
        service: BackendDependency,
        dataset_id: str | None = None,
        limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
        offset: int = Query(default=0, ge=0),
    ) -> RunPage:
        total, rows = service.runs(dataset_id, limit, offset)
        return RunPage(total=total, limit=limit, offset=offset, rows=rows)

    @app.get("/api/rights", response_model=RightsPage, tags=["rights"])
    def rights(service: BackendDependency) -> RightsPage:
        return RightsPage(policies=service.licenses())

    @app.get(
        "/api/tactical/capabilities/{dataset_id}",
        response_model=TacticalCapabilityView,
        tags=["tactical"],
    )
    def tactical_capabilities(
        dataset_id: str, service: BackendDependency
    ) -> TacticalCapabilityView:
        found = service.tactical_capability(dataset_id)
        if found is None:
            raise HTTPException(
                status_code=404, detail=f"tactical capability for {dataset_id!r} is unavailable"
            )
        return found

    @app.get(
        "/api/tactical/methodology",
        response_model=TacticalMethodologyPage,
        tags=["tactical"],
    )
    def tactical_methodology(service: BackendDependency) -> TacticalMethodologyPage:
        return service.tactical_methodology()

    @app.get(
        "/api/tactical/quality/{dataset_id}",
        response_model=TacticalQualityView,
        tags=["tactical"],
    )
    def tactical_quality(dataset_id: str, service: BackendDependency) -> TacticalQualityView:
        found = service.tactical_quality(dataset_id)
        if found is None:
            raise HTTPException(
                status_code=404, detail=f"tactical quality for {dataset_id!r} is unavailable"
            )
        return found

    @app.get(
        "/api/tactical/artifacts",
        response_model=list[ArtifactRefView],
        tags=["tactical"],
    )
    def tactical_artifacts(
        dataset_id: str,
        service: BackendDependency,
        session_id: str | None = None,
        stream_id: str | None = None,
        series_name: str | None = None,
    ) -> list[ArtifactRefView]:
        return service.tactical_artifacts(dataset_id, session_id, stream_id, series_name)

    @app.get(
        "/api/processing/artifacts",
        response_model=list[ArtifactRefView],
        tags=["processing"],
    )
    def processing_artifacts(
        dataset_id: str,
        service: BackendDependency,
        session_id: str | None = None,
        stream_id: str | None = None,
        algorithm_id: str | None = None,
        series_name: str | None = None,
    ) -> list[ArtifactRefView]:
        return service.processing_artifacts(
            dataset_id,
            session_id,
            stream_id,
            algorithm_id,
            series_name,
        )

    @app.get(
        "/api/pose/range-report",
        response_model=PoseRangeReportView,
        tags=["pose"],
    )
    def pose_range_report(
        dataset_id: str,
        session_id: str,
        stream_id: str,
        subject_id: str,
        from_ns: int,
        to_ns: int,
        service: BackendDependency,
        landmark_name: str = Query(min_length=1, max_length=128),
    ) -> PoseRangeReportView:
        try:
            report = service.pose_range_report(
                dataset_id,
                session_id,
                stream_id,
                subject_id,
                from_ns,
                to_ns,
                landmark_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if report is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Pose range report requires current processor series for the selected stream"
                ),
            )
        return report

    def _tactical_series(
        artifact_id: str,
        request: Request,
        service: BackendDependency,
        *,
        from_ns: int | None,
        to_ns: int | None,
        columns: str | None,
        max_points: int | None,
        required_level: str | None = None,
    ) -> tuple[TacticalSeriesView | None, dict[str, str] | Response | None]:
        ref = service.artifact(artifact_id)
        if ref is None:
            raise HTTPException(
                status_code=404, detail=f"artifact {artifact_id!r} is not registered"
            )
        metadata = ref.artifact_metadata
        level_value = str(metadata.get("tactical_level") or "A")
        if level_value not in {"A", "B", "C", "D", "E", "V3"}:
            raise HTTPException(
                status_code=500, detail="tactical artifact has invalid level metadata"
            )
        if required_level is not None and level_value != required_level:
            raise HTTPException(
                status_code=400,
                detail=f"artifact {artifact_id!r} must be Level {required_level} for this endpoint",
            )
        parsed_columns = _parse_columns(columns)
        etag = window_etag(
            ref,
            from_ns=from_ns,
            to_ns=to_ns,
            columns=parsed_columns,
            max_points=max_points,
            entity_id=None,
            representation="tactical-json",
        )
        if request.headers.get("if-none-match") == etag:
            return None, Response(status_code=304, headers={"ETag": etag, "Vary": "Accept"})
        result = service.window(
            artifact_id,
            from_ns=from_ns,
            to_ns=to_ns,
            columns=parsed_columns,
            max_points=max_points,
        )
        level = cast(Literal["A", "B", "C", "D", "E", "V3"], level_value)
        tactical_meta = TacticalSeriesMeta(
            artifact=ref,
            series_name=str(metadata.get("series_name") or "unknown"),
            level=level,
            measurement_class=ref.measurement_class or "PIPELINE_DERIVED",
            input_measurement_class=(
                metadata.get("input_measurement_class")
                if isinstance(metadata.get("input_measurement_class"), str)
                else None
            ),
            coordinate_frame_id=ref.coordinate_frame_id,
            algorithm_id=ref.algorithm_id,
            algorithm_version=ref.algorithm_version,
            parameters_hash=ref.parameters_hash,
            from_ns=result.meta.from_ns,
            to_ns=result.meta.to_ns,
            source_rows=result.meta.source_rows,
            returned_rows=result.meta.returned_rows,
            quality=dict(metadata.get("quality") or {}),
            display_note=(
                "Authoritative processor output; MODEL_ESTIMATED means an assumption-bearing "
                "model, not measured territory."
                if ref.measurement_class == "MODEL_ESTIMATED"
                else "Provider source context preserved without tactical relabeling."
                if ref.measurement_class == "SOURCE_DERIVED"
                else "Authoritative deterministic processor output."
            ),
        )
        return (
            TacticalSeriesView(meta=tactical_meta, rows=table_records(result.table)),
            {"ETag": etag, "Vary": "Accept"},
        )

    @app.get(
        "/api/tactical/series/{artifact_id}",
        response_model=TacticalSeriesView,
        tags=["tactical"],
    )
    def tactical_series(
        artifact_id: str,
        request: Request,
        service: BackendDependency,
        from_ns: int | None = Query(default=None),
        to_ns: int | None = Query(default=None),
        columns: str | None = Query(default=None),
        max_points: int | None = Query(default=None, ge=1, le=100_000),
    ) -> Response:
        payload, response = _tactical_series(
            artifact_id,
            request,
            service,
            from_ns=from_ns,
            to_ns=to_ns,
            columns=columns,
            max_points=max_points,
        )
        if payload is None:
            assert isinstance(response, Response)
            return response
        assert isinstance(response, dict)
        return JSONResponse(content=payload.model_dump(mode="json"), headers=response)

    @app.get(
        "/api/tactical/events/{artifact_id}",
        response_model=TacticalEventPage,
        tags=["tactical"],
    )
    def tactical_events(
        artifact_id: str,
        request: Request,
        service: BackendDependency,
        from_ns: int | None = Query(default=None),
        to_ns: int | None = Query(default=None),
        max_points: int | None = Query(default=None, ge=1, le=100_000),
    ) -> Response:
        payload, response = _tactical_series(
            artifact_id,
            request,
            service,
            from_ns=from_ns,
            to_ns=to_ns,
            columns=None,
            max_points=max_points,
            required_level="D",
        )
        if payload is None:
            assert isinstance(response, Response)
            return response
        assert isinstance(response, dict)
        event_rows = [TacticalEventView(**row) for row in payload.rows]
        event_page = TacticalEventPage(meta=payload.meta, rows=event_rows)
        return JSONResponse(content=event_page.model_dump(mode="json"), headers=response)

    @app.get(
        "/api/artifacts/{artifact_id}",
        response_model=ArtifactDetail,
        tags=["dense"],
    )
    def artifact(artifact_id: str, service: BackendDependency) -> ArtifactDetail:
        found = service.artifact_detail(artifact_id)
        if found is None:
            raise HTTPException(
                status_code=404, detail=f"artifact {artifact_id!r} is not registered"
            )
        return found

    @app.get(
        "/api/artifacts/{artifact_id}/observations",
        response_model=list[EntityObservationView],
        tags=["dense"],
        responses={404: {"description": "Artifact not found"}},
    )
    def artifact_observations(
        artifact_id: str,
        service: BackendDependency,
        from_ns: int | None = Query(default=None),
        to_ns: int | None = Query(default=None),
    ) -> list[EntityObservationView]:
        found = service.artifact_observations(artifact_id, from_ns=from_ns, to_ns=to_ns)
        if found is None:
            raise HTTPException(
                status_code=404, detail=f"artifact {artifact_id!r} is not registered"
            )
        return found

    @app.get(
        "/api/artifacts/{artifact_id}/window",
        tags=["dense"],
        # The JSON branch is the typed document; the Arrow branch returns a
        # binary IPC stream with the same metadata in X-Dynamis-Window-Meta.
        response_model=DenseWindow,
    )
    def artifact_window(
        artifact_id: str,
        request: Request,
        service: BackendDependency,
        # Canonical t_rel_ns is signed: a trial aligned on a source event (the
        # White CMJ takeoff) runs from a negative time up to zero, so the
        # window bounds must accept negative nanoseconds.
        from_ns: int | None = Query(default=None),
        to_ns: int | None = Query(default=None),
        columns: str | None = Query(default=None),
        max_points: int | None = Query(default=None, ge=1, le=100_000),
        entity_id: str | None = Query(default=None, max_length=128),
        format: str = Query(default="json", pattern="^(json|arrow)$"),
    ) -> Response:
        parsed_columns = _parse_columns(columns)
        ref = service.artifact(artifact_id)
        if ref is None:
            raise HTTPException(
                status_code=404, detail=f"artifact {artifact_id!r} is not registered"
            )
        wants_arrow = format == "arrow" or ARROW_MEDIA_TYPE in request.headers.get("accept", "")
        etag = window_etag(
            ref,
            from_ns=from_ns,
            to_ns=to_ns,
            columns=parsed_columns,
            max_points=max_points,
            entity_id=entity_id,
            representation="arrow" if wants_arrow else "json",
        )
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag, "Vary": "Accept"})
        result = service.window(
            artifact_id,
            from_ns=from_ns,
            to_ns=to_ns,
            columns=parsed_columns,
            max_points=max_points,
            entity_id=entity_id,
        )
        headers = {
            "ETag": etag,
            "Vary": "Accept",
            "X-Dynamis-Window-Meta": window_metadata_header(result.meta),
        }
        if wants_arrow:
            return Response(
                content=arrow_ipc_stream(result.table),
                media_type=ARROW_MEDIA_TYPE,
                headers=headers,
            )
        payload = DenseWindow(meta=result.meta, rows=table_records(result.table))
        return JSONResponse(content=payload.model_dump(mode="json"), headers=headers)

    return app


def app() -> FastAPI:  # pragma: no cover - uvicorn factory hook
    """Uvicorn factory hook (``--factory dynamis.serving.app:app``)."""
    return create_app()


__all__ = [
    "API_VERSION",
    "ARROW_MEDIA_TYPE",
    "PostgresServingBackend",
    "ServingBackend",
    "app",
    "create_app",
    "get_backend",
]
