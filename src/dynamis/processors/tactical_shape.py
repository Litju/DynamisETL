"""RES-110 MatchLab Tactical V3 roster, shape, and interaction geometry."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pyarrow as pa
from scipy.spatial import Delaunay, QhullError

from dynamis.processors.spec import ProcessorResult, ProcessorSpec, SeriesOutput

ALGORITHM_ID = "tactical.matchlab_shape"
ALGORITHM_VERSION = "1"
ROLE_DOMAINS = ("GK", "DEF", "MID", "ATT", "unknown")
PLAYER_TYPES = frozenset({"player", "goalkeeper"})
REQUIRED_COLUMNS = frozenset(
    {
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
)
DEFAULT_PARAMETERS: dict[str, Any] = {
    "pitch_length_m": 105.0,
    "pitch_width_m": 68.0,
    "stable_window_ns": 1_000_000_000,
    "stable_minimum_coverage_ns": 800_000_000,
    "stable_minimum_fraction": 0.8,
    "persistence_max_gap_ns": 200_000_000,
    "local_overload_radius_m": 10.0,
    "triangle_area_epsilon_m2": 1e-9,
    "coincident_player_policy": "lexicographically_smallest_player_id",
    "delaunay_library": "scipy.spatial.Delaunay",
}


@dataclass(frozen=True, slots=True)
class _Player:
    entity_id: str
    group_id: str
    x_m: float
    y_m: float
    role: str
    is_detected: bool | None


@dataclass(frozen=True, slots=True)
class _Frame:
    trial_id: str
    t_rel_ns: int
    groups: dict[str, tuple[_Player, ...]]
    ball: tuple[float, float] | None
    missing_rows: int
    outside_pitch_rows: int
    extrapolated_rows: int
    duplicate_rows: int


def _point_in_triangle(
    point: tuple[float, float], triangle: tuple[tuple[float, float], ...]
) -> bool:
    x, y = point
    signs = tuple(
        (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])
        for a, b in zip(triangle, (*triangle[1:], triangle[0]), strict=True)
    )
    return all(value >= -1e-10 for value in signs) or all(value <= 1e-10 for value in signs)


def _orientation(points: tuple[tuple[float, float], ...]) -> tuple[float | None, float, float]:
    """Principal-axis angle [0,180) and major/minor standard deviations."""
    if len(points) < 2:
        return None, 0.0, 0.0
    mean_x = sum(point[0] for point in points) / len(points)
    mean_y = sum(point[1] for point in points) / len(points)
    xx = sum((x - mean_x) ** 2 for x, _ in points) / len(points)
    yy = sum((y - mean_y) ** 2 for _, y in points) / len(points)
    xy = sum((x - mean_x) * (y - mean_y) for x, y in points) / len(points)
    root = math.sqrt(max(0.0, (xx - yy) ** 2 + 4 * xy * xy))
    major = max(0.0, (xx + yy + root) / 2)
    minor = max(0.0, (xx + yy - root) / 2)
    if root <= 1e-12:
        return None, math.sqrt(major), math.sqrt(minor)
    angle = math.degrees(0.5 * math.atan2(2 * xy, xx - yy)) % 180.0
    return angle, math.sqrt(major), math.sqrt(minor)


def _delaunay(
    players: tuple[_Player, ...], *, direction: str | None
) -> tuple[set[tuple[str, str]], set[tuple[str, str, str]]]:
    flip = -1.0 if direction == "right_to_left" else 1.0
    by_point: dict[tuple[float, float], _Player] = {}
    for player in sorted(players, key=lambda item: item.entity_id):
        point = (player.x_m * flip, player.y_m * flip)
        by_point.setdefault(point, player)
    points = sorted(by_point.items(), key=lambda item: item[1].entity_id)
    if len(points) < 3:
        return set(), set()
    coordinates = np.asarray([point for point, _ in points], dtype=np.float64)
    try:
        simplices = Delaunay(coordinates).simplices
    except QhullError:
        return set(), set()
    triangles: set[tuple[str, str, str]] = set()
    for simplex in simplices:
        triangle = sorted(by_point[tuple(coordinates[index])].entity_id for index in simplex)
        triangles.add((triangle[0], triangle[1], triangle[2]))
    edges: set[tuple[str, str]] = set()
    for triangle in triangles:
        for left, right in (
            (triangle[0], triangle[1]),
            (triangle[0], triangle[2]),
            (triangle[1], triangle[2]),
        ):
            edges.add((left, right) if left < right else (right, left))
    return edges, triangles


def _series_table(
    rows: list[dict[str, Any]],
    *,
    series_name: str,
    parameters: Mapping[str, Any],
    measurement_class: str = "PIPELINE_DERIVED",
    null_types: Mapping[str, pa.DataType] | None = None,
) -> pa.Table | None:
    if not rows:
        return None
    table = pa.Table.from_pylist(rows)
    for name, dtype in (null_types or {}).items():
        index = table.schema.get_field_index(name)
        if index >= 0 and pa.types.is_null(table.schema.field(index).type):
            table = table.set_column(index, name, pa.array([None] * table.num_rows, type=dtype))
    metadata = dict(table.schema.metadata or {})
    metadata.update(
        {
            b"dynamis.contract": b"tactical_dense_series",
            b"dynamis.measurement_class": measurement_class.encode(),
            b"dynamis.algorithm_id": ALGORITHM_ID.encode(),
            b"dynamis.algorithm_version": ALGORITHM_VERSION.encode(),
            b"dynamis.series_name": series_name.encode(),
            b"dynamis.metric_authority": b"architecture/tactical-metrics.json",
            b"dynamis.parameters": json.dumps(
                dict(parameters), sort_keys=True, separators=(",", ":")
            ).encode(),
        }
    )
    return table.replace_schema_metadata(metadata)


def _parameters(parameters: Mapping[str, Any] | None) -> dict[str, Any]:
    resolved = dict(DEFAULT_PARAMETERS)
    if parameters:
        resolved.update(parameters)
    if float(resolved["pitch_length_m"]) <= 0 or float(resolved["pitch_width_m"]) <= 0:
        raise ValueError(f"{ALGORITHM_ID}: pitch dimensions must be positive")
    if int(resolved["stable_window_ns"]) <= 0 or int(resolved["stable_minimum_coverage_ns"]) < 0:
        raise ValueError(f"{ALGORITHM_ID}: persistence window parameters are invalid")
    if not 0 < float(resolved["stable_minimum_fraction"]) <= 1:
        raise ValueError(f"{ALGORITHM_ID}: stable_minimum_fraction must be in (0, 1]")
    if float(resolved["local_overload_radius_m"]) <= 0:
        raise ValueError(f"{ALGORITHM_ID}: local_overload_radius_m must be positive")
    return resolved


def _frames(
    table: pa.Table,
    *,
    role_by_player: Mapping[str, str],
    pitch_length_m: float,
    pitch_width_m: float,
) -> tuple[_Frame, ...]:
    missing = REQUIRED_COLUMNS - set(table.column_names)
    if missing:
        raise ValueError(f"{ALGORITHM_ID}: missing tracking columns {sorted(missing)}")
    if table.num_rows == 0:
        raise ValueError(f"{ALGORITHM_ID}: tracking table is empty")
    if (
        len(set(table.column("trial_id").to_pylist())) != 1
        or len(set(table.column("stream_id").to_pylist())) != 1
    ):
        raise ValueError(f"{ALGORITHM_ID}: process one stream/period at a time")
    grouped: dict[tuple[str, int], dict[str, dict[str, _Player]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    balls: dict[tuple[str, int], tuple[float, float]] = {}
    quality: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for row in table.to_pylist():
        trial_id = str(row.get("trial_id") or "")
        timestamp = int(row["t_rel_ns"])
        key = (trial_id, timestamp)
        if row.get("x_m") is None or row.get("y_m") is None:
            quality[key][0] += 1
            continue
        x, y = float(row["x_m"]), float(row["y_m"])
        if not (math.isfinite(x) and math.isfinite(y)):
            quality[key][0] += 1
            continue
        if not (-pitch_length_m / 2 <= x <= pitch_length_m / 2) or not (
            -pitch_width_m / 2 <= y <= pitch_width_m / 2
        ):
            quality[key][1] += 1
        if row.get("is_detected") is False:
            quality[key][2] += 1
        object_type = str(row.get("object_type") or "")
        if object_type == "ball":
            current = balls.get(key)
            candidate = (x, y)
            if current is not None:
                quality[key][3] += 1
            if current is None or candidate < current:
                balls[key] = candidate
            continue
        group_id = str(row.get("group_id") or "")
        object_id = str(row.get("object_id") or "")
        if object_type not in PLAYER_TYPES or not group_id or not object_id:
            continue
        if object_id in grouped[key][group_id]:
            quality[key][3] += 1
            continue
        role = str(role_by_player.get(object_id, "unknown")).strip()
        role = "unknown" if role.casefold() == "unknown" else role.upper()
        if role not in ROLE_DOMAINS:
            raise ValueError(f"{ALGORITHM_ID}: unsupported source role {role!r}")
        grouped[key][group_id][object_id] = _Player(
            entity_id=object_id,
            group_id=group_id,
            x_m=x,
            y_m=y,
            role=role,
            is_detected=row.get("is_detected"),
        )
    return tuple(
        _Frame(
            trial_id=trial_id,
            t_rel_ns=timestamp,
            groups={
                group_id: tuple(sorted(players.values(), key=lambda item: item.entity_id))
                for group_id, players in sorted(groups.items())
            },
            ball=balls.get((trial_id, timestamp)),
            missing_rows=quality[(trial_id, timestamp)][0],
            outside_pitch_rows=quality[(trial_id, timestamp)][1],
            extrapolated_rows=quality[(trial_id, timestamp)][2],
            duplicate_rows=quality[(trial_id, timestamp)][3],
        )
        for (trial_id, timestamp), groups in sorted(grouped.items())
    )


def _source_context(
    possession: pa.Table | None,
) -> dict[tuple[str, int], dict[str, Any]]:
    if possession is None or possession.num_rows == 0:
        return {}
    required = {"trial_id", "t_rel_ns", "team_id", "player_id", "ball_status"}
    missing = required - set(possession.column_names)
    if missing:
        raise ValueError(f"{ALGORITHM_ID}: possession table missing {sorted(missing)}")
    if "measurement_class" in possession.column_names:
        classes = set(possession.column("measurement_class").to_pylist())
        if classes != {"SOURCE_DERIVED"}:
            raise ValueError(f"{ALGORITHM_ID}: possession input must be SOURCE_DERIVED")
    result: dict[tuple[str, int], dict[str, Any]] = {}
    for row in possession.to_pylist():
        key = (str(row.get("trial_id") or ""), int(row["t_rel_ns"]))
        value = {
            "team_id": None if row.get("team_id") is None else str(row["team_id"]),
            "player_id": None if row.get("player_id") is None else str(row["player_id"]),
            "ball_status": (None if row.get("ball_status") is None else str(row["ball_status"])),
        }
        if key in result and result[key] != value:
            raise ValueError(f"{ALGORITHM_ID}: conflicting source possession at {key}")
        result[key] = value
    return result


def _frame_row(
    *,
    context: Mapping[str, Any],
    frame: _Frame,
    group_id: str,
    direction: str | None,
    input_class: str,
    role_authority: str,
    direction_authority: str,
    possession_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    transform = "team_attack_positive_x" if direction else "source_frame"
    players = frame.groups.get(group_id, ())
    role_counts = Counter(player.role for player in players)
    quality = {
        "input_measurement_classes": sorted(input_class.split(",")),
        "player_count": len(players),
        "role_counts": dict(sorted(role_counts.items())),
        "unknown_role_count": role_counts.get("unknown", 0),
        "role_authority": role_authority,
        "attacking_direction_available": direction is not None,
        "missing_coordinate_rows": frame.missing_rows,
        "outside_pitch_rows": frame.outside_pitch_rows,
        "extrapolated_rows": frame.extrapolated_rows,
        "duplicate_rows": frame.duplicate_rows,
        "source_possession_frame_present": possession_context is not None,
        "source_possession_known": (
            possession_context is not None and possession_context["team_id"] is not None
        ),
    }
    return {
        **context,
        "source_coordinate_frame_id": context["coordinate_frame_id"],
        "coordinate_frame_id": (
            f"{context['coordinate_frame_id']}:team-attack-positive-x:v1"
            if direction
            else context["coordinate_frame_id"]
        ),
        "trial_id": frame.trial_id,
        "t_rel_ns": frame.t_rel_ns,
        "group_id": group_id,
        "measurement_class": "PIPELINE_DERIVED",
        "input_measurement_class": input_class,
        "attacking_direction": direction,
        "coordinate_normalization": transform,
        "role_authority": role_authority,
        "direction_authority": direction_authority,
        "source_possession_team_id": (
            None if possession_context is None else possession_context["team_id"]
        ),
        "source_possession_player_id": (
            None if possession_context is None else possession_context["player_id"]
        ),
        "source_ball_status": (
            None if possession_context is None else possession_context["ball_status"]
        ),
        "source_possession_measurement_class": (
            "SOURCE_DERIVED" if possession_context is not None else None
        ),
        "quality_json": json.dumps(quality, sort_keys=True, separators=(",", ":")),
    }


def _window_statistics(
    samples: list[tuple[int, set[Any], set[Any]]],
    *,
    window_ns: int,
    max_gap_ns: int,
) -> dict[int, tuple[Counter[Any], Counter[Any], int, int]]:
    """Rolling edge/triangle counts, valid-frame denominator, and coverage."""
    output: dict[int, tuple[Counter[Any], Counter[Any], int, int]] = {}
    edges: Counter[Any] = Counter()
    triangles: Counter[Any] = Counter()
    window: deque[tuple[int, set[Any], set[Any]]] = deque()
    previous: int | None = None
    for index, sample in enumerate(samples):
        timestamp, frame_edges, frame_triangles = sample
        if previous is not None and timestamp - previous > max_gap_ns:
            window.clear()
            edges.clear()
            triangles.clear()
        previous = timestamp
        window.append(sample)
        edges.update(frame_edges)
        triangles.update(frame_triangles)
        while window and timestamp - window[0][0] > window_ns:
            _, old_edges, old_triangles = window.popleft()
            edges.subtract(old_edges)
            triangles.subtract(old_triangles)
        edges += Counter()
        triangles += Counter()
        coverage_ns = timestamp - window[0][0] if window else 0
        output[index] = (edges.copy(), triangles.copy(), len(window), coverage_ns)
    return output


def process_tactical_shape(
    tracking: pa.Table,
    *,
    role_by_player: Mapping[str, str],
    attacking_direction_by_team: Mapping[str, str] | None = None,
    possession: pa.Table | None = None,
    role_authority: str = "source_roster_position_v1",
    direction_authority: str = "unavailable",
    parameters: Mapping[str, Any] | None = None,
) -> ProcessorResult:
    """Compute roster functional units, persistent Delaunay shape, and context."""
    resolved = _parameters(parameters)
    directions = dict(attacking_direction_by_team or {})
    if any(value not in {"left_to_right", "right_to_left"} for value in directions.values()):
        raise ValueError(f"{ALGORITHM_ID}: directions must be declared source values")
    frames = _frames(
        tracking,
        role_by_player=role_by_player,
        pitch_length_m=float(resolved["pitch_length_m"]),
        pitch_width_m=float(resolved["pitch_width_m"]),
    )
    if not frames:
        raise ValueError(f"{ALGORITHM_ID}: no finite tracking players")
    first = tracking.slice(0, 1).to_pylist()[0]
    context = {
        "dataset_id": str(first["dataset_id"]),
        "session_id": str(first["session_id"]),
        "stream_id": str(first["stream_id"]),
        "coordinate_frame_id": str(first["coordinate_frame_id"]),
    }
    input_classes = set(tracking.column("measurement_class").to_pylist())
    input_class = ",".join(sorted(str(value) for value in input_classes))
    possession_by_time = _source_context(possession)
    source_group_ids = sorted({group for frame in frames for group in frame.groups})
    all_timestamps = sorted({frame.t_rel_ns for frame in frames})
    by_time = {(frame.trial_id, frame.t_rel_ns): frame for frame in frames}
    role_rows: list[dict[str, Any]] = []
    edge_rows: list[dict[str, Any]] = []
    triangle_rows: list[dict[str, Any]] = []
    interaction_rows: list[dict[str, Any]] = []
    possession_rows: list[dict[str, Any]] = []
    shape_samples: dict[str, list[tuple[int, set[Any], set[Any]]]] = {
        group: [] for group in source_group_ids
    }
    shape_frames: dict[tuple[str, int, str], tuple[tuple[_Player, ...], set[Any], set[Any]]] = {}
    triangle_rows_by_key: dict[tuple[str, int, str, tuple[str, str, str]], dict[str, Any]] = {}
    pitch_length = float(resolved["pitch_length_m"])
    pitch_width = float(resolved["pitch_width_m"])
    minimum_x, maximum_x = -pitch_length / 2, pitch_length / 2
    minimum_y, maximum_y = -pitch_width / 2, pitch_width / 2
    gap_by_frame: dict[tuple[int, str], dict[str, float | None]] = {}

    for frame in frames:
        source_possession = possession_by_time.get((frame.trial_id, frame.t_rel_ns))
        if source_possession is not None:
            possession_rows.append(
                {
                    "dataset_id": context["dataset_id"],
                    "session_id": context["session_id"],
                    "trial_id": frame.trial_id,
                    "stream_id": context["stream_id"],
                    "t_rel_ns": frame.t_rel_ns,
                    "coordinate_frame_id": context["coordinate_frame_id"],
                    "measurement_class": "SOURCE_DERIVED",
                    "source_possession_team_id": source_possession["team_id"],
                    "source_possession_player_id": source_possession["player_id"],
                    "source_ball_status": source_possession["ball_status"],
                    "source_possession_known": source_possession["team_id"] is not None,
                    "quality_json": json.dumps(
                        {
                            "source_measurement_class": "SOURCE_DERIVED",
                            "source_possession_known": source_possession["team_id"] is not None,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            )
        for group_id in source_group_ids:
            players = frame.groups.get(group_id, ())
            if not players:
                shape_samples[group_id].append((frame.t_rel_ns, set(), set()))
                continue
            direction = directions.get(group_id)
            flip = -1.0 if direction == "right_to_left" else 1.0
            local = {player.entity_id: (player.x_m * flip, player.y_m * flip) for player in players}
            unit_centres: dict[str, tuple[float, float]] = {}
            for role in ROLE_DOMAINS:
                members = tuple(player for player in players if player.role == role)
                if not members:
                    continue
                points = tuple(local[player.entity_id] for player in members)
                xs = tuple(point[0] for point in points)
                ys = tuple(point[1] for point in points)
                centroid = (sum(xs) / len(xs), sum(ys) / len(ys))
                unit_centres[role] = centroid
                orientation, major_sd, minor_sd = _orientation(points)
                rms = math.sqrt(
                    sum((x - centroid[0]) ** 2 + (y - centroid[1]) ** 2 for x, y in points)
                    / len(points)
                )
                row = _frame_row(
                    context=context,
                    frame=frame,
                    group_id=group_id,
                    direction=direction,
                    input_class=input_class,
                    role_authority=role_authority,
                    direction_authority=direction_authority,
                    possession_context=source_possession,
                )
                row.update(
                    {
                        "functional_unit": role,
                        "player_count": len(members),
                        "centroid_x_m": centroid[0],
                        "centroid_y_m": centroid[1],
                        "line_height_x_m": centroid[0],
                        "depth_x_m": max(xs) - min(xs),
                        "width_y_m": max(ys) - min(ys),
                        "dispersion_rms_m": rms,
                        "major_axis_sd_m": major_sd,
                        "minor_axis_sd_m": minor_sd,
                        "orientation_deg": orientation,
                        "def_mid_gap_m": None,
                        "mid_att_gap_m": None,
                        "outfield_block_depth_m": None,
                        "role_ids_json": json.dumps(
                            [player.entity_id for player in members], separators=(",", ":")
                        ),
                    }
                )
                role_rows.append(row)
            def_mid = (
                abs(unit_centres["DEF"][0] - unit_centres["MID"][0])
                if "DEF" in unit_centres and "MID" in unit_centres
                else None
            )
            mid_att = (
                abs(unit_centres["MID"][0] - unit_centres["ATT"][0])
                if "MID" in unit_centres and "ATT" in unit_centres
                else None
            )
            outfield = tuple(player for player in players if player.role in {"DEF", "MID", "ATT"})
            block_depth = (
                max(local[player.entity_id][0] for player in outfield)
                - min(local[player.entity_id][0] for player in outfield)
                if outfield
                else None
            )
            gap_by_frame[(frame.t_rel_ns, group_id)] = {
                "def_mid": def_mid,
                "mid_att": mid_att,
                "block_depth": block_depth,
            }
            for row in role_rows[-len(unit_centres) :]:
                row["def_mid_gap_m"] = def_mid
                row["mid_att_gap_m"] = mid_att
                row["outfield_block_depth_m"] = block_depth

            edges, triangles = _delaunay(players, direction=direction)
            shape_samples[group_id].append((frame.t_rel_ns, edges, triangles))
            shape_frames[(frame.trial_id, frame.t_rel_ns, group_id)] = (players, edges, triangles)

            # Interactions use the shared source frame, so distance is not
            # distorted by independently normalizing both opposing teams.
            attackers = tuple(player for player in players if player.role == "ATT")
            defenders = tuple(
                opponent
                for other_group, other_players in frame.groups.items()
                if other_group != group_id
                for opponent in other_players
                if opponent.role == "DEF"
            )
            if attackers and defenders:
                opposing_attacker_nearest: dict[str, str] = {}
                for defender in defenders:
                    opposing_attacker_nearest[defender.entity_id] = min(
                        attackers,
                        key=lambda attacker: (
                            math.hypot(attacker.x_m - defender.x_m, attacker.y_m - defender.y_m),
                            attacker.entity_id,
                        ),
                    ).entity_id
                radius = float(resolved["local_overload_radius_m"])
                for attacker in attackers:
                    ordered = sorted(
                        (
                            math.hypot(attacker.x_m - defender.x_m, attacker.y_m - defender.y_m),
                            defender.entity_id,
                        )
                        for defender in defenders
                    )
                    nearest_id = ordered[0][1]
                    tied = opposing_attacker_nearest[nearest_id] == attacker.entity_id
                    nearby_att = sum(
                        1
                        for player in players
                        if player.role == "ATT"
                        and math.hypot(attacker.x_m - player.x_m, attacker.y_m - player.y_m)
                        <= radius
                    )
                    nearby_def = sum(
                        1
                        for defender in defenders
                        if math.hypot(attacker.x_m - defender.x_m, attacker.y_m - defender.y_m)
                        <= radius
                    )
                    row = _frame_row(
                        context=context,
                        frame=frame,
                        group_id=group_id,
                        direction=direction,
                        input_class=input_class,
                        role_authority=role_authority,
                        direction_authority=direction_authority,
                        possession_context=source_possession,
                    )
                    row.update(
                        {
                            "attacker_id": attacker.entity_id,
                            "nearest_defender_id": nearest_id,
                            "nearest_defender_distance_m": ordered[0][0],
                            "second_nearest_defender_id": (
                                ordered[1][1] if len(ordered) > 1 else None
                            ),
                            "second_nearest_defender_distance_m": (
                                ordered[1][0] if len(ordered) > 1 else None
                            ),
                            "geometric_tie_up": tied,
                            "geometric_free_attacker": not tied,
                            "local_radius_m": radius,
                            "local_attacker_count": nearby_att,
                            "local_defender_count": nearby_def,
                            "local_overload_margin_players": nearby_att - nearby_def,
                        }
                    )
                    interaction_rows.append(row)

            # Raw coordinates are shared by both teams. Use the focal team's
            # transform for both groups before constructing triangle context.
            frame_all_players = tuple(
                player for group_players in frame.groups.values() for player in group_players
            )
            transformed = {
                player.entity_id: (player.x_m * flip, player.y_m * flip)
                for player in frame_all_players
            }
            ball = None if frame.ball is None else (frame.ball[0] * flip, frame.ball[1] * flip)
            zones_have_direction = direction is not None
            for triangle_ids in sorted(triangles):
                triangle = tuple(local[player_id] for player_id in triangle_ids)
                area = abs(
                    sum(
                        triangle[index][0] * triangle[(index + 1) % 3][1]
                        - triangle[(index + 1) % 3][0] * triangle[index][1]
                        for index in range(3)
                    )
                    / 2
                )
                if area <= float(resolved["triangle_area_epsilon_m2"]):
                    continue
                sides = tuple(
                    math.hypot(
                        triangle[index][0] - triangle[(index + 1) % 3][0],
                        triangle[index][1] - triangle[(index + 1) % 3][1],
                    )
                    for index in range(3)
                )
                centroid = (
                    sum(point[0] for point in triangle) / 3,
                    sum(point[1] for point in triangle) / 3,
                )
                outside = not (
                    minimum_x <= centroid[0] <= maximum_x and minimum_y <= centroid[1] <= maximum_y
                )
                if outside:
                    zone = "out_of_bounds"
                elif zones_have_direction:
                    zone = (
                        "own_third"
                        if centroid[0] < -pitch_length / 6
                        else "opponent_third"
                        if centroid[0] >= pitch_length / 6
                        else "middle_third"
                    )
                else:
                    zone = (
                        "left_third"
                        if centroid[0] < -pitch_length / 6
                        else "right_third"
                        if centroid[0] >= pitch_length / 6
                        else "center_third"
                    )
                opponents = tuple(
                    player
                    for other_group, other_players in frame.groups.items()
                    if other_group != group_id
                    for player in other_players
                )
                opponent_count = sum(
                    1
                    for opponent in opponents
                    if _point_in_triangle(transformed[opponent.entity_id], triangle)
                )
                same_distances = tuple(
                    (
                        math.hypot(
                            local[player.entity_id][0] - centroid[0],
                            local[player.entity_id][1] - centroid[1],
                        ),
                        group_id,
                        player.entity_id,
                    )
                    for player in players
                )
                other_distances = tuple(
                    (
                        math.hypot(
                            transformed[player.entity_id][0] - centroid[0],
                            transformed[player.entity_id][1] - centroid[1],
                        ),
                        other_group,
                        player.entity_id,
                    )
                    for other_group, other_players in frame.groups.items()
                    if other_group != group_id
                    for player in other_players
                )
                owner = min((*same_distances, *other_distances), default=None)
                distance_margin = (
                    min(item[0] for item in other_distances)
                    - min(item[0] for item in same_distances)
                    if other_distances and same_distances
                    else None
                )
                row = _frame_row(
                    context=context,
                    frame=frame,
                    group_id=group_id,
                    direction=direction,
                    input_class=input_class,
                    role_authority=role_authority,
                    direction_authority=direction_authority,
                    possession_context=source_possession,
                )
                row.update(
                    {
                        "triangle_player_ids_json": json.dumps(triangle_ids, separators=(",", ":")),
                        "area_m2": area,
                        "aspect_ratio": max(sides) / min(sides),
                        "orientation_deg": _orientation(triangle)[0],
                        "centroid_x_m": centroid[0],
                        "centroid_y_m": centroid[1],
                        "ball_distance_m": (
                            None
                            if ball is None
                            else math.hypot(ball[0] - centroid[0], ball[1] - centroid[1])
                        ),
                        "zone": zone,
                        "zone_frame": "team_attack_normalized" if direction else "source_frame",
                        "opponent_count_inside": opponent_count,
                        "opponent_density_per_m2": opponent_count / area,
                        "nearest_team_at_centroid": None if owner is None else owner[1],
                        "nearest_team_distance_margin_m": distance_margin,
                        "triangle_persistence_fraction": 0.0,
                        "persistence_window_frames": 0,
                        "stable_triangle": False,
                    }
                )
                triangle_rows.append(row)
                triangle_rows_by_key[(frame.trial_id, frame.t_rel_ns, group_id, triangle_ids)] = row

    # Convert per-frame triangle persistence into stable-edge authority.
    for group_id, samples in shape_samples.items():
        stats = _window_statistics(
            samples,
            window_ns=int(resolved["stable_window_ns"]),
            max_gap_ns=int(resolved["persistence_max_gap_ns"]),
        )
        frame_number_by_time = {sample[0]: index for index, sample in enumerate(samples)}
        trial_id = str(first.get("trial_id") or "")
        for timestamp in all_timestamps:
            players_edges = shape_frames.get((trial_id, timestamp, group_id))
            if players_edges is None:
                continue
            _players, raw_edges, raw_triangles = players_edges
            index = frame_number_by_time[timestamp]
            edge_counts, triangle_counts, window_frames, coverage_ns = stats[index]
            enough_coverage = coverage_ns >= int(resolved["stable_minimum_coverage_ns"])
            direction = directions.get(group_id)
            frame = by_time[(trial_id, timestamp)]
            source_possession = possession_by_time.get((frame.trial_id, timestamp))
            for edge in sorted(raw_edges):
                fraction = edge_counts[edge] / window_frames if window_frames else 0.0
                row = _frame_row(
                    context=context,
                    frame=frame,
                    group_id=group_id,
                    direction=direction,
                    input_class=input_class,
                    role_authority=role_authority,
                    direction_authority=direction_authority,
                    possession_context=source_possession,
                )
                row.update(
                    {
                        "player_a_id": edge[0],
                        "player_b_id": edge[1],
                        "raw_delaunay_edge": True,
                        "edge_persistence_fraction": fraction,
                        "persistence_window_frames": window_frames,
                        "stable_edge": enough_coverage
                        and fraction >= float(resolved["stable_minimum_fraction"]),
                    }
                )
                edge_rows.append(row)
            triangle_persistence = {
                triangle_id: count / window_frames if window_frames else 0.0
                for triangle_id, count in triangle_counts.items()
            }
            for triangle_id in raw_triangles:
                row = triangle_rows_by_key.get((trial_id, timestamp, group_id, triangle_id))
                if row is None:
                    continue
                fraction = triangle_persistence.get(triangle_id, 0.0)
                row["triangle_persistence_fraction"] = fraction
                row["persistence_window_frames"] = window_frames
                row["stable_triangle"] = enough_coverage and fraction >= float(
                    resolved["stable_minimum_fraction"]
                )

    spec = ProcessorSpec(
        algorithm_id=ALGORITHM_ID,
        name="MatchLab Tactical V3 shape and interaction geometry",
        version=ALGORITHM_VERSION,
        description=(
            "Source-roster functional units, team-relative Delaunay stability, "
            "triangle context, and explicitly geometric attacker/defender descriptors."
        ),
        parameters=resolved,
    )
    outputs: list[SeriesOutput] = []
    for name, rows, null_types, measurement_class in (
        (
            "functional_unit_geometry",
            role_rows,
            {"orientation_deg": pa.float64()},
            "PIPELINE_DERIVED",
        ),
        (
            "shape_graph_edges",
            edge_rows,
            {
                "source_possession_team_id": pa.string(),
                "source_possession_player_id": pa.string(),
                "source_ball_status": pa.string(),
            },
            "PIPELINE_DERIVED",
        ),
        (
            "tactical_triangles",
            triangle_rows,
            {
                "ball_distance_m": pa.float64(),
                "orientation_deg": pa.float64(),
                "nearest_team_at_centroid": pa.string(),
                "nearest_team_distance_margin_m": pa.float64(),
            },
            "PIPELINE_DERIVED",
        ),
        (
            "attacker_defender_interactions",
            interaction_rows,
            {
                "second_nearest_defender_id": pa.string(),
                "second_nearest_defender_distance_m": pa.float64(),
            },
            "PIPELINE_DERIVED",
        ),
        ("source_possession_context", possession_rows, {}, "SOURCE_DERIVED"),
    ):
        table = _series_table(
            rows,
            series_name=name,
            parameters=resolved,
            measurement_class=measurement_class,
            null_types=null_types,
        )
        if table is not None:
            outputs.append(SeriesOutput(name=name, table=table))
    if not outputs:
        raise ValueError(f"{ALGORITHM_ID}: no functional tactical outputs were produced")
    return ProcessorResult(
        spec=spec,
        series=tuple(outputs),
        diagnostics={
            "level": "V3",
            "measurement_class": "PIPELINE_DERIVED",
            "source_context_class": "SOURCE_DERIVED",
            "role_authority": role_authority,
            "direction_authority": direction_authority,
            "directional_groups": sorted(directions),
            "possession_frames": len(possession_by_time),
            "source_possession_known_frames": sum(
                value["team_id"] is not None for value in possession_by_time.values()
            ),
            "frames": len(frames),
            "teams": source_group_ids,
            "functional_unit_rows": len(role_rows),
            "raw_delaunay_edge_rows": len(edge_rows),
            "raw_triangle_rows": len(triangle_rows),
            "attacker_defender_rows": len(interaction_rows),
            "phase_classifier_emitted": False,
        },
    )


__all__ = ["ALGORITHM_ID", "ALGORITHM_VERSION", "DEFAULT_PARAMETERS", "process_tactical_shape"]
