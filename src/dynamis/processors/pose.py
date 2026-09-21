"""Deterministic translation-invariant pose kinematics.

Pose remains MODEL_ESTIMATED source data. This processor never builds an
anatomical parent tree and never interprets provider Z as absolute height or
whole-body COM: only differences between named landmarks in the source frame
are used, so every computed vector is translation-invariant.

Every required landmark is named explicitly in the processor parameters:

* a segment is ``end - start`` with its Euclidean length;
* a three-point angle is the angle at the vertex between ``vertex->first`` and
  ``vertex->second``, explicitly defined rather than implied;
* angular velocity is the derivative of the accepted angle series with an
  explicit filter/derivative specification.

A segment or angle is computed only when every required landmark is declared
available and carries finite coordinates; otherwise the result is absent, never
imputed. The provider ``error_m`` field is its 90th-percentile predicted error
radius, not a probability, standard deviation or confidence weight. Error
propagation, when enabled, is a named worst-case additive bound on segment
length (``e_start + e_end``) and is never labelled a confidence interval.

Observed pose may disappear and later resume. Every subject's observed frames
are therefore split into contiguous temporal segments at explicit gaps, and
filter/derivative state restarts at each boundary: no interpolated sample is
invented and no derivative is taken across a gap.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pyarrow as pa

from dynamis.processors.signals import (
    EDGE_NAN,
    DerivativeSpec,
    derivative_variable,
)
from dynamis.processors.spec import (
    MetricDeclaration,
    ProcessorResult,
    ProcessorSpec,
    ScalarMetric,
    SeriesOutput,
)

ALGORITHM_ID = "pose.translation_invariant_kinematics"
ALGORITHM_VERSION = "1.0.0"

ERROR_POLICY_NONE = "none"
ERROR_POLICY_WORST_CASE = "worst_case_additive_radius"
ERROR_POLICIES = (ERROR_POLICY_NONE, ERROR_POLICY_WORST_CASE)

TRANSLATION_INVARIANCE = "relative_vectors_only"
ABSOLUTE_HEIGHT_INTERPRETATION = "none"
PARENT_TREE_CREATED = False

#: Locked V1 temporal-gap policy. Provider pose is observation-limited: a subject
#: may disappear and later resume. Every subject's observed frames are split into
#: contiguous temporal segments at gaps larger than ``max_gap_factor`` times the
#: expected sample step; filtering and differentiation restart at every segment
#: boundary and never cross a gap. There is no interpolation and no imputation.
GAP_POLICY_CONTIGUOUS_SEGMENTS = "contiguous_segments"
GAP_POLICIES = (GAP_POLICY_CONTIGUOUS_SEGMENTS,)
DEFAULT_MAX_GAP_FACTOR = 1.5
GAP_POLICY_SEMANTICS = (
    "Observed pose frames are split into contiguous temporal segments at an observed "
    "step above max_gap_factor * expected step; filter and derivative state restart at "
    "every segment boundary, no value is interpolated and no derivative is taken across "
    "a gap. ROM is the range of observed values and is not a differentiated quantity."
)

DEFAULT_PARAMETERS: dict[str, Any] = {
    "required_coordinate_components": ["x_m", "y_m", "z_m"],
    "segments": [],
    "angles": [],
    "derivative": {
        "filter": {
            "family": "none",
            "order": None,
            "cutoff_hz": None,
            "phase": "zero_phase",
            "padding": "odd",
            "padlen": None,
        },
        "edge_policy": EDGE_NAN,
    },
    "error_policy": ERROR_POLICY_NONE,
    "gap_policy": {
        "strategy": GAP_POLICY_CONTIGUOUS_SEGMENTS,
        "max_gap_factor": DEFAULT_MAX_GAP_FACTOR,
    },
    "translation_invariance": TRANSLATION_INVARIANCE,
    "absolute_height_interpretation": ABSOLUTE_HEIGHT_INTERPRETATION,
    "parent_tree_created": PARENT_TREE_CREATED,
}

ANATOMICAL_SEMANTICS = (
    "Joint names are source landmark names. No anatomical parent tree, no absolute "
    "height and no whole-body COM interpretation is created or claimed."
)
ERROR_RADIUS_SEMANTICS = (
    "provider error_m is a 90th-percentile predicted error radius; the worst-case "
    "additive bound sums the two endpoint radii and is not a confidence interval."
)

SERIES_NAME = "pose_translation_invariant_kinematics"
#: Landmark names are preserved (case included) so a metric id remains a direct
#: reader of the provider landmark vocabulary; only unsafe characters are folded.
_TOKEN = re.compile(r"[^A-Za-z0-9]+")


def _token(value: str) -> str:
    token = _TOKEN.sub("_", value.strip()).strip("_")
    if not token:
        raise ValueError(f"cannot derive a metric token from {value!r}")
    return token


@dataclass(frozen=True, slots=True)
class SegmentDefinition:
    name: str
    start_landmark: str
    end_landmark: str

    @staticmethod
    def from_parameters(parameters: Mapping[str, Any]) -> SegmentDefinition:
        return SegmentDefinition(
            name=str(parameters["name"]),
            start_landmark=str(parameters["start_landmark"]),
            end_landmark=str(parameters["end_landmark"]),
        )


@dataclass(frozen=True, slots=True)
class AngleDefinition:
    name: str
    vertex_landmark: str
    first_landmark: str
    second_landmark: str

    @staticmethod
    def from_parameters(parameters: Mapping[str, Any]) -> AngleDefinition:
        return AngleDefinition(
            name=str(parameters["name"]),
            vertex_landmark=str(parameters["vertex_landmark"]),
            first_landmark=str(parameters["first_landmark"]),
            second_landmark=str(parameters["second_landmark"]),
        )


def _segment_length_declaration(segment: SegmentDefinition) -> MetricDeclaration:
    """Metric declaration for one segment mean length."""
    return MetricDeclaration(
        metric_id=f"pose.segment_length_mean.{_token(segment.name)}",
        name=f"Mean length of segment {segment.name}",
        si_unit="m",
        description=(
            f"Mean Euclidean length of the relative landmark vector "
            f"{segment.end_landmark} - {segment.start_landmark}. {ANATOMICAL_SEMANTICS}"
        ),
    )


def _segment_error_bound_declaration(segment: SegmentDefinition) -> MetricDeclaration:
    """Metric declaration for one segment worst-case error bound."""
    return MetricDeclaration(
        metric_id=f"pose.segment_length_error_bound.{_token(segment.name)}",
        name=f"Worst-case segment length error bound for {segment.name}",
        si_unit="m",
        description=(
            f"Maximum worst-case additive bound (e_start + e_end) on the "
            f"{segment.name} segment length over frames where both landmarks are "
            f"available. {ERROR_RADIUS_SEMANTICS}"
        ),
    )


def _landmark_availability_declaration(landmark: str) -> MetricDeclaration:
    """Metric declaration for one landmark availability fraction."""
    return MetricDeclaration(
        metric_id=f"pose.availability.{_token(landmark)}",
        name=f"Available-frame fraction for landmark {landmark}",
        si_unit="1",
        description=f"Fraction of entity frames where {landmark} is available and finite.",
    )


def _landmark_error_declaration(landmark: str) -> MetricDeclaration:
    """Metric declaration for one landmark mean provider error radius."""
    return MetricDeclaration(
        metric_id=f"pose.error_radius_mean.{_token(landmark)}",
        name=f"Mean provider error radius for landmark {landmark}",
        si_unit="m",
        description=(
            f"Mean provider error_m over frames where {landmark} is available. "
            f"{ERROR_RADIUS_SEMANTICS}"
        ),
    )


def _angle_rom_declaration(angle: AngleDefinition) -> MetricDeclaration:
    """Metric declaration for one angle range of motion."""
    return MetricDeclaration(
        metric_id=f"pose.angular_rom.{_token(angle.name)}",
        name=f"Range of motion for angle {angle.name}",
        si_unit="rad",
        description=(
            f"max - min of the {angle.name} angle at {angle.vertex_landmark} between "
            f"{angle.vertex_landmark}->{angle.first_landmark} and "
            f"{angle.vertex_landmark}->{angle.second_landmark} over available frames."
        ),
    )


def _angle_velocity_peak_declaration(angle: AngleDefinition) -> MetricDeclaration:
    """Metric declaration for one angle peak angular velocity."""
    return MetricDeclaration(
        metric_id=f"pose.angular_velocity_peak.{_token(angle.name)}",
        name=f"Peak angular velocity for angle {angle.name}",
        si_unit="rad/s",
        description=f"Maximum absolute derivative of the {angle.name} angle series.",
    )


def _angle_velocity_rms_declaration(angle: AngleDefinition) -> MetricDeclaration:
    """Metric declaration for one angle RMS angular velocity."""
    return MetricDeclaration(
        metric_id=f"pose.angular_velocity_rms.{_token(angle.name)}",
        name=f"RMS angular velocity for angle {angle.name}",
        si_unit="rad/s",
        description=f"Root-mean-square derivative of the {angle.name} angle series.",
    )


def pose_spec(parameters: Mapping[str, Any] | None = None) -> ProcessorSpec:
    """Resolve and validate the pose processor parameters."""
    resolved = {**DEFAULT_PARAMETERS, **dict(parameters or {})}
    components = tuple(str(item) for item in resolved["required_coordinate_components"])
    if components != ("x_m", "y_m", "z_m"):
        raise ValueError(
            "required_coordinate_components must remain ('x_m', 'y_m', 'z_m'); a partial "
            "component set would silently change every geometry definition"
        )
    if resolved["translation_invariance"] != TRANSLATION_INVARIANCE:
        raise ValueError("translation_invariance must remain 'relative_vectors_only'")
    if resolved["absolute_height_interpretation"] != ABSOLUTE_HEIGHT_INTERPRETATION:
        raise ValueError("absolute_height_interpretation must remain 'none'")
    if resolved["parent_tree_created"] is not PARENT_TREE_CREATED:
        raise ValueError("parent_tree_created must remain False")
    if resolved["error_policy"] not in ERROR_POLICIES:
        raise ValueError(f"unknown error_policy {resolved['error_policy']!r}")
    gap_policy = dict(resolved["gap_policy"])
    strategy = str(gap_policy.get("strategy", ""))
    if strategy != GAP_POLICY_CONTIGUOUS_SEGMENTS:
        raise ValueError(
            f"gap_policy.strategy must remain {GAP_POLICY_CONTIGUOUS_SEGMENTS!r}; "
            "differentiating across an observation gap would fabricate motion"
        )
    max_gap_factor = float(gap_policy.get("max_gap_factor", DEFAULT_MAX_GAP_FACTOR))
    if not math.isfinite(max_gap_factor) or max_gap_factor < 1.0:
        raise ValueError("gap_policy.max_gap_factor must be a finite factor of at least 1.0")
    resolved["gap_policy"] = {
        "strategy": strategy,
        "max_gap_factor": max_gap_factor,
    }
    segments = tuple(SegmentDefinition.from_parameters(item) for item in resolved["segments"])
    angles = tuple(AngleDefinition.from_parameters(item) for item in resolved["angles"])
    if not segments and not angles:
        raise ValueError("at least one segment or angle definition is required")
    required = sorted(
        {
            landmark
            for segment in segments
            for landmark in (segment.start_landmark, segment.end_landmark)
        }
        | {
            landmark
            for angle in angles
            for landmark in (
                angle.vertex_landmark,
                angle.first_landmark,
                angle.second_landmark,
            )
        }
    )
    tokens = [_token(definition.name) for definition in (*segments, *angles)]
    if len(set(tokens)) != len(tokens):
        raise ValueError("segment/angle names must map to unique metric tokens")
    DerivativeSpec.from_parameters(dict(resolved["derivative"]))
    resolved["segments"] = [asdict(segment) for segment in segments]
    resolved["angles"] = [asdict(angle) for angle in angles]
    resolved["required_landmarks"] = required
    return ProcessorSpec(
        algorithm_id=ALGORITHM_ID,
        name="Translation-invariant pose kinematics",
        version=ALGORITHM_VERSION,
        description=(
            "Relative segment vectors/lengths and explicitly defined three-point angles "
            "with ROM and explicitly specified angular velocity. Required landmarks are "
            "named in parameters, unavailable landmarks produce no result, no parent tree "
            "is created, provider Z is never interpreted as absolute height, and "
            "filter/derivative state restarts at every contiguous temporal segment."
        ),
        parameters=resolved,
    )


def _entity_arrays(
    table: pa.Table,
    *,
    subject: str | None,
    required_landmarks: tuple[str, ...],
) -> tuple[np.ndarray, dict[str, dict[str, np.ndarray]]]:
    """Pivot one entity's long pose rows into per-landmark frame arrays."""
    from dynamis.quality import arrow_kernels as kernels

    selected = table
    if subject is not None:
        selected = table.filter(kernels.equal(table.column("subject_id"), subject))
    names = selected.column("joint_name").to_pylist()
    times = np.asarray(selected.column("t_rel_ns").to_numpy(zero_copy_only=False), dtype=np.int64)
    frame_keys, frame_index = np.unique(times, return_inverse=True)
    frames = frame_keys.size
    per_landmark: dict[str, dict[str, np.ndarray]] = {
        name: {
            "x": np.full(frames, np.nan),
            "y": np.full(frames, np.nan),
            "z": np.full(frames, np.nan),
            "available": np.zeros(frames, dtype=bool),
            "error": np.full(frames, np.nan),
        }
        for name in required_landmarks
    }
    x = np.asarray(selected.column("x_m").to_numpy(zero_copy_only=False), dtype=np.float64)
    y = np.asarray(selected.column("y_m").to_numpy(zero_copy_only=False), dtype=np.float64)
    z = np.asarray(selected.column("z_m").to_numpy(zero_copy_only=False), dtype=np.float64)
    available = np.asarray(
        selected.column("is_available").to_numpy(zero_copy_only=False), dtype=bool
    )
    error = np.asarray(selected.column("error_m").to_numpy(zero_copy_only=False), dtype=np.float64)
    for row, name in enumerate(names):
        target = per_landmark.get(name)
        if target is None:
            continue
        frame = int(frame_index[row])
        if not bool(available[row]):
            continue
        if not (math.isfinite(x[row]) and math.isfinite(y[row]) and math.isfinite(z[row])):
            continue
        target["x"][frame] = x[row]
        target["y"][frame] = y[row]
        target["z"][frame] = z[row]
        target["available"][frame] = True
        if math.isfinite(error[row]):
            target["error"][frame] = error[row]
    return frame_keys, per_landmark


def process_pose(
    table: pa.Table,
    *,
    parameters: Mapping[str, Any] | None = None,
) -> ProcessorResult:
    """Compute translation-invariant pose kinematics for one pose stream."""
    spec = pose_spec(parameters)
    segments = tuple(
        SegmentDefinition.from_parameters(item) for item in spec.parameters["segments"]
    )
    angles = tuple(AngleDefinition.from_parameters(item) for item in spec.parameters["angles"])
    required = tuple(str(item) for item in spec.parameters["required_landmarks"])
    derivative_spec = DerivativeSpec.from_parameters(dict(spec.parameters["derivative"]))
    error_policy = str(spec.parameters["error_policy"])
    gap_policy = dict(spec.parameters["gap_policy"])
    max_gap_factor = float(gap_policy["max_gap_factor"])
    for name in ("t_rel_ns", "joint_name", "is_available", "x_m", "y_m", "z_m"):
        if name not in table.column_names:
            raise ValueError(f"{ALGORITHM_ID}: required column {name!r} is absent")

    subjects = sorted(
        {str(value) for value in table.column("subject_id").to_pylist() if value is not None}
    )
    if not subjects:
        raise ValueError(f"{ALGORITHM_ID}: a pose stream requires subject identity")
    if len(subjects) == 1:
        subjects = [subjects[0]]
    observations = table.column("joint_name").to_pylist()
    missing = sorted(set(required) - set(observations))
    if missing:
        raise ValueError(
            f"{ALGORITHM_ID}: required landmark(s) {missing} are not present in the stream"
        )

    metrics: list[ScalarMetric] = []
    series_parts: list[pa.Table] = []
    total_frames = 0
    for subject in subjects:
        frames, per_landmark = _entity_arrays(table, subject=subject, required_landmarks=required)
        total_frames += frames.size
        rate_hz = _rate_hz(table, frames)
        temporal_segments = _contiguous_segments(
            frames,
            rate_hz=rate_hz,
            max_gap_factor=max_gap_factor,
        )
        gap_policy_provenance = {
            "strategy": GAP_POLICY_CONTIGUOUS_SEGMENTS,
            "max_gap_factor": max_gap_factor,
            "pose_segments": len(temporal_segments),
            "semantics": GAP_POLICY_SEMANTICS,
        }
        scope = {
            "session_id": table.column("session_id")[0].as_py(),
            "subject_id": subject,
            "trial_id": table.column("trial_id")[0].as_py(),
            "stream_id": table.column("stream_id")[0].as_py(),
        }
        provenance = {
            "entity_id": subject,
            "frames": int(frames.size),
            "required_landmarks": list(required),
            "error_policy": error_policy,
            "error_radius_semantics": ERROR_RADIUS_SEMANTICS,
            "absolute_height_interpretation": ABSOLUTE_HEIGHT_INTERPRETATION,
            "parent_tree_created": PARENT_TREE_CREATED,
            "translation_invariance": TRANSLATION_INVARIANCE,
            "gap_policy": gap_policy_provenance,
            "derivative": derivative_spec.parameters(),
        }
        for name in required:
            availability = float(np.count_nonzero(per_landmark[name]["available"]))
            fraction = availability / frames.size if frames.size else 0.0
            metrics.append(
                ScalarMetric(
                    declaration=_landmark_availability_declaration(name),
                    value=fraction,
                    entity_id=subject,
                    provenance=provenance,
                    **scope,
                )
            )
            error = per_landmark[name]["error"]
            finite_error = error[np.isfinite(error)]
            if finite_error.size:
                metrics.append(
                    ScalarMetric(
                        declaration=_landmark_error_declaration(name),
                        value=float(np.mean(finite_error)),
                        entity_id=subject,
                        provenance=provenance,
                        **scope,
                    )
                )

        columns: dict[str, pa.Array] = {
            "entity_id": pa.array([subject] * frames.size, type=pa.string()),
            "t_rel_ns": pa.array(frames, type=pa.int64()),
            "segment_index": _segment_index_column(frames, temporal_segments),
        }
        for segment in segments:
            start = per_landmark[segment.start_landmark]
            end = per_landmark[segment.end_landmark]
            valid = start["available"] & end["available"]
            vector = np.stack(
                [end["x"] - start["x"], end["y"] - start["y"], end["z"] - start["z"]], axis=1
            )
            length = np.linalg.norm(vector, axis=1)
            length = np.where(valid, length, np.nan)
            token = _token(segment.name)
            columns[f"segment_{token}_length_m"] = pa.array(length, type=pa.float64())
            finite = length[np.isfinite(length)]
            if finite.size:
                metrics.append(
                    ScalarMetric(
                        declaration=_segment_length_declaration(segment),
                        value=float(np.mean(finite)),
                        entity_id=subject,
                        provenance=provenance,
                        **scope,
                    )
                )
            if error_policy == ERROR_POLICY_WORST_CASE:
                bound = start["error"] + end["error"]
                bound = np.where(valid & np.isfinite(bound), bound, np.nan)
                columns[f"segment_{token}_error_bound_m"] = pa.array(bound, type=pa.float64())
                finite_bound = bound[np.isfinite(bound)]
                if finite_bound.size:
                    metrics.append(
                        ScalarMetric(
                            declaration=_segment_error_bound_declaration(segment),
                            value=float(np.max(finite_bound)),
                            entity_id=subject,
                            provenance=provenance,
                            **scope,
                        )
                    )
        for angle in angles:
            vertex = per_landmark[angle.vertex_landmark]
            first = per_landmark[angle.first_landmark]
            second = per_landmark[angle.second_landmark]
            valid = vertex["available"] & first["available"] & second["available"]
            u = np.stack(
                [first["x"] - vertex["x"], first["y"] - vertex["y"], first["z"] - vertex["z"]],
                axis=1,
            )
            v = np.stack(
                [second["x"] - vertex["x"], second["y"] - vertex["y"], second["z"] - vertex["z"]],
                axis=1,
            )
            norm_u = np.linalg.norm(u, axis=1)
            norm_v = np.linalg.norm(v, axis=1)
            dot = np.sum(u * v, axis=1)
            denominator = norm_u * norm_v
            valid = valid & (denominator > 0) & np.isfinite(denominator)
            cosine = np.where(valid, dot / np.where(denominator == 0, np.nan, denominator), np.nan)
            angle_series = np.where(valid, np.arccos(np.clip(cosine, -1.0, 1.0)), np.nan)
            token = _token(angle.name)
            columns[f"angle_{token}_rad"] = pa.array(angle_series, type=pa.float64())
            finite = angle_series[np.isfinite(angle_series)]
            # Filter and derivative state restart at every contiguous segment
            # boundary: no sample is interpolated and no difference spans a gap.
            velocity = np.full(frames.size, np.nan)
            for start, stop in temporal_segments:
                if stop - start < 2:
                    continue
                try:
                    filtered_angle = derivative_spec.filter.apply(
                        angle_series[start:stop], rate_hz=rate_hz
                    )
                    velocity[start:stop] = derivative_variable(
                        filtered_angle,
                        frames[start:stop],
                        edge_policy=derivative_spec.edge_policy,
                    )
                except ValueError:
                    continue
            columns[f"angular_velocity_{token}_rad_s"] = pa.array(velocity, type=pa.float64())
            if finite.size >= 2:
                metrics.append(
                    ScalarMetric(
                        declaration=_angle_rom_declaration(angle),
                        value=float(np.max(finite) - np.min(finite)),
                        entity_id=subject,
                        provenance=provenance,
                        **scope,
                    )
                )
                finite_velocity = velocity[np.isfinite(velocity)]
                if finite_velocity.size:
                    metrics.append(
                        ScalarMetric(
                            declaration=_angle_velocity_peak_declaration(angle),
                            value=float(np.max(np.abs(finite_velocity))),
                            entity_id=subject,
                            provenance=provenance,
                            **scope,
                        )
                    )
                    metrics.append(
                        ScalarMetric(
                            declaration=_angle_velocity_rms_declaration(angle),
                            value=float(np.sqrt(np.mean(finite_velocity**2))),
                            entity_id=subject,
                            provenance=provenance,
                            **scope,
                        )
                    )
        series_parts.append(pa.table(columns))
    series = (
        pa.concat_tables(series_parts)
        if len(series_parts) > 1
        else (series_parts[0] if series_parts else None)
    )
    outputs: list[SeriesOutput] = []
    if series is not None:
        outputs.append(
            SeriesOutput(
                name=SERIES_NAME,
                table=series,
                description=(
                    "Per-frame translation-invariant segment lengths and three-point angles "
                    "with their explicit angular velocities."
                ),
            )
        )
    return ProcessorResult(
        spec=spec,
        metrics=tuple(metrics),
        series=tuple(outputs),
        diagnostics={
            "entities": len(subjects),
            "frames": total_frames,
            "required_landmarks": list(required),
            "error_policy": error_policy,
            "gap_policy": {
                "strategy": GAP_POLICY_CONTIGUOUS_SEGMENTS,
                "max_gap_factor": max_gap_factor,
                "semantics": GAP_POLICY_SEMANTICS,
            },
            "parent_tree_created": PARENT_TREE_CREATED,
            "absolute_height_interpretation": ABSOLUTE_HEIGHT_INTERPRETATION,
        },
    )


def _contiguous_segments(
    frames: np.ndarray,
    *,
    rate_hz: float,
    max_gap_factor: float,
) -> tuple[tuple[int, int], ...]:
    """Split observed frames into contiguous temporal segments.

    A boundary exists where the observed step exceeds ``max_gap_factor`` times
    the expected step. The expected step is the declared/measured sampling period
    when one is resolvable; a series with fewer than two frames is one segment.
    """
    if frames.size <= 1:
        return ((0, int(frames.size)),)
    if rate_hz > 0:
        expected_step_ns = 1e9 / rate_hz
    else:
        expected_step_ns = float(np.median(np.diff(frames)))
    if not math.isfinite(expected_step_ns) or expected_step_ns <= 0:
        return ((0, int(frames.size)),)
    breaks = np.flatnonzero(np.diff(frames) > max_gap_factor * expected_step_ns) + 1
    bounds = (0, *breaks.tolist(), int(frames.size))
    return tuple((int(bounds[index]), int(bounds[index + 1])) for index in range(len(bounds) - 1))


def _segment_index_column(frames: np.ndarray, segments: tuple[tuple[int, int], ...]) -> pa.Array:
    """Per-frame contiguous-segment index, so consumers can see the gaps."""
    values = np.zeros(frames.size, dtype=np.int32)
    for index, (start, stop) in enumerate(segments):
        values[start:stop] = index
    return pa.array(values, type=pa.int32())


def _rate_hz(table: pa.Table, frames: np.ndarray) -> float:
    if "nominal_sampling_rate_hz" in table.column_names:
        declared = table.column("nominal_sampling_rate_hz")[0].as_py()
        if declared is not None and math.isfinite(float(declared)) and float(declared) > 0:
            return float(declared)
    if frames.size >= 2:
        steps = np.diff(frames).astype(np.float64) / 1e9
        if np.all(steps > 0):
            return float(1.0 / np.median(steps))
    # No usable rate: acceptable only while no filter is configured, because the
    # filter application itself enforces a positive sampling rate.
    return 0.0


__all__ = [
    "ABSOLUTE_HEIGHT_INTERPRETATION",
    "ALGORITHM_ID",
    "ALGORITHM_VERSION",
    "DEFAULT_MAX_GAP_FACTOR",
    "ERROR_POLICY_NONE",
    "ERROR_POLICY_WORST_CASE",
    "GAP_POLICIES",
    "GAP_POLICY_CONTIGUOUS_SEGMENTS",
    "GAP_POLICY_SEMANTICS",
    "PARENT_TREE_CREATED",
    "TRANSLATION_INVARIANCE",
    "AngleDefinition",
    "SegmentDefinition",
    "pose_spec",
    "process_pose",
]
