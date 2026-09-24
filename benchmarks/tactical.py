"""Small deterministic tactical processor benchmark.

This benchmark uses CI-safe synthetic tracking/events with the same canonical
columns as the accepted tracking contracts. Real-data evidence is written only
to an external cache by ``--out``.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pyarrow as pa

from dynamis.processors.tactical_events import process_tactical_event_snapshots
from dynamis.processors.tactical_geometry import process_tactical_geometry
from dynamis.processors.tactical_influence import process_tactical_influence
from dynamis.processors.tactical_territory import process_tactical_territory


def _tracking(frame_count: int = 250) -> pa.Table:
    rows = []
    for frame in range(frame_count):
        t_rel_ns = frame * 40_000_000
        for index in range(22):
            group_id = "home" if index < 11 else "away"
            side_index = index if index < 11 else index - 11
            rows.append(
                {
                    "dataset_id": "synthetic-tactical",
                    "session_id": "benchmark",
                    "trial_id": "period-1",
                    "stream_id": "tracking-period-1",
                    "t_rel_ns": t_rel_ns,
                    "measurement_class": "RAW_MEASURED",
                    "coordinate_frame_id": "synthetic-pitch",
                    "object_id": f"{group_id}-{side_index:02d}",
                    "object_type": "player",
                    "group_id": group_id,
                    "x_m": (-30 if group_id == "home" else 30) + side_index * 1.2 + frame * 0.01,
                    "y_m": -25 + side_index * 5,
                    "vx_m_s": None,
                    "vy_m_s": None,
                    "is_detected": True,
                }
            )
        rows.append(
            {
                "dataset_id": "synthetic-tactical",
                "session_id": "benchmark",
                "trial_id": "period-1",
                "stream_id": "tracking-period-1",
                "t_rel_ns": t_rel_ns,
                "measurement_class": "RAW_MEASURED",
                "coordinate_frame_id": "synthetic-pitch",
                "object_id": "ball",
                "object_type": "ball",
                "group_id": None,
                "x_m": frame * 0.05,
                "y_m": 0.0,
                "vx_m_s": None,
                "vy_m_s": None,
                "is_detected": True,
            }
        )
    return pa.Table.from_pylist(rows)


def _events() -> pa.Table:
    return pa.Table.from_pylist(
        [
            {
                "dataset_id": "synthetic-tactical",
                "session_id": "benchmark",
                "trial_id": "period-1",
                "stream_id": "events",
                "t_rel_ns": index * 200_000_000,
                "measurement_class": "SOURCE_DERIVED",
                "coordinate_frame_id": "synthetic-pitch",
                "event_id": f"event-{index:03d}",
                "event_type": "play",
                "event_subtype": "pass",
                "provider_team_id": "home",
                "provider_player_id": "home-00",
                "x_m": 0.0,
                "y_m": 0.0,
                "provider_context_json": '{"Evaluation":"successfullyCompleted"}',
            }
            for index in range(50)
        ]
    )


def _measure(name, function, *args) -> dict[str, object]:
    timings = []
    result = None
    for _ in range(3):
        started = time.perf_counter()
        result = function(*args)
        timings.append((time.perf_counter() - started) * 1000)
    timings.sort()
    assert result is not None
    return {
        "name": name,
        "median_ms": timings[1],
        "p95_ms": timings[-1],
        "series_rows": {series.name: series.table.num_rows for series in result.series},
        "diagnostics": dict(result.diagnostics),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    tracking = _tracking()
    events = _events()
    results = [
        _measure("hull_centroid_geometry", process_tactical_geometry, tracking),
        _measure("clipped_voronoi_territory", process_tactical_territory, tracking),
        _measure("arrival_time_influence", process_tactical_influence, tracking),
        _measure("source_event_snapshot", process_tactical_event_snapshots, events, tracking),
    ]
    receipt = {
        "benchmark": "RES-110 tactical processors",
        "input": {"frames": 250, "players_per_team": 11, "events": 50, "raw_rows": False},
        "base_field": "browser renderer-smoke and e2e field acceptance",
        "results": results,
    }
    text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(args.out)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
