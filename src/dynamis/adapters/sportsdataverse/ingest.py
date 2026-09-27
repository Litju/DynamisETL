"""Canonicalize the pinned SportsDataverse NBA/NHL season slices.

For each league the pinned Bronze assets become:

* V4 semantics: sport, competition, edition, teams, contests, contest teams,
  contest periods and provider identity crosswalks (provider ids are aliases);
* Silver artifacts per competition edition × family, grain-validated:
  PLAY_BY_PLAY (the cross-sport event envelope + every source column preserved
  as ``src_*``), PLAYER_GAME, TEAM_GAME and GAME_SUMMARY;
* versioned clock mappings. Basketball counts down within a quarter, hockey
  counts up within a period; canonical contest time is only derived where the
  period semantics make it valid (never for a hockey shootout).

Nothing is joined by display name. Ordering is provider sequence within a period.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from dynamis.adapters.sportsdataverse.releases import (
    DATASET_ID,
    PinnedAsset,
    load_snapshot,
    pinned_assets,
)
from dynamis.adapters.sportsdataverse.taxonomy import edition_label
from dynamis.contracts.sports import (
    ClockDirection,
    ClockKind,
    ClockMapping,
    ContestSide,
    DataGrain,
    DataGrainKind,
    EditionKind,
    PeriodKind,
    ProviderIdentityCrosswalk,
    SportsEntityKind,
    canonical_sports_id,
    provider_crosswalk,
    provider_crosswalk_id,
)

INGEST_VERSION = "1"
NS = 1_000_000_000

PBP_GRAIN = DataGrain(kind=DataGrainKind.PLAY_BY_PLAY, axes=("contest", "period", "sequence_index"))
PLAYER_GAME_GRAIN = DataGrain(kind=DataGrainKind.PLAYER_GAME, axes=("subject", "contest"))
TEAM_GAME_GRAIN = DataGrain(kind=DataGrainKind.TEAM_GAME, axes=("team", "contest"))
GAME_SUMMARY_GRAIN = DataGrain(kind=DataGrainKind.GAME_SUMMARY, axes=("contest",))

GRAIN_COLUMNS: dict[DataGrainKind, tuple[str, ...]] = {
    DataGrainKind.PLAY_BY_PLAY: ("contest_id", "contest_period_id", "sequence_index"),
    DataGrainKind.PLAYER_GAME: ("subject_id", "contest_id"),
    DataGrainKind.TEAM_GAME: ("team_id", "contest_id"),
    DataGrainKind.GAME_SUMMARY: ("contest_id",),
}


class IngestError(ValueError):
    """A pinned asset cannot be canonicalized under the declared rules."""


@dataclass(frozen=True, slots=True)
class PeriodRule:
    """Period semantics for one league: duration and clock direction."""

    regulation_periods: int
    regulation_seconds: int
    overtime_seconds_regular: int | None
    overtime_seconds_postseason: int | None
    direction: ClockDirection
    regulation_kind: PeriodKind
    authority: str

    def duration_s(self, number: int, *, postseason: bool) -> int | None:
        if number <= self.regulation_periods:
            return self.regulation_seconds
        seconds = self.overtime_seconds_postseason if postseason else self.overtime_seconds_regular
        return seconds


NBA_PERIODS = PeriodRule(
    regulation_periods=4,
    regulation_seconds=720,
    overtime_seconds_regular=300,
    overtime_seconds_postseason=300,
    direction=ClockDirection.COUNT_DOWN,
    regulation_kind=PeriodKind.QUARTER,
    authority="NBA rules: four 12-minute quarters, 5-minute overtimes; ESPN clock counts down",
)
NHL_PERIODS = PeriodRule(
    regulation_periods=3,
    regulation_seconds=1200,
    overtime_seconds_regular=300,
    overtime_seconds_postseason=1200,
    direction=ClockDirection.COUNT_UP,
    regulation_kind=PeriodKind.PERIOD,
    authority=(
        "NHL rules: three 20-minute periods; regular-season 5-minute overtime then shootout; "
        "playoff overtimes are 20-minute periods; fastRhockey period_seconds counts up"
    ),
)


@dataclass(frozen=True, slots=True)
class LeagueSpec:
    league_id: str
    namespace: str
    sport_id: str
    sport_name: str
    competition_name: str
    periods: PeriodRule
    attributes_schema_id: str
    families: Mapping[str, str]
    provider_label: str


NBA = LeagueSpec(
    league_id="nba",
    namespace="espn_nba",
    sport_id="basketball",
    sport_name="Basketball",
    competition_name="NBA",
    periods=NBA_PERIODS,
    attributes_schema_id="sportsdataverse.espn_nba.pbp",
    families={
        "schedule": "espn_nba_schedules",
        "pbp": "espn_nba_pbp",
        "player_game": "espn_nba_player_boxscores",
        "team_game": "espn_nba_team_boxscores",
    },
    provider_label="SportsDataverse hoopR (ESPN)",
)
NHL = LeagueSpec(
    league_id="nhl",
    namespace="nhl_api",
    sport_id="ice_hockey",
    sport_name="Ice hockey",
    competition_name="NHL",
    periods=NHL_PERIODS,
    attributes_schema_id="sportsdataverse.nhl.pbp_lite",
    families={
        "schedule": "nhl_schedules",
        "pbp": "nhl_pbp_lite",
        "skater_game": "nhl_skater_boxscores",
        "goalie_game": "nhl_goalie_boxscores",
        "team_game": "nhl_team_boxscores",
    },
    provider_label="SportsDataverse fastRhockey (NHL API)",
)
LEAGUES: dict[str, LeagueSpec] = {NBA.league_id: NBA, NHL.league_id: NHL}


def canonical_id(spec: LeagueSpec, kind: SportsEntityKind, provider_id: object) -> str:
    return canonical_sports_id(spec.namespace, kind, str(provider_id))


def subject_id(spec: LeagueSpec, provider_id: object) -> str:
    """Canonical subject: dataset-scoped provider identity, as every adapter does."""
    return f"{DATASET_ID}/{spec.namespace}/{provider_id}"


def period_id(contest_id: str, number: int) -> str:
    return f"{contest_id}:period:{number}"


def _schema_fingerprint(schema: pa.Schema) -> str:
    canonical = json.dumps([[item.name, str(item.type)] for item in schema], separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _preserve(table: pa.Table, prefix: str = "src_") -> list[tuple[str, pa.ChunkedArray]]:
    return [(f"{prefix}{name}", table[name]) for name in table.column_names]


def _to_list(column: pa.ChunkedArray | pa.Array) -> list[Any]:
    return column.to_pylist()


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def period_origin_ns(rule: PeriodRule, number: int, *, postseason: bool) -> int | None:
    """Canonical contest-time origin of a period, or ``None`` when undefined."""
    origin = 0
    for previous in range(1, number):
        duration = rule.duration_s(previous, postseason=postseason)
        if duration is None:
            return None
        origin += duration * NS
    return origin


def clock_mappings(spec: LeagueSpec, *, max_period: int, postseason: bool) -> list[ClockMapping]:
    mappings: list[ClockMapping] = []
    for number in range(1, max_period + 1):
        duration = spec.periods.duration_s(number, postseason=postseason)
        origin = period_origin_ns(spec.periods, number, postseason=postseason)
        if duration is None or origin is None:
            continue
        phase = "postseason" if postseason else "regular"
        mappings.append(
            ClockMapping(
                mapping_id=f"sdv-{spec.league_id}-game-clock-{phase}-p{number}",
                version=INGEST_VERSION,
                clock_kind=ClockKind.GAME_CLOCK,
                direction=spec.periods.direction,
                source_unit="s",
                scale_to_ns=float(NS),
                source_origin=float(duration)
                if spec.periods.direction is ClockDirection.COUNT_DOWN
                else None,
                period_origin_ns=origin,
                authority=spec.periods.authority,
                evidence={
                    "league": spec.league_id,
                    "period": number,
                    "duration_s": duration,
                    "postseason": postseason,
                },
            )
        )
    return mappings


def canonical_time_ns(
    spec: LeagueSpec, *, period: int, clock_s: float | None, postseason: bool
) -> int | None:
    """Canonical contest time from a source game clock, or ``None`` if not valid."""
    if clock_s is None:
        return None
    duration = spec.periods.duration_s(period, postseason=postseason)
    origin = period_origin_ns(spec.periods, period, postseason=postseason)
    if duration is None or origin is None or not 0 <= clock_s <= duration:
        return None
    elapsed = duration - clock_s if spec.periods.direction is ClockDirection.COUNT_DOWN else clock_s
    return origin + round(elapsed * NS)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class LeagueResult:
    spec: LeagueSpec
    edition_id: str
    edition_label: str
    season: int
    semantic: dict[str, list[dict[str, Any]]]
    artifacts: dict[str, tuple[pa.Table, DataGrain]]
    clock_mappings: list[ClockMapping]
    reconciliation: dict[str, Any] = field(default_factory=dict)


def _semantic_skeleton(spec: LeagueSpec, *, season: int, first: date, last: date, authority: str):
    competition_id = canonical_id(spec, SportsEntityKind.COMPETITION, spec.league_id)
    edition_id = canonical_id(spec, SportsEntityKind.EDITION, season)
    label = edition_label(spec.league_id, season)
    rows: dict[str, list[dict[str, Any]]] = {
        "sport": [
            {"sport_id": spec.sport_id, "code": spec.sport_id, "display_name": spec.sport_name}
        ],
        "competition": [
            {
                "competition_id": competition_id,
                "sport_id": spec.sport_id,
                "name": spec.competition_name,
            }
        ],
        "competition_edition": [
            {
                "edition_id": edition_id,
                "competition_id": competition_id,
                "label": label,
                "kind": EditionKind.LEAGUE_SEASON.value,
                "starts_on": first,
                "ends_on": last,
            }
        ],
        "team": [],
        "contest": [],
        "contest_team": [],
        "contest_period": [],
        "provider_identity_crosswalk": [],
    }
    for kind, provider_id, metadata in (
        (SportsEntityKind.COMPETITION, spec.league_id, {"name": spec.competition_name}),
        (SportsEntityKind.EDITION, str(season), {"label": label, "season_year": season}),
    ):
        rows["provider_identity_crosswalk"].append(
            _crosswalk_row(spec, kind, provider_id, authority=authority, metadata=metadata)
        )
    return rows, edition_id, label


def _crosswalk_row(
    spec: LeagueSpec,
    kind: SportsEntityKind,
    provider_id: object,
    *,
    authority: str,
    metadata: Mapping[str, Any] | None = None,
    canonical: str | None = None,
) -> dict[str, Any]:
    if canonical is not None:
        crosswalk = ProviderIdentityCrosswalk(
            provider_namespace=spec.namespace,
            entity_kind=kind,
            provider_entity_id=str(provider_id),
            canonical_entity_id=canonical,
            source_authority=authority,
            metadata=dict(metadata or {}),
        )
    else:
        crosswalk = provider_crosswalk(
            provider_namespace=spec.namespace,
            entity_kind=kind,
            provider_entity_id=str(provider_id),
            source_authority=authority,
            metadata=dict(metadata or {}),
        )
    return {
        "crosswalk_id": provider_crosswalk_id(crosswalk),
        "provider_namespace": crosswalk.provider_namespace,
        "entity_kind": crosswalk.entity_kind.value,
        "provider_entity_id": crosswalk.provider_entity_id,
        "canonical_entity_id": crosswalk.canonical_entity_id,
        "valid_from": None,
        "valid_to": None,
        "source_authority": crosswalk.source_authority,
        "metadata_json": dict(crosswalk.metadata),
    }


def _period_rows(
    spec: LeagueSpec,
    contest_id: str,
    periods: Sequence[tuple[int, str | None]],
    *,
    postseason: bool,
) -> list[dict[str, Any]]:
    rows = []
    for number, label in periods:
        duration = spec.periods.duration_s(number, postseason=postseason)
        origin = period_origin_ns(spec.periods, number, postseason=postseason)
        shootout = label is not None and "shootout" in label.lower()
        if number <= spec.periods.regulation_periods:
            kind = spec.periods.regulation_kind
        else:
            kind = PeriodKind.OTHER if shootout else PeriodKind.OVERTIME
        timed = duration is not None and origin is not None and not shootout
        rows.append(
            {
                "contest_period_id": period_id(contest_id, number),
                "contest_id": contest_id,
                "source_period_number": str(number),
                "kind": kind.value,
                "label": label,
                "provider_namespace": spec.namespace,
                "start_ns": origin if timed else None,
                "end_ns": (origin + duration * NS)
                if timed and duration and origin is not None
                else None,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# NBA (ESPN via hoopR)
# ---------------------------------------------------------------------------

NBA_EVENT_ATTRIBUTES = (
    "type_id",
    "type_text",
    "text",
    "scoring_play",
    "score_value",
    "shooting_play",
    "points_attempted",
    "coordinate_x",
    "coordinate_y",
    "athlete_id_1",
    "athlete_id_2",
    "athlete_id_3",
    "home_score",
    "away_score",
    "wallclock",
)

NHL_EVENT_ATTRIBUTES = (
    "event_type",
    "event",
    "secondary_type",
    "description",
    "strength_state",
    "empty_net",
    "penalty_severity",
    "penalty_minutes",
    "x_fixed",
    "y_fixed",
    "shot_distance",
    "shot_angle",
    "event_player_1_id",
    "event_player_1_type",
    "event_player_2_id",
    "event_player_2_type",
    "event_player_3_id",
    "event_player_3_type",
    "event_goalie_id",
    "home_score",
    "away_score",
    "xg",
)


def _attributes(row: Mapping[str, Any], names: Sequence[str]) -> str:
    payload = {}
    for name in names:
        value = row.get(name)
        if isinstance(value, float) and value != value:  # NaN is not JSON
            value = None
        payload[name] = value
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _nba(assets: Mapping[str, pa.Table], *, season: int, authority: str) -> LeagueResult:
    spec = NBA
    schedule = assets["schedule"]
    pbp = assets["pbp"]
    dates = [value for value in _to_list(schedule["game_date"]) if value is not None]
    semantic, edition_id, label = _semantic_skeleton(
        spec, season=season, first=min(dates), last=max(dates), authority=authority
    )

    teams: dict[str, str] = {}
    team_names: dict[str, str] = {}
    contest_by_game: dict[int, str] = {}
    postseason_by_game: dict[int, bool] = {}
    schedule_rows = schedule.to_pylist()
    for row in schedule_rows:
        for side in ("home", "away"):
            provider_team = str(row[f"{side}_id"])
            if provider_team not in teams:
                teams[provider_team] = canonical_id(spec, SportsEntityKind.TEAM, provider_team)
                team_names[provider_team] = str(row[f"{side}_display_name"])
    for provider_team, team_id in sorted(teams.items()):
        semantic["team"].append(
            {
                "team_id": team_id,
                "sport_id": spec.sport_id,
                "display_name": team_names[provider_team],
            }
        )
        semantic["provider_identity_crosswalk"].append(
            _crosswalk_row(spec, SportsEntityKind.TEAM, provider_team, authority=authority)
        )

    pbp_periods: dict[int, dict[int, str | None]] = {}
    for game, period_number, period_label in zip(
        _to_list(pbp["game_id"]),
        _to_list(pbp["period_number"]),
        _to_list(pbp["period_display_value"]),
        strict=True,
    ):
        pbp_periods.setdefault(int(game), {})[int(period_number)] = period_label

    for row in sorted(schedule_rows, key=lambda item: int(item["game_id"])):
        game = int(row["game_id"])
        contest_id = canonical_id(spec, SportsEntityKind.CONTEST, game)
        contest_by_game[game] = contest_id
        postseason = int(row["season_type"]) == 3
        postseason_by_game[game] = postseason
        start = datetime.fromisoformat(str(row["start_date"]).replace("Z", "+00:00"))
        completed = bool(row["status_type_completed"])
        semantic["contest"].append(
            {
                "contest_id": contest_id,
                "sport_id": spec.sport_id,
                "competition_edition_id": edition_id,
                "scheduled_start_at": start,
                "actual_start_at": start if completed else None,
                "venue": row.get("venue_full_name"),
                "home_away_supported": not bool(row.get("neutral_site")),
                "source_authority": authority,
            }
        )
        for order, side in enumerate(("home", "away")):
            semantic["contest_team"].append(
                {
                    "contest_id": contest_id,
                    "team_id": teams[str(row[f"{side}_id"])],
                    "side": (ContestSide.HOME if side == "home" else ContestSide.AWAY).value
                    if not row.get("neutral_site")
                    else ContestSide.NEUTRAL.value,
                    "side_order": order,
                    "score": row[f"{side}_score"] if completed else None,
                }
            )
        periods = sorted(pbp_periods.get(game, {}).items())
        semantic["contest_period"].extend(
            _period_rows(spec, contest_id, periods, postseason=postseason)
        )
        semantic["provider_identity_crosswalk"].append(
            _crosswalk_row(
                spec,
                SportsEntityKind.CONTEST,
                game,
                authority=authority,
                metadata={
                    "season_type": int(row["season_type"]),
                    "status": row.get("status_type_name"),
                    "completed": completed,
                    "play_by_play_available": bool(row.get("PBP")),
                    "player_box_available": bool(row.get("player_box")),
                    "team_box_available": bool(row.get("team_box")),
                },
            )
        )

    unknown_games = sorted(set(pbp_periods) - set(contest_by_game))
    if unknown_games:
        raise IngestError(
            f"NBA play-by-play references games absent from the schedule: {unknown_games[:5]}"
        )

    # Play-by-play → event envelope + preserved source columns.
    rows = pbp.to_pylist()
    envelope: dict[str, list[Any]] = {name: [] for name in _ENVELOPE_COLUMNS}
    for row in rows:
        game = int(row["game_id"])
        contest_id = contest_by_game[game]
        period = int(row["period_number"])
        minutes = row.get("clock_minutes")
        seconds = row.get("clock_seconds")
        clock_s = (
            float(minutes) * 60 + float(seconds)
            if minutes is not None and seconds is not None
            else None
        )
        team = row.get("team_id")
        athlete = row.get("athlete_id_1")
        envelope["contest_id"].append(contest_id)
        envelope["contest_period_id"].append(period_id(contest_id, period))
        envelope["sequence_index"].append(f"{int(row['game_play_number']):06d}")
        envelope["source_event_id"].append(str(row["id"]))
        envelope["provider_namespace"].append(spec.namespace)
        envelope["provider_event_type"].append(str(row["type_text"] or "unknown"))
        envelope["canonical_time_ns"].append(
            canonical_time_ns(
                spec, period=period, clock_s=clock_s, postseason=postseason_by_game[game]
            )
        )
        envelope["source_clock_json"].append(
            json.dumps(
                {
                    "period": period,
                    "clock": row.get("clock_display_value"),
                    "direction": "count_down",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        envelope["team_id"].append(teams.get(str(team)) if team is not None else None)
        envelope["subject_id"].append(subject_id(spec, athlete) if athlete is not None else None)
        envelope["attributes_json"].append(_attributes(row, NBA_EVENT_ATTRIBUTES))
        envelope["attributes_schema_id"].append(spec.attributes_schema_id)
        envelope["attributes_schema_version"].append(INGEST_VERSION)
        envelope["period_number"].append(period)
        envelope["provider_game_id"].append(str(game))

    player_box = assets["player_game"]
    team_box = assets["team_game"]
    artifacts = {
        "pbp": (_envelope_table(envelope, pbp), PBP_GRAIN),
        "schedule": (_with_ids(schedule, contest_by_game, "game_id"), GAME_SUMMARY_GRAIN),
        "player_game": (
            _with_ids(
                player_box,
                contest_by_game,
                "game_id",
                subject=lambda value: subject_id(spec, value),
                subject_column="athlete_id",
                teams=teams,
                team_column="team_id",
            ),
            PLAYER_GAME_GRAIN,
        ),
        "team_game": (
            _with_ids(team_box, contest_by_game, "game_id", teams=teams, team_column="team_id"),
            TEAM_GAME_GRAIN,
        ),
    }
    athletes = sorted(
        {int(value) for value in _to_list(player_box["athlete_id"]) if value is not None}
    )
    names = dict(
        zip(
            _to_list(player_box["athlete_id"]),
            _to_list(player_box["athlete_display_name"]),
            strict=True,
        )
    )
    for athlete in athletes:
        semantic["provider_identity_crosswalk"].append(
            _crosswalk_row(
                spec,
                SportsEntityKind.SUBJECT,
                athlete,
                authority=authority,
                canonical=subject_id(spec, athlete),
                metadata={"display_name": names.get(athlete)},
            )
        )
    max_period = max((period for periods in pbp_periods.values() for period in periods), default=4)
    return LeagueResult(
        spec=spec,
        edition_id=edition_id,
        edition_label=label,
        season=season,
        semantic=semantic,
        artifacts=artifacts,
        clock_mappings=[
            *clock_mappings(spec, max_period=max_period, postseason=False),
            *clock_mappings(spec, max_period=max_period, postseason=True),
        ],
        reconciliation=_score_reconciliation(
            schedule_rows,
            pbp,
            game_column="game_id",
            order_column="game_play_number",
            home_score="home_score",
            away_score="away_score",
            final_home=lambda row: row["home_score"],
            final_away=lambda row: row["away_score"],
            completed=lambda row: bool(row["status_type_completed"]),
            schedule_game=lambda row: int(row["game_id"]),
        ),
    )


# ---------------------------------------------------------------------------
# NHL (NHL API via fastRhockey)
# ---------------------------------------------------------------------------


def _nhl(assets: Mapping[str, pa.Table], *, season: int, authority: str) -> LeagueResult:
    spec = NHL
    schedule = assets["schedule"]
    pbp = assets["pbp"]
    team_box = assets["team_game"]
    dates = [date.fromisoformat(value) for value in _to_list(schedule["game_date"]) if value]
    semantic, edition_id, label = _semantic_skeleton(
        spec, season=season, first=min(dates), last=max(dates), authority=authority
    )

    # The schedule names teams by provider abbreviation; team ids come from the
    # same provider's box scores (id ↔ abbreviation), never from display names.
    team_by_abbr: dict[str, str] = {}
    team_names: dict[str, str] = {}
    schedule_rows = schedule.to_pylist()
    location_by_abbr = {}
    for row in schedule_rows:
        location_by_abbr[str(row["home_team_abbr"])] = str(row["home_team_name"])
        location_by_abbr[str(row["away_team_abbr"])] = str(row["away_team_name"])
    for abbr, provider_team, name in zip(
        _to_list(team_box["team_abbrev"]),
        _to_list(team_box["team_id"]),
        _to_list(team_box["team_name"]),
        strict=True,
    ):
        known = team_by_abbr.get(str(abbr))
        if known is not None and known != str(provider_team):
            raise IngestError(f"NHL abbreviation {abbr} maps to several team ids")
        team_by_abbr[str(abbr)] = str(provider_team)
        location = location_by_abbr.get(str(abbr))
        team_names[str(provider_team)] = f"{location} {name}" if location else str(name)
    teams = {
        provider: canonical_id(spec, SportsEntityKind.TEAM, provider)
        for provider in sorted(set(team_by_abbr.values()))
    }
    abbr_by_team = {value: key for key, value in team_by_abbr.items()}
    for provider_team, team_id in teams.items():
        semantic["team"].append(
            {
                "team_id": team_id,
                "sport_id": spec.sport_id,
                "display_name": team_names[provider_team],
            }
        )
        semantic["provider_identity_crosswalk"].append(
            _crosswalk_row(
                spec,
                SportsEntityKind.TEAM,
                provider_team,
                authority=authority,
                metadata={"abbreviation": abbr_by_team[provider_team]},
            )
        )

    pbp_periods: dict[int, dict[int, str | None]] = {}
    for game, period_number, period_type in zip(
        _to_list(pbp["game_id"]), _to_list(pbp["period"]), _to_list(pbp["period_type"]), strict=True
    ):
        period_label = {"REGULAR": None, "OVERTIME": "Overtime", "SHOOTOUT": "Shootout"}.get(
            str(period_type), str(period_type)
        )
        pbp_periods.setdefault(int(game), {})[int(period_number)] = period_label

    contest_by_game: dict[int, str] = {}
    postseason_by_game: dict[int, bool] = {}
    skipped: list[int] = []
    for row in sorted(schedule_rows, key=lambda item: int(item["game_id"])):
        game = int(row["game_id"])
        home = team_by_abbr.get(str(row["home_team_abbr"]))
        away = team_by_abbr.get(str(row["away_team_abbr"]))
        if home is None or away is None:
            # A schedule entry whose teams never appear in the season box scores
            # (e.g. an exhibition opponent) has no provider team identity here.
            skipped.append(game)
            continue
        contest_id = canonical_id(spec, SportsEntityKind.CONTEST, game)
        contest_by_game[game] = contest_id
        postseason = str(row["game_type"]) == "P"
        postseason_by_game[game] = postseason
        completed = str(row["game_state"]) in {"OFF", "FINAL"}
        start = datetime.fromisoformat(str(row["game_time"]).replace("Z", "+00:00"))
        semantic["contest"].append(
            {
                "contest_id": contest_id,
                "sport_id": spec.sport_id,
                "competition_edition_id": edition_id,
                "scheduled_start_at": start,
                "actual_start_at": start if completed else None,
                "venue": row.get("venue"),
                "home_away_supported": True,
                "source_authority": authority,
            }
        )
        for order, (side, provider_team) in enumerate((("home", home), ("away", away))):
            semantic["contest_team"].append(
                {
                    "contest_id": contest_id,
                    "team_id": teams[provider_team],
                    "side": (ContestSide.HOME if side == "home" else ContestSide.AWAY).value,
                    "side_order": order,
                    "score": row[f"{side}_score"] if completed else None,
                }
            )
        periods = sorted(pbp_periods.get(game, {}).items())
        semantic["contest_period"].extend(
            _period_rows(spec, contest_id, periods, postseason=postseason)
        )
        semantic["provider_identity_crosswalk"].append(
            _crosswalk_row(
                spec,
                SportsEntityKind.CONTEST,
                game,
                authority=authority,
                metadata={
                    "game_type": row.get("game_type"),
                    "game_state": row.get("game_state"),
                    "completed": completed,
                    "play_by_play_available": bool(row.get("PBP")),
                    "player_box_available": bool(row.get("skater_box")),
                    "team_box_available": bool(row.get("team_box")),
                },
            )
        )

    unknown_games = sorted(set(pbp_periods) - set(contest_by_game))
    if unknown_games:
        raise IngestError(
            f"NHL play-by-play references games absent from the schedule: {unknown_games[:5]}"
        )

    rows = pbp.to_pylist()
    envelope: dict[str, list[Any]] = {name: [] for name in _ENVELOPE_COLUMNS}
    for row in rows:
        game = int(row["game_id"])
        contest_id = contest_by_game[game]
        period = int(row["period"])
        shootout = str(row.get("period_type")) == "SHOOTOUT"
        seconds = row.get("period_seconds")
        abbr = row.get("event_team_abbr")
        provider_team = team_by_abbr.get(str(abbr)) if abbr is not None else None
        player = row.get("event_player_1_id")
        envelope["contest_id"].append(contest_id)
        envelope["contest_period_id"].append(period_id(contest_id, period))
        envelope["sequence_index"].append(f"{int(row['event_idx']):06d}")
        envelope["source_event_id"].append(str(row["event_id"]))
        envelope["provider_namespace"].append(spec.namespace)
        envelope["provider_event_type"].append(str(row["event_type"] or "UNKNOWN"))
        envelope["canonical_time_ns"].append(
            None
            if shootout
            else canonical_time_ns(
                spec,
                period=period,
                clock_s=float(seconds) if seconds is not None else None,
                postseason=postseason_by_game[game],
            )
        )
        envelope["source_clock_json"].append(
            json.dumps(
                {
                    "period": period,
                    "period_type": row.get("period_type"),
                    "clock": row.get("period_time"),
                    "direction": "count_up",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        envelope["team_id"].append(teams.get(provider_team) if provider_team else None)
        envelope["subject_id"].append(subject_id(spec, player) if player is not None else None)
        envelope["attributes_json"].append(_attributes(row, NHL_EVENT_ATTRIBUTES))
        envelope["attributes_schema_id"].append(spec.attributes_schema_id)
        envelope["attributes_schema_version"].append(INGEST_VERSION)
        envelope["period_number"].append(period)
        envelope["provider_game_id"].append(str(game))

    def player_ids(table: pa.Table) -> pa.Table:
        return _with_ids(
            table,
            contest_by_game,
            "game_id",
            subject=lambda value: subject_id(spec, value),
            subject_column="player_id",
            teams=teams,
            team_column="team_id",
        )

    skater = assets["skater_game"]
    goalie = assets["goalie_game"]
    artifacts = {
        "pbp": (_envelope_table(envelope, pbp), PBP_GRAIN),
        "schedule": (_with_ids(schedule, contest_by_game, "game_id"), GAME_SUMMARY_GRAIN),
        "skater_game": (player_ids(skater), PLAYER_GAME_GRAIN),
        "goalie_game": (player_ids(goalie), PLAYER_GAME_GRAIN),
        "team_game": (
            _with_ids(team_box, contest_by_game, "game_id", teams=teams, team_column="team_id"),
            TEAM_GAME_GRAIN,
        ),
    }
    names: dict[int, str] = {}
    for table in (skater, goalie):
        names.update(zip(_to_list(table["player_id"]), _to_list(table["player_name"]), strict=True))
    for player in sorted(names):
        semantic["provider_identity_crosswalk"].append(
            _crosswalk_row(
                spec,
                SportsEntityKind.SUBJECT,
                player,
                authority=authority,
                canonical=subject_id(spec, player),
                metadata={"display_name": names[player]},
            )
        )
    max_period = max((period for periods in pbp_periods.values() for period in periods), default=3)
    shootout_games = {
        game
        for game, periods in pbp_periods.items()
        if any(value == "Shootout" for value in periods.values())
    }
    return LeagueResult(
        spec=spec,
        edition_id=edition_id,
        edition_label=label,
        season=season,
        semantic=semantic,
        artifacts=artifacts,
        clock_mappings=[
            *clock_mappings(spec, max_period=min(max_period, 4), postseason=False),
            *clock_mappings(spec, max_period=max_period, postseason=True),
        ],
        reconciliation={
            **_score_reconciliation(
                [row for row in schedule_rows if int(row["game_id"]) in contest_by_game],
                pbp,
                game_column="game_id",
                order_column="event_idx",
                home_score="home_score",
                away_score="away_score",
                final_home=lambda row: row["home_score"],
                final_away=lambda row: row["away_score"],
                completed=lambda row: str(row["game_state"]) in {"OFF", "FINAL"},
                schedule_game=lambda row: int(row["game_id"]),
                shootout_games=shootout_games,
            ),
            "schedule_games_without_team_identity": skipped,
        },
    )


# ---------------------------------------------------------------------------
# Shared table builders
# ---------------------------------------------------------------------------

_ENVELOPE_COLUMNS = (
    "contest_id",
    "contest_period_id",
    "sequence_index",
    "source_event_id",
    "provider_namespace",
    "provider_event_type",
    "canonical_time_ns",
    "source_clock_json",
    "team_id",
    "subject_id",
    "attributes_json",
    "attributes_schema_id",
    "attributes_schema_version",
    "period_number",
    "provider_game_id",
)
_ENVELOPE_TYPES = {"canonical_time_ns": pa.int64(), "period_number": pa.int32()}


def _envelope_table(envelope: Mapping[str, list[Any]], source: pa.Table) -> pa.Table:
    arrays: list[tuple[str, pa.Array | pa.ChunkedArray]] = [
        (name, pa.array(envelope[name], type=_ENVELOPE_TYPES.get(name, pa.string())))
        for name in _ENVELOPE_COLUMNS
    ]
    arrays.extend(_preserve(source))
    table = pa.table(dict(arrays))
    return table.sort_by([("contest_id", "ascending"), ("sequence_index", "ascending")])


def _with_ids(
    table: pa.Table,
    contest_by_game: Mapping[int, str],
    game_column: str,
    *,
    subject: Callable[[object], str] | None = None,
    subject_column: str | None = None,
    teams: Mapping[str, str] | None = None,
    team_column: str | None = None,
) -> pa.Table:
    """Prefix canonical identities to a source table; keep every source column."""
    games = [int(value) for value in _to_list(table[game_column])]
    keep = [game in contest_by_game for game in games]
    filtered = table.filter(pa.array(keep))
    columns: list[tuple[str, pa.Array | pa.ChunkedArray]] = [
        (
            "contest_id",
            pa.array([contest_by_game[game] for game in games if game in contest_by_game]),
        )
    ]
    if subject is not None and subject_column is not None:
        columns.append(
            (
                "subject_id",
                pa.array([subject(value) for value in _to_list(filtered[subject_column])]),
            )
        )
    if teams is not None and team_column is not None:
        columns.append(
            (
                "team_id",
                pa.array([teams.get(str(value)) for value in _to_list(filtered[team_column])]),
            )
        )
    columns.extend(_preserve(filtered))
    out = pa.table(dict(columns))
    sort = [("contest_id", "ascending")]
    if subject is not None:
        sort.append(("subject_id", "ascending"))
    elif teams is not None:
        sort.append(("team_id", "ascending"))
    return out.sort_by(sort)


def _score_reconciliation(
    schedule_rows: Sequence[Mapping[str, Any]],
    pbp: pa.Table,
    *,
    game_column: str,
    order_column: str,
    home_score: str,
    away_score: str,
    final_home: Callable[[Mapping[str, Any]], Any],
    final_away: Callable[[Mapping[str, Any]], Any],
    completed: Callable[[Mapping[str, Any]], bool],
    schedule_game: Callable[[Mapping[str, Any]], int],
    shootout_games: set[int] | frozenset[int] = frozenset(),
) -> dict[str, Any]:
    """Compare the last play-by-play score state with the schedule final score.

    A hockey shootout adds one goal to the winner's official score without a
    corresponding play-by-play score state, so a tied final state in a shootout
    game that differs by exactly one goal is classified, not counted as a
    mismatch. Every other disagreement is reported as a provider discrepancy.
    """
    ordered = pbp.select([game_column, order_column, home_score, away_score]).sort_by(
        [(game_column, "ascending"), (order_column, "ascending")]
    )
    last: dict[int, tuple[Any, Any]] = {}
    for game, home, away in zip(
        _to_list(ordered[game_column]),
        _to_list(ordered[home_score]),
        _to_list(ordered[away_score]),
        strict=True,
    ):
        last[int(game)] = (home, away)
    checked = matched = shootout_decided = 0
    mismatches: list[dict[str, Any]] = []
    for row in schedule_rows:
        game = schedule_game(row)
        if not completed(row) or game not in last:
            continue
        checked += 1
        expected = (final_home(row), final_away(row))
        home, away = last[game]
        if last[game] == expected:
            matched += 1
            continue
        if (
            game in shootout_games
            and home == away
            and home is not None
            and abs(int(expected[0]) - int(expected[1])) == 1
            and min(int(expected[0]), int(expected[1])) == int(home)
        ):
            shootout_decided += 1
            continue
        if len(mismatches) < 20:
            mismatches.append({"game": game, "pbp": list(last[game]), "schedule": list(expected)})
    return {
        "completed_games_with_pbp": checked,
        "final_score_matches": matched,
        "shootout_decided": shootout_decided,
        "provider_score_discrepancies": checked - matched - shootout_decided,
        "discrepancy_examples": mismatches,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _read_assets(
    pins: Sequence[PinnedAsset], league: LeagueSpec, *, read: Callable[[PinnedAsset], pa.Table]
) -> tuple[dict[str, pa.Table], dict[str, PinnedAsset]]:
    by_tag = {pin.tag: pin for pin in pins}
    tables: dict[str, pa.Table] = {}
    chosen: dict[str, PinnedAsset] = {}
    for family, tag in league.families.items():
        pin = by_tag.get(tag)
        if pin is None:
            raise IngestError(f"{league.league_id}: no pinned asset for family {family} ({tag})")
        tables[family] = read(pin)
        chosen[family] = pin
    return tables, chosen


def canonicalize(
    read: Callable[[PinnedAsset], pa.Table], *, snapshot: Mapping[str, Any] | None = None
) -> list[tuple[LeagueResult, dict[str, PinnedAsset]]]:
    """Canonicalize every pinned league slice from Bronze tables."""
    data = snapshot or load_snapshot()
    pins = pinned_assets(data)
    results = []
    for league, build in ((NBA, _nba), (NHL, _nhl)):
        tables, chosen = _read_assets(pins, league, read=read)
        seasons = {pin.season for pin in chosen.values()}
        if len(seasons) != 1:
            raise IngestError(f"{league.league_id}: pinned assets span several seasons {seasons}")
        season = seasons.pop()
        authority = f"{league.provider_label} release snapshot {data['snapshot']}: " + ", ".join(
            f"{pin.tag}/{pin.asset_name}#{pin.asset_id}" for pin in chosen.values()
        )
        result = build(tables, season=season, authority=authority)
        result.reconciliation["source_rows"] = {
            family: table.num_rows for family, table in tables.items()
        }
        result.reconciliation["silver_rows"] = {
            family: table.num_rows for family, (table, _grain) in result.artifacts.items()
        }
        result.reconciliation["schema_fingerprints"] = {
            family: _schema_fingerprint(table.schema) for family, table in tables.items()
        }
        results.append((result, chosen))
    return results


def read_bronze_table(path: str) -> pa.Table:
    table = pq.read_table(path)
    # Drop pandas index metadata; keep columns and types exactly.
    return table.replace_schema_metadata(None)


def grain_rows(table: pa.Table, grain: DataGrain) -> list[dict[str, Any]]:
    columns = GRAIN_COLUMNS[grain.kind]
    return [
        dict(zip(grain.axes, values, strict=True))
        for values in zip(*(_to_list(table[name]) for name in columns), strict=True)
    ]


def null_identity_counts(table: pa.Table, grain: DataGrain) -> dict[str, int]:
    return {name: table[name].null_count for name in GRAIN_COLUMNS[grain.kind]}


def ingested_at() -> datetime:
    return datetime.now(UTC)
