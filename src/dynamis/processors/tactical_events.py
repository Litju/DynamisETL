"""Level D source-event/tracking joins with fail-closed semantics."""

from __future__ import annotations

import bisect
import json
import math
from collections import defaultdict
from typing import Any

import pyarrow as pa

from dynamis.processors.spec import ProcessorResult, ProcessorSpec, SeriesOutput

ALGORITHM_ID = "tactical.source_event_snapshot"
ALGORITHM_VERSION = "1"
DEFAULT_PARAMETERS = {
    "max_sync_delta_ns": 40_000_000,
    "include_unsynchronized": True,
    "event_semantics": "preserve_source_event_identity_and_context",
    "derived_event_labels": False,
}
REQUIRED_EVENT_COLUMNS = {
    "dataset_id",
    "session_id",
    "stream_id",
    "t_rel_ns",
    "measurement_class",
    "event_id",
    "event_type",
    "event_subtype",
    "provider_team_id",
    "provider_player_id",
    "x_m",
    "y_m",
    "provider_context_json",
}
REQUIRED_TRACKING_COLUMNS = {
    "t_rel_ns",
    "object_id",
    "object_type",
    "group_id",
    "x_m",
    "y_m",
}


def _finite(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _tracking_frames(table: pa.Table) -> tuple[list[int], dict[int, list[dict[str, Any]]]]:
    missing = REQUIRED_TRACKING_COLUMNS - set(table.column_names)
    if missing:
        raise ValueError(f"{ALGORITHM_ID}: tracking table missing {sorted(missing)}")
    by_time: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in table.to_pylist():
        by_time[int(row["t_rel_ns"])].append(row)
    return sorted(by_time), by_time


def _nearest_tracking(
    timestamp: int, times: list[int], by_time: dict[int, list[dict[str, Any]]]
) -> tuple[int | None, list[dict[str, Any]]]:
    if not times:
        return None, []
    index = bisect.bisect_left(times, timestamp)
    candidates = []
    if index < len(times):
        candidates.append(times[index])
    if index:
        candidates.append(times[index - 1])
    chosen = min(candidates, key=lambda candidate: (abs(candidate - timestamp), candidate))
    return chosen, by_time[chosen]


def _series_table(rows: list[dict[str, Any]], parameters: dict[str, Any]) -> pa.Table:
    if not rows:
        raise ValueError(f"{ALGORITHM_ID}: no canonical source event rows")
    table = pa.Table.from_pylist(rows)
    metadata = dict(table.schema.metadata or {})
    metadata.update(
        {
            b"dynamis.contract": b"tactical_event_snapshot",
            b"dynamis.measurement_class": b"PIPELINE_DERIVED",
            b"dynamis.source_measurement_class": b"SOURCE_DERIVED",
            b"dynamis.method": b"nearest_shared-clock_tracking_snapshot",
            b"dynamis.algorithm_id": ALGORITHM_ID.encode(),
            b"dynamis.algorithm_version": ALGORITHM_VERSION.encode(),
            b"dynamis.parameters": json.dumps(
                parameters, sort_keys=True, separators=(",", ":")
            ).encode(),
        }
    )
    return table.replace_schema_metadata(metadata)


def process_tactical_event_snapshots(
    events: pa.Table,
    tracking: pa.Table,
    *,
    parameters: dict[str, Any] | None = None,
) -> ProcessorResult:
    """Join source events to nearest tracking frames without relabelling events."""
    resolved = dict(DEFAULT_PARAMETERS)
    if parameters:
        resolved.update(parameters)
    if int(resolved["max_sync_delta_ns"]) < 0:
        raise ValueError(f"{ALGORITHM_ID}: max_sync_delta_ns must be non-negative")
    missing = REQUIRED_EVENT_COLUMNS - set(events.column_names)
    if missing:
        raise ValueError(f"{ALGORITHM_ID}: event table missing {sorted(missing)}")
    event_classes = set(events.column("measurement_class").to_pylist())
    if event_classes != {"SOURCE_DERIVED"}:
        raise ValueError(
            f"{ALGORITHM_ID}: source event snapshots require SOURCE_DERIVED event rows; "
            f"found {sorted(str(value) for value in event_classes)}"
        )
    times, by_time = _tracking_frames(tracking)
    first = events.slice(0, 1).to_pylist()[0]
    rows: list[dict[str, Any]] = []
    matched = 0
    for event in sorted(
        events.to_pylist(), key=lambda row: (int(row["t_rel_ns"]), str(row["event_id"]))
    ):
        event_time = int(event["t_rel_ns"])
        tracking_time, frame_rows = _nearest_tracking(event_time, times, by_time)
        delta = None if tracking_time is None else abs(tracking_time - event_time)
        synchronized = delta is not None and delta <= int(resolved["max_sync_delta_ns"])
        if synchronized:
            matched += 1
        player_rows = [
            row for row in frame_rows if str(row.get("object_type")) in {"player", "goalkeeper"}
        ]
        ball = next((row for row in frame_rows if str(row.get("object_type")) == "ball"), None)
        event_x = float(event["x_m"]) if _finite(event.get("x_m")) else None
        event_y = float(event["y_m"]) if _finite(event.get("y_m")) else None
        ball_x = float(ball["x_m"]) if ball and _finite(ball.get("x_m")) else None
        ball_y = float(ball["y_m"]) if ball and _finite(ball.get("y_m")) else None
        event_ball_distance = (
            math.hypot(event_x - ball_x, event_y - ball_y)
            if event_x is not None
            and event_y is not None
            and ball_x is not None
            and ball_y is not None
            else None
        )
        quality = {
            "source_event_preserved": True,
            "source_event_measurement_class": "SOURCE_DERIVED",
            "synchronized_tracking": synchronized,
            "sync_delta_ns": delta,
            "max_sync_delta_ns": int(resolved["max_sync_delta_ns"]),
            "derived_event_label": None,
            "possession_inferred": False,
            "pressure_inferred": False,
            "attacking_direction_required_outputs": "not emitted",
        }
        row = {
            "dataset_id": str(first["dataset_id"]),
            "session_id": str(first["session_id"]),
            "trial_id": event.get("trial_id"),
            "stream_id": str(first["stream_id"]),
            "t_rel_ns": event_time,
            "measurement_class": "PIPELINE_DERIVED",
            "source_event_measurement_class": "SOURCE_DERIVED",
            "coordinate_frame_id": event.get("coordinate_frame_id"),
            "event_id": str(event["event_id"]),
            "event_type": str(event["event_type"]),
            "event_subtype": event.get("event_subtype"),
            "provider_team_id": event.get("provider_team_id"),
            "provider_player_id": event.get("provider_player_id"),
            "event_x_m": event_x,
            "event_y_m": event_y,
            "provider_context_json": event.get("provider_context_json"),
            "tracking_t_rel_ns": tracking_time if synchronized else None,
            "tracking_entity_count": len(frame_rows) if synchronized else 0,
            "tracking_player_count": len(player_rows) if synchronized else 0,
            "tracking_team_count": len(
                {row.get("group_id") for row in player_rows if row.get("group_id")}
            )
            if synchronized
            else 0,
            "ball_x_m": ball_x if synchronized else None,
            "ball_y_m": ball_y if synchronized else None,
            "event_ball_distance_m": event_ball_distance if synchronized else None,
            "quality_json": json.dumps(quality, sort_keys=True, separators=(",", ":")),
        }
        rows.append(row)
    if not resolved["include_unsynchronized"]:
        rows = [row for row in rows if json.loads(row["quality_json"])["synchronized_tracking"]]
    if not rows:
        raise ValueError(f"{ALGORITHM_ID}: no events remain after synchronization policy")
    spec = ProcessorSpec(
        algorithm_id=ALGORITHM_ID,
        name="Source event and synchronized tracking snapshot",
        version=ALGORITHM_VERSION,
        description=(
            "Preserves source event identity/context and joins the nearest shared-clock "
            "tracking frame; no new tactical event class is inferred."
        ),
        parameters=resolved,
    )
    return ProcessorResult(
        spec=spec,
        series=(
            SeriesOutput(
                name="source_event_snapshots",
                table=_series_table(rows, resolved),
            ),
        ),
        diagnostics={
            "level": "D",
            "source_events": len(events),
            "emitted_events": len(rows),
            "synchronized_events": matched,
            "unsynchronized_events": len(events) - matched,
            "source_event_semantics": "preserved",
            "derived_event_labels": False,
            "possession_inferred": False,
            "pressure_inferred": False,
            "input_measurement_classes": {
                "events": "SOURCE_DERIVED",
                "tracking": "canonical_tracking_input",
            },
        },
    )


__all__ = ["ALGORITHM_ID", "process_tactical_event_snapshots"]
