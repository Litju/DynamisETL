"""SkillCorner Dynamic Events encoded in the V4 event envelope."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from dynamis.adapters.skillcorner_basketball import authorities
from dynamis.contracts.sports import (
    EventAttributeSchema,
    EventAttributeType,
    EventEnvelope,
    SportsEntityKind,
    canonical_sports_id,
    event_envelope_table,
)

ATTRIBUTE_SCHEMA_ID = "skillcorner-basketball.dynamic-event"
ATTRIBUTE_SCHEMA_VERSION = "1"
ATTRIBUTE_SCHEMA = EventAttributeSchema(
    schema_id=ATTRIBUTE_SCHEMA_ID,
    version=ATTRIBUTE_SCHEMA_VERSION,
    properties={
        "source": EventAttributeType.OBJECT,
        "location_source_field": EventAttributeType.STRING,
    },
    additional_properties=True,
)


def _first(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record and record[key] is not None:
            return record[key]
    return None


def _numeric(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _location(record: dict[str, Any]) -> tuple[dict[str, float] | None, str | None]:
    for key in ("location", "loc", "startLoc", "startLocation"):
        value = record.get(key)
        if isinstance(value, dict):
            if isinstance(value.get("xyz"), list):
                value = value["xyz"]
            else:
                x = _numeric(value.get("x"))
                y = _numeric(value.get("y"))
                z = _numeric(value.get("z"))
                if x is not None and y is not None:
                    return ({"x": x, "y": y, **({"z": z} if z is not None else {})}, key)
                continue
        if isinstance(value, list) and len(value) >= 2:
            x = _numeric(value[0])
            y = _numeric(value[1])
            z = _numeric(value[2]) if len(value) > 2 else None
            if x is not None and y is not None:
                return ({"x": x, "y": y, **({"z": z} if z is not None else {})}, key)
    return None, None


def build_event_table(
    *,
    path: Path,
    frame_clock_path: Path,
    game_id: str,
    provider_team_ids: dict[str, str],
    source_revision: str,
    player_aliases: dict[str, str] | None = None,
) -> tuple[pa.Table, dict[str, Any]]:
    """Link events only on exact source frame or clock keys, retaining every disposition."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    source_records: list[dict[str, Any]] = []
    family_counts: Counter[str] = Counter()
    for family in sorted(payload):
        records = payload[family]
        if not isinstance(records, list):
            continue
        for family_index, record in enumerate(records):
            if not isinstance(record, dict):
                raise ValueError(f"Dynamic Events {family}[{family_index}] is not an object")
            source_event_id = _first(record, "id", "eventId", "event_id")
            period = _first(record, "period", "periodNumber")
            if source_event_id is None or period is None:
                raise ValueError(f"Dynamic Events {family}[{family_index}] lacks id or period")
            source_frame = _first(
                record, "frameIdx", "frame", "startFrame", "start_frame", "endFrame", "end_frame"
            )
            wall_clock = _first(record, "wallClock", "wall_clock", "startWallClock", "endWallClock")
            game_clock = _first(record, "gameClock", "game_clock", "startGameClock", "endGameClock")
            shot_clock = _first(record, "shotClock", "shot_clock", "startShotClock", "endShotClock")
            source_records.append(
                {
                    "family": family,
                    "family_index": family_index,
                    "sequence_index": f"{family}:{family_index:07d}",
                    "source_event_id": str(source_event_id),
                    "period_number": int(period),
                    "source_frame_idx": int(source_frame) if source_frame is not None else None,
                    "wall_clock_ms": int(wall_clock) if wall_clock is not None else None,
                    "game_clock_s": _numeric(game_clock),
                    "shot_clock_s": _numeric(shot_clock),
                    "payload_json": json.dumps(
                        record, sort_keys=True, separators=(",", ":"), allow_nan=False
                    ),
                }
            )
            family_counts[family] += 1

    frame_rows = pq.read_table(
        frame_clock_path,
        columns=[
            "frame_idx",
            "period_number",
            "wall_clock_ms",
            "canonical_time_ns",
            "game_clock_s",
            "shot_clock_s",
        ],
    ).to_pylist()
    frames_by_idx: dict[tuple[int, int], dict[str, Any]] = {}
    frames_by_wall: dict[tuple[int, int], dict[str, Any]] = {}
    frames_by_game_clock: dict[tuple[int, float], list[dict[str, Any]]] = defaultdict(list)
    for frame in frame_rows:
        period = int(frame["period_number"])
        frame_idx = int(frame["frame_idx"])
        wall_clock = int(frame["wall_clock_ms"])
        if (period, frame_idx) in frames_by_idx or (period, wall_clock) in frames_by_wall:
            raise ValueError(
                "frame-clock artifact contains duplicate exact frame or wall-clock keys"
            )
        frames_by_idx[(period, frame_idx)] = frame
        frames_by_wall[(period, wall_clock)] = frame
        if frame["game_clock_s"] is not None:
            frames_by_game_clock[(period, float(frame["game_clock_s"]))].append(frame)

    contest = canonical_sports_id(authorities.NAMESPACE, SportsEntityKind.CONTEST, game_id)
    player_aliases = player_aliases or {}
    events: list[EventEnvelope] = []
    linked = 0
    link_methods: Counter[str] = Counter()
    linked_by_family: Counter[str] = Counter()
    dispositions: Counter[str] = Counter()
    family_dispositions: dict[str, Counter[str]] = defaultdict(Counter)
    unlinked_reasons: Counter[str] = Counter()
    family_unlinked_reasons: dict[str, Counter[str]] = defaultdict(Counter)
    for row in sorted(
        source_records, key=lambda item: (item["period_number"], item["sequence_index"])
    ):
        raw = json.loads(row["payload_json"])
        location, location_field = _location(raw)
        period = int(row["period_number"])
        frame_match = (
            frames_by_idx.get((period, int(row["source_frame_idx"])))
            if row["source_frame_idx"] is not None
            else None
        )
        wall_match = (
            frames_by_wall.get((period, int(row["wall_clock_ms"])))
            if row["wall_clock_ms"] is not None
            else None
        )
        linked_frame: dict[str, Any] | None = None
        method: str | None = None
        reason: str | None = None
        if (
            frame_match is not None
            and wall_match is not None
            and frame_match["frame_idx"] != wall_match["frame_idx"]
        ):
            reason = "conflicting_exact_frame_and_wall_clock_keys"
        elif frame_match is not None:
            linked_frame = frame_match
            method = "frameIdx"
        elif wall_match is not None:
            linked_frame = wall_match
            method = "wallClock"
        elif row["game_clock_s"] is not None:
            candidates = frames_by_game_clock.get((period, float(row["game_clock_s"])), [])
            if row["shot_clock_s"] is not None:
                candidates = [
                    frame
                    for frame in candidates
                    if frame["shot_clock_s"] is not None
                    and float(frame["shot_clock_s"]) == float(row["shot_clock_s"])
                ]
            if len(candidates) == 1:
                linked_frame = candidates[0]
                method = "gameClock"
            elif len(candidates) > 1:
                reason = "ambiguous_period_game_clock_key"

        if linked_frame is not None:
            assert method is not None
            linked += 1
            disposition = "exact_frame" if method == "frameIdx" else "authoritative_time_clock"
            link_methods[method] += 1
            linked_by_family[str(row["family"])] += 1
        else:
            disposition = "legitimately_unlinked"
            reason = reason or (
                "no_temporal_key_on_relationship_record"
                if row["family"] == "chance_players"
                and all(
                    row[key] is None
                    for key in ("source_frame_idx", "wall_clock_ms", "game_clock_s")
                )
                else "provider_temporal_keys_missing"
                if all(
                    row[key] is None
                    for key in ("source_frame_idx", "wall_clock_ms", "game_clock_s")
                )
                else "no_exact_tracking_key"
            )
            unlinked_reasons[reason] += 1
            family_unlinked_reasons[str(row["family"])][reason] += 1
        dispositions[disposition] += 1
        family_dispositions[str(row["family"])][disposition] += 1
        linked_frame_idx = linked_frame["frame_idx"] if linked_frame is not None else None
        linked_time_ns = linked_frame["canonical_time_ns"] if linked_frame is not None else None
        team_value = _first(raw, "teamId", "team_id")
        team_id = provider_team_ids.get(str(team_value)) if team_value is not None else None
        subject_value = _first(
            raw,
            "playerId",
            "player_id",
            "shooterId",
            "handlerId",
            "actorId",
            "screenerId",
        )
        subject_id = (
            canonical_sports_id(
                authorities.NAMESPACE,
                SportsEntityKind.SUBJECT,
                player_aliases.get(str(subject_value), str(subject_value)),
            )
            if subject_value is not None
            else None
        )
        source_clock = {
            "period": period,
            "source_frame_idx": row["source_frame_idx"],
            "source_wall_clock_ms": row["wall_clock_ms"],
            "game_clock_s": row["game_clock_s"],
            "shot_clock_s": row["shot_clock_s"],
            "linked_frame_idx": linked_frame_idx,
            "linked_wall_clock_ms": (
                linked_frame["wall_clock_ms"] if linked_frame is not None else None
            ),
            "link_method": method,
            "linkage_disposition": disposition,
            "unlinked_reason": reason,
        }
        attributes = {
            "source": raw,
            "source_revision": source_revision,
            **({"location_source_field": location_field} if location_field else {}),
        }
        events.append(
            EventEnvelope(
                contest_id=contest,
                contest_period_id=f"{contest}:period:{period}",
                sequence_index=str(row["sequence_index"]),
                source_event_id=str(row["source_event_id"]),
                provider_namespace=authorities.NAMESPACE,
                provider_event_type=str(row["family"]),
                canonical_time_ns=int(linked_time_ns) if linked_time_ns is not None else None,
                source_clock_json=source_clock,
                team_id=team_id,
                subject_id=subject_id,
                location=location,
                spatial_reference_id=authorities.COURT_REFERENCE_ID if location else None,
                attributes_json=attributes,
                attributes_schema_id=ATTRIBUTE_SCHEMA_ID,
                attributes_schema_version=ATTRIBUTE_SCHEMA_VERSION,
            )
        )
    table = event_envelope_table(
        events, {(ATTRIBUTE_SCHEMA_ID, ATTRIBUTE_SCHEMA_VERSION): ATTRIBUTE_SCHEMA}
    )
    return table, {
        "source_records": len(source_records),
        "canonical_rows": table.num_rows,
        "linked_events": linked,
        "unlinked_events": len(source_records) - linked,
        "link_methods": dict(sorted(link_methods.items())),
        "linked_by_family": dict(sorted(linked_by_family.items())),
        "family_counts": dict(sorted(family_counts.items())),
        "linkage_reconciliation": {
            "total_events": len(source_records),
            "exact_frame": dispositions["exact_frame"],
            "authoritative_time_clock": dispositions["authoritative_time_clock"],
            "legitimately_unlinked": dispositions["legitimately_unlinked"],
            "unlinked_reasons": dict(sorted(unlinked_reasons.items())),
            "by_family": {
                family: {
                    "total_events": family_counts[family],
                    "exact_frame": family_dispositions[family]["exact_frame"],
                    "authoritative_time_clock": family_dispositions[family][
                        "authoritative_time_clock"
                    ],
                    "legitimately_unlinked": family_dispositions[family]["legitimately_unlinked"],
                    "unlinked_reasons": dict(sorted(family_unlinked_reasons[family].items())),
                }
                for family in sorted(family_counts)
            },
        },
        "attribute_schema": f"{ATTRIBUTE_SCHEMA_ID}@{ATTRIBUTE_SCHEMA_VERSION}",
        "event_envelope_schema": "cross_sport_event_envelope@1",
    }


__all__ = ["ATTRIBUTE_SCHEMA_ID", "ATTRIBUTE_SCHEMA_VERSION", "build_event_table"]
