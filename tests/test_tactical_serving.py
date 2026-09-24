import pyarrow as pa
from fastapi.testclient import TestClient

from dynamis.serving import tactical as authority
from dynamis.serving.app import create_app
from dynamis.serving.dense import DenseWindowResult
from dynamis.serving.models import ArtifactRefView, DenseWindowMeta


class TacticalBackend:
    artifact_ref = ArtifactRefView(
        artifact_id="tactical-1",
        dataset_id="skillcorner-opendata",
        stream_id="tracking-period-1",
        layer="gold",
        relative_path="gold/tactical.parquet",
        format="parquet",
        compression="zstd",
        checksum_sha256="a" * 64,
        row_count=1,
        byte_size=100,
        artifact_kind="processing",
        modality=None,
        measurement_class="PIPELINE_DERIVED",
        si_units=[],
        coordinate_frame_id="pitch",
        synchronization_spec_id=None,
        algorithm_id="tactical.team_geometry",
        algorithm_version="1",
        parameters_hash="b" * 64,
        run_id="run-tactical",
        artifact_metadata={
            "series_name": "team_geometry",
            "tactical_level": "A",
            "input_measurement_class": "MODEL_ESTIMATED",
        },
    )

    def __init__(self) -> None:
        self.window_calls = 0

    def tactical_capability(self, dataset_id: str):
        return authority.tactical_capability(dataset_id)

    def tactical_methodology(self):
        return authority.tactical_methodology()

    def tactical_quality(self, dataset_id: str):
        return authority.tactical_quality(dataset_id)

    def tactical_artifacts(self, dataset_id, session_id=None, stream_id=None, series_name=None):
        return []

    def artifact(self, artifact_id):
        return self.artifact_ref if artifact_id == "tactical-1" else None

    def window(self, artifact_id, *, from_ns, to_ns, columns, max_points, entity_id=None):
        self.window_calls += 1
        table = pa.table(
            {
                "t_rel_ns": pa.array([0], type=pa.int64()),
                "group_id": pa.array(["home"]),
                "centroid_x_m": pa.array([1.0]),
            }
        )
        return DenseWindowResult(
            table=table,
            meta=DenseWindowMeta(
                artifact=self.artifact_ref,
                from_ns=0,
                to_ns=0,
                columns=list(table.column_names),
                source_rows=1,
                returned_rows=1,
                canonical_time_min_ns=0,
                canonical_time_max_ns=0,
                reduction=None,
                units={"centroid_x_m": "m"},
                coordinate_frame_id="pitch",
                measurement_class="PIPELINE_DERIVED",
                display_note="Exact.",
            ),
        )


def test_tactical_authority_routes_are_typed_and_fail_closed() -> None:
    client = TestClient(create_app(backend=TacticalBackend()))

    capabilities = client.get("/api/tactical/capabilities/dfl-sportec-idsse")
    assert capabilities.status_code == 200
    assert capabilities.json()["capabilities"]["level_d_event_linked"] == (
        "supported_source_snapshots_only"
    )
    assert capabilities.json()["capabilities"]["possession_context"] == (
        "supported_source_team_only"
    )
    assert capabilities.json()["semantics"]["attacking_direction"].startswith("unavailable")

    quality = client.get("/api/tactical/quality/womens-soccer-positioning")
    assert quality.status_code == 200
    assert quality.json()["capabilities"]["level_b_territory"] == "unavailable"

    methodology = client.get("/api/tactical/methodology")
    assert methodology.status_code == 200
    assert any(
        item["metric_id"] == "tactical.team.centroid_x" for item in methodology.json()["metrics"]
    )
    shape = next(
        item
        for item in methodology.json()["metrics"]
        if item["metric_id"] == "tactical.triangle.area"
    )
    assert shape["level"] == "V3"
    assert shape["algorithm_id"] == "tactical.matchlab_shape"

    assert client.get("/api/tactical/capabilities/not-a-dataset").status_code == 404


def test_tactical_paths_are_in_openapi() -> None:
    paths = create_app(backend=TacticalBackend()).openapi()["paths"]
    assert "/api/tactical/capabilities/{dataset_id}" in paths
    assert "/api/tactical/series/{artifact_id}" in paths
    assert "/api/tactical/events/{artifact_id}" in paths


def test_tactical_series_returns_json_and_preserves_etag() -> None:
    client = TestClient(create_app(backend=TacticalBackend()))
    response = client.get("/api/tactical/series/tactical-1")
    assert response.status_code == 200
    assert response.json()["rows"][0]["centroid_x_m"] == 1.0
    etag = response.headers["etag"]
    cached = client.get("/api/tactical/series/tactical-1", headers={"if-none-match": etag})
    assert cached.status_code == 304


def test_tactical_series_accepts_v3_level_metadata() -> None:
    backend = TacticalBackend()
    backend.artifact_ref = backend.artifact_ref.model_copy(
        update={
            "algorithm_id": "tactical.matchlab_shape",
            "artifact_metadata": {
                **backend.artifact_ref.artifact_metadata,
                "tactical_level": "V3",
                "series_name": "functional_unit_geometry",
            },
        }
    )
    response = TestClient(create_app(backend=backend)).get("/api/tactical/series/tactical-1")

    assert response.status_code == 200
    assert response.json()["meta"]["level"] == "V3"


def test_tactical_events_rejects_non_event_artifacts_before_window_read() -> None:
    backend = TacticalBackend()
    response = TestClient(create_app(backend=backend)).get("/api/tactical/events/tactical-1")

    assert response.status_code == 400
    assert "must be Level D" in response.json()["detail"]
    assert backend.window_calls == 0
