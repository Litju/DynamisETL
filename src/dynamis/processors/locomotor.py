"""Deterministic locomotor processor for planar tracking and geodetic GNSS.

Every choice that can change a metric is an explicit, versioned parameter:
position domain, distance method, ENU method and earth radius, filter family/
order/cutoff/phase/padding, derivative edge policy, speed zones (SI), effort
threshold/minimum duration/merge gap/hysteresis, rolling windows and the
incomplete-edge policy. Nothing is interpolated or resampled silently: the
``resample_method`` and ``interpolation`` parameters exist and must remain
``none`` for this revision.

Two position domains are supported and they are not interchangeable:

* ``planar``: positions already live in a declared planar frame (pitch-centred
  tracking). Distance is the planar path length and kinematics come from the
  same planar axes;
* ``geodetic``: positions are WGS 84 geodetic degrees. Distance is the explicit
  haversine method with a declared mean radius, while local kinematics use an
  explicit equirectangular tangent-plane ENU projection with a per-entity
  origin. The datum is the pipeline's documented inference for the Women's
  release, never a provider declaration, and is recorded in acceptance receipts.

Filtering (when enabled) is applied to the kinematic coordinate components only;
it never changes the geodesic/planar distance, and the applied filter is fully
described by its parameters and recorded in the metric provenance.

Metric identity carries the entity id as well as the stream id, so a
multi-object tracking stream produces one metric row per object without
collisions.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pyarrow as pa

from dynamis.processors.signals import (
    DISTANCE_METHOD_HAVERSINE,
    DISTANCE_METHOD_PLANAR,
    EDGE_DROP_INCOMPLETE,
    EDGE_NAN,
    ENU_METHOD_EQUIRECTANGULAR,
    ROLLING_EDGE_POLICIES,
    WGS84_MEAN_RADIUS_M,
    DerivativeSpec,
    EffortParameters,
    SpeedZone,
    derivative_variable,
    effort_segments,
    enu_from_geodetic,
    haversine_distance_m,
    rolling_peak_window,
    sample_durations_s,
    steps_s,
    zone_statistics,
)
from dynamis.processors.spec import (
    MetricDeclaration,
    ProcessorResult,
    ProcessorSpec,
    ScalarMetric,
    SeriesOutput,
)

ALGORITHM_ID = "locomotor.speed_effort_kinematics"
ALGORITHM_VERSION = "1.0.0"

POSITION_DOMAIN_PLANAR = "planar"
POSITION_DOMAIN_GEODETIC = "geodetic"
POSITION_DOMAINS = (POSITION_DOMAIN_PLANAR, POSITION_DOMAIN_GEODETIC)

ENTITY_GROUPING_OBJECT = "object_id_when_present"
ENTITY_GROUPING_STREAM = "whole_stream"
ENTITY_GROUPINGS = (ENTITY_GROUPING_OBJECT, ENTITY_GROUPING_STREAM)

RESAMPLE_NONE = "none"
INTERPOLATION_NONE = "none"

FILTER_APPLIES_KINEMATICS_ONLY = "kinematics_only"

DETECTION_GATE_NONE = "none"
DETECTION_GATE_REQUIRE = "require_is_detected"
DETECTION_GATES = (DETECTION_GATE_NONE, DETECTION_GATE_REQUIRE)

STEP_SPEED_GATE_KINEMATICS_ONLY = "kinematics_only"

STEP_GATE_KEEP_DISTANCE = "keep_step_in_distance"
STEP_GATE_DROP_DISTANCE = "drop_step_from_distance"
STEP_GATE_POLICIES = (STEP_GATE_KEEP_DISTANCE, STEP_GATE_DROP_DISTANCE)

DEFAULT_PARAMETERS: dict[str, Any] = {
    "position_domain": POSITION_DOMAIN_PLANAR,
    "planar_position_fields": ["x_m", "y_m"],
    "geodetic_position_fields": ["latitude_deg", "longitude_deg"],
    "distance_method": DISTANCE_METHOD_PLANAR,
    "enu_method": "none",
    "earth_radius_m": WGS84_MEAN_RADIUS_M,
    "geodetic_origin": "first_sample_per_entity",
    "entity_grouping": ENTITY_GROUPING_OBJECT,
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
    "filter_applies_to": FILTER_APPLIES_KINEMATICS_ONLY,
    "detection_gate": DETECTION_GATE_NONE,
    "step_speed_gate": None,
    "resample_method": RESAMPLE_NONE,
    "interpolation": INTERPOLATION_NONE,
    "zones": [],
    "effort": None,
    "rolling_windows_s": [],
    "rolling_edge_policy": EDGE_DROP_INCOMPLETE,
}

DISTANCE_TOTAL = MetricDeclaration(
    metric_id="locomotor.distance_total",
    name="Total locomotor distance",
    si_unit="m",
    description=(
        "Cumulative distance over the stream: planar path length for the planar "
        "domain, haversine geodesic steps for the geodetic domain."
    ),
)
MEAN_SPEED = MetricDeclaration(
    metric_id="locomotor.mean_speed",
    name="Mean speed over the whole stream",
    si_unit="m/s",
    description="Total distance divided by the stream duration.",
)
MAX_SPEED = MetricDeclaration(
    metric_id="locomotor.max_speed",
    name="Peak locomotor speed",
    si_unit="m/s",
    description="Maximum derived speed over the stream.",
)
MAX_ACCELERATION = MetricDeclaration(
    metric_id="locomotor.max_acceleration",
    name="Peak acceleration magnitude",
    si_unit="m/s**2",
    description="Maximum planar acceleration magnitude derived from the velocity series.",
)
MAX_DECELERATION = MetricDeclaration(
    metric_id="locomotor.max_deceleration",
    name="Peak deceleration magnitude",
    si_unit="m/s**2",
    description=(
        "Largest negative signed tangential acceleration d|v|/dt (floored at zero), i.e. "
        "the peak slowing rate. This is not the minimum of the non-negative vector "
        "acceleration magnitude."
    ),
)
EFFORT_COUNT = MetricDeclaration(
    metric_id="locomotor.effort_count",
    name="Effort count above the configured threshold",
    si_unit="1",
    description="Number of contiguous above-threshold efforts surviving the configured minimum.",
)
EFFORT_DURATION_TOTAL = MetricDeclaration(
    metric_id="locomotor.effort_duration_total",
    name="Total duration above the configured threshold",
    si_unit="s",
    description="Summed duration of all accepted efforts, using trapezoidal sample weights.",
)
EFFORT_DISTANCE_TOTAL = MetricDeclaration(
    metric_id="locomotor.effort_distance_total",
    name="Distance covered inside accepted efforts",
    si_unit="m",
    description="Summed distance of all accepted efforts.",
)
EFFORT_PEAK_SPEED = MetricDeclaration(
    metric_id="locomotor.effort_peak_speed",
    name="Peak speed inside accepted efforts",
    si_unit="m/s",
    description="Maximum speed observed inside any accepted effort.",
)

SERIES_NAME = "locomotor_kinematics"
EFFORTS_SERIES_NAME = "locomotor_efforts"
ROLLING_SERIES_NAME = "locomotor_rolling_peaks"

_TOKEN = re.compile(r"[^a-z0-9]+")


def _metric_token(value: str) -> str:
    token = _TOKEN.sub("_", value.strip().lower()).strip("_")
    if not token:
        raise ValueError(f"cannot derive a metric token from {value!r}")
    return token


def zone_distance_declaration(zone: SpeedZone) -> MetricDeclaration:
    """Metric declaration for distance covered inside one speed zone."""
    return MetricDeclaration(
        metric_id=f"locomotor.distance_zone.{_metric_token(zone.name)}",
        name=f"Distance in speed zone {zone.name}",
        si_unit="m",
        description=(
            f"Distance covered while speed is in [{zone.lower_m_s}, "
            f"{zone.upper_m_s if zone.upper_m_s is not None else 'inf'}) m/s."
        ),
    )


def zone_peak_speed_declaration(zone: SpeedZone) -> MetricDeclaration:
    """Metric declaration for peak speed inside one speed zone."""
    return MetricDeclaration(
        metric_id=f"locomotor.peak_speed_zone.{_metric_token(zone.name)}",
        name=f"Peak speed in speed zone {zone.name}",
        si_unit="m/s",
        description=f"Maximum speed inside speed zone {zone.name}.",
    )


def rolling_distance_declaration(window_s: float) -> MetricDeclaration:
    """Metric declaration for the peak rolling distance of one window."""
    return MetricDeclaration(
        metric_id=f"locomotor.rolling_peak_distance.{window_s:g}s",
        name=f"Peak rolling distance over {window_s:g} s",
        si_unit="m",
        description=(
            f"Maximum distance covered in any fully contained {window_s:g} s window "
            "(incomplete-edge policy applies)."
        ),
    )


def rolling_mean_speed_declaration(window_s: float) -> MetricDeclaration:
    """Metric declaration for the peak rolling mean speed of one window."""
    return MetricDeclaration(
        metric_id=f"locomotor.rolling_peak_mean_speed.{window_s:g}s",
        name=f"Peak rolling mean speed over {window_s:g} s",
        si_unit="m/s",
        description=(
            f"Peak rolling distance divided by {window_s:g} s; a window demand, not an "
            "instantaneous speed."
        ),
    )


def _resolved(parameters: Mapping[str, Any] | None) -> dict[str, Any]:
    resolved = {**DEFAULT_PARAMETERS, **dict(parameters or {})}
    domain = resolved["position_domain"]
    if domain not in POSITION_DOMAINS:
        raise ValueError(f"position_domain {domain!r} is not one of {POSITION_DOMAINS}")
    if resolved["resample_method"] != RESAMPLE_NONE:
        raise ValueError(
            "this processor revision does not resample; resample_method must stay 'none'"
        )
    if resolved["interpolation"] != INTERPOLATION_NONE:
        raise ValueError(
            "this processor revision never interpolates; interpolation must stay 'none'"
        )
    if resolved["entity_grouping"] not in ENTITY_GROUPINGS:
        raise ValueError(f"unknown entity_grouping {resolved['entity_grouping']!r}")
    if domain == POSITION_DOMAIN_PLANAR:
        if resolved["distance_method"] != DISTANCE_METHOD_PLANAR:
            raise ValueError(
                f"a planar position domain requires distance_method {DISTANCE_METHOD_PLANAR!r}"
            )
        if resolved["enu_method"] != "none":
            raise ValueError("a planar position domain must not declare an ENU method")
    else:
        if resolved["distance_method"] != DISTANCE_METHOD_HAVERSINE:
            raise ValueError(
                f"a geodetic position domain requires distance_method {DISTANCE_METHOD_HAVERSINE!r}"
            )
        if resolved["enu_method"] != ENU_METHOD_EQUIRECTANGULAR:
            raise ValueError(
                f"a geodetic position domain requires enu_method {ENU_METHOD_EQUIRECTANGULAR!r}"
            )
    radius = float(resolved["earth_radius_m"])
    if not math.isfinite(radius) or radius <= 0:
        raise ValueError("earth_radius_m must be finite and positive")
    if resolved["filter_applies_to"] != FILTER_APPLIES_KINEMATICS_ONLY:
        raise ValueError(
            "filter_applies_to must remain 'kinematics_only'; distance is never filtered"
        )
    if resolved["geodetic_origin"] != "first_sample_per_entity":
        raise ValueError("geodetic_origin must remain 'first_sample_per_entity'")
    if resolved["rolling_edge_policy"] not in ROLLING_EDGE_POLICIES:
        raise ValueError(f"unknown rolling_edge_policy {resolved['rolling_edge_policy']!r}")
    if resolved["detection_gate"] not in DETECTION_GATES:
        raise ValueError(f"unknown detection_gate {resolved['detection_gate']!r}")
    gate = resolved.get("step_speed_gate")
    if gate is not None:
        maximum = float(gate["max_m_s"])
        if not math.isfinite(maximum) or maximum <= 0:
            raise ValueError("step_speed_gate.max_m_s must be finite and positive")
        policy = str(gate.get("excluded_step_policy", "keep_step_in_distance"))
        if policy not in STEP_GATE_POLICIES:
            raise ValueError(f"unknown step_speed_gate.excluded_step_policy {policy!r}")
    zones = tuple(SpeedZone.from_parameters(item) for item in resolved.get("zones") or ())
    zone_tokens = [_metric_token(zone.name) for zone in zones]
    if len(set(zone_tokens)) != len(zone_tokens):
        raise ValueError("speed zone names must map to unique metric tokens")
    effort = resolved.get("effort")
    if effort is not None:
        EffortParameters(
            threshold_m_s=float(effort["threshold_m_s"]),
            min_duration_s=float(effort["min_duration_s"]),
            merge_gap_s=float(effort.get("merge_gap_s", 0.0)),
            hysteresis_m_s=float(effort.get("hysteresis_m_s", 0.0)),
        )
    windows: list[float] = []
    for window in resolved.get("rolling_windows_s") or ():
        value = float(window)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("rolling windows must be finite and positive")
        windows.append(value)
    if len({f"{value:g}" for value in windows}) != len(windows):
        raise ValueError("rolling windows must be unique")
    DerivativeSpec.from_parameters(dict(resolved["derivative"]))
    return resolved


def locomotor_spec(parameters: Mapping[str, Any] | None = None) -> ProcessorSpec:
    """Resolve and validate the full explicit parameter set."""
    resolved = _resolved(parameters)
    return ProcessorSpec(
        algorithm_id=ALGORITHM_ID,
        name="Deterministic locomotor speed/effort processor",
        version=ALGORITHM_VERSION,
        description=(
            "Planar or geodetic distance, explicit filtered derivatives, configurable SI "
            "speed zones, hysteresis effort segmentation and rolling peak demands. No "
            "resampling, interpolation or hidden smoothing; all thresholds are supplied "
            "configuration."
        ),
        parameters=resolved,
    )


@dataclass(frozen=True, slots=True)
class _EntityFrame:
    entity_id: str
    row_indices: np.ndarray
    sample_index: np.ndarray
    t_rel_ns: np.ndarray
    scope: dict[str, str | None]


def _scope(table: pa.Table) -> dict[str, str | None]:
    def single(name: str) -> str | None:
        if name not in table.column_names:
            return None
        value = table.column(name)[0].as_py()
        return None if value is None else str(value)

    return {
        "session_id": single("session_id"),
        "subject_id": single("subject_id"),
        "trial_id": single("trial_id"),
        "stream_id": single("stream_id"),
    }


def _entities(table: pa.Table, *, grouping: str) -> tuple[_EntityFrame, ...]:
    if table.num_rows == 0:
        raise ValueError(f"{ALGORITHM_ID}: the input stream is empty")
    scope = _scope(table)
    sample_index = np.asarray(
        table.column("sample_index").to_numpy(zero_copy_only=False), dtype=np.int64
    )
    t_rel_ns = np.asarray(table.column("t_rel_ns").to_numpy(zero_copy_only=False), dtype=np.int64)
    use_object = grouping == ENTITY_GROUPING_OBJECT and "object_id" in table.column_names
    if not use_object:
        stream_id = scope["stream_id"] or "stream"
        return (
            _EntityFrame(
                entity_id=stream_id,
                row_indices=np.arange(sample_index.size, dtype=np.int64),
                sample_index=sample_index,
                t_rel_ns=t_rel_ns,
                scope=scope,
            ),
        )
    object_ids = table.column("object_id").to_pylist()
    seen: dict[str, list[int]] = {}
    for position, value in enumerate(object_ids):
        if value is None:
            continue
        seen.setdefault(str(value), []).append(position)
    if not seen:
        stream_id = scope["stream_id"] or "stream"
        return (
            _EntityFrame(
                entity_id=stream_id,
                row_indices=np.arange(sample_index.size, dtype=np.int64),
                sample_index=sample_index,
                t_rel_ns=t_rel_ns,
                scope=scope,
            ),
        )
    frames: list[_EntityFrame] = []
    for entity_id in sorted(seen):
        indices = np.asarray(seen[entity_id], dtype=np.int64)
        frames.append(
            _EntityFrame(
                entity_id=entity_id,
                row_indices=indices,
                sample_index=sample_index[indices],
                t_rel_ns=t_rel_ns[indices],
                scope=scope,
            )
        )
    return tuple(frames)


def _column_float(table: pa.Table, name: str) -> np.ndarray:
    return np.asarray(table.column(name).to_numpy(zero_copy_only=False), dtype=np.float64)


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    """Boolean dilation by ``radius`` samples, for stencil invalidation."""
    if radius <= 0:
        return mask.copy()
    result = mask.copy()
    for shift in range(1, radius + 1):
        result[shift:] |= mask[:-shift]
        result[:-shift] |= mask[shift:]
    return result


def _detection_invalid(table: pa.Table, frame: _EntityFrame, *, gate: str) -> np.ndarray:
    """Samples the configured detection gate rejects (kinematics-only effect)."""
    invalid = np.zeros(frame.t_rel_ns.size, dtype=bool)
    if gate == DETECTION_GATE_NONE:
        return invalid
    if "is_detected" not in table.column_names:
        raise ValueError(
            "detection_gate 'require_is_detected' was configured but the stream has no "
            "is_detected declaration"
        )
    declared = table.column("is_detected").to_pylist()
    values = [declared[index] for index in frame.row_indices]
    if all(value is None for value in values):
        raise ValueError(
            "detection_gate 'require_is_detected' was configured but every is_detected "
            "sample is null; the gate cannot be honored"
        )
    return np.asarray([value is not True for value in values], dtype=bool)


def _finite_max(values: np.ndarray) -> float | None:
    finite = values[np.isfinite(values)]
    return float(np.max(finite)) if finite.size else None


def _finite_min(values: np.ndarray) -> float | None:
    finite = values[np.isfinite(values)]
    return float(np.min(finite)) if finite.size else None


def process_locomotor(
    table: pa.Table,
    *,
    parameters: Mapping[str, Any] | None = None,
) -> ProcessorResult:
    """Process one canonical GNSS or tracking stream into metrics and series."""
    spec = locomotor_spec(parameters)
    resolved = spec.parameters
    domain = str(resolved["position_domain"])
    zones = tuple(SpeedZone.from_parameters(item) for item in resolved.get("zones") or ())
    effort_parameters = resolved.get("effort")
    windows = tuple(float(item) for item in resolved.get("rolling_windows_s") or ())
    derivative_spec = DerivativeSpec.from_parameters(dict(resolved["derivative"]))
    radius = float(resolved["earth_radius_m"])
    entities = _entities(table, grouping=str(resolved["entity_grouping"]))

    series_parts: list[pa.Table] = []
    effort_rows: list[dict[str, Any]] = []
    rolling_rows: list[dict[str, Any]] = []
    metrics: list[ScalarMetric] = []
    total_samples = 0
    for frame in entities:
        positions = _positions(table, frame, domain=domain, fields=resolved)
        total_samples += frame.t_rel_ns.size
        if frame.t_rel_ns.size >= 2:
            step = steps_s(frame.t_rel_ns)
            nominal = _nominal_rate(table)
            rate_hz = nominal if nominal and nominal > 0 else float(1.0 / np.median(step))
        else:
            rate_hz = _nominal_rate(table) or 0.0
        times_s = (frame.t_rel_ns - frame.t_rel_ns[0]).astype(np.float64) / 1e9
        durations = sample_durations_s(frame.t_rel_ns)

        if domain == POSITION_DOMAIN_PLANAR:
            x_raw = positions["x"]
            y_raw = positions["y"]
            distance_step = np.concatenate(([0.0], np.hypot(np.diff(x_raw), np.diff(y_raw))))
            kinematic_x, kinematic_y = x_raw, y_raw
        else:
            east, north = enu_from_geodetic(
                positions["latitude"],
                positions["longitude"],
                origin_latitude_deg=float(positions["latitude"][0]),
                origin_longitude_deg=float(positions["longitude"][0]),
                radius_m=radius,
            )
            step_distances = haversine_distance_m(
                positions["latitude"], positions["longitude"], radius_m=radius
            )
            distance_step = np.concatenate(([0.0], step_distances))
            kinematic_x, kinematic_y = east, north

        invalid = _detection_invalid(table, frame, gate=str(resolved["detection_gate"]))
        step_gate = resolved.get("step_speed_gate")
        excluded_steps = 0
        distance_policy = STEP_GATE_KEEP_DISTANCE
        if step_gate is not None:
            distance_policy = str(step_gate.get("excluded_step_policy", STEP_GATE_KEEP_DISTANCE))
            segment_steps = np.diff(frame.t_rel_ns).astype(np.float64) / 1e9
            segment_speed = np.full(segment_steps.size, np.inf, dtype=np.float64)
            positive = segment_steps > 0
            segment_speed[positive] = distance_step[1:][positive] / segment_steps[positive]
            implausible = segment_speed > float(step_gate["max_m_s"])
            excluded_steps = int(np.count_nonzero(implausible))
            invalid[:-1] |= implausible
            invalid[1:] |= implausible
            if distance_policy == STEP_GATE_DROP_DISTANCE:
                distance_step = distance_step.copy()
                distance_step[1:][implausible] = 0.0

        filtered_x = derivative_spec.filter.apply(kinematic_x, rate_hz=rate_hz)
        filtered_y = derivative_spec.filter.apply(kinematic_y, rate_hz=rate_hz)
        vx = derivative_variable(
            filtered_x, frame.t_rel_ns, edge_policy=derivative_spec.edge_policy
        )
        vy = derivative_variable(
            filtered_y, frame.t_rel_ns, edge_policy=derivative_spec.edge_policy
        )
        velocity_invalid = _dilate(invalid, 1)
        vx = np.where(velocity_invalid, np.nan, vx)
        vy = np.where(velocity_invalid, np.nan, vy)
        speed = np.hypot(vx, vy)
        # NaN velocities propagate through the second difference, so acceleration is
        # never claimed across a sample the configured gate rejected.
        ax = derivative_variable(vx, frame.t_rel_ns, edge_policy=derivative_spec.edge_policy)
        ay = derivative_variable(vy, frame.t_rel_ns, edge_policy=derivative_spec.edge_policy)
        acceleration = np.hypot(ax, ay)
        # Signed tangential acceleration d|v|/dt: negative while the entity slows,
        # so the deceleration peak is a real slowing rate and not the minimum of a
        # non-negative magnitude.
        tangential_acceleration = derivative_variable(
            speed, frame.t_rel_ns, edge_policy=derivative_spec.edge_policy
        )
        cumulative_distance = np.cumsum(distance_step)
        total_distance = float(cumulative_distance[-1]) if cumulative_distance.size else 0.0
        duration_s = float(times_s[-1]) if times_s.size else 0.0
        max_speed = _finite_max(speed)
        max_accel = _finite_max(acceleration)
        min_tangential = _finite_min(tangential_acceleration)
        if max_speed is None:
            raise ValueError(
                f"{ALGORITHM_ID}: speed could not be derived (edge policy "
                f"{derivative_spec.edge_policy!r} on a very short stream); choose "
                "'one_sided_first_order' or provide a longer stream"
            )

        entity_scope = dict(frame.scope)
        provenance = {
            "entity_id": frame.entity_id,
            "position_domain": domain,
            "distance_method": str(resolved["distance_method"]),
            "enu_method": str(resolved["enu_method"]),
            "earth_radius_m": radius,
            "derivative": derivative_spec.parameters(),
            "filter_applies_to": str(resolved["filter_applies_to"]),
            "detection_gate": str(resolved["detection_gate"]),
            "step_speed_gate": resolved.get("step_speed_gate"),
            "quality_gate_applies_to": STEP_SPEED_GATE_KINEMATICS_ONLY,
            "excluded_steps": excluded_steps,
            "excluded_step_distance_policy": distance_policy,
            "distance_gated": excluded_steps > 0 and distance_policy == STEP_GATE_DROP_DISTANCE,
            "resample_method": RESAMPLE_NONE,
            "interpolation": INTERPOLATION_NONE,
            "samples": int(frame.t_rel_ns.size),
            "rate_hz": float(rate_hz),
            "duration_s": duration_s,
            "invalid_samples": int(np.count_nonzero(invalid)),
            "max_deceleration_definition": "negative_minimum_of_d_speed_dt_floored_at_zero",
        }

        def emit(
            declaration: MetricDeclaration,
            value: float,
            *,
            entity_id: str = frame.entity_id,
            scope: dict[str, str | None] = entity_scope,
            base_provenance: dict[str, Any] = provenance,
            **extra: Any,
        ) -> None:
            metrics.append(
                ScalarMetric(
                    declaration=declaration,
                    value=value,
                    entity_id=entity_id,
                    provenance={**base_provenance, **extra},
                    **scope,
                )
            )

        emit(DISTANCE_TOTAL, total_distance)
        emit(MEAN_SPEED, total_distance / duration_s if duration_s > 0 else 0.0)
        emit(MAX_SPEED, max_speed)
        emit(MAX_ACCELERATION, max_accel if max_accel is not None else 0.0)
        emit(
            MAX_DECELERATION,
            max(0.0, -(min_tangential if min_tangential is not None else 0.0)),
        )

        if zones:
            stats = zone_statistics(
                speed,
                distance_step,
                zones=zones,
                sample_duration_s=durations,
            )
            for zone in zones:
                emit(zone_distance_declaration(zone), stats[zone.name]["distance_m"])
                emit(zone_peak_speed_declaration(zone), stats[zone.name]["peak_speed_m_s"])

        if effort_parameters is not None:
            params = EffortParameters(
                threshold_m_s=float(effort_parameters["threshold_m_s"]),
                min_duration_s=float(effort_parameters["min_duration_s"]),
                merge_gap_s=float(effort_parameters.get("merge_gap_s", 0.0)),
                hysteresis_m_s=float(effort_parameters.get("hysteresis_m_s", 0.0)),
            )
            efforts = effort_segments(
                speed,
                distance_step,
                times_s=times_s,
                sample_duration_s=durations,
                parameters=params,
            )
            emit(EFFORT_COUNT, float(len(efforts)))
            emit(EFFORT_DURATION_TOTAL, float(sum(item.duration_s for item in efforts)))
            emit(EFFORT_DISTANCE_TOTAL, float(sum(item.distance_m for item in efforts)))
            emit(
                EFFORT_PEAK_SPEED,
                max((item.peak_speed_m_s for item in efforts), default=0.0),
            )
            for index, item in enumerate(efforts):
                effort_rows.append(
                    {
                        "entity_id": frame.entity_id,
                        "effort_index": index,
                        "start_sample_index": int(frame.sample_index[item.start_index]),
                        "end_sample_index": int(frame.sample_index[item.end_index]),
                        "start_time_s": item.start_time_s,
                        "end_time_s": item.end_time_s,
                        "duration_s": item.duration_s,
                        "distance_m": item.distance_m,
                        "peak_speed_m_s": item.peak_speed_m_s,
                        "mean_speed_m_s": item.mean_speed_m_s,
                    }
                )

        for window in windows:
            peak, end_index = rolling_peak_window(
                cumulative_distance,
                times_s,
                window_s=window,
                edge_policy=str(resolved["rolling_edge_policy"]),
            )
            if math.isfinite(peak):
                emit(rolling_distance_declaration(window), float(peak))
                emit(rolling_mean_speed_declaration(window), float(peak) / window)
                rolling_rows.append(
                    {
                        "entity_id": frame.entity_id,
                        "window_s": float(window),
                        "peak_distance_m": float(peak),
                        "peak_mean_speed_m_s": float(peak) / window,
                        "end_sample_index": int(frame.sample_index[end_index]),
                        "end_time_s": float(times_s[end_index]),
                    }
                )

        series_parts.append(
            pa.table(
                {
                    "entity_id": pa.array(
                        [frame.entity_id] * frame.t_rel_ns.size, type=pa.string()
                    ),
                    "sample_index": pa.array(frame.sample_index, type=pa.int64()),
                    "t_rel_ns": pa.array(frame.t_rel_ns, type=pa.int64()),
                    "position_x_m": pa.array(kinematic_x, type=pa.float64()),
                    "position_y_m": pa.array(kinematic_y, type=pa.float64()),
                    "speed_m_s": pa.array(speed, type=pa.float64()),
                    "vx_m_s": pa.array(vx, type=pa.float64()),
                    "vy_m_s": pa.array(vy, type=pa.float64()),
                    "ax_m_s2": pa.array(ax, type=pa.float64()),
                    "ay_m_s2": pa.array(ay, type=pa.float64()),
                }
            )
        )

    series: list[SeriesOutput] = []
    if series_parts:
        kinematics = pa.concat_tables(series_parts) if len(series_parts) > 1 else series_parts[0]
        series.append(
            SeriesOutput(
                name=SERIES_NAME,
                table=kinematics,
                description=(
                    "Per-sample derived locomotor kinematics: filtered positions, velocity "
                    "components, speed and acceleration components."
                ),
            )
        )
    if effort_rows:
        series.append(
            SeriesOutput(
                name=EFFORTS_SERIES_NAME,
                table=pa.Table.from_pylist(
                    effort_rows,
                    schema=pa.schema(
                        [
                            pa.field("entity_id", pa.string()),
                            pa.field("effort_index", pa.int64()),
                            pa.field("start_sample_index", pa.int64()),
                            pa.field("end_sample_index", pa.int64()),
                            pa.field("start_time_s", pa.float64()),
                            pa.field("end_time_s", pa.float64()),
                            pa.field("duration_s", pa.float64()),
                            pa.field("distance_m", pa.float64()),
                            pa.field("peak_speed_m_s", pa.float64()),
                            pa.field("mean_speed_m_s", pa.float64()),
                        ]
                    ),
                ),
                description="Accepted above-threshold efforts with their explicit parameters.",
            )
        )
    if rolling_rows:
        series.append(
            SeriesOutput(
                name=ROLLING_SERIES_NAME,
                table=pa.Table.from_pylist(
                    rolling_rows,
                    schema=pa.schema(
                        [
                            pa.field("entity_id", pa.string()),
                            pa.field("window_s", pa.float64()),
                            pa.field("peak_distance_m", pa.float64()),
                            pa.field("peak_mean_speed_m_s", pa.float64()),
                            pa.field("end_sample_index", pa.int64()),
                            pa.field("end_time_s", pa.float64()),
                        ]
                    ),
                ),
                description="Rolling peak demands for each configured window.",
            )
        )
    diagnostics = {
        "entities": len(entities),
        "samples": total_samples,
        "position_domain": domain,
        "zones": [zone.parameters() for zone in zones],
        "effort_parameters": None if effort_parameters is None else dict(effort_parameters),
        "rolling_windows_s": list(windows),
        "derivative": derivative_spec.parameters(),
        "detection_gate": str(resolved["detection_gate"]),
        "step_speed_gate": resolved.get("step_speed_gate"),
    }
    return ProcessorResult(
        spec=spec, metrics=tuple(metrics), series=tuple(series), diagnostics=diagnostics
    )


def _positions(
    table: pa.Table,
    frame: _EntityFrame,
    *,
    domain: str,
    fields: Mapping[str, Any],
) -> dict[str, np.ndarray]:
    """Extract the entity's own position rows, failing closed on non-finite input."""
    if domain == POSITION_DOMAIN_PLANAR:
        names = [str(item) for item in fields["planar_position_fields"]]
        output = {"x": names[0], "y": names[1]}
    else:
        names = [str(item) for item in fields["geodetic_position_fields"]]
        output = {"latitude": names[0], "longitude": names[1]}
    positions: dict[str, np.ndarray] = {}
    for key, name in output.items():
        if name not in table.column_names:
            raise ValueError(f"{ALGORITHM_ID}: required position column {name!r} is absent")
        values = _column_float(table, name)[frame.row_indices]
        if not np.isfinite(values).all():
            raise ValueError(
                f"{ALGORITHM_ID}: position column {name!r} contains non-finite samples for "
                f"entity {frame.entity_id!r}; no value is imputed"
            )
        positions[key] = values
    return positions


def _nominal_rate(table: pa.Table) -> float | None:
    if "nominal_sampling_rate_hz" not in table.column_names:
        return None
    value = table.column("nominal_sampling_rate_hz")[0].as_py()
    if value is None:
        return None
    rate = float(value)
    return rate if math.isfinite(rate) and rate > 0 else None


__all__ = [
    "ALGORITHM_ID",
    "ALGORITHM_VERSION",
    "DISTANCE_TOTAL",
    "EFFORT_COUNT",
    "EFFORT_DISTANCE_TOTAL",
    "EFFORT_DURATION_TOTAL",
    "EFFORT_PEAK_SPEED",
    "MAX_ACCELERATION",
    "MAX_DECELERATION",
    "MAX_SPEED",
    "MEAN_SPEED",
    "POSITION_DOMAIN_GEODETIC",
    "POSITION_DOMAIN_PLANAR",
    "locomotor_spec",
    "process_locomotor",
    "rolling_distance_declaration",
    "rolling_mean_speed_declaration",
    "zone_distance_declaration",
    "zone_peak_speed_declaration",
]
