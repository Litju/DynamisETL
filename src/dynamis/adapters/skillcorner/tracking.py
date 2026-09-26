"""SkillCorner 10 Hz tracking JSONL -> canonical ``tracking_sample`` streams.

The provider distributes one frame per line; this module streams the file once
per declared period and emits bounded Arrow batches. Every player-frame is an
observation; the ball is either present with a finite X/Y pair or is an explicit
non-observation (no coordinates at all, recorded as ignored) or a quarantined
record (partial/non-finite coordinates). Provider truth is preserved: no
smoothing, no interpolation, no invented velocity or acceleration.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa

from dynamis.adapters.skillcorner.authorities import (
    CLOCK_ID,
    HYBRID_GEOMETRY_STATEMENT,
    SKILLCORNER_DATASET_ID,
    SYNC_SPEC_ID,
    TRACKING_FRAME_ID,
    TRACKING_FRAME_RATE_HZ,
    tracking_stream_id,
)
from dynamis.adapters.skillcorner.metadata import (
    MatchPeriod,
    SkillCornerMatchMetadata,
)
from dynamis.contracts import MeasurementClass, Modality, get_schema
from dynamis.contracts.sports import (
    DataGrain,
    DataGrainKind,
    SportsEntityKind,
    canonical_sports_id,
)
from dynamis.pipeline.quarantine import (
    RULE_COORDINATE_MISSING,
    RULE_DUPLICATE_FRAME,
    RULE_NON_FINITE_VALUE,
    RULE_TIMESTAMP_UNPARSABLE,
    RULE_UNKNOWN_PARTICIPANT,
    QuarantinedRecord,
)
from dynamis.pipeline.streams import DEFAULT_BATCH_SIZE, CanonicalStream


def match_time_ns(text: object) -> int:
    """Parse the provider's ``HH:MM:SS.cc`` match timestamp into nanoseconds.

    The provider timestamp is the clock authority (period 2 continues from
    45:00:00); this function only re-expresses it exactly in SI time, it never
    derives time from host clocks.
    """
    if not isinstance(text, str):
        raise ValueError(f"timestamp is not text: {text!r}")
    parts = text.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"timestamp {text!r} is not HH:MM:SS.cc")
    hours_text, minutes_text, seconds_text = parts
    seconds_part, dot, centiseconds_text = seconds_text.partition(".")
    if dot != "." or len(centiseconds_text) != 2 or not centiseconds_text.isdigit():
        raise ValueError(f"timestamp {text!r} does not carry centisecond precision")
    if not (hours_text.isdigit() and minutes_text.isdigit() and seconds_part.isdigit()):
        raise ValueError(f"timestamp {text!r} is not HH:MM:SS.cc")
    hours = int(hours_text)
    minutes = int(minutes_text)
    seconds = int(seconds_part)
    centiseconds = int(centiseconds_text)
    if not 0 <= minutes < 60 or not 0 <= seconds < 60 or not 0 <= centiseconds < 100:
        raise ValueError(f"timestamp {text!r} has out-of-range components")
    return ((hours * 60 + minutes) * 60 + seconds) * 1_000_000_000 + centiseconds * 10_000_000


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _as_float(value: object) -> float:
    """Finite float value, or a hard error; no silent coercion of anything else."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        result = float(value)
        if math.isfinite(result):
            return result
    raise ValueError(f"value is not a finite number: {value!r}")


@dataclass(slots=True)
class TrackingPeriodSummary:
    period: int
    stream_id: str
    source_frames: int = 0
    source_player_entries: int = 0
    source_ball_entries: int = 0
    canonical_rows: int = 0
    quarantined: list[QuarantinedRecord] = field(default_factory=list)
    ignored_ball_without_coordinates: int = 0
    duplicate_frames: int = 0
    detected_true: int = 0
    detected_false: int = 0
    detected_null: int = 0
    null_counts: Counter[str] = field(default_factory=Counter)
    seen_player_ids: set[str] = field(default_factory=set)
    unknown_player_ids: set[str] = field(default_factory=set)
    first_t_rel_ns: int | None = None
    last_t_rel_ns: int | None = None

    @property
    def source_records(self) -> int:
        return self.source_player_entries + self.source_ball_entries

    @property
    def quarantined_rows(self) -> int:
        return len(self.quarantined)

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "stream_id": self.stream_id,
            "source_frames": self.source_frames,
            "source_player_entries": self.source_player_entries,
            "source_ball_entries": self.source_ball_entries,
            "canonical_rows": self.canonical_rows,
            "quarantined_rows": self.quarantined_rows,
            "ignored_ball_without_coordinates": self.ignored_ball_without_coordinates,
            "duplicate_frames": self.duplicate_frames,
            "detected_true": self.detected_true,
            "detected_false": self.detected_false,
            "detected_null": self.detected_null,
            "observed_player_ids": len(self.seen_player_ids),
            "unknown_player_ids": sorted(self.unknown_player_ids)[:100],
            "unknown_player_id_count": len(self.unknown_player_ids),
            "first_t_rel_ns": self.first_t_rel_ns,
            "last_t_rel_ns": self.last_t_rel_ns,
        }


class TrackingCanonicalizer:
    """Streams one SkillCorner tracking file into per-period canonical streams."""

    def __init__(
        self,
        path: Path,
        metadata: SkillCornerMatchMetadata,
        *,
        dataset_id: str = SKILLCORNER_DATASET_ID,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._path = Path(path)
        self._metadata = metadata
        self._dataset_id = dataset_id
        self._batch_size = batch_size
        self._summaries: dict[int, TrackingPeriodSummary] = {}
        self._schema = get_schema(Modality.TRACKING)

    def summary(self, period: int) -> TrackingPeriodSummary:
        return self._summaries[period]

    def streams(self) -> tuple[CanonicalStream, ...]:
        return tuple(self.stream(period.period) for period in self._metadata.periods)

    def stream(self, period: int) -> CanonicalStream:
        period_record = self._metadata.period(period)
        if period_record is None:
            raise KeyError(f"match {self._metadata.match_id} declares no period {period}")
        summary = TrackingPeriodSummary(period=period, stream_id=tracking_stream_id(period))
        self._summaries[period] = summary
        return CanonicalStream(
            dataset_id=self._dataset_id,
            session_id=self._metadata.session_id,
            stream_id=summary.stream_id,
            modality=Modality.TRACKING,
            measurement_class=MeasurementClass.MODEL_ESTIMATED,
            clock_id=CLOCK_ID,
            synchronization_spec_id=SYNC_SPEC_ID,
            trial_id=period_record.name,
            coordinate_frame_id=TRACKING_FRAME_ID,
            nominal_sampling_rate_hz=TRACKING_FRAME_RATE_HZ,
            source_unit="m",
            batches=self._batches(period_record, summary),
            schema=self._schema,
            stream_metadata={
                "adapter": "skillcorner_opendata",
                "contest_id": canonical_sports_id(
                    "skillcorner_opendata", SportsEntityKind.CONTEST, self._metadata.match_id
                ),
                "source_file_key": self._path.name,
                "provider_product": "broadcast tracking (computer-vision, extrapolated)",
                "provider_is_detected_semantics": (
                    "true = detected on screen; false = provider extrapolation"
                ),
                "geometry": "pitch-centred X/Y metres, long/short axes",
                "z_semantics": (
                    "source Z preserved unchanged; only the ball carries Z in this release"
                ),
                "hybrid_geometry_statement": HYBRID_GEOMETRY_STATEMENT,
                "measurement_note": (
                    "broadcast computer-vision provider estimates, not an instrument measurement"
                ),
            },
            grain=DataGrain(kind=DataGrainKind.FRAME_SERIES),
        )

    def _quarantine(
        self,
        summary: TrackingPeriodSummary,
        *,
        rule: str,
        detail: str,
        source_record_id: str,
        subject_id: str | None = None,
        source_time: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        summary.quarantined.append(
            QuarantinedRecord(
                rule=rule,
                detail=detail,
                dataset_id=self._dataset_id,
                session_id=self._metadata.session_id,
                stream_id=summary.stream_id,
                subject_id=subject_id,
                source_record_id=source_record_id,
                source_time=source_time,
                evidence=evidence or {},
            )
        )

    def _batches(
        self, period: MatchPeriod, summary: TrackingPeriodSummary
    ) -> Iterator[pa.RecordBatch]:
        rows: list[dict[str, Any]] = []
        sample_index = 0
        last_frame: int | None = None
        with self._path.open("r", encoding="utf-8") as handle:
            for line_number, raw in enumerate(handle):
                payload = json.loads(raw)
                frame = int(payload["frame"])
                if not period.contains(frame):
                    continue
                summary.source_frames += 1
                duplicate = last_frame is not None and frame <= last_frame
                if duplicate:
                    summary.duplicate_frames += 1
                last_frame = frame
                timestamp = payload.get("timestamp")
                try:
                    t_rel_ns = match_time_ns(timestamp)
                except ValueError as exc:
                    for entry in payload.get("player_data") or []:
                        summary.source_player_entries += 1
                        self._quarantine(
                            summary,
                            rule=RULE_TIMESTAMP_UNPARSABLE,
                            detail=str(exc),
                            source_record_id=f"line={line_number}",
                            subject_id=str(entry.get("player_id"))
                            if isinstance(entry, dict)
                            else None,
                        )
                    if payload.get("ball_data") is not None:
                        summary.source_ball_entries += 1
                        self._quarantine(
                            summary,
                            rule=RULE_TIMESTAMP_UNPARSABLE,
                            detail=str(exc),
                            source_record_id=f"line={line_number}",
                        )
                    continue
                summary.first_t_rel_ns = (
                    t_rel_ns
                    if summary.first_t_rel_ns is None
                    else min(summary.first_t_rel_ns, t_rel_ns)
                )
                summary.last_t_rel_ns = (
                    t_rel_ns
                    if summary.last_t_rel_ns is None
                    else max(summary.last_t_rel_ns, t_rel_ns)
                )
                for entry in payload.get("player_data") or []:
                    summary.source_player_entries += 1
                    if duplicate:
                        self._quarantine(
                            summary,
                            rule=RULE_DUPLICATE_FRAME,
                            detail="tracking frame is repeated or out of order",
                            source_record_id=str(frame),
                            subject_id=str(entry.get("player_id"))
                            if isinstance(entry, dict)
                            else None,
                            evidence={"frame": frame},
                        )
                        continue
                    row = self._player_row(entry, summary, period, t_rel_ns)
                    if row is None:
                        continue
                    sample_index = self._append(rows, row, sample_index)
                    if len(rows) >= self._batch_size:
                        yield self._batch(rows)
                        rows = []
                if payload.get("ball_data") is not None:
                    summary.source_ball_entries += 1
                    if duplicate:
                        self._quarantine(
                            summary,
                            rule=RULE_DUPLICATE_FRAME,
                            detail="tracking frame is repeated or out of order",
                            source_record_id=str(frame),
                            evidence={"frame": frame},
                        )
                        continue
                    ball = payload["ball_data"] if isinstance(payload["ball_data"], dict) else {}
                    if all(ball.get(key) is None for key in ("x", "y", "z")):
                        summary.ignored_ball_without_coordinates += 1
                        continue
                    ball_row = self._ball_row(ball, summary, period, t_rel_ns)
                    if ball_row is not None:
                        sample_index = self._append(rows, ball_row, sample_index)
                if len(rows) >= self._batch_size:
                    yield self._batch(rows)
                    rows = []
        if rows:
            yield self._batch(rows)

    def _append(self, rows: list[dict[str, Any]], row: dict[str, Any], sample_index: int) -> int:
        row["sample_index"] = sample_index
        rows.append(row)
        return sample_index + 1

    def _batch(self, rows: list[dict[str, Any]]) -> pa.RecordBatch:
        return pa.RecordBatch.from_pylist(rows, schema=self._schema)

    def _base_row(
        self,
        *,
        period: MatchPeriod,
        t_rel_ns: int,
        object_id: str,
        object_type: str,
        subject_id: str | None,
        group_id: str | None,
    ) -> dict[str, Any]:
        return {
            "dataset_id": self._dataset_id,
            "session_id": self._metadata.session_id,
            "trial_id": period.name,
            "subject_id": subject_id,
            "device_id": None,
            "stream_id": tracking_stream_id(period.period),
            "sample_index": 0,
            "t_rel_ns": t_rel_ns,
            "timestamp_utc_ns": None,
            "nominal_sampling_rate_hz": TRACKING_FRAME_RATE_HZ,
            "measurement_class": MeasurementClass.MODEL_ESTIMATED.value,
            "clock_id": CLOCK_ID,
            "synchronization_spec_id": SYNC_SPEC_ID,
            "coordinate_frame_id": TRACKING_FRAME_ID,
            "object_id": object_id,
            "object_type": object_type,
            "group_id": group_id,
            "x_m": None,
            "y_m": None,
            "z_m": None,
            "vx_m_s": None,
            "vy_m_s": None,
            "vz_m_s": None,
            "ax_m_s2": None,
            "ay_m_s2": None,
            "az_m_s2": None,
            "is_detected": None,
            "confidence": None,
        }

    def _player_row(
        self,
        entry: object,
        summary: TrackingPeriodSummary,
        period: MatchPeriod,
        t_rel_ns: int,
    ) -> dict[str, Any] | None:
        if not isinstance(entry, dict):
            self._quarantine(
                summary,
                rule=RULE_NON_FINITE_VALUE,
                detail="player entry is not an object",
                source_record_id=period.name,
            )
            return None
        player_id = entry.get("player_id")
        player = None if player_id is None else self._metadata.player(str(player_id))
        if player is None:
            if player_id is not None:
                summary.unknown_player_ids.add(str(player_id))
            self._quarantine(
                summary,
                rule=RULE_UNKNOWN_PARTICIPANT,
                detail="tracking player id is not a declared participant",
                source_record_id=str(player_id),
                subject_id=None if player_id is None else str(player_id),
            )
            return None
        summary.seen_player_ids.add(player.player_id)
        x = entry.get("x")
        y = entry.get("y")
        if not _finite_number(x) or not _finite_number(y):
            self._quarantine(
                summary,
                rule=RULE_NON_FINITE_VALUE,
                detail="tracking player coordinates are missing or non-finite",
                source_record_id=player.player_id,
                subject_id=player.player_id,
                evidence={"x": x, "y": y},
            )
            return None
        row = self._base_row(
            period=period,
            t_rel_ns=t_rel_ns,
            object_id=player.player_id,
            object_type="goalkeeper" if player.is_goalkeeper else "player",
            subject_id=player.player_id,
            group_id=player.team_id,
        )
        row["x_m"] = _as_float(x)
        row["y_m"] = _as_float(y)
        detected = entry.get("is_detected")
        if detected is None:
            summary.detected_null += 1
        elif bool(detected):
            summary.detected_true += 1
        else:
            summary.detected_false += 1
        row["is_detected"] = None if detected is None else bool(detected)
        summary.canonical_rows += 1
        return row

    def _ball_row(
        self,
        ball: dict[str, Any],
        summary: TrackingPeriodSummary,
        period: MatchPeriod,
        t_rel_ns: int,
    ) -> dict[str, Any] | None:
        x = ball.get("x")
        y = ball.get("y")
        z = ball.get("z")
        if not _finite_number(x) or not _finite_number(y):
            self._quarantine(
                summary,
                rule=RULE_COORDINATE_MISSING,
                detail="ball entry has no finite X/Y pair",
                source_record_id="ball",
                evidence={"x": x, "y": y, "z": z},
            )
            return None
        if z is not None and not _finite_number(z):
            self._quarantine(
                summary,
                rule=RULE_NON_FINITE_VALUE,
                detail="ball Z is present but not finite",
                source_record_id="ball",
                evidence={"z": z},
            )
            return None
        row = self._base_row(
            period=period,
            t_rel_ns=t_rel_ns,
            object_id="ball",
            object_type="ball",
            subject_id=None,
            group_id=None,
        )
        row["x_m"] = _as_float(x)
        row["y_m"] = _as_float(y)
        row["z_m"] = None if z is None else _as_float(z)
        detected = ball.get("is_detected")
        row["is_detected"] = None if detected is None else bool(detected)
        summary.canonical_rows += 1
        return row


__all__ = [
    "TrackingCanonicalizer",
    "TrackingPeriodSummary",
    "match_time_ns",
]
