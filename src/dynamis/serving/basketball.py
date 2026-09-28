"""Bounded local reads for the SkillCorner basketball spatial surface."""

from __future__ import annotations

import json
from typing import Any

import duckdb

from dynamis.config import Settings
from dynamis.serving.dense import ArtifactPathError, resolve_artifact_path
from dynamis.serving.models import (
    ArtifactRefView,
    BasketballBallPointView,
    BasketballEventPage,
    BasketballEventView,
    BasketballFramePage,
    BasketballFrameView,
    BasketballPeriodRangeView,
    BasketballPlayerPointView,
    BasketballRosterPlayerView,
)

FEET_PER_METRE = 1.0 / 0.3048


def period_ranges(settings: Settings, artifact: ArtifactRefView) -> list[BasketballPeriodRangeView]:
    path = resolve_artifact_path(settings, artifact)
    with duckdb.connect() as connection:
        rows = connection.execute(
            """
            SELECT period_number, min(frame_idx),
                   min(frame_idx) FILTER (WHERE player_count > 0 OR ball_present),
                   max(frame_idx), count(*),
                   count(*) FILTER (WHERE is_dead_time)
            FROM read_parquet(?)
            GROUP BY period_number
            ORDER BY period_number
            """,
            [str(path)],
        ).fetchall()
    return [
        BasketballPeriodRangeView(
            number=int(number),
            label=f"Q{number}" if int(number) <= 4 else f"OT{int(number) - 4}",
            first_frame=int(first_frame),
            first_active_frame=int(first_active_frame or first_frame),
            last_frame=int(last_frame),
            frame_count=int(count),
            dead_time_frames=int(dead_time),
        )
        for number, first_frame, first_active_frame, last_frame, count, dead_time in rows
    ]


def read_frames(
    settings: Settings,
    *,
    contest_id: str,
    period: int,
    from_frame: int,
    limit: int,
    frame_clock: ArtifactRefView,
    tracking: list[ArtifactRefView],
    roster: list[BasketballRosterPlayerView],
) -> BasketballFramePage:
    frame_path = resolve_artifact_path(settings, frame_clock)
    with duckdb.connect() as connection:
        count_row = connection.execute(
            "SELECT count(*) FROM read_parquet(?) WHERE period_number = ?",
            [str(frame_path), period],
        ).fetchone()
        total = int(count_row[0]) if count_row is not None else 0
        clock_rows = connection.execute(
            """
            SELECT frame_idx, period_number, wall_clock_ms, canonical_time_ns,
                   game_clock_s, game_clock_stopped, shot_clock_s, player_count,
                   ball_present, is_dead_time
            FROM read_parquet(?)
            WHERE period_number = ? AND frame_idx >= ?
            ORDER BY frame_idx
            LIMIT ?
            """,
            [str(frame_path), period, from_frame, limit],
        ).fetchall()
    if not clock_rows:
        return BasketballFramePage(
            contest_id=contest_id,
            period=period,
            from_frame=from_frame,
            limit=limit,
            total_frames=total,
            rows=[],
        )

    time_min, time_max = int(clock_rows[0][3]), int(clock_rows[-1][3])
    tracking_paths = [str(resolve_artifact_path(settings, artifact)) for artifact in tracking]
    positions: dict[int, list[dict[str, Any]]] = {}
    if tracking_paths:
        with duckdb.connect() as connection:
            cursor = connection.execute(
                """
                SELECT t_rel_ns, object_id, object_type, subject_id, group_id,
                       x_m, y_m, z_m, is_detected
                FROM read_parquet(?)
                WHERE t_rel_ns BETWEEN ? AND ?
                ORDER BY t_rel_ns, object_type, object_id
                """,
                [tracking_paths, time_min, time_max],
            )
            for (
                time_ns,
                object_id,
                object_type,
                subject_id,
                team_id,
                x_m,
                y_m,
                z_m,
                detected,
            ) in cursor.fetchall():
                positions.setdefault(int(time_ns), []).append(
                    {
                        "provider_player_id": str(object_id),
                        "object_type": str(object_type),
                        "subject_id": str(subject_id) if subject_id is not None else None,
                        "team_id": str(team_id) if team_id is not None else None,
                        "x": float(x_m) * FEET_PER_METRE if x_m is not None else None,
                        "y": float(y_m) * FEET_PER_METRE if y_m is not None else None,
                        "z": float(z_m) * FEET_PER_METRE if z_m is not None else None,
                        "is_detected": bool(detected) if detected is not None else None,
                    }
                )
    names = {player.provider_player_id: player for player in roster}
    frames: list[BasketballFrameView] = []
    for row in clock_rows:
        (
            frame_idx,
            number,
            wall_ms,
            time_ns,
            game_clock,
            stopped,
            shot_clock,
            count,
            ball_present,
            dead,
        ) = row
        players: list[BasketballPlayerPointView] = []
        ball: BasketballBallPointView | None = None
        for point in positions.get(int(time_ns), []):
            if point["object_type"] == "ball":
                ball = BasketballBallPointView(
                    x=point["x"],
                    y=point["y"],
                    z=point["z"],
                    is_detected=point["is_detected"],
                )
                continue
            player = names.get(point["provider_player_id"])
            players.append(
                BasketballPlayerPointView(
                    subject_id=point["subject_id"]
                    or (player.subject_id if player else point["provider_player_id"]),
                    provider_player_id=point["provider_player_id"],
                    display_name=player.display_name if player else point["provider_player_id"],
                    jersey=player.jersey if player else None,
                    team_id=point["team_id"] or (player.team_id if player else None),
                    x=point["x"],
                    y=point["y"],
                    z=point["z"],
                    is_detected=point["is_detected"],
                )
            )
        frames.append(
            BasketballFrameView(
                frame_idx=int(frame_idx),
                period_number=int(number),
                wall_clock_ms=int(wall_ms),
                canonical_time_ns=int(time_ns),
                game_clock_s=float(game_clock) if game_clock is not None else None,
                game_clock_stopped=bool(stopped),
                shot_clock_s=float(shot_clock) if shot_clock is not None else None,
                player_count=int(count),
                ball_present=bool(ball_present),
                is_dead_time=bool(dead),
                players=players,
                ball=ball,
            )
        )
    return BasketballFramePage(
        contest_id=contest_id,
        period=period,
        from_frame=from_frame,
        limit=limit,
        total_frames=total,
        rows=frames,
    )


def read_events(
    settings: Settings,
    *,
    contest_id: str,
    period: int | None,
    limit: int,
    offset: int,
    artifact: ArtifactRefView,
) -> BasketballEventPage:
    path = resolve_artifact_path(settings, artifact)
    where = "contest_id = ?"
    params: list[Any] = [contest_id]
    if period is not None:
        where += " AND contest_period_id = ?"
        params.append(f"{contest_id}:period:{period}")
    with duckdb.connect() as connection:
        count_row = connection.execute(
            f"SELECT count(*) FROM read_parquet(?) WHERE {where}", [str(path), *params]
        ).fetchone()
        total = int(count_row[0]) if count_row is not None else 0
        cursor = connection.execute(
            f"""
            SELECT source_event_id, provider_event_type, contest_period_id, sequence_index,
                   canonical_time_ns, source_clock_json, team_id, subject_id, location,
                   attributes_json
            FROM read_parquet(?) WHERE {where}
            ORDER BY canonical_time_ns NULLS LAST, sequence_index
            LIMIT ? OFFSET ?
            """,
            [str(path), *params, limit, offset],
        )
        rows = cursor.fetchall()
    return BasketballEventPage(
        contest_id=contest_id,
        period=period,
        total=total,
        limit=limit,
        offset=offset,
        rows=[
            BasketballEventView(
                source_event_id=str(row[0]),
                provider_event_type=str(row[1]),
                contest_period_id=str(row[2]),
                sequence_index=str(row[3]),
                canonical_time_ns=int(row[4]) if row[4] is not None else None,
                source_clock=json.loads(row[5]) if row[5] else None,
                team_id=str(row[6]) if row[6] is not None else None,
                subject_id=str(row[7]) if row[7] is not None else None,
                location=row[8],
                attributes=json.loads(row[9]),
            )
            for row in rows
        ],
    )


def assert_basketball_artifact(ref: ArtifactRefView | None, *, kind: str) -> ArtifactRefView:
    if ref is None:
        raise ArtifactPathError(f"basketball {kind} has not been materialized")
    return ref
