import json
import math

import pyarrow as pa
import pytest

from dynamis.processors.tactical_influence import (
    arrival_time_seconds,
    process_tactical_influence,
)


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
        "vx_m_s": None,
        "vy_m_s": None,
    }
    return pa.Table.from_pylist([{**base, **row} for row in rows])


def test_zero_velocity_arrival_is_bounded_and_monotonic() -> None:
    near = arrival_time_seconds(
        (0, 0),
        (0, 0),
        (1, 0),
        reaction_time_s=0.25,
        max_speed_m_s=7,
        max_acceleration_m_s2=3,
    )
    far = arrival_time_seconds(
        (0, 0),
        (0, 0),
        (10, 0),
        reaction_time_s=0.25,
        max_speed_m_s=7,
        max_acceleration_m_s2=3,
    )
    delayed = arrival_time_seconds(
        (0, 0),
        (0, 0),
        (1, 0),
        reaction_time_s=0.5,
        max_speed_m_s=7,
        max_acceleration_m_s2=3,
    )
    assert near >= 0.25
    assert far > near
    assert delayed > near


def test_directional_velocity_favors_forward_target() -> None:
    forward = arrival_time_seconds(
        (0, 0),
        (2, 0),
        (10, 0),
        reaction_time_s=0.25,
        max_speed_m_s=7,
        max_acceleration_m_s2=3,
    )
    backward = arrival_time_seconds(
        (0, 0),
        (-2, 0),
        (10, 0),
        reaction_time_s=0.25,
        max_speed_m_s=7,
        max_acceleration_m_s2=3,
    )
    assert forward < backward


def test_influence_is_bounded_and_discloses_model_class() -> None:
    table = tracking_table(
        [
            {"object_id": "h", "x_m": -2.0, "y_m": 0.0, "group_id": "home"},
            {"object_id": "a", "x_m": 2.0, "y_m": 0.0, "group_id": "away"},
        ]
    )
    result = process_tactical_influence(
        table,
        parameters={
            "pitch_length_m": 10,
            "pitch_width_m": 10,
            "grid_x": 5,
            "grid_y": 5,
            "grid_interval_ns": 1,
        },
    )
    teams = result.series[0].table.to_pylist()
    players = result.series[1].table.to_pylist()
    assert sum(row["influence_percentage"] for row in teams) == pytest.approx(100)
    assert all(0 <= row["influence_percentage"] <= 100 for row in teams)
    assert all(row["influence_area_m2"] <= 100 for row in players)
    assert all(row["measurement_class"] == "MODEL_ESTIMATED" for row in players)
    assert all(
        json.loads(row["quality_json"])["pressure_on_ball"]
        == "unavailable_without_source_resolved_ball_carrier"
        for row in players
    )
    assert math.isfinite(result.series[2].table.to_pylist()[0]["arrival_time_s"])


def test_influence_rejects_zero_maximum_speed() -> None:
    with pytest.raises(ValueError, match="max_speed_m_s must be positive"):
        process_tactical_influence(
            tracking_table([{"object_id": "p", "x_m": 0.0, "y_m": 0.0}]),
            parameters={"max_speed_m_s": 0},
        )
