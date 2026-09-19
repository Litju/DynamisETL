"""Local real-source acceptance for RES-100.

Runs the deterministic processors over already-acquired canonical Silver data
(White CMJ force/IMU/cross-sensor, Women's GNSS, DFL and SkillCorner tracking,
SkillCorner pose), proves checksum-deterministic reruns, executes the
synthetic-only LPT known-answer check, verifies GymAware stayed summary-only,
and rebuilds the Gold marts over the real control plane. No step downloads
anything and no dense sample is written to PostgreSQL.

Usage (from the repository root, with the machine-local .env configured)::

    uv run python scripts/res100_real_acceptance.py
"""

from __future__ import annotations

import json
import sys
import time

from sqlalchemy import text

from dynamis.config import settings
from dynamis.gold.build import build_gold
from dynamis.gold.export import export_serving
from dynamis.gold.publish import publish_gold
from dynamis.orchestration.processors import synthetic_lpt_known_answer
from dynamis.processors.acceptance import (
    SKILLCORNER_ACCEPTANCE_PARAMETERS,
    TRACKING_ACCEPTANCE_PARAMETERS,
    skillcorner_pose_acceptance,
    tracking_acceptance,
    white_cross_sensor_acceptance,
    white_force_acceptance,
    white_imu_acceptance,
    womens_gnss_acceptance,
)
from dynamis.storage.atomic import atomic_write_text
from dynamis.storage.control_plane import control_plane_engine
from dynamis.storage.paths import receipt_path, relative_posix

DFL_DATASET_ID = "dfl-sportec-idsse"
SKILLCORNER_DATASET_ID = "skillcorner-opendata"


def _progress(label: str):
    def report(done: int, total: int) -> None:
        if done == total or done % 100 == 0:
            print(f"  {label}: {done}/{total}", file=sys.stderr, flush=True)

    return report


def _compact(receipt: dict) -> dict:
    """Strip per-stream detail lists from a receipt for the console summary."""
    compact = {}
    for key, value in receipt.items():
        if key in {"per_stream", "paired_keys", "aggregate_metrics", "metric_summaries"}:
            continue
        compact[key] = value
    return compact


def main() -> int:
    resolved = settings()
    engine = control_plane_engine(resolved)
    summary: dict = {}
    started = time.time()
    try:
        print("[1/8] White CMJ force (663 trials, deterministic rerun)", file=sys.stderr)
        summary["white_force"] = _compact(
            white_force_acceptance(resolved, engine, progress=_progress("white-force"))
        )
        print("[2/8] White CMJ IMU (663 streams)", file=sys.stderr)
        summary["white_imu"] = _compact(
            white_imu_acceptance(resolved, engine, progress=_progress("white-imu"))
        )
        print("[3/8] White force/IMU cross-sensor (persisted sync pairs)", file=sys.stderr)
        summary["white_cross_sensor"] = _compact(
            white_cross_sensor_acceptance(resolved, engine, progress=_progress("cross-sensor"))
        )
        print("[4/8] Women's GNSS (geodetic)", file=sys.stderr)
        summary["womens_gnss"] = _compact(
            womens_gnss_acceptance(resolved, engine, progress=_progress("womens-gnss"))
        )
        print("[5/8] DFL tracking (planar)", file=sys.stderr)
        summary["dfl_tracking"] = _compact(
            tracking_acceptance(
                resolved,
                engine,
                dataset_id=DFL_DATASET_ID,
                parameters=TRACKING_ACCEPTANCE_PARAMETERS,
                kind="res100-dfl-tracking",
                progress=_progress("dfl"),
            )
        )
        print("[6/8] SkillCorner tracking (planar)", file=sys.stderr)
        summary["skillcorner_tracking"] = _compact(
            tracking_acceptance(
                resolved,
                engine,
                dataset_id=SKILLCORNER_DATASET_ID,
                parameters=SKILLCORNER_ACCEPTANCE_PARAMETERS,
                kind="res100-skillcorner-tracking",
                progress=_progress("skillcorner"),
            )
        )
        print("[7/8] SkillCorner pose (translation-invariant geometry)", file=sys.stderr)
        summary["skillcorner_pose"] = _compact(
            skillcorner_pose_acceptance(resolved, engine, progress=_progress("pose"))
        )
        print("[8/8] Synthetic LPT + GymAware summary-only + Gold", file=sys.stderr)
        summary["spl_synthetic_lpt"] = synthetic_lpt_known_answer()
        with engine.connect() as connection:
            gymaware = connection.execute(
                text(
                    "SELECT measurement_class, count(*) FROM derived_metric "
                    "WHERE metric_id LIKE 'gymaware_%' GROUP BY measurement_class"
                )
            ).fetchall()
        summary["gymaware_source_only"] = {
            "classes": {row[0]: row[1] for row in gymaware},
            "dense_lpt_processing": False,
            "gymaware_validation_claimed": False,
            "note": (
                "The real GymAware archive is summary-only; its values stay SOURCE_DERIVED and "
                "feed Gold without any dense LPT fabrication or GymAware validation claim."
            ),
        }
        summary["spl"] = {
            "real_files_processed": 0,
            "validation": "synthetic known-answer only",
            "note": "No real SPL file is acquired or processed in RES-100.",
        }

        export = export_serving(resolved, engine)
        summary["gold_export"] = {
            "root": str(export.root),
            "tables": export.tables,
            "receipt_path": export.receipt_path,
        }
        built = build_gold(resolved)
        summary["gold_build"] = built.to_dict()
        summary["gold_publish"] = publish_gold(resolved, engine)
    finally:
        engine.dispose()

    summary["elapsed_s"] = round(time.time() - started, 1)
    target = receipt_path(
        resolved, dataset_id="platform", kind="acceptance", name="res100-real-e2e"
    )
    atomic_write_text(
        target,
        json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n",
    )
    summary["receipt_path"] = relative_posix(resolved.dataset_root, target)
    print(json.dumps(summary, indent=1, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
