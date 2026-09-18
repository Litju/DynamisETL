"""Structural discovery receipts for the accepted SPL free-throw trials."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dynamis.adapters.spl.adapter import SplTrialSource
from dynamis.adapters.spl.authorities import SPL_KEYPOINTS
from dynamis.adapters.spl.trial import identity_from_key


@dataclass(frozen=True, slots=True)
class SplDiscovery:
    trials: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {"trials": list(self.trials)}


def discover_spl(trials: tuple[SplTrialSource, ...]) -> SplDiscovery:
    return SplDiscovery(trials=tuple(_inspect_trial(source) for source in trials))


def _inspect_trial(source: SplTrialSource) -> dict[str, Any]:
    identity = identity_from_key(source.key)
    document = json.loads(Path(source.path).read_text(encoding="utf-8"))
    frames = document.get("tracking") if isinstance(document, dict) else None
    keypoint_names: list[str] = []
    seen: set[str] = set()
    frames_with_player = 0
    null_values = 0
    ball_frames = 0
    ball_with_xyz = 0
    missing_by_keypoint: dict[str, int] = {}
    for raw in frames or []:
        if not isinstance(raw, dict):
            continue
        data = raw.get("data")
        if not isinstance(data, dict):
            continue
        player = data.get("player")
        if not isinstance(player, dict):
            continue
        frames_with_player += 1
        for name, value in player.items():
            name = str(name)
            if name not in seen:
                seen.add(name)
                keypoint_names.append(name)
            if value is None:
                null_values += 1
        ball = data.get("ball")
        if ball is not None:
            ball_frames += 1
            if (
                isinstance(ball, list)
                and len(ball) == 3
                and all(isinstance(component, (int, float)) for component in ball)
            ):
                ball_with_xyz += 1
        for name in seen:
            if name not in player:
                missing_by_keypoint[name] = missing_by_keypoint.get(name, 0) + 1
    return {
        "key": source.key,
        "session_date": identity.session_date,
        "participant_id": identity.participant_id,
        "trial_id": identity.trial_id,
        "size_bytes": Path(source.path).stat().st_size,
        "top_level_keys": sorted(document.keys()) if isinstance(document, dict) else [],
        "frame_count": len(frames) if isinstance(frames, list) else 0,
        "frames_with_player_mapping": frames_with_player,
        "observed_keypoints": len(keypoint_names),
        "observed_keypoint_names": keypoint_names,
        "documented_keypoint_count": len(SPL_KEYPOINTS),
        "null_keypoint_values": null_values,
        "missing_keypoint_observations": dict(sorted(missing_by_keypoint.items())),
        "ball_frames": ball_frames,
        "ball_frames_with_xyz": ball_with_xyz,
        "units_documented": "feet (README coordinate system and units)",
        "keypoint_availability": "session-specific across acquisition generations",
    }


__all__ = ["SplDiscovery", "discover_spl"]
