"""Level B deterministic clipped Voronoi territory."""

from __future__ import annotations

from typing import Any

import pyarrow as pa

from dynamis.processors.spec import ProcessorResult, ProcessorSpec, SeriesOutput
from dynamis.processors.tactical_geometry import (
    ALGORITHM_VERSION,
    DEFAULT_PARAMETERS,
    PLAYER_TYPES,
    Position,
    _context,
    _frames,
    _row_context,
    _series_table,
    polygon_area,
)

ALGORITHM_ID = "tactical.spatial_territory"
TERRITORY_PARAMETERS: dict[str, Any] = {
    **DEFAULT_PARAMETERS,
    "territory_method": "bounded_clipped_voronoi",
    "duplicate_point_policy": "lexicographically_smallest_entity_owns_cell",
    "out_of_pitch_policy": "clamp_for_bounded_cell_and_flag",
}


def _rectangle(length: float, width: float) -> tuple[tuple[float, float], ...]:
    return (
        (-length / 2, -width / 2),
        (length / 2, -width / 2),
        (length / 2, width / 2),
        (-length / 2, width / 2),
    )


def _clip_half_plane(
    polygon: tuple[tuple[float, float], ...],
    a: float,
    b: float,
    c: float,
) -> tuple[tuple[float, float], ...]:
    """Keep ``a*x + b*y <= c`` with deterministic line intersections."""
    if not polygon:
        return ()
    output: list[tuple[float, float]] = []
    epsilon = 1e-12
    previous = polygon[-1]
    previous_value = a * previous[0] + b * previous[1] - c
    previous_inside = previous_value <= epsilon
    for current in polygon:
        current_value = a * current[0] + b * current[1] - c
        current_inside = current_value <= epsilon
        if current_inside != previous_inside:
            denominator = previous_value - current_value
            if abs(denominator) > epsilon:
                fraction = previous_value / denominator
                output.append(
                    (
                        previous[0] + fraction * (current[0] - previous[0]),
                        previous[1] + fraction * (current[1] - previous[1]),
                    )
                )
        if current_inside:
            output.append(current)
        previous = current
        previous_value = current_value
        previous_inside = current_inside
    return tuple(output)


def _cell(
    player: Position,
    players: tuple[Position, ...],
    *,
    length: float,
    width: float,
) -> tuple[tuple[float, float], ...]:
    """Return one player cell in the finite pitch rectangle."""
    x = min(length / 2, max(-length / 2, player.x_m))
    y = min(width / 2, max(-width / 2, player.y_m))
    points = {
        other.entity_id: (
            min(length / 2, max(-length / 2, other.x_m)),
            min(width / 2, max(-width / 2, other.y_m)),
        )
        for other in players
    }
    same_point_ids = sorted(
        entity_id
        for entity_id, point in points.items()
        if point == (x, y)
    )
    if same_point_ids and player.entity_id != same_point_ids[0]:
        return ()
    polygon = _rectangle(length, width)
    for other in players:
        if other.entity_id == player.entity_id:
            continue
        ox, oy = points[other.entity_id]
        dx, dy = ox - x, oy - y
        if abs(dx) < 1e-12 and abs(dy) < 1e-12:
            continue
        polygon = _clip_half_plane(
            polygon,
            2.0 * dx,
            2.0 * dy,
            ox * ox + oy * oy - x * x - y * y,
        )
    return polygon


def _third_area(
    cell: tuple[tuple[float, float], ...], *, length: float, width: float, third: int
) -> float:
    if not cell:
        return 0.0
    start = -length / 2 + third * length / 3
    end = start + length / 3
    clipped = _clip_half_plane(cell, -1.0, 0.0, -start)
    clipped = _clip_half_plane(clipped, 1.0, 0.0, end)
    return polygon_area(clipped)


def _quality(frame, *, player_count: int, duplicate_count: int) -> dict[str, Any]:
    return {
        "player_count": player_count,
        "missing_rows": frame.missing_rows,
        "outside_pitch_rows": frame.outside_rows,
        "extrapolated_rows": frame.extrapolated_rows,
        "duplicate_rows": frame.duplicate_rows,
        "coincident_point_count": duplicate_count,
        "territory_semantics": "geometric_control_not_possession_probability",
        "free_space": "unassigned_space_not_defined_by_this_method",
        "attacking_direction": "unavailable; thirds are frame-axis thirds",
    }


def process_tactical_territory(
    table: pa.Table, *, parameters: dict[str, Any] | None = None
) -> ProcessorResult:
    """Compute bounded player cells and team control from canonical tracking rows."""
    resolved = dict(TERRITORY_PARAMETERS)
    if parameters:
        resolved.update(parameters)
    if float(resolved["pitch_length_m"]) <= 0 or float(resolved["pitch_width_m"]) <= 0:
        raise ValueError(f"{ALGORITHM_ID}: pitch dimensions must be positive")
    dataset_id, session_id, trial_id, stream_id, frame_id, input_class = _context(table)
    frames = _frames(table, resolved)
    if not frames:
        raise ValueError(f"{ALGORITHM_ID}: no timestamps with canonical tracking rows")
    length = float(resolved["pitch_length_m"])
    width = float(resolved["pitch_width_m"])
    pitch_area = length * width
    player_rows: list[dict[str, Any]] = []
    team_rows: list[dict[str, Any]] = []

    for frame in frames:
        all_players = tuple(
            player
            for group in frame.groups.values()
            for player in group
            if player.object_type in PLAYER_TYPES
        )
        point_counts: dict[tuple[float, float], int] = {}
        for player in all_players:
            point = (
                min(length / 2, max(-length / 2, player.x_m)),
                min(width / 2, max(-width / 2, player.y_m)),
            )
            point_counts[point] = point_counts.get(point, 0) + 1
        cells = {
            player.entity_id: _cell(
                player,
                all_players,
                length=length,
                width=width,
            )
            for player in all_players
        }
        duplicate_count = sum(count - 1 for count in point_counts.values() if count > 1)
        cell_areas = {entity_id: polygon_area(cell) for entity_id, cell in cells.items()}
        for group_id, players in frame.groups.items():
            group_quality = _quality(
                frame,
                player_count=len(players),
                duplicate_count=duplicate_count,
            )
            area = sum(cell_areas[player.entity_id] for player in players)
            team_row = _row_context(
                dataset_id=dataset_id,
                session_id=session_id,
                trial_id=trial_id,
                stream_id=stream_id,
                coordinate_frame_id=frame_id,
                input_measurement_class=input_class,
                timestamp=frame.t_rel_ns,
                quality=group_quality,
            )
            team_row.update(
                {
                    "group_id": group_id,
                    "player_count": len(players),
                    "controlled_area_m2": area,
                    "control_percentage": 100.0 * area / pitch_area,
                    "frame_third_0_area_m2": sum(
                        _third_area(cells[player.entity_id], length=length, width=width, third=0)
                        for player in players
                    ),
                    "frame_third_1_area_m2": sum(
                        _third_area(cells[player.entity_id], length=length, width=width, third=1)
                        for player in players
                    ),
                    "frame_third_2_area_m2": sum(
                        _third_area(cells[player.entity_id], length=length, width=width, third=2)
                        for player in players
                    ),
                }
            )
            team_rows.append(team_row)
        for player in all_players:
            quality = _quality(
                frame,
                player_count=len(frame.groups[player.group_id]),
                duplicate_count=duplicate_count,
            )
            player_row = _row_context(
                dataset_id=dataset_id,
                session_id=session_id,
                trial_id=trial_id,
                stream_id=stream_id,
                coordinate_frame_id=frame_id,
                input_measurement_class=input_class,
                timestamp=frame.t_rel_ns,
                quality=quality,
            )
            player_row.update(
                {
                    "entity_id": player.entity_id,
                    "group_id": player.group_id,
                    "object_type": player.object_type,
                    "cell_area_m2": cell_areas[player.entity_id],
                    "cell_percentage": 100.0 * cell_areas[player.entity_id] / pitch_area,
                    "frame_third_0_area_m2": _third_area(
                        cells[player.entity_id], length=length, width=width, third=0
                    ),
                    "frame_third_1_area_m2": _third_area(
                        cells[player.entity_id], length=length, width=width, third=1
                    ),
                    "frame_third_2_area_m2": _third_area(
                        cells[player.entity_id], length=length, width=width, third=2
                    ),
                }
            )
            player_rows.append(player_row)

    spec = ProcessorSpec(
        algorithm_id=ALGORITHM_ID,
        name="Clipped player Voronoi territory",
        version=ALGORITHM_VERSION,
        description=(
            "Bounded geometric player and team control regions clipped to the declared "
            "pitch; not possession or arrival-time probability."
        ),
        parameters=resolved,
    )
    return ProcessorResult(
        spec=spec,
        series=(
            SeriesOutput(
                name="player_territory",
                table=_series_table(
                    player_rows,
                    method="bounded clipped player Voronoi cells",
                    parameters=resolved,
                ),
            ),
            SeriesOutput(
                name="team_territory",
                table=_series_table(
                    team_rows,
                    method="sum of bounded player cells by declared team",
                    parameters=resolved,
                ),
            ),
        ),
        diagnostics={
            "level": "B",
            "samples": len(frames),
            "entities": sum(len(players) for frame in frames for players in frame.groups.values()),
            "pitch_area_m2": pitch_area,
            "input_measurement_class": input_class,
            "coordinate_frame_id": frame_id,
            "territory_semantics": "geometric_control_not_possession_probability",
            "quality": {
                "outside_pitch_rows": sum(frame.outside_rows for frame in frames),
                "extrapolated_rows": sum(frame.extrapolated_rows for frame in frames),
                "duplicate_rows": sum(frame.duplicate_rows for frame in frames),
            },
        },
    )


__all__ = ["ALGORITHM_ID", "process_tactical_territory"]
