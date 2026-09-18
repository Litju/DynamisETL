"""Structural discovery receipts for a SkillCorner match slice.

Nothing is assumed from memory: the receipt records the match metadata, the
tracking JSONL structure (frames, periods, entries, identities, flags), the ZIP
central directory of the pose archive and the structure of its first record.
The ~3.3 GB pose member is never expanded for discovery; it is streamed at
ingestion time.
"""

from __future__ import annotations

import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dynamis.adapters.skillcorner.metadata import SkillCornerMatchMetadata
from dynamis.adapters.skillcorner.pose import pose_zip_member


@dataclass(frozen=True, slots=True)
class SkillCornerDiscovery:
    match: dict[str, Any]
    tracking: dict[str, Any]
    pose_archive: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "match": self.match,
            "tracking": self.tracking,
            "pose_archive": self.pose_archive,
        }


def discover_skillcorner(
    *,
    metadata: SkillCornerMatchMetadata,
    tracking_path: Path,
    pose_zip_path: Path,
) -> SkillCornerDiscovery:
    """Structural receipt for the pinned SkillCorner match slice."""
    tracking = _inspect_tracking(Path(tracking_path))
    pose_archive = _inspect_pose_archive(Path(pose_zip_path), match_id=metadata.match_id)
    return SkillCornerDiscovery(
        match={
            "match_id": metadata.match_id,
            "title": metadata.title,
            "kickoff_utc": metadata.kickoff_utc.isoformat(),
            "pitch_size_m": [metadata.pitch_length_m, metadata.pitch_width_m],
            "stadium": metadata.stadium,
            "periods": [period.to_dict() for period in metadata.periods],
            "player_count": len(metadata.players),
            "team_ids": sorted({player.team_id for player in metadata.players}),
            "position_groups": dict(
                sorted(
                    Counter(
                        player.position_group or "unspecified" for player in metadata.players
                    ).items()
                )
            ),
        },
        tracking=tracking,
        pose_archive=pose_archive,
    )


def _inspect_tracking(path: Path) -> dict[str, Any]:
    lines = 0
    timestamp_nulls = 0
    player_entries = 0
    ball_entries = 0
    ball_with_coordinates = 0
    detected_true = 0
    detected_false = 0
    player_ids: set[str] = set()
    frame_min: int | None = None
    frame_max: int | None = None
    period_ranges: dict[str, list[int]] = {}
    first_line_keys: list[str] | None = None
    import json

    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle):
            payload = json.loads(raw)
            if line_number == 0:
                first_line_keys = sorted(payload.keys())
            lines += 1
            frame = int(payload["frame"])
            frame_min = frame if frame_min is None else min(frame_min, frame)
            frame_max = frame if frame_max is None else max(frame_max, frame)
            period = payload.get("period")
            span = period_ranges.setdefault(
                "unknown" if period is None else str(period), [frame, frame]
            )
            span[0] = min(span[0], frame)
            span[1] = max(span[1], frame)
            if payload.get("timestamp") is None:
                timestamp_nulls += 1
            for entry in payload.get("player_data") or []:
                if not isinstance(entry, dict):
                    continue
                player_entries += 1
                if entry.get("player_id") is not None:
                    player_ids.add(str(entry["player_id"]))
                if entry.get("is_detected") is True:
                    detected_true += 1
                elif entry.get("is_detected") is False:
                    detected_false += 1
            ball = payload.get("ball_data")
            if ball is not None:
                ball_entries += 1
                if (
                    isinstance(ball, dict)
                    and ball.get("x") is not None
                    and ball.get("y") is not None
                ):
                    ball_with_coordinates += 1
    return {
        "source_file_key": path.name,
        "record_keys": first_line_keys,
        "lines": lines,
        "frame_min": frame_min,
        "frame_max": frame_max,
        "period_frame_ranges": {
            key: {"start": value[0], "end": value[1]}
            for key, value in sorted(period_ranges.items())
        },
        "timestamp_null_frames": timestamp_nulls,
        "player_entries": player_entries,
        "distinct_player_ids": len(player_ids),
        "player_ids": sorted(player_ids),
        "detected_true": detected_true,
        "detected_false": detected_false,
        "ball_entries": ball_entries,
        "ball_entries_with_xy": ball_with_coordinates,
    }


def _inspect_pose_archive(path: Path, *, match_id: str) -> dict[str, Any]:
    import json

    with zipfile.ZipFile(path) as archive:
        member = pose_zip_member(archive, match_id=match_id)
        entries = [
            {
                "name": info.filename,
                "file_size": info.file_size,
                "compress_size": info.compress_size,
                "crc": info.CRC,
            }
            for info in archive.infolist()
        ]
        info = archive.getinfo(member)
        with archive.open(member) as stream:
            first = json.loads(stream.readline())
    return {
        "source_file_key": path.name,
        "members": entries,
        "selected_member": member,
        "selected_member_file_size": info.file_size,
        "selected_member_compress_size": info.compress_size,
        "first_record_keys": sorted(first.keys()),
        "first_record_frame": first.get("frame"),
        "first_record_period": first.get("period"),
        "expansion_policy": (
            "member streamed directly from the ZIP at ingestion; the plaintext file is "
            "never expanded to disk"
        ),
    }


__all__ = ["SkillCornerDiscovery", "discover_skillcorner"]
