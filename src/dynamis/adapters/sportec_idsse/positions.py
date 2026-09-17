"""Streaming canonicalization of the provider's 25 Hz positions XML.

Design (bounded memory is a hard requirement: the file is 372 MB / 3.36 M
frames and must never be materialized):

1. **Spill pass** - one ``lxml.iterparse`` pass with aggressive element clearing.
   Each ``FrameSet`` (one entity: player or ball, one period) is written to a
   small temporary Arrow IPC file as canonical ``tracking_sample`` columns plus a
   temporary ``source_frame`` column. Nothing but one batch is held in memory.
2. **Merge pass** - per period, the entity files are merged with a k-way heap
   ordered by ``(frame, object_id)`` so the canonical file is frame-major and
   ``t_rel_ns`` is non-decreasing, as the tracking contract requires. Entities
   that joined late (substitutes) are handled by the merge naturally.

Canonical frame/time mapping (verified by the discovery receipt and tests):

    t_rel_ns(frame) = timestamp_utc_ns - kickoff_utc_ns
    timestamp(N) = section_origin_timestamp + (N - section_origin_frame) * 40 ms

Rows that break the contract are quarantined with an explicit rule id; source
scalar movement attributes (``S`` km/h, ``A`` clipped at +/-7.99) are *not*
mapped because the canonical tracking contract has no scalar-movement field and
fabricating one would misrepresent the source (documented in the receipt).
"""

from __future__ import annotations

import heapq
import shutil
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import lxml.etree as etree
import pyarrow as pa
import pyarrow.ipc as ipc

from dynamis.adapters.sportec_idsse.authorities import (
    FRAME_INTERVAL_NS,
    tracking_stream_id,
)
from dynamis.adapters.sportec_idsse.matchinfo import BALL_TEAM_ID, IdsseMatchMetadata
from dynamis.contracts import TRACKING_SCHEMA, MeasurementClass, Modality
from dynamis.pipeline.quarantine import (
    RULE_COORDINATE_MISSING,
    RULE_COORDINATE_OUT_OF_RANGE,
    RULE_DUPLICATE_FRAME,
    RULE_FRAME_TIME_MISMATCH,
    RULE_REQUIRED_FIELD_NULL,
    RULE_TIMESTAMP_UNPARSABLE,
    QuarantinedRecord,
)
from dynamis.pipeline.streams import CanonicalStream

PERIOD_SECTIONS = {"firstHalf": "period-1", "secondHalf": "period-2"}
SPILL_SCHEMA = TRACKING_SCHEMA.append(pa.field("source_frame", pa.int64()))
FRAME_COLUMN_INDEX = TRACKING_SCHEMA.get_field_index("source_frame")
OBJECT_ID_COLUMN_INDEX = TRACKING_SCHEMA.get_field_index("object_id")
ROW_FRAME_TOLERANCE_NS = 1_000_000  # 1 ms

#: Slice size for the frame-major merge. The merge never materializes a full
#: entity batch as Python objects, so peak memory stays bounded by
#: ``merge_batch_size`` plus one slice per entity.
MERGE_SLICE_ROWS = 1_024
MERGE_BATCH_ROWS = 8_192


@dataclass(slots=True)
class EntitySpill:
    section: str
    team_id: str
    person_id: str
    object_type: str
    path: Path
    row_count: int = 0
    first_frame: int | None = None
    last_frame: int | None = None


@dataclass(slots=True)
class SectionSummary:
    section: str
    period_id: str
    frame_first: int
    frame_last: int
    entity_count: int
    source_frames: int = 0
    canonical_rows: int = 0
    ball_object_id: str | None = None

    @property
    def frame_count(self) -> int:
        if self.frame_first == 0 and self.frame_last == 0:
            return 0
        return self.frame_last - self.frame_first + 1


@dataclass(frozen=True, slots=True)
class PositionsSummary:
    source_frames: int
    canonical_rows: int
    quarantined_rows: int
    quarantined_by_rule: dict[str, int]
    entity_count: int
    sections: tuple[SectionSummary, ...]
    spill_dir: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_frames": self.source_frames,
            "canonical_rows": self.canonical_rows,
            "quarantined_rows": self.quarantined_rows,
            "quarantined_by_rule": self.quarantined_by_rule,
            "entity_count": self.entity_count,
            "sections": [
                {
                    "section": summary.section,
                    "period_id": summary.period_id,
                    "frame_first": summary.frame_first,
                    "frame_last": summary.frame_last,
                    "frame_count": summary.frame_count,
                    "source_frames": summary.source_frames,
                    "canonical_rows": summary.canonical_rows,
                    "entity_count": summary.entity_count,
                    "ball_object_id": summary.ball_object_id,
                }
                for summary in self.sections
            ],
        }


def _parse_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


class PositionsCanonicalizer:
    """Two-pass, bounded-memory canonicalizer for ``positions_raw_observed``."""

    def __init__(
        self,
        positions_path: Path,
        metadata: IdsseMatchMetadata,
        *,
        spill_dir: Path,
        batch_size: int,
        dataset_id: str,
        clock_id: str,
        synchronization_spec_id: str,
        coordinate_frame_id: str,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self._path = Path(positions_path)
        self._metadata = metadata
        self._spill_dir = Path(spill_dir)
        self._batch_size = batch_size
        self._dataset_id = dataset_id
        self._clock_id = clock_id
        self._synchronization_spec_id = synchronization_spec_id
        self._coordinate_frame_id = coordinate_frame_id
        self._spills: dict[str, dict[str, EntitySpill]] = {}
        self._summaries: dict[str, SectionSummary] = {}
        self._source_frames = 0
        self._quarantined: list[QuarantinedRecord] = []
        self._session_id = metadata.match_id

    # -- stage 1 ---------------------------------------------------------

    @property
    def spilled(self) -> bool:
        return bool(self._spills)

    def spill(self) -> PositionsSummary:
        """Parse the XML once, spilling every entity stream to Arrow IPC."""
        if self._spills:
            return self.summary()
        if self._spill_dir.exists():
            shutil.rmtree(self._spill_dir)
        self._spill_dir.mkdir(parents=True, exist_ok=True)
        kickoff_ns = int(self._metadata.kickoff_utc.timestamp() * 1_000_000_000)

        state: dict[str, Any] = {"spill": None, "writer": None, "sink": None, "rows": []}
        section_origin: dict[str, tuple[int, int]] = {}

        def flush() -> None:
            rows = state["rows"]
            writer = state["writer"]
            if rows and writer is not None:
                writer.write_batch(pa.RecordBatch.from_pylist(rows, schema=SPILL_SCHEMA))
                state["rows"] = []

        def close_entity() -> None:
            flush()
            if state["writer"] is not None:
                state["writer"].close()
                state["writer"] = None
            if state["sink"] is not None:
                state["sink"].close()
                state["sink"] = None

        context = etree.iterparse(
            str(self._path),
            events=("start", "end"),
            tag=("Frame", "FrameSet"),
        )
        for event, elem in context:
            if event == "start":
                if elem.tag == "FrameSet":
                    close_entity()
                    spill = self._open_entity(
                        section=str(elem.get("GameSection")),
                        team_id=str(elem.get("TeamId")),
                        person_id=str(elem.get("PersonId")),
                    )
                    state["spill"] = spill
                    state["sink"] = pa.OSFile(str(spill.path), "wb")
                    state["writer"] = ipc.new_stream(state["sink"], SPILL_SCHEMA)
                continue

            spill = state["spill"]
            if elem.tag != "Frame" or spill is None:
                pass
            else:
                row, error = self._canonicalize_frame(
                    elem,
                    spill,
                    kickoff_ns=kickoff_ns,
                    section_origin=section_origin,
                )
                self._source_frames += 1
                summary = self._summaries[spill.section]
                summary.source_frames += 1
                if row is None and error is not None:
                    self._quarantined.append(error)
                elif row is not None:
                    state["rows"].append(row)
                    spill.row_count += 1
                    summary.canonical_rows += 1
                    frame = int(row["source_frame"])
                    if spill.first_frame is None:
                        spill.first_frame = frame
                    spill.last_frame = frame
                    if summary.frame_first == 0 or frame < summary.frame_first:
                        summary.frame_first = frame
                    summary.frame_last = max(summary.frame_last, frame)
                    if len(state["rows"]) >= self._batch_size:
                        flush()
            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]

        close_entity()
        return self.summary()

    def _open_entity(self, *, section: str, team_id: str, person_id: str) -> EntitySpill:
        """Open a spill file for one ``FrameSet`` occurrence.

        A provider may emit more than one ``FrameSet`` for the same entity in a
        section; every occurrence gets its own file (the merge reads the whole
        section directory), so a later occurrence can never truncate the frames
        an earlier one already produced.
        """
        if section not in PERIOD_SECTIONS:
            raise ValueError(f"unsupported GameSection {section!r} in {self._path.name}")
        entities = self._spills.setdefault(section, {})
        occurrence = sum(1 for spill in entities.values() if spill.person_id == person_id)
        target = self._spill_dir / section / f"{person_id}.{occurrence}.arrow"
        target.parent.mkdir(parents=True, exist_ok=True)
        spill = EntitySpill(
            section=section,
            team_id=team_id,
            person_id=person_id,
            object_type="ball" if team_id == BALL_TEAM_ID else "player",
            path=target,
        )
        entities[f"{person_id}#{occurrence}"] = spill
        self._summaries.setdefault(
            section,
            SectionSummary(
                section=section,
                period_id=PERIOD_SECTIONS[section],
                frame_first=0,
                frame_last=0,
                entity_count=0,
                ball_object_id=person_id if team_id == BALL_TEAM_ID else None,
            ),
        )
        return spill

    def _canonicalize_frame(
        self,
        elem: etree._Element,
        spill: EntitySpill,
        *,
        kickoff_ns: int,
        section_origin: dict[str, tuple[int, int]],
    ) -> tuple[dict[str, Any] | None, QuarantinedRecord | None]:
        def quarantine(rule: str, detail: str, evidence: dict[str, Any]) -> QuarantinedRecord:
            return QuarantinedRecord(
                rule=rule,
                detail=detail,
                dataset_id=self._dataset_id,
                session_id=self._session_id,
                stream_id=tracking_stream_id(PERIOD_SECTIONS[spill.section]),
                subject_id=spill.person_id if spill.object_type == "player" else None,
                source_record_id=f"{spill.person_id}:{elem.get('N')}",
                source_time=elem.get("T"),
                evidence=evidence,
            )

        n_raw = elem.get("N")
        time_raw = elem.get("T")
        if n_raw is None:
            return None, quarantine(RULE_REQUIRED_FIELD_NULL, "Frame has no N", {})
        try:
            frame = int(n_raw)
        except ValueError:
            return None, quarantine(
                RULE_REQUIRED_FIELD_NULL, "Frame N is not an integer", {"N": n_raw}
            )
        if time_raw is None:
            return None, quarantine(RULE_REQUIRED_FIELD_NULL, "Frame has no T", {"N": frame})
        parsed = _parse_utc(time_raw)
        if parsed is None:
            return None, quarantine(
                RULE_TIMESTAMP_UNPARSABLE,
                "Frame T is not a timezone-aware ISO 8601 timestamp",
                {"T": time_raw},
            )
        origin = section_origin.get(spill.section)
        if origin is None:
            origin = (frame, int(parsed.timestamp() * 1_000_000_000))
            section_origin[spill.section] = origin
        expected_ns = origin[1] + (frame - origin[0]) * FRAME_INTERVAL_NS
        actual_ns = int(parsed.timestamp() * 1_000_000_000)
        if abs(expected_ns - actual_ns) > ROW_FRAME_TOLERANCE_NS:
            return None, quarantine(
                RULE_FRAME_TIME_MISMATCH,
                "frame counter and timestamp disagree by more than 1 ms",
                {"frame": frame, "expected_utc_ns": expected_ns, "actual_utc_ns": actual_ns},
            )
        if spill.last_frame is not None and frame <= spill.last_frame:
            return None, quarantine(
                RULE_DUPLICATE_FRAME,
                "frame number does not advance within the entity stream",
                {"frame": frame, "previous": spill.last_frame},
            )

        coordinates: dict[str, float] = {}
        for name in ("X", "Y"):
            raw = elem.get(name)
            if raw is None:
                return None, quarantine(
                    RULE_COORDINATE_MISSING,
                    f"Frame is missing required coordinate {name}",
                    {"frame": frame, "attribute": name},
                )
            try:
                coordinates[name] = float(raw)
            except ValueError:
                return None, quarantine(
                    RULE_COORDINATE_OUT_OF_RANGE,
                    f"coordinate {name} is not numeric",
                    {"frame": frame, "value": raw},
                )
        z_raw = elem.get("Z")
        z_m = float(z_raw) if z_raw is not None else None

        return (
            {
                "dataset_id": self._dataset_id,
                "session_id": self._session_id,
                "trial_id": PERIOD_SECTIONS[spill.section],
                "subject_id": spill.person_id if spill.object_type == "player" else None,
                "device_id": None,
                "stream_id": f"tracking-{PERIOD_SECTIONS[spill.section]}",
                "sample_index": -1,  # assigned by the frame-major merge
                "t_rel_ns": actual_ns - kickoff_ns,
                "timestamp_utc_ns": actual_ns,
                "nominal_sampling_rate_hz": 25.0,
                "measurement_class": MeasurementClass.RAW_MEASURED.value,
                "clock_id": self._clock_id,
                "synchronization_spec_id": self._synchronization_spec_id,
                "coordinate_frame_id": self._coordinate_frame_id,
                "object_id": spill.person_id,
                "object_type": spill.object_type,
                "group_id": None if spill.object_type == "ball" else spill.team_id,
                "x_m": coordinates["X"],
                "y_m": coordinates["Y"],
                "z_m": z_m,
                "vx_m_s": None,
                "vy_m_s": None,
                "vz_m_s": None,
                "ax_m_s2": None,
                "ay_m_s2": None,
                "az_m_s2": None,
                "is_detected": None,
                "confidence": None,
                "source_frame": frame,
            },
            None,
        )

    # -- stage 2 ---------------------------------------------------------

    def streams(
        self,
        *,
        session_id: str,
    ) -> tuple[CanonicalStream, ...]:
        """Frame-major canonical streams, one per period."""
        if not self._spills:
            raise RuntimeError("spill() must run before streams()")
        self._session_id = session_id
        streams: list[CanonicalStream] = []
        for section, summary in self._summaries.items():
            summary.entity_count = len(
                {spill.person_id for spill in self._spills.get(section, {}).values()}
            )
            streams.append(
                CanonicalStream(
                    dataset_id=self._dataset_id,
                    session_id=session_id,
                    stream_id=tracking_stream_id(summary.period_id),
                    modality=Modality.TRACKING,
                    measurement_class=MeasurementClass.RAW_MEASURED,
                    clock_id=self._clock_id,
                    synchronization_spec_id=self._synchronization_spec_id,
                    coordinate_frame_id=self._coordinate_frame_id,
                    trial_id=summary.period_id,
                    nominal_sampling_rate_hz=25.0,
                    stream_metadata={
                        "adapter": "sportec_idsse",
                        "source_file_key": self._path.name,
                        "game_section": section,
                        "entities": str(summary.entity_count),
                        "frame_major": "true",
                        "unmapped_attributes": "D,A,M (no published semantics)",
                    },
                    schema=TRACKING_SCHEMA,
                    batches=self._merged_batches(section),
                )
            )
        return tuple(streams)

    def _merged_batches(self, section: str) -> Iterator[pa.RecordBatch]:
        entities = sorted(
            self._spills[section].values(),
            key=lambda item: (item.person_id, item.path.name),
        )
        # Sequential stream reads keep the working set to the current buffer
        # instead of accumulating memory-mapped pages for every entity file.
        handles = [pa.OSFile(str(entity.path), "rb") for entity in entities]
        readers = [ipc.open_stream(handle) for handle in handles]
        try:
            iterators = [_entity_rows(reader) for reader in readers]
            merged = heapq.merge(
                *iterators,
                key=lambda row: (row[FRAME_COLUMN_INDEX], row[OBJECT_ID_COLUMN_INDEX]),
            )
            rows: list[tuple[Any, ...]] = []
            sample_index = 0
            for row in merged:
                rows.append(row)
                if len(rows) >= MERGE_BATCH_ROWS:
                    yield _batch_from_rows(rows, start=sample_index)
                    sample_index += len(rows)
                    rows = []
            if rows:
                yield _batch_from_rows(rows, start=sample_index)
        finally:
            del readers
            for handle in handles:
                handle.close()

    # -- receipts --------------------------------------------------------

    def summary(self) -> PositionsSummary:
        by_rule = Counter(record.rule for record in self._quarantined)
        return PositionsSummary(
            source_frames=self._source_frames,
            canonical_rows=sum(summary.canonical_rows for summary in self._summaries.values()),
            quarantined_rows=len(self._quarantined),
            quarantined_by_rule=dict(by_rule),
            entity_count=sum(
                len({spill.person_id for spill in entities.values()})
                for entities in self._spills.values()
            ),
            sections=tuple(self._summaries[section] for section in self._summaries),
            spill_dir=self._spill_dir,
        )

    def quarantined(self) -> tuple[QuarantinedRecord, ...]:
        return tuple(self._quarantined)

    def cleanup(self) -> None:
        if self._spill_dir.exists():
            shutil.rmtree(self._spill_dir, ignore_errors=True)


def _entity_rows(reader: ipc.RecordBatchReader) -> Iterator[tuple[Any, ...]]:
    """Row tuples from one entity stream, never materializing a whole batch."""
    for batch in reader:
        for start in range(0, batch.num_rows, MERGE_SLICE_ROWS):
            window = batch.slice(start, MERGE_SLICE_ROWS)
            columns = [
                window.column(position).to_pylist() for position in range(window.num_columns)
            ]
            yield from zip(*columns, strict=True)


def _batch_from_rows(rows: list[tuple[Any, ...]], *, start: int) -> pa.RecordBatch:
    columns = []
    for position, field in enumerate(TRACKING_SCHEMA):
        if field.name == "sample_index":
            values: list[Any] = list(range(start, start + len(rows)))
        else:
            values = [row[position] for row in rows]
        columns.append(pa.array(values, type=field.type))
    return pa.RecordBatch.from_arrays(columns, schema=TRACKING_SCHEMA)
