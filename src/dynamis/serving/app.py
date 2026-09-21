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
from typing import Annotated, Any, Protocol

import pyarrow.parquet as pq
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from dynamis.config import ConfigurationError, Settings
from dynamis.config import settings as resolve_settings
from dynamis.gold.publish import resolve_gold_schema
from dynamis.serving import repository
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
    load_artifact_window,
    resolve_artifact_path,
    table_records,
    window_etag,
    window_metadata_header,
)
from dynamis.serving.models import (
    ArtifactDetail,
    ArtifactRefView,
    DatasetDetail,
    DatasetSummary,
    DenseWindow,
    HealthStatus,
    MetricCatalogEntry,
    MetricMethodology,
    MetricPage,
    ProvenanceGraph,
    QualityIssuePage,
    RightsPage,
    RightsPolicyView,
    RunPage,
    RunView,
    ServingStatus,
    SessionDetail,
    SessionSummary,
)
from dynamis.storage.control_plane import control_plane_engine

API_VERSION = "0.1.0"
ACCESS_LOG = logging.getLogger("dynamis.access")
DEFAULT_PAGE_LIMIT = 100
MAX_PAGE_LIMIT = 1000

ARROW_MEDIA_TYPE = "application/vnd.apache.arrow.stream"


class ServingBackend(Protocol):
    """Everything the HTTP layer needs; implemented over PostgreSQL + Parquet."""

    def status(self) -> ServingStatus: ...

    def datasets(self) -> list[DatasetSummary]: ...

    def dataset(self, dataset_id: str) -> DatasetDetail | None: ...

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
            return repository.list_datasets(connection)

    def dataset(self, dataset_id: str) -> DatasetDetail | None:
        with self._connect() as connection:
            return repository.dataset_detail(connection, dataset_id)

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
        )

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
    backend: ServingBackend | None = None,
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
