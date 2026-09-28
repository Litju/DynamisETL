"""25 Hz SkillCorner basketball tracking and lossless frame-clock index."""

from __future__ import annotations

import gzip
import json
import math
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa

from dynamis.adapters.skillcorner_basketball import authorities
from dynamis.contracts import MeasurementClass, Modality, get_schema
from dynamis.contracts.sports import DataGrain, DataGrainKind, SportsEntityKind, canonical_sports_id
from dynamis.pipeline.streams import CanonicalStream

FRAME_CLOCK_SCHEMA = pa.schema(
    [
        pa.field("frame_idx", pa.int64(), nullable=False),
        pa.field("period_number", pa.int16(), nullable=False),
        pa.field("wall_clock_ms", pa.int64(), nullable=False),
        pa.field("canonical_time_ns", pa.int64(), nullable=False),
        pa.field("game_clock_s", pa.float64(), nullable=True),
        pa.field("game_clock_stopped", pa.bool_(), nullable=False),
        pa.field("shot_clock_s", pa.float64(), nullable=True),
        pa.field("player_count", pa.int16(), nullable=False),
        pa.field("ball_present", pa.bool_(), nullable=False),
        pa.field("is_dead_time", pa.bool_(), nullable=False),
    ],
    metadata={
        b"dynamis.contract": b"skillcorner_basketball_frame_clock",
        b"dynamis.schema_version": b"1",
        b"dynamis.frame_rate_hz": b"25",
        b"dynamis.source_clock": b"wallClock milliseconds since video start",
    },
)


def _number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} is not numeric: {value!r}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} is not finite: {value!r}")
    return result


def _integer(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} is not an integer: {value!r}")
    return value


def _coordinates(payload: dict[str, Any], *, object_id: str) -> tuple[float, float, float | None]:
    xyz = payload.get("xyz")
    if not isinstance(xyz, list) or len(xyz) < 2:
        raise ValueError(f"{object_id}: source xyz must contain x and y")
    x = _number(xyz[0], field_name=f"{object_id}.x")
    y = _number(xyz[1], field_name=f"{object_id}.y")
    z = (
        _number(xyz[2], field_name=f"{object_id}.z")
        if len(xyz) > 2 and xyz[2] is not None
        else None
    )
    return x, y, z


def _has_xy_coordinates(payload: dict[str, Any]) -> bool:
    coordinates = payload.get("xyz")
    return isinstance(coordinates, list) and len(coordinates) >= 2


@dataclass(slots=True)
class PeriodFrameSummary:
    period: int
    first_frame: int | None = None
    last_frame: int | None = None
    first_time_ns: int | None = None
    last_time_ns: int | None = None
    frame_count: int = 0
    dead_time_frames: int = 0
    frames_with_players: int = 0
    frames_with_ball: int = 0

    def observe(
        self,
        *,
        frame_idx: int,
        time_ns: int,
        player_count: int,
        ball_present: bool,
    ) -> None:
        if self.last_frame is not None and frame_idx <= self.last_frame:
            raise ValueError(f"period {self.period}: frameIdx is duplicated or out of order")
        if self.last_time_ns is not None and time_ns <= self.last_time_ns:
            raise ValueError(f"period {self.period}: wallClock is duplicated or out of order")
        self.first_frame = frame_idx if self.first_frame is None else self.first_frame
        self.first_time_ns = time_ns if self.first_time_ns is None else self.first_time_ns
        self.last_frame = frame_idx
        self.last_time_ns = time_ns
        self.frame_count += 1
        self.dead_time_frames += int(player_count == 0 and not ball_present)
        self.frames_with_players += int(player_count > 0)
        self.frames_with_ball += int(ball_present)

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "first_frame": self.first_frame,
            "last_frame": self.last_frame,
            "first_time_ns": self.first_time_ns,
            "last_time_ns": self.last_time_ns,
            "frame_count": self.frame_count,
            "dead_time_frames": self.dead_time_frames,
            "frames_with_players": self.frames_with_players,
            "frames_with_ball": self.frames_with_ball,
        }


@dataclass(slots=True)
class FrameClockSummary:
    game_id: str
    periods: dict[int, PeriodFrameSummary] = field(default_factory=dict)
    frame_count: int = 0
    dead_time_frames: int = 0
    source_player_entries: int = 0
    source_ball_observations: int = 0
    wall_clock_delta_counts_ms: Counter[int] = field(default_factory=Counter)

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "frame_rate_hz": authorities.FRAME_RATE_HZ,
            "frame_count": self.frame_count,
            "dead_time_frames": self.dead_time_frames,
            "source_player_entries": self.source_player_entries,
            "source_ball_observations": self.source_ball_observations,
            "wall_clock_delta_counts_ms": dict(sorted(self.wall_clock_delta_counts_ms.items())),
            "periods": [self.periods[number].to_dict() for number in sorted(self.periods)],
        }


def _frame_clock_batch(rows: list[dict[str, Any]]) -> pa.RecordBatch:
    return pa.RecordBatch.from_pylist(rows, schema=FRAME_CLOCK_SCHEMA)


def write_frame_clock(
    path: Path,
    *,
    game_id: str,
    session_id: str,
    output_path: Path,
    dataset_root: Path,
    batch_size: int,
    row_group_size: int,
):
    """Index every source frame, including dead time, with bounded memory."""
    from dynamis.storage.parquet import write_parquet_streaming_atomic

    summary = FrameClockSummary(game_id=game_id)

    def batches() -> Iterator[pa.RecordBatch]:
        rows: list[dict[str, Any]] = []
        last_wall_ms: int | None = None
        with gzip.open(path, "rt", encoding="utf-8") as source:
            for line_no, raw in enumerate(source, start=1):
                frame = json.loads(raw)
                frame_idx = _integer(frame.get("frameIdx"), field_name=f"line {line_no}.frameIdx")
                period = _integer(frame.get("period"), field_name=f"line {line_no}.period")
                wall_ms = _integer(frame.get("wallClock"), field_name=f"line {line_no}.wallClock")
                if period < 1:
                    raise ValueError(f"line {line_no}: source period must be >= 1")
                if last_wall_ms is not None:
                    delta = wall_ms - last_wall_ms
                    if delta <= 0:
                        raise ValueError(f"line {line_no}: wallClock is not increasing")
                    summary.wall_clock_delta_counts_ms[delta] += 1
                last_wall_ms = wall_ms
                home = frame.get("homePlayers") or []
                away = frame.get("awayPlayers") or []
                if not isinstance(home, list) or not isinstance(away, list):
                    raise ValueError(f"line {line_no}: homePlayers and awayPlayers must be arrays")
                ball = frame.get("ball")
                if ball is None:
                    ball = {}
                if not isinstance(ball, dict):
                    raise ValueError(f"line {line_no}: ball must be an object")
                ball_present = _has_xy_coordinates(ball)
                if ball_present:
                    _coordinates(ball, object_id="ball")
                game_clock = frame.get("gameClock")
                shot_clock = frame.get("shotClock")
                stopped = frame.get("gameClockStopped")
                if not isinstance(stopped, bool):
                    raise ValueError(f"line {line_no}: gameClockStopped must be boolean")
                game_clock_s = (
                    _number(game_clock, field_name=f"line {line_no}.gameClock")
                    if game_clock is not None
                    else None
                )
                shot_clock_s = (
                    _number(shot_clock, field_name=f"line {line_no}.shotClock")
                    if shot_clock is not None
                    else None
                )
                player_count = len(home) + len(away)
                time_ns = wall_ms * 1_000_000
                period_summary = summary.periods.setdefault(
                    period, PeriodFrameSummary(period=period)
                )
                period_summary.observe(
                    frame_idx=frame_idx,
                    time_ns=time_ns,
                    player_count=player_count,
                    ball_present=ball_present,
                )
                summary.frame_count += 1
                summary.dead_time_frames += int(player_count == 0 and not ball_present)
                summary.source_player_entries += player_count
                summary.source_ball_observations += int(ball_present)
                rows.append(
                    {
                        "frame_idx": frame_idx,
                        "period_number": period,
                        "wall_clock_ms": wall_ms,
                        "canonical_time_ns": time_ns,
                        "game_clock_s": game_clock_s,
                        "game_clock_stopped": stopped,
                        "shot_clock_s": shot_clock_s,
                        "player_count": player_count,
                        "ball_present": ball_present,
                        "is_dead_time": player_count == 0 and not ball_present,
                    }
                )
                if len(rows) >= batch_size:
                    yield _frame_clock_batch(rows)
                    rows = []
        if rows:
            yield _frame_clock_batch(rows)

    written = write_parquet_streaming_atomic(
        batches(),
        output_path,
        schema=FRAME_CLOCK_SCHEMA,
        row_group_size=row_group_size,
        relative_to=dataset_root,
    )
    return summary, written


@dataclass(slots=True)
class TrackingPeriodSummary:
    period: int
    stream_id: str
    source_frames: int = 0
    player_entries: int = 0
    ball_observations: int = 0
    canonical_rows: int = 0
    first_time_ns: int | None = None
    last_time_ns: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "stream_id": self.stream_id,
            "source_frames": self.source_frames,
            "player_entries": self.player_entries,
            "ball_observations": self.ball_observations,
            "canonical_rows": self.canonical_rows,
            "first_time_ns": self.first_time_ns,
            "last_time_ns": self.last_time_ns,
        }


class BasketballTrackingCanonicalizer:
    """Stream source player/ball observations into standard tracking samples."""

    def __init__(
        self,
        *,
        path: Path,
        game_id: str,
        game_data: dict[str, Any],
        frame_clock: FrameClockSummary,
        batch_size: int,
        player_aliases: dict[str, str] | None = None,
    ) -> None:
        self.path = Path(path)
        self.game_id = game_id
        self.game_data = game_data
        self.frame_clock = frame_clock
        self.player_aliases = player_aliases or {}
        self.batch_size = batch_size
        self.schema = get_schema(Modality.TRACKING)
        self._team_ids = {
            "home": canonical_sports_id(
                authorities.NAMESPACE, SportsEntityKind.TEAM, str(game_data["homeTeam"]["teamId"])
            ),
            "away": canonical_sports_id(
                authorities.NAMESPACE, SportsEntityKind.TEAM, str(game_data["awayTeam"]["teamId"])
            ),
        }
        self._period_summaries: dict[int, TrackingPeriodSummary] = {}

    def streams(self) -> tuple[CanonicalStream, ...]:
        return tuple(self.stream(number) for number in sorted(self.frame_clock.periods))

    def summary(self, period: int) -> TrackingPeriodSummary:
        return self._period_summaries[period]

    def stream(self, period: int) -> CanonicalStream:
        if period not in self.frame_clock.periods:
            raise KeyError(f"game {self.game_id} has no source period {period}")
        stream_id = f"{self.game_id}-tracking-period-{period}"
        summary = TrackingPeriodSummary(period=period, stream_id=stream_id)
        self._period_summaries[period] = summary
        return CanonicalStream(
            dataset_id=authorities.DATASET_ID,
            session_id=self.game_id,
            stream_id=stream_id,
            modality=Modality.TRACKING,
            measurement_class=MeasurementClass.MODEL_ESTIMATED,
            clock_id=authorities.WALL_CLOCK_ID,
            synchronization_spec_id=authorities.SYNC_SPEC_ID,
            trial_id=f"period-{period}",
            coordinate_frame_id=authorities.COURT_FRAME_ID,
            nominal_sampling_rate_hz=authorities.FRAME_RATE_HZ,
            source_unit="ft",
            batches=self._batches(period, summary),
            schema=self.schema,
            stream_metadata={
                "adapter": authorities.ADAPTER_ID,
                "contest_id": canonical_sports_id(
                    authorities.NAMESPACE, SportsEntityKind.CONTEST, self.game_id
                ),
                "provider_game_id": self.game_id,
                "provider_frame_rate_hz": authorities.FRAME_RATE_HZ,
                "source_coordinates": "center-origin feet; x court length, y court width",
                "source_to_si_scale": authorities.FT_TO_M,
                "dead_time_policy": "source frames with empty players/ball emit no positions",
            },
            grain=DataGrain(kind=DataGrainKind.FRAME_SERIES),
        )

    def _row(
        self,
        *,
        sample_index: int,
        period: int,
        time_ns: int,
        object_id: str,
        object_type: str,
        group_id: str | None,
        subject_id: str | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        x_ft, y_ft, z_ft = _coordinates(payload, object_id=object_id)
        detected = payload.get("isDetected")
        if detected is not None and detected not in (0, 1, 0.0, 1.0, False, True):
            raise ValueError(f"{object_id}: isDetected must be 0, 1 or null")
        return {
            "dataset_id": authorities.DATASET_ID,
            "session_id": self.game_id,
            "trial_id": f"period-{period}",
            "subject_id": subject_id,
            "device_id": None,
            "stream_id": f"{self.game_id}-tracking-period-{period}",
            "sample_index": sample_index,
            "t_rel_ns": time_ns,
            "timestamp_utc_ns": None,
            "nominal_sampling_rate_hz": authorities.FRAME_RATE_HZ,
            "measurement_class": MeasurementClass.MODEL_ESTIMATED.value,
            "clock_id": authorities.WALL_CLOCK_ID,
            "synchronization_spec_id": authorities.SYNC_SPEC_ID,
            "coordinate_frame_id": authorities.COURT_FRAME_ID,
            "object_id": object_id,
            "object_type": object_type,
            "group_id": group_id,
            "x_m": x_ft * authorities.FT_TO_M,
            "y_m": y_ft * authorities.FT_TO_M,
            "z_m": z_ft * authorities.FT_TO_M if z_ft is not None else None,
            "vx_m_s": None,
            "vy_m_s": None,
            "vz_m_s": None,
            "ax_m_s2": None,
            "ay_m_s2": None,
            "az_m_s2": None,
            "is_detected": bool(detected) if detected is not None else None,
            "confidence": None,
        }

    def _batches(self, period: int, summary: TrackingPeriodSummary) -> Iterator[pa.RecordBatch]:
        rows: list[dict[str, Any]] = []
        sample_index = 0
        with gzip.open(self.path, "rt", encoding="utf-8") as source:
            for line_no, raw in enumerate(source, start=1):
                frame = json.loads(raw)
                if _integer(frame.get("period"), field_name=f"line {line_no}.period") != period:
                    continue
                summary.source_frames += 1
                _integer(frame.get("frameIdx"), field_name=f"line {line_no}.frameIdx")
                wall_ms = _integer(frame.get("wallClock"), field_name=f"line {line_no}.wallClock")
                time_ns = wall_ms * 1_000_000
                summary.first_time_ns = (
                    time_ns if summary.first_time_ns is None else summary.first_time_ns
                )
                summary.last_time_ns = time_ns
                for side in ("home", "away"):
                    entries = frame.get(f"{side}Players") or []
                    if not isinstance(entries, list):
                        raise ValueError(f"line {line_no}: {side}Players must be an array")
                    for player in entries:
                        if not isinstance(player, dict) or player.get("playerId") is None:
                            raise ValueError(f"line {line_no}: player entry lacks playerId")
                        player_id = str(player["playerId"])
                        canonical_player_id = self.player_aliases.get(player_id, player_id)
                        subject_id = canonical_sports_id(
                            authorities.NAMESPACE,
                            SportsEntityKind.SUBJECT,
                            canonical_player_id,
                        )
                        rows.append(
                            self._row(
                                sample_index=sample_index,
                                period=period,
                                time_ns=time_ns,
                                object_id=player_id,
                                object_type="player",
                                group_id=self._team_ids[side],
                                subject_id=subject_id,
                                payload=player,
                            )
                        )
                        sample_index += 1
                        summary.player_entries += 1
                ball = frame.get("ball")
                if ball is None:
                    ball = {}
                if not isinstance(ball, dict):
                    raise ValueError(f"line {line_no}: ball must be an object")
                if _has_xy_coordinates(ball):
                    rows.append(
                        self._row(
                            sample_index=sample_index,
                            period=period,
                            time_ns=time_ns,
                            object_id="ball",
                            object_type="ball",
                            group_id=None,
                            subject_id=None,
                            payload=ball,
                        )
                    )
                    sample_index += 1
                    summary.ball_observations += 1
                if len(rows) >= self.batch_size:
                    batch = pa.RecordBatch.from_pylist(rows, schema=self.schema)
                    summary.canonical_rows += batch.num_rows
                    yield batch
                    rows = []
        if rows:
            batch = pa.RecordBatch.from_pylist(rows, schema=self.schema)
            summary.canonical_rows += batch.num_rows
            yield batch


__all__ = [
    "BasketballTrackingCanonicalizer",
    "FRAME_CLOCK_SCHEMA",
    "FrameClockSummary",
    "PeriodFrameSummary",
    "TrackingPeriodSummary",
    "write_frame_clock",
]
