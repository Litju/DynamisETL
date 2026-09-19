"""Dagster assets for the RES-100 deterministic processor and Gold lineage.

Lineage (explicitly selected; nothing runs on import)::

    <lab/real source silver assets> -> white_cmj_force_processing
                                    -> white_cmj_imu_processing
                                    -> white_cmj_cross_sensor_processing
    womens_j01_silver_gnss -> womens_gnss_processing
    dfl_j03wpy_silver_tracking -> dfl_tracking_processing
    skillcorner silver tracking/pose -> skillcorner_tracking_processing
                                     -> skillcorner_pose_processing
    all processing assets -> gold_serving_export -> gold_marts -> gold_publish

Every asset reads already-acquired canonical Silver streams through the
control-plane registry and verifies their checksums; importing this module never
downloads anything, and CI materializes only the synthetic LPT asset.

This module intentionally avoids ``from __future__ import annotations``:
Dagster resolves annotations at decoration time.
"""

from dagster import (
    AssetCheckResult,
    AssetCheckSeverity,
    AssetKey,
    asset,
    asset_check,
)

from dynamis.config import settings
from dynamis.gold.build import build_gold
from dynamis.gold.export import export_serving
from dynamis.gold.publish import publish_gold
from dynamis.processors.acceptance import (
    SKILLCORNER_ACCEPTANCE_PARAMETERS,
    SKILLCORNER_POSE_PARAMETERS,
    TRACKING_ACCEPTANCE_PARAMETERS,
    StreamProcessorPlan,
    process_corpus,
    white_cross_sensor_acceptance,
)
from dynamis.storage.control_plane import control_plane_engine

WHITE_DATASET_ID = "white-cmj-acc-grf"
WOMENS_DATASET_ID = "womens-soccer-positioning"
DFL_DATASET_ID = "dfl-sportec-idsse"
SKILLCORNER_DATASET_ID = "skillcorner-opendata"


def _engine():
    resolved = settings()
    return resolved, control_plane_engine(resolved)


def _process(
    dataset_id: str,
    modality: str,
    processor,
    *,
    parameters: dict | None = None,
) -> dict:
    resolved, engine = _engine()
    try:
        if parameters is None:
            plan = StreamProcessorPlan(
                dataset_id=dataset_id, modality=modality, processor=processor
            )
        else:
            plan = StreamProcessorPlan(
                dataset_id=dataset_id,
                modality=modality,
                processor=lambda table: processor(table, parameters=parameters),
            )
        return process_corpus(resolved, engine, plan=plan).to_dict()
    finally:
        engine.dispose()


def _force_processor(table):
    from dynamis.processors.force_cmj import process_force_cmj

    return process_force_cmj(table)


def _imu_processor(table):
    from dynamis.processors.imu import process_imu

    return process_imu(table)


def _loco_processor(table):
    from dynamis.processors.locomotor import process_locomotor

    return process_locomotor(table)


def _pose_processor(table):
    from dynamis.processors.pose import process_pose

    return process_pose(table, parameters=SKILLCORNER_POSE_PARAMETERS)


def _womens_processor(table):
    from dynamis.processors.acceptance import WOMENS_GEODETIC_PARAMETERS
    from dynamis.processors.locomotor import process_locomotor

    return process_locomotor(table, parameters=WOMENS_GEODETIC_PARAMETERS)


def _dfl_processor(table):
    from dynamis.processors.locomotor import process_locomotor

    return process_locomotor(table, parameters=TRACKING_ACCEPTANCE_PARAMETERS)


def _skillcorner_tracking_processor(table):
    from dynamis.processors.locomotor import process_locomotor

    return process_locomotor(table, parameters=SKILLCORNER_ACCEPTANCE_PARAMETERS)


@asset(group_name="processors", compute_kind="python")
def white_cmj_force_processing() -> dict:
    """Full-record CMJ force metrics for every registered White trial."""
    return _process(WHITE_DATASET_ID, "force", _force_processor)


@asset(group_name="processors", compute_kind="python")
def white_cmj_imu_processing() -> dict:
    """Sensor-frame resultant and derivative features for every White trial."""
    return _process(WHITE_DATASET_ID, "imu", _imu_processor)


@asset(group_name="processors", compute_kind="python")
def white_cmj_cross_sensor_processing() -> dict:
    """Exact-coincidence force/IMU association over persisted sync pairs only."""
    resolved, engine = _engine()
    try:
        return white_cross_sensor_acceptance(resolved, engine)
    finally:
        engine.dispose()


@asset(group_name="processors", compute_kind="python")
def womens_gnss_processing() -> dict:
    """Geodetic locomotor processing for the Women's GNSS release."""
    return _process(WOMENS_DATASET_ID, "gnss", _womens_processor)


@asset(group_name="processors", compute_kind="python")
def dfl_tracking_processing() -> dict:
    """Planar locomotor processing for the DFL tracking product."""
    return _process(DFL_DATASET_ID, "tracking", _dfl_processor)


@asset(group_name="processors", compute_kind="python")
def skillcorner_tracking_processing() -> dict:
    """Planar locomotor processing for SkillCorner tracking (never pose XY)."""
    return _process(SKILLCORNER_DATASET_ID, "tracking", _skillcorner_tracking_processor)


@asset(group_name="processors", compute_kind="python")
def skillcorner_pose_processing() -> dict:
    """Translation-invariant pose geometry for the SkillCorner pose product."""
    return _process(SKILLCORNER_DATASET_ID, "pose", _pose_processor)


@asset(group_name="synthetic_processors", compute_kind="python")
def synthetic_lpt_known_answer() -> dict:
    """Synthetic-only LPT processor check (no real SPL/GymAware dense data).

    A known-answer sinusoid is segmented in memory and the three analytic
    features (repetition count, ROM, peak speed) are asserted before the asset
    returns. This is the CI surface for the generic LPT processor; real
    GymAware data remains summary-only.
    """
    import math

    import numpy as np
    import pyarrow as pa

    from dynamis.contracts import LPT_SCHEMA
    from dynamis.processors.lpt import process_lpt

    rate_hz = 100
    amplitude = 0.6
    frequency = 1.0
    periods = 4
    samples = int(periods / frequency * rate_hz) + 1
    times = np.arange(samples) / rate_hz
    position = -amplitude * np.cos(2 * math.pi * frequency * times)
    rows = [
        {
            "dataset_id": "synthetic-lpt",
            "session_id": "synthetic-session",
            "trial_id": "synthetic-trial",
            "subject_id": "synthetic-subject",
            "device_id": None,
            "stream_id": "lpt-synthetic-known-answer",
            "sample_index": index,
            "t_rel_ns": index * (1_000_000_000 // rate_hz),
            "timestamp_utc_ns": None,
            "nominal_sampling_rate_hz": float(rate_hz),
            "measurement_class": "PIPELINE_DERIVED",
            "clock_id": "synthetic-clock",
            "synchronization_spec_id": "synthetic-sync",
            "coordinate_frame_id": None,
            "position_m": float(position[index]),
            "velocity_m_s": None,
            "load_kg": None,
            "load_n": None,
            "cable_angle_deg": None,
            "rep_index": None,
            "quality_flag": None,
        }
        for index in range(samples)
    ]
    table = pa.Table.from_batches([pa.RecordBatch.from_pylist(rows, schema=LPT_SCHEMA)])
    result = process_lpt(table)
    by_id = {metric.declaration.metric_id: metric.value for metric in result.metrics}
    if by_id.get("lpt.rep_count") != 3.0:
        raise ValueError(
            f"synthetic LPT known answer failed: rep_count={by_id.get('lpt.rep_count')}"
        )
    if abs(by_id["lpt.rep_rom_max"] - 2 * amplitude) > 0.005:
        raise ValueError("synthetic LPT known answer failed: ROM")
    if abs(by_id["lpt.rep_peak_speed_max"] - amplitude * 2 * math.pi * frequency) > 0.05:
        raise ValueError("synthetic LPT known answer failed: peak speed")
    return {
        "validation_scope": "synthetic_known_answer_only",
        "gymaware_validation_claimed": False,
        "rep_count": by_id["lpt.rep_count"],
        "rom_max_m": by_id["lpt.rep_rom_max"],
        "peak_speed_max_m_s": by_id["lpt.rep_peak_speed_max"],
        "parameters_hash": result.spec.parameters_hash,
    }


@asset(group_name="gold", compute_kind="python")
def gold_serving_export(
    white_cmj_force_processing: dict,
    white_cmj_imu_processing: dict,
    white_cmj_cross_sensor_processing: dict,
    womens_gnss_processing: dict,
    dfl_tracking_processing: dict,
    skillcorner_tracking_processing: dict,
    skillcorner_pose_processing: dict,
) -> dict:
    """Deterministic Parquet export of the control plane for dbt-duckdb."""
    del (
        white_cmj_force_processing,
        white_cmj_imu_processing,
        white_cmj_cross_sensor_processing,
        womens_gnss_processing,
        dfl_tracking_processing,
        skillcorner_tracking_processing,
        skillcorner_pose_processing,
    )
    resolved, engine = _engine()
    try:
        return export_serving(resolved, engine).to_dict()
    finally:
        engine.dispose()


@asset(group_name="gold", compute_kind="dbt")
def gold_marts(gold_serving_export: dict) -> dict:
    """dbt-duckdb build (models + tests) over the serving export."""
    del gold_serving_export
    resolved = settings()
    return build_gold(resolved).to_dict()


@asset(group_name="gold", compute_kind="postgres")
def gold_publish(gold_marts: dict) -> dict:
    """Publish curated marts into the dedicated PostgreSQL gold schema."""
    del gold_marts
    resolved, engine = _engine()
    try:
        return publish_gold(resolved, engine)
    finally:
        engine.dispose()


@asset_check(
    asset=AssetKey("white_cmj_force_processing"),
    description="Every White trial produced metrics and a processing run.",
)
def white_force_processing_complete(white_cmj_force_processing: dict) -> AssetCheckResult:
    streams = int(white_cmj_force_processing.get("streams", 0))
    runs = int(white_cmj_force_processing.get("runs", 0))
    return AssetCheckResult(
        passed=streams > 0 and runs > 0 and streams == runs,
        severity=AssetCheckSeverity.ERROR,
        metadata={"streams": streams, "runs": runs},
    )


@asset_check(
    asset=AssetKey("synthetic_lpt_known_answer"),
    description="The synthetic LPT known-answer asset carries its analytic values.",
)
def synthetic_lpt_known_answer_holds(synthetic_lpt_known_answer: dict) -> AssetCheckResult:
    return AssetCheckResult(
        passed=(
            synthetic_lpt_known_answer.get("validation_scope") == "synthetic_known_answer_only"
            and synthetic_lpt_known_answer.get("gymaware_validation_claimed") is False
            and synthetic_lpt_known_answer.get("rep_count") == 3.0
        ),
        severity=AssetCheckSeverity.ERROR,
        metadata={
            "rep_count": synthetic_lpt_known_answer.get("rep_count"),
            "rom_max_m": synthetic_lpt_known_answer.get("rom_max_m"),
            "peak_speed_max_m_s": synthetic_lpt_known_answer.get("peak_speed_max_m_s"),
        },
    )


@asset_check(
    asset=AssetKey("gold_marts"),
    description="Gold marts rebuild deterministically and reconcile with the export.",
)
def gold_marts_reconcile(gold_marts: dict) -> AssetCheckResult:
    marts = gold_marts.get("marts", {})
    expected = {
        "gold_trial_metrics",
        "gold_session_player_load",
        "gold_cmj_metrics",
        "gold_pose_kinematics_summary",
        "gold_processing_provenance",
    }
    return AssetCheckResult(
        passed=bool(gold_marts.get("success")) and expected <= set(marts),
        severity=AssetCheckSeverity.ERROR,
        metadata={
            "marts": sorted(marts),
            "trial_metrics_rows": marts.get("gold_trial_metrics", {}).get("row_count"),
        },
    )


__all__ = [
    "dfl_tracking_processing",
    "gold_marts",
    "gold_publish",
    "gold_serving_export",
    "skillcorner_pose_processing",
    "skillcorner_tracking_processing",
    "synthetic_lpt_known_answer",
    "white_cmj_cross_sensor_processing",
    "white_cmj_force_processing",
    "white_cmj_imu_processing",
    "womens_gnss_processing",
]
