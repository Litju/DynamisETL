"""Bounded real-data RES-110 Tactical V3 receipts for accepted DFL and SkillCorner."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from dynamis.config import settings
from dynamis.processors.runtime import collect_input, execute_processor, read_series_checksums
from dynamis.processors.tactical_shape import process_tactical_shape
from dynamis.processors.tactical_sources import load_tactical_source_authority
from dynamis.storage.atomic import atomic_write_text
from dynamis.storage.paths import receipt_path

SAMPLE_FRAMES = 250
DATASETS = {
    "dfl-sportec-idsse": "DFL-MAT-J03WPY",
    "skillcorner-opendata": "1925299",
}
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
    "is_detected",
]


def _tracking_paths(dataset_root: Path, dataset_id: str, session_id: str) -> list[Path]:
    base = dataset_root / "silver" / f"dataset_id={dataset_id}" / "modality=tracking"
    paths = sorted((base / f"session_id={session_id}").glob("*.parquet"))
    if len(paths) < 2:
        raise FileNotFoundError(f"{dataset_id}: accepted tracking periods are unavailable")
    return paths


def _bounded_tracking(path: Path) -> pa.Table:
    table = pq.read_table(path, columns=TRACKING_COLUMNS)
    selected_times: list[int] = []
    seen: set[int] = set()
    timestamp_values = table.column("t_rel_ns").to_pylist()
    for value in timestamp_values:
        timestamp = int(value)
        if timestamp not in seen:
            selected_times.append(timestamp)
            seen.add(timestamp)
            if len(selected_times) == SAMPLE_FRAMES:
                break
    if not selected_times:
        raise ValueError(f"{path.name}: no canonical tracking timestamps")
    selected = set(selected_times)
    mask = pa.array([int(value) in selected for value in timestamp_values], type=pa.bool_())
    return table.filter(mask)


def _run_period(settings_value, dataset_id: str, tracking_path: Path) -> dict[str, object]:
    tracking = _bounded_tracking(tracking_path)
    trial_id = str(tracking.column("trial_id")[0].as_py())
    source = load_tactical_source_authority(
        settings_value,
        dataset_id=dataset_id,
        trial_id=trial_id,
        tracking=tracking,
    )
    canonical_input = collect_input(
        settings_value,
        tracking_path,
        role="silver_tracking_bounded_sample",
        row_count=tracking.num_rows,
    )
    result = process_tactical_shape(
        tracking,
        role_by_player=source.role_by_player,
        attacking_direction_by_team=source.attacking_direction_by_team,
        possession=source.possession,
        role_authority=source.role_authority,
        direction_authority=source.direction_authority,
    )
    inputs = (*source.inputs, canonical_input)
    first = execute_processor(
        settings_value,
        result=result,
        dataset_id=dataset_id,
        inputs=inputs,
        series_key=f"res110-v3-{trial_id}",
        persist=False,
    )
    second = execute_processor(
        settings_value,
        result=result,
        dataset_id=dataset_id,
        inputs=inputs,
        series_key=f"res110-v3-{trial_id}",
        persist=False,
    )
    role_counts = dict(sorted(Counter(source.role_by_player.values()).items()))
    return {
        "period": trial_id,
        "canonical_sample_rows": tracking.num_rows,
        "sample_frames": len(set(tracking.column("t_rel_ns").to_pylist())),
        "input_checksums": [item.checksum_sha256 for item in inputs],
        "source_roles": role_counts,
        "direction_authority": source.direction_authority,
        "directional_teams": len(source.attacking_direction_by_team),
        "source_possession_frames": source.possession.num_rows,
        "source_possession_known_frames": sum(
            value is not None for value in source.possession.column("team_id").to_pylist()
        ),
        "role_authority": source.role_authority,
        "possession_authority": source.possession_authority,
        "algorithm_id": result.spec.algorithm_id,
        "algorithm_version": result.spec.version,
        "parameters_hash": result.spec.parameters_hash,
        "code_git_sha": first.code_git_sha,
        "run_id": first.run_id,
        "rerun_run_id": second.run_id,
        "run_id_stable": first.run_id == second.run_id,
        "series_checksums": read_series_checksums(first),
        "rerun_series_checksums": read_series_checksums(second),
        "series_stable": read_series_checksums(first) == read_series_checksums(second),
        "output_rows": {item.name: item.table.num_rows for item in result.series},
        "processor_receipts": [first.receipt_path, second.receipt_path],
        "phase_classifier_emitted": result.diagnostics["phase_classifier_emitted"],
    }


def main() -> int:
    resolved = settings()
    results: dict[str, list[dict[str, object]]] = {}
    for dataset_id, session_id in DATASETS.items():
        results[dataset_id] = [
            _run_period(resolved, dataset_id, path)
            for path in _tracking_paths(resolved.dataset_root, dataset_id, session_id)
        ]
    receipt = {
        "acceptance": "RES-110 MatchLab Tactical V3 bounded real-data validation",
        "sample_frames_per_period": SAMPLE_FRAMES,
        "raw_rows_committed": False,
        "source_event_and_phase_labels_rederived": False,
        "results": results,
    }
    target = receipt_path(
        resolved,
        dataset_id="platform",
        kind="acceptance",
        name="res110-tactical-v3-real-sources",
    )
    atomic_write_text(target, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
