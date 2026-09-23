import json
import math

import pyarrow as pa
import pytest

from dynamis.processors.tactical_shape import _delaunay, _Player, process_tactical_shape


def _rows(timestamps: list[int]) -> pa.Table:
    home = {
        "home-gk": ("goalkeeper", "home", 20.0, 0.0),
        "home-def-1": ("player", "home", 10.0, -2.0),
        "home-def-2": ("player", "home", 10.0, 4.0),
        "home-mid-1": ("player", "home", 2.0, -3.0),
        "home-mid-2": ("player", "home", 2.0, 3.0),
        "home-att-1": ("player", "home", -8.0, -3.0),
        "home-att-2": ("player", "home", -8.0, 3.0),
        "home-att-3": ("player", "home", -8.0, 22.0),
    }
    away = {
        "away-gk": ("goalkeeper", "away", -20.0, 0.0),
        "away-def-1": ("player", "away", -5.0, -3.0),
        "away-def-2": ("player", "away", -5.0, 3.0),
        "away-mid-1": ("player", "away", 4.0, -3.0),
        "away-mid-2": ("player", "away", 4.0, 3.0),
        "away-att-1": ("player", "away", 15.0, -3.0),
        "away-att-2": ("player", "away", 15.0, 3.0),
    }
    entities = {**home, **away}
    rows = []
    for timestamp in timestamps:
        for entity_id, (object_type, group_id, x, y) in entities.items():
            rows.append(
                {
                    "dataset_id": "synthetic-match",
                    "session_id": "match-1",
                    "trial_id": "period-1",
                    "stream_id": "tracking-period-1",
                    "t_rel_ns": timestamp,
                    "measurement_class": "RAW_MEASURED",
                    "coordinate_frame_id": "pitch-source",
                    "object_id": entity_id,
                    "object_type": object_type,
                    "group_id": group_id,
                    "x_m": x,
                    "y_m": y,
                    "is_detected": True,
                }
            )
        rows.append(
            {
                "dataset_id": "synthetic-match",
                "session_id": "match-1",
                "trial_id": "period-1",
                "stream_id": "tracking-period-1",
                "t_rel_ns": timestamp,
                "measurement_class": "RAW_MEASURED",
                "coordinate_frame_id": "pitch-source",
                "object_id": "ball",
                "object_type": "ball",
                "group_id": None,
                "x_m": 0.0,
                "y_m": 0.0,
                "is_detected": True,
            }
        )
    return pa.Table.from_pylist(rows)


def _roles() -> dict[str, str]:
    return {
        **{"home-gk": "GK"},
        **{f"home-def-{i}": "DEF" for i in (1, 2)},
        **{f"home-mid-{i}": "MID" for i in (1, 2)},
        **{f"home-att-{i}": "ATT" for i in (1, 2, 3)},
        **{"away-gk": "GK"},
        **{f"away-def-{i}": "DEF" for i in (1, 2)},
        **{f"away-mid-{i}": "MID" for i in (1, 2)},
        **{f"away-att-{i}": "ATT" for i in (1, 2)},
    }


def _possession(timestamps: list[int]) -> pa.Table:
    return pa.Table.from_pylist(
        [
            {
                "trial_id": "period-1",
                "t_rel_ns": timestamp,
                "team_id": "home",
                "player_id": "home-att-1",
                "ball_status": "active",
                "measurement_class": "SOURCE_DERIVED",
            }
            for timestamp in timestamps
        ]
    )


def _small_triangle() -> pa.Table:
    coordinates = {
        "a": ("home", 0.0, 0.0),
        "b": ("home", 3.0, 0.0),
        "c": ("home", 0.0, 4.0),
        "opponent": ("away", 1.0, 1.0),
        "ball": (None, 1.0, 1.0),
    }
    return pa.Table.from_pylist(
        [
            {
                "dataset_id": "synthetic-match",
                "session_id": "match-1",
                "trial_id": "period-1",
                "stream_id": "tracking-period-1",
                "t_rel_ns": 0,
                "measurement_class": "RAW_MEASURED",
                "coordinate_frame_id": "pitch-source",
                "object_id": entity,
                "object_type": "ball" if entity == "ball" else "player",
                "group_id": group_id,
                "x_m": x,
                "y_m": y,
                "is_detected": True,
            }
            for entity, (group_id, x, y) in coordinates.items()
        ]
    )


def _result(timestamps: list[int]):
    return process_tactical_shape(
        _rows(timestamps),
        role_by_player=_roles(),
        attacking_direction_by_team={
            "home": "right_to_left",
            "away": "left_to_right",
        },
        possession=_possession(timestamps),
        role_authority="synthetic-roster-v1",
        direction_authority="synthetic-period-side-v1",
        parameters={
            "pitch_length_m": 100.0,
            "pitch_width_m": 60.0,
            "stable_window_ns": 1_000_000_000,
            "stable_minimum_coverage_ns": 800_000_000,
            "persistence_max_gap_ns": 200_000_000,
        },
    )


def _series_rows(result, name: str) -> list[dict]:
    series = next(item for item in result.series if item.name == name)
    return series.table.to_pylist()


def test_functional_unit_geometry_and_attack_normalization() -> None:
    timestamps = list(range(0, 1_000_000_001, 100_000_000))
    result = _result(timestamps)
    rows = _series_rows(result, "functional_unit_geometry")
    home = {
        row["functional_unit"]: row
        for row in rows
        if row["group_id"] == "home" and row["t_rel_ns"] == timestamps[0]
    }
    assert home["GK"]["centroid_x_m"] == -20.0
    assert home["GK"]["depth_x_m"] == 0.0
    assert home["GK"]["width_y_m"] == 0.0
    assert home["GK"]["orientation_deg"] is None
    assert home["DEF"]["centroid_x_m"] == -10.0
    assert home["DEF"]["centroid_y_m"] == -1.0
    assert home["DEF"]["dispersion_rms_m"] == 3.0
    assert home["DEF"]["orientation_deg"] == 90.0
    assert home["DEF"]["def_mid_gap_m"] == 8.0
    assert home["DEF"]["mid_att_gap_m"] == 10.0
    assert home["DEF"]["outfield_block_depth_m"] == 18.0
    assert home["ATT"]["coordinate_normalization"] == "team_attack_positive_x"
    quality = json.loads(home["DEF"]["quality_json"])
    assert quality["role_counts"] == {"ATT": 3, "DEF": 2, "GK": 1, "MID": 2}
    assert quality["attacking_direction_available"]
    assert quality["extrapolated_rows"] == 0
    series = next(item for item in result.series if item.name == "functional_unit_geometry")
    metadata = series.table.schema.metadata or {}
    assert metadata[b"dynamis.algorithm_id"] == b"tactical.matchlab_shape"
    assert metadata[b"dynamis.algorithm_version"] == b"1"
    assert b"stable_window_ns" in metadata[b"dynamis.parameters"]


def test_stable_graph_triangles_interactions_and_source_context() -> None:
    timestamps = list(range(0, 1_000_000_001, 100_000_000))
    result = _result(timestamps)
    edges = _series_rows(result, "shape_graph_edges")
    final_edges = [
        row for row in edges if row["group_id"] == "home" and row["t_rel_ns"] == timestamps[-1]
    ]
    assert final_edges
    assert all(row["edge_persistence_fraction"] == 1.0 for row in final_edges)
    assert all(row["stable_edge"] for row in final_edges)

    triangles = _series_rows(result, "tactical_triangles")
    assert triangles
    assert all(row["area_m2"] > 0 for row in triangles)
    assert all(0 <= row["triangle_persistence_fraction"] <= 1 for row in triangles)
    assert all(row["ball_distance_m"] is not None for row in triangles)
    last_triangles = [row for row in triangles if row["t_rel_ns"] == timestamps[-1]]
    assert last_triangles and all(row["stable_triangle"] for row in last_triangles)

    interactions = _series_rows(result, "attacker_defender_interactions")
    focal = next(
        row for row in interactions if row["attacker_id"] == "home-att-1" and row["t_rel_ns"] == 0
    )
    assert focal["nearest_defender_id"] == "away-def-1"
    assert focal["nearest_defender_distance_m"] == 3.0
    assert focal["second_nearest_defender_id"] == "away-def-2"
    assert focal["local_attacker_count"] == 2
    assert focal["local_defender_count"] == 2
    assert focal["local_overload_margin_players"] == 0
    assert focal["geometric_tie_up"] is True
    free = next(
        row for row in interactions if row["attacker_id"] == "home-att-3" and row["t_rel_ns"] == 0
    )
    assert free["geometric_free_attacker"] is True

    possession = _series_rows(result, "source_possession_context")
    assert len(possession) == len(timestamps)
    assert all(row["measurement_class"] == "SOURCE_DERIVED" for row in possession)
    assert all(row["source_possession_team_id"] == "home" for row in possession)
    possession_series = next(
        item for item in result.series if item.name == "source_possession_context"
    )
    assert (possession_series.table.schema.metadata or {})[
        b"dynamis.measurement_class"
    ] == b"SOURCE_DERIVED"


def test_direction_missing_fails_closed_to_frame_axis() -> None:
    table = _rows([0])
    result = process_tactical_shape(table, role_by_player=_roles())
    rows = _series_rows(result, "functional_unit_geometry")
    home_gk = next(
        row for row in rows if row["group_id"] == "home" and row["functional_unit"] == "GK"
    )
    assert home_gk["centroid_x_m"] == 20.0
    assert home_gk["coordinate_normalization"] == "source_frame"
    assert home_gk["attacking_direction"] is None
    assert "source_possession_context" not in {item.name for item in result.series}


def test_source_role_absence_stays_unknown() -> None:
    result = process_tactical_shape(_rows([0]), role_by_player={})
    rows = _series_rows(result, "functional_unit_geometry")
    assert {row["functional_unit"] for row in rows} == {"unknown"}
    assert not any(item.name == "attacker_defender_interactions" for item in result.series)


def test_triangle_known_answers_and_geometric_control_context() -> None:
    result = process_tactical_shape(
        _small_triangle(),
        role_by_player={},
        parameters={"pitch_length_m": 10.0, "pitch_width_m": 10.0},
    )
    triangle = _series_rows(result, "tactical_triangles")[0]
    assert triangle["area_m2"] == 6.0
    assert triangle["aspect_ratio"] == pytest.approx(5 / 3)
    assert triangle["orientation_deg"] == pytest.approx(
        0.5 * math.degrees(math.atan2(-8 / 3, -14 / 9)) % 180
    )
    assert triangle["ball_distance_m"] == pytest.approx(1 / 3)
    assert triangle["zone"] == "center_third"
    assert triangle["zone_frame"] == "source_frame"
    assert triangle["opponent_count_inside"] == 1
    assert triangle["nearest_team_at_centroid"] == "away"
    assert triangle["nearest_team_distance_margin_m"] == pytest.approx(-4 / 3)


def test_delaunay_duplicate_and_collinear_degeneracy() -> None:
    def player(entity_id: str, x: float, y: float) -> _Player:
        return _Player(entity_id, "home", x, y, "DEF", True)

    square = (
        player("a", -1, -1),
        player("b", -1, 1),
        player("c", 1, 1),
        player("d", 1, -1),
    )
    first = _delaunay(square, direction=None)
    assert first == _delaunay(tuple(reversed(square)), direction=None)
    assert len(first[0]) == 5
    assert len(first[1]) == 2
    coincident = (*square, player("z", -1, -1))
    edges, triangles = _delaunay(coincident, direction=None)
    assert edges == first[0]
    assert triangles == first[1]
    line = (player("a", 0, 0), player("b", 1, 0), player("c", 2, 0))
    assert _delaunay(line, direction=None) == (set(), set())


def test_persistence_restarts_after_tracking_gap() -> None:
    timestamps = [
        0,
        100_000_000,
        200_000_000,
        300_000_000,
        400_000_000,
        1_000_000_000,
        1_100_000_000,
        1_200_000_000,
        1_300_000_000,
        1_400_000_000,
    ]
    result = _result(timestamps)
    edges = _series_rows(result, "shape_graph_edges")
    final_edges = [
        row for row in edges if row["group_id"] == "home" and row["t_rel_ns"] == timestamps[-1]
    ]
    assert final_edges
    assert all(not row["stable_edge"] for row in final_edges)
