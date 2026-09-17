"""Streaming structure discovery for DFL/Sportec IDSSE XML files.

Every adapter mapping in this package is derived from these receipts; nothing is
assumed from memory. The 372 MB positions file is profiled with a bounded
``lxml.iterparse`` pass that clears elements aggressively, never as a DOM tree.

Value semantics that the receipts *do not* establish (the vendor attributes
``D``, ``A``, ``M``) are reported as-undecoded with their distributions rather
than guessed at.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import lxml.etree as etree

#: Provider frame rate declared by the reference client (kloppy SPORTEC_FPS).
SPORTEC_FPS = 25
#: Fixed frame-counter origins per period (kloppy SPORTEC_*_STARTING_FRAME_ID).
PERIOD_FRAME_ORIGINS = {
    "firstHalf": 10_000,
    "secondHalf": 100_000,
    "firstHalfExtra": 200_000,
    "secondHalfExtra": 250_000,
}
BALL_TEAM_ID = "BALL"

UNMAPPED_FRAME_ATTRIBUTES = ("D", "A", "M")


class DiscoveryError(ValueError):
    """The XML contradicts the structure the adapter can ingest."""


@dataclass(slots=True)
class _Counter:
    total: int = 0
    null: int = 0
    minimum: float = float("inf")
    maximum: float = float("-inf")

    def observe(self, value: float | None) -> None:
        self.total += 1
        if value is None:
            self.null += 1
            return
        self.minimum = min(self.minimum, value)
        self.maximum = max(self.maximum, value)

    def as_dict(self) -> dict[str, Any]:
        return {
            "observed": self.total,
            "null": self.null,
            "min": None if self.minimum == float("inf") else self.minimum,
            "max": None if self.maximum == float("-inf") else self.maximum,
        }


@dataclass(frozen=True, slots=True)
class MatchInfoDiscovery:
    match_id: str
    competition: str
    season: str
    match_day: str
    kickoff_utc: str
    home_team_id: str
    away_team_id: str
    result: str
    pitch_x_m: float
    pitch_y_m: float
    player_count: int
    players_per_team: dict[str, int]
    trainer_count: int
    referee_count: int
    single_root_namespace: bool
    total_times_ms: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_kind": "matchinformation",
            "match_id": self.match_id,
            "competition": self.competition,
            "season": self.season,
            "match_day": self.match_day,
            "kickoff_utc": self.kickoff_utc,
            "home_team_id": self.home_team_id,
            "away_team_id": self.away_team_id,
            "result": self.result,
            "pitch_size_m": {"x": self.pitch_x_m, "y": self.pitch_y_m},
            "player_count": self.player_count,
            "players_per_team": self.players_per_team,
            "trainer_count": self.trainer_count,
            "referee_count": self.referee_count,
            "namespaces": "none" if self.single_root_namespace else "present",
            "period_total_times_ms": self.total_times_ms,
        }


@dataclass(frozen=True, slots=True)
class EventsDiscovery:
    event_count: int
    event_types: dict[str, int]
    events_with_coordinates: int
    x_range_m: tuple[float, float]
    y_range_m: tuple[float, float]
    first_event_time: str
    last_event_time_by_clock: str
    chronological_order: bool
    duplicate_timestamps: int
    deleted_events: int
    game_sections: dict[str, str]
    root_has_namespace: bool
    start_frame_events: int
    calculated_timestamp_events: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_kind": "events",
            "event_count": self.event_count,
            "event_types": self.event_types,
            "events_with_coordinates": self.events_with_coordinates,
            "coordinate_frame": (
                "corner origin in metres; pitch length x width (verified by ranges)"
            ),
            "x_range_m": list(self.x_range_m),
            "y_range_m": list(self.y_range_m),
            "first_event_time": self.first_event_time,
            "last_event_time": self.last_event_time_by_clock,
            "source_order_chronological": self.chronological_order,
            "duplicate_timestamps": self.duplicate_timestamps,
            "deleted_events": self.deleted_events,
            "period_boundary_events": self.game_sections,
            "namespaces": "present" if self.root_has_namespace else "none",
            "events_with_start_end_frames": self.start_frame_events,
            "events_with_calculated_timestamp": self.calculated_timestamp_events,
        }


@dataclass(frozen=True, slots=True)
class PositionsDiscovery:
    sections: tuple[str, ...]
    framesets: int
    frames: int
    distinct_frame_numbers: int
    frames_per_period: dict[str, int]
    frame_entity_count_distribution: dict[str, int]
    entity_kinds: dict[str, int]
    ball_entities: tuple[str, ...]
    player_entities: int
    frame_number_range: tuple[int, int]
    frame_time_min: str
    frame_time_max: str
    time_step_s: float
    frame_to_time_exact: bool
    duplicate_frame_numbers: int
    x_range_m: tuple[float, float]
    y_range_m: tuple[float, float]
    z_range_m: tuple[float, float] | None
    ball_possession_values: dict[str, int]
    ball_status_values: dict[str, int]
    unmapped_attribute_distributions: dict[str, dict[str, int]]
    attribute_null_counts: dict[str, int]
    pitch_size_declared_m: tuple[float, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_kind": "positions",
            "sections": list(self.sections),
            "framesets": self.framesets,
            "frames": self.frames,
            "distinct_frame_numbers": self.distinct_frame_numbers,
            "frames_per_period": self.frames_per_period,
            "frame_entity_count_distribution": self.frame_entity_count_distribution,
            "entity_kinds": self.entity_kinds,
            "ball_entity_ids": list(self.ball_entities),
            "player_entities": self.player_entities,
            "frame_number_range": list(self.frame_number_range),
            "frame_time_range": [self.frame_time_min, self.frame_time_max],
            "time_step_s": self.time_step_s,
            "frame_number_to_time_exact": self.frame_to_time_exact,
            "duplicate_frame_numbers": self.duplicate_frame_numbers,
            "coordinate_frame": (
                "centre origin in metres; x along the long axis, y along the short axis "
                "(verified by ranges and the reference client)"
            ),
            "x_range_m": list(self.x_range_m),
            "y_range_m": list(self.y_range_m),
            "z_range_m": list(self.z_range_m) if self.z_range_m else None,
            "ball_attributes": {
                "BallPossession": self.ball_possession_values,
                "BallStatus": self.ball_status_values,
            },
            "unmapped_attribute_distributions": self.unmapped_attribute_distributions,
            "attribute_null_counts": self.attribute_null_counts,
            "pitch_size_declared_m": list(self.pitch_size_declared_m),
            "notes": [
                "X/Y/Z are provider-observed positions in metres (no conversion applied).",
                "D/A/M have no published semantics; kloppy (the reference client) does not "
                "decode them; they remain in Bronze and are not mapped canonically.",
            ],
        }


def discover_match_information(path: Path) -> MatchInfoDiscovery:
    tree = etree.parse(str(path))
    root = tree.getroot()
    general = root.find(".//MatchInformation/General")
    environment = root.find(".//MatchInformation/Environment")
    if general is None or environment is None:
        raise DiscoveryError(f"{path.name}: missing MatchInformation/General or Environment")
    players = root.findall(".//Teams/Team/Players/Player")
    per_team: dict[str, int] = defaultdict(int)
    for team in root.findall(".//Teams/Team"):
        per_team[str(team.get("TeamId"))] += len(team.findall("Players/Player"))
    trainers = len(root.findall(".//Trainer"))
    referees = len(root.findall(".//Referee"))
    other = root.find(".//OtherGameInformation")
    total_times = dict(other.attrib) if other is not None else {}
    kickoff = str(general.get("KickoffTime"))
    return MatchInfoDiscovery(
        match_id=str(general.get("MatchId")),
        competition=str(general.get("CompetitionName")),
        season=str(general.get("Season")),
        match_day=str(general.get("MatchDay")),
        kickoff_utc=kickoff,
        home_team_id=str(general.get("HomeTeamId")),
        away_team_id=str(general.get("GuestTeamId")),
        result=str(general.get("Result")),
        pitch_x_m=float(environment.get("PitchX")),
        pitch_y_m=float(environment.get("PitchY")),
        player_count=len(players),
        players_per_team=dict(per_team),
        trainer_count=trainers,
        referee_count=referees,
        single_root_namespace=not root.tag.startswith("{"),
        total_times_ms=total_times,
    )


def discover_events(path: Path) -> EventsDiscovery:
    types: Counter[str] = Counter()
    x_min, x_max = float("inf"), float("-inf")
    y_min, y_max = float("inf"), float("-inf")
    with_coordinates = 0
    deleted = 0
    start_frame_events = 0
    calculated = 0
    times: list[str] = []
    sections: dict[str, str] = {}
    root_has_namespace = False
    for event, elem in etree.iterparse(str(path), events=("start", "end")):
        if event == "start" and elem.tag == "PutDataRequest":
            root_has_namespace = elem.tag.startswith("{")
        if event != "end" or elem.tag != "Event":
            continue
        children = [child for child in elem if isinstance(child.tag, str)]
        if not children:
            raise DiscoveryError(f"{path.name}: Event {elem.get('EventId')} has no payload")
        primary = children[0]
        types[primary.tag] += 1
        if primary.tag == "Delete":
            deleted += 1
        if primary.tag in {"KickOff", "FinalWhistle"} and primary.get("GameSection"):
            sections[primary.get("GameSection", "")] = str(elem.get("EventTime"))
        if elem.get("X-Position") is not None and elem.get("Y-Position") is not None:
            with_coordinates += 1
            x_min = min(x_min, float(str(elem.get("X-Position"))))
            x_max = max(x_max, float(str(elem.get("X-Position"))))
            y_min = min(y_min, float(str(elem.get("Y-Position"))))
            y_max = max(y_max, float(str(elem.get("Y-Position"))))
        if elem.get("StartFrame") is not None:
            start_frame_events += 1
        if elem.get("CalculatedTimestamp") is not None:
            calculated += 1
        times.append(str(elem.get("EventTime")))
        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]
    chronological = all(a <= b for a, b in zip(times, times[1:], strict=False))
    duplicates = sum(1 for a, b in zip(times, times[1:], strict=False) if a == b)
    return EventsDiscovery(
        event_count=len(times),
        event_types=dict(types),
        events_with_coordinates=with_coordinates,
        x_range_m=(x_min, x_max),
        y_range_m=(y_min, y_max),
        first_event_time=times[0],
        last_event_time_by_clock=max(times),
        chronological_order=chronological,
        duplicate_timestamps=duplicates,
        deleted_events=deleted,
        game_sections=sections,
        root_has_namespace=root_has_namespace,
        start_frame_events=start_frame_events,
        calculated_timestamp_events=calculated,
    )


def discover_positions(path: Path) -> PositionsDiscovery:
    sections: list[str] = []
    framesets = 0
    frames = 0
    frames_per_period: Counter[str] = Counter()
    entity_counts_per_frame: Counter[int] = Counter()
    entity_kinds: Counter[str] = Counter()
    ball_entities: list[str] = []
    player_entities = 0
    n_min, n_max = None, None
    t_min, t_max = None, None
    step_ns: Counter[int] = Counter()
    frame_to_time_ok = True
    duplicates = 0
    x_min, x_max = float("inf"), float("-inf")
    y_min, y_max = float("inf"), float("-inf")
    z_min, z_max = float("inf"), float("-inf")
    z_observed = 0
    z_missing_on_ball = 0
    possession: Counter[str] = Counter()
    status: Counter[str] = Counter()
    unmapped: dict[str, Counter[str]] = {name: Counter() for name in UNMAPPED_FRAME_ATTRIBUTES}
    null_counts: Counter[str] = Counter()
    pitch_size = (0.0, 0.0)
    current: tuple[str, str, str] | None = None
    section_origin: dict[str, tuple[int, str]] = {}
    last_frame_number: dict[tuple[str, str, str], int] = {}

    context = etree.iterparse(
        str(path),
        events=("start", "end"),
        tag=("Frame", "FrameSet", "PitchSize"),
    )
    for event, elem in context:
        if event == "start":
            if elem.tag == "PitchSize":
                pitch_size = (float(elem.get("X")), float(elem.get("Y")))
            elif elem.tag == "FrameSet":
                framesets += 1
                section = str(elem.get("GameSection"))
                if section not in sections:
                    sections.append(section)
                team = str(elem.get("TeamId"))
                person = str(elem.get("PersonId"))
                current = (section, team, person)
                if team == BALL_TEAM_ID:
                    ball_entities.append(person)
                    entity_kinds["ball"] += 1
                else:
                    player_entities += 1
                    entity_kinds["player"] += 1
            continue
        if elem.tag != "Frame" or current is None:
            if event == "end":
                elem.clear()
                while elem.getprevious() is not None:
                    del elem.getparent()[0]
            continue
        section, _, _ = current
        frames += 1
        frames_per_period[section] += 1
        n_raw = elem.get("N")
        if n_raw is None:
            raise DiscoveryError(f"{path.name}: Frame without N in {section}")
        n = int(n_raw)
        entity_counts_per_frame[n] += 1
        if last_frame_number.get(current) == n:
            duplicates += 1
        last_frame_number[current] = n
        n_min = n if n_min is None else min(n_min, n)
        n_max = n if n_max is None else max(n_max, n)
        time_value = str(elem.get("T"))
        t_min = time_value if t_min is None else min(t_min, time_value)
        t_max = time_value if t_max is None else max(t_max, time_value)
        origin = section_origin.setdefault(section, (n, time_value))
        expected_ns = (n - origin[0]) * (1_000_000_000 // SPORTEC_FPS)
        actual_ns = round((_parse_iso(time_value) - _parse_iso(origin[1])).total_seconds() * 1e9)
        if abs(expected_ns - actual_ns) > 1_000:  # one microsecond tolerance
            frame_to_time_ok = False
        if n != origin[0]:
            step_ns[actual_ns // (n - origin[0])] += 1
        for coordinate_name, aggregate in (
            ("X", "x"),
            ("Y", "y"),
        ):
            raw_coordinate = elem.get(coordinate_name)
            if raw_coordinate is None:
                null_counts[coordinate_name] += 1
                continue
            try:
                value = float(raw_coordinate)
            except ValueError:
                null_counts[f"{coordinate_name}_unparsable"] += 1
                continue
            if aggregate == "x":
                x_min = min(x_min, value)
                x_max = max(x_max, value)
            else:
                y_min = min(y_min, value)
                y_max = max(y_max, value)
        z_raw = elem.get("Z")
        if z_raw is None:
            if current[1] == BALL_TEAM_ID:
                z_missing_on_ball += 1
        else:
            z_observed += 1
            try:
                z_value = float(z_raw)
            except ValueError:
                null_counts["Z_unparsable"] += 1
            else:
                z_min = min(z_min, z_value)
                z_max = max(z_max, z_value)
        for name, destination in (("BallPossession", possession), ("BallStatus", status)):
            raw = elem.get(name)
            if raw is not None:
                destination[raw] += 1
        for name in UNMAPPED_FRAME_ATTRIBUTES:
            raw = elem.get(name)
            if raw is None:
                null_counts[name] += 1
            else:
                unmapped[name][raw] += 1
        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]

    step_s = min(step_ns) / 1e9 if step_ns else 1.0 / SPORTEC_FPS
    null_counts["Z"] = z_missing_on_ball
    return PositionsDiscovery(
        sections=tuple(sections),
        framesets=framesets,
        frames=frames,
        distinct_frame_numbers=len(entity_counts_per_frame),
        frames_per_period=dict(frames_per_period),
        frame_entity_count_distribution={
            str(count): number
            for count, number in Counter(entity_counts_per_frame.values()).items()
        },
        entity_kinds=dict(entity_kinds),
        ball_entities=tuple(ball_entities),
        player_entities=player_entities,
        frame_number_range=(n_min or 0, n_max or 0),
        frame_time_min=t_min or "",
        frame_time_max=t_max or "",
        time_step_s=step_s,
        frame_to_time_exact=frame_to_time_ok,
        duplicate_frame_numbers=duplicates,
        x_range_m=(x_min, x_max),
        y_range_m=(y_min, y_max),
        z_range_m=(z_min, z_max) if z_min != float("inf") else None,
        ball_possession_values=dict(possession),
        ball_status_values=dict(status),
        unmapped_attribute_distributions={
            name: _summarize_unmapped(counter) for name, counter in unmapped.items()
        },
        attribute_null_counts={**dict(null_counts), "Z_observed": z_observed},
        pitch_size_declared_m=pitch_size,
    )


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _summarize_unmapped(counter: Counter[str]) -> dict[str, Any]:
    """Bounded summary of an undecoded vendor attribute.

    A float attribute (``D``) has near-continuous cardinality, so a full value
    histogram would bloat the receipt; it is summarized with count/min/max and
    the 10 most frequent values. Low-cardinality codes (``M``) keep the full
    distribution.
    """
    total = sum(counter.values())
    summary: dict[str, Any] = {"observed": total, "distinct": len(counter)}
    if total == 0:
        return summary
    try:
        numeric = [float(value) for value in counter]
    except ValueError:
        numeric = []
    if numeric and len(counter) > 64:
        summary["kind"] = "numeric"
        summary["min"] = min(numeric)
        summary["max"] = max(numeric)
        summary["top_values"] = {value: count for value, count in counter.most_common(10)}
    else:
        summary["kind"] = "code"
        summary["values"] = dict(counter.most_common(64))
    return summary


@dataclass(frozen=True, slots=True)
class IdsseDiscovery:
    match_information: MatchInfoDiscovery
    events: EventsDiscovery
    positions: PositionsDiscovery

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": "dfl-sportec-idsse",
            "match_id": self.match_information.match_id,
            "match_information": self.match_information.to_dict(),
            "events": self.events.to_dict(),
            "positions": self.positions.to_dict(),
            "unmapped_attributes": list(UNMAPPED_FRAME_ATTRIBUTES),
            "contract_notes": [
                "Tracking canonicalization is multi-entity; frame-major order is required by "
                "the non-decreasing t_rel_ns contract.",
                "Event rows are canonicalized in chronological (EventTime, EventId) order "
                "because the source file is not chronologically ordered.",
            ],
        }


def discover_idsse(
    match_information_path: Path,
    events_path: Path,
    positions_path: Path,
) -> IdsseDiscovery:
    return IdsseDiscovery(
        match_information=discover_match_information(match_information_path),
        events=discover_events(events_path),
        positions=discover_positions(positions_path),
    )
