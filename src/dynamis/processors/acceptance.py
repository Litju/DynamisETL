"""Real-source acceptance harness for processor runs.

This module executes processors over already-acquired canonical Silver corpora,
proves checksum-deterministic reruns and reports paired agreement against
source-provided reference values. It never downloads anything and never claims
a source value is physical ground truth: reference metrics are labelled
SOURCE_DERIVED, the comparison is descriptive, and no automatic scientific
verdict is emitted.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Engine

from dynamis.config import Settings
from dynamis.processors.corpus import SilverStreamRef, list_silver_streams, load_silver
from dynamis.processors.force_cmj import process_force_cmj
from dynamis.processors.runtime import ProcessorRunResult, execute_processor
from dynamis.processors.statistics import bland_altman, paired_comparison
from dynamis.storage.atomic import atomic_write_text
from dynamis.storage.metadata import build_metadata
from dynamis.storage.paths import receipt_path, relative_posix

_TABLES = build_metadata().tables
DERIVED_METRIC_TABLE = _TABLES["derived_metric"]
SKELETON_JOINT_TABLE = _TABLES["skeleton_joint"]

WHITE_DATASET_ID = "white-cmj-acc-grf"
REFERENCE_JUMP_HEIGHT = "source_jump_height"
REFERENCE_PEAK_POWER = "source_peak_power_relative"
PIPELINE_JUMP_HEIGHT = "cmj.jump_height_jhwd"
PIPELINE_PEAK_POWER = "cmj.peak_specific_power"


@dataclass(frozen=True, slots=True)
class DatasetProcessing:
    """Outcome of processing one canonical corpus with one processor."""

    dataset_id: str
    algorithm_id: str
    streams: int
    runs: int
    series_checksums: dict[str, str]
    metric_values: dict[str, float]
    metric_units: dict[str, str]
    processed_stream_ids: tuple[str, ...] = ()
    run_ids: tuple[str, ...] = ()
    algorithm_version: str = ""
    parameters_hash: str = ""
    code_git_sha: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable corpus processing descriptor."""
        return {
            "dataset_id": self.dataset_id,
            "algorithm_id": self.algorithm_id,
            "algorithm_version": self.algorithm_version,
            "parameters_hash": self.parameters_hash,
            "code_git_sha": self.code_git_sha,
            "streams": self.streams,
            "runs": self.runs,
            "series_checksums": self.series_checksums,
            "metric_count": len(self.metric_values),
            "processed_stream_ids": list(self.processed_stream_ids),
            "diagnostics": self.diagnostics,
        }


def _reference_values(
    connection,
    *,
    dataset_id: str,
    metric_ids: tuple[str, ...],
) -> dict[str, dict[str, float]]:
    """Reference metric values from the control plane, keyed by trial/stream."""
    rows = connection.execute(
        sa.select(
            DERIVED_METRIC_TABLE.c.metric_id,
            DERIVED_METRIC_TABLE.c.trial_id,
            DERIVED_METRIC_TABLE.c.stream_id,
            DERIVED_METRIC_TABLE.c.value_num,
        ).where(
            DERIVED_METRIC_TABLE.c.dataset_id == dataset_id,
            DERIVED_METRIC_TABLE.c.metric_id.in_(metric_ids),
        )
    ).fetchall()
    values: dict[str, dict[str, float]] = {metric_id: {} for metric_id in metric_ids}
    for row in rows:
        key = row.trial_id or row.stream_id
        if key is None:
            continue
        values[row.metric_id][key] = float(row.value_num)
    return values


def _collect_pipeline_values(
    runs: dict[str, ProcessorRunResult],
    *,
    stream_to_key: dict[str, str],
    metric_ids: tuple[str, ...],
) -> dict[str, dict[str, float]]:
    """In-memory pipeline values of this execution, keyed by trial/stream.

    Reading the values from the executed results (instead of re-querying every
    historical revision of the algorithm) keeps the comparison bound to exactly
    the code revision and parameters that produced the receipt.
    """
    values: dict[str, dict[str, float]] = {metric_id: {} for metric_id in metric_ids}
    for stream_id, run in runs.items():
        key = stream_to_key[stream_id]
        for metric in run.metrics.metrics:
            if metric.declaration.metric_id in values:
                values[metric.declaration.metric_id][key] = metric.value
    return values


def _paired(
    pipeline: dict[str, float],
    reference: dict[str, float],
    *,
    tolerance: float,
) -> dict[str, Any]:
    """Descriptive paired comparison payload with no automated verdict."""
    keys = sorted(set(pipeline) & set(reference))
    if not keys:
        return {"n": 0, "paired_keys": []}
    comparison = paired_comparison(
        [pipeline[key] for key in keys],
        [reference[key] for key in keys],
        tolerance=tolerance,
    )
    payload = comparison.to_dict()
    payload["paired_keys"] = keys
    payload["within_tolerance_fraction"] = (
        comparison.within_tolerance / comparison.n
        if comparison.within_tolerance is not None
        else None
    )
    bands = bland_altman([pipeline[key] for key in keys], [reference[key] for key in keys])
    payload["bland_altman"] = None if bands is None else bands.to_dict()
    payload["reference_semantics"] = (
        "source-derived reference metric supplied by the provider; not physical ground truth"
    )
    payload["verdict"] = None
    return payload


def white_force_acceptance(
    settings: Settings,
    engine: Engine,
    *,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Process all registered White CMJ force streams and compare references."""
    with engine.connect() as connection:
        refs = list_silver_streams(connection, dataset_id=WHITE_DATASET_ID, modality="force")
    if not refs:
        raise ValueError(f"{WHITE_DATASET_ID}: no registered force streams to process")

    def process(ref: SilverStreamRef) -> ProcessorRunResult:
        table, processor_input = load_silver(settings, ref)
        result = process_force_cmj(table)
        return execute_processor(
            settings,
            result=result,
            dataset_id=WHITE_DATASET_ID,
            inputs=(processor_input,),
            series_key=ref.stream_id,
            engine=engine,
        )

    first_pass: dict[str, ProcessorRunResult] = {}
    for index, ref in enumerate(refs):
        first_pass[ref.stream_id] = process(ref)
        if progress is not None:
            progress(index + 1, len(refs))

    checksums = {
        stream_id: run.series[0].artifact.checksum_sha256
        for stream_id, run in first_pass.items()
        if run.series
    }
    # Deterministic rerun: the same code revision over the same verified inputs
    # must reproduce byte-identical artifacts and identical metric values, and
    # must not duplicate a single control-plane row.
    second_pass: dict[str, ProcessorRunResult] = {}
    for ref in refs:
        second_pass[ref.stream_id] = process(ref)
    rerun_matches = sum(
        1
        for stream_id, run in second_pass.items()
        if run.series and run.series[0].artifact.checksum_sha256 == checksums.get(stream_id)
    )
    run_ids_stable = all(
        second_pass[stream_id].run_id == first_pass[stream_id].run_id for stream_id in first_pass
    )

    pipeline = _collect_pipeline_values(
        first_pass,
        stream_to_key={ref.stream_id: ref.trial_id or ref.stream_id for ref in refs},
        metric_ids=(PIPELINE_JUMP_HEIGHT, PIPELINE_PEAK_POWER),
    )
    with engine.connect() as connection:
        reference = _reference_values(
            connection,
            dataset_id=WHITE_DATASET_ID,
            metric_ids=(REFERENCE_JUMP_HEIGHT, REFERENCE_PEAK_POWER),
        )
        # Persistence proof for the executed runs: every stream's metrics must be
        # present in the control plane exactly once under its deterministic run.
        metric_rows = connection.execute(
            sa.select(sa.func.count())
            .select_from(DERIVED_METRIC_TABLE)
            .where(
                DERIVED_METRIC_TABLE.c.dataset_id == WHITE_DATASET_ID,
                DERIVED_METRIC_TABLE.c.run_id.in_(
                    sorted({run.run_id for run in first_pass.values()})
                ),
            )
        ).scalar_one()
        provenance_rows = connection.execute(
            sa.select(DERIVED_METRIC_TABLE.c.provenance)
            .where(
                DERIVED_METRIC_TABLE.c.run_id == first_pass[refs[0].stream_id].run_id,
                DERIVED_METRIC_TABLE.c.metric_id == PIPELINE_JUMP_HEIGHT,
            )
            .limit(1)
        ).fetchone()
    provenance = dict(provenance_rows.provenance) if provenance_rows else {}
    expected_metric_rows = len(refs) * 7
    if metric_rows != expected_metric_rows:
        raise ValueError(
            f"{WHITE_DATASET_ID}: expected {expected_metric_rows} persisted metric rows for "
            f"the executed runs, found {metric_rows}"
        )
    if provenance.get("parameters_hash") != first_pass[refs[0].stream_id].parameters_hash:
        raise ValueError("persisted metric provenance does not carry the executed parameters hash")
    if provenance.get("code_git_sha") != first_pass[refs[0].stream_id].code_git_sha:
        raise ValueError("persisted metric provenance does not carry the executed code Git SHA")

    jump_height = _paired(
        pipeline[PIPELINE_JUMP_HEIGHT], reference[REFERENCE_JUMP_HEIGHT], tolerance=1e-3
    )
    peak_power = _paired(
        pipeline[PIPELINE_PEAK_POWER], reference[REFERENCE_PEAK_POWER], tolerance=0.1
    )
    receipt = {
        "dataset_id": WHITE_DATASET_ID,
        "algorithm_id": first_pass[refs[0].stream_id].spec.algorithm_id,
        "algorithm_version": first_pass[refs[0].stream_id].spec.version,
        "parameters_hash": first_pass[refs[0].stream_id].parameters_hash,
        "code_git_sha": first_pass[refs[0].stream_id].code_git_sha,
        "streams": len(refs),
        "runs": len(first_pass),
        "metric_rows_total": int(metric_rows),
        "persisted_provenance_parameters_hash": provenance.get("parameters_hash"),
        "persisted_provenance_code_git_sha": provenance.get("code_git_sha"),
        "rerun_series_matches": rerun_matches,
        "rerun_run_ids_stable": run_ids_stable,
        "jump_height_comparison": jump_height,
        "peak_power_comparison": peak_power,
        "reference_semantics": (
            "source_jump_height and source_peak_power_relative remain SOURCE_DERIVED provider "
            "values; the pipeline metrics carry distinct PIPELINE_DERIVED identities"
        ),
        "no_body_mass_fabricated": True,
        "no_flight_time_metric": True,
        "full_record_used": True,
        "onset_redetection": False,
    }
    target = receipt_path(
        settings, dataset_id=WHITE_DATASET_ID, kind="acceptance", name="res100-white-force"
    )
    atomic_write_text(target, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    receipt["receipt_path"] = relative_posix(settings.dataset_root, target)
    return receipt


WOMENS_DATASET_ID = "womens-soccer-positioning"
DFL_DATASET_ID = "dfl-sportec-idsse"
SKILLCORNER_DATASET_ID = "skillcorner-opendata"

#: Explicit geodetic configuration for the Women's consumer-GNSS release.
#: The datum is the pipeline's documented WGS 84 inference, not a provider
#: declaration; no datum transform is applied. The derivative edge policy is
#: ``nan`` so no value is claimed where a central difference would need
#: extrapolation, and no filter is applied.
WOMENS_GEODETIC_PARAMETERS: dict[str, Any] = {
    "position_domain": "geodetic",
    "distance_method": "haversine_wgs84_mean_radius",
    "enu_method": "equirectangular_tangent_plane_wgs84_mean_radius",
    "earth_radius_m": 6_371_008.8,
    "derivative": {
        "filter": {
            "family": "none",
            "order": None,
            "cutoff_hz": None,
            "phase": "zero_phase",
            "padding": "odd",
            "padlen": None,
        },
        "edge_policy": "nan",
    },
    "filter_applies_to": "kinematics_only",
    # Explicit run configuration for a consumer-GNSS release whose positions
    # contain isolated acquisition glitches (up to kilometres in one 100 ms
    # step) while the provider speed channel stays smooth. A step above this
    # supplied SI bound is excluded from kinematics AND from the distance
    # accumulation; the record itself is never modified and the raw input
    # checksum is preserved. This is supplied configuration, not a universal
    # sport constant.
    "step_speed_gate": {
        "max_m_s": 15.0,
        "excluded_step_policy": "drop_step_from_distance",
    },
    "resample_method": "none",
    "interpolation": "none",
    "zones": [],
    "effort": None,
    "rolling_windows_s": [],
}

#: Explicit planar tracking configuration used for the DFL and SkillCorner
#: acceptance runs. Zones, effort rules and rolling windows are supplied run
#: configuration in SI units, never universal scientific constants.
TRACKING_ACCEPTANCE_PARAMETERS: dict[str, Any] = {
    "position_domain": "planar",
    # Athletes only: the ball shares the tracking stream but is not a locomotor
    # entity, so it never receives distance/speed/effort metrics.
    "entity_object_types": ["player", "goalkeeper"],
    "derivative": {
        "filter": {
            "family": "none",
            "order": None,
            "cutoff_hz": None,
            "phase": "zero_phase",
            "padding": "odd",
            "padlen": None,
        },
        "edge_policy": "nan",
    },
    "step_speed_gate": {
        "max_m_s": 15.0,
        "excluded_step_policy": "keep_step_in_distance",
    },
    "zones": [
        {"name": "low", "lower_m_s": 0.0, "upper_m_s": 2.0},
        {"name": "medium", "lower_m_s": 2.0, "upper_m_s": 5.5},
        {"name": "high", "lower_m_s": 5.5, "upper_m_s": None},
    ],
    "effort": {
        "threshold_m_s": 5.0,
        "min_duration_s": 1.0,
        "merge_gap_s": 0.5,
        "hysteresis_m_s": 0.5,
    },
    "rolling_windows_s": [1.0, 5.0, 10.0],
}

#: SkillCorner declares is_detected on every sample, so its acceptance run also
#: honors the provider's own detection declaration for kinematics.
SKILLCORNER_ACCEPTANCE_PARAMETERS: dict[str, Any] = {
    **TRACKING_ACCEPTANCE_PARAMETERS,
    "detection_gate": "require_is_detected",
}

#: Pose geometry for the SkillCorner acceptance run: required landmarks are named
#: explicitly and every segment/angle is a translation-invariant relative vector.
#: Z stays the provider's centroid-relative channel; no absolute height or COM
#: interpretation is made.
SKILLCORNER_POSE_PARAMETERS: dict[str, Any] = {
    "required_coordinate_components": ["x_m", "y_m", "z_m"],
    "segments": [
        {"name": "left_thigh", "start_landmark": "lHip", "end_landmark": "lKnee"},
        {"name": "right_thigh", "start_landmark": "rHip", "end_landmark": "rKnee"},
        {"name": "left_shank", "start_landmark": "lKnee", "end_landmark": "lAnkle"},
        {"name": "right_shank", "start_landmark": "rKnee", "end_landmark": "rAnkle"},
        {"name": "shoulder_width", "start_landmark": "lShoulder", "end_landmark": "rShoulder"},
        {"name": "hip_width", "start_landmark": "lHip", "end_landmark": "rHip"},
    ],
    "angles": [
        {
            "name": "left_knee",
            "vertex_landmark": "lKnee",
            "first_landmark": "lHip",
            "second_landmark": "lAnkle",
        },
        {
            "name": "right_knee",
            "vertex_landmark": "rKnee",
            "first_landmark": "rHip",
            "second_landmark": "rAnkle",
        },
        {
            "name": "left_hip",
            "vertex_landmark": "lHip",
            "first_landmark": "lShoulder",
            "second_landmark": "lKnee",
        },
        {
            "name": "right_hip",
            "vertex_landmark": "rHip",
            "first_landmark": "rShoulder",
            "second_landmark": "rKnee",
        },
    ],
    "derivative": {
        "filter": {
            "family": "none",
            "order": None,
            "cutoff_hz": None,
            "phase": "zero_phase",
            "padding": "odd",
            "padlen": None,
        },
        "edge_policy": "nan",
    },
    "error_policy": "worst_case_additive_radius",
}

SKILLCORNER_POSE_QUALITY_PARAMETERS: dict[str, Any] = {
    "expected_joint_names": [],
    "metric_requirements": {
        **{
            f"segment_{segment['name']}": [
                segment["start_landmark"],
                segment["end_landmark"],
            ]
            for segment in SKILLCORNER_POSE_PARAMETERS["segments"]
        },
        **{
            f"included_angle_{angle['name']}": [
                angle["vertex_landmark"],
                angle["first_landmark"],
                angle["second_landmark"],
            ]
            for angle in SKILLCORNER_POSE_PARAMETERS["angles"]
        },
        **{
            f"body_relative_kinematics_{name}": [name, "midHip"]
            for name in (
                "lHip",
                "rHip",
                "lKnee",
                "rKnee",
                "lAnkle",
                "rAnkle",
            )
        },
    },
    "minimum_derivative_segment_frames": 3,
    "derivative": SKILLCORNER_POSE_PARAMETERS["derivative"],
}

SKILLCORNER_POSE_LANDMARK_PARAMETERS: dict[str, Any] = {
    "landmark_names": ["lHip", "rHip", "lKnee", "rKnee", "lAnkle", "rAnkle"],
    "body_anchor_landmark": "midHip",
    "max_gap_factor": 1.5,
    "derivative": SKILLCORNER_POSE_PARAMETERS["derivative"],
    "acceleration": {
        "enabled": False,
        "maximum_provider_error_radius_m": None,
        "minimum_segment_frames": 11,
    },
}

SKILLCORNER_POSE_BILATERAL_PARAMETERS: dict[str, Any] = {
    "angles": [
        dict(angle)
        for angle in SKILLCORNER_POSE_PARAMETERS["angles"]
        if angle["name"] in {"left_knee", "right_knee", "left_hip", "right_hip"}
    ],
    "angle_pairs": [
        {"name": "knee_included_angle", "left_angle": "left_knee", "right_angle": "right_knee"},
        {"name": "hip_included_angle", "left_angle": "left_hip", "right_angle": "right_hip"},
    ],
    "derivative": SKILLCORNER_POSE_PARAMETERS["derivative"],
}

POSE_REQUIRED_COLUMNS = [
    "session_id",
    "trial_id",
    "stream_id",
    "subject_id",
    "t_rel_ns",
    "sample_index",
    "joint_id",
    "joint_name",
    "is_available",
    "x_m",
    "y_m",
    "z_m",
    "error_m",
    "nominal_sampling_rate_hz",
]


def _pose_quality_parameters(
    pose_parameters: dict[str, Any],
    expected_joint_names: tuple[str, ...],
) -> dict[str, Any]:
    """Bind quality coverage to the registered skeleton and configured metrics."""
    requirements: dict[str, list[str]] = {}
    for segment in pose_parameters.get("segments", []):
        name = str(segment["name"])
        requirements[f"segment_{name}"] = [
            str(segment["start_landmark"]),
            str(segment["end_landmark"]),
        ]
    for angle in pose_parameters.get("angles", []):
        name = str(angle["name"])
        requirements[f"included_angle_{name}"] = [
            str(angle["vertex_landmark"]),
            str(angle["first_landmark"]),
            str(angle["second_landmark"]),
        ]
    return {
        "expected_joint_names": list(expected_joint_names),
        "metric_requirements": requirements,
        "minimum_derivative_segment_frames": 3,
        "derivative": dict(pose_parameters.get("derivative", {})),
    }


def skillcorner_pose_acceptance(
    settings: Settings,
    engine: Engine,
    *,
    parameters: dict[str, Any] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Accept SkillCorner geometry and cadence-grid Pose quality deterministically."""
    from dynamis.processors.pose import process_pose
    from dynamis.processors.pose_bilateral import process_pose_bilateral
    from dynamis.processors.pose_landmark import process_pose_landmark_kinematics
    from dynamis.processors.pose_quality import process_pose_quality

    resolved = dict(parameters or SKILLCORNER_POSE_PARAMETERS)
    with engine.connect() as connection:
        refs = list_silver_streams(connection, dataset_id=SKILLCORNER_DATASET_ID, modality="pose")
    if not refs:
        raise ValueError(f"{SKILLCORNER_DATASET_ID}: no registered pose streams")

    skeleton_ids = sorted({ref.skeleton_id for ref in refs if ref.skeleton_id is not None})
    if len(skeleton_ids) != 1 or len(skeleton_ids) != len({ref.skeleton_id for ref in refs}):
        raise ValueError("SkillCorner Pose streams must declare one registered skeleton authority")
    with engine.connect() as connection:
        skeleton_rows = connection.execute(
            sa.select(
                SKELETON_JOINT_TABLE.c.skeleton_id,
                SKELETON_JOINT_TABLE.c.joint_id,
                SKELETON_JOINT_TABLE.c.joint_name,
            )
            .where(SKELETON_JOINT_TABLE.c.skeleton_id.in_(skeleton_ids))
            .order_by(SKELETON_JOINT_TABLE.c.skeleton_id, SKELETON_JOINT_TABLE.c.joint_id)
        ).fetchall()
    skeleton_names: dict[str, list[str]] = {skeleton_id: [] for skeleton_id in skeleton_ids}
    for row in skeleton_rows:
        skeleton_names[row.skeleton_id].append(row.joint_name)
    for ref in refs:
        if ref.skeleton_id is None or not skeleton_names.get(ref.skeleton_id):
            raise ValueError(f"{ref.stream_id}: registered Pose skeleton has no joint definitions")

    def execute(ref: SilverStreamRef) -> tuple[Any, ...]:
        table, processor_input = load_silver(settings, ref, columns=POSE_REQUIRED_COLUMNS)
        result = process_pose(table, parameters=resolved)
        run = execute_processor(
            settings,
            result=result,
            dataset_id=SKILLCORNER_DATASET_ID,
            inputs=(processor_input,),
            series_key=ref.stream_id,
            engine=engine,
        )
        quality_result = process_pose_quality(
            table,
            parameters=_pose_quality_parameters(
                resolved,
                tuple(skeleton_names[ref.skeleton_id or ""]),
            ),
        )
        quality_run = execute_processor(
            settings,
            result=quality_result,
            dataset_id=SKILLCORNER_DATASET_ID,
            inputs=(processor_input,),
            series_key=ref.stream_id,
            engine=engine,
        )
        bilateral_result = process_pose_bilateral(
            table,
            parameters=SKILLCORNER_POSE_BILATERAL_PARAMETERS,
        )
        bilateral_run = execute_processor(
            settings,
            result=bilateral_result,
            dataset_id=SKILLCORNER_DATASET_ID,
            inputs=(processor_input,),
            series_key=ref.stream_id,
            engine=engine,
        )
        landmark_result = process_pose_landmark_kinematics(
            table,
            parameters=SKILLCORNER_POSE_LANDMARK_PARAMETERS,
        )
        landmark_run = execute_processor(
            settings,
            result=landmark_result,
            dataset_id=SKILLCORNER_DATASET_ID,
            inputs=(processor_input,),
            series_key=ref.stream_id,
            engine=engine,
        )
        return (
            run,
            result,
            quality_run,
            quality_result,
            bilateral_run,
            bilateral_result,
            landmark_run,
            landmark_result,
            table,
        )

    first_checksums: dict[str, str] = {}
    run_ids: set[str] = set()
    per_stream: list[dict[str, Any]] = []
    metric_values: dict[str, list[float]] = {}
    for index, ref in enumerate(refs):
        (
            run,
            result,
            quality_run,
            quality_result,
            bilateral_run,
            bilateral_result,
            landmark_run,
            landmark_result,
            table,
        ) = execute(ref)
        for processor_name, processor_run in (
            ("kinematics", run),
            ("quality", quality_run),
            ("bilateral", bilateral_run),
            ("landmark", landmark_run),
        ):
            run_ids.add(processor_run.run_id)
            for series in processor_run.series:
                first_checksums[f"{ref.stream_id}:{processor_name}:{series.name}"] = (
                    series.artifact.checksum_sha256
                )
        per_stream.append(
            {
                "stream_id": ref.stream_id,
                "rows": int(table.num_rows),
                "frames": result.diagnostics["frames"],
                "entities": result.diagnostics["entities"],
                "metrics": len(result.metrics)
                + len(quality_result.metrics)
                + len(bilateral_result.metrics)
                + len(landmark_result.metrics),
                "quality_expected_frames": quality_result.diagnostics["expected_frames"],
                "skeleton_id": ref.skeleton_id,
                "series_checksums": {
                    f"kinematics:{series.name}": series.artifact.checksum_sha256
                    for series in run.series
                }
                | {
                    f"quality:{series.name}": series.artifact.checksum_sha256
                    for series in quality_run.series
                }
                | {
                    f"bilateral:{series.name}": series.artifact.checksum_sha256
                    for series in bilateral_run.series
                }
                | {
                    f"landmark:{series.name}": series.artifact.checksum_sha256
                    for series in landmark_run.series
                },
            }
        )
        for metric in (
            *result.metrics,
            *quality_result.metrics,
            *bilateral_result.metrics,
            *landmark_result.metrics,
        ):
            metric_values.setdefault(metric.declaration.metric_id, []).append(metric.value)
        del table
        if progress is not None:
            progress(index + 1, len(refs))

    rerun_matches = 0
    rerun_run_ids: set[str] = set()
    for ref in refs:
        run, _, quality_run, _, bilateral_run, _, landmark_run, _, table = execute(ref)
        for processor_name, processor_run in (
            ("kinematics", run),
            ("quality", quality_run),
            ("bilateral", bilateral_run),
            ("landmark", landmark_run),
        ):
            rerun_run_ids.add(processor_run.run_id)
            for series in processor_run.series:
                if (
                    series.artifact.checksum_sha256
                    == first_checksums[f"{ref.stream_id}:{processor_name}:{series.name}"]
                ):
                    rerun_matches += 1
        del table
    receipt = {
        "dataset_id": SKILLCORNER_DATASET_ID,
        "algorithms": [
            "pose.translation_invariant_kinematics",
            "pose.analysis_quality",
            "pose.bilateral_geometry",
            "pose.landmark_kinematics",
        ],
        "configurations": {
            "pose.translation_invariant_kinematics": resolved,
            "pose.analysis_quality": "registered skeleton names and geometry requirements",
            "pose.bilateral_geometry": SKILLCORNER_POSE_BILATERAL_PARAMETERS,
            "pose.landmark_kinematics": SKILLCORNER_POSE_LANDMARK_PARAMETERS,
        },
        "streams": len(refs),
        "runs": len(run_ids),
        "rerun_series_matches": rerun_matches,
        "rerun_run_ids_stable": run_ids == rerun_run_ids,
        "per_stream": per_stream,
        "metric_summaries": {
            metric_id: {
                "n": len(values),
                "min": float(min(values)),
                "max": float(max(values)),
                "mean": float(sum(values) / len(values)),
            }
            for metric_id, values in sorted(metric_values.items())
        },
        "conventions": {
            "translation_invariance": "relative_vectors_only",
            "parent_tree_created": False,
            "absolute_height_interpretation": "none",
            "provider_z_semantics": (
                "SkillCorner Z is relative to the player centroid and not registered in "
                "the pitch frame; only within-frame landmark differences are used"
            ),
            "error_radius_semantics": (
                "provider error_m is a 90th-percentile predicted error radius; the "
                "reported bound is a worst-case additive bound, not a confidence interval"
            ),
        },
    }
    target = receipt_path(
        settings,
        dataset_id=SKILLCORNER_DATASET_ID,
        kind="acceptance",
        name="res111-pose-analysis-quality",
    )
    atomic_write_text(target, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    receipt["receipt_path"] = relative_posix(settings.dataset_root, target)
    return receipt


DATUM_INFERENCE_NOTE = (
    "The provider does not declare a geodetic datum for the Women's GNSS release. The "
    "pipeline interpretation is WGS 84 recorded as a documented inference; no datum "
    "transformation is applied and source coordinates pass through unchanged."
)


def _optional_float_array(column: Any) -> Any:
    """Column values as float64 with missing values mapped to NaN."""
    import numpy as np

    return np.asarray(
        [float(value) if value is not None else float("nan") for value in column.to_pylist()],
        dtype=np.float64,
    )


def womens_gnss_acceptance(
    settings: Settings,
    engine: Engine,
    *,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Process the Women's GNSS corpus and compare derived speed to source speed."""
    import numpy as np

    from dynamis.processors.locomotor import process_locomotor

    with engine.connect() as connection:
        refs = list_silver_streams(connection, dataset_id=WOMENS_DATASET_ID, modality="gnss")
    if not refs:
        raise ValueError(f"{WOMENS_DATASET_ID}: no registered GNSS streams to process")

    pooled_derived: list[np.ndarray] = []
    pooled_source: list[np.ndarray] = []
    per_stream: list[dict[str, Any]] = []
    checksums: dict[str, str] = {}
    run_ids: set[str] = set()
    metric_totals: dict[str, list[float]] = {}

    def execute(ref: SilverStreamRef) -> tuple[Any, Any, ProcessorRunResult]:
        table, processor_input = load_silver(settings, ref)
        result = process_locomotor(table, parameters=WOMENS_GEODETIC_PARAMETERS)
        run = execute_processor(
            settings,
            result=result,
            dataset_id=WOMENS_DATASET_ID,
            inputs=(processor_input,),
            series_key=ref.stream_id,
            engine=engine,
        )
        return table, result, run

    first_pass: dict[str, ProcessorRunResult] = {}
    for index, ref in enumerate(refs):
        table, result, run = execute(ref)
        derived_speed = _optional_float_array(result.series[0].table.column("speed_m_s"))
        source_speed = _optional_float_array(table.column("speed_m_s"))
        finite = np.isfinite(derived_speed) & np.isfinite(source_speed)
        pooled_derived.append(derived_speed[finite])
        pooled_source.append(source_speed[finite])
        per_stream.append(
            {
                "stream_id": ref.stream_id,
                "samples": int(table.num_rows),
                "paired_samples": int(np.count_nonzero(finite)),
            }
        )
        for metric in result.metrics:
            metric_totals.setdefault(metric.declaration.metric_id, []).append(metric.value)
        first_pass[ref.stream_id] = run
        checksums[ref.stream_id] = run.series[0].artifact.checksum_sha256
        run_ids.add(run.run_id)
        del table
        if progress is not None:
            progress(index + 1, len(refs))

    # Deterministic rerun over the same verified Silver inputs.
    rerun_matches = 0
    rerun_run_ids: set[str] = set()
    for ref in refs:
        _, _, rerun = execute(ref)
        rerun_run_ids.add(rerun.run_id)
        if rerun.series[0].artifact.checksum_sha256 == checksums[ref.stream_id]:
            rerun_matches += 1

    derived_all = np.concatenate(pooled_derived) if pooled_derived else np.zeros(0)
    source_all = np.concatenate(pooled_source) if pooled_source else np.zeros(0)
    comparison = paired_comparison(derived_all, source_all)
    payload = comparison.to_dict()
    payload.update(
        {
            "paired_samples": int(derived_all.size),
            "comparison_scope": (
                "dense per-sample comparison of pipeline-derived speed and the source "
                "speed channel over each player's full stream"
            ),
            "bland_altman_omitted": (
                "per-sample speeds within a time series are strongly autocorrelated, so "
                "Bland-Altman limits would overstate the independent sample size"
            ),
            "interchangeability_claimed": False,
            "reference_semantics": (
                "source speed is a provider SOURCE_DERIVED channel; agreement does not "
                "establish interchangeability with pipeline-derived speed"
            ),
            "verdict": None,
        }
    )
    receipt = {
        "dataset_id": WOMENS_DATASET_ID,
        "algorithm_id": first_pass[refs[0].stream_id].spec.algorithm_id,
        "algorithm_version": first_pass[refs[0].stream_id].spec.version,
        "parameters_hash": first_pass[refs[0].stream_id].parameters_hash,
        "code_git_sha": first_pass[refs[0].stream_id].code_git_sha,
        "parameters": WOMENS_GEODETIC_PARAMETERS,
        "datum_inference": DATUM_INFERENCE_NOTE,
        "streams": len(refs),
        "runs": len(run_ids),
        "rerun_series_matches": rerun_matches,
        "rerun_run_ids_stable": run_ids == rerun_run_ids,
        "per_stream": per_stream,
        "speed_comparison": payload,
        "aggregate_metrics": {
            metric_id: {
                "sum": float(sum(values)),
                "mean": float(sum(values) / len(values)),
                "n": len(values),
            }
            for metric_id, values in sorted(metric_totals.items())
        },
    }
    target = receipt_path(
        settings, dataset_id=WOMENS_DATASET_ID, kind="acceptance", name="res100-womens-gnss"
    )
    atomic_write_text(target, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    receipt["receipt_path"] = relative_posix(settings.dataset_root, target)
    return receipt


def corpus_acceptance(
    settings: Settings,
    engine: Engine,
    *,
    dataset_id: str,
    modality: str,
    processor: Callable[[Any], Any],
    parameters: dict[str, Any],
    kind: str,
    extra: dict[str, Any] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Process one canonical corpus, prove deterministic reruns, seal the receipt."""
    plan = StreamProcessorPlan(dataset_id=dataset_id, modality=modality, processor=processor)
    first = process_corpus(settings, engine, plan=plan, progress=progress)
    second = process_corpus(settings, engine, plan=plan)
    rerun_matches = sum(
        1
        for key, checksum in first.series_checksums.items()
        if second.series_checksums.get(key) == checksum
    )
    receipt: dict[str, Any] = {
        "dataset_id": dataset_id,
        "modality": modality,
        "algorithm_id": first.algorithm_id,
        "algorithm_version": first.algorithm_version,
        "parameters_hash": first.parameters_hash,
        "code_git_sha": first.code_git_sha,
        "configuration": parameters,
        "streams": first.streams,
        "runs": first.runs,
        "series_artifacts": len(first.series_checksums),
        "samples": first.diagnostics.get("samples"),
        "entities": first.diagnostics.get("entities"),
        "rerun_series_matches": rerun_matches,
        "rerun_run_ids_stable": first.run_ids == second.run_ids,
        "configuration_semantics": (
            "zones, effort thresholds and rolling windows are explicit supplied run "
            "configuration in SI units; they are not universal scientific constants"
        ),
        "pose_tracking_fusion": False,
        "per_stream": first.diagnostics.get("per_stream"),
    }
    if extra:
        receipt.update(extra)
    target = receipt_path(settings, dataset_id=dataset_id, kind="acceptance", name=kind)
    atomic_write_text(target, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    receipt["receipt_path"] = relative_posix(settings.dataset_root, target)
    return receipt


def tracking_acceptance(
    settings: Settings,
    engine: Engine,
    *,
    dataset_id: str,
    parameters: dict[str, Any],
    kind: str,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Process one tracking corpus with the locomotor processor."""
    from dynamis.processors.locomotor import process_locomotor

    return corpus_acceptance(
        settings,
        engine,
        dataset_id=dataset_id,
        modality="tracking",
        processor=lambda table: process_locomotor(table, parameters=parameters),
        parameters=parameters,
        kind=kind,
        progress=progress,
    )


def white_imu_acceptance(
    settings: Settings,
    engine: Engine,
    *,
    parameters: dict[str, Any] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Process all registered White CMJ accelerometer streams."""
    from dynamis.processors.imu import process_imu

    return corpus_acceptance(
        settings,
        engine,
        dataset_id=WHITE_DATASET_ID,
        modality="imu",
        processor=lambda table: process_imu(table, parameters=parameters),
        parameters=dict(parameters or {}),
        kind="res100-white-imu",
        extra={
            "algorithm_scope": (
                "sensor-frame resultant and explicitly specified derivative features; no "
                "anatomical axis relabelling and no vendor equivalence claim"
            )
        },
        progress=progress,
    )


def white_cross_sensor_acceptance(
    settings: Settings,
    engine: Engine,
    *,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Run the paired force/IMU association diagnostic on persisted sync pairs only."""
    from dynamis.processors.corpus import list_sync_pairs
    from dynamis.processors.cross_sensor import process_cross_sensor

    with engine.connect() as connection:
        pairs = list_sync_pairs(connection, dataset_id=WHITE_DATASET_ID)
        refs = list_silver_streams(connection, dataset_id=WHITE_DATASET_ID)
    by_stream = {ref.stream_id: ref for ref in refs}
    if not pairs:
        raise ValueError(f"{WHITE_DATASET_ID}: no persisted synchronization pairs")

    run_ids: set[str] = set()
    code_sha: str | None = None
    algorithm_id = ""
    algorithm_version = ""
    parameters_hash = ""
    paired_total = 0
    correlations: list[float] = []
    processed = 0
    for index, pair in enumerate(pairs):
        source = by_stream.get(pair.source_stream_id)
        target = by_stream.get(pair.target_stream_id)
        if source is None or target is None:
            raise ValueError(
                f"sync pair references an unregistered stream: {pair.source_stream_id} / "
                f"{pair.target_stream_id}"
            )
        if source.modality == "force" and target.modality == "imu":
            force_ref, imu_ref = source, target
        elif source.modality == "imu" and target.modality == "force":
            force_ref, imu_ref = target, source
        else:
            raise ValueError(
                f"sync pair {pair.source_stream_id}->{pair.target_stream_id} does not join "
                "force and IMU streams"
            )
        force_table, force_input = load_silver(settings, force_ref)
        imu_table, imu_input = load_silver(settings, imu_ref)
        result = process_cross_sensor(imu_table, force_table)
        run = execute_processor(
            settings,
            result=result,
            dataset_id=WHITE_DATASET_ID,
            inputs=(imu_input, force_input),
            series_key=pair.source_stream_id,
            engine=engine,
        )
        run_ids.add(run.run_id)
        code_sha = run.code_git_sha
        algorithm_id = result.spec.algorithm_id
        algorithm_version = result.spec.version
        parameters_hash = result.spec.parameters_hash
        paired_total += int(result.diagnostics["paired_samples"])
        if result.diagnostics["pearson_r"] is not None:
            correlations.append(float(result.diagnostics["pearson_r"]))
        processed += 1
        if progress is not None and (index + 1 == len(pairs) or (index + 1) % 100 == 0):
            progress(index + 1, len(pairs))
    receipt = {
        "dataset_id": WHITE_DATASET_ID,
        "algorithm_id": algorithm_id,
        "algorithm_version": algorithm_version,
        "parameters_hash": parameters_hash,
        "code_git_sha": code_sha,
        "pairs": len(pairs),
        "processed_pairs": processed,
        "runs": len(run_ids),
        "paired_samples_total": paired_total,
        "correlation_pairs": len(correlations),
        "correlation_mean": (
            float(sum(correlations) / len(correlations)) if correlations else None
        ),
        "sync_authority": (
            "only persisted SyncAlignment pairs are processed; no stream is paired by "
            "convention or timing guesswork"
        ),
        "equivalence_claimed": False,
        "interpolation": "none",
    }
    target = receipt_path(
        settings, dataset_id=WHITE_DATASET_ID, kind="acceptance", name="res100-cross-sensor"
    )
    atomic_write_text(target, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    receipt["receipt_path"] = relative_posix(settings.dataset_root, target)
    return receipt


@dataclass(frozen=True, slots=True)
class StreamProcessorPlan:
    """One corpus to process with one pure function."""

    dataset_id: str
    modality: str
    processor: Callable[[Any], Any]
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "modality": self.modality,
            "session_id": self.session_id,
        }


def process_corpus(
    settings: Settings,
    engine: Engine,
    *,
    plan: StreamProcessorPlan,
    progress: Callable[[int, int], None] | None = None,
) -> DatasetProcessing:
    """Process every registered stream of one dataset/modality deterministically."""
    with engine.connect() as connection:
        refs = list_silver_streams(
            connection,
            dataset_id=plan.dataset_id,
            modality=plan.modality,
            session_id=plan.session_id,
        )
    if not refs:
        raise ValueError(f"{plan.dataset_id}/{plan.modality}: no registered streams to process")
    checksums: dict[str, str] = {}
    metric_values: dict[str, float] = {}
    metric_units: dict[str, str] = {}
    run_ids: set[str] = set()
    algorithm_id = ""
    algorithm_version = ""
    parameters_hash = ""
    code_sha: str | None = None
    per_stream: list[dict[str, Any]] = []
    total_samples = 0
    total_entities = 0
    for index, ref in enumerate(refs):
        table, processor_input = load_silver(settings, ref)
        result = plan.processor(table)
        algorithm_id = result.spec.algorithm_id
        algorithm_version = result.spec.version
        parameters_hash = result.spec.parameters_hash
        run = execute_processor(
            settings,
            result=result,
            dataset_id=plan.dataset_id,
            inputs=(processor_input,),
            series_key=ref.stream_id,
            engine=engine,
        )
        run_ids.add(run.run_id)
        code_sha = run.code_git_sha
        for series in run.series:
            checksums[f"{ref.stream_id}.{series.name}"] = series.artifact.checksum_sha256
        for metric in result.metrics:
            key = (
                f"{ref.stream_id}|{metric.declaration.metric_id}|"
                f"{metric.entity_id or ''}|{metric.subject_id or ''}"
            )
            metric_values[key] = metric.value
            metric_units[metric.declaration.metric_id] = metric.declaration.si_unit
        total_samples += int(result.diagnostics.get("samples", 0))
        total_entities += int(result.diagnostics.get("entities", 0))
        per_stream.append(
            {
                "stream_id": ref.stream_id,
                "samples": int(result.diagnostics.get("samples", 0)),
                "entities": int(result.diagnostics.get("entities", 0)),
                "metrics": len(result.metrics),
                "series": {series.name: series.artifact.checksum_sha256 for series in run.series},
            }
        )
        del table
        if progress is not None:
            progress(index + 1, len(refs))
    return DatasetProcessing(
        dataset_id=plan.dataset_id,
        algorithm_id=algorithm_id,
        streams=len(refs),
        runs=len(run_ids),
        series_checksums=checksums,
        metric_values=metric_values,
        metric_units=metric_units,
        processed_stream_ids=tuple(ref.stream_id for ref in refs),
        run_ids=tuple(sorted(run_ids)),
        algorithm_version=algorithm_version,
        parameters_hash=parameters_hash,
        code_git_sha=code_sha,
        diagnostics={
            "samples": total_samples,
            "entities": total_entities,
            "per_stream": per_stream,
        },
    )


__all__ = [
    "DatasetProcessing",
    "StreamProcessorPlan",
    "process_corpus",
    "white_force_acceptance",
]
