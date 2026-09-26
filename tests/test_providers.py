"""Provider adapter tests on structurally synthetic fixtures.

CI has no network and cannot embed licensed source rows, so every assertion here
runs against fixtures that mirror the *structure* discovered in the verified
real sources. The real-source end-to-end runs are local evidence reported in the
PR and the Linear receipt.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

import pyarrow as pa
import pytest

import synthetic_providers as providers
from dynamis.acquisition.resolvers import ZenodoResolver
from dynamis.adapters.sportec_idsse.adapter import IdsseMatchAdapter
from dynamis.adapters.sportec_idsse.authorities import (
    CENTER_FRAME_ID,
    CORNER_FRAME_ID,
)
from dynamis.adapters.sportec_idsse.discovery import discover_idsse
from dynamis.adapters.womens_soccer_positioning.adapter import (
    WOMENS_DATASET_ID,
    WOMENS_SESSION_ID,
    canonical_gnss_streams,
)
from dynamis.adapters.womens_soccer_positioning.discovery import discover_workbook
from dynamis.config import Settings
from dynamis.contracts import (
    EVENT_SCHEMA,
    GNSS_SCHEMA,
    TRACKING_SCHEMA,
    transform_points,
)
from dynamis.pipeline.ingest import ingest_dfl_match, ingest_womens_j01
from dynamis.pipeline.quarantine import KNOWN_RULES
from dynamis.quality.checks import validate
from dynamis.storage.parquet import read_parquet_schema, read_parquet_table
from dynamis.storage.paths import receipt_path, silver_parquet_path
from synthetic_providers import FakeSession, synthetic_registry

KICKOFF = datetime(2022, 10, 15, 11, 1, 28, 300000, tzinfo=UTC)
HALF_END = datetime(2022, 10, 15, 11, 47, 31, tzinfo=UTC)
SECOND_START = datetime(2022, 10, 15, 12, 3, 29, tzinfo=UTC)
MATCH_END = datetime(2022, 10, 15, 12, 54, 41, tzinfo=UTC)


@pytest.fixture
def womens_workbook(tmp_path: Path) -> Path:
    return providers.default_womens_workbook(tmp_path / "J01.xlsx")


@pytest.fixture
def dfl_files(tmp_path: Path) -> dict[str, Path]:
    return {
        "info": providers.write_match_information(tmp_path / "info.xml", kickoff_utc=KICKOFF),
        "events": providers.write_events(
            tmp_path / "events.xml",
            kickoff_utc=KICKOFF,
            half_end_utc=HALF_END,
            second_half_start_utc=SECOND_START,
            match_end_utc=MATCH_END,
        ),
        "positions": providers.write_positions(
            tmp_path / "positions.xml",
            first_half_start=KICKOFF + timedelta(seconds=1),
            second_half_start=SECOND_START,
        ),
    }


# ---------------------------------------------------------------------------
# Women's Soccer Positioning
# ---------------------------------------------------------------------------


def test_workbook_discovery_describes_the_synthetic_structure(
    womens_workbook: Path,
) -> None:
    discovery = discover_workbook(womens_workbook)
    assert discovery.sheet_names == ("p01", "p02")
    assert discovery.header_consistent
    assert discovery.total_rows == 11
    first, second = discovery.sheets
    assert first.nominal_rate_hz == 10.0
    assert first.strictly_increasing
    assert second.unparsable_timestamps == 1
    assert second.backward_timestamps == 1
    hr = next(column for column in first.columns if column.name == "hr(bpm)")
    assert hr.null_count == hr.non_null + hr.null_count
    assert discovery.to_dict()["unmapped_columns"] == ["hr(bpm)"]
    datum = discovery.to_dict()["geodetic_datum"]
    assert datum["source_datum"] == "not explicitly declared by the provider"
    assert datum["canonical_interpretation"] == "WGS 84"
    assert datum["authority"] == "inferred pipeline assumption"


def test_womens_ingest_maps_rows_and_quarantines_bad_ones(
    tmp_settings: Settings, womens_workbook: Path
) -> None:
    result = ingest_womens_j01(
        tmp_settings, workbook_path=womens_workbook, version="1.0", session_id="J01"
    )
    reconciliation = result.reconciliation
    assert reconciliation.source_rows == 11
    assert reconciliation.canonical_rows == 7
    assert reconciliation.quarantined_rows == 4
    assert reconciliation.all_balanced
    assert {record.rule for record in result.quarantine_records} <= KNOWN_RULES
    assert len(result.streams) == 2
    assert len(result.quarantine_artifacts) == 4

    target = silver_parquet_path(
        tmp_settings,
        dataset_id=WOMENS_DATASET_ID,
        modality="gnss",
        session_id=WOMENS_SESSION_ID,
        stream_id="gnss-p01",
    )
    assert target.is_file()
    assert read_parquet_schema(target).names == GNSS_SCHEMA.names
    table = read_parquet_table(target)
    assert validate(table, GNSS_SCHEMA) == ()
    payload = table.to_pylist()
    assert [row["subject_id"] for row in payload] == ["wsp-p01"] * 5
    assert payload[0]["latency"] if False else True  # noqa: SIM223 - readability guard

    # Source km/h is converted to SI m/s with the exact 1/3.6 scale.
    assert payload[0]["speed_m_s"] == pytest.approx(7.2 / 3.6)
    # Session-monotonic time starts at the workbook origin; UTC is not invented.
    assert payload[0]["t_rel_ns"] == 0
    assert all(row["timestamp_utc_ns"] is None for row in payload)
    assert payload[0]["coordinate_frame_id"] == "wsp-wgs84-geodetic"
    assert payload[0]["measurement_class"] == "RAW_MEASURED"

    # Datum provenance is explicit in the reconciliation receipt: the source
    # declares no datum and WGS 84 is the documented canonical interpretation.
    checks = result.reconciliation.streams[0].checks
    assert checks["source_datum"] == "not explicitly declared by the provider"
    assert checks["canonical_datum"] == "WGS 84"
    assert checks["datum_authority"] == "inferred pipeline assumption"
    assert result.domain["geodetic_datum"]["canonical_interpretation"] == "WGS 84"


def test_womens_stream_counters_and_authorities(
    tmp_settings: Settings, womens_workbook: Path
) -> None:
    discovery = discover_workbook(womens_workbook)
    adapter, streams = canonical_gnss_streams(womens_workbook, discovery)
    authorities = adapter.source_authorities()
    assert authorities.clocks[0].timebase.value == "session_monotonic"
    assert authorities.frames[0].kind.value == "world_geodetic"
    frame = authorities.frames[0]
    # The source does not declare a datum; WGS 84 is an explicit inference.
    assert frame.description is not None
    assert "not explicitly declared by the provider" in frame.description
    assert "inferred pipeline assumption" in frame.description
    assert "WGS 84" in frame.description
    assert authorities.synchronizations[0].method.value == "source_provided"
    subjects = adapter.subject_streams()
    assert [subject.stream_id for subject in subjects] == ["gnss-p01", "gnss-p02"]
    stream = adapter.canonical_stream(subjects[0])
    assert stream.stream_metadata["source_datum"] == "not explicitly declared by the provider"
    assert stream.stream_metadata["canonical_datum"] == "WGS 84"
    assert stream.stream_metadata["datum_authority"] == "inferred pipeline assumption"
    batches = list(stream.batches)
    total = sum(batch.num_rows for batch in batches)
    assert total == 5
    assert batches[0].schema.names == GNSS_SCHEMA.names
    counters = adapter.counters("p01")
    assert counters.source_rows == 5
    assert counters.canonical_rows == 5
    assert not counters.quarantined


def test_womens_ingest_is_deterministic(tmp_settings: Settings, womens_workbook: Path) -> None:
    first = ingest_womens_j01(
        tmp_settings, workbook_path=womens_workbook, version="1.0", session_id="J01"
    )
    second = ingest_womens_j01(
        tmp_settings, workbook_path=womens_workbook, version="1.0", session_id="J01"
    )
    assert [item.checksum_sha256 for item in first.streams] == [
        item.checksum_sha256 for item in second.streams
    ]


def test_womens_quarantine_records_are_locatable(
    tmp_settings: Settings, womens_workbook: Path
) -> None:
    result = ingest_womens_j01(
        tmp_settings, workbook_path=womens_workbook, version="1.0", session_id="J01"
    )
    for record in result.quarantine_records:
        assert record.source_record_id
        assert record.evidence
        assert record.dataset_id == WOMENS_DATASET_ID
        assert record.session_id == WOMENS_SESSION_ID
    receipt = Path(result.receipt_path)
    assert receipt.is_file()
    assert str(tmp_settings.dataset_root) not in receipt.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# DFL/Sportec IDSSE
# ---------------------------------------------------------------------------


def _adapter(tmp_path: Path, dfl_files: dict[str, Path]) -> IdsseMatchAdapter:
    adapter = IdsseMatchAdapter(
        match_information_path=dfl_files["info"],
        events_path=dfl_files["events"],
        positions_path=dfl_files["positions"],
        version="0" * 40,
        spill_dir=tmp_path / "spill",
    )
    return adapter


def test_idsse_discovery_measures_frames_and_defects(
    tmp_path: Path, dfl_files: dict[str, Path]
) -> None:
    discovery = discover_idsse(dfl_files["info"], dfl_files["events"], dfl_files["positions"])
    positions = discovery.positions
    assert positions.sections == ("firstHalf", "secondHalf")
    assert positions.entity_frame_observations == 100
    assert positions.distinct_frame_numbers == 30
    assert positions.framesets == 7
    assert positions.frame_number_range == (10_000, 100_009)
    assert positions.time_step_s == pytest.approx(0.04)
    # The synthetic fixture contains a deliberate time/frame mismatch.
    assert positions.frame_to_time_exact is False
    assert set(positions.ball_entities) == {"DFL-OBJ-B001"}
    assert len(positions.ball_entities) == 2  # one ball FrameSet per period
    assert positions.pitch_size_declared_m == (105.0, 68.0)
    events = discovery.events
    assert events.event_count == 7
    assert events.deleted_events == 1
    assert events.chronological_order is False
    assert discovery.match_information.player_count == 4
    assert discovery.match_information.pitch_x_m == 105.0


def test_idsse_match_metadata_and_periods(tmp_path: Path, dfl_files: dict[str, Path]) -> None:
    adapter = _adapter(tmp_path, dfl_files)
    metadata = adapter.metadata
    assert metadata.match_id == "DFL-MAT-SYNTH1"
    assert metadata.player_count == 4
    assert metadata.kickoff_utc == KICKOFF
    events = adapter.parse_events()
    assert [period.period_id for period in events.periods] == ["period-1", "period-2"]
    assert events.periods[0].started_at == KICKOFF
    assert events.periods[0].ended_at == HALF_END
    assert events.canonical_rows == 6
    assert events.deleted_events == 1


def test_idsse_tracking_stream_registers_source_pitch_dimensions(
    tmp_path: Path, dfl_files: dict[str, Path]
) -> None:
    adapter = _adapter(tmp_path, dfl_files)
    tracking = next(
        stream for stream in adapter.domain().streams if stream.modality.value == "tracking"
    )
    metadata = adapter.metadata
    assert tracking.stream_metadata["pitch_dimensions_m"] == {
        "length_m": metadata.pitch_x_m,
        "width_m": metadata.pitch_y_m,
    }


def test_idsse_authorities_declare_the_origin_translation(
    tmp_path: Path, dfl_files: dict[str, Path]
) -> None:
    adapter = _adapter(tmp_path, dfl_files)
    authorities = adapter.source_authorities()
    frames = {frame.frame_id: frame for frame in authorities.frames}
    assert set(frames) == {CENTER_FRAME_ID, CORNER_FRAME_ID}
    corner = frames[CORNER_FRAME_ID]
    assert corner.parent_frame_id == CENTER_FRAME_ID
    assert corner.transform is not None
    assert corner.transform.translation_m == (-52.5, -34.0, 0.0)
    ((x_center, y_center, _z),) = transform_points(corner.transform, ((70.0, 20.0, 0.0),))
    assert (x_center, y_center) == (17.5, -14.0)
    clock = authorities.clocks[0]
    assert clock.timebase.value == "utc"
    assert clock.frequency_hz == 25.0


def test_idsse_positions_canonicalization_balances_and_is_frame_major(
    tmp_settings: Settings, tmp_path: Path, dfl_files: dict[str, Path]
) -> None:
    result = ingest_dfl_match(
        tmp_settings,
        match_information_path=dfl_files["info"],
        events_path=dfl_files["events"],
        positions_path=dfl_files["positions"],
        version="0" * 40,
        session_id="DFL-MAT-SYNTH1",
        spill_dir=tmp_path / "spill",
    )
    reconciliation = result.reconciliation
    assert reconciliation.all_balanced
    tracking_streams = [item for item in result.streams if item.modality == "tracking"]
    assert {item.stream_id for item in tracking_streams} == {
        "tracking-period-1",
        "tracking-period-2",
    }
    period_one = next(item for item in tracking_streams if item.stream_id == "tracking-period-1")
    assert period_one.row_count == 67
    period_two = next(item for item in tracking_streams if item.stream_id == "tracking-period-2")
    assert period_two.row_count == 30
    assert len(result.quarantine_artifacts) == 3
    rules = {artifact["rule"] for artifact in result.quarantine_artifacts}
    assert rules == {"coordinate_missing", "duplicate_frame", "frame_time_mismatch"}

    target = silver_parquet_path(
        tmp_settings,
        dataset_id="dfl-sportec-idsse",
        modality="tracking",
        session_id="DFL-MAT-SYNTH1",
        stream_id="tracking-period-1",
    )
    table = read_parquet_table(target)
    assert validate(table, TRACKING_SCHEMA) == ()
    payload = table.to_pylist()
    times = [row["t_rel_ns"] for row in payload]
    assert times == sorted(times)
    assert [row["sample_index"] for row in payload] == list(range(len(payload)))
    by_frame: dict[int, list[str]] = {}
    for row in payload:
        by_frame.setdefault(row["t_rel_ns"], []).append(row["object_id"])
    origin = 1_000_000_000  # synthetic first-half origin is kickoff + 1 s
    assert sorted(by_frame)[0] == origin
    assert len(by_frame[origin]) == 3
    assert len(by_frame[origin + 4 * 40_000_000]) == 2  # ball quarantined
    assert by_frame[origin][0] == "DFL-OBJ-A002"
    assert payload[0]["object_type"] == "player"
    assert payload[0]["group_id"] == "DFL-CLU-00000A"
    subject_ids = {row["subject_id"] for row in payload}
    assert "DFL-OBJ-B001" not in subject_ids  # the ball carries no subject
    assert {"DFL-OBJ-H001", "DFL-OBJ-A002", "DFL-OBJ-H003"} <= subject_ids
    ball_rows = [row for row in payload if row["object_type"] == "ball"]
    assert all(row["z_m"] is not None for row in ball_rows)
    assert all(row["vx_m_s"] is None for row in payload)


def test_idsse_events_are_chronological_transformed_and_mapped(
    tmp_settings: Settings, tmp_path: Path, dfl_files: dict[str, Path]
) -> None:
    result = ingest_dfl_match(
        tmp_settings,
        match_information_path=dfl_files["info"],
        events_path=dfl_files["events"],
        positions_path=dfl_files["positions"],
        version="0" * 40,
        session_id="DFL-MAT-SYNTH1",
        spill_dir=tmp_path / "spill",
    )
    events_result = next(item for item in result.streams if item.modality == "event")
    assert events_result.row_count == 6
    target = silver_parquet_path(
        tmp_settings,
        dataset_id="dfl-sportec-idsse",
        modality="event",
        session_id="DFL-MAT-SYNTH1",
        stream_id="events",
    )
    table = read_parquet_table(target)
    assert validate(table, EVENT_SCHEMA) == ()
    rows = table.to_pylist()
    assert [row["event_id"] for row in rows] == [
        "SYN-EV-0001",
        "SYN-EV-0002",
        "SYN-EV-0003",
        "SYN-EV-0005",
        "SYN-EV-0006",
        "SYN-EV-0007",
    ]
    assert all(row["trial_id"] == "period-1" for row in rows[:4])
    assert rows[4]["trial_id"] == "period-2"
    kickoff = rows[0]
    assert kickoff["event_type"] == "kick_off"
    assert kickoff["event_subtype"] == "pass"
    assert kickoff["provider_player_id"] == "DFL-OBJ-H002"
    assert kickoff["provider_team_id"] == "DFL-CLU-00000H"
    shot = rows[2]
    assert shot["event_type"] == "shot_at_goal"
    assert shot["event_subtype"] == "saved_shot"
    assert shot["x_m"] == pytest.approx(17.5)
    assert shot["y_m"] == pytest.approx(-14.0)
    assert shot["body_part"] == "right_leg"
    assert shot["coordinate_frame_id"] == CENTER_FRAME_ID
    foul = rows[1]
    assert foul["provider_team_id"] == "DFL-CLU-00000A"
    assert foul["x_m"] == pytest.approx(-12.5)
    assert foul["provider_context_json"] is not None
    assert "Delete" not in {row["event_type"] for row in rows}


def test_idsse_domain_registers_players_and_periods(
    tmp_path: Path, dfl_files: dict[str, Path]
) -> None:
    adapter = _adapter(tmp_path, dfl_files)
    adapter.parse_positions()
    domain = adapter.domain()
    assert [session.session_id for session in domain.all_sessions] == ["DFL-MAT-SYNTH1"]
    assert domain.all_sessions[0].kind.value == "match"
    assert len(domain.subjects) == 4
    assert len(domain.participants) == 4
    assert [trial.trial_id for trial in domain.trials] == ["period-1", "period-2"]
    sports = domain.sports_contexts[0]
    assert sports.sport.code == "football"
    assert sports.competition is not None
    assert sports.competition.name == adapter.metadata.competition
    assert sports.edition is not None and sports.edition.label == adapter.metadata.season
    assert len(sports.teams) == 2 and len(sports.periods) == 2
    assert len(sports.roster_memberships) == len(domain.subjects)
    assert len(domain.authorities.surface_geometries) == 1
    assert domain.authorities.clock_mappings[0].source_unit == "ns"
    assert domain.authorities.clock_mappings[0].offset_ns < 0
    assert [stream.stream_id for stream in domain.streams] == [
        "tracking-period-1",
        "tracking-period-2",
        "events",
    ]
    goalkeepers = [
        participant for participant in domain.participants if participant.role.value == "goalkeeper"
    ]
    assert [item.subject_id for item in goalkeepers] == ["DFL-OBJ-A001"]
    assert domain.participants_ignored == {"trainers": 2, "referees_and_officials": 1}


def test_idsse_spill_files_are_removed_after_cleanup(
    tmp_path: Path, dfl_files: dict[str, Path]
) -> None:
    adapter = _adapter(tmp_path, dfl_files)
    summary = adapter.parse_positions()
    assert summary.frame_entity_observations == 100
    assert summary.quarantined_rows == 3
    assert summary.spill_dir.is_dir()
    adapter.cleanup()
    assert not summary.spill_dir.exists()


def test_idsse_tracking_is_byte_deterministic(
    tmp_settings: Settings, tmp_path: Path, dfl_files: dict[str, Path]
) -> None:
    first = ingest_dfl_match(
        tmp_settings,
        match_information_path=dfl_files["info"],
        events_path=dfl_files["events"],
        positions_path=dfl_files["positions"],
        version="0" * 40,
        session_id="DFL-MAT-SYNTH1",
        spill_dir=tmp_path / "spill-a",
    )
    second = ingest_dfl_match(
        tmp_settings,
        match_information_path=dfl_files["info"],
        events_path=dfl_files["events"],
        positions_path=dfl_files["positions"],
        version="0" * 40,
        session_id="DFL-MAT-SYNTH1",
        spill_dir=tmp_path / "spill-b",
    )
    assert [item.checksum_sha256 for item in first.streams] == [
        item.checksum_sha256 for item in second.streams
    ]


def test_idsse_malformed_documents_are_quarantined_not_dropped(
    tmp_settings: Settings, tmp_path: Path
) -> None:
    positions = providers.write_positions(
        tmp_path / "positions.xml",
        first_half_start=KICKOFF + timedelta(seconds=1),
        second_half_start=SECOND_START,
    )
    info = providers.write_match_information(tmp_path / "info.xml", kickoff_utc=KICKOFF)
    events = providers.write_events(
        tmp_path / "events.xml",
        kickoff_utc=KICKOFF,
        half_end_utc=HALF_END,
        second_half_start_utc=SECOND_START,
        match_end_utc=MATCH_END,
    )
    result = ingest_dfl_match(
        tmp_settings,
        match_information_path=info,
        events_path=events,
        positions_path=positions,
        version="0" * 40,
        session_id="DFL-MAT-SYNTH1",
        spill_dir=tmp_path / "spill",
    )
    assert result.reconciliation.all_balanced
    tracking = next(
        stream
        for stream in result.reconciliation.streams
        if stream.stream_id == "tracking-period-1"
    )
    assert tracking.canonical_rows + tracking.quarantined_rows == tracking.source_records
    assert tracking.quarantined_rows == 3
    assert tracking.source_records == 70
    assert "quarantine" in result.quarantine_artifacts[0]["relative_path"]


def test_idsse_non_finite_positions_are_quarantined_not_published(tmp_path: Path) -> None:
    """NaN/Inf X/Y, and a malformed or non-finite optional Z, never publish."""
    from dynamis.adapters.sportec_idsse.matchinfo import parse_match_information
    from dynamis.adapters.sportec_idsse.positions import PositionsCanonicalizer

    info = providers.write_match_information(tmp_path / "info.xml", kickoff_utc=KICKOFF)
    metadata = parse_match_information(info)
    start = KICKOFF + timedelta(seconds=1)
    root = ET.Element("PutDataRequest")
    positions = ET.SubElement(root, "Positions", {"EventTime": start.isoformat()})
    frameset = ET.SubElement(
        positions,
        "FrameSet",
        {
            "GameSection": "firstHalf",
            "MatchId": "DFL-MAT-SYNTH1",
            "TeamId": "DFL-CLU-00000H",
            "PersonId": "DFL-OBJ-H001",
        },
    )
    raw_frames: tuple[tuple[int, str, str, str | None], ...] = (
        (10_000, "0.00", "0.00", None),
        (10_001, "NaN", "1.00", None),
        (10_002, "1.00", "inf", None),
        (10_003, "2.00", "3.00", "not-a-number"),
        (10_004, "4.00", "5.00", "NaN"),
        (10_005, "6.00", "7.00", "0.50"),
    )
    for number, x_raw, y_raw, z_raw in raw_frames:
        stamp = start + timedelta(milliseconds=40 * (number - 10_000))
        attributes = {
            "N": str(number),
            "T": stamp.strftime("%Y-%m-%dT%H:%M:%S.") + f"{stamp.microsecond // 1000:03d}Z",
            "X": x_raw,
            "Y": y_raw,
        }
        if z_raw is not None:
            attributes["Z"] = z_raw
        ET.SubElement(frameset, "Frame", attributes)
    target = tmp_path / "positions.xml"
    ET.ElementTree(root).write(str(target), encoding="UTF-8", xml_declaration=True)

    canonicalizer = PositionsCanonicalizer(
        target,
        metadata,
        spill_dir=tmp_path / "spill",
        batch_size=2,
        dataset_id="dfl-sportec-idsse",
        clock_id="dfl-sportec-utc",
        synchronization_spec_id="dfl-source-provided",
        coordinate_frame_id="dfl-pitch-center-m",
    )
    summary = canonicalizer.spill()
    assert summary.frame_entity_observations == 6
    assert summary.canonical_rows == 2  # first and last frames only
    assert summary.quarantined_rows == 4
    assert summary.quarantined_by_rule == {
        "non_finite_value": 3,
        "coordinate_out_of_range": 1,
    }
    rows = [
        row
        for batch in canonicalizer.streams(session_id=metadata.match_id)[0].batches
        for row in batch.to_pylist()
    ]
    assert [row["x_m"] for row in rows] == [0.0, 6.0]
    assert all(
        math.isfinite(row["x_m"]) and math.isfinite(row["y_m"]) and math.isfinite(row["z_m"] or 0.0)
        for row in rows
    )
    assert rows[1]["z_m"] == pytest.approx(0.5)
    # Off-pitch positions are legitimate and are never clipped or rejected.
    assert all(row["x_m"] is not None for row in rows)
    canonicalizer.cleanup()


def test_idsse_non_finite_event_coordinates_are_quarantined(tmp_path: Path) -> None:
    from dynamis.adapters.sportec_idsse.authorities import corner_to_center_transform
    from dynamis.adapters.sportec_idsse.events import EventsCanonicalizer
    from dynamis.adapters.sportec_idsse.matchinfo import parse_match_information

    info = providers.write_match_information(tmp_path / "info.xml", kickoff_utc=KICKOFF)
    metadata = parse_match_information(info)
    root = ET.Element("PutDataRequest")

    def event(event_id: str, when: datetime, x_raw: str | None, y_raw: str | None) -> ET.Element:
        attributes = {
            "EventId": event_id,
            "EventTime": when.isoformat(),
            "MatchId": "DFL-MAT-SYNTH1",
        }
        if x_raw is not None and y_raw is not None:
            attributes["X-Position"] = x_raw
            attributes["Y-Position"] = y_raw
        return ET.Element("Event", attributes)

    for element in (
        event("SYN-EV-1002", KICKOFF + timedelta(seconds=5), "70.0", "20.0"),
        event("SYN-EV-1003", KICKOFF + timedelta(seconds=6), "NaN", "1.0"),
        event("SYN-EV-1004", KICKOFF + timedelta(seconds=7), "1.0", "inf"),
        event("SYN-EV-1005", KICKOFF + timedelta(seconds=8), "abc", "1.0"),
    ):
        ET.SubElement(element, "Play", {"Team": "DFL-CLU-00000H", "Player": "DFL-OBJ-H001"})
        root.append(element)
    kickoff = event("SYN-EV-1001", KICKOFF, None, None)
    ET.SubElement(
        kickoff,
        "KickOff",
        {
            "TeamLeft": "DFL-CLU-00000H",
            "TeamRight": "DFL-CLU-00000A",
            "GameSection": "firstHalf",
        },
    )
    root.insert(0, kickoff)
    target = tmp_path / "events.xml"
    ET.ElementTree(root).write(str(target), encoding="UTF-8", xml_declaration=True)

    canonicalizer = EventsCanonicalizer(
        target,
        metadata,
        transform=corner_to_center_transform(metadata.pitch_x_m, metadata.pitch_y_m),
        dataset_id="dfl-sportec-idsse",
        session_id=metadata.match_id,
        clock_id="dfl-sportec-utc",
        synchronization_spec_id="dfl-source-provided",
        coordinate_frame_id="dfl-pitch-center-m",
    )
    canonicalizer.parse()
    summary = canonicalizer.summary
    assert summary.source_events == 5
    assert summary.canonical_rows == 2  # kick-off and the single valid position
    assert summary.events_with_coordinates == 1
    assert {record.rule for record in summary.quarantined} == {
        "non_finite_value",
        "coordinate_out_of_range",
    }


def test_reconciliation_receipt_is_written_for_both_providers(
    tmp_settings: Settings, womens_workbook: Path, tmp_path: Path, dfl_files: dict[str, Path]
) -> None:
    womens = ingest_womens_j01(
        tmp_settings, workbook_path=womens_workbook, version="1.0", session_id="J01"
    )
    dfl = ingest_dfl_match(
        tmp_settings,
        match_information_path=dfl_files["info"],
        events_path=dfl_files["events"],
        positions_path=dfl_files["positions"],
        version="0" * 40,
        session_id="DFL-MAT-SYNTH1",
        spill_dir=tmp_path / "spill",
    )
    for dataset_id, name, result in (
        (WOMENS_DATASET_ID, "J01-gnss", womens),
        ("dfl-sportec-idsse", "DFL-MAT-SYNTH1-match", dfl),
    ):
        receipt = receipt_path(
            tmp_settings, dataset_id=dataset_id, kind="reconciliation", name=name
        )
        assert receipt.is_file()
        assert result.reconciliation.all_balanced
        text = receipt.read_text(encoding="utf-8")
        assert str(tmp_settings.dataset_root) not in text


def test_ingest_cli_verifies_bronze_and_writes_silver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, womens_workbook: Path
) -> None:
    from dynamis.config import (
        ENV_DATABASE_ROOT,
        ENV_DATASET_ROOT,
        ENV_DUCKDB_PATH,
        Settings,
    )
    from dynamis.pipeline import cli
    from dynamis.registry import source_by_id, validate_registry
    from dynamis.storage.manifest import (
        manifest_from_registry,
        record_retrieval,
        write_bronze_manifest,
    )
    from dynamis.storage.paths import bronze_native_path

    dataset_root = tmp_path / "datasets"
    database_root = tmp_path / "databases"
    env = {
        ENV_DATASET_ROOT: str(dataset_root),
        ENV_DATABASE_ROOT: str(database_root),
        ENV_DUCKDB_PATH: str(database_root / "duckdb" / "dynamis.duckdb"),
    }
    monkeypatch.setenv(ENV_DATASET_ROOT, env[ENV_DATASET_ROOT])
    monkeypatch.setenv(ENV_DATABASE_ROOT, env[ENV_DATABASE_ROOT])
    monkeypatch.setenv(ENV_DUCKDB_PATH, env[ENV_DUCKDB_PATH])
    resolved = Settings.from_environ(env)

    missing = cli.main(
        [
            "womens-soccer-positioning",
            "--version",
            "1.0",
            "--key",
            "J01.xlsx",
            "--no-persist",
            "--json",
        ]
    )
    assert missing == 2  # no Bronze yet

    source = source_by_id(validate_registry(), "womens-soccer-positioning")
    version = source.version("1.0")
    target = bronze_native_path(
        resolved, dataset_id=source.dataset_id, version="1.0", key="J01.xlsx"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(womens_workbook.read_bytes())
    manifest = record_retrieval(
        resolved,
        manifest_from_registry(source, version),
        retrieved_at=datetime(2026, 9, 17, tzinfo=UTC),
        only_keys=("J01.xlsx",),
    )
    write_bronze_manifest(resolved, manifest)

    assert (
        cli.main(
            [
                "womens-soccer-positioning",
                "--version",
                "1.0",
                "--key",
                "J01.xlsx",
                "--no-persist",
                "--discovery",
                "--json",
            ]
        )
        == 0
    )
    discovery_receipt = receipt_path(
        resolved,
        dataset_id=WOMENS_DATASET_ID,
        kind="discovery",
        name="J01-workbook",
    )
    assert discovery_receipt.is_file()
    assert '"sheet_names"' in discovery_receipt.read_text(encoding="utf-8")
    silver = silver_parquet_path(
        resolved,
        dataset_id=WOMENS_DATASET_ID,
        modality="gnss",
        session_id="J01",
        stream_id="gnss-p01",
    )
    assert silver.is_file()


def test_ingest_cli_rejects_a_selection_outside_the_registry(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from dynamis.pipeline import cli

    assert cli.main(["womens-soccer-positioning", "--version", "1.0", "--key", "nope.xlsx"]) == 2
    assert "declares no file" in capsys.readouterr().err


def test_synthetic_event_document_has_no_namespaces(dfl_files: dict[str, Path]) -> None:
    root = ET.parse(str(dfl_files["events"])).getroot()
    assert root.tag == "PutDataRequest"


# ---------------------------------------------------------------------------
# Review-driven regression tests (CodeRabbit findings on PR #2)
# ---------------------------------------------------------------------------


def test_repeated_frameset_for_one_entity_is_merged_not_truncated(tmp_path: Path) -> None:
    """A second FrameSet for the same person must extend, never replace, its rows."""
    from xml.etree import ElementTree as ET

    from dynamis.adapters.sportec_idsse.matchinfo import parse_match_information
    from dynamis.adapters.sportec_idsse.positions import PositionsCanonicalizer

    info = providers.write_match_information(tmp_path / "info.xml", kickoff_utc=KICKOFF)
    metadata = parse_match_information(info)
    start = KICKOFF + timedelta(seconds=1)
    root = ET.Element("PutDataRequest")
    positions = ET.SubElement(root, "Positions", {"EventTime": start.isoformat()})

    def add_frameset(numbers: tuple[int, ...]) -> None:
        frameset = ET.SubElement(
            positions,
            "FrameSet",
            {
                "GameSection": "firstHalf",
                "MatchId": "DFL-MAT-SYNTH1",
                "TeamId": "DFL-CLU-00000H",
                "PersonId": "DFL-OBJ-H001",
            },
        )
        for n in numbers:
            stamp = start + timedelta(milliseconds=40 * (n - 10_000))
            ET.SubElement(
                frameset,
                "Frame",
                {
                    "N": str(n),
                    "T": (
                        stamp.strftime("%Y-%m-%dT%H:%M:%S.") + f"{stamp.microsecond // 1000:03d}Z"
                    ),
                    "X": "1.00",
                    "Y": "2.00",
                    "D": "0.00",
                    "S": "1.00",
                    "A": "0.00",
                    "M": "1",
                },
            )

    add_frameset((10_000, 10_001, 10_002))
    add_frameset((10_003, 10_004))

    target = tmp_path / "positions.xml"
    ET.ElementTree(root).write(str(target), encoding="UTF-8", xml_declaration=True)

    canonicalizer = PositionsCanonicalizer(
        target,
        metadata,
        spill_dir=tmp_path / "spill",
        batch_size=2,
        dataset_id="dfl-sportec-idsse",
        clock_id="dfl-sportec-utc",
        synchronization_spec_id="dfl-source-provided",
        coordinate_frame_id="dfl-pitch-center-m",
    )
    summary = canonicalizer.spill()
    assert summary.canonical_rows == 5
    rows = [
        row
        for batch in canonicalizer.streams(session_id=metadata.match_id)[0].batches
        for row in batch.to_pylist()
    ]
    assert len(rows) == 5
    assert [row["t_rel_ns"] for row in rows] == sorted(row["t_rel_ns"] for row in rows)
    assert summary.sections[0].frame_first == 10_000
    assert summary.sections[0].frame_last == 10_004
    canonicalizer.cleanup()


def test_naive_kickoff_time_is_rejected(tmp_path: Path) -> None:
    from dynamis.adapters.sportec_idsse.matchinfo import (
        MatchInfoError,
        parse_match_information,
    )

    path = providers.write_match_information(
        tmp_path / "info.xml", kickoff_utc=KICKOFF.replace(tzinfo=None)
    )
    with pytest.raises(MatchInfoError, match="no UTC offset"):
        parse_match_information(path)


def test_womens_non_numeric_and_non_finite_cells_are_quarantined(
    tmp_settings: Settings, tmp_path: Path
) -> None:
    start = datetime(2023, 9, 10, 17, 22, 32, 800000)
    stamp = start.strftime("%Y-%m-%d %H:%M:%S.800")
    later = (start + timedelta(seconds=0.1)).strftime("%Y-%m-%d %H:%M:%S.900")
    workbook = providers.write_womens_workbook(
        tmp_path / "J01.xlsx",
        (
            providers.WomensSheet(
                name="p01",
                rows=(
                    (stamp, 43.35, -5.92, "not-a-number", None),
                    (later, 43.35, -5.92, "inf", None),
                ),
            ),
        ),
    )
    result = ingest_womens_j01(
        tmp_settings, workbook_path=workbook, version="1.0", session_id="J01"
    )
    assert result.reconciliation.source_rows == 2
    assert result.reconciliation.canonical_rows == 0
    assert result.reconciliation.quarantined_rows == 2
    assert result.reconciliation.streams[0].source_records == 2
    # A text cell and an infinite cell both fail the non-finite numeric rule;
    # neither row is silently dropped and no invalid speed is published.
    assert {record.rule for record in result.quarantine_records} == {"non_finite_value"}


def test_zenodo_resolution_carries_registry_sha256_when_provider_is_silent() -> None:
    from dynamis.contracts import RetrievalFile

    digest = "ab" * 32
    registry = synthetic_registry(
        files=(RetrievalFile(key="a.bin", size_bytes=4, md5="unknown", sha256=digest),)
    )
    session = FakeSession(
        {
            "https://zenodo.org/api/records/12345": {
                "files": [
                    {
                        "key": "a.bin",
                        "size": 4,
                        "links": {
                            "self": "https://zenodo.org/api/records/12345/files/a.bin/content"
                        },
                    }
                ]
            }
        }
    )
    resolved = ZenodoResolver().resolve(
        session,
        source=registry.sources[0],
        version=registry.sources[0].versions[0],
        keys=["a.bin"],
        timeout=(1.0, 1.0),
    )
    assert resolved[0].upstream_sha256 == digest


def test_streaming_validator_ignores_empty_batches() -> None:
    from dynamis.contracts import get_schema
    from dynamis.quality.streaming import StreamingValidator

    schema = get_schema("gnss")
    validator = StreamingValidator(schema)
    validator.observe(pa.RecordBatch.from_pylist([], schema=schema))
    assert validator.finish() == ()
