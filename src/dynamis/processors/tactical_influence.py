"""Level C transparent kinematic arrival-time and influence processor."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from typing import Any, cast

import pyarrow as pa

from dynamis.processors.spec import ProcessorResult, ProcessorSpec, SeriesOutput
from dynamis.processors.tactical_geometry import (
    DEFAULT_PARAMETERS,
    PLAYER_TYPES,
    _context,
    _frames,
    _row_context,
)

ALGORITHM_ID = "tactical.arrival_time"
ALGORITHM_VERSION = "1"
INFLUENCE_PARAMETERS: dict[str, Any] = {
    **DEFAULT_PARAMETERS,
    "reaction_time_s": 0.25,
    "max_speed_m_s": 7.0,
    "max_acceleration_m_s2": 3.0,
    "grid_x": 21,
    "grid_y": 14,
    "grid_interval_ns": 1_000_000_000,
    "max_velocity_gap_s": 0.25,
}


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def _velocity_map(
    table: pa.Table, *, max_gap_s: float
) -> tuple[dict[tuple[int, str], tuple[float, float, str]], dict[str, int]]:
    rows_by_entity: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in table.to_pylist():
        if str(row.get("object_type") or "") not in PLAYER_TYPES:
            continue
        if not row.get("object_id") or not row.get("group_id"):
            continue
        if _finite(row.get("x_m")) and _finite(row.get("y_m")):
            rows_by_entity[(str(row["group_id"]), str(row["object_id"]))].append(row)
    result: dict[tuple[int, str], tuple[float, float, str]] = {}
    counts = {"provided": 0, "derived": 0, "zero_fallback": 0}
    for (_group_id, entity_id), rows in rows_by_entity.items():
        ordered = sorted(rows, key=lambda row: int(row["t_rel_ns"]))
        previous: dict[str, Any] | None = None
        for row in ordered:
            timestamp = int(row["t_rel_ns"])
            vx, vy = row.get("vx_m_s"), row.get("vy_m_s")
            if _finite(vx) and _finite(vy):
                result[(timestamp, entity_id)] = (
                    float(cast(float, vx)),
                    float(cast(float, vy)),
                    "provider",
                )
                counts["provided"] += 1
            elif previous is not None:
                delta_s = (timestamp - int(previous["t_rel_ns"])) / 1_000_000_000
                if 0 < delta_s <= max_gap_s:
                    result[(timestamp, entity_id)] = (
                        (float(cast(float, row["x_m"])) - float(cast(float, previous["x_m"])))
                        / delta_s,
                        (float(cast(float, row["y_m"])) - float(cast(float, previous["y_m"])))
                        / delta_s,
                        "position_first_difference",
                    )
                    counts["derived"] += 1
                else:
                    result[(timestamp, entity_id)] = (0.0, 0.0, "zero_fallback")
                    counts["zero_fallback"] += 1
            else:
                result[(timestamp, entity_id)] = (0.0, 0.0, "zero_fallback")
                counts["zero_fallback"] += 1
            previous = row
    return result, counts


def _travel_time(
    distance_m: float, initial_speed_m_s: float, *, max_speed_m_s: float, acceleration_m_s2: float
) -> float:
    if distance_m <= 0:
        return 0.0
    initial = min(max(0.0, initial_speed_m_s), max_speed_m_s)
    if acceleration_m_s2 <= 0:
        return distance_m / max(max_speed_m_s, 1e-12)
    distance_to_cap = max(0.0, (max_speed_m_s**2 - initial**2) / (2.0 * acceleration_m_s2))
    if distance_m <= distance_to_cap:
        return (
            -initial + math.sqrt(initial**2 + 2.0 * acceleration_m_s2 * distance_m)
        ) / acceleration_m_s2
    return (max_speed_m_s - initial) / acceleration_m_s2 + (
        distance_m - distance_to_cap
    ) / max_speed_m_s


def arrival_time_seconds(
    position: tuple[float, float],
    velocity: tuple[float, float],
    target: tuple[float, float],
    *,
    reaction_time_s: float,
    max_speed_m_s: float,
    max_acceleration_m_s2: float,
) -> float:
    """Evaluate the frozen bounded kinematic arrival-time model."""
    speed = math.hypot(*velocity)
    if speed > max_speed_m_s > 0:
        scale = max_speed_m_s / speed
        velocity = (velocity[0] * scale, velocity[1] * scale)
        speed = max_speed_m_s
    reaction_position = (
        position[0] + velocity[0] * reaction_time_s,
        position[1] + velocity[1] * reaction_time_s,
    )
    initial_speed = min(max_speed_m_s, speed + max_acceleration_m_s2 * reaction_time_s)
    distance = math.hypot(target[0] - reaction_position[0], target[1] - reaction_position[1])
    return reaction_time_s + _travel_time(
        distance,
        initial_speed,
        max_speed_m_s=max_speed_m_s,
        acceleration_m_s2=max_acceleration_m_s2,
    )


def _grid(
    length: float, width: float, grid_x: int, grid_y: int
) -> tuple[tuple[int, int, float, float], ...]:
    return tuple(
        (
            x_index,
            y_index,
            -length / 2 + (x_index + 0.5) * length / grid_x,
            -width / 2 + (y_index + 0.5) * width / grid_y,
        )
        for x_index in range(grid_x)
        for y_index in range(grid_y)
    )


def _model_row_context(**kwargs: Any) -> dict[str, Any]:
    row = _row_context(**kwargs)
    row["measurement_class"] = "MODEL_ESTIMATED"
    row["model_semantics"] = "bounded_kinematic_arrival_time"
    return row


def _model_series_table(
    rows: list[dict[str, Any]], *, method: str, parameters: dict[str, Any]
) -> pa.Table:
    if not rows:
        raise ValueError(f"{ALGORITHM_ID}: no influence rows")
    table = pa.Table.from_pylist(rows)
    metadata = dict(table.schema.metadata or {})
    metadata.update(
        {
            b"dynamis.contract": b"tactical_dense_series",
            b"dynamis.measurement_class": b"MODEL_ESTIMATED",
            b"dynamis.method": method.encode(),
            b"dynamis.algorithm_id": ALGORITHM_ID.encode(),
            b"dynamis.algorithm_version": ALGORITHM_VERSION.encode(),
            b"dynamis.parameters": json.dumps(
                parameters, sort_keys=True, separators=(",", ":")
            ).encode(),
        }
    )
    return table.replace_schema_metadata(metadata)


def process_tactical_influence(
    table: pa.Table, *, parameters: dict[str, Any] | None = None
) -> ProcessorResult:
    """Compute exact-frame arrival summaries and sampled bounded influence grids."""
    resolved = dict(INFLUENCE_PARAMETERS)
    if parameters:
        resolved.update(parameters)
    for name in ("reaction_time_s", "max_acceleration_m_s2"):
        if float(resolved[name]) < 0:
            raise ValueError(f"{ALGORITHM_ID}: {name} must be non-negative")
    if float(resolved["max_speed_m_s"]) <= 0:
        raise ValueError(f"{ALGORITHM_ID}: max_speed_m_s must be positive")
    if int(resolved["grid_x"]) < 1 or int(resolved["grid_y"]) < 1:
        raise ValueError(f"{ALGORITHM_ID}: grid dimensions must be positive")
    if int(resolved["grid_interval_ns"]) <= 0:
        raise ValueError(f"{ALGORITHM_ID}: grid_interval_ns must be positive")
    dataset_id, session_id, trial_id, stream_id, frame_id, input_class = _context(table)
    frames = _frames(table, resolved)
    if not frames:
        raise ValueError(f"{ALGORITHM_ID}: no timestamps with canonical tracking rows")
    velocities, velocity_counts = _velocity_map(
        table, max_gap_s=float(resolved["max_velocity_gap_s"])
    )
    length = float(resolved["pitch_length_m"])
    width = float(resolved["pitch_width_m"])
    grid = _grid(length, width, int(resolved["grid_x"]), int(resolved["grid_y"]))
    cell_area = length * width / len(grid)
    team_rows: list[dict[str, Any]] = []
    player_rows: list[dict[str, Any]] = []
    grid_rows: list[dict[str, Any]] = []
    last_grid_time: int | None = None
    for frame in frames:
        players = tuple(
            player
            for group in frame.groups.values()
            for player in group
            if player.object_type in PLAYER_TYPES
        )
        arrivals_for_frame: dict[str, tuple[float, float, str]] = {}
        for player in players:
            vx, vy, source = velocities.get(
                (frame.t_rel_ns, player.entity_id), (0.0, 0.0, "zero_fallback")
            )
            arrivals_for_frame[player.entity_id] = (vx, vy, source)
        player_cells: dict[str, int] = defaultdict(int)
        group_cells: dict[str, int] = defaultdict(int)
        should_emit_grid = last_grid_time is None or frame.t_rel_ns - last_grid_time >= int(
            resolved["grid_interval_ns"]
        )
        for cell_x, cell_y, x, y in grid:
            ranked = sorted(
                (
                    arrival_time_seconds(
                        (player.x_m, player.y_m),
                        arrivals_for_frame[player.entity_id][:2],
                        (x, y),
                        reaction_time_s=float(resolved["reaction_time_s"]),
                        max_speed_m_s=float(resolved["max_speed_m_s"]),
                        max_acceleration_m_s2=float(resolved["max_acceleration_m_s2"]),
                    ),
                    player.group_id,
                    player.entity_id,
                )
                for player in players
            )
            if not ranked:
                continue
            arrival, group_id, entity_id = ranked[0]
            player_cells[entity_id] += 1
            group_cells[group_id] += 1
            if should_emit_grid:
                grid_quality = {
                    "grid_sampled": True,
                    "grid_interval_ns": int(resolved["grid_interval_ns"]),
                    "input_measurement_class": input_class,
                    "provider_extrapolated_rows": frame.extrapolated_rows,
                    "attacking_direction": "not used",
                }
                grid_row = _model_row_context(
                    dataset_id=dataset_id,
                    session_id=session_id,
                    trial_id=trial_id,
                    stream_id=stream_id,
                    coordinate_frame_id=frame_id,
                    input_measurement_class=input_class,
                    timestamp=frame.t_rel_ns,
                    quality=grid_quality,
                )
                grid_row.update(
                    {
                        "cell_x": cell_x,
                        "cell_y": cell_y,
                        "x_m": x,
                        "y_m": y,
                        "cell_area_m2": cell_area,
                        "owner_entity_id": entity_id,
                        "owner_group_id": group_id,
                        "arrival_time_s": arrival,
                    }
                )
                grid_rows.append(grid_row)
        if should_emit_grid:
            last_grid_time = frame.t_rel_ns
        for group_id, group_players in frame.groups.items():
            quality = {
                "player_count": len(group_players),
                "grid_cells": len(grid),
                "grid_sampled": should_emit_grid,
                "velocity_counts": velocity_counts,
                "provider_extrapolated_rows": frame.extrapolated_rows,
                "model_semantics": "minimum_kinematic_arrival_time",
                "pressure_on_ball": "unavailable_without_source_resolved_ball_carrier",
            }
            row = _model_row_context(
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
                    "player_count": len(group_players),
                    "controlled_area_m2": group_cells[group_id] * cell_area,
                    "influence_percentage": 100.0 * group_cells[group_id] / len(grid),
                    "grid_cells_controlled": group_cells[group_id],
                }
            )
            team_rows.append(row)
        for player in players:
            velocity = arrivals_for_frame[player.entity_id]
            opponent_arrivals = [
                arrival_time_seconds(
                    (opponent.x_m, opponent.y_m),
                    arrivals_for_frame[opponent.entity_id][:2],
                    (player.x_m, player.y_m),
                    reaction_time_s=float(resolved["reaction_time_s"]),
                    max_speed_m_s=float(resolved["max_speed_m_s"]),
                    max_acceleration_m_s2=float(resolved["max_acceleration_m_s2"]),
                )
                for other_group, group_players in frame.groups.items()
                if other_group != player.group_id
                for opponent in group_players
            ]
            row = _model_row_context(
                dataset_id=dataset_id,
                session_id=session_id,
                trial_id=trial_id,
                stream_id=stream_id,
                coordinate_frame_id=frame_id,
                input_measurement_class=input_class,
                timestamp=frame.t_rel_ns,
                quality={
                    "velocity_source": velocity[2],
                    "provider_extrapolated_rows": frame.extrapolated_rows,
                    "model_semantics": "minimum_kinematic_arrival_time",
                    "pressure_on_ball": "unavailable_without_source_resolved_ball_carrier",
                },
            )
            row.update(
                {
                    "entity_id": player.entity_id,
                    "group_id": player.group_id,
                    "x_m": player.x_m,
                    "y_m": player.y_m,
                    "velocity_x_m_s": velocity[0],
                    "velocity_y_m_s": velocity[1],
                    "velocity_source": velocity[2],
                    "influence_area_m2": player_cells[player.entity_id] * cell_area,
                    "influence_percentage": 100.0 * player_cells[player.entity_id] / len(grid),
                    "opponent_min_arrival_time_s": min(opponent_arrivals, default=None),
                    "arrival_time_to_ball_s": (
                        arrival_time_seconds(
                            (player.x_m, player.y_m),
                            velocity[:2],
                            frame.ball,
                            reaction_time_s=float(resolved["reaction_time_s"]),
                            max_speed_m_s=float(resolved["max_speed_m_s"]),
                            max_acceleration_m_s2=float(resolved["max_acceleration_m_s2"]),
                        )
                        if frame.ball is not None
                        else None
                    ),
                }
            )
            player_rows.append(row)
    spec = ProcessorSpec(
        algorithm_id=ALGORITHM_ID,
        name="Bounded kinematic arrival-time influence",
        version=ALGORITHM_VERSION,
        description=(
            "Model-estimated arrival times and dominant influence from declared planar "
            "position/velocity/capacity assumptions; pressure and possession are not inferred."
        ),
        parameters=resolved,
    )
    return ProcessorResult(
        spec=spec,
        series=(
            SeriesOutput(
                name="team_influence",
                table=_model_series_table(
                    team_rows,
                    method="team dominant region from minimum bounded kinematic arrival time",
                    parameters=resolved,
                ),
            ),
            SeriesOutput(
                name="player_influence",
                table=_model_series_table(
                    player_rows,
                    method="player arrival time, influence area and opponent minimum arrival",
                    parameters=resolved,
                ),
            ),
            SeriesOutput(
                name="influence_grid",
                table=_model_series_table(
                    grid_rows,
                    method="sampled bounded influence grid",
                    parameters=resolved,
                ),
            ),
        ),
        diagnostics={
            "level": "C",
            "samples": len(frames),
            "entities": sum(len(players) for frame in frames for players in frame.groups.values()),
            "grid_samples": len({row["t_rel_ns"] for row in grid_rows}),
            "grid_cells_per_sample": len(grid),
            "input_measurement_class": input_class,
            "coordinate_frame_id": frame_id,
            "velocity_counts": velocity_counts,
            "model_semantics": "minimum_kinematic_arrival_time",
            "pressure_on_ball": "unavailable_without_source_resolved_ball_carrier",
        },
    )


__all__ = [
    "ALGORITHM_ID",
    "arrival_time_seconds",
    "process_tactical_influence",
]
