"""SPL free-throw trial canonicalization.

The provider distributes one JSON document per trial with a ``tracking`` list of
frames; each frame carries ``data.player`` (a mapping from keypoint name to a
three-component position or ``null``) and ``data.ball``. This module validates
that structure, discovers the session's keypoint set honestly (including names
outside the documented table), and streams one canonical ``pose_joint_sample``
stream per trial with the exact ``0.3048`` feet-to-metre conversion.

No parent graph exists in the source and none is invented. A keypoint absent
from a frame, or explicitly ``null``, becomes an ``is_available=false`` row with
null coordinates; nothing is imputed.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa

from dynamis.adapters.spl.authorities import (
    FEET_TO_METRE_SCALE,
    SOURCE_LENGTH_UNIT,
    SPL_DATASET_ID,
    SPL_KEYPOINTS,
    SPL_SESSION_RATES_HZ,
    court_frame,
    ordered_keypoints,
    pose_stream_id,
    session_clock,
    session_sync_spec,
    skeleton_id_for,
)
from dynamis.contracts import MeasurementClass, Modality, get_schema
from dynamis.contracts.sports import DataGrain, DataGrainKind
from dynamis.pipeline.quarantine import (
    RULE_NON_FINITE_VALUE,
    QuarantinedRecord,
)
from dynamis.pipeline.streams import DEFAULT_BATCH_SIZE, CanonicalStream

TRIAL_KEY = re.compile(
    r"data/(?P<session>\d{4}-\d{2}-\d{2})/(?P<participant>P\d+)/"
    r"BB_FT_(?P<file_participant>P\d+)_(?P<trial>T\d+)\.json$"
)
_DOCUMENTED_KEYPOINTS = frozenset(SPL_KEYPOINTS)


class SplTrialError(ValueError):
    """The distributed trial document does not match the documented structure."""


@dataclass(frozen=True, slots=True)
class SplTrialIdentity:
    session_date: str
    participant_id: str
    trial_id: str

    @property
    def session_id(self) -> str:
        return self.session_date


def identity_from_key(key: str) -> SplTrialIdentity:
    """Derive session/participant/trial identity from the registry file key."""
    match = TRIAL_KEY.search(key)
    if match is None:
        raise SplTrialError(f"{key!r} is not a documented SPL free-throw trial key")
    if match.group("participant") != match.group("file_participant"):
        raise SplTrialError(
            f"{key!r}: folder participant {match.group('participant')!r} does not match "
            f"file participant {match.group('file_participant')!r}"
        )
    return SplTrialIdentity(
        session_date=match.group("session"),
        participant_id=match.group("participant"),
        trial_id=match.group("trial"),
    )


def sampling_rate_for(session_date: str) -> float:
    try:
        return SPL_SESSION_RATES_HZ[session_date]
    except KeyError as exc:
        raise SplTrialError(
            f"session {session_date!r} has no documented sampling rate; known sessions: "
            f"{sorted(SPL_SESSION_RATES_HZ)}"
        ) from exc


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


@dataclass(slots=True)
class SplTrialSummary:
    identity: SplTrialIdentity
    stream_id: str
    sampling_rate_hz: float
    keypoints: tuple[str, ...]
    undocumented_keypoints: tuple[str, ...]
    frames: int = 0
    observed_keypoints: int = 0
    unavailable_keypoints: int = 0
    absent_keypoint_observations: int = 0
    malformed_keypoints: int = 0
    quarantined: list[QuarantinedRecord] = field(default_factory=list)
    ball_observations: int = 0
    ball_with_xyz: int = 0
    first_t_rel_ns: int | None = None
    last_t_rel_ns: int | None = None

    @property
    def keypoint_count(self) -> int:
        return len(self.keypoints)

    @property
    def source_records(self) -> int:
        return self.frames * self.keypoint_count

    @property
    def canonical_rows(self) -> int:
        return self.observed_keypoints + self.unavailable_keypoints

    @property
    def quarantined_rows(self) -> int:
        return self.malformed_keypoints

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_date": self.identity.session_date,
            "participant_id": self.identity.participant_id,
            "trial_id": self.identity.trial_id,
            "stream_id": self.stream_id,
            "sampling_rate_hz": self.sampling_rate_hz,
            "keypoint_count": self.keypoint_count,
            "keypoints": list(self.keypoints),
            "undocumented_keypoints": list(self.undocumented_keypoints),
            "frames": self.frames,
            "observed_keypoints": self.observed_keypoints,
            "unavailable_keypoints": self.unavailable_keypoints,
            "absent_keypoint_observations": self.absent_keypoint_observations,
            "malformed_keypoints": self.malformed_keypoints,
            "canonical_rows": self.canonical_rows,
            "ball_observations": self.ball_observations,
            "ball_with_xyz": self.ball_with_xyz,
            "first_t_rel_ns": self.first_t_rel_ns,
            "last_t_rel_ns": self.last_t_rel_ns,
        }


@dataclass(frozen=True, slots=True)
class _Frame:
    index: int
    player: dict[str, object]
    ball: object


class SplTrialCanonicalizer:
    """Parses one trial document and streams its canonical pose rows."""

    def __init__(
        self,
        path: Path,
        identity: SplTrialIdentity,
        *,
        dataset_id: str = SPL_DATASET_ID,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._path = Path(path)
        self._identity = identity
        self._dataset_id = dataset_id
        self._batch_size = batch_size
        self._rate = sampling_rate_for(identity.session_date)
        self._schema = get_schema(Modality.POSE)
        self._frames: tuple[_Frame, ...] | None = None
        self._keypoints: tuple[str, ...] | None = None
        self._summary: SplTrialSummary | None = None

    # -- structure discovery --------------------------------------------

    def _parse(self) -> None:
        if self._frames is not None:
            return
        try:
            document = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SplTrialError(f"{self._path.name}: not valid JSON: {exc}") from exc
        if not isinstance(document, dict):
            raise SplTrialError(f"{self._path.name}: root is not a JSON object")
        raw_frames = document.get("tracking")
        if not isinstance(raw_frames, list) or not raw_frames:
            raise SplTrialError(f"{self._path.name}: 'tracking' must be a non-empty array")
        frames: list[_Frame] = []
        names: set[str] = set()
        for index, raw in enumerate(raw_frames):
            if not isinstance(raw, dict):
                raise SplTrialError(f"{self._path.name}: frame {index} is not an object")
            data = raw.get("data")
            if not isinstance(data, dict):
                raise SplTrialError(f"{self._path.name}: frame {index} has no data object")
            player = data.get("player")
            if not isinstance(player, dict):
                raise SplTrialError(
                    f"{self._path.name}: frame {index} has no player keypoint mapping"
                )
            for name in player:
                names.add(str(name))
            frames.append(_Frame(index=index, player=player, ball=data.get("ball")))
        self._frames = tuple(frames)
        self._keypoints = ordered_keypoints(names)

    @property
    def identity(self) -> SplTrialIdentity:
        return self._identity

    @property
    def sampling_rate_hz(self) -> float:
        return self._rate

    @property
    def keypoints(self) -> tuple[str, ...]:
        self._parse()
        assert self._keypoints is not None
        return self._keypoints

    @property
    def skeleton_id(self) -> str:
        return skeleton_id_for(self.keypoints)

    def summary(self) -> SplTrialSummary:
        if self._summary is None:
            self._summary = SplTrialSummary(
                identity=self._identity,
                stream_id=pose_stream_id(self._identity.session_date, self._identity.trial_id),
                sampling_rate_hz=self._rate,
                keypoints=self.keypoints,
                undocumented_keypoints=tuple(
                    name for name in self.keypoints if name not in _DOCUMENTED_KEYPOINTS
                ),
            )
        return self._summary

    def stream(self) -> CanonicalStream:
        summary = self.summary()
        return CanonicalStream(
            dataset_id=self._dataset_id,
            session_id=self._identity.session_id,
            stream_id=summary.stream_id,
            modality=Modality.POSE,
            measurement_class=MeasurementClass.MODEL_ESTIMATED,
            clock_id=session_clock(self._identity.session_date, self._rate).clock_id,
            synchronization_spec_id=session_sync_spec(
                self._identity.session_date, self._rate
            ).sync_spec_id,
            trial_id=self._identity.trial_id,
            subject_id=self._identity.participant_id,
            coordinate_frame_id=court_frame().frame_id,
            nominal_sampling_rate_hz=self._rate,
            source_unit=SOURCE_LENGTH_UNIT,
            batches=self._batches(summary),
            schema=self._schema,
            stream_metadata={
                "adapter": "spl_freethrow",
                "source_file_key": f"data/{self._identity.session_date}/"
                f"{self._identity.participant_id}/"
                f"BB_FT_{self._identity.participant_id}_{self._identity.trial_id}.json",
                "provider_product": "markerless 3D pose (free throw)",
                "source_length_unit": SOURCE_LENGTH_UNIT,
                "source_to_si_scale": FEET_TO_METRE_SCALE,
                "keypoint_authority": (
                    "basketball/freethrow/README.md keypoint table at the pinned revision"
                ),
                "session_specific_availability": True,
                "parent_graph": "source publishes no parent graph; landmark_set only",
            },
            grain=DataGrain(
                kind=DataGrainKind.TRIAL_SERIES,
                axes=("subject", "trial", "sample_index", "joint"),
            ),
        )

    def _batches(self, summary: SplTrialSummary) -> Iterator[pa.RecordBatch]:
        self._parse()
        assert self._frames is not None
        rows: list[dict[str, Any]] = []
        sample_index = 0
        keypoints = summary.keypoints
        for frame in self._frames:
            summary.frames += 1
            t_rel_ns = round(frame.index * 1_000_000_000 / self._rate)
            summary.first_t_rel_ns = (
                t_rel_ns
                if summary.first_t_rel_ns is None
                else min(summary.first_t_rel_ns, t_rel_ns)
            )
            summary.last_t_rel_ns = (
                t_rel_ns if summary.last_t_rel_ns is None else max(summary.last_t_rel_ns, t_rel_ns)
            )
            if isinstance(frame.ball, list):
                summary.ball_observations += 1
                if len(frame.ball) == 3 and all(
                    _finite_number(component) for component in frame.ball
                ):
                    summary.ball_with_xyz += 1
            elif frame.ball is not None:
                summary.ball_observations += 1
            for name in keypoints:
                if name not in frame.player:
                    summary.absent_keypoint_observations += 1
                    summary.unavailable_keypoints += 1
                    row = self._row(
                        frame=frame,
                        summary=summary,
                        name=name,
                        t_rel_ns=t_rel_ns,
                        available=False,
                        xyz=None,
                    )
                else:
                    row = self._value_row(
                        frame=frame,
                        summary=summary,
                        name=name,
                        value=frame.player[name],
                        t_rel_ns=t_rel_ns,
                    )
                if row is None:
                    continue
                row["sample_index"] = sample_index
                sample_index += 1
                rows.append(row)
                if len(rows) >= self._batch_size:
                    yield self._batch(rows)
                    rows = []
        if rows:
            yield self._batch(rows)

    def _batch(self, rows: list[dict[str, Any]]) -> pa.RecordBatch:
        return pa.RecordBatch.from_pylist(rows, schema=self._schema)

    def _value_row(
        self,
        *,
        frame: _Frame,
        summary: SplTrialSummary,
        name: str,
        value: object,
        t_rel_ns: int,
    ) -> dict[str, Any] | None:
        if value is None:
            summary.unavailable_keypoints += 1
            return self._row(
                frame=frame,
                summary=summary,
                name=name,
                t_rel_ns=t_rel_ns,
                available=False,
                xyz=None,
            )
        if not isinstance(value, list) or len(value) != 3:
            self._malformed(summary, frame, name, "value is not a 3-element list")
            return None
        if not all(_finite_number(component) for component in value):
            self._malformed(summary, frame, name, "value is not finite")
            return None
        summary.observed_keypoints += 1
        return self._row(
            frame=frame,
            summary=summary,
            name=name,
            t_rel_ns=t_rel_ns,
            available=True,
            xyz=(float(value[0]), float(value[1]), float(value[2])),
        )

    def _row(
        self,
        *,
        frame: _Frame,
        summary: SplTrialSummary,
        name: str,
        t_rel_ns: int,
        available: bool,
        xyz: tuple[float, float, float] | None,
    ) -> dict[str, Any]:
        assert xyz is not None or not available
        converted = (
            None if xyz is None else tuple(component * FEET_TO_METRE_SCALE for component in xyz)
        )
        return {
            "dataset_id": self._dataset_id,
            "session_id": self._identity.session_id,
            "trial_id": self._identity.trial_id,
            "subject_id": self._identity.participant_id,
            "device_id": None,
            "stream_id": summary.stream_id,
            "sample_index": 0,
            "t_rel_ns": t_rel_ns,
            "timestamp_utc_ns": None,
            "nominal_sampling_rate_hz": self._rate,
            "measurement_class": MeasurementClass.MODEL_ESTIMATED.value,
            "clock_id": session_clock(self._identity.session_date, self._rate).clock_id,
            "synchronization_spec_id": session_sync_spec(
                self._identity.session_date, self._rate
            ).sync_spec_id,
            "coordinate_frame_id": court_frame().frame_id,
            "skeleton_id": self.skeleton_id,
            "joint_id": summary.keypoints.index(name),
            "joint_name": name,
            "parent_joint_id": None,
            "is_available": available,
            "x_m": None if converted is None else converted[0],
            "y_m": None if converted is None else converted[1],
            "z_m": None if converted is None else converted[2],
            "confidence": None,
            "error_m": None,
            "is_occluded": None,
        }

    def _malformed(self, summary: SplTrialSummary, frame: _Frame, name: str, detail: str) -> None:
        summary.malformed_keypoints += 1
        summary.quarantined.append(
            QuarantinedRecord(
                rule=RULE_NON_FINITE_VALUE,
                detail=f"keypoint {name!r}: {detail}",
                dataset_id=self._dataset_id,
                session_id=self._identity.session_id,
                stream_id=summary.stream_id,
                subject_id=self._identity.participant_id,
                source_record_id=f"frame={frame.index}",
            )
        )


__all__ = [
    "SplTrialCanonicalizer",
    "SplTrialError",
    "SplTrialIdentity",
    "SplTrialSummary",
    "identity_from_key",
    "sampling_rate_for",
]
