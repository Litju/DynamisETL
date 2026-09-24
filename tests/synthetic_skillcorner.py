"""Structurally synthetic SkillCorner provider files.

These are **not** source data: a tiny match metadata document, a 10 Hz tracking
JSONL and a 25 Hz pose ZIP whose structure mirrors the real provider exactly
(keys, units, joint mapping, frame relation). CI never downloads or commits real
SkillCorner data.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from dynamis.adapters.skillcorner.authorities import POSE_LANDMARKS

HOME_TEAM_ID = 1
AWAY_TEAM_ID = 2
PLAYERS = (
    (101, HOME_TEAM_ID, 7, "Home One"),
    (102, HOME_TEAM_ID, 9, "Home Two"),
    (201, AWAY_TEAM_ID, 3, "Away One"),
    (202, AWAY_TEAM_ID, 11, "Away Two"),
)

PERIODS = ((1, 0, 4), (2, 10, 12))


def _timestamp(*, second_half: bool, offset_s: float) -> str:
    base_s = 45 * 60 if second_half else 0
    total = base_s + offset_s
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    centiseconds = round((seconds - int(seconds)) * 100)
    whole_seconds = int(seconds)
    if centiseconds == 100:
        centiseconds = 0
        whole_seconds += 1
    return f"{int(hours):02d}:{int(minutes):02d}:{whole_seconds:02d}.{centiseconds:02d}"


def write_match_json(path: Path) -> Path:
    document: dict[str, Any] = {
        "id": 9000001,
        "date_time": "2025-01-01T10:00:00Z",
        "pitch_length": 105,
        "pitch_width": 68,
        "home_team_score": 2,
        "away_team_score": 1,
        "home_team": {"id": HOME_TEAM_ID, "name": "Synthetic Home"},
        "away_team": {"id": AWAY_TEAM_ID, "name": "Synthetic Away"},
        "stadium": {"id": 1, "name": "Synthetic Park"},
        "home_team_side": ["left_to_right", "right_to_left"],
        "match_periods": [
            {
                "period": period,
                "name": f"period_{period}",
                "start_frame": start,
                "end_frame": end,
                "duration_frames": end - start + 1,
                "duration_minutes": (end - start + 1) / 600.0,
            }
            for period, start, end in PERIODS
        ],
        "players": [
            {
                "id": player_id,
                "team_id": team_id,
                "number": number,
                "short_name": name,
                "trackable_object": 50000 + player_id,
                "player_role": (
                    {
                        "id": 1,
                        "position_group": "Other",
                        "name": "Goalkeeper",
                        "acronym": "GK",
                    }
                    if player_id == 101
                    else {
                        "id": 1,
                        "position_group": "Midfield",
                        "name": "Central Midfield",
                        "acronym": "CM",
                    }
                ),
            }
            for player_id, team_id, number, name in PLAYERS
        ],
    }
    path.write_text(json.dumps(document, indent=1), encoding="utf-8")
    return path


def write_tracking_jsonl(path: Path) -> Path:
    lines: list[str] = []
    for period, start, end in PERIODS:
        second_half = period == 2
        for frame in range(start, end + 1):
            offset = (frame - start) / 10.0
            players = []
            for index, (player_id, team_id, _, _) in enumerate(PLAYERS):
                direction = 1.0 if team_id == HOME_TEAM_ID else -1.0
                players.append(
                    {
                        "x": direction * (frame + index),
                        "y": float(index),
                        "player_id": player_id,
                        "is_detected": (frame + index) % 2 == 0,
                    }
                )
            ball: dict[str, Any] = {"x": None, "y": None, "z": None, "is_detected": None}
            if (frame - start) % 2 == 0:
                ball = {
                    "x": float(frame),
                    "y": 1.0,
                    "z": None if frame == start else 0.5,
                    "is_detected": frame == start,
                }
            lines.append(
                json.dumps(
                    {
                        "frame": frame,
                        "timestamp": _timestamp(second_half=second_half, offset_s=offset),
                        "period": period,
                        "ball_data": ball,
                        "possession": {"player_id": None, "group": None},
                        "image_corners_projection": {
                            "x_top_left": None,
                            "y_top_left": None,
                            "x_bottom_left": None,
                            "y_bottom_left": None,
                            "x_bottom_right": None,
                            "y_bottom_right": None,
                            "x_top_right": None,
                            "y_top_right": None,
                        },
                        "player_data": players,
                    }
                )
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def joints_for(*, player_id: int, frame: int, perturb_m: float = 0.0) -> dict[str, Any]:
    joints: dict[str, Any] = {}
    for index, name in enumerate(POSE_LANDMARKS):
        if name == "neck" and frame == 5 and player_id == 101:
            joints[name] = {"xyz": [None, None, None], "p90_mae_cm": 2.0}
            continue
        joints[name] = {
            "xyz": [frame * 0.4 + index * 0.01 + perturb_m, 0.2, 0.3 + index * 0.01],
            "p90_mae_cm": 1.0 + index,
        }
    return joints


def pose_frame(frame: int, *, period: int) -> dict[str, Any]:
    second_half = period == 2
    start = 25 if second_half else 0
    offset = (frame - start) / 25.0
    players: list[dict[str, Any]] = []
    for player_id, _, _, _ in PLAYERS:
        if player_id in (201, 202):
            continue
        resolved = frame % 5 == 0 and (player_id == 101 or frame % 10 == 0)
        if player_id == 102 and frame % 2 != 0:
            continue
        players.append(
            {
                "player_id": player_id,
                "x": frame * 0.4 + (0.1 if frame == 5 and player_id == 101 else 0.0),
                "y": 0.2,
                "is_detected": resolved,
                "joints": (
                    joints_for(
                        player_id=player_id,
                        frame=frame,
                        perturb_m=0.0,
                    )
                    if resolved
                    else None
                ),
            }
        )
    return {
        "frame": frame,
        "timestamp": _timestamp(second_half=second_half, offset_s=offset),
        "period": period,
        "ball_data": {"x": None, "y": None, "z": None, "is_detected": None},
        "possession": {"player_id": None, "group": None},
        "image_corners_projection": {
            "x_top_left": None,
            "y_top_left": None,
            "x_bottom_left": None,
            "y_bottom_left": None,
            "x_bottom_right": None,
            "y_bottom_right": None,
            "x_top_right": None,
            "y_top_right": None,
        },
        "player_data": players,
    }


def write_pose_zip(path: Path, *, match_id: int = 9000001) -> Path:
    frames: list[str] = []
    for period, _start, _end in PERIODS:
        first = 25 if period == 2 else 0
        last = 30 if period == 2 else 10
        for frame in range(first, last + 1):
            frames.append(json.dumps(pose_frame(frame, period=period)))
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{match_id}.jsonl", "\n".join(frames) + "\n")
    return path


def write_skillcorner_bundle(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    return {
        "match_json": write_match_json(root / "9000001_match.json"),
        "tracking": write_tracking_jsonl(root / "9000001_tracking_extrapolated.jsonl"),
        "pose_zip": write_pose_zip(root / "9000001.jsonl.zip"),
    }


__all__ = [
    "PLAYERS",
    "joints_for",
    "pose_frame",
    "write_match_json",
    "write_pose_zip",
    "write_skillcorner_bundle",
    "write_tracking_jsonl",
]
