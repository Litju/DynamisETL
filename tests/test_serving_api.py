"""HTTP and dense-window contracts for the analytical API.

Route tests use a deterministic in-process backend, so they exercise the full
FastAPI surface (status codes, query validation, ETag, Arrow transport, OpenAPI)
without a live PostgreSQL. The dense tests read real Parquet files under a
temporary dataset root. A separate PostgreSQL suite (marked ``postgres``) covers
the SQL repository.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from dynamis.config import Settings
from dynamis.serving.app import ARROW_MEDIA_TYPE, PostgresServingBackend, create_app
from dynamis.serving.dense import (
    ArtifactPathError,
    DenseWindowTooLarge,
    arrow_ipc_stream,
    canonical_timespan,
    entity_cardinality,
    entity_column,
    entity_ids,
    entity_observations,
    load_artifact_window,
    resolve_artifact_path,
)
from dynamis.serving.models import (
    AlgorithmView,
    ArtifactDetail,
    ArtifactRefView,
    DatasetDetail,
    DatasetSummary,
    DenseWindowMeta,
    EntityObservationView,
    LicenseView,
    MetricCatalogEntry,
    MetricDefinitionView,
    MetricMethodology,
    MetricPage,
    MetricValue,
    PitchDimensionsView,
    PoseRangeMetricView,
    PoseRangeReportView,
    ProvenanceEdge,
    ProvenanceGraph,
    ProvenanceNode,
    QualityIssuePage,
    QualityIssueView,
    RightsPolicyView,
    RunView,
    ServingStatus,
    SessionDetail,
    SessionParticipantView,
    SessionSummary,
    StreamView,
    TrialView,
)
from dynamis.serving.repository import MetricFilters
from dynamis.storage.object_store import ObjectMetadata, S3ObjectStore

LICENSE = LicenseView(
    policy_id="skillcorner-opendata",
    identifier="CC BY 4.0",
    status="declared",
    attribution_required=True,
    noncommercial_only=False,
    share_alike=False,
    redistribution="conditional",
    local_only=False,
    restrictions=[],
    notice="CC BY 4.0; attribution required; redistribution: conditional",
)

DATASET = DatasetSummary(
    dataset_id="skillcorner-opendata",
    name="SkillCorner Open Data",
    provider="SkillCorner",
    domain="football",
    doi=None,
    upstream_urls=["https://github.com/SkillCorner/opendata"],
    modalities=["tracking", "pose"],
    license=LICENSE,
    version_count=1,
    session_count=1,
    subject_count=23,
    trial_count=2,
    stream_count=3,
    metric_count=4,
    quality_issue_count=1,
)

METRIC = MetricValue(
    derived_metric_id="dm-pose-rom",
    dataset_id="skillcorner-opendata",
    metric_id="pose.angular_rom.left_knee",
    metric_name="Range of motion for angle left_knee",
    metric_description="max - min of the observed angle.",
    si_unit="rad",
    measurement_class="PIPELINE_DERIVED",
    value_kind="scalar",
    value_num=2.7,
    value_json=None,
    subject_id="SC-P1",
    session_id="1925299",
    trial_id="period_1",
    stream_id="pose-period-1",
    entity_id="SC-P1",
    algorithm_id="pose.translation_invariant_kinematics",
    algorithm_version="1.0.0",
    parameters_hash="e" * 64,
    code_git_sha="b" * 40,
    run_id="run-pose",
    computed_at="2026-09-18T12:00:00+00:00",
    provenance={"gap_policy": {"strategy": "contiguous_segments"}},
)

ARTIFACT = ArtifactRefView(
    artifact_id="sample-1",
    dataset_id="skillcorner-opendata",
    stream_id="tracking-period-1",
    layer="silver",
    relative_path="silver/dataset_id=skillcorner-opendata/tracking/sample-1.parquet",
    format="parquet",
    compression="zstd",
    checksum_sha256="a" * 64,
    row_count=100,
    byte_size=4096,
    artifact_kind="sample",
    modality="tracking",
    measurement_class="MODEL_ESTIMATED",
    si_units=["m"],
    coordinate_frame_id="skillcorner-pitch-m",
    synchronization_spec_id="skillcorner-source-provided-match-clock",
)

PROCESSING_ARTIFACT = ArtifactRefView(
    **{
        **ARTIFACT.model_dump(),
        "artifact_id": "pose-landmark-series",
        "layer": "gold",
        "relative_path": "gold/pose-landmark-series.parquet",
        "artifact_kind": "processing",
        "modality": None,
        "measurement_class": "PIPELINE_DERIVED",
        "algorithm_id": "pose.landmark_kinematics",
        "algorithm_version": "1.0.0",
        "parameters_hash": "c" * 64,
        "run_id": "run-pose-landmarks",
        "artifact_metadata": {"series_name": "pose_landmark_kinematics"},
    }
)


def _window_result() -> Any:
    table = pa.table(
        {
            "t_rel_ns": pa.array([0, 40_000_000], type=pa.int64()),
            "x_m": pa.array([1.0, 2.0], type=pa.float64()),
        }
    )
    meta = DenseWindowMeta(
        artifact=ARTIFACT,
        from_ns=0,
        to_ns=40_000_000,
        columns=["t_rel_ns", "x_m"],
        source_rows=2,
        returned_rows=2,
        canonical_time_min_ns=0,
        canonical_time_max_ns=40_000_000,
        reduction=None,
        units={"x_m": "m"},
        coordinate_frame_id=ARTIFACT.coordinate_frame_id,
        measurement_class=ARTIFACT.measurement_class,
        display_note="Exact canonical samples.",
    )
    from dynamis.serving.dense import DenseWindowResult

    return DenseWindowResult(table=table, meta=meta)


class FakeBackend:
    """Deterministic backend covering both successful and failing states."""

    def __init__(self) -> None:
        self.window_error: Exception | None = None
        self.last_filters: MetricFilters | None = None
        self.last_window_kwargs: dict[str, Any] = {}
        self.last_processing_filters: dict[str, str | None] | None = None
        self.last_pose_range_request: tuple[Any, ...] | None = None

    def status(self) -> ServingStatus:
        return ServingStatus(
            database="ok",
            db_schema="dynamis",
            gold_schema="gold",
            gold_published=True,
            dataset_count=1,
            metric_count=1,
            run_count=1,
            quality_issue_count=1,
        )

    def datasets(self) -> list[DatasetSummary]:
        return [DATASET]

    def dataset(self, dataset_id: str) -> DatasetDetail | None:
        if dataset_id != DATASET.dataset_id:
            return None
        return DatasetDetail(
            **DATASET.model_dump(),
            versions=[],
            v1_role="tracking and pose reference",
            initial_scope="match 1925299",
            adapter_id="skillcorner_adapter",
        )

    def sessions(self, dataset_id: str) -> list[SessionSummary]:
        return [
            SessionSummary(
                session_id="1925299",
                kind="match",
                label="Eintracht Frankfurt vs Bayern",
                started_at=None,
                ended_at=None,
                participant_count=23,
                trial_count=2,
                stream_count=3,
            )
        ]

    def session(self, dataset_id: str, session_id: str) -> SessionDetail | None:
        if session_id != "1925299":
            return None
        return SessionDetail(
            dataset_id=dataset_id,
            session=self.sessions(dataset_id)[0],
            participants=[
                SessionParticipantView(subject_id="SC-P1", role="player", group_label="home")
            ],
            trials=[
                TrialView(
                    trial_id="period_1",
                    subject_id=None,
                    parent_trial_id=None,
                    label="first half",
                    started_at=None,
                    ended_at=None,
                )
            ],
            streams=[
                StreamView(
                    stream_id="tracking-period-1",
                    modality="tracking",
                    measurement_class="MODEL_ESTIMATED",
                    subject_id=None,
                    trial_id="period_1",
                    device_id=None,
                    nominal_sampling_rate_hz=10.0,
                    si_units=["m"],
                    source_unit="m",
                    coordinate_frame_id="skillcorner-pitch-m",
                    synchronization_spec_id="skillcorner-source-provided-match-clock",
                    clock_id="skillcorner-match-clock",
                    skeleton_id=None,
                    pitch_dimensions_m=PitchDimensionsView(length_m=105.0, width_m=68.0),
                    sample_artifact_ids=["sample-1"],
                    sample_row_count=100,
                )
            ],
        )

    def metrics(self, filters: MetricFilters, limit: int, offset: int) -> MetricPage:
        self.last_filters = filters
        return MetricPage(source="gold", total=1, limit=limit, offset=offset, rows=[METRIC])

    def processing_artifacts(
        self,
        dataset_id: str,
        session_id: str | None = None,
        stream_id: str | None = None,
        algorithm_id: str | None = None,
        series_name: str | None = None,
    ) -> list[ArtifactRefView]:
        self.last_processing_filters = {
            "dataset_id": dataset_id,
            "session_id": session_id,
            "stream_id": stream_id,
            "algorithm_id": algorithm_id,
            "series_name": series_name,
        }
        return [PROCESSING_ARTIFACT]

    def pose_range_report(
        self,
        dataset_id: str,
        session_id: str,
        stream_id: str,
        subject_id: str,
        from_ns: int,
        to_ns: int,
        landmark_name: str,
    ) -> PoseRangeReportView:
        self.last_pose_range_request = (
            dataset_id,
            session_id,
            stream_id,
            subject_id,
            from_ns,
            to_ns,
            landmark_name,
        )
        return PoseRangeReportView(
            algorithm_id="pose.range_summary",
            algorithm_version="1.0.0",
            parameters_hash="e" * 64,
            code_git_sha="f" * 40,
            dataset_id=dataset_id,
            session_id=session_id,
            trial_id="period-1",
            stream_id=stream_id,
            subject_id=subject_id,
            from_ns=from_ns,
            to_ns=to_ns,
            input_artifact_checksums={"pose_source": "a" * 64},
            metrics=[
                PoseRangeMetricView(
                    metric_id="pose.range.landmark.speed_mean.lKnee",
                    metric_name="Mean knee speed",
                    si_unit="m/s",
                    value_num=1.0,
                    description="A precomputed series summary.",
                    provenance={"scope": "exact-range"},
                )
            ],
            display_note="Exact precomputed processor inputs.",
        )

    def metric_definitions(self) -> list[MetricCatalogEntry]:
        return []

    def methodology(self, metric_id: str) -> MetricMethodology | None:
        if metric_id != METRIC.metric_id:
            return None
        return MetricMethodology(
            metric=MetricDefinitionView(
                metric_id=METRIC.metric_id,
                name="Range of motion",
                si_unit="rad",
                measurement_class="PIPELINE_DERIVED",
                value_kind="scalar",
                description="max - min of the observed angle.",
                algorithm_id=METRIC.algorithm_id,
            ),
            algorithm=AlgorithmView(
                algorithm_id=str(METRIC.algorithm_id),
                name="Translation-invariant pose kinematics",
                version="1.0.0",
                kind="processor",
                code_git_sha=METRIC.code_git_sha,
                parameters_hash=METRIC.parameters_hash,
                parameters={"gap_policy": {"strategy": "contiguous_segments"}},
                description="Relative vectors and explicit angles.",
                citation=None,
            ),
            measurement_class_semantics="Computed by a versioned processor.",
            measurement_class_never_means=["PIPELINE_DERIVED is not a measurement."],
            provenance_fields=["run_id"],
        )

    def provenance(self, derived_metric_id: str) -> ProvenanceGraph | None:
        if derived_metric_id != METRIC.derived_metric_id:
            return None
        return ProvenanceGraph(
            derived_metric_id=derived_metric_id,
            nodes=[
                ProvenanceNode(
                    id="run:run-pose",
                    kind="processing_run",
                    label="run-pose",
                    status="completed",
                    details={},
                )
            ],
            edges=[
                ProvenanceEdge(
                    id="a->b", source="run:run-pose", target="derived:x", label="results in"
                )
            ],
            provenance={"code_git_sha": METRIC.code_git_sha},
            lineage_note="Selected result lineage only.",
        )

    def quality(
        self,
        dataset_id: str | None,
        session_id: str | None,
        severity: str | None,
        limit: int,
        offset: int,
    ) -> QualityIssuePage:
        return QualityIssuePage(
            total=1,
            limit=limit,
            offset=offset,
            rows=[
                QualityIssueView(
                    issue_id="q-1",
                    dataset_id="skillcorner-opendata",
                    run_id=None,
                    session_id="1925299",
                    stream_id="tracking-period-1",
                    subject_id=None,
                    trial_id=None,
                    sample_index=10,
                    rule="tracking.ball_gap",
                    severity="WARNING",
                    state="VALID",
                    evidence={"gap_frames": 3},
                    detected_at="2026-09-18T12:00:00+00:00",
                )
            ],
        )

    def runs(self, dataset_id: str | None, limit: int, offset: int) -> tuple[int, list[RunView]]:
        return (
            1,
            [
                RunView(
                    run_id="run-pose",
                    dataset_id="skillcorner-opendata",
                    algorithm_id="pose.translation_invariant_kinematics",
                    algorithm_name="Pose kinematics",
                    algorithm_version="1.0.0",
                    kind="processor",
                    status="completed",
                    code_git_sha="b" * 40,
                    parameters_hash="e" * 64,
                    started_at=None,
                    completed_at=None,
                    input_checksums=["c" * 64],
                    metric_count=4,
                    artifact_count=1,
                    notes=None,
                )
            ],
        )

    def licenses(self) -> list[RightsPolicyView]:
        return [RightsPolicyView(license=LICENSE, dataset_ids=["skillcorner-opendata"])]

    def artifact(self, artifact_id: str) -> ArtifactRefView | None:
        return ARTIFACT if artifact_id == ARTIFACT.artifact_id else None

    def artifact_detail(self, artifact_id: str) -> ArtifactDetail | None:
        if artifact_id != ARTIFACT.artifact_id:
            return None
        return ArtifactDetail(
            **ARTIFACT.model_dump(),
            canonical_time_min_ns=0,
            canonical_time_max_ns=100_000_000,
            entity_column="object_id",
            entity_count=3,
            entity_ids=["p1", "p2", "p3"],
        )

    def artifact_observations(
        self, artifact_id: str, *, from_ns: int | None, to_ns: int | None
    ) -> list[EntityObservationView] | None:
        if artifact_id != ARTIFACT.artifact_id:
            return None
        return []

    def window(self, artifact_id: str, **kwargs: Any):
        if self.window_error is not None:
            raise self.window_error
        self.last_window_kwargs = dict(kwargs)
        return _window_result()


@pytest.fixture
def client() -> TestClient:
    backend = FakeBackend()
    app = create_app(backend=backend)
    app.state.fake_backend = backend
    return TestClient(app)


def test_health_and_serving_status(client: TestClient) -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    ready = client.get("/api/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ok"
    status = client.get("/api/serving/status")
    assert status.status_code == 200
    body = status.json()
    assert body["gold_published"] is True
    assert body["db_schema"] == "dynamis"


def test_catalog_routes_preserve_rights_and_measurement_context(client: TestClient) -> None:
    datasets = client.get("/api/catalog/datasets").json()
    assert datasets[0]["dataset_id"] == "skillcorner-opendata"
    assert "attribution required" in datasets[0]["license"]["notice"]
    detail = client.get("/api/catalog/datasets/skillcorner-opendata")
    assert detail.status_code == 200
    assert detail.json()["adapter_id"] == "skillcorner_adapter"
    assert client.get("/api/catalog/datasets/unknown").status_code == 404
    sessions = client.get("/api/catalog/datasets/skillcorner-opendata/sessions").json()
    assert sessions[0]["kind"] == "match"
    session = client.get("/api/catalog/datasets/skillcorner-opendata/sessions/1925299")
    assert session.status_code == 200
    stream = session.json()["streams"][0]
    assert stream["measurement_class"] == "MODEL_ESTIMATED"
    assert stream["sample_artifact_ids"] == ["sample-1"]
    assert stream["pitch_dimensions_m"] == {"length_m": 105.0, "width_m": 68.0}
    assert session.json()["participants"][0]["group_label"] == "home"


def test_pitch_dimensions_require_positive_finite_source_metres() -> None:
    assert PitchDimensionsView(length_m=105.0, width_m=68.0).width_m == 68.0
    with pytest.raises(ValueError):
        PitchDimensionsView(length_m=0.0, width_m=68.0)
    with pytest.raises(ValueError):
        PitchDimensionsView(length_m=float("nan"), width_m=68.0)
    with pytest.raises(ValueError):
        PitchDimensionsView.model_validate({"length_m": "105.0", "width_m": 68.0})


def test_metrics_route_passes_filters_and_exposes_provenance(client: TestClient) -> None:
    response = client.get(
        "/api/metrics",
        params={"dataset_id": "skillcorner-opendata", "subject_id": "SC-P1", "limit": 10},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "gold"
    row = body["rows"][0]
    assert row["measurement_class"] == "PIPELINE_DERIVED"
    assert row["algorithm_id"] == "pose.translation_invariant_kinematics"
    assert row["code_git_sha"] == "b" * 40
    backend = client.app.state.fake_backend  # type: ignore[attr-defined]
    assert backend.last_filters.dataset_id == "skillcorner-opendata"
    assert backend.last_filters.subject_id == "SC-P1"
    assert client.get("/api/metrics", params={"limit": 0}).status_code == 422
    assert client.get("/api/metrics", params={"limit": 5000}).status_code == 422


def test_methodology_and_provenance_routes(client: TestClient) -> None:
    methodology = client.get(f"/api/metrics/methodology/{METRIC.metric_id}")
    assert methodology.status_code == 200
    body = methodology.json()
    assert body["measurement_class_never_means"]
    assert body["algorithm"]["parameters"]["gap_policy"]["strategy"] == "contiguous_segments"
    assert client.get("/api/metrics/methodology/unknown.metric").status_code == 404
    provenance = client.get(f"/api/derived-metrics/{METRIC.derived_metric_id}/provenance")
    assert provenance.status_code == 200
    graph = provenance.json()
    assert any(node["kind"] == "processing_run" for node in graph["nodes"])
    assert graph["lineage_note"].startswith("Selected result lineage only")
    assert client.get("/api/derived-metrics/unknown/provenance").status_code == 404


def test_quality_runs_and_rights_routes(client: TestClient) -> None:
    quality = client.get("/api/quality", params={"severity": "WARNING"}).json()
    assert quality["rows"][0]["evidence"] == {"gap_frames": 3}
    assert client.get("/api/quality", params={"severity": "BOGUS"}).status_code == 422
    runs = client.get("/api/runs").json()
    assert runs["rows"][0]["code_git_sha"] == "b" * 40
    rights = client.get("/api/rights").json()
    assert rights["policies"][0]["license"]["identifier"] == "CC BY 4.0"


def test_dense_window_json_arrow_and_etag(client: TestClient) -> None:
    artifact = client.get(f"/api/artifacts/{ARTIFACT.artifact_id}")
    assert artifact.status_code == 200
    assert artifact.json()["measurement_class"] == "MODEL_ESTIMATED"
    window = client.get(f"/api/artifacts/{ARTIFACT.artifact_id}/window")
    assert window.status_code == 200
    body = window.json()
    assert body["meta"]["source_rows"] == 2
    assert body["rows"][0]["x_m"] == 1.0
    etag = window.headers["etag"]
    cached = client.get(
        f"/api/artifacts/{ARTIFACT.artifact_id}/window",
        headers={"if-none-match": etag},
    )
    assert cached.status_code == 304
    assert cached.headers["vary"] == "Accept"
    arrow = client.get(
        f"/api/artifacts/{ARTIFACT.artifact_id}/window",
        params={"format": "arrow"},
    )
    assert arrow.status_code == 200
    assert arrow.headers["content-type"].startswith(ARROW_MEDIA_TYPE)
    assert arrow.headers["etag"] != etag
    assert json.loads(arrow.headers["x-dynamis-window-meta"])["returned_rows"] == 2
    arrow_cached = client.get(
        f"/api/artifacts/{ARTIFACT.artifact_id}/window",
        params={"format": "arrow"},
        headers={"if-none-match": arrow.headers["etag"]},
    )
    assert arrow_cached.status_code == 304
    assert arrow_cached.headers["vary"] == "Accept"
    assert client.get("/api/artifacts/unknown/window").status_code == 404


def test_dense_window_errors_map_to_explicit_states(client: TestClient) -> None:
    backend = client.app.state.fake_backend  # type: ignore[attr-defined]
    backend.window_error = DenseWindowTooLarge("too large")
    response = client.get(f"/api/artifacts/{ARTIFACT.artifact_id}/window")
    assert response.status_code == 413
    assert response.json()["state"] == "dense_window_too_large"
    backend.window_error = ArtifactPathError("missing")
    response = client.get(f"/api/artifacts/{ARTIFACT.artifact_id}/window")
    assert response.status_code == 404
    assert response.json()["state"] == "unavailable_for_source"


def test_openapi_document_covers_the_locked_surface() -> None:
    document = create_app(backend=FakeBackend()).openapi()
    paths = document["paths"]
    assert set(paths["/api/artifacts/{artifact_id}/observations"]["get"]["responses"]) >= {
        "200",
        "404",
    }
    for path in (
        "/api/health",
        "/api/serving/status",
        "/api/catalog/datasets",
        "/api/catalog/datasets/{dataset_id}",
        "/api/catalog/datasets/{dataset_id}/sessions",
        "/api/catalog/datasets/{dataset_id}/sessions/{session_id}",
        "/api/metrics",
        "/api/metrics/methodology/{metric_id}",
        "/api/derived-metrics/{derived_metric_id}/provenance",
        "/api/quality",
        "/api/runs",
        "/api/rights",
        "/api/processing/artifacts",
        "/api/pose/range-report",
        "/api/artifacts/{artifact_id}",
        "/api/artifacts/{artifact_id}/observations",
        "/api/artifacts/{artifact_id}/window",
    ):
        assert path in paths, path


def test_processing_artifacts_route_filters_scientific_series(client: TestClient) -> None:
    response = client.get(
        "/api/processing/artifacts",
        params={
            "dataset_id": "skillcorner-opendata",
            "session_id": "1925299",
            "stream_id": "pose-period-1",
            "algorithm_id": "pose.landmark_kinematics",
            "series_name": "pose_landmark_kinematics",
        },
    )

    assert response.status_code == 200
    assert response.json()[0]["artifact_kind"] == "processing"
    assert response.json()[0]["algorithm_id"] == "pose.landmark_kinematics"
    backend = client.app.state.fake_backend  # type: ignore[attr-defined]
    assert backend.last_processing_filters == {
        "dataset_id": "skillcorner-opendata",
        "session_id": "1925299",
        "stream_id": "pose-period-1",
        "algorithm_id": "pose.landmark_kinematics",
        "series_name": "pose_landmark_kinematics",
    }


def test_pose_range_report_route_preserves_subject_and_exact_bounds(client: TestClient) -> None:
    response = client.get(
        "/api/pose/range-report",
        params={
            "dataset_id": "skillcorner-opendata",
            "session_id": "1925299",
            "stream_id": "pose-period-1",
            "subject_id": "SC-P1",
            "from_ns": 40_000_000,
            "to_ns": 200_000_000,
            "landmark_name": "lKnee",
        },
    )

    assert response.status_code == 200
    assert response.json()["algorithm_id"] == "pose.range_summary"
    assert response.json()["from_ns"] == 40_000_000
    assert response.json()["to_ns"] == 200_000_000
    backend = client.app.state.fake_backend  # type: ignore[attr-defined]
    assert backend.last_pose_range_request == (
        "skillcorner-opendata",
        "1925299",
        "pose-period-1",
        "SC-P1",
        40_000_000,
        200_000_000,
        "lKnee",
    )


def _dense_artifact_ref(settings: Settings, table: pa.Table) -> ArtifactRefView:
    relative = Path("silver") / "dataset_id=demo" / "tracking" / "window.parquet"
    target = settings.dataset_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, target, compression="zstd")
    return ArtifactRefView(
        artifact_id="dense-demo",
        dataset_id="demo",
        stream_id="tracking-demo",
        layer="silver",
        relative_path=relative.as_posix(),
        format="parquet",
        compression="zstd",
        checksum_sha256="d" * 64,
        row_count=table.num_rows,
        byte_size=target.stat().st_size,
        artifact_kind="sample",
        modality="tracking",
        measurement_class="MODEL_ESTIMATED",
        si_units=[],
        coordinate_frame_id="demo-pitch",
        synchronization_spec_id="demo-sync",
    )


def test_dense_reduction_preserves_extrema_and_identity(tmp_settings: Settings) -> None:
    frames = list(range(100))
    table = pa.table(
        {
            "object_id": pa.array(["p1"] * 100, type=pa.string()),
            "t_rel_ns": pa.array([index * 40_000_000 for index in frames], type=pa.int64()),
            "x_m": pa.array([float(index) for index in frames], type=pa.float64()),
            "is_detected": pa.array([True] * 100, type=pa.bool_()),
        }
    )
    ref = _dense_artifact_ref(tmp_settings, table)
    result = load_artifact_window(tmp_settings, ref, max_points=10)
    assert result.meta.source_rows == 100
    assert result.meta.returned_rows <= 10
    assert result.meta.reduction is not None
    assert result.meta.reduction.method == "min_max_envelope_per_time_bucket"
    assert result.meta.reduction.source_points == 100
    assert set(result.table.column_names) >= {"object_id", "x_m_min", "x_m_max"}
    assert min(result.table.column("x_m_min").to_pylist()) == 0.0
    assert max(result.table.column("x_m_max").to_pylist()) == 99.0
    exact = load_artifact_window(tmp_settings, ref, from_ns=0, to_ns=40_000_000)
    assert exact.meta.reduction is None
    assert exact.table.num_rows == 2


def test_dense_window_scopes_to_one_entity(tmp_settings: Settings) -> None:
    """A viewer that renders one entity must not pay for every other entity.

    A dense artifact interleaves entities on one time axis, so without scoping
    a pose or tracking window overruns the point budget and comes back
    display-reduced — which a replay cannot use, because a per-bucket extremum
    is not an observed position.
    """
    frames = list(range(50))
    table = pa.table(
        {
            "object_id": pa.array(
                [entity for _ in frames for entity in ("p1", "p2", "p3")], type=pa.string()
            ),
            "t_rel_ns": pa.array(
                [index * 40_000_000 for index in frames for _ in range(3)], type=pa.int64()
            ),
            "x_m": pa.array(
                [float(index) for index in frames for _ in range(3)], type=pa.float64()
            ),
        }
    )
    ref = _dense_artifact_ref(tmp_settings, table)

    everyone = load_artifact_window(tmp_settings, ref, max_points=60)
    assert everyone.meta.source_rows == 150
    assert everyone.meta.reduction is not None
    assert everyone.meta.returned_rows <= 60

    # The same budget serves exact frames once the window names one entity.
    scoped = load_artifact_window(tmp_settings, ref, max_points=60, entity_id="p2")
    assert scoped.meta.source_rows == 50
    assert scoped.meta.reduction is None
    assert set(scoped.table.column("object_id").to_pylist()) == {"p2"}

    # Cardinality is what a viewer divides by to size its window.
    assert entity_cardinality(tmp_settings, ref) == 3
    assert entity_ids(tmp_settings, ref) == ["p1", "p2", "p3"]
    assert entity_column(pq.read_schema(resolve_artifact_path(tmp_settings, ref))) == "object_id"


def test_processed_series_scopes_windows_by_entity_id(tmp_settings: Settings) -> None:
    table = pa.table(
        {
            "entity_id": pa.array(["s1", "s2", "s1"], type=pa.string()),
            "t_rel_ns": pa.array([0, 0, 40_000_000], type=pa.int64()),
            "body_relative_speed_lKnee_m_s": pa.array([1.0, 9.0, 1.5], type=pa.float64()),
        }
    )
    ref = _dense_artifact_ref(tmp_settings, table).model_copy(
        update={"artifact_kind": "processing"}
    )

    scoped = load_artifact_window(tmp_settings, ref, entity_id="s1")

    assert entity_column(pq.read_schema(resolve_artifact_path(tmp_settings, ref))) == "entity_id"
    assert scoped.table.column("body_relative_speed_lKnee_m_s").to_pylist() == [1.0, 1.5]


def test_pose_entity_observation_authority_excludes_unavailable_rows(
    tmp_settings: Settings,
) -> None:
    table = pa.table(
        {
            "subject_id": pa.array(["s1", "s1", "s1", "s2", "s2"], type=pa.string()),
            "t_rel_ns": pa.array([0, 40, 80, 40, 80], type=pa.int64()),
            "joint_name": pa.array(["nose"] * 5, type=pa.string()),
            "is_available": pa.array([True, True, True, True, False], type=pa.bool_()),
            "x_m": pa.array([1.0, 1.0, 1.0, 2.0, None], type=pa.float64()),
            "y_m": pa.array([1.0, 1.0, 1.0, 2.0, None], type=pa.float64()),
            "z_m": pa.array([1.0, 1.0, 1.0, 2.0, None], type=pa.float64()),
        }
    )
    ref = _dense_artifact_ref(tmp_settings, table).model_copy(update={"modality": "pose"})

    observations = entity_observations(tmp_settings, ref)

    assert observations is not None
    assert [item.model_dump() for item in observations] == [
        {
            "entity_id": "s1",
            "first_observed_ns": 0,
            "last_observed_ns": 80,
            "observation_count": 3,
        },
        {
            "entity_id": "s2",
            "first_observed_ns": 40,
            "last_observed_ns": 40,
            "observation_count": 1,
        },
    ]


def test_pose_observation_summary_is_cached_by_immutable_artifact(
    tmp_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dynamis.serving import dense

    table = pa.table(
        {
            "subject_id": pa.array(["s1", "s1"], type=pa.string()),
            "t_rel_ns": pa.array([0, 40], type=pa.int64()),
            "is_available": pa.array([True, True], type=pa.bool_()),
            "x_m": pa.array([1.0, 1.0], type=pa.float64()),
            "y_m": pa.array([1.0, 1.0], type=pa.float64()),
            "z_m": pa.array([1.0, 1.0], type=pa.float64()),
        }
    )
    ref = _dense_artifact_ref(tmp_settings, table).model_copy(update={"modality": "pose"})
    dense._cached_entity_observation_rows.cache_clear()
    original = dense._query_entity_observation_rows
    calls = 0

    def counted(path: Path, column: str, from_ns: int | None, to_ns: int | None):
        nonlocal calls
        calls += 1
        return original(path, column, from_ns, to_ns)

    monkeypatch.setattr(dense, "_query_entity_observation_rows", counted)
    assert entity_observations(tmp_settings, ref) == entity_observations(tmp_settings, ref)
    assert calls == 1


def test_registered_s3_artifact_is_materialized_for_dense_serving(
    tmp_path: Path, tmp_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dynamis.serving import dense

    table = pa.table({"object_id": ["p1", "p1"], "t_rel_ns": [0, 10], "speed": [2.0, 3.0]})
    ref = _dense_artifact_ref(tmp_settings, table)
    source = resolve_artifact_path(tmp_settings, ref)
    data = source.read_bytes()
    checksum = hashlib.sha256(data).hexdigest()
    ref = ref.model_copy(update={"checksum_sha256": checksum, "byte_size": len(data)})
    settings = tmp_settings.model_copy(update={"object_store_provider": "s3"})
    store = S3ObjectStore(
        endpoint="https://objects.example",
        bucket="private",
        access_key="access",
        secret_key="secret",
    )
    monkeypatch.setattr(store, "head", lambda key: ObjectMetadata(key, len(data), checksum))
    monkeypatch.setattr(store, "get_range", lambda _key, start, end: data[start : end + 1])
    monkeypatch.setattr(dense, "object_store", lambda _settings: store)
    monkeypatch.setattr(dense, "_OBJECT_CACHE_ROOT", tmp_path / "object-cache")

    result = load_artifact_window(settings, ref, from_ns=0, to_ns=10)
    assert result.meta.returned_rows == 2
    assert set(result.table.column("object_id").to_pylist()) == {"p1"}


def test_dense_window_carries_signed_canonical_time(tmp_settings: Settings) -> None:
    """Event-aligned trials run up to zero from a negative canonical time.

    White CMJ records are aligned on the source-provided takeoff, so refusing a
    negative bound would make the flagship force trial unreachable.
    """
    table = pa.table(
        {
            "subject_id": pa.array(["white-s000"] * 4, type=pa.string()),
            "t_rel_ns": pa.array(
                [-1_345_000_000, -1_000_000_000, -500_000_000, 0], type=pa.int64()
            ),
            "force_z_body_weight_ratio": pa.array([1.0, 0.6, 2.7, 0.1], type=pa.float64()),
        }
    )
    ref = _dense_artifact_ref(tmp_settings, table)

    assert canonical_timespan(tmp_settings, ref) == (-1_345_000_000, 0)
    window = load_artifact_window(tmp_settings, ref, from_ns=-1_345_000_000, to_ns=-500_000_000)
    assert window.meta.returned_rows == 3
    assert window.meta.from_ns == -1_345_000_000
    assert window.table.column("t_rel_ns").to_pylist() == [
        -1_345_000_000,
        -1_000_000_000,
        -500_000_000,
    ]


def test_artifact_detail_serves_bounds_for_a_first_window(client: TestClient) -> None:
    response = client.get("/api/artifacts/sample-1")
    assert response.status_code == 200
    body = response.json()
    assert body["canonical_time_min_ns"] == 0
    assert body["canonical_time_max_ns"] == 100_000_000
    assert body["entity_column"] == "object_id"
    assert body["entity_count"] == 3


def test_artifact_observation_authority_route(client: TestClient) -> None:
    response = client.get("/api/artifacts/sample-1/observations")
    assert response.status_code == 200
    assert response.json() == []
    assert client.get("/api/artifacts/missing/observations").status_code == 404


def test_resolved_artifact_without_pose_observations_returns_empty_list(
    tmp_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = PostgresServingBackend(tmp_settings)
    monkeypatch.setattr(backend, "artifact", lambda _artifact_id: ARTIFACT)
    monkeypatch.setattr("dynamis.serving.app.entity_observations", lambda *_args, **_kwargs: None)
    assert backend.artifact_observations("sample-1", from_ns=None, to_ns=None) == []


def test_window_endpoint_accepts_negative_bounds_and_entity_scope(client: TestClient) -> None:
    backend: FakeBackend = client.app.state.fake_backend  # type: ignore[attr-defined]
    response = client.get(
        "/api/artifacts/sample-1/window",
        params={"from_ns": -1_345_000_000, "to_ns": 0, "entity_id": "white-s000"},
    )
    assert response.status_code == 200
    assert backend.last_window_kwargs["from_ns"] == -1_345_000_000
    assert backend.last_window_kwargs["entity_id"] == "white-s000"


def test_dense_window_rejects_path_traversal_and_row_overflow(tmp_settings: Settings) -> None:
    table = pa.table(
        {
            "object_id": pa.array(["p1"] * 3, type=pa.string()),
            "t_rel_ns": pa.array([0, 1, 2], type=pa.int64()),
            "x_m": pa.array([0.0, 1.0, 2.0], type=pa.float64()),
        }
    )
    ref = _dense_artifact_ref(tmp_settings, table)
    escaped = ref.model_copy(update={"relative_path": "../escape.parquet"})
    with pytest.raises(ArtifactPathError, match="outside the dataset root"):
        load_artifact_window(tmp_settings, escaped)
    with pytest.raises(DenseWindowTooLarge, match="row cap"):
        load_artifact_window(tmp_settings, ref, max_source_rows=1)
    absent = ref.model_copy(update={"relative_path": "silver/missing.parquet"})
    with pytest.raises(ArtifactPathError, match="missing"):
        load_artifact_window(tmp_settings, absent)


def test_dense_window_reports_contract_units(tmp_settings: Settings) -> None:
    schema = pa.schema(
        [
            pa.field("object_id", pa.string()),
            pa.field("t_rel_ns", pa.int64(), metadata={b"dynamis.si_unit": b"ns"}),
            pa.field("x_m", pa.float64(), metadata={b"dynamis.si_unit": b"m"}),
        ]
    )
    table = pa.Table.from_arrays(
        [
            pa.array(["p1", "p1"], type=pa.string()),
            pa.array([0, 1], type=pa.int64()),
            pa.array([0.0, 1.0], type=pa.float64()),
        ],
        schema=schema,
    )
    ref = _dense_artifact_ref(tmp_settings, table)
    result = load_artifact_window(tmp_settings, ref)
    assert result.meta.units == {"t_rel_ns": "ns", "x_m": "m"}
    assert result.meta.measurement_class == "MODEL_ESTIMATED"


def test_arrow_ipc_stream_round_trip() -> None:
    table = pa.table({"t_rel_ns": pa.array([0, 1], type=pa.int64())})
    payload = arrow_ipc_stream(table)
    reader = pa.ipc.open_stream(pa.BufferReader(payload))
    assert reader.read_all().equals(table)
