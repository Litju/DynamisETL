import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_tactical_authority_files_are_consistent() -> None:
    metrics = json.loads((ROOT / "architecture" / "tactical-metrics.json").read_text())
    capabilities = json.loads((ROOT / "sources" / "tactical-capability-matrix.json").read_text())

    assert metrics["schema_version"] == "1"
    assert metrics["level_c_model"]["algorithm_id"] == "tactical.arrival_time"
    assert metrics["level_c_model"]["parameters"]["grid_interval_ns"] == 1_000_000_000
    assert {item["level"] for item in metrics["metrics"]} == {
        "A",
        "B",
        "C",
        "D",
        "E",
        "V3",
    }
    assert metrics["matchlab_tactical_v3"]["algorithm_id"] == "tactical.matchlab_shape"
    assert metrics["matchlab_tactical_v3"]["role_domains"] == ["GK", "DEF", "MID", "ATT", "unknown"]
    assert all(item["id"].startswith("tactical.") for item in metrics["metrics"])
    assert all(len(item["id"]) > 9 and item["unit"] for item in metrics["metrics"])

    assert set(capabilities["datasets"]) == {
        "dfl-sportec-idsse",
        "skillcorner-opendata",
        "womens-soccer-positioning",
    }
    for dataset in capabilities["datasets"].values():
        assert {
            "matchlab_v3_functional_units",
            "matchlab_v3_shape_graph",
            "matchlab_v3_triangles",
            "matchlab_v3_interactions",
            "possession_context",
        } <= dataset["capabilities"].keys()
    assert (
        capabilities["datasets"]["dfl-sportec-idsse"]["capabilities"]["level_d_event_linked"]
        == "supported_source_snapshots_only"
    )
    assert (
        capabilities["datasets"]["skillcorner-opendata"]["capabilities"]["level_d_event_linked"]
        == "unavailable"
    )
    assert (
        capabilities["datasets"]["womens-soccer-positioning"]["capabilities"]["level_a_geometry"]
        == "unavailable_for_pitch_team_geometry"
    )
