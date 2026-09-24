"""Bounded RES-110 real-data sanity receipts for the accepted DFL slice.

The script never commits source rows. It reads canonical Silver artifacts,
processes a deterministic first-window sample from every DFL period, reruns the
same inputs, and writes checksum/provenance receipts under the external cache.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq

from dynamis.config import settings
from dynamis.processors.runtime import collect_input, execute_processor, read_series_checksums
from dynamis.processors.tactical_events import process_tactical_event_snapshots
from dynamis.processors.tactical_geometry import process_tactical_geometry
from dynamis.processors.tactical_influence import process_tactical_influence
from dynamis.processors.tactical_territory import process_tactical_territory
from dynamis.storage.atomic import atomic_write_text
from dynamis.storage.paths import receipt_path

DATASET_ID = "dfl-sportec-idsse"
SESSION_ID = "DFL-MAT-J03WPY"
SAMPLE_FRAMES = 250
TRACKING_COLUMNS = [
    "dataset_id",
    "session_id",
    "trial_id",
    "stream_id",
    "t_rel_ns",
    "measurement_class",
    "coordinate_frame_id",
    "object_id",
    "object_type",
    "group_id",
    "x_m",
    "y_m",
    "vx_m_s",
    "vy_m_s",
    "is_detected",
]


def _paths(dataset_root: Path) -> tuple[list[Path], Path]:
    base = dataset_root / "silver" / "dataset_id=dfl-sportec-idsse"
    tracking = sorted((base / "modality=tracking" / f"session_id={SESSION_ID}").glob("*.parquet"))
    events = next((base / "modality=event" / f"session_id={SESSION_ID}").glob("*.parquet"), None)
    if len(tracking) < 2 or events is None:
        raise FileNotFoundError(
            "accepted DFL Silver tracking periods and event artifact are required"
        )
    return tracking, events


def _run(settings_value, table, source_path, processor, *, series_key, role, extra_inputs=()):
    source_input = collect_input(
        settings_value,
        source_path,
        role=role,
        row_count=table.num_rows,
    )
    result = processor(table)
    first = execute_processor(
        settings_value,
        result=result,
        dataset_id=DATASET_ID,
        inputs=(*extra_inputs, source_input),
        series_key=series_key,
        persist=False,
    )
    second = execute_processor(
        settings_value,
        result=result,
        dataset_id=DATASET_ID,
        inputs=(*extra_inputs, source_input),
        series_key=series_key,
        persist=False,
    )
    return {
        "algorithm_id": result.spec.algorithm_id,
        "algorithm_version": result.spec.version,
        "parameters_hash": result.spec.parameters_hash,
        "code_git_sha": first.code_git_sha,
        "run_id": first.run_id,
        "rerun_run_id": second.run_id,
        "rerun_run_id_stable": first.run_id == second.run_id,
        "input_checksum": source_input.checksum_sha256,
        "input_rows_in_sample": table.num_rows,
        "series_checksums": read_series_checksums(first),
        "rerun_series_checksums": read_series_checksums(second),
        "rerun_series_stable": read_series_checksums(first) == read_series_checksums(second),
        "diagnostics": dict(result.diagnostics),
        "receipt_paths": [first.receipt_path, second.receipt_path],
    }


def main() -> int:
    resolved = settings()
    tracking_paths, event_path = _paths(resolved.dataset_root)
    event_table = pq.read_table(event_path)
    event_input = collect_input(
        resolved,
        event_path,
        role="silver_event_source",
        row_count=event_table.num_rows,
    )
    periods: list[dict[str, object]] = []
    for tracking_path in tracking_paths:
        table = pq.read_table(tracking_path, columns=TRACKING_COLUMNS).slice(0, SAMPLE_FRAMES * 23)
        period_id = str(table.column("trial_id")[0].as_py())
        periods.append(
            {
                "stream": tracking_path.name,
                "period": period_id,
                "geometry": _run(
                    resolved,
                    table,
                    tracking_path,
                    process_tactical_geometry,
                    series_key=f"res110-{period_id}-geometry",
                    role="silver_tracking_sample",
                ),
                "territory": _run(
                    resolved,
                    table,
                    tracking_path,
                    process_tactical_territory,
                    series_key=f"res110-{period_id}-territory",
                    role="silver_tracking_sample",
                ),
                "influence": _run(
                    resolved,
                    table,
                    tracking_path,
                    process_tactical_influence,
                    series_key=f"res110-{period_id}-influence",
                    role="silver_tracking_sample",
                ),
            }
        )
        period_events = event_table.filter(pc.equal(event_table["trial_id"], period_id))
        if period_events.num_rows:
            event_result = process_tactical_event_snapshots(period_events, table)
            event_run = execute_processor(
                resolved,
                result=event_result,
                dataset_id=DATASET_ID,
                inputs=(
                    event_input,
                    collect_input(
                        resolved,
                        tracking_path,
                        role="silver_tracking_sample",
                        row_count=table.num_rows,
                    ),
                ),
                series_key=f"res110-{period_id}-events",
                persist=False,
            )
            periods[-1]["events"] = {
                "algorithm_id": event_result.spec.algorithm_id,
                "code_git_sha": event_run.code_git_sha,
                "input_checksum": event_input.checksum_sha256,
                "source_events": period_events.num_rows,
                "diagnostics": dict(event_result.diagnostics),
                "series_checksums": read_series_checksums(event_run),
                "receipt_path": event_run.receipt_path,
            }
    receipt = {
        "acceptance": "RES-110 real DFL bounded tactical sanity",
        "dataset_id": DATASET_ID,
        "session_id": SESSION_ID,
        "source_event_checksum": event_input.checksum_sha256,
        "sample_frames_per_period": SAMPLE_FRAMES,
        "raw_rows_committed": False,
        "periods": periods,
        "capability_boundary": (
            "A/B/C are exercised; D is source-event snapshot only; attack-normalized "
            "events, possession, pressure, formation and phase labels are not emitted."
        ),
    }
    target = receipt_path(
        resolved,
        dataset_id=DATASET_ID,
        kind="acceptance",
        name="res110-tactical-real-dfl",
    )
    atomic_write_text(target, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
