"""Event XML parsing and canonicalization for DFL/Sportec IDSSE.

Verified structure (discovery receipt): ``PutDataRequest > Event*`` where each
event holds exactly one primary payload element (``Play``, ``TacklingGame``,
``ShotAtGoal``, ...) that may nest a more specific child (``Play > Pass``,
``ShotAtGoal > SavedShot``). ``Delete`` events are provider retractions and are
excluded explicitly, never silently.

Two provider realities shape the canonical output:

* the source file is **not** chronologically ordered, so canonical rows are
  sorted by ``(EventTime, EventId)`` - deterministic and time-ordered;
* event positions use the provider's bottom-left origin, so they are resolved
  into the declared pitch-centred frame through the declared frame transform.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import lxml.etree as etree
import pyarrow as pa

from dynamis.adapters.sportec_idsse.matchinfo import IdsseMatchMetadata
from dynamis.contracts import EVENT_SCHEMA, FrameTransform, MeasurementClass, Modality
from dynamis.contracts.frames import transform_points
from dynamis.pipeline.quarantine import (
    RULE_COORDINATE_OUT_OF_RANGE,
    RULE_NON_FINITE_VALUE,
    RULE_REQUIRED_FIELD_NULL,
    RULE_SCHEMA_FAILURE,
    RULE_TIMESTAMP_UNPARSABLE,
    QuarantinedRecord,
)
from dynamis.pipeline.streams import DEFAULT_BATCH_SIZE, CanonicalStream

DELETE_EVENT = "Delete"
PERIOD_FOR_SECTION = {"firstHalf": "period-1", "secondHalf": "period-2"}

#: Explicit actor mapping: canonical ``provider_player_id`` per primary element.
#: Types without an entry fall back to the generic ``Player`` attribute, which
#: the chain flattening resolves from the nested specialization (for example
#: ``KickOff > Play > Pass`` carries the player on ``Play``).
PRIMARY_PLAYER_ATTRIBUTE = {
    "Play": "Player",
    "OtherBallAction": "Player",
    "ShotAtGoal": "Player",
    "BlockedShot": "Player",
    "SavedShot": "GoalKeeper",
    "Caution": "Player",
    "TacklingGame": "Winner",
    "Foul": "Fouler",
    "BallClaiming": "Player",
    "Substitution": "PlayerIn",
}

#: Explicit team mapping: canonical ``provider_team_id`` per primary element;
#: the generic ``Team`` fallback resolves from the nested chain like the actor map.
PRIMARY_TEAM_ATTRIBUTE = {
    "Play": "Team",
    "OtherBallAction": "Team",
    "ThrowIn": "Team",
    "FreeKick": "Team",
    "GoalKick": "Team",
    "CornerKick": "Team",
    "ShotAtGoal": "Team",
    "Caution": "Team",
    "BallClaiming": "Team",
    "Substitution": "Team",
    "Foul": "TeamFouler",
    "TacklingGame": "WinnerTeam",
}

#: Provider shot-type vocabulary with an explicit body-part interpretation.
BODY_PART_MAP = {"leftLeg": "left_leg", "rightLeg": "right_leg", "head": "head"}


@dataclass(frozen=True, slots=True)
class RawEvent:
    """One parsed event element held between the boundary and row passes.

    ``chain_attributes`` merges the attributes of the primary element and every
    nested specialization (e.g. ``KickOff > Play > Pass``), outermost first, so
    an inner element wins a name collision. That mirrors how the reference
    client flattens the event chain before reading ``Team``/``Player``.
    """

    event_id: str
    parsed_time: datetime
    primary_tag: str
    chain_attributes: dict[str, str]
    event_attributes: dict[str, str]
    deepest_tag: str | None
    x_raw: str | None
    y_raw: str | None


@dataclass(frozen=True, slots=True)
class PeriodBoundary:
    period_id: str
    section: str
    started_at: datetime
    ended_at: datetime
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_id": self.period_id,
            "section": self.section,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "source": self.source,
        }


@dataclass(slots=True)
class EventsSummary:
    source_events: int = 0
    deleted_events: int = 0
    canonical_rows: int = 0
    event_types: Counter[str] = field(default_factory=Counter)
    events_with_coordinates: int = 0
    events_reordered: int = 0
    duplicate_timestamps: int = 0
    source_time_min: str | None = None
    source_time_max: str | None = None
    t_rel_min_ns: int | None = None
    t_rel_max_ns: int | None = None
    periods: tuple[PeriodBoundary, ...] = ()
    quarantined: list[QuarantinedRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_events": self.source_events,
            "deleted_events": self.deleted_events,
            "canonical_rows": self.canonical_rows,
            "event_types": dict(sorted(self.event_types.items())),
            "events_with_coordinates": self.events_with_coordinates,
            "events_reordered": self.events_reordered,
            "duplicate_timestamps": self.duplicate_timestamps,
            "source_time_min": self.source_time_min,
            "source_time_max": self.source_time_max,
            "t_rel_min_ns": self.t_rel_min_ns,
            "t_rel_max_ns": self.t_rel_max_ns,
            "periods": [period.to_dict() for period in self.periods],
            "quarantined_rows": len(self.quarantined),
        }


def snake_case(tag: str) -> str:
    out: list[str] = []
    for index, character in enumerate(tag):
        if character.isupper() and index and not tag[index - 1].isupper():
            out.append("_")
        out.append(character.lower())
    return "".join(out)


def deepest_child(element: etree._Element) -> etree._Element:
    current = element
    while len(current) and isinstance(current[0].tag, str):
        current = current[0]
    return current


def _parse_event_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def derive_periods(
    boundaries: dict[str, dict[str, datetime]], metadata: IdsseMatchMetadata
) -> tuple[PeriodBoundary, ...]:
    """Periods from the provider's KickOff/FinalWhistle events, with a declared fallback."""
    periods: list[PeriodBoundary] = []
    for section, period_id in PERIOD_FOR_SECTION.items():
        boundary = boundaries.get(section, {})
        start = boundary.get("start")
        end = boundary.get("end")
        if start is not None and end is not None:
            periods.append(
                PeriodBoundary(
                    period_id=period_id,
                    section=section,
                    started_at=start,
                    ended_at=end,
                    source="provider kick-off/final-whistle events",
                )
            )
            continue
        totals = metadata.period_total_times_ms
        key = "TotalTimeFirstHalf" if section == "firstHalf" else "TotalTimeSecondHalf"
        if key in totals and start is None and end is None:
            start = metadata.kickoff_utc
            end = start + timedelta(milliseconds=totals[key])
            periods.append(
                PeriodBoundary(
                    period_id=period_id,
                    section=section,
                    started_at=start,
                    ended_at=end,
                    source=f"match-information {key} fallback (no boundary events)",
                )
            )
    return tuple(periods)


class EventsCanonicalizer:
    """Parses the (small) events XML into chronologically ordered canonical rows."""

    def __init__(
        self,
        events_path: Path,
        metadata: IdsseMatchMetadata,
        *,
        transform: FrameTransform,
        dataset_id: str,
        session_id: str,
        clock_id: str,
        synchronization_spec_id: str,
        coordinate_frame_id: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._path = Path(events_path)
        self._metadata = metadata
        self._transform = transform
        self._dataset_id = dataset_id
        self._session_id = session_id
        self._clock_id = clock_id
        self._synchronization_spec_id = synchronization_spec_id
        self._coordinate_frame_id = coordinate_frame_id
        self._batch_size = batch_size
        self._rows: list[dict[str, Any]] = []
        self._summary = EventsSummary()

    @property
    def summary(self) -> EventsSummary:
        return self._summary

    def parse(self) -> None:
        if self._summary.source_events:
            return
        kickoff_ns = int(self._metadata.kickoff_utc.timestamp() * 1_000_000_000)
        raw: list[RawEvent] = []
        boundaries: dict[str, dict[str, datetime]] = defaultdict(dict)
        source_order_times: list[str] = []

        for _event, elem in etree.iterparse(str(self._path), events=("end",), tag=("Event",)):
            self._summary.source_events += 1
            event_time_raw = elem.get("EventTime")
            event_id = elem.get("EventId")
            if event_time_raw is None or event_id is None:
                self._summary.quarantined.append(
                    QuarantinedRecord(
                        rule=RULE_REQUIRED_FIELD_NULL,
                        detail="Event is missing EventId or EventTime",
                        dataset_id=self._dataset_id,
                        session_id=self._session_id,
                        stream_id="events",
                        source_record_id=str(event_id),
                        evidence={
                            "event_id": event_id,
                            "event_time": event_time_raw,
                        },
                    )
                )
                elem.clear()
                while elem.getprevious() is not None:
                    del elem.getparent()[0]
                continue
            parsed_time = _parse_event_time(event_time_raw)
            if parsed_time is None:
                self._summary.quarantined.append(
                    QuarantinedRecord(
                        rule=RULE_TIMESTAMP_UNPARSABLE,
                        detail="EventTime is not a timezone-aware ISO 8601 timestamp",
                        dataset_id=self._dataset_id,
                        session_id=self._session_id,
                        stream_id="events",
                        source_record_id=event_id,
                        source_time=event_time_raw,
                        evidence={"event_time": event_time_raw},
                    )
                )
                elem.clear()
                while elem.getprevious() is not None:
                    del elem.getparent()[0]
                continue
            source_order_times.append(event_time_raw)
            primary = elem[0] if len(elem) else None
            if primary is None or not isinstance(primary.tag, str):
                self._summary.quarantined.append(
                    QuarantinedRecord(
                        rule=RULE_SCHEMA_FAILURE,
                        detail="Event has no primary payload element",
                        dataset_id=self._dataset_id,
                        session_id=self._session_id,
                        stream_id="events",
                        source_record_id=event_id,
                        source_time=event_time_raw,
                        evidence={"event_id": event_id},
                    )
                )
                elem.clear()
                while elem.getprevious() is not None:
                    del elem.getparent()[0]
                continue
            if primary.tag == DELETE_EVENT:
                self._summary.deleted_events += 1
                elem.clear()
                while elem.getprevious() is not None:
                    del elem.getparent()[0]
                continue
            section = primary.get("GameSection")
            if primary.tag == "KickOff" and section:
                boundaries[section]["start"] = parsed_time
            elif primary.tag == "FinalWhistle" and section:
                boundaries[section]["end"] = parsed_time
            deepest = deepest_child(primary)
            chain_attributes: dict[str, str] = {}
            for element in primary.iter():
                if isinstance(element.tag, str):
                    chain_attributes.update(element.attrib)
            raw.append(
                RawEvent(
                    event_id=event_id,
                    parsed_time=parsed_time,
                    primary_tag=str(primary.tag),
                    chain_attributes=chain_attributes,
                    event_attributes=dict(elem.attrib),
                    deepest_tag=str(deepest.tag) if deepest is not primary else None,
                    x_raw=elem.get("X-Position"),
                    y_raw=elem.get("Y-Position"),
                )
            )
            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]

        self._summary.periods = derive_periods(dict(boundaries), self._metadata)
        self._summary.duplicate_timestamps = sum(
            1 for a, b in zip(source_order_times, source_order_times[1:], strict=False) if a == b
        )
        source_order_ns = [int(event.parsed_time.timestamp() * 1_000_000_000) for event in raw]
        self._summary.events_reordered = sum(
            1 for a, b in zip(source_order_ns, source_order_ns[1:], strict=False) if b < a
        )
        raw.sort(key=lambda event: (event.parsed_time, event.event_id))
        for event in raw:
            row = self._canonical_row(event, kickoff_ns)
            if row is not None:
                self._rows.append(row)

    def _canonical_row(self, event: RawEvent, kickoff_ns: int) -> dict[str, Any] | None:
        primary_tag = event.primary_tag
        event_id = event.event_id
        parsed_time = event.parsed_time
        event_type = snake_case(primary_tag)
        subtype = event.deepest_tag
        player_attribute = PRIMARY_PLAYER_ATTRIBUTE.get(primary_tag, "Player")
        team_attribute = PRIMARY_TEAM_ATTRIBUTE.get(primary_tag, "Team")
        # Keep every provider attribute for anti-corruption-layer fidelity except
        # the ones already mapped to canonical identity/time/location columns.
        context = {
            key: value
            for key, value in {**event.event_attributes, **event.chain_attributes}.items()
            if key
            not in {
                "EventId",
                "EventTime",
                "MatchId",
                "GameSection",
                "X-Position",
                "Y-Position",
            }
        }

        x_m: float | None = None
        y_m: float | None = None
        x_raw = event.x_raw
        y_raw = event.y_raw
        if x_raw is not None and y_raw is not None:
            try:
                x_value, y_value = float(x_raw), float(y_raw)
            except ValueError:
                self._summary.quarantined.append(
                    QuarantinedRecord(
                        rule=RULE_COORDINATE_OUT_OF_RANGE,
                        detail="event position is not numeric",
                        dataset_id=self._dataset_id,
                        session_id=self._session_id,
                        stream_id="events",
                        source_record_id=event_id,
                        source_time=parsed_time.isoformat(),
                        evidence={"X-Position": x_raw, "Y-Position": y_raw},
                    )
                )
                return None
            if not (math.isfinite(x_value) and math.isfinite(y_value)):
                self._summary.quarantined.append(
                    QuarantinedRecord(
                        rule=RULE_NON_FINITE_VALUE,
                        detail="event position is not a finite number",
                        dataset_id=self._dataset_id,
                        session_id=self._session_id,
                        stream_id="events",
                        source_record_id=event_id,
                        source_time=parsed_time.isoformat(),
                        evidence={"X-Position": x_raw, "Y-Position": y_raw},
                    )
                )
                return None
            ((x_center, y_center, _),) = transform_points(
                self._transform, ((x_value, y_value, 0.0),)
            )
            x_m, y_m = x_center, y_center
        event_ns = int(parsed_time.timestamp() * 1_000_000_000)
        t_rel_ns = event_ns - kickoff_ns
        period_id = None
        for period in self._summary.periods:
            if period.started_at <= parsed_time <= period.ended_at:
                period_id = period.period_id
                break
        self._summary.event_types[event_type] += 1
        if x_m is not None:
            self._summary.events_with_coordinates += 1
        if self._summary.source_time_min is None or parsed_time < datetime.fromisoformat(
            self._summary.source_time_min
        ):
            self._summary.source_time_min = parsed_time.isoformat()
        if self._summary.source_time_max is None or parsed_time > datetime.fromisoformat(
            self._summary.source_time_max
        ):
            self._summary.source_time_max = parsed_time.isoformat()
        self._summary.t_rel_min_ns = (
            t_rel_ns
            if self._summary.t_rel_min_ns is None
            else min(self._summary.t_rel_min_ns, t_rel_ns)
        )
        self._summary.t_rel_max_ns = (
            t_rel_ns
            if self._summary.t_rel_max_ns is None
            else max(self._summary.t_rel_max_ns, t_rel_ns)
        )
        self._summary.canonical_rows += 1
        return {
            "dataset_id": self._dataset_id,
            "session_id": self._session_id,
            "trial_id": period_id,
            "subject_id": None,
            "device_id": None,
            "stream_id": "events",
            "sample_index": -1,
            "t_rel_ns": t_rel_ns,
            "timestamp_utc_ns": event_ns,
            "nominal_sampling_rate_hz": None,
            "measurement_class": MeasurementClass.SOURCE_DERIVED.value,
            "clock_id": self._clock_id,
            "synchronization_spec_id": self._synchronization_spec_id,
            "coordinate_frame_id": self._coordinate_frame_id,
            "event_id": event_id,
            "event_type": event_type,
            "event_subtype": None if subtype is None else snake_case(subtype),
            "provider_team_id": (
                None if team_attribute is None else event.chain_attributes.get(team_attribute)
            ),
            "provider_player_id": (
                None if player_attribute is None else event.chain_attributes.get(player_attribute)
            ),
            "x_m": x_m,
            "y_m": y_m,
            "body_part": BODY_PART_MAP.get(event.chain_attributes.get("TypeOfShot") or ""),
            "outcome": event.chain_attributes.get("Evaluation"),
            "provider_context_json": json.dumps(context, sort_keys=True, separators=(",", ":")),
        }

    def stream(self) -> CanonicalStream:
        self.parse()
        return CanonicalStream(
            dataset_id=self._dataset_id,
            session_id=self._session_id,
            stream_id="events",
            modality=Modality.EVENT,
            measurement_class=MeasurementClass.SOURCE_DERIVED,
            clock_id=self._clock_id,
            synchronization_spec_id=self._synchronization_spec_id,
            coordinate_frame_id=self._coordinate_frame_id,
            nominal_sampling_rate_hz=None,
            stream_metadata={
                "adapter": "sportec_idsse",
                "source_file_key": self._path.name,
                "ordering": "chronological (EventTime, EventId)",
                "excluded": "Delete retraction events",
            },
            schema=EVENT_SCHEMA,
            batches=self._batches(),
        )

    def _batches(self) -> Iterator[pa.RecordBatch]:
        rows = self._rows
        for start in range(0, len(rows), self._batch_size):
            chunk = rows[start : start + self._batch_size]
            for offset, row in enumerate(chunk):
                row["sample_index"] = start + offset
            yield pa.RecordBatch.from_pylist(chunk, schema=EVENT_SCHEMA)
