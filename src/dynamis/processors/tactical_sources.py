"""Load only accepted source-side role/direction/possession context for V3."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import lxml.etree as etree

from dynamis.adapters.skillcorner.metadata import parse_match_metadata
from dynamis.adapters.skillcorner.tracking import match_time_ns
from dynamis.adapters.sportec_idsse.matchinfo import BALL_TEAM_ID, parse_match_information
from dynamis.adapters.sportec_idsse.positions import PERIOD_SECTIONS
from dynamis.config import Settings, repository_root
from dynamis.processors.runtime import ProcessorInput, collect_input

_POSSESSION_SCHEMA = pa.schema(
    [
        pa.field("trial_id", pa.string(), nullable=False),
        pa.field("t_rel_ns", pa.int64(), nullable=False),
        pa.field("team_id", pa.string()),
        pa.field("player_id", pa.string()),
        pa.field("ball_status", pa.string()),
        pa.field("measurement_class", pa.string(), nullable=False),
    ]
)
_SKILL_CORNER_GROUPS = {
    "goalkeeper": "GK",
    "central defender": "DEF",
    "full back": "DEF",
    "midfield": "MID",
    "center forward": "ATT",
    "wide attacker": "ATT",
}


@dataclass(frozen=True, slots=True)
class TacticalSourceAuthority:
    role_by_player: dict[str, str]
    attacking_direction_by_team: dict[str, str]
    possession: pa.Table
    inputs: tuple[ProcessorInput, ...]
    role_authority: str
    direction_authority: str
    possession_authority: str


def _authority() -> tuple[dict[str, Any], dict[str, Any]]:
    root = repository_root()
    capabilities = json.loads(
        (root / "sources" / "tactical-capability-matrix.json").read_text(encoding="utf-8")
    )
    metrics = json.loads(
        (root / "architecture" / "tactical-metrics.json").read_text(encoding="utf-8")
    )
    return capabilities, metrics["matchlab_tactical_v3"]["role_mappings"]


def _source_files(settings: Settings, dataset_id: str) -> tuple[Path, Path]:
    capabilities, _ = _authority()
    accepted = capabilities["datasets"][dataset_id]["accepted_slice"]
    version = accepted.get("version") or accepted.get("tracking_version")
    if not version:
        raise ValueError(f"{dataset_id}: accepted tactical source has no pinned version")
    base = settings.dataset_root / "bronze" / dataset_id / str(version)
    if dataset_id == "dfl-sportec-idsse":
        metadata = next(base.glob("*matchinformation*.xml"), None)
        tracking = next(base.glob("*positions_raw*.xml"), None)
    elif dataset_id == "skillcorner-opendata":
        match_id = str(accepted["match_id"])
        match_dir = base / "data" / "matches" / match_id
        metadata = match_dir / f"{match_id}_match.json"
        tracking = match_dir / f"{match_id}_tracking_extrapolated.jsonl"
    else:
        raise ValueError(f"{dataset_id}: no accepted Tactical V3 source authority")
    if metadata is None or tracking is None or not metadata.is_file() or not tracking.is_file():
        raise FileNotFoundError(f"{dataset_id}: accepted metadata/tracking source is unavailable")
    return metadata, tracking


def _verify_input_checksums(
    settings: Settings,
    dataset_id: str,
    *,
    metadata_path: Path,
    tracking_path: Path,
    metadata_rows: int,
    tracking_rows: int,
) -> tuple[ProcessorInput, ProcessorInput]:
    capabilities, _ = _authority()
    expected = {
        item["role"]: item["sha256"]
        for item in capabilities["datasets"][dataset_id]["accepted_slice"]["input_artifacts"]
    }
    metadata_input = collect_input(
        settings,
        metadata_path,
        role="source_match_metadata",
        row_count=metadata_rows,
    )
    tracking_input = collect_input(
        settings,
        tracking_path,
        role="source_tracking_context",
        row_count=tracking_rows,
    )
    expected_tracking_role = "tracking"
    expected_metadata_role = (
        "match_information" if dataset_id == "dfl-sportec-idsse" else "match_metadata"
    )
    for role, item in (
        (expected_tracking_role, tracking_input),
        (expected_metadata_role, metadata_input),
    ):
        if expected.get(role) != item.checksum_sha256:
            raise ValueError(
                f"{dataset_id}: {role} checksum differs from the accepted local artifact"
            )
    return metadata_input, tracking_input


def _dfl_authority(
    settings: Settings,
    *,
    metadata_path: Path,
    tracking_path: Path,
    trial_id: str,
    wanted_times: set[int],
) -> TacticalSourceAuthority:
    capabilities, _ = _authority()
    metadata = parse_match_information(metadata_path)
    code_map = _authority()[1]["dfl_sportec_playing_position"]
    roles = {
        player.person_id: str(code_map.get(player.playing_position or "", "unknown"))
        for player in metadata.players
    }
    if trial_id not in PERIOD_SECTIONS.values():
        raise ValueError(f"DFL: unsupported canonical period {trial_id!r}")
    trial_by_section = {value: key for key, value in PERIOD_SECTIONS.items()}
    wanted_section = trial_by_section[trial_id]
    kickoff_ns = int(metadata.kickoff_utc.timestamp() * 1_000_000_000)
    possession_rows: list[dict[str, Any]] = []
    current: dict[str, str | None] = {}
    for event, element in etree.iterparse(
        str(tracking_path), events=("start", "end"), tag=("FrameSet", "Frame")
    ):
        if event == "start" and element.tag == "FrameSet":
            current = {
                "section": element.get("GameSection"),
                "team_id": element.get("TeamId"),
            }
            continue
        if event != "end" or element.tag != "Frame":
            continue
        section = current.get("section")
        if section == wanted_section and current.get("team_id") == BALL_TEAM_ID:
            timestamp = element.get("T")
            if timestamp:
                parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                t_rel_ns = int(parsed.timestamp() * 1_000_000_000) - kickoff_ns
                if t_rel_ns in wanted_times:
                    code = element.get("BallPossession")
                    team_id = (
                        metadata.home_team.team_id
                        if code == "1"
                        else metadata.away_team.team_id
                        if code == "2"
                        else None
                    )
                    status = {
                        "0": "inactive",
                        "1": "active",
                    }.get(element.get("BallStatus"))
                    possession_rows.append(
                        {
                            "trial_id": trial_id,
                            "t_rel_ns": t_rel_ns,
                            "team_id": team_id,
                            "player_id": None,
                            "ball_status": status,
                            "measurement_class": "SOURCE_DERIVED",
                        }
                    )
        element.clear()
        while element.getprevious() is not None:
            del element.getparent()[0]
    if not possession_rows:
        raise ValueError(f"DFL: no source possession frames matched {trial_id}")
    metadata_input, tracking_input = _verify_input_checksums(
        settings,
        "dfl-sportec-idsse",
        metadata_path=metadata_path,
        tracking_path=tracking_path,
        metadata_rows=len(metadata.players),
        tracking_rows=int(
            capabilities["datasets"]["dfl-sportec-idsse"]["quality_evidence"][
                "tracking_entity_observations"
            ]
        ),
    )
    return TacticalSourceAuthority(
        role_by_player=roles,
        attacking_direction_by_team={},
        possession=pa.Table.from_pylist(possession_rows, schema=_POSSESSION_SCHEMA),
        inputs=(metadata_input, tracking_input),
        role_authority="dfl-sportec-playing-position-v1",
        direction_authority="unavailable",
        possession_authority="dfl-sportec-ball-attributes-v1",
    )


def _skillcorner_authority(
    settings: Settings,
    *,
    metadata_path: Path,
    tracking_path: Path,
    trial_id: str,
    wanted_times: set[int],
) -> TacticalSourceAuthority:
    metadata = parse_match_metadata(metadata_path)
    role_maps = _authority()[1]
    group_map = role_maps["skillcorner_position_group"]
    acronym_overrides = role_maps["skillcorner_position_acronym_overrides"]
    roles = {
        player.player_id: acronym_overrides.get(
            (player.position_acronym or "").upper(),
            group_map.get((player.position_group or "").strip(), "unknown"),
        )
        for player in metadata.players
    }
    period = next((item for item in metadata.periods if item.name == trial_id), None)
    if period is None:
        raise ValueError(f"SkillCorner: undeclared period {trial_id!r}")
    directions = {
        team_id: direction
        for team_id in (metadata.home_team_id, metadata.away_team_id)
        if (direction := metadata.attacking_direction(team_id, period.period)) is not None
    }
    possession_rows: list[dict[str, Any]] = []
    line_count = 0
    with tracking_path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line_count += 1
            payload = json.loads(raw)
            try:
                record_period = int(payload["period"])
                t_rel_ns = match_time_ns(payload.get("timestamp"))
            except (KeyError, TypeError, ValueError):
                continue
            if record_period != period.period or t_rel_ns not in wanted_times:
                continue
            source = payload.get("possession")
            source = source if isinstance(source, dict) else {}
            group = source.get("group")
            team_id = (
                metadata.home_team_id
                if group == "home team"
                else metadata.away_team_id
                if group == "away team"
                else None
            )
            possession_rows.append(
                {
                    "trial_id": trial_id,
                    "t_rel_ns": t_rel_ns,
                    "team_id": team_id,
                    "player_id": (
                        None if source.get("player_id") is None else str(source["player_id"])
                    ),
                    "ball_status": None,
                    "measurement_class": "SOURCE_DERIVED",
                }
            )
    if not possession_rows:
        raise ValueError(f"SkillCorner: no source possession frames matched {trial_id}")
    metadata_input, tracking_input = _verify_input_checksums(
        settings,
        "skillcorner-opendata",
        metadata_path=metadata_path,
        tracking_path=tracking_path,
        metadata_rows=len(metadata.players),
        tracking_rows=line_count,
    )
    return TacticalSourceAuthority(
        role_by_player=roles,
        attacking_direction_by_team=directions,
        possession=pa.Table.from_pylist(possession_rows, schema=_POSSESSION_SCHEMA),
        inputs=(metadata_input, tracking_input),
        role_authority="skillcorner-match-player-role-v1",
        direction_authority="skillcorner-home-team-side-v1",
        possession_authority="skillcorner-tracking-possession-v1",
    )


def load_tactical_source_authority(
    settings: Settings,
    *,
    dataset_id: str,
    trial_id: str,
    tracking: pa.Table,
) -> TacticalSourceAuthority:
    """Join accepted metadata/possession to one checksum-verified period slice."""
    metadata_path, tracking_path = _source_files(settings, dataset_id)
    wanted_times = {int(value) for value in tracking.column("t_rel_ns").to_pylist()}
    if dataset_id == "dfl-sportec-idsse":
        return _dfl_authority(
            settings,
            metadata_path=metadata_path,
            tracking_path=tracking_path,
            trial_id=trial_id,
            wanted_times=wanted_times,
        )
    return _skillcorner_authority(
        settings,
        metadata_path=metadata_path,
        tracking_path=tracking_path,
        trial_id=trial_id,
        wanted_times=wanted_times,
    )


__all__ = ["TacticalSourceAuthority", "load_tactical_source_authority"]
