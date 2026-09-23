import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_tactical_authority_files_are_consistent() -> None:
    metrics = json.loads((ROOT / "architecture" / "tactical-metrics.json").read_text())
    capabilities = json.loads(
        (ROOT / "sources" / "tactical-capability-matrix.json").read_text()
    )

    assert metrics["schema_version"] == "1"
    assert metrics["level_c_model"]["algorithm_id"] == "tactical.arrival_time"
    assert metrics["level_c_model"]["parameters"]["grid_interval_ns"] == 1_000_000_000
    assert {item["level"] for item in metrics["metrics"]} == {"A", "B", "C", "D", "E"}
    assert all(item["id"].startswith("tactical.") for item in metrics["metrics"])
    assert all(len(item["id"]) > 9 and item["unit"] for item in metrics["metrics"])

    assert set(capabilities["datasets"]) == {
        "dfl-sportec-idsse",
        "skillcorner-opendata",
        "womens-soccer-positioning",
    }
    assert capabilities["datasets"]["dfl-sportec-idsse"]["capabilities"][
        "level_d_event_linked"
    ] == "supported_source_snapshots_only"
    assert capabilities["datasets"]["skillcorner-opendata"]["capabilities"][
        "level_d_event_linked"
    ] == "unavailable"
    assert capabilities["datasets"]["womens-soccer-positioning"]["capabilities"][
        "level_a_geometry"
    ] == "unavailable_for_pitch_team_geometry"
