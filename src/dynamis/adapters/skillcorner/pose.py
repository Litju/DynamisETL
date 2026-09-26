"""SkillCorner 25 Hz body pose -> canonical ``pose_joint_sample`` streams.

The provider archive is a ZIP whose JSONL member is ~3.3 GB of plaintext. This
module never expands it: it streams the member line by line, keeps only bounded
batches in memory, and emits Arrow batches with exactly the declared 29-joint
landmark order. Player frames whose ``joints`` is null are explicit coverage
(they produce no rows and are counted), never imputed.

The same module provides the documented exact-coincidence V&V: pose frames that
satisfy ``pose_frame = 2.5 * tracking_frame`` are compared with their tracking
counterpart for timestamp equality, player-identity agreement and pose-vs-
tracking XY residual distribution. Residuals are reported, never corrected.
"""

from __future__ import annotations

import json
import math
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa

from dynamis.adapters.skillcorner.authorities import (
    ALIGNMENT_STATEMENT,
    CLOCK_ID,
    HYBRID_GEOMETRY_STATEMENT,
    POSE_ERROR_SEMANTICS,
    POSE_ERROR_SOURCE_FIELD,
    POSE_ERROR_SOURCE_TO_SI_SCALE,
    POSE_FRAME_ID,
    POSE_FRAME_RATE_HZ,
    POSE_LANDMARKS,
    POSE_SKELETON_ID,
    SKILLCORNER_DATASET_ID,
    SYNC_SPEC_ID,
    pose_stream_id,
)
from dynamis.adapters.skillcorner.metadata import (
    MatchPeriod,
    SkillCornerMatchMetadata,
)
from dynamis.adapters.skillcorner.tracking import match_time_ns
from dynamis.contracts import MeasurementClass, Modality, get_schema
from dynamis.contracts.sports import (
    DataGrain,
    DataGrainKind,
    SportsEntityKind,
    canonical_sports_id,
)
from dynamis.pipeline.quarantine import (
    RULE_NON_FINITE_VALUE,
    RULE_SCHEMA_FAILURE,
    RULE_TIMESTAMP_UNPARSABLE,
    RULE_UNKNOWN_PARTICIPANT,
    QuarantinedRecord,
)
from dynamis.pipeline.streams import DEFAULT_BATCH_SIZE, CanonicalStream

_LANDMARK_INDEX = {name: index for index, name in enumerate(POSE_LANDMARKS)}
_LANDMARK_COUNT = len(POSE_LANDMARKS)


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


def pose_zip_member(archive: zipfile.ZipFile, *, match_id: str) -> str:
    """Locate the pose JSONL member, refusing AppleDouble/metadata members."""
    candidates = [
        info.filename
        for info in archive.infolist()
        if info.filename.endswith(".jsonl")
        and not info.filename.startswith("__MACOSX/")
        and not Path(info.filename).name.startswith("._")
    ]
    if not candidates:
        raise ValueError(f"pose archive exposes no .jsonl member for match {match_id}")
    preferred = [name for name in candidates if match_id in Path(name).name]
    if len(preferred) == 1:
        return preferred[0]
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError(f"pose archive member is ambiguous for match {match_id}: {sorted(candidates)}")


@dataclass(slots=True)
class PosePeriodSummary:
    period: int
    stream_id: str
    source_frames: int = 0
    frames_with_pose: int = 0
    player_frames: int = 0
    player_frames_with_pose: int = 0
    declared_joint_records: int = 0
    observed_joints: int = 0
    unavailable_joints: int = 0
    malformed_joints: int = 0
    quarantined: list[QuarantinedRecord] = field(default_factory=list)
    error_min_m: float | None = None
    error_max_m: float | None = None
    error_observed: int = 0
    error_null: int = 0
    seen_player_ids: set[str] = field(default_factory=set)
    unknown_player_ids: set[str] = field(default_factory=set)
    first_t_rel_ns: int | None = None
    last_t_rel_ns: int | None = None

    @property
    def source_records(self) -> int:
        return self.declared_joint_records

    @property
    def canonical_rows(self) -> int:
        return self.observed_joints + self.unavailable_joints

    @property
    def quarantined_rows(self) -> int:
        return self.malformed_joints

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "stream_id": self.stream_id,
            "source_frames": self.source_frames,
            "frames_with_pose": self.frames_with_pose,
            "player_frames": self.player_frames,
            "player_frames_with_pose": self.player_frames_with_pose,
            "declared_joint_records": self.declared_joint_records,
            "observed_joints": self.observed_joints,
            "unavailable_joints": self.unavailable_joints,
            "malformed_joints": self.malformed_joints,
            "canonical_rows": self.canonical_rows,
            "error_observed": self.error_observed,
            "error_null": self.error_null,
            "error_min_m": self.error_min_m,
            "error_max_m": self.error_max_m,
            "observed_player_ids": len(self.seen_player_ids),
            "unknown_player_ids": sorted(self.unknown_player_ids)[:100],
            "unknown_player_id_count": len(self.unknown_player_ids),
            "first_t_rel_ns": self.first_t_rel_ns,
            "last_t_rel_ns": self.last_t_rel_ns,
        }


class PoseCanonicalizer:
    """Streams the SkillCorner pose archive member into per-period streams."""

    def __init__(
        self,
        zip_path: Path,
        metadata: SkillCornerMatchMetadata,
        *,
        dataset_id: str = SKILLCORNER_DATASET_ID,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._zip_path = Path(zip_path)
        self._metadata = metadata
        self._dataset_id = dataset_id
        self._batch_size = batch_size
        self._summaries: dict[int, PosePeriodSummary] = {}
        self._schema = get_schema(Modality.POSE)

    def summary(self, period: int) -> PosePeriodSummary:
        return self._summaries[period]

    def streams(self) -> tuple[CanonicalStream, ...]:
        return tuple(self.stream(period.period) for period in self._metadata.periods)

    def stream(self, period: int) -> CanonicalStream:
        period_record = self._metadata.period(period)
        if period_record is None:
            raise KeyError(f"match {self._metadata.match_id} declares no period {period}")
        summary = PosePeriodSummary(period=period, stream_id=pose_stream_id(period))
        self._summaries[period] = summary
        return CanonicalStream(
            dataset_id=self._dataset_id,
            session_id=self._metadata.session_id,
            stream_id=summary.stream_id,
            modality=Modality.POSE,
            measurement_class=MeasurementClass.MODEL_ESTIMATED,
            clock_id=CLOCK_ID,
            synchronization_spec_id=SYNC_SPEC_ID,
            trial_id=period_record.name,
            coordinate_frame_id=POSE_FRAME_ID,
            nominal_sampling_rate_hz=POSE_FRAME_RATE_HZ,
            source_unit="m",
            batches=self._batches(period_record, summary),
            schema=self._schema,
            stream_metadata={
                "adapter": "skillcorner_opendata",
                "contest_id": canonical_sports_id(
                    "skillcorner_opendata", SportsEntityKind.CONTEST, self._metadata.match_id
                ),
                "source_file_key": self._zip_path.name,
                "source_zip_member": self._metadata.match_id,
                "provider_product": "body pose (25 fps, 29 landmarks)",
                "landmark_order_authority": (
                    "data/bodypose/README.md at the pinned SkillCorner revision"
                ),
                "error_source_field": POSE_ERROR_SOURCE_FIELD,
                "error_source_to_si_scale": POSE_ERROR_SOURCE_TO_SI_SCALE,
                "error_semantics": POSE_ERROR_SEMANTICS,
                "geometry": "hybrid: pitch-global X/Y with centroid-relative Z",
                "hybrid_geometry_statement": HYBRID_GEOMETRY_STATEMENT,
                "alignment_statement": ALIGNMENT_STATEMENT,
                "missing_joint_policy": (
                    "player frames with joints=null produce no rows and remain explicit in "
                    "coverage counts; unavailable joints (source null xyz) are rows with "
                    "is_available=false and null coordinates; nothing is imputed"
                ),
            },
            grain=DataGrain(kind=DataGrainKind.JOINT_FRAME_SERIES),
        )

    def _quarantine(
        self,
        summary: PosePeriodSummary,
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

    def _batches(self, period: MatchPeriod, summary: PosePeriodSummary) -> Iterator[pa.RecordBatch]:
        rows: list[dict[str, Any]] = []
        sample_index = 0
        declared_periods = {item.period for item in self._metadata.periods}
        with zipfile.ZipFile(self._zip_path) as archive:
            member = pose_zip_member(archive, match_id=self._metadata.match_id)
            with archive.open(member) as stream:
                for line_number, raw in enumerate(stream):
                    payload = json.loads(raw)
                    frame = int(payload["frame"])
                    payload_period = payload.get("period")
                    players = payload.get("player_data") or []
                    if payload_period != period.period:
                        if (
                            payload_period not in declared_periods
                            and period.period == self._metadata.periods[0].period
                            and any(
                                isinstance(player, dict) and player.get("joints") is not None
                                for player in players
                            )
                        ):
                            # A posed frame whose period matches no declared stream
                            # cannot be assigned canonically; it is quarantined once,
                            # by the first period stream, never silently dropped.
                            for player in players:
                                if not isinstance(player, dict) or player.get("joints") is None:
                                    continue
                                joints = player["joints"]
                                declared = (
                                    len(joints) if isinstance(joints, dict) else _LANDMARK_COUNT
                                )
                                summary.declared_joint_records += declared
                                summary.malformed_joints += declared
                                self._quarantine(
                                    summary,
                                    rule=RULE_SCHEMA_FAILURE,
                                    detail=(
                                        f"posed frame declares undeclared period {payload_period!r}"
                                    ),
                                    source_record_id=f"frame={frame}",
                                    subject_id=(
                                        None
                                        if player.get("player_id") is None
                                        else str(player.get("player_id"))
                                    ),
                                )
                        continue
                    summary.source_frames += 1
                    timestamp = payload.get("timestamp")
                    summary.player_frames += len(players)
                    if any(
                        isinstance(player, dict) and player.get("joints") is not None
                        for player in players
                    ):
                        summary.frames_with_pose += 1
                    try:
                        t_rel_ns = match_time_ns(timestamp)
                    except ValueError as exc:
                        for player in players:
                            subject_id = None
                            joints = None
                            if isinstance(player, dict):
                                subject_id = (
                                    None
                                    if player.get("player_id") is None
                                    else str(player.get("player_id"))
                                )
                                joints = player.get("joints")
                            declared = len(joints) if isinstance(joints, dict) else _LANDMARK_COUNT
                            summary.declared_joint_records += declared
                            summary.malformed_joints += declared
                            self._quarantine(
                                summary,
                                rule=RULE_TIMESTAMP_UNPARSABLE,
                                detail=str(exc),
                                source_record_id=f"line={line_number}",
                                subject_id=subject_id,
                                source_time=None if timestamp is None else str(timestamp),
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
                    for player in players:
                        emitted = self._player_rows(
                            player, summary, period, frame, line_number, timestamp, t_rel_ns
                        )
                        for row in emitted:
                            sample_index = self._append(rows, row, sample_index)
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

    def _player_rows(
        self,
        player: object,
        summary: PosePeriodSummary,
        period: MatchPeriod,
        frame: int,
        line_number: int,
        timestamp: object,
        t_rel_ns: int,
    ) -> list[dict[str, Any]]:
        if not isinstance(player, dict):
            summary.declared_joint_records += _LANDMARK_COUNT
            summary.malformed_joints += _LANDMARK_COUNT
            self._quarantine(
                summary,
                rule=RULE_SCHEMA_FAILURE,
                detail="pose player entry is not an object",
                source_record_id=f"line={line_number}",
            )
            return []
        joints = player.get("joints")
        if joints is None:
            # Explicit coverage: the provider resolved no pose for this player
            # frame. No rows are fabricated and no joints are counted as source
            # joint records.
            return []
        summary.player_frames_with_pose += 1
        subject_id = None if player.get("player_id") is None else str(player.get("player_id"))
        if not isinstance(joints, dict):
            summary.declared_joint_records += _LANDMARK_COUNT
            summary.malformed_joints += _LANDMARK_COUNT
            self._quarantine(
                summary,
                rule=RULE_SCHEMA_FAILURE,
                detail="pose joints is neither null nor a landmark mapping",
                source_record_id=f"frame={frame}",
                subject_id=subject_id,
                source_time=None if timestamp is None else str(timestamp),
            )
            return []
        if subject_id is None or self._metadata.player(subject_id) is None:
            if subject_id is not None:
                summary.unknown_player_ids.add(subject_id)
            summary.declared_joint_records += len(joints)
            summary.malformed_joints += len(joints)
            self._quarantine(
                summary,
                rule=RULE_UNKNOWN_PARTICIPANT,
                detail="pose player id is not a declared participant",
                source_record_id=f"frame={frame}",
                subject_id=subject_id,
                source_time=None if timestamp is None else str(timestamp),
            )
            return []
        summary.seen_player_ids.add(subject_id)
        declared = len(joints) + sum(1 for name in POSE_LANDMARKS if name not in joints)
        summary.declared_joint_records += declared
        rows: list[dict[str, Any]] = []
        for name in joints:
            if name not in _LANDMARK_INDEX:
                summary.malformed_joints += 1
                self._quarantine(
                    summary,
                    rule=RULE_SCHEMA_FAILURE,
                    detail=f"landmark {name!r} is outside the published 29-landmark authority",
                    source_record_id=f"frame={frame}",
                    subject_id=subject_id,
                    source_time=None if timestamp is None else str(timestamp),
                )
        for name in POSE_LANDMARKS:
            if name not in joints:
                summary.malformed_joints += 1
                self._quarantine(
                    summary,
                    rule=RULE_SCHEMA_FAILURE,
                    detail=f"published landmark {name!r} is absent from the source mapping",
                    source_record_id=f"frame={frame}",
                    subject_id=subject_id,
                    source_time=None if timestamp is None else str(timestamp),
                )
                continue
            row = self._joint_row(
                name,
                joints[name],
                summary,
                period,
                frame,
                subject_id,
                timestamp,
                t_rel_ns,
            )
            if row is not None:
                rows.append(row)
        return rows

    def _joint_row(
        self,
        name: str,
        value: object,
        summary: PosePeriodSummary,
        period: MatchPeriod,
        frame: int,
        subject_id: str,
        timestamp: object,
        t_rel_ns: int,
    ) -> dict[str, Any] | None:
        unavailable = value is None
        xyz: list[Any] = [None, None, None]
        p90 = None
        if value is not None and not isinstance(value, dict):
            self._malformed_joint(
                summary,
                name,
                frame,
                subject_id,
                timestamp,
                "landmark value is neither null nor an object",
                rule=RULE_SCHEMA_FAILURE,
            )
            return None
        if isinstance(value, dict):
            p90 = value.get(POSE_ERROR_SOURCE_FIELD)
            raw_xyz = value.get("xyz")
            if isinstance(raw_xyz, list) and len(raw_xyz) == 3:
                xyz = list(raw_xyz)
            elif raw_xyz is not None:
                self._malformed_joint(
                    summary,
                    name,
                    frame,
                    subject_id,
                    timestamp,
                    "xyz is not a 3-element list",
                    rule=RULE_SCHEMA_FAILURE,
                )
                return None
            if all(component is None for component in xyz):
                unavailable = True
            elif any(component is None for component in xyz):
                self._malformed_joint(
                    summary,
                    name,
                    frame,
                    subject_id,
                    timestamp,
                    "xyz mixes null and non-null components",
                    rule=RULE_SCHEMA_FAILURE,
                )
                return None
            elif not all(_finite_number(component) for component in xyz):
                self._malformed_joint(
                    summary,
                    name,
                    frame,
                    subject_id,
                    timestamp,
                    "xyz is non-finite",
                    rule=RULE_NON_FINITE_VALUE,
                )
                return None
        error_m: float | None = None
        if p90 is not None:
            if not _finite_number(p90) or float(p90) < 0:
                self._malformed_joint(
                    summary,
                    name,
                    frame,
                    subject_id,
                    timestamp,
                    f"{POSE_ERROR_SOURCE_FIELD} is non-finite or negative",
                    rule=RULE_NON_FINITE_VALUE,
                )
                return None
            error_m = float(p90) * POSE_ERROR_SOURCE_TO_SI_SCALE
            summary.error_observed += 1
            summary.error_min_m = (
                error_m if summary.error_min_m is None else min(summary.error_min_m, error_m)
            )
            summary.error_max_m = (
                error_m if summary.error_max_m is None else max(summary.error_max_m, error_m)
            )
        elif not unavailable:
            summary.error_null += 1
        row: dict[str, Any] = {
            "dataset_id": self._dataset_id,
            "session_id": self._metadata.session_id,
            "trial_id": period.name,
            "subject_id": subject_id,
            "device_id": None,
            "stream_id": pose_stream_id(period.period),
            "sample_index": 0,
            "t_rel_ns": t_rel_ns,
            "timestamp_utc_ns": None,
            "nominal_sampling_rate_hz": POSE_FRAME_RATE_HZ,
            "measurement_class": MeasurementClass.MODEL_ESTIMATED.value,
            "clock_id": CLOCK_ID,
            "synchronization_spec_id": SYNC_SPEC_ID,
            "coordinate_frame_id": POSE_FRAME_ID,
            "skeleton_id": POSE_SKELETON_ID,
            "joint_id": _LANDMARK_INDEX[name],
            "joint_name": name,
            "parent_joint_id": None,
            "is_available": not unavailable,
            "x_m": None if unavailable else _as_float(xyz[0]),
            "y_m": None if unavailable else _as_float(xyz[1]),
            "z_m": None if unavailable else _as_float(xyz[2]),
            "confidence": None,
            "error_m": error_m,
            "is_occluded": None,
        }
        if unavailable:
            summary.unavailable_joints += 1
        else:
            summary.observed_joints += 1
        return row

    def _malformed_joint(
        self,
        summary: PosePeriodSummary,
        name: str,
        frame: int,
        subject_id: str,
        timestamp: object,
        detail: str,
        *,
        rule: str = RULE_SCHEMA_FAILURE,
    ) -> None:
        summary.malformed_joints += 1
        self._quarantine(
            summary,
            rule=rule,
            detail=f"landmark {name!r}: {detail}",
            source_record_id=f"frame={frame}",
            subject_id=subject_id,
            source_time=None if timestamp is None else str(timestamp),
        )


# ---------------------------------------------------------------------------
# Documented exact-coincidence V&V (pose <-> tracking)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CoincidenceReport:
    """V&V evidence at documented exact coincidences; corrections are never made."""

    coincident_frame_pairs: int
    timestamp_matches: int
    timestamp_mismatches: int
    timestamp_mismatch_examples: tuple[dict[str, Any], ...]
    matched_player_observations: int
    pose_only_player_observations: int
    tracking_only_player_observations: int
    xy_residual_count: int
    xy_residual_mean_m: float | None
    xy_residual_median_m: float | None
    xy_residual_p90_m: float | None
    xy_residual_max_m: float | None
    per_period: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "relation": "pose_frame = 2.5 * tracking_frame",
            "coincident_frame_pairs": self.coincident_frame_pairs,
            "timestamp_matches": self.timestamp_matches,
            "timestamp_mismatches": self.timestamp_mismatches,
            "timestamp_mismatch_examples": list(self.timestamp_mismatch_examples),
            "matched_player_observations": self.matched_player_observations,
            "pose_only_player_observations": self.pose_only_player_observations,
            "tracking_only_player_observations": self.tracking_only_player_observations,
            "xy_residual_count": self.xy_residual_count,
            "xy_residual_mean_m": self.xy_residual_mean_m,
            "xy_residual_median_m": self.xy_residual_median_m,
            "xy_residual_p90_m": self.xy_residual_p90_m,
            "xy_residual_max_m": self.xy_residual_max_m,
            "correction_applied": False,
            "per_period": self.per_period,
        }


def _iter_tracking_frames(path: Path) -> Iterator[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as handle:
        for raw in handle:
            payload = json.loads(raw)
            yield payload


def analyse_coincidences(
    *,
    pose_zip_path: Path,
    tracking_path: Path,
    match_id: str,
    timestamp_mismatch_examples: int = 5,
) -> CoincidenceReport:
    """Stream both sources in lockstep and quantify exact coincidences.

    Constant memory over the whole match: only per-period counters and the
    bounded XY-residual vector are retained, and no pose coordinate is ever
    rewritten from tracking (or vice versa).
    """
    tracking_iterator = _iter_tracking_frames(tracking_path)
    current = next(tracking_iterator, None)

    residuals: list[float] = []
    pairs = matches = mismatches = 0
    examples: list[dict[str, Any]] = []
    matched_players = pose_only = tracking_only = 0
    per_period: dict[str, dict[str, Any]] = {}

    def period_bucket(period: object) -> dict[str, Any]:
        key = "unknown" if period is None else str(period)
        return per_period.setdefault(
            key,
            {
                "coincident_frame_pairs": 0,
                "timestamp_matches": 0,
                "timestamp_mismatches": 0,
                "matched_player_observations": 0,
                "pose_only_player_observations": 0,
                "tracking_only_player_observations": 0,
                "xy_residual_count": 0,
            },
        )

    with zipfile.ZipFile(pose_zip_path) as archive:
        member = pose_zip_member(archive, match_id=match_id)
        with archive.open(member) as stream:
            for raw in stream:
                payload = json.loads(raw)
                frame = int(payload["frame"])
                if frame % 5:
                    continue
                target = frame * 2 // 5
                while current is not None and int(current["frame"]) < target:
                    current = next(tracking_iterator, None)
                if current is None:
                    break
                if int(current["frame"]) != target:
                    continue
                pose_period = payload.get("period")
                tracking_period = current.get("period")
                if pose_period is None or tracking_period is None:
                    continue
                bucket = period_bucket(pose_period)
                pairs += 1
                bucket["coincident_frame_pairs"] += 1
                pose_timestamp = payload.get("timestamp")
                tracking_timestamp = current.get("timestamp")
                if pose_timestamp == tracking_timestamp:
                    matches += 1
                    bucket["timestamp_matches"] += 1
                else:
                    mismatches += 1
                    bucket["timestamp_mismatches"] += 1
                    if len(examples) < timestamp_mismatch_examples:
                        examples.append(
                            {
                                "pose_frame": frame,
                                "tracking_frame": target,
                                "pose_timestamp": pose_timestamp,
                                "tracking_timestamp": tracking_timestamp,
                            }
                        )
                pose_positions = {
                    str(player["player_id"]): (player.get("x"), player.get("y"))
                    for player in payload.get("player_data") or []
                    if isinstance(player, dict) and player.get("player_id") is not None
                }
                tracking_positions = {
                    str(player["player_id"]): (player.get("x"), player.get("y"))
                    for player in current.get("player_data") or []
                    if isinstance(player, dict) and player.get("player_id") is not None
                }
                shared = set(pose_positions) & set(tracking_positions)
                matched_players += len(shared)
                bucket["matched_player_observations"] += len(shared)
                pose_only_count = len(set(pose_positions) - set(tracking_positions))
                tracking_only_count = len(set(tracking_positions) - set(pose_positions))
                pose_only += pose_only_count
                tracking_only += tracking_only_count
                bucket["pose_only_player_observations"] += pose_only_count
                bucket["tracking_only_player_observations"] += tracking_only_count
                for player_id in shared:
                    px, py = pose_positions[player_id]
                    tx, ty = tracking_positions[player_id]
                    if not all(_finite_number(v) for v in (px, py, tx, ty)):
                        continue
                    residual = math.hypot(
                        _as_float(px) - _as_float(tx), _as_float(py) - _as_float(ty)
                    )
                    residuals.append(residual)
                    bucket["xy_residual_count"] += 1

    residual_array = np.asarray(residuals, dtype=np.float64)
    return CoincidenceReport(
        coincident_frame_pairs=pairs,
        timestamp_matches=matches,
        timestamp_mismatches=mismatches,
        timestamp_mismatch_examples=tuple(examples),
        matched_player_observations=matched_players,
        pose_only_player_observations=pose_only,
        tracking_only_player_observations=tracking_only,
        xy_residual_count=int(residual_array.size),
        xy_residual_mean_m=(float(np.mean(residual_array)) if residual_array.size else None),
        xy_residual_median_m=(float(np.median(residual_array)) if residual_array.size else None),
        xy_residual_p90_m=(
            float(np.quantile(residual_array, 0.9)) if residual_array.size else None
        ),
        xy_residual_max_m=(float(np.max(residual_array)) if residual_array.size else None),
        per_period=per_period,
    )


__all__ = [
    "CoincidenceReport",
    "PoseCanonicalizer",
    "PosePeriodSummary",
    "analyse_coincidences",
    "pose_zip_member",
]
