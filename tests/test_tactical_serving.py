from fastapi.testclient import TestClient

from dynamis.serving import tactical as authority
from dynamis.serving.app import create_app


class TacticalBackend:
    def tactical_capability(self, dataset_id: str):
        return authority.tactical_capability(dataset_id)

    def tactical_methodology(self):
        return authority.tactical_methodology()

    def tactical_quality(self, dataset_id: str):
        return authority.tactical_quality(dataset_id)

    def tactical_artifacts(self, dataset_id, session_id=None, stream_id=None, series_name=None):
        return []


def test_tactical_authority_routes_are_typed_and_fail_closed() -> None:
    client = TestClient(create_app(backend=TacticalBackend()))

    capabilities = client.get("/api/tactical/capabilities/dfl-sportec-idsse")
    assert capabilities.status_code == 200
    assert capabilities.json()["capabilities"]["level_d_event_linked"] == (
        "supported_source_snapshots_only"
    )

    quality = client.get("/api/tactical/quality/womens-soccer-positioning")
    assert quality.status_code == 200
    assert quality.json()["capabilities"]["level_b_territory"] == "unavailable"

    methodology = client.get("/api/tactical/methodology")
    assert methodology.status_code == 200
    assert any(
        item["metric_id"] == "tactical.team.centroid_x" for item in methodology.json()["metrics"]
    )

    assert client.get("/api/tactical/capabilities/not-a-dataset").status_code == 404


def test_tactical_paths_are_in_openapi() -> None:
    paths = create_app(backend=TacticalBackend()).openapi()["paths"]
    assert "/api/tactical/capabilities/{dataset_id}" in paths
    assert "/api/tactical/series/{artifact_id}" in paths
    assert "/api/tactical/events/{artifact_id}" in paths
