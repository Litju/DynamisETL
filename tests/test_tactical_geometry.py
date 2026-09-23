import math

import pyarrow as pa
import pytest

from dynamis.processors.tactical_geometry import (
    convex_hull,
    convex_polygon_intersection_area,
    polygon_area,
    process_tactical_geometry,
)


def tracking_table(rows: list[dict]) -> pa.Table:
    base = {
        "dataset_id": "synthetic-dfl",
        "session_id": "match",
        "trial_id": "period-1",
        "stream_id": "tracking-period-1",
        "t_rel_ns": 0,
        "measurement_class": "RAW_MEASURED",
        "coordinate_frame_id": "pitch",
        "object_id": "p",
        "object_type": "player",
        "group_id": "home",
        "x_m": 0.0,
        "y_m": 0.0,
        "is_detected": True,
    }
    return pa.Table.from_pylist([{**base, **row} for row in rows])


def test_symmetric_geometry_known_answer() -> None:
    table = tracking_table(
        [
            {"object_id": "h1", "x_m": -1.0, "y_m": -1.0},
            {"object_id": "h2", "x_m": -1.0, "y_m": 1.0},
            {"object_id": "h3", "x_m": 1.0, "y_m": 1.0},
            {"object_id": "h4", "x_m": 1.0, "y_m": -1.0},
        ]
    )
    result = process_tactical_geometry(
        table, parameters={"pitch_length_m": 10, "pitch_width_m": 10}
    )
    row = result.series[0].table.to_pylist()[0]
    assert row["centroid_x_m"] == 0
    assert row["centroid_y_m"] == 0
    assert row["length_m"] == 2
    assert row["width_m"] == 2
    assert row["hull_area_m2"] == 4
    assert row["pairwise_distance_mean_m"] == pytest.approx((4 * 2 + 2 * math.sqrt(8)) / 6)
    assert row["stretch_index"] == pytest.approx(0.1)


def test_team_and_player_quality_fail_closed_for_missing_opponent() -> None:
    table = tracking_table(
        [
            {"object_id": "h1", "x_m": 0.0, "y_m": 0.0},
            {"object_id": "h2", "x_m": 1.0, "y_m": 0.0},
            {"object_id": "h2", "x_m": 1.0, "y_m": 0.0},
        ]
    )
    result = process_tactical_geometry(table)
    player_rows = result.series[1].table.to_pylist()
    assert all(row["nearest_opponent_distance_m"] is None for row in player_rows)
    assert all('"attacking_direction":"unavailable"' in row["quality_json"] for row in player_rows)


def test_side_swap_preserves_scalar_geometry() -> None:
    original = tracking_table(
        [
            {"object_id": "h1", "x_m": -1.0, "y_m": -1.0},
            {"object_id": "h2", "x_m": 1.0, "y_m": 1.0},
        ]
    )
    swapped = tracking_table(
        [
            {"object_id": "h1", "x_m": 1.0, "y_m": -1.0},
            {"object_id": "h2", "x_m": -1.0, "y_m": 1.0},
        ]
    )
    left = process_tactical_geometry(original).series[0].table.to_pylist()[0]
    right = process_tactical_geometry(swapped).series[0].table.to_pylist()[0]
    assert left["hull_area_m2"] == right["hull_area_m2"]
    assert left["pairwise_distance_mean_m"] == right["pairwise_distance_mean_m"]


def test_hull_and_convex_intersection_known_answer() -> None:
    hull = convex_hull(((-1, -1), (-1, 1), (1, 1), (1, -1)))
    assert polygon_area(hull) == 4
    other = convex_hull(((0, -1), (0, 1), (2, 1), (2, -1)))
    assert convex_polygon_intersection_area(hull, other) == 2
