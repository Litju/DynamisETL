"""Match-information parsing for the DFL/Sportec IDSSE provider.

The file is small (~12 KB) and is parsed as a DOM tree; it yields the domain
metadata the canonical session/participant/period records are built from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import lxml.etree as etree

IDSSE_DATASET_ID = "dfl-sportec-idsse"
BALL_TEAM_ID = "BALL"


class MatchInfoError(ValueError):
    """The match-information file contradicts the expected provider schema."""


@dataclass(frozen=True, slots=True)
class PlayerRecord:
    person_id: str
    team_id: str
    shirt_number: int | None
    first_name: str
    last_name: str
    shortname: str
    starting: bool
    playing_position: str | None
    team_leader: bool

    @property
    def is_goalkeeper(self) -> bool:
        return self.playing_position == "TW"


@dataclass(frozen=True, slots=True)
class TeamRecord:
    team_id: str
    name: str
    role: str
    lineup: str | None


@dataclass(frozen=True, slots=True)
class IdsseMatchMetadata:
    request_id: str
    match_id: str
    competition: str
    season: str
    match_day: int
    title: str
    result: str
    kickoff_utc: datetime
    planned_kickoff_utc: datetime
    stadium: str
    pitch_x_m: float
    pitch_y_m: float
    home_team: TeamRecord
    away_team: TeamRecord
    players: tuple[PlayerRecord, ...]
    trainer_count: int
    referee_count: int
    period_total_times_ms: dict[str, int]

    @property
    def player_count(self) -> int:
        return len(self.players)

    def players_by_id(self) -> dict[str, PlayerRecord]:
        return {player.person_id: player for player in self.players}

    def team_name(self, team_id: str) -> str:
        if team_id == self.home_team.team_id:
            return self.home_team.name
        if team_id == self.away_team.team_id:
            return self.away_team.name
        return team_id


def _required(element: etree._Element, attribute: str) -> str:
    value = element.get(attribute)
    if value is None:
        raise MatchInfoError(f"{element.tag} is missing required attribute {attribute!r}")
    return value


def _required_aware_datetime(element: etree._Element, attribute: str) -> datetime:
    """Parse a timestamp that must carry a UTC offset.

    ``kickoff_utc`` is the origin of every canonical ``t_rel_ns`` value, so a
    naive provider timestamp must fail loudly: interpreting it in the host
    timezone would silently make the canonical output machine-dependent.
    """
    raw = _required(element, attribute)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise MatchInfoError(f"{attribute}={raw!r} is not an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise MatchInfoError(
            f"{attribute}={raw!r} carries no UTC offset; a naive kickoff time cannot "
            "define a machine-independent canonical time origin"
        )
    return parsed


def parse_match_information(path: Path) -> IdsseMatchMetadata:
    tree = etree.parse(str(path))
    root = tree.getroot()
    general = root.find(".//MatchInformation/General")
    environment = root.find(".//MatchInformation/Environment")
    teams_root = root.find(".//MatchInformation/Teams")
    if general is None or environment is None or teams_root is None:
        raise MatchInfoError(f"{path.name}: missing MatchInformation sections")

    teams: list[TeamRecord] = []
    players: list[PlayerRecord] = []
    for team_element in teams_root.findall("Team"):
        team_id = _required(team_element, "TeamId")
        role = _required(team_element, "Role")
        teams.append(
            TeamRecord(
                team_id=team_id,
                name=_required(team_element, "TeamName"),
                role=role,
                lineup=team_element.get("LineUp"),
            )
        )
        for player_element in team_element.findall("Players/Player"):
            shirt = player_element.get("ShirtNumber")
            players.append(
                PlayerRecord(
                    person_id=_required(player_element, "PersonId"),
                    team_id=team_id,
                    shirt_number=int(shirt) if shirt is not None else None,
                    first_name=player_element.get("FirstName") or "",
                    last_name=player_element.get("LastName") or "",
                    shortname=player_element.get("Shortname") or "",
                    starting=(player_element.get("Starting") or "false").lower() == "true",
                    playing_position=player_element.get("PlayingPosition"),
                    team_leader=(player_element.get("TeamLeader") or "false").lower() == "true",
                )
            )
    home = next((team for team in teams if team.role == "home"), None)
    away = next((team for team in teams if team.role == "guest"), None)
    if home is None or away is None:
        raise MatchInfoError(f"{path.name}: home and guest teams are both required")

    other = root.find(".//OtherGameInformation")
    total_times: dict[str, int] = {}
    if other is not None:
        for key, value in other.attrib.items():
            try:
                total_times[key] = int(value)
            except ValueError:
                continue
    return IdsseMatchMetadata(
        request_id=_required(root, "RequestId"),
        match_id=_required(general, "MatchId"),
        competition=_required(general, "CompetitionName"),
        season=_required(general, "Season"),
        match_day=int(general.get("MatchDay") or 0),
        title=_required(general, "MatchTitle"),
        result=_required(general, "Result"),
        kickoff_utc=_required_aware_datetime(general, "KickoffTime"),
        planned_kickoff_utc=_required_aware_datetime(general, "PlannedKickoffTime"),
        stadium=environment.get("StadiumName") or "",
        pitch_x_m=float(_required(environment, "PitchX")),
        pitch_y_m=float(_required(environment, "PitchY")),
        home_team=home,
        away_team=away,
        players=tuple(players),
        trainer_count=len(root.findall(".//Trainer")),
        referee_count=len(root.findall(".//Referee")),
        period_total_times_ms=total_times,
    )
