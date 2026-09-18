"""Women's Soccer Positioning workbook adapter: sheets -> canonical GNSS streams.

Mapping (derived from the verified workbook discovery, never from memory):

* one canonical ``gnss_sample`` stream per sheet; the sheet name is the provider
  athlete identifier (``wsp-<sheet>`` as the dataset-scoped subject id);
* ``local_time`` is provider local wall-clock text (``%Y-%m-%d %H:%M:%S.%f``);
  ``t_rel_ns`` is measured from the earliest accepted sample of the workbook and
  ``timestamp_utc_ns`` is null because no UTC truth exists upstream;
* ``latitude``/``longitude`` are geographic GNSS degrees passed through
  unchanged; the provider does **not** explicitly declare the geodetic datum, so
  WGS 84 is the canonical interpretation (an inferred pipeline assumption)
  recorded on the frame, the stream metadata and the reconciliation receipt;
* ``speed(km/h)`` is converted to SI m/s with the exact scale 1/3.6;
* ``hr(bpm)`` has no canonical GNSS destination in V1 and is reported as an
  unmapped column (all values are null in the verified workbook).

Rows that cannot satisfy the canonical contract are quarantined with an explicit
rule id, never dropped silently.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import openpyxl
import pyarrow as pa

from dynamis.adapters.womens_soccer_positioning import authorities
from dynamis.adapters.womens_soccer_positioning.discovery import (
    SOURCE_COLUMNS,
    UNMAPPED_COLUMNS,
    WorkbookDiscovery,
    parse_source_timestamp,
)
from dynamis.contracts import (
    GNSS_SCHEMA,
    AlgorithmKind,
    AlgorithmSpec,
    MeasurementClass,
    Modality,
    ParticipantRole,
    SensorStream,
    Session,
    SessionKind,
    SessionParticipant,
    Subject,
)
from dynamis.pipeline.quarantine import (
    RULE_COORDINATE_OUT_OF_RANGE,
    RULE_NON_FINITE_VALUE,
    RULE_REQUIRED_FIELD_NULL,
    RULE_TIME_OUT_OF_RANGE,
    RULE_TIMESTAMP_UNPARSABLE,
    QuarantinedRecord,
)
from dynamis.pipeline.streams import (
    DEFAULT_BATCH_SIZE,
    CanonicalStream,
    ProviderDomain,
    SourceAuthorities,
)

WOMENS_DATASET_ID = authorities.WOMENS_DATASET_ID
WOMENS_VERSION = authorities.WOMENS_VERSION
WOMENS_SESSION_ID = authorities.WOMENS_SESSION_ID

#: The single accepted workbook for RES-97.
WORKBOOK_KEY_J01 = "J01.xlsx"

#: Datum provenance recorded on every canonical stream and receipt: the source
#: publishes geographic GNSS coordinates without declaring a datum, so WGS 84 is
#: an explicit pipeline inference, never presented as provider truth.
DATUM_PROVENANCE: dict[str, str] = {
    "source_coordinate_representation": authorities.SOURCE_COORDINATE_REPRESENTATION,
    "source_datum": authorities.SOURCE_DATUM_DECLARATION,
    "canonical_datum": authorities.CANONICAL_DATUM,
    "datum_authority": authorities.DATUM_AUTHORITY,
}


def adapter_algorithm_spec() -> AlgorithmSpec:
    """Deterministic algorithm identity for the Women's workbook adapter."""
    return AlgorithmSpec(
        algorithm_id="womens_soccer_positioning_adapter",
        name="Women's Soccer Positioning anti-corruption adapter",
        version="1",
        kind=AlgorithmKind.ADAPTER,
        description=(
            "Streams the verified J01 workbook into canonical gnss_sample streams "
            "with SI-unit speed, the WGS 84 canonical frame (source datum not "
            "explicitly declared) and session-monotonic time."
        ),
    )


_LATITUDE_INDEX = SOURCE_COLUMNS.index("latitude")
_LONGITUDE_INDEX = SOURCE_COLUMNS.index("longitude")
_SPEED_INDEX = SOURCE_COLUMNS.index("speed(km/h)")
_TIME_INDEX = SOURCE_COLUMNS.index("local_time")

NULLABLE_PAYLOAD: dict[str, Any] = {
    "ellipsoidal_height_m": None,
    "ecef_x_m": None,
    "ecef_y_m": None,
    "ecef_z_m": None,
    "course_deg": None,
    "horizontal_accuracy_m": None,
    "vertical_accuracy_m": None,
    "hdop": None,
    "satellites_used": None,
    "fix_type": None,
    "quality_flag": None,
}


@dataclass(slots=True)
class SheetCounters:
    source_rows: int = 0
    canonical_rows: int = 0
    quarantined: list[QuarantinedRecord] = field(default_factory=list)
    first_source_time: str | None = None
    last_source_time: str | None = None
    first_t_rel_ns: int | None = None
    last_t_rel_ns: int | None = None


@dataclass(frozen=True, slots=True)
class WomenSubjectStream:
    """One sheet projected onto a canonical stream plus its source counters."""

    sheet_name: str
    subject_id: str
    stream_id: str
    row_count: int
    nominal_rate_hz: float
    first_timestamp: str
    last_timestamp: str


def subject_id_for_sheet(sheet_name: str) -> str:
    return f"wsp-{sheet_name}"


def stream_id_for_sheet(sheet_name: str) -> str:
    return f"gnss-{sheet_name}"


def relative_ns(later: datetime, origin: datetime) -> int:
    """Integer nanoseconds between two provider-local datetimes.

    The workbook timestamps are naive local wall-clock values. Subtracting them
    directly avoids re-interpreting them in the host timezone (which a DST
    transition or a ``timestamp()`` float round-trip could shift) and yields
    exact integer nanoseconds.
    """
    delta = later - origin
    return (
        delta.days * 86_400_000_000_000 + delta.seconds * 1_000_000_000 + delta.microseconds * 1_000
    )


class WomenWorkbookAdapter:
    """Streaming anti-corruption layer for verified ``J01.xlsx`` workbooks."""

    def __init__(self, workbook_path: Path, discovery: WorkbookDiscovery) -> None:
        self._path = Path(workbook_path)
        self._discovery = discovery
        if not discovery.header_consistent:
            raise ValueError("workbook header is not the discovered canonical header set")
        if not discovery.sheet_names:
            raise ValueError("workbook discovery reported no sheets")
        self._counters: dict[str, SheetCounters] = {}

    @property
    def discovery(self) -> WorkbookDiscovery:
        return self._discovery

    @property
    def session_origin(self) -> datetime:
        """Earliest parseable timestamp in the workbook (deterministic anchor)."""
        origins: list[datetime] = []
        for sheet in self._discovery.sheets:
            if sheet.first_timestamp is None:
                continue
            parsed = parse_source_timestamp(sheet.first_timestamp)
            if parsed is not None:
                origins.append(parsed)
        if not origins:
            raise ValueError("workbook discovery reported no parseable timestamps")
        return min(origins)

    def source_authorities(self) -> SourceAuthorities:
        origin = self.session_origin
        return SourceAuthorities(
            frames=(authorities.wgs84_frame(),),
            clocks=(authorities.local_clock(origin_local=origin.isoformat(sep=" ")),),
            synchronizations=(authorities.source_sync_spec(),),
        )

    def subject_streams(self) -> tuple[WomenSubjectStream, ...]:
        return tuple(
            WomenSubjectStream(
                sheet_name=sheet.name,
                subject_id=subject_id_for_sheet(sheet.name),
                stream_id=stream_id_for_sheet(sheet.name),
                row_count=sheet.row_count,
                nominal_rate_hz=sheet.nominal_rate_hz or authorities.NOMINAL_RATE_HZ,
                first_timestamp=sheet.first_timestamp or "",
                last_timestamp=sheet.last_timestamp or "",
            )
            for sheet in self._discovery.sheets
            if sheet.first_timestamp is not None
            and parse_source_timestamp(sheet.first_timestamp) is not None
        )

    def canonical_stream(self, subject: WomenSubjectStream) -> CanonicalStream:
        return CanonicalStream(
            dataset_id=WOMENS_DATASET_ID,
            session_id=WOMENS_SESSION_ID,
            stream_id=subject.stream_id,
            modality=Modality.GNSS,
            measurement_class=MeasurementClass.RAW_MEASURED,
            clock_id=authorities.CLOCK_ID,
            synchronization_spec_id=authorities.SYNC_SPEC_ID,
            coordinate_frame_id=authorities.WGS84_FRAME_ID,
            subject_id=subject.subject_id,
            nominal_sampling_rate_hz=subject.nominal_rate_hz,
            source_unit=authorities.SPEED_SOURCE_UNIT,
            stream_metadata={
                "adapter": "womens_soccer_positioning",
                "provider_sheet": subject.sheet_name,
                "source_file_key": "J01.xlsx",
                "source_time_representation": "provider local wall-clock text",
                "speed_source_unit": authorities.SPEED_SOURCE_UNIT,
                "speed_source_to_si_scale": authorities.SPEED_SOURCE_TO_SI_SCALE,
                "unmapped_columns": ",".join(UNMAPPED_COLUMNS),
                **DATUM_PROVENANCE,
            },
            schema=GNSS_SCHEMA,
            batches=self._batches_for_sheet(subject),
        )

    def counters(self, sheet_name: str) -> SheetCounters:
        return self._counters.get(sheet_name, SheetCounters())

    def domain(self) -> ProviderDomain:
        """Canonical domain records derived from workbook truth.

        No UTC anchors exist upstream, so the session carries no timestamps; the
        local-clock origin lives in the clock notes and session metadata.
        """
        subjects = tuple(
            Subject(
                dataset_id=WOMENS_DATASET_ID,
                subject_id=subject_id_for_sheet(sheet.name),
                sex="female",
                cohort="2023/2024 Spanish third category",
                notes=f"provider sheet {sheet.name}",
            )
            for sheet in self._discovery.sheets
        )
        participants = tuple(
            SessionParticipant(
                dataset_id=WOMENS_DATASET_ID,
                session_id=WOMENS_SESSION_ID,
                subject_id=subject.subject_id,
                role=ParticipantRole.PLAYER,
            )
            for subject in subjects
        )
        streams = tuple(
            SensorStream(
                dataset_id=WOMENS_DATASET_ID,
                session_id=WOMENS_SESSION_ID,
                stream_id=subject.stream_id,
                modality=Modality.GNSS,
                measurement_class=MeasurementClass.RAW_MEASURED,
                clock_id=authorities.CLOCK_ID,
                synchronization_spec_id=authorities.SYNC_SPEC_ID,
                coordinate_frame_id=authorities.WGS84_FRAME_ID,
                subject_id=subject.subject_id,
                nominal_sampling_rate_hz=subject.nominal_rate_hz,
                si_units=("deg", "m", "m/s", "1"),
                source_unit=authorities.SPEED_SOURCE_UNIT,
                stream_metadata={
                    "source_file_key": WORKBOOK_KEY_J01,
                    "provider_sheet": subject.sheet_name,
                    **DATUM_PROVENANCE,
                },
            )
            for subject in self.subject_streams()
        )
        return ProviderDomain(
            session=Session(
                dataset_id=WOMENS_DATASET_ID,
                session_id=WOMENS_SESSION_ID,
                kind=SessionKind.MATCH,
                label="2023/2024 matchday J01",
            ),
            subjects=subjects,
            participants=participants,
            trials=(),
            streams=streams,
            authorities=self.source_authorities(),
            session_metadata={
                "workbook_key": WORKBOOK_KEY_J01,
                "sheet_count": len(self._discovery.sheet_names),
                "session_origin_local": self.session_origin.isoformat(sep=" "),
                "time_representation": "provider local wall-clock text (no timezone declared)",
                "license": "CC-BY-NC-4.0 (local use only for this project slice)",
            },
        )

    def _batches_for_sheet(self, subject: WomenSubjectStream) -> Iterator[pa.RecordBatch]:
        counters = SheetCounters()
        self._counters[subject.sheet_name] = counters
        origin = self.session_origin
        workbook = openpyxl.load_workbook(self._path, read_only=True, data_only=True)
        try:
            worksheet = workbook[subject.sheet_name]
            rows: list[dict[str, Any]] = []
            previous_parsed: datetime | None = None
            for position, row in enumerate(worksheet.iter_rows(values_only=True)):
                if position == 0:
                    continue
                counters.source_rows += 1
                record = self._canonicalize_row(
                    row,
                    subject,
                    origin=origin,
                    previous_parsed=previous_parsed,
                    counters=counters,
                )
                if record is None:
                    continue
                previous_parsed = record.pop("_parsed_time")
                rows.append(record)
                if len(rows) >= DEFAULT_BATCH_SIZE:
                    yield pa.RecordBatch.from_pylist(rows, schema=GNSS_SCHEMA)
                    rows = []
            if rows:
                yield pa.RecordBatch.from_pylist(rows, schema=GNSS_SCHEMA)
        finally:
            workbook.close()

    def _canonicalize_row(
        self,
        row: tuple[Any, ...],
        subject: WomenSubjectStream,
        *,
        origin: datetime,
        previous_parsed: datetime | None,
        counters: SheetCounters,
    ) -> dict[str, Any] | None:
        def value(index: int) -> Any:
            return row[index] if index < len(row) else None

        raw_time = value(_TIME_INDEX)
        parsed = parse_source_timestamp(raw_time)
        if parsed is None:
            counters.quarantined.append(
                QuarantinedRecord(
                    rule=RULE_TIMESTAMP_UNPARSABLE,
                    detail="local_time is not in the provider YYYY-MM-DD HH:MM:SS.sss format",
                    dataset_id=WOMENS_DATASET_ID,
                    session_id=WOMENS_SESSION_ID,
                    stream_id=subject.stream_id,
                    subject_id=subject.subject_id,
                    source_record_id=f"{subject.sheet_name}:row-{counters.source_rows}",
                    source_time=str(raw_time),
                    evidence={"expected_format": "YYYY-MM-DD HH:MM:SS.sss"},
                )
            )
            return None
        if previous_parsed is not None and parsed <= previous_parsed:
            counters.quarantined.append(
                QuarantinedRecord(
                    rule=RULE_TIME_OUT_OF_RANGE,
                    detail=(
                        "timestamp does not advance within the sheet; a canonical stream "
                        "requires strictly increasing source time"
                    ),
                    dataset_id=WOMENS_DATASET_ID,
                    session_id=WOMENS_SESSION_ID,
                    stream_id=subject.stream_id,
                    subject_id=subject.subject_id,
                    source_record_id=f"{subject.sheet_name}:row-{counters.source_rows}",
                    source_time=str(raw_time),
                    evidence={"previous": previous_parsed.isoformat()},
                )
            )
            return None

        latitude = value(_LATITUDE_INDEX)
        longitude = value(_LONGITUDE_INDEX)
        if latitude is None or longitude is None:
            counters.quarantined.append(
                QuarantinedRecord(
                    rule=RULE_REQUIRED_FIELD_NULL,
                    detail="latitude/longitude are mandatory in the canonical GNSS contract",
                    dataset_id=WOMENS_DATASET_ID,
                    session_id=WOMENS_SESSION_ID,
                    stream_id=subject.stream_id,
                    subject_id=subject.subject_id,
                    source_record_id=f"{subject.sheet_name}:row-{counters.source_rows}",
                    source_time=str(raw_time),
                    evidence={"latitude": latitude, "longitude": longitude},
                )
            )
            return None
        try:
            latitude_f, longitude_f = float(latitude), float(longitude)
        except (TypeError, ValueError):
            counters.quarantined.append(
                QuarantinedRecord(
                    rule=RULE_COORDINATE_OUT_OF_RANGE,
                    detail="latitude/longitude cell is not numeric",
                    dataset_id=WOMENS_DATASET_ID,
                    session_id=WOMENS_SESSION_ID,
                    stream_id=subject.stream_id,
                    subject_id=subject.subject_id,
                    source_record_id=f"{subject.sheet_name}:row-{counters.source_rows}",
                    source_time=str(raw_time),
                    evidence={"latitude": str(latitude), "longitude": str(longitude)},
                )
            )
            return None
        if not (-90.0 <= latitude_f <= 90.0) or not (-180.0 <= longitude_f <= 180.0):
            counters.quarantined.append(
                QuarantinedRecord(
                    rule=RULE_COORDINATE_OUT_OF_RANGE,
                    detail="geodetic coordinate outside the WGS 84 degree domain",
                    dataset_id=WOMENS_DATASET_ID,
                    session_id=WOMENS_SESSION_ID,
                    stream_id=subject.stream_id,
                    subject_id=subject.subject_id,
                    source_record_id=f"{subject.sheet_name}:row-{counters.source_rows}",
                    source_time=str(raw_time),
                    evidence={"latitude": latitude_f, "longitude": longitude_f},
                )
            )
            return None

        speed_raw = value(_SPEED_INDEX)
        speed_m_s: float | None = None
        if speed_raw is not None:
            try:
                speed_value = float(speed_raw)
            except (TypeError, ValueError):
                speed_value = float("nan")
            if not math.isfinite(speed_value):
                counters.quarantined.append(
                    QuarantinedRecord(
                        rule=RULE_NON_FINITE_VALUE,
                        detail="speed cell is not a finite number",
                        dataset_id=WOMENS_DATASET_ID,
                        session_id=WOMENS_SESSION_ID,
                        stream_id=subject.stream_id,
                        subject_id=subject.subject_id,
                        source_record_id=f"{subject.sheet_name}:row-{counters.source_rows}",
                        source_time=str(raw_time),
                        evidence={"speed": str(speed_raw)},
                    )
                )
                return None
            speed_m_s = speed_value * authorities.SPEED_SOURCE_TO_SI_SCALE
        t_rel_ns = relative_ns(parsed, origin)
        counters.canonical_rows += 1
        if counters.first_source_time is None:
            counters.first_source_time = str(raw_time)
            counters.first_t_rel_ns = t_rel_ns
        counters.last_source_time = str(raw_time)
        counters.last_t_rel_ns = t_rel_ns
        return {
            "dataset_id": WOMENS_DATASET_ID,
            "session_id": WOMENS_SESSION_ID,
            "trial_id": None,
            "subject_id": subject.subject_id,
            "device_id": None,
            "stream_id": subject.stream_id,
            "sample_index": counters.canonical_rows - 1,
            "t_rel_ns": t_rel_ns,
            "timestamp_utc_ns": None,
            "nominal_sampling_rate_hz": subject.nominal_rate_hz,
            "measurement_class": MeasurementClass.RAW_MEASURED.value,
            "clock_id": authorities.CLOCK_ID,
            "synchronization_spec_id": authorities.SYNC_SPEC_ID,
            "coordinate_frame_id": authorities.WGS84_FRAME_ID,
            "latitude_deg": latitude_f,
            "longitude_deg": longitude_f,
            "speed_m_s": speed_m_s,
            **NULLABLE_PAYLOAD,
            "_parsed_time": parsed,
        }


def canonical_gnss_streams(
    workbook_path: Path,
    discovery: WorkbookDiscovery,
) -> tuple[WomenWorkbookAdapter, tuple[CanonicalStream, ...]]:
    adapter = WomenWorkbookAdapter(workbook_path, discovery)
    streams = tuple(adapter.canonical_stream(subject) for subject in adapter.subject_streams())
    return adapter, streams
