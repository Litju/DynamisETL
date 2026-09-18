"""Workbook structure discovery for the Women's Soccer Positioning source.

The adapter must never assume sheet names, headers, units, timestamp semantics
or player layout from memory; this module derives them from the verified native
workbook and emits a structure receipt (written outside the repository, next to
the other provenance receipts).

Nothing here publishes source rows: the receipt records shapes, counts, format
templates and null patterns only.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import openpyxl

#: Timestamp representation observed in the source workbook (text cells).
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S.%f"
TIMESTAMP_EXAMPLE_TEMPLATE = "YYYY-MM-DD HH:MM:SS.sss"

#: Declared source columns. The adapter enforces this exact header set.
SOURCE_COLUMNS = ("local_time", "latitude", "longitude", "speed(km/h)", "hr(bpm)")

#: Columns with an explicit unit suffix, which map to canonical SI values.
VENDOR_DERIVED_COLUMNS = ("speed(km/h)",)

#: Source columns with no canonical GNSS destination in V1 (kept in the receipt).
UNMAPPED_COLUMNS = ("hr(bpm)",)

_LOCAL_TIME = "local_time"


class DiscoveryError(ValueError):
    """The workbook contradicts the structure the adapter can ingest."""


@dataclass(frozen=True, slots=True)
class ColumnDiscovery:
    name: str
    observed_types: tuple[str, ...]
    non_null: int
    null_count: int
    as_text: bool = False


@dataclass(frozen=True, slots=True)
class SheetDiscovery:
    name: str
    row_count: int
    column_names: tuple[str, ...]
    columns: tuple[ColumnDiscovery, ...]
    parseable_timestamps: int
    unparsable_timestamps: int
    first_timestamp: str | None
    last_timestamp: str | None
    duplicate_timestamps: int
    backward_timestamps: int
    min_delta_s: float | None
    median_delta_s: float | None
    max_delta_s: float | None
    modal_delta_s: float | None

    @property
    def nominal_rate_hz(self) -> float | None:
        if self.modal_delta_s is None or self.modal_delta_s <= 0:
            return None
        return round(1.0 / self.modal_delta_s, 6)

    @property
    def strictly_increasing(self) -> bool:
        return self.duplicate_timestamps == 0 and self.backward_timestamps == 0


@dataclass(frozen=True, slots=True)
class WorkbookDiscovery:
    workbook_key: str
    sheet_names: tuple[str, ...]
    sheets: tuple[SheetDiscovery, ...]

    @property
    def total_rows(self) -> int:
        return sum(sheet.row_count for sheet in self.sheets)

    @property
    def header_consistent(self) -> bool:
        return all(sheet.column_names == SOURCE_COLUMNS for sheet in self.sheets)

    @property
    def identity_representation(self) -> str:
        return "sheet name is the provider athlete identifier"

    def to_dict(self) -> dict[str, Any]:
        return {
            "workbook_key": self.workbook_key,
            "sheet_names": list(self.sheet_names),
            "sheet_count": len(self.sheets),
            "total_data_rows": self.total_rows,
            "header_columns": list(SOURCE_COLUMNS),
            "header_consistent": self.header_consistent,
            "identity_representation": self.identity_representation,
            "timestamp_format": TIMESTAMP_EXAMPLE_TEMPLATE,
            "time_semantics": (
                "provider local wall-clock text timestamps; no timezone or UTC truth is "
                "declared upstream"
            ),
            "units": {
                "latitude": (
                    "degrees; geographic GNSS latitude, source datum not explicitly "
                    "declared (canonical interpretation: WGS 84)"
                ),
                "longitude": (
                    "degrees; geographic GNSS longitude, source datum not explicitly "
                    "declared (canonical interpretation: WGS 84)"
                ),
                "speed(km/h)": "km/h as declared by the column name",
                "hr(bpm)": "bpm as declared by the column name",
            },
            "geodetic_datum": {
                "source_representation": "geographic GNSS latitude/longitude",
                "source_datum": "not explicitly declared by the provider",
                "canonical_interpretation": "WGS 84",
                "authority": "inferred pipeline assumption",
                "transformation": "none; source coordinate values pass through unchanged",
            },
            "vendor_derived_columns": list(VENDOR_DERIVED_COLUMNS),
            "unmapped_columns": list(UNMAPPED_COLUMNS),
            "sheets": [
                {
                    "name": sheet.name,
                    "row_count": sheet.row_count,
                    "column_names": list(sheet.column_names),
                    "columns": [
                        {
                            "name": column.name,
                            "observed_types": list(column.observed_types),
                            "non_null": column.non_null,
                            "null_count": column.null_count,
                        }
                        for column in sheet.columns
                    ],
                    "timestamps": {
                        "parseable": sheet.parseable_timestamps,
                        "unparsable": sheet.unparsable_timestamps,
                        "first": sheet.first_timestamp,
                        "last": sheet.last_timestamp,
                        "duplicates": sheet.duplicate_timestamps,
                        "backwards": sheet.backward_timestamps,
                        "min_delta_s": sheet.min_delta_s,
                        "median_delta_s": sheet.median_delta_s,
                        "max_delta_s": sheet.max_delta_s,
                        "modal_delta_s": sheet.modal_delta_s,
                        "nominal_rate_hz": sheet.nominal_rate_hz,
                        "strictly_increasing": sheet.strictly_increasing,
                    },
                }
                for sheet in self.sheets
            ],
        }


def parse_source_timestamp(value: object) -> datetime | None:
    """Parse the provider's text timestamp; ``None`` when it is not that format."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), TIMESTAMP_FORMAT)
    except ValueError:
        return None


def _quantile_from_histogram(counts: Counter[int], total: int, fraction: float) -> int | None:
    if total <= 0:
        return None
    target = max(1, int(total * fraction))
    seen = 0
    for delta_ns in sorted(counts):
        seen += counts[delta_ns]
        if seen >= target:
            return delta_ns
    return max(counts)


def _discover_sheet(sheet_name: str, rows: list[tuple[Any, ...]]) -> SheetDiscovery:
    if not rows:
        raise DiscoveryError(f"sheet {sheet_name!r} is empty")
    header = tuple(str(value).strip() if value is not None else "" for value in rows[0])
    data = rows[1:]
    types: dict[str, Counter[str]] = {name: Counter() for name in header}
    nulls: dict[str, int] = dict.fromkeys(header, 0)
    deltas: Counter[int] = Counter()
    parseable = 0
    unparsable = 0
    first: str | None = None
    last: str | None = None
    previous: datetime | None = None
    duplicates = 0
    backwards = 0

    for row in data:
        for position, name in enumerate(header):
            value = row[position] if position < len(row) else None
            if value is None or (isinstance(value, str) and not value.strip()):
                nulls[name] += 1
            else:
                types[name][type(value).__name__] += 1
        raw_time = row[0] if row else None
        parsed = parse_source_timestamp(raw_time)
        if parsed is None:
            unparsable += 1
            continue
        parseable += 1
        if first is None:
            first = str(raw_time)
        last = str(raw_time)
        if previous is not None:
            delta_ns = int((parsed - previous).total_seconds() * 1_000_000_000)
            if delta_ns == 0:
                duplicates += 1
            elif delta_ns < 0:
                backwards += 1
            else:
                deltas[delta_ns] += 1
        previous = parsed

    columns = tuple(
        ColumnDiscovery(
            name=name,
            observed_types=tuple(sorted(types[name])),
            non_null=sum(types[name].values()),
            null_count=nulls[name],
            as_text=set(types[name]) == {"str"},
        )
        for name in header
    )
    positive_total = sum(deltas.values())
    median_ns = _quantile_from_histogram(deltas, positive_total, 0.5)
    return SheetDiscovery(
        name=sheet_name,
        row_count=len(data),
        column_names=header,
        columns=columns,
        parseable_timestamps=parseable,
        unparsable_timestamps=unparsable,
        first_timestamp=first,
        last_timestamp=last,
        duplicate_timestamps=duplicates,
        backward_timestamps=backwards,
        min_delta_s=round(min(deltas) / 1e9, 6) if deltas else None,
        median_delta_s=round(median_ns / 1e9, 6) if median_ns is not None else None,
        max_delta_s=round(max(deltas) / 1e9, 6) if deltas else None,
        modal_delta_s=round(deltas.most_common(1)[0][0] / 1e9, 6) if deltas else None,
    )


def discover_workbook(path: Path, *, workbook_key: str | None = None) -> WorkbookDiscovery:
    """Read-only structural discovery of the provider workbook."""
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"workbook not found: {target}")
    workbook = openpyxl.load_workbook(target, read_only=True, data_only=True)
    try:
        sheets = tuple(
            _discover_sheet(name, list(workbook[name].iter_rows(values_only=True)))
            for name in workbook.sheetnames
        )
    finally:
        workbook.close()
    return WorkbookDiscovery(
        workbook_key=workbook_key or target.name,
        sheet_names=tuple(workbook.sheetnames),
        sheets=sheets,
    )
