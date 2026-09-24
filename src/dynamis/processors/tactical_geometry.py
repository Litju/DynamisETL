"""Level A deterministic team and interpersonal tracking geometry.

The processor consumes canonical tracking rows only. It never infers possession,
attacking direction, formation, or a tactical event from a picture. Dense output
is long-lived Parquet through the existing processor runtime; the row envelope
keeps the coordinate frame, measurement class, input class, and quality facts
next to the values.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import Any

import pyarrow as pa

from dynamis.processors.spec import ProcessorResult, ProcessorSpec, SeriesOutput

ALGORITHM_ID = "tactical.team_geometry"
ALGORITHM_VERSION = "1"
DEFAULT_PARAMETERS: dict[str, Any] = {
    "pitch_length_m": 105.0,
    "pitch_width_m": 68.0,
    "minimum_players": 2,
    "include_extrapolated": True,
    "normalize_attacking_direction": False,
    "gap_policy": "exact_timestamps_only",
}

REQUIRED_COLUMNS = {
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
}
PLAYER_TYPES = frozenset({"player", "goalkeeper"})


@dataclass(frozen=True, slots=True)
class Position:
    entity_id: str
    group_id: str
    x_m: float
    y_m: float
    object_type: str
    is_detected: bool | None


@dataclass(frozen=True, slots=True)
class Frame:
    t_rel_ns: int
    groups: dict[str, tuple[Position, ...]]
    ball: tuple[float, float] | None
    missing_rows: int
    outside_rows: int
    extrapolated_rows: int
    duplicate_rows: int


def _parameters(parameters: dict[str, Any] | None) -> dict[str, Any]:
    resolved = dict(DEFAULT_PARAMETERS)
    if parameters:
        resolved.update(parameters)
    if float(resolved["pitch_length_m"]) <= 0 or float(resolved["pitch_width_m"]) <= 0:
        raise ValueError("tactical geometry pitch dimensions must be positive")
    if int(resolved["minimum_players"]) < 2:
        raise ValueError("tactical geometry minimum_players must be at least 2")
    if bool(resolved["normalize_attacking_direction"]):
        raise ValueError(
            "attack-normalized geometry requires a declared per-team direction; "
            "the canonical tracking contract does not provide one"
        )
    return resolved


def _context(table: pa.Table) -> tuple[str, str, str | None, str, str, str]:
    if table.num_rows == 0:
        raise ValueError(f"{ALGORITHM_ID}: tracking table is empty")
    first = table.slice(0, 1).to_pylist()[0]
    return (
        str(first["dataset_id"]),
        str(first["session_id"]),
        None if first.get("trial_id") is None else str(first["trial_id"]),
        str(first["stream_id"]),
        str(first["coordinate_frame_id"]),
        str(first["measurement_class"]),
    )


def _frames(table: pa.Table, parameters: dict[str, Any]) -> tuple[Frame, ...]:
    missing_columns = REQUIRED_COLUMNS - set(table.column_names)
    if missing_columns:
        raise ValueError(f"{ALGORITHM_ID}: missing tracking columns {sorted(missing_columns)}")
    length = float(parameters["pitch_length_m"])
    width = float(parameters["pitch_width_m"])
    grouped: dict[int, dict[str, dict[str, Position]]] = defaultdict(lambda: defaultdict(dict))
    balls: dict[int, tuple[float, float]] = {}
    diagnostics: dict[int, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for row in table.to_pylist():
        timestamp = int(row["t_rel_ns"])
        x_raw, y_raw = row.get("x_m"), row.get("y_m")
        if x_raw is None or y_raw is None:
            diagnostics[timestamp][0] += 1
            continue
        try:
            x, y = float(x_raw), float(y_raw)
        except (TypeError, ValueError):
            diagnostics[timestamp][0] += 1
            continue
        if not (math.isfinite(x) and math.isfinite(y)):
            diagnostics[timestamp][0] += 1
            continue
        if not (-length / 2 <= x <= length / 2 and -width / 2 <= y <= width / 2):
            diagnostics[timestamp][1] += 1
        if row.get("is_detected") is False:
            diagnostics[timestamp][2] += 1
            if not bool(parameters["include_extrapolated"]):
                diagnostics[timestamp][0] += 1
                continue
        object_type = str(row.get("object_type") or "")
        object_id = str(row.get("object_id") or "")
        if object_type == "ball":
            balls.setdefault(timestamp, (x, y))
            continue
        if object_type not in PLAYER_TYPES or not row.get("group_id") or not object_id:
            continue
        group_id = str(row["group_id"])
        if object_id in grouped[timestamp][group_id]:
            diagnostics[timestamp][3] += 1
            continue
        grouped[timestamp][group_id][object_id] = Position(
            entity_id=object_id,
            group_id=group_id,
            x_m=x,
            y_m=y,
            object_type=object_type,
            is_detected=row.get("is_detected"),
        )
    return tuple(
        Frame(
            t_rel_ns=timestamp,
            groups={
                group: tuple(sorted(players.values(), key=lambda item: item.entity_id))
                for group, players in sorted(groups.items())
            },
            ball=balls.get(timestamp),
            missing_rows=diagnostics[timestamp][0],
            outside_rows=diagnostics[timestamp][1],
            extrapolated_rows=diagnostics[timestamp][2],
            duplicate_rows=diagnostics[timestamp][3],
        )
        for timestamp, groups in sorted(grouped.items())
    )


def _cross(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def convex_hull(points: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float], ...]:
    """Return a deterministic counter-clockwise monotone-chain hull."""
    unique = sorted(set(points))
    if len(unique) <= 1:
        return tuple(unique)
    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return tuple(lower[:-1] + upper[:-1])


def polygon_area(polygon: tuple[tuple[float, float], ...]) -> float:
    if len(polygon) < 3:
        return 0.0
    return abs(
        sum(
            polygon[index][0] * polygon[(index + 1) % len(polygon)][1]
            - polygon[(index + 1) % len(polygon)][0] * polygon[index][1]
            for index in range(len(polygon))
        )
        / 2.0
    )


def _clip_convex_polygon(
    subject: tuple[tuple[float, float], ...],
    clipper: tuple[tuple[float, float], ...],
) -> tuple[tuple[float, float], ...]:
    """Clip one CCW convex polygon by another CCW convex polygon."""
    output = list(subject)
    if len(output) < 3 or len(clipper) < 3:
        return ()
    epsilon = 1e-12
    for index, start in enumerate(clipper):
        end = clipper[(index + 1) % len(clipper)]
        if not output:
            break
        input_points = output
        output = []
        previous = input_points[-1]
        previous_inside = _cross(start, end, previous) >= -epsilon
        for current in input_points:
            current_inside = _cross(start, end, current) >= -epsilon
            if current_inside != previous_inside:
                edge_cross = _cross(start, end, previous)
                direction_cross = _cross(start, end, current)
                delta = edge_cross - direction_cross
                if abs(delta) > epsilon:
                    fraction = edge_cross / delta
                    output.append(
                        (
                            previous[0] + fraction * (current[0] - previous[0]),
                            previous[1] + fraction * (current[1] - previous[1]),
                        )
                    )
            if current_inside:
                output.append(current)
            previous = current
            previous_inside = current_inside
    return tuple(output)


def convex_polygon_intersection_area(
    left: tuple[tuple[float, float], ...], right: tuple[tuple[float, float], ...]
) -> float:
    return polygon_area(_clip_convex_polygon(left, right))


def _distance(left: Position | tuple[float, float], right: Position | tuple[float, float]) -> float:
    lx, ly = (left.x_m, left.y_m) if isinstance(left, Position) else left
    rx, ry = (right.x_m, right.y_m) if isinstance(right, Position) else right
    return math.hypot(lx - rx, ly - ry)


def _row_context(
    *,
    dataset_id: str,
    session_id: str,
    trial_id: str | None,
    stream_id: str,
    coordinate_frame_id: str,
    input_measurement_class: str,
    timestamp: int,
    quality: dict[str, Any],
) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "session_id": session_id,
        "trial_id": trial_id,
        "stream_id": stream_id,
        "t_rel_ns": timestamp,
        "measurement_class": "PIPELINE_DERIVED",
        "input_measurement_class": input_measurement_class,
        "coordinate_frame_id": coordinate_frame_id,
        "quality_json": json.dumps(quality, sort_keys=True, separators=(",", ":")),
    }


def _series_table(
    rows: list[dict[str, Any]], *, method: str, parameters: dict[str, Any]
) -> pa.Table:
    if not rows:
        raise ValueError(f"{ALGORITHM_ID}: no valid tactical geometry rows")
    table = pa.Table.from_pylist(rows)
    metadata = dict(table.schema.metadata or {})
    metadata.update(
        {
            b"dynamis.contract": b"tactical_dense_series",
            b"dynamis.measurement_class": b"PIPELINE_DERIVED",
            b"dynamis.method": method.encode(),
            b"dynamis.algorithm_id": ALGORITHM_ID.encode(),
            b"dynamis.algorithm_version": ALGORITHM_VERSION.encode(),
            b"dynamis.parameters": json.dumps(
                parameters, sort_keys=True, separators=(",", ":")
            ).encode(),
        }
    )
    return table.replace_schema_metadata(metadata)


def process_tactical_geometry(
    table: pa.Table, *, parameters: dict[str, Any] | None = None
) -> ProcessorResult:
    """Compute Level A team, interpersonal, and frame-axis relation series."""
    resolved = _parameters(parameters)
    dataset_id, session_id, trial_id, stream_id, frame_id, input_class = _context(table)
    frames = _frames(table, resolved)
    if not frames:
        raise ValueError(f"{ALGORITHM_ID}: no timestamps with canonical tracking rows")
    length = float(resolved["pitch_length_m"])
    width = float(resolved["pitch_width_m"])
    pitch_diagonal = math.hypot(length, width)
    minimum_players = int(resolved["minimum_players"])
    team_rows: list[dict[str, Any]] = []
    interpersonal_rows: list[dict[str, Any]] = []
    relation_rows: list[dict[str, Any]] = []
    team_lengths: dict[str, list[tuple[int, float, float]]] = defaultdict(list)

    for frame in frames:
        team_hulls: dict[str, tuple[tuple[float, float], ...]] = {}
        centroids: dict[str, tuple[float, float]] = {}
        for group_id, players in frame.groups.items():
            count = len(players)
            xs = tuple(player.x_m for player in players)
            ys = tuple(player.y_m for player in players)
            centroid = (sum(xs) / count, sum(ys) / count)
            centroids[group_id] = centroid
            hull = convex_hull(tuple((player.x_m, player.y_m) for player in players))
            team_hulls[group_id] = hull
            pairwise = tuple(_distance(left, right) for left, right in combinations(players, 2))
            minimum_met = count >= minimum_players
            rms = math.sqrt(sum(_distance(player, centroid) ** 2 for player in players) / count)
            quality = {
                "minimum_players_met": minimum_met,
                "player_count": count,
                "missing_rows": frame.missing_rows,
                "outside_pitch_rows": frame.outside_rows,
                "extrapolated_rows": frame.extrapolated_rows,
                "duplicate_rows": frame.duplicate_rows,
                "attacking_direction": "unavailable",
            }
            row = _row_context(
                dataset_id=dataset_id,
                session_id=session_id,
                trial_id=trial_id,
                stream_id=stream_id,
                coordinate_frame_id=frame_id,
                input_measurement_class=input_class,
                timestamp=frame.t_rel_ns,
                quality=quality,
            )
            row.update(
                {
                    "group_id": group_id,
                    "player_count": count,
                    "centroid_x_m": centroid[0],
                    "centroid_y_m": centroid[1],
                    "length_m": (max(xs) - min(xs)) if minimum_met else None,
                    "width_m": (max(ys) - min(ys)) if minimum_met else None,
                    "length_width_ratio": (
                        (max(xs) - min(xs)) / (max(ys) - min(ys))
                        if minimum_met and max(ys) > min(ys)
                        else None
                    ),
                    "hull_area_m2": polygon_area(hull) if minimum_met else None,
                    "stretch_index": rms / pitch_diagonal if minimum_met else None,
                    "pairwise_distance_mean_m": (
                        sum(pairwise) / len(pairwise) if minimum_met and pairwise else None
                    ),
                    "pairwise_distance_min_m": min(pairwise) if minimum_met and pairwise else None,
                    "pairwise_distance_max_m": max(pairwise) if minimum_met and pairwise else None,
                    "ball_distance_to_centroid_m": (
                        _distance(centroid, frame.ball) if frame.ball is not None else None
                    ),
                    "hull_polygon_json": json.dumps(hull, separators=(",", ":")),
                }
            )
            team_rows.append(row)
            team_lengths[group_id].append(
                (
                    frame.t_rel_ns,
                    float(row["length_m"] or 0.0),
                    float(row["width_m"] or 0.0),
                )
            )
            for player in players:
                teammates = tuple(other for other in players if other.entity_id != player.entity_id)
                opponents = tuple(
                    other
                    for other_group, group_players in frame.groups.items()
                    if other_group != group_id
                    for other in group_players
                )
                player_quality = {
                    **quality,
                    "player_detected": player.is_detected,
                    "nearest_teammate_available": bool(teammates),
                    "nearest_opponent_available": bool(opponents),
                }
                player_row = _row_context(
                    dataset_id=dataset_id,
                    session_id=session_id,
                    trial_id=trial_id,
                    stream_id=stream_id,
                    coordinate_frame_id=frame_id,
                    input_measurement_class=input_class,
                    timestamp=frame.t_rel_ns,
                    quality=player_quality,
                )
                player_row.update(
                    {
                        "entity_id": player.entity_id,
                        "group_id": group_id,
                        "object_type": player.object_type,
                        "x_m": player.x_m,
                        "y_m": player.y_m,
                        "distance_to_team_centroid_m": _distance(player, centroid),
                        "nearest_teammate_distance_m": (
                            min((_distance(player, other) for other in teammates), default=None)
                        ),
                        "nearest_opponent_distance_m": (
                            min((_distance(player, other) for other in opponents), default=None)
                        ),
                    }
                )
                interpersonal_rows.append(player_row)
        for left_group, right_group in combinations(sorted(centroids), 2):
            relation_quality = {
                "group_count": len(centroids),
                "missing_rows": frame.missing_rows,
                "outside_pitch_rows": frame.outside_rows,
                "extrapolated_rows": frame.extrapolated_rows,
                "attacking_direction": "unavailable",
            }
            relation_row = _row_context(
                dataset_id=dataset_id,
                session_id=session_id,
                trial_id=trial_id,
                stream_id=stream_id,
                coordinate_frame_id=frame_id,
                input_measurement_class=input_class,
                timestamp=frame.t_rel_ns,
                quality=relation_quality,
            )
            relation_row.update(
                {
                    "group_a": left_group,
                    "group_b": right_group,
                    "inter_centroid_distance_m": _distance(
                        centroids[left_group], centroids[right_group]
                    ),
                    "hull_overlap_area_m2": convex_polygon_intersection_area(
                        team_hulls[left_group], team_hulls[right_group]
                    ),
                }
            )
            relation_rows.append(relation_row)

    previous: dict[str, tuple[int, float, float] | None] = {}
    for row in team_rows:
        group_id = str(row["group_id"])
        row["expansion_rate_x_m_s"] = None
        row["expansion_rate_y_m_s"] = None
        if row["length_m"] is None or row["width_m"] is None:
            previous[group_id] = None
            continue
        current = (int(row["t_rel_ns"]), float(row["length_m"]), float(row["width_m"]))
        before = previous.get(group_id)
        if before is not None:
            delta_s = (current[0] - before[0]) / 1_000_000_000
            if delta_s > 0:
                row["expansion_rate_x_m_s"] = (current[1] - before[1]) / delta_s
                row["expansion_rate_y_m_s"] = (current[2] - before[2]) / delta_s
        previous[group_id] = current

    spec = ProcessorSpec(
        algorithm_id=ALGORITHM_ID,
        name="Deterministic team and interpersonal tactical geometry",
        version=ALGORITHM_VERSION,
        description=(
            "Team geometry, interpersonal distances and frame-axis team relations from "
            "canonical tracking positions; no attack direction or possession is inferred."
        ),
        parameters=resolved,
    )
    series = [
        SeriesOutput(
            name="team_geometry",
            table=_series_table(
                team_rows,
                method="team centroid, frame-axis extent, convex hull and pairwise geometry",
                parameters=resolved,
            ),
        ),
        SeriesOutput(
            name="interpersonal",
            table=_series_table(
                interpersonal_rows,
                method="nearest teammate/opponent and distance-to-centroid geometry",
                parameters=resolved,
            ),
        ),
    ]
    if relation_rows:
        series.append(
            SeriesOutput(
                name="team_relations",
                table=_series_table(
                    relation_rows,
                    method="inter-team centroid separation and convex-hull overlap",
                    parameters=resolved,
                ),
            )
        )
    return ProcessorResult(
        spec=spec,
        series=tuple(series),
        diagnostics={
            "level": "A",
            "samples": len(frames),
            "entities": sum(len(players) for frame in frames for players in frame.groups.values()),
            "groups": sorted({group for frame in frames for group in frame.groups}),
            "input_measurement_class": input_class,
            "coordinate_frame_id": frame_id,
            "quality": {
                "missing_rows": sum(frame.missing_rows for frame in frames),
                "outside_pitch_rows": sum(frame.outside_rows for frame in frames),
                "extrapolated_rows": sum(frame.extrapolated_rows for frame in frames),
                "duplicate_rows": sum(frame.duplicate_rows for frame in frames),
                "attacking_direction": "unavailable",
            },
        },
    )


__all__ = [
    "ALGORITHM_ID",
    "ALGORITHM_VERSION",
    "DEFAULT_PARAMETERS",
    "convex_hull",
    "convex_polygon_intersection_area",
    "polygon_area",
    "process_tactical_geometry",
]
