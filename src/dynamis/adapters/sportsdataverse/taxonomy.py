"""Versioned SportsDataverse release-family taxonomy.

SportsDataverse publishes one GitHub release per dataset *family* (``espn_nba_pbp``,
``nhl_skater_boxscores`` ...), each holding one asset per season and format. A
family maps to a sport, a competition and a V4 data grain only through an explicit
rule in this module; a tag that no rule claims is catalogued as ``unmapped`` and is
never routed to a product by filename guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from dynamis.contracts.sports import DataGrainKind

TAXONOMY_VERSION = "sportsdataverse-taxonomy/1"

# Explicit release-family capabilities shared by acquisition and metadata cataloging.
FAMILY_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "play_by_play": ("PLAY_BY_PLAY",),
    "player_game": ("BOX_SCORE",),
    "team_game": ("BOX_SCORE",),
    "player_season": ("SEASON_AGGREGATE",),
    "team_season": ("SEASON_AGGREGATE",),
    "shots": ("EVENTS",),
}


@dataclass(frozen=True, slots=True)
class League:
    league_id: str
    sport_id: str
    competition_name: str
    #: Tag prefixes whose families belong to this league.
    prefixes: tuple[str, ...]


LEAGUES: tuple[League, ...] = (
    League("nba", "basketball", "NBA", ("espn_nba_", "nba_")),
    League("wnba", "basketball", "WNBA", ("espn_wnba_", "wnba_")),
    League("mbb", "basketball", "NCAA Men's Basketball", ("espn_mbb_", "ncaa_mbb_", "mbb_")),
    League(
        "wbb",
        "basketball",
        "NCAA Women's Basketball",
        ("espn_wbb_", "ncaa_wbb_", "espn_womens_college_basketball_", "wbb_"),
    ),
    League("nhl", "ice_hockey", "NHL", ("espn_nhl_", "nhl_")),
    League("pwhl", "ice_hockey", "PWHL", ("pwhl_",)),
    League("phf", "ice_hockey", "PHF", ("phf_",)),
    League("nfl", "american_football", "NFL", ("espn_nfl_", "nfl_")),
    League("cfb", "american_football", "NCAA Football", ("espn_cfb_", "cfb_", "ncaa_mfb_")),
    League("mlb", "baseball", "MLB", ("espn_mlb_", "mlb_")),
    League("ncaa_baseball", "baseball", "NCAA Baseball", ("ncaa_baseball_",)),
)

#: Family kinds in resolution order; the first matching pattern wins.
_FAMILY_RULES: tuple[tuple[str, re.Pattern[str], DataGrainKind | None], ...] = (
    ("play_by_play", re.compile(r"(^|_)pbp(_lite|_full)?$"), DataGrainKind.PLAY_BY_PLAY),
    ("schedule", re.compile(r"(^|_)(schedules?|games)$"), DataGrainKind.GAME_SUMMARY),
    ("game_info", re.compile(r"(^|_)(game_info|linescore)$"), DataGrainKind.GAME_SUMMARY),
    (
        "player_game",
        re.compile(r"(^|_)(player|skater|goalie)_box(scores?)?$|(^|_)player_game_logs$"),
        DataGrainKind.PLAYER_GAME,
    ),
    ("team_game", re.compile(r"(^|_)team_box(scores?)?$"), DataGrainKind.TEAM_GAME),
    ("player_season", re.compile(r"(^|_)player_season_stats$"), DataGrainKind.PLAYER_SEASON),
    ("team_season", re.compile(r"(^|_)team_season_stats$"), DataGrainKind.TEAM_SEASON),
    ("shots", re.compile(r"(^|_)shots$"), DataGrainKind.EVENT_SERIES),
    ("roster", re.compile(r"(^|_)(game_|team_)?rosters$"), None),
)

#: Families whose assets are season-sliced by a trailing four-digit year.
_SEASON_IN_NAME = re.compile(
    r"(?:^|[_-])(?P<season>(?:19|20)\d{2})(?:[_-]lite)?\.(?P<format>parquet|csv|csv\.gz|rds)$"
)
_SEASON_RANGE_IN_NAME = re.compile(
    r"(?:^|[_-])(?P<season>(?:19|20)\d{2})-\d{2}\.(?P<format>parquet|csv|csv\.gz|rds)$"
)


@dataclass(frozen=True, slots=True)
class FamilyMapping:
    tag: str
    league_id: str | None
    sport_id: str | None
    competition_name: str | None
    family_kind: str
    grain: DataGrainKind | None
    rule: str

    @property
    def mapped(self) -> bool:
        return self.league_id is not None and self.grain is not None


def map_family(tag: str) -> FamilyMapping:
    """Resolve one release tag under :data:`TAXONOMY_VERSION`."""
    league = next(
        (item for item in LEAGUES if any(tag.startswith(prefix) for prefix in item.prefixes)),
        None,
    )
    stem = tag
    if league is not None:
        prefix = next(prefix for prefix in league.prefixes if tag.startswith(prefix))
        stem = tag[len(prefix) :]
    for kind, pattern, grain in _FAMILY_RULES:
        if pattern.search(stem):
            return FamilyMapping(
                tag=tag,
                league_id=league.league_id if league else None,
                sport_id=league.sport_id if league else None,
                competition_name=league.competition_name if league else None,
                family_kind=kind,
                grain=grain,
                rule=f"{TAXONOMY_VERSION}:{kind}",
            )
    return FamilyMapping(
        tag=tag,
        league_id=league.league_id if league else None,
        sport_id=league.sport_id if league else None,
        competition_name=league.competition_name if league else None,
        family_kind="unmapped",
        grain=None,
        rule=f"{TAXONOMY_VERSION}:unmapped",
    )


def asset_season(name: str) -> tuple[int, str] | None:
    """Season year and format of a season-sliced asset name, or ``None``."""
    for pattern in (_SEASON_IN_NAME, _SEASON_RANGE_IN_NAME):
        match = pattern.search(name)
        if match is not None:
            season = int(match["season"])
            # "2025-26" names the season that ends in 2026, like every other asset.
            if pattern is _SEASON_RANGE_IN_NAME:
                season += 1
            return season, match["format"]
    return None


def edition_label(league_id: str, season: int) -> str:
    """Human label for a SportsDataverse season year (the year a season ends)."""
    if league_id in {"nba", "nhl", "mbb", "wbb", "pwhl"}:
        return f"{season - 1}-{str(season)[-2:]}"
    return str(season)
