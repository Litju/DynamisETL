import json

import pyarrow as pa
import pytest

from dynamis.processors.tactical_geometry import convex_hull
from dynamis.processors.tactical_territory import process_tactical_territory


def tracking_table(rows: list[dict]) -> pa.Table:
    base = {
        "dataset_id": "synthetic",
        "session_id": "session",
        "trial_id": "period-1",
        "stream_id": "tracking",
        "t_rel_ns": 0,
        "measurement_class": "RAW_MEASURED",
        "coordinate_frame_id": "pitch",
        "object_type": "player",
        "group_id": "home",
        "is_detected": True,
    }
    return pa.Table.from_pylist([{**base, **row} for row in rows])


def test_four_corner_voronoi_cells_fill_pitch() -> None:
    table = tracking_table(
        [
            {"object_id": "a", "x_m": -5.0, "y_m": -5.0},
            {"object_id": "b", "x_m": -5.0, "y_m": 5.0},
            {"object_id": "c", "x_m": 5.0, "y_m": 5.0},
            {"object_id": "d", "x_m": 5.0, "y_m": -5.0},
        ]
    )
    result = process_tactical_territory(
        table, parameters={"pitch_length_m": 10, "pitch_width_m": 10}
    )
    players = result.series[0].table.to_pylist()
    team = result.series[1].table.to_pylist()[0]
    assert [row["cell_area_m2"] for row in players] == pytest.approx([25] * 4)
    assert team["controlled_area_m2"] == pytest.approx(100)
    assert team["control_percentage"] == pytest.approx(100)


def test_two_teams_split_pitch_without_possession_claim() -> None:
    table = tracking_table(
        [
            {"object_id": "h", "x_m": -2.0, "y_m": 0.0, "group_id": "home"},
            {"object_id": "a", "x_m": 2.0, "y_m": 0.0, "group_id": "away"},
        ]
    )
    result = process_tactical_territory(
        table, parameters={"pitch_length_m": 10, "pitch_width_m": 10}
    )
    teams = result.series[1].table.to_pylist()
    assert [row["control_percentage"] for row in teams] == pytest.approx([50, 50])
    assert all(
        json.loads(row["quality_json"])["territory_semantics"]
        == "geometric_control_not_possession_probability"
        for row in teams
    )


def test_collocated_points_have_stable_owner_and_zero_duplicate_cell() -> None:
    table = tracking_table(
        [
            {"object_id": "b", "x_m": 0.0, "y_m": 0.0},
            {"object_id": "a", "x_m": 0.0, "y_m": 0.0},
        ]
    )
    result = process_tactical_territory(
        table, parameters={"pitch_length_m": 10, "pitch_width_m": 10}
    )
    rows = {row["entity_id"]: row for row in result.series[0].table.to_pylist()}
    assert rows["a"]["cell_area_m2"] == pytest.approx(100)
    assert rows["b"]["cell_area_m2"] == 0
    assert json.loads(rows["b"]["quality_json"])["coincident_point_count"] == 1


def test_outside_pitch_coordinates_are_flagged_and_bounded() -> None:
    table = tracking_table([{"object_id": "a", "x_m": 20.0, "y_m": 20.0}])
    result = process_tactical_territory(
        table, parameters={"pitch_length_m": 10, "pitch_width_m": 10}
    )
    row = result.series[0].table.to_pylist()[0]
    quality = json.loads(row["quality_json"])
    assert row["cell_area_m2"] == pytest.approx(100)
    assert quality["outside_pitch_rows"] == 1
    assert len(convex_hull(((-5, -5), (5, -5), (5, 5)))) == 3
