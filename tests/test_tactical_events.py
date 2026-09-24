import json

import pyarrow as pa
import pytest

from dynamis.processors.tactical_events import process_tactical_event_snapshots


def tables(offset_ns: int = 0) -> tuple[pa.Table, pa.Table]:
    events = pa.Table.from_pylist(
        [
            {
                "dataset_id": "dfl",
                "session_id": "match",
                "trial_id": "period-1",
                "stream_id": "events",
                "t_rel_ns": 1_000_000_000,
                "measurement_class": "SOURCE_DERIVED",
                "coordinate_frame_id": "pitch",
                "event_id": "e1",
                "event_type": "play",
                "event_subtype": "pass",
                "provider_team_id": "home",
                "provider_player_id": "p1",
                "x_m": 1.0,
                "y_m": 2.0,
                "provider_context_json": '{"Evaluation":"successfullyCompleted"}',
            }
        ]
    )
    tracking = pa.Table.from_pylist(
        [
            {
                "t_rel_ns": 1_000_000_000 + offset_ns,
                "object_id": "p1",
                "object_type": "player",
                "group_id": "home",
                "x_m": 1.0,
                "y_m": 2.0,
            },
            {
                "t_rel_ns": 1_000_000_000 + offset_ns,
                "object_id": "ball",
                "object_type": "ball",
                "group_id": None,
                "x_m": 1.5,
                "y_m": 2.0,
            },
        ]
    )
    return events, tracking


def test_exact_event_tracking_join_preserves_source_semantics() -> None:
    events, tracking = tables()
    result = process_tactical_event_snapshots(events, tracking)
    row = result.series[0].table.to_pylist()[0]
    quality = json.loads(row["quality_json"])
    assert row["event_id"] == "e1"
    assert row["event_type"] == "play"
    assert row["tracking_t_rel_ns"] == 1_000_000_000
    assert row["event_ball_distance_m"] == 0.5
    assert quality["source_event_preserved"] is True
    assert quality["derived_event_label"] is None


def test_within_tolerance_join_and_out_of_tolerance_fail_closed() -> None:
    events, tracking = tables(offset_ns=20_000_000)
    joined = process_tactical_event_snapshots(events, tracking)
    joined_row = joined.series[0].table.to_pylist()[0]
    assert json.loads(joined_row["quality_json"])["synchronized_tracking"] is True

    events, tracking = tables(offset_ns=100_000_000)
    unsynchronized = process_tactical_event_snapshots(events, tracking)
    row = unsynchronized.series[0].table.to_pylist()[0]
    quality = json.loads(row["quality_json"])
    assert quality["synchronized_tracking"] is False
    assert row["tracking_t_rel_ns"] is None
    assert row["event_type"] == "play"


def test_unsynchronized_events_can_be_excluded_explicitly() -> None:
    events, tracking = tables(offset_ns=100_000_000)
    with pytest.raises(ValueError, match="no events remain"):
        process_tactical_event_snapshots(
            events, tracking, parameters={"include_unsynchronized": False}
        )
