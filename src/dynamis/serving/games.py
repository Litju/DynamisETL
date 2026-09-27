"""Bounded reads over PLAY_BY_PLAY / PLAYER_GAME / TEAM_GAME Silver artifacts.

One contest is always the predicate: a season artifact is sorted by ``contest_id``
with statistics-bearing row groups, so DuckDB prunes to the few row groups of the
requested game. The browser never receives a season of play-by-play.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import duckdb

#: Source columns that are presentation assets (logos, colors, urls) rather than
#: scientific or identity content; they are not served with box scores.
_PRESENTATION_SUFFIXES = ("_logo", "_color", "_alternate_color", "_href", "_uid", "_slug")

ENVELOPE_FIELDS = (
    "contest_id",
    "contest_period_id",
    "sequence_index",
    "source_event_id",
    "provider_namespace",
    "provider_event_type",
    "canonical_time_ns",
    "source_clock_json",
    "team_id",
    "subject_id",
    "attributes_json",
    "attributes_schema_id",
    "attributes_schema_version",
    "period_number",
    "provider_game_id",
)


class GameDataError(RuntimeError):
    """A game artifact or request cannot be served as asked."""


def _clean(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    return value


def read_plays(
    path: Path,
    *,
    contest_id: str,
    period: int | None,
    limit: int,
    offset: int,
) -> tuple[int, list[dict[str, Any]]]:
    """Envelope rows of one contest in provider order, bounded and paged."""
    where = "contest_id = ?"
    params: list[Any] = [contest_id]
    if period is not None:
        where += " AND period_number = ?"
        params.append(period)
    projection = ", ".join(ENVELOPE_FIELDS)
    with duckdb.connect() as connection:
        total_row = connection.execute(
            f"SELECT count(*) FROM read_parquet(?) WHERE {where}", [str(path), *params]
        ).fetchone()
        cursor = connection.execute(
            f"SELECT {projection} FROM read_parquet(?) WHERE {where} "
            "ORDER BY period_number, sequence_index LIMIT ? OFFSET ?",
            [str(path), *params, limit, offset],
        )
        names = [item[0] for item in cursor.description]
        rows = [dict(zip(names, values, strict=True)) for values in cursor.fetchall()]
    plays = []
    for row in rows:
        plays.append(
            {
                **{
                    key: _clean(row[key])
                    for key in ENVELOPE_FIELDS
                    if key
                    not in {
                        "attributes_json",
                        "source_clock_json",
                    }
                },
                "attributes": json.loads(row["attributes_json"]),
                "source_clock": json.loads(row["source_clock_json"])
                if row["source_clock_json"]
                else None,
            }
        )
    return int(total_row[0]) if total_row else 0, plays


def read_box(path: Path, *, contest_id: str) -> tuple[list[str], list[dict[str, Any]]]:
    """Every box-score row of one contest with source columns unprefixed."""
    with duckdb.connect() as connection:
        cursor = connection.execute(
            "SELECT * FROM read_parquet(?) WHERE contest_id = ? ORDER BY ALL",
            [str(path), contest_id],
        )
        names = [item[0] for item in cursor.description]
        raw = [dict(zip(names, values, strict=True)) for values in cursor.fetchall()]
    keep = [
        name
        for name in names
        if not (name.startswith("src_") and name.endswith(_PRESENTATION_SUFFIXES))
    ]
    columns = [name.removeprefix("src_") for name in keep]
    rows = [{name.removeprefix("src_"): _clean(row[name]) for name in keep} for row in raw]
    return columns, rows


def period_event_counts(path: Path, *, contest_id: str) -> dict[int, int]:
    with duckdb.connect() as connection:
        rows = connection.execute(
            "SELECT period_number, count(*) FROM read_parquet(?) WHERE contest_id = ? "
            "GROUP BY 1 ORDER BY 1",
            [str(path), contest_id],
        ).fetchall()
    return {int(period): int(count) for period, count in rows}
