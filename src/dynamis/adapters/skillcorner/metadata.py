"""SkillCorner ``{match}_match.json`` structural metadata.

Only facts the source actually carries are modelled: teams, squad list with the
provider's player identity and team assignment, pitch size, declared match
periods with their frame ranges, venue and kickoff timestamp. Nothing is
inferred from prose.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


class MatchMetadataError(ValueError):
    """The match metadata document does not satisfy the expected structure."""


def _mapping(payload: object, *, what: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise MatchMetadataError(f"{what}: expected a JSON object")
    return payload


def _sequence(payload: object, *, what: str) -> list[Any]:
    if not isinstance(payload, list):
        raise MatchMetadataError(f"{what}: expected a JSON array")
    return payload


def _aware_datetime(text: object, *, what: str) -> datetime:
    if not isinstance(text, str):
        raise MatchMetadataError(f"{what}: expected an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MatchMetadataError(f"{what}: cannot parse {text!r}") from exc
    if parsed.tzinfo is None:
        raise MatchMetadataError(f"{what}: timestamp {text!r} has no timezone")
    return parsed


@dataclass(frozen=True, slots=True)
class MatchPlayer:
    player_id: str
    team_id: str
    team_name: str
    shirt_number: int | None
    position_group: str | None
    position_name: str | None
    position_acronym: str | None
    short_name: str | None
    trackable_object: str | None

    @property
    def is_goalkeeper(self) -> bool:
        return (self.position_acronym or "").strip().upper() == "GK" or (
            (self.position_group or "").strip().lower() == "goalkeeper"
        )


@dataclass(frozen=True, slots=True)
class MatchPeriod:
    period: int
    name: str
    start_frame: int
    end_frame: int

    def contains(self, frame: int) -> bool:
        return self.start_frame <= frame <= self.end_frame

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "name": self.name,
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
        }


@dataclass(frozen=True, slots=True)
class SkillCornerMatchMetadata:
    match_id: str
    title: str
    kickoff_utc: datetime
    pitch_length_m: float
    pitch_width_m: float
    home_team_id: str
    home_team_name: str
    away_team_id: str
    away_team_name: str
    home_score: int | None
    away_score: int | None
    stadium: str | None
    home_team_side: tuple[str | None, str | None]
    periods: tuple[MatchPeriod, ...]
    players: tuple[MatchPlayer, ...]

    @property
    def session_id(self) -> str:
        return self.match_id

    def player(self, player_id: str) -> MatchPlayer | None:
        for candidate in self.players:
            if candidate.player_id == player_id:
                return candidate
        return None

    def period(self, period: int) -> MatchPeriod | None:
        for candidate in self.periods:
            if candidate.period == period:
                return candidate
        return None

    def attacking_direction(self, team_id: str, period: int) -> str | None:
        """Source-declared team direction for a period, when present."""
        if period not in {1, 2}:
            return None
        direction = self.home_team_side[period - 1]
        if direction is None:
            return None
        if team_id == self.home_team_id:
            return direction
        if team_id == self.away_team_id:
            return {
                "left_to_right": "right_to_left",
                "right_to_left": "left_to_right",
            }[direction]
        raise KeyError(f"team {team_id!r} is not in match {self.match_id}")


def parse_match_metadata(path: Path) -> SkillCornerMatchMetadata:
    """Parse and structurally validate one SkillCorner match metadata document."""
    document = _mapping(json.loads(Path(path).read_text(encoding="utf-8")), what="match.json")

    home = _mapping(document.get("home_team"), what="home_team")
    away = _mapping(document.get("away_team"), what="away_team")
    home_id = str(home.get("id"))
    away_id = str(away.get("id"))
    home_name = str(home.get("name") or home_id)
    away_name = str(away.get("name") or away_id)

    pitch_length = document.get("pitch_length")
    pitch_width = document.get("pitch_width")
    if not isinstance(pitch_length, (int, float)) or not isinstance(pitch_width, (int, float)):
        raise MatchMetadataError("pitch_length and pitch_width must be numeric")

    raw_periods = _sequence(document.get("match_periods"), what="match_periods")
    periods: list[MatchPeriod] = []
    for raw in raw_periods:
        entry = _mapping(raw, what="match period")
        period = entry.get("period")
        start_frame = entry.get("start_frame")
        end_frame = entry.get("end_frame")
        if (
            not isinstance(period, int)
            or not isinstance(start_frame, int)
            or not isinstance(end_frame, int)
        ):
            raise MatchMetadataError("match period requires integer period/start_frame/end_frame")
        if end_frame < start_frame:
            raise MatchMetadataError(f"period {period}: end_frame precedes start_frame")
        periods.append(
            MatchPeriod(
                period=period,
                name=str(entry.get("name") or f"period_{period}"),
                start_frame=start_frame,
                end_frame=end_frame,
            )
        )
    if not periods:
        raise MatchMetadataError("match metadata declares no period")

    side_value = document.get("home_team_side")
    if side_value is None:
        home_team_side: tuple[str | None, str | None] = (None, None)
    else:
        sides = _sequence(side_value, what="home_team_side")
        if len(sides) != 2 or any(side not in {"left_to_right", "right_to_left"} for side in sides):
            raise MatchMetadataError(
                "home_team_side must declare left_to_right/right_to_left for both halves"
            )
        home_team_side = (str(sides[0]), str(sides[1]))

    raw_players = _sequence(document.get("players"), what="players")
    players: list[MatchPlayer] = []
    seen: set[str] = set()
    for raw in raw_players:
        entry = _mapping(raw, what="player")
        player_id = entry.get("id")
        if player_id is None:
            raise MatchMetadataError("a player record has no id")
        player_id = str(player_id)
        if player_id in seen:
            raise MatchMetadataError(f"duplicate player id {player_id!r}")
        seen.add(player_id)
        team_id = entry.get("team_id")
        if team_id is None:
            raise MatchMetadataError(f"player {player_id!r} has no team_id")
        team_id = str(team_id)
        if team_id == home_id:
            team_name = home_name
        elif team_id == away_id:
            team_name = away_name
        else:
            raise MatchMetadataError(
                f"player {player_id!r} references team {team_id!r} outside home/away"
            )
        role = entry.get("player_role")
        role_mapping = _mapping(role, what="player_role") if role is not None else {}
        number = entry.get("number")
        trackable = entry.get("trackable_object")
        players.append(
            MatchPlayer(
                player_id=player_id,
                team_id=team_id,
                team_name=team_name,
                shirt_number=int(number) if isinstance(number, (int, float)) else None,
                position_group=(
                    str(role_mapping.get("position_group"))
                    if role_mapping.get("position_group") is not None
                    else None
                ),
                position_name=(
                    str(role_mapping.get("name")) if role_mapping.get("name") is not None else None
                ),
                position_acronym=(
                    str(role_mapping.get("acronym"))
                    if role_mapping.get("acronym") is not None
                    else None
                ),
                short_name=(
                    str(entry.get("short_name")) if entry.get("short_name") is not None else None
                ),
                trackable_object=str(trackable) if trackable is not None else None,
            )
        )

    stadium = document.get("stadium")
    stadium_name: str | None = None
    if isinstance(stadium, dict) and stadium.get("name") is not None:
        stadium_name = str(stadium["name"])

    home_score = document.get("home_team_score")
    away_score = document.get("away_team_score")

    return SkillCornerMatchMetadata(
        match_id=str(document.get("id")),
        title=f"{home_name} vs {away_name}",
        kickoff_utc=_aware_datetime(document.get("date_time"), what="date_time"),
        pitch_length_m=float(pitch_length),
        pitch_width_m=float(pitch_width),
        home_team_id=home_id,
        home_team_name=home_name,
        away_team_id=away_id,
        away_team_name=away_name,
        home_score=int(home_score) if isinstance(home_score, (int, float)) else None,
        away_score=int(away_score) if isinstance(away_score, (int, float)) else None,
        stadium=stadium_name,
        home_team_side=home_team_side,
        periods=tuple(periods),
        players=tuple(players),
    )
