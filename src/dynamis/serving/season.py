"""SeasonLab: bounded reads and explicit-denominator statistics over season aggregates.

A PLAYER_SEASON artifact is one Parquet file per competition edition and provider
family. Its grain is ``subject × team × competition_edition × position_group``: a
player who played for two teams, or in two position groups, owns two rows. Every
statistic served here therefore names its population in *rows of that grain*, never
"players", and never a league population the caller did not select.

Metric identity is provider/method semantics, not a column name. The registry below
maps SkillCorner's documented column grammar to labelled, united metric definitions
under a versioned rule; an unrecognized column is refused rather than guessed.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import duckdb

SEASON_METRIC_REGISTRY_VERSION = "skillcorner-season-metrics/1"
SKILLCORNER_GLOSSARY_URL = "https://skillcorner.crunch.help/en/glossaries/physical-data-glossary"
SKILLCORNER_INCLUSION_RULE = (
    "Upstream SkillCorner aggregates include only individual match performances above "
    "60 minutes played; the served row is the provider's season aggregate of those "
    "performances."
)

#: Identity columns shared by every family, always projected with a row.
IDENTITY_COLUMNS: tuple[str, ...] = (
    "subject_id",
    "player_name",
    "player_short_name",
    "team_id",
    "team_name",
    "position_group",
    "competition_edition_id",
)

PopulationScope = Literal["edition", "position", "team"]
POPULATION_SCOPES: tuple[PopulationScope, ...] = ("edition", "position", "team")


@dataclass(frozen=True, slots=True)
class SeasonMetricSpec:
    """One provider-defined season metric under the versioned registry."""

    metric_id: str
    column: str
    family: str
    label: str
    group: str
    unit: str
    basis: str
    definition: str
    split: str | None = None
    base: str | None = None
    exposure: bool = False
    higher_is: Literal["more", "faster", "neutral"] = "more"


class SeasonDataError(RuntimeError):
    """A season artifact or request cannot be served as asked."""


# ---------------------------------------------------------------------------
# Registry: SkillCorner A-League player-season aggregate families.
# ---------------------------------------------------------------------------

_PHYSICAL_SPLITS = {
    "all": ("Full match", "all phases of play"),
    "tip": ("TIP", "while the player's team is in possession"),
    "otip": ("OTIP", "while the opponent team is in possession"),
}

_PHYSICAL_BASES: dict[str, tuple[str, str, str, str]] = {
    # base column stem: (label, group, unit, definition)
    "total_distance": ("Total distance", "Volume", "m", "Distance covered"),
    "total_metersperminute": (
        "Distance rate",
        "Volume",
        "m/min",
        "Distance covered per minute played",
    ),
    "running_distance": ("Running distance", "Volume", "m", "Distance covered while running"),
    "hsr_distance": ("HSR distance", "Volume", "m", "High-speed running distance"),
    "hsr_count": ("HSR efforts", "Volume", "count", "High-speed running efforts"),
    "sprint_distance": ("Sprint distance", "Volume", "m", "Sprinting distance"),
    "sprint_count": ("Sprint efforts", "Volume", "count", "Sprint efforts"),
    "hi_distance": (
        "HI distance",
        "Volume",
        "m",
        "High-intensity distance (HSR + sprint)",
    ),
    "hi_count": ("HI efforts", "Volume", "count", "High-intensity efforts (HSR + sprint)"),
    "medaccel_count": ("Medium accelerations", "Accel / decel", "count", "Medium accelerations"),
    "highaccel_count": ("High accelerations", "Accel / decel", "count", "High accelerations"),
    "meddecel_count": ("Medium decelerations", "Accel / decel", "count", "Medium decelerations"),
    "highdecel_count": ("High decelerations", "Accel / decel", "count", "High decelerations"),
    "explacceltohsr_count": (
        "Explosive accel → HSR",
        "Explosive transitions",
        "count",
        "Explosive accelerations reaching high-speed running",
    ),
    "explacceltosprint_count": (
        "Explosive accel → sprint",
        "Explosive transitions",
        "count",
        "Explosive accelerations reaching sprint speed",
    ),
}

_PHYSICAL_SINGLE: dict[str, tuple[str, str, str, str, str]] = {
    # column: (label, group, unit, basis, definition)
    "count_match": (
        "Included matches",
        "Exposure",
        "matches",
        "season count",
        "Match performances included in the aggregate",
    ),
    "count_match_failed": (
        "Failed matches",
        "Exposure",
        "matches",
        "season count",
        "Match performances the provider could not measure",
    ),
    "psv99": (
        "PSV-99",
        "Peak speed",
        "km/h",
        "season value",
        "Peak sprint velocity: the 99th percentile of the player's speed",
    ),
    "psv99_top5": (
        "PSV-99 top-5",
        "Peak speed",
        "km/h",
        "season value",
        "Mean of the player's five highest match PSV-99 values",
    ),
    "timetohsr_top3": (
        "Time to HSR (top 3)",
        "Explosive transitions",
        "s",
        "season value",
        "Mean of the three fastest accelerations into high-speed running",
    ),
    "timetosprint_top3": (
        "Time to sprint (top 3)",
        "Explosive transitions",
        "s",
        "season value",
        "Mean of the three fastest accelerations into sprint speed",
    ),
}

_RUN_TYPES: dict[str, str] = {
    "offballrun": "All off-ball runs",
    "behindrun": "Runs in behind",
    "comingshortrun": "Coming short",
    "crossreceiverrun": "Cross receiver",
    "droppingoffrun": "Dropping off",
    "overlaprun": "Overlap",
    "pullinghalfspacerun": "Pulling half-space",
    "pullingwiderun": "Pulling wide",
    "aheadoftheballrun": "Ahead of the ball",
    "supportrun": "Support",
    "underlaprun": "Underlap",
}

_RUN_QUALIFIERS: dict[str, tuple[str, str]] = {
    "": ("Runs", "Off-ball runs of this type"),
    "shotwithin10s": ("Shot within 10 s", "Runs followed by a team shot within 10 s"),
    "goalwithin10s": ("Goal within 10 s", "Runs followed by a team goal within 10 s"),
    "targeted": ("Targeted", "Runs the ball carrier attempted to pass to"),
    "received": ("Received", "Runs on which the runner received the ball"),
    "abovehsr": ("Above HSR", "Runs reaching high-speed running"),
    "penaltyarea": ("Into penalty area", "Runs into the penalty area"),
    "dangerous": ("Dangerous", "Runs the provider classifies as dangerous"),
    "dangerous_targeted": ("Dangerous · targeted", "Dangerous runs that were targeted"),
    "dangerous_received": ("Dangerous · received", "Dangerous runs that were received"),
}

_OBR_GROUP = {
    "": "Volume",
    "abovehsr": "Volume",
    "penaltyarea": "Volume",
    "targeted": "Service",
    "received": "Service",
    "dangerous": "Threat",
    "dangerous_targeted": "Threat",
    "dangerous_received": "Threat",
    "shotwithin10s": "Outcome",
    "goalwithin10s": "Outcome",
}

_EXPOSURE_RATE: dict[str, tuple[str, str, str]] = {
    "minutes": ("Minutes per match", "min", "Average minutes played per included match"),
    "minutes_tip": ("TIP minutes per match", "min", "Average team-in-possession minutes"),
    "minutes_otip": ("OTIP minutes per match", "min", "Average opponent-in-possession minutes"),
}

_EXPOSURE_COUNT: dict[str, tuple[str, str]] = {
    "performance_count": ("Match performances", "Performances in the provider population"),
    "performance_included_count": ("Included performances", "Performances inside the aggregate"),
    "performance_failed_count": ("Failed performances", "Performances the provider failed"),
}

_PASSING: dict[str, tuple[str, str, str, str, str]] = {
    # column: (label, group, unit, basis, definition)
    "passopportunity_count_total": (
        "Pass opportunities",
        "Volume",
        "count",
        "season total",
        "Teammate options available to the player while in possession",
    ),
    "passopportunity_count_p30tip": (
        "Pass opportunities",
        "Volume",
        "count",
        "per 30 min TIP",
        "Teammate options available to the player while in possession",
    ),
    "pass_count_attempted_total": (
        "Passes attempted",
        "Volume",
        "count",
        "season total",
        "Passes attempted",
    ),
    "pass_count_attempted_p30tip": (
        "Passes attempted",
        "Volume",
        "count",
        "per 30 min TIP",
        "Passes attempted",
    ),
    "pass_count_completed_p30tip": (
        "Passes completed",
        "Volume",
        "count",
        "per 30 min TIP",
        "Passes completed",
    ),
    "pass_pct_completed": (
        "Completion",
        "Efficiency",
        "%",
        "season ratio",
        "Completed passes as a share of attempted passes",
    ),
    "pass_avgxpass_attempted": (
        "Mean xPass",
        "Difficulty",
        "%",
        "season mean",
        "Provider-modelled completion probability of attempted passes",
    ),
    "pass_avgdistance": ("Mean pass distance", "Volume", "m", "season mean", "Mean pass length"),
    "pass_count_longrange_attempted_p30tip": (
        "Long passes",
        "Style",
        "count",
        "per 30 min TIP",
        "Long-range passes attempted",
    ),
    "pass_count_onetouch_attempted_p30tip": (
        "One-touch passes",
        "Style",
        "count",
        "per 30 min TIP",
        "One-touch passes attempted",
    ),
    "pass_count_quickpass_attempted_p30tip": (
        "Quick passes",
        "Style",
        "count",
        "per 30 min TIP",
        "Quick passes attempted",
    ),
    "pass_count_onetouch_dangerous_attempted_p30tip": (
        "One-touch dangerous",
        "Threat",
        "count",
        "per 30 min TIP",
        "Dangerous one-touch passes attempted",
    ),
    "pass_count_quickpass_dangerous_attempted_p30tip": (
        "Quick dangerous",
        "Threat",
        "count",
        "per 30 min TIP",
        "Dangerous quick passes attempted",
    ),
    "pass_count_goalwithin10s_p30tip": (
        "Team goal within 10 s",
        "Outcome",
        "count",
        "per 30 min TIP",
        "Passes followed by a team goal within 10 s",
    ),
    "pass_count_shotwithin10s_p30tip": (
        "Team shot within 10 s",
        "Outcome",
        "count",
        "per 30 min TIP",
        "Passes followed by a team shot within 10 s",
    ),
    "passopportunity_count_linebreak_p30tip": (
        "Line-break opportunities",
        "Line-breaking",
        "count",
        "per 30 min TIP",
        "Line-breaking pass options available",
    ),
    "pass_count_linebreak_attempted_p30tip": (
        "Line-break attempted",
        "Line-breaking",
        "count",
        "per 30 min TIP",
        "Line-breaking passes attempted",
    ),
    "pass_count_linebreak_completed_p30tip": (
        "Line-break completed",
        "Line-breaking",
        "count",
        "per 30 min TIP",
        "Line-breaking passes completed",
    ),
    "passopportunity_count_torun_p30tip": (
        "Pass-to-run opportunities",
        "Pass to run",
        "count",
        "per 30 min TIP",
        "Options to pass to a teammate's off-ball run",
    ),
    "pass_count_torun_attempted_p30tip": (
        "Pass-to-run attempted",
        "Pass to run",
        "count",
        "per 30 min TIP",
        "Passes attempted to a teammate's off-ball run",
    ),
    "pass_count_torun_completed_p30tip": (
        "Pass-to-run completed",
        "Pass to run",
        "count",
        "per 30 min TIP",
        "Passes completed to a teammate's off-ball run",
    ),
    "pass_pct_torun_completed": (
        "Pass-to-run completion",
        "Pass to run",
        "%",
        "season ratio",
        "Completed share of passes attempted to runs",
    ),
    "pass_avgxpass_torun_attempted": (
        "Pass-to-run mean xPass",
        "Pass to run",
        "%",
        "season mean",
        "Provider-modelled completion probability of passes to runs",
    ),
    "pass_count_torun_shotwithin10s_p30tip": (
        "Pass-to-run · shot within 10 s",
        "Pass to run",
        "count",
        "per 30 min TIP",
        "Passes to runs followed by a team shot within 10 s",
    ),
    "pass_count_torun_goalwithin10s_p30tip": (
        "Pass-to-run · goal within 10 s",
        "Pass to run",
        "count",
        "per 30 min TIP",
        "Passes to runs followed by a team goal within 10 s",
    ),
    "passopportunity_count_dangerous_p30tip": (
        "Dangerous opportunities",
        "Threat",
        "count",
        "per 30 min TIP",
        "Dangerous pass options available",
    ),
    "pass_count_dangerous_attempted_p30tip": (
        "Dangerous attempted",
        "Threat",
        "count",
        "per 30 min TIP",
        "Dangerous passes attempted",
    ),
    "pass_count_dangerous_completed_p30tip": (
        "Dangerous completed",
        "Threat",
        "count",
        "per 30 min TIP",
        "Dangerous passes completed",
    ),
    "pass_pct_dangerous_completed": (
        "Dangerous completion",
        "Threat",
        "%",
        "season ratio",
        "Completed share of dangerous passes attempted",
    ),
    "pass_count_difficultpass_attempted_p30tip": (
        "Difficult passes",
        "Difficulty",
        "count",
        "per 30 min TIP",
        "Passes attempted that the provider classifies as difficult",
    ),
}

_OBR_COUNT = re.compile(
    r"^(?P<run>[a-z]+run)_count_(?:(?P<qual>[a-z0-9_]+?)_)?p30tip$",
)
_OBR_DISTANCE = re.compile(r"^(?P<run>[a-z]+run)_avgdistance$")
_PHYSICAL = re.compile(r"^(?P<base>[a-z]+(?:_[a-z]+)?)_full_(?P<split>all|tip|otip)$")


def _metric_id(family: str, column: str) -> str:
    return f"skillcorner.{family}.{column}"


def _physical_spec(column: str) -> SeasonMetricSpec | None:
    if column in _PHYSICAL_SINGLE:
        label, group, unit, basis, definition = _PHYSICAL_SINGLE[column]
        return SeasonMetricSpec(
            metric_id=_metric_id("physical", column),
            column=column,
            family="physical",
            label=label,
            group=group,
            unit=unit,
            basis=basis,
            definition=definition,
            exposure=group == "Exposure",
            higher_is="neutral" if group == "Exposure" or unit == "s" else "more",
        )
    match = _PHYSICAL.match(column)
    if match is None:
        return None
    base, split = match["base"], match["split"]
    split_label, split_phrase = _PHYSICAL_SPLITS[split]
    if base == "minutes":
        return SeasonMetricSpec(
            metric_id=_metric_id("physical", column),
            column=column,
            family="physical",
            label=f"Minutes · {split_label}",
            group="Exposure",
            unit="min",
            basis="per match (season mean)",
            definition=f"Average minutes played {split_phrase} per included match",
            split=split,
            base=base,
            exposure=True,
            higher_is="neutral",
        )
    if base not in _PHYSICAL_BASES:
        return None
    label, group, unit, definition = _PHYSICAL_BASES[base]
    return SeasonMetricSpec(
        metric_id=_metric_id("physical", column),
        column=column,
        family="physical",
        label=label if split == "all" else f"{label} · {split_label}",
        group=group,
        unit=unit,
        basis="per match (season mean)",
        definition=f"{definition} {split_phrase}, averaged over included match performances",
        split=split,
        base=base,
    )


def _exposure_spec(family: str, column: str) -> SeasonMetricSpec | None:
    if column in _EXPOSURE_RATE:
        label, unit, definition = _EXPOSURE_RATE[column]
        return SeasonMetricSpec(
            metric_id=_metric_id(family, column),
            column=column,
            family=family,
            label=label,
            group="Exposure",
            unit=unit,
            basis="per match (season mean)",
            definition=definition,
            exposure=True,
            higher_is="neutral",
        )
    if column in _EXPOSURE_COUNT:
        label, definition = _EXPOSURE_COUNT[column]
        return SeasonMetricSpec(
            metric_id=_metric_id(family, column),
            column=column,
            family=family,
            label=label,
            group="Exposure",
            unit="matches",
            basis="season count",
            definition=definition,
            exposure=True,
            higher_is="neutral",
        )
    return None


def _obr_spec(column: str) -> SeasonMetricSpec | None:
    exposure = _exposure_spec("obr", column)
    if exposure is not None:
        return exposure
    if column == "offballrun_count_total":
        return SeasonMetricSpec(
            metric_id=_metric_id("obr", column),
            column=column,
            family="obr",
            label="All off-ball runs",
            group="Volume",
            unit="count",
            basis="season total",
            definition="Off-ball runs of every type across included performances",
            base="offballrun",
        )
    match = _OBR_DISTANCE.match(column)
    if match is not None and match["run"] in _RUN_TYPES:
        run_label = _RUN_TYPES[match["run"]]
        return SeasonMetricSpec(
            metric_id=_metric_id("obr", column),
            column=column,
            family="obr",
            label=f"{run_label} · mean distance",
            group="Distance",
            unit="m",
            basis="season mean",
            definition=f"Mean distance covered by {run_label.lower()} runs",
            base=match["run"],
            split="avgdistance",
            higher_is="neutral",
        )
    match = _OBR_COUNT.match(column)
    if match is None or match["run"] not in _RUN_TYPES:
        return None
    qualifier = match["qual"] or ""
    if qualifier not in _RUN_QUALIFIERS:
        return None
    run_label = _RUN_TYPES[match["run"]]
    qual_label, qual_definition = _RUN_QUALIFIERS[qualifier]
    return SeasonMetricSpec(
        metric_id=_metric_id("obr", column),
        column=column,
        family="obr",
        label=run_label if qualifier == "" else f"{run_label} · {qual_label}",
        group=_OBR_GROUP[qualifier],
        unit="count",
        basis="per 30 min TIP",
        definition=f"{qual_definition} ({run_label.lower()}), per 30 minutes of team possession",
        base=match["run"],
        split=qualifier or "runs",
    )


def _passing_spec(column: str) -> SeasonMetricSpec | None:
    exposure = _exposure_spec("passing", column)
    if exposure is not None:
        return exposure
    if column not in _PASSING:
        return None
    label, group, unit, basis, definition = _PASSING[column]
    return SeasonMetricSpec(
        metric_id=_metric_id("passing", column),
        column=column,
        family="passing",
        label=label,
        group=group,
        unit=unit,
        basis=basis,
        definition=definition,
    )


_FAMILY_RESOLVERS = {
    "physical": _physical_spec,
    "obr": _obr_spec,
    "passing": _passing_spec,
}

FAMILY_LABELS: dict[str, str] = {
    "physical": "Physical",
    "obr": "Off-ball runs",
    "passing": "Passing",
}

#: Columns carried as identity/provenance, never offered as metrics.
_NON_METRIC_COLUMNS = frozenset(
    {
        *IDENTITY_COLUMNS,
        "player_id",
        "player_birthdate",
        "provider_team_id",
        "provider_player_id",
        "competition_name",
        "competition_id",
        "season_name",
        "season_id",
        "provider_season_id",
        "provider_competition_edition_id",
    }
)

#: The exposure column that counts match performances inside each family row.
MATCH_COUNT_COLUMN = {
    "physical": "count_match",
    "obr": "performance_included_count",
    "passing": "performance_included_count",
}


def family_metrics(family: str, columns: Iterable[str]) -> list[SeasonMetricSpec]:
    """Resolve every metric column of one family; refuse unknown columns."""
    resolver = _FAMILY_RESOLVERS.get(family)
    if resolver is None:
        raise SeasonDataError(f"season family {family!r} has no registered metric resolver")
    specs: list[SeasonMetricSpec] = []
    unknown: list[str] = []
    for column in columns:
        if column in _NON_METRIC_COLUMNS:
            continue
        spec = resolver(column)
        if spec is None:
            unknown.append(column)
        else:
            specs.append(spec)
    if unknown:
        raise SeasonDataError(
            f"{family} columns are not covered by {SEASON_METRIC_REGISTRY_VERSION}: "
            + ", ".join(sorted(unknown))
        )
    return specs


# ---------------------------------------------------------------------------
# Bounded reads
# ---------------------------------------------------------------------------


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


@lru_cache(maxsize=32)
def _schema_columns(path: str, mtime_ns: int) -> tuple[str, ...]:
    del mtime_ns  # cache key only: a rewritten artifact invalidates the entry
    with duckdb.connect() as connection:
        rows = connection.execute(
            "SELECT name FROM parquet_schema(?) WHERE name <> 'schema'", [path]
        ).fetchall()
    return tuple(str(row[0]) for row in rows)


def artifact_columns(path: Path) -> tuple[str, ...]:
    return _schema_columns(str(path), path.stat().st_mtime_ns)


@dataclass(frozen=True, slots=True)
class SeasonRowFilter:
    team_id: str | None = None
    position_group: str | None = None
    subject_ids: tuple[str, ...] = ()
    min_matches: int | None = None


def _where(family: str, filters: SeasonRowFilter) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if filters.team_id is not None:
        clauses.append("team_id = ?")
        params.append(filters.team_id)
    if filters.position_group is not None:
        clauses.append("position_group = ?")
        params.append(filters.position_group)
    if filters.subject_ids:
        clauses.append(f"subject_id IN ({', '.join('?' for _ in filters.subject_ids)})")
        params.extend(filters.subject_ids)
    if filters.min_matches is not None and filters.min_matches > 1:
        clauses.append(f"{_quote(MATCH_COUNT_COLUMN[family])} >= ?")
        params.append(filters.min_matches)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def read_rows(
    path: Path,
    *,
    family: str,
    metrics: Sequence[str],
    filters: SeasonRowFilter,
    limit: int,
    offset: int = 0,
) -> tuple[int, list[dict[str, Any]]]:
    """Project identity + requested metric columns for a filtered, bounded page."""
    available = set(artifact_columns(path))
    missing = [column for column in metrics if column not in available]
    if missing:
        raise SeasonDataError(f"requested metrics are not in this artifact: {sorted(missing)}")
    projection = [
        *IDENTITY_COLUMNS,
        MATCH_COUNT_COLUMN[family],
        *(column for column in metrics if column != MATCH_COUNT_COLUMN[family]),
    ]
    where, params = _where(family, filters)
    select = ", ".join(_quote(column) for column in projection)
    source = "read_parquet(?)"
    with duckdb.connect() as connection:
        total_row = connection.execute(
            f"SELECT count(*) FROM {source}{where}", [str(path), *params]
        ).fetchone()
        total = int(total_row[0]) if total_row else 0
        cursor = connection.execute(
            f"SELECT {select} FROM {source}{where} "
            "ORDER BY team_name, player_name, position_group, subject_id "
            "LIMIT ? OFFSET ?",
            [str(path), *params, limit, offset],
        )
        names = [description[0] for description in cursor.description]
        rows = [dict(zip(names, values, strict=True)) for values in cursor.fetchall()]
    for row in rows:
        for key, value in list(row.items()):
            if isinstance(value, float) and not math.isfinite(value):
                row[key] = None
    return total, rows


@dataclass(frozen=True, slots=True)
class PopulationSummary:
    rows: int
    subjects: int
    teams: list[tuple[str, str, int]]
    position_groups: list[tuple[str, int]]


def population_summary(path: Path) -> PopulationSummary:
    with duckdb.connect() as connection:
        source = "read_parquet(?)"
        totals = connection.execute(
            f"SELECT count(*), count(DISTINCT subject_id) FROM {source}", [str(path)]
        ).fetchone()
        teams = connection.execute(
            f"SELECT team_id, any_value(team_name), count(*) FROM {source} "
            "GROUP BY team_id ORDER BY 2",
            [str(path)],
        ).fetchall()
        positions = connection.execute(
            f"SELECT position_group, count(*) FROM {source} GROUP BY 1 ORDER BY 1",
            [str(path)],
        ).fetchall()
    return PopulationSummary(
        rows=int(totals[0]) if totals else 0,
        subjects=int(totals[1]) if totals else 0,
        teams=[(str(team), str(name), int(count)) for team, name, count in teams],
        position_groups=[(str(group), int(count)) for group, count in positions],
    )


# ---------------------------------------------------------------------------
# Explicit-denominator statistics
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RankedValue:
    value: float | None
    population_n: int
    valid_n: int
    rank: int | None
    percentile: float | None
    minimum: float | None
    median: float | None
    maximum: float | None


def rank_within(value: float | None, population: Sequence[float | None]) -> RankedValue:
    """Rank one value inside an explicit population of values.

    ``rank`` is 1 for the largest value (ties share the best rank). ``percentile``
    is the inclusive share of valid population values at or below ``value`` × 100.
    Neither implies "better": the metric's own semantics decide that.
    """
    valid = sorted(float(item) for item in population if item is not None and math.isfinite(item))
    minimum = valid[0] if valid else None
    maximum = valid[-1] if valid else None
    median = None
    if valid:
        middle = len(valid) // 2
        median = valid[middle] if len(valid) % 2 else (valid[middle - 1] + valid[middle]) / 2
    if value is None or not math.isfinite(value) or not valid:
        return RankedValue(
            value=None if value is None or not math.isfinite(value) else value,
            population_n=len(population),
            valid_n=len(valid),
            rank=None,
            percentile=None,
            minimum=minimum,
            median=median,
            maximum=maximum,
        )
    above = sum(1 for item in valid if item > value)
    at_or_below = len(valid) - above
    return RankedValue(
        value=value,
        population_n=len(population),
        valid_n=len(valid),
        rank=above + 1,
        percentile=round(100.0 * at_or_below / len(valid), 1),
        minimum=minimum,
        median=median,
        maximum=maximum,
    )


def population_filter(
    scope: PopulationScope, *, team_id: str, position_group: str, min_matches: int | None
) -> SeasonRowFilter:
    if scope == "team":
        return SeasonRowFilter(team_id=team_id, min_matches=min_matches)
    if scope == "position":
        return SeasonRowFilter(position_group=position_group, min_matches=min_matches)
    return SeasonRowFilter(min_matches=min_matches)


def population_label(
    scope: PopulationScope,
    *,
    edition_label: str,
    competition_name: str,
    team_name: str,
    position_group: str,
    min_matches: int | None,
) -> str:
    base = {
        "edition": f"All {competition_name} {edition_label} rows",
        "position": f"{position_group} rows, {competition_name} {edition_label}",
        "team": f"{team_name} rows, {competition_name} {edition_label}",
    }[scope]
    if min_matches is not None and min_matches > 1:
        base += f", ≥{min_matches} included matches"
    return base


# ---------------------------------------------------------------------------
# Serving assembly
# ---------------------------------------------------------------------------

PERCENTILE_METHOD = (
    "Inclusive percentile: share of population rows with a valid value at or below the "
    "selected row's value, ×100. Rows without a value are excluded from the denominator "
    "and reported as valid_n."
)
RANK_METHOD = "Rank 1 = largest value in the population; tied values share the best rank."
PROFILE_CAVEATS = (
    "A percentile describes position inside the selected population only; it is not a "
    "quality, talent or risk rating.",
    "Values are provider season aggregates; they are not decomposed into matches.",
    "The unit of analysis is a player × team × position-group row, so one player can "
    "contribute several rows to a population.",
)


def metric_views(specs: Sequence[SeasonMetricSpec]) -> list[dict[str, Any]]:
    return [
        {
            "metric_id": spec.metric_id,
            "column": spec.column,
            "family": spec.family,
            "label": spec.label,
            "group": spec.group,
            "unit": spec.unit,
            "basis": spec.basis,
            "definition": spec.definition,
            "split": spec.split,
            "base": spec.base,
            "exposure": spec.exposure,
            "higher_is": spec.higher_is,
        }
        for spec in specs
    ]


def row_view(row: dict[str, Any], *, family: str, metrics: Sequence[str]) -> dict[str, Any]:
    matches = row.get(MATCH_COUNT_COLUMN[family])
    return {
        "subject_id": str(row["subject_id"]),
        "player_name": str(row["player_name"]),
        "player_short_name": row.get("player_short_name"),
        "team_id": str(row["team_id"]),
        "team_name": str(row["team_name"]),
        "position_group": str(row["position_group"]),
        "matches": int(matches) if matches is not None else None,
        "values": {
            column: (float(row[column]) if row.get(column) is not None else None)
            for column in metrics
        },
    }


def resolve_metric_columns(
    family: str, path: Path, requested: Sequence[str] | None
) -> tuple[list[SeasonMetricSpec], list[str]]:
    specs = family_metrics(family, artifact_columns(path))
    by_column = {spec.column: spec for spec in specs}
    by_id = {spec.metric_id: spec for spec in specs}
    if not requested:
        return specs, [spec.column for spec in specs]
    chosen: list[str] = []
    for item in requested:
        spec = by_column.get(item) or by_id.get(item)
        if spec is None:
            raise SeasonDataError(f"metric {item!r} is not defined for the {family} family")
        if spec.column not in chosen:
            chosen.append(spec.column)
    return specs, chosen


def profile_payload(
    path: Path,
    *,
    family: str,
    subject_id: str,
    team_id: str | None,
    position_group: str | None,
    scope: PopulationScope,
    min_matches: int | None,
    requested_metrics: Sequence[str] | None,
    edition_label: str,
    competition_name: str,
    population_team_id: str | None = None,
    population_position_group: str | None = None,
) -> dict[str, Any] | None:
    """The selected row, every requested metric ranked inside one explicit population.

    The population is derived from the selected row unless an explicit team or
    position group is given, which lets two players be ranked against the same
    denominator. A row outside its population is still ranked, and says so.
    """
    _, columns = resolve_metric_columns(family, path, requested_metrics)
    _, candidates = read_rows(
        path,
        family=family,
        metrics=columns,
        filters=SeasonRowFilter(
            subject_ids=(subject_id,), team_id=team_id, position_group=position_group
        ),
        limit=64,
    )
    if not candidates:
        return None
    # Several rows remain when team/position were not specified: the row with the
    # most included matches is the player's primary grain row for this family.
    match_column = MATCH_COUNT_COLUMN[family]
    selected = max(
        candidates,
        key=lambda row: (
            row.get(match_column) or 0,
            str(row["team_id"]),
            str(row["position_group"]),
        ),
    )
    population = population_filter(
        scope,
        team_id=population_team_id or str(selected["team_id"]),
        position_group=population_position_group or str(selected["position_group"]),
        min_matches=min_matches,
    )
    total, population_rows = read_rows(
        path, family=family, metrics=columns, filters=population, limit=100_000
    )
    selected_key = (selected["subject_id"], selected["team_id"], selected["position_group"])
    in_population = any(
        (row["subject_id"], row["team_id"], row["position_group"]) == selected_key
        for row in population_rows
    )
    population_team_name = next(
        (str(row["team_name"]) for row in population_rows),
        str(selected["team_name"]),
    )
    ranked = []
    for column in columns:
        value = selected.get(column)
        result = rank_within(
            float(value) if value is not None else None,
            [row.get(column) for row in population_rows],
        )
        ranked.append(
            {
                "metric_id": _metric_id(family, column),
                "column": column,
                "value": result.value,
                "rank": result.rank,
                "percentile": result.percentile,
                "valid_n": result.valid_n,
                "population_minimum": result.minimum,
                "population_median": result.median,
                "population_maximum": result.maximum,
            }
        )
    return {
        "row": row_view(selected, family=family, metrics=columns),
        "population": {
            "scope": scope,
            "label": population_label(
                scope,
                edition_label=edition_label,
                competition_name=competition_name,
                team_name=population_team_name,
                position_group=population.position_group or str(selected["position_group"]),
                min_matches=min_matches,
            ),
            "selected_row_in_population": in_population,
            "team_id": population.team_id,
            "position_group": population.position_group,
            "min_matches": min_matches if min_matches and min_matches > 1 else None,
            "rows": total,
            "unit_of_analysis": "player × team × position-group season row",
        },
        "metrics": ranked,
        "percentile_method": PERCENTILE_METHOD,
        "rank_method": RANK_METHOD,
        "caveats": list(PROFILE_CAVEATS),
    }
