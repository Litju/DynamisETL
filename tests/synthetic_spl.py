"""Structurally synthetic SPL free-throw trials.

These are **not** source data: two tiny JSON documents mirror the documented
provider structure (``tracking`` list of frames, ``data.player`` keypoint
mapping in feet, ``data.ball``) with deliberately different keypoint
availability across the 30 fps and 60 fps sessions. CI never downloads or
commits real SPL data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

KEY_2024 = "basketball/freethrow/data/2024-08-28/P0001/BB_FT_P0001_T0001.json"
KEY_2025 = "basketball/freethrow/data/2025-12-18/P0001/BB_FT_P0001_T0001.json"

KEYPOINTS_2024: tuple[str, ...] = (
    "NOSE",
    "NECK",
    "LEFT_SHOULDER",
    "MID_HIP",
    "LEFT_KNEE",
    "LEFT_ANKLE",
)
KEYPOINTS_2025: tuple[str, ...] = (
    "NOSE",
    "LEFT_EYE",
    "RIGHT_EYE",
    "NECK",
    "LEFT_SHOULDER",
    "RIGHT_SHOULDER",
    "LEFT_WRIST",
    "MID_HIP",
    "LEFT_KNEE",
    "RIGHT_KNEE",
    "LEFT_ANKLE",
    "RIGHT_ANKLE",
)
UNDOCUMENTED_2025 = "CUSTOM_MARKER"


def _point(x: float, y: float, z: float) -> list[float]:
    return [x, y, z]


def _trial_2024() -> dict[str, Any]:
    frames: list[dict[str, Any]] = []
    for frame_index in range(3):
        player: dict[str, Any] = {
            "NOSE": _point(1.0, 2.0, 3.0 + frame_index),
            "LEFT_SHOULDER": _point(1.5, 2.0, 2.2),
            "MID_HIP": _point(1.0, 2.0, 1.5),
            "LEFT_KNEE": _point(1.0, 2.0, 0.8),
            "LEFT_ANKLE": _point(1.0, 2.0, 0.2),
        }
        if frame_index == 1:
            player["LEFT_ANKLE"] = None  # explicit null: unavailable, never imputed
            # NECK is absent in this frame: a second explicit unavailable form.
        else:
            player["NECK"] = _point(1.0, 2.0, 2.5)
        frames.append(
            {
                "data": {
                    "player": player,
                    "ball": _point(1.0, 2.0, 3.0) if frame_index != 1 else None,
                }
            }
        )
    return {"tracking": frames}


def _trial_2025() -> dict[str, Any]:
    frames: list[dict[str, Any]] = []
    for frame_index in range(4):
        player: dict[str, Any] = {
            name: _point(1.0 + 0.1 * frame_index, float(index), 2.0 - index * 0.1)
            for index, name in enumerate(KEYPOINTS_2025)
        }
        player[UNDOCUMENTED_2025] = _point(0.5, 0.5, 0.5)
        if frame_index == 2:
            player["RIGHT_WRIST"] = None
        if frame_index == 3:
            player.pop("LEFT_EYE")
        frames.append(
            {
                "data": {
                    "player": player,
                    "ball": _point(2.0, 2.0, 3.5),
                }
            }
        )
    return {"tracking": frames}


def write_bundle(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    trial_2024 = root / "BB_FT_P0001_T0001_2024.json"
    trial_2025 = root / "BB_FT_P0001_T0001_2025.json"
    trial_2024.write_text(json.dumps(_trial_2024()), encoding="utf-8")
    trial_2025.write_text(json.dumps(_trial_2025()), encoding="utf-8")
    return {"trial_2024": trial_2024, "trial_2025": trial_2025}


__all__ = [
    "KEY_2024",
    "KEY_2025",
    "KEYPOINTS_2024",
    "KEYPOINTS_2025",
    "UNDOCUMENTED_2025",
    "write_bundle",
]
