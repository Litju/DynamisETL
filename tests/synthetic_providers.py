"""Structurally synthetic provider fixtures for the RES-97 adapters.

These mirror the *structure* discovered in the verified real sources (sheet
layout, XML element hierarchy, attribute vocabulary, 25 Hz frame/time relation)
without embedding any real provider row. They exist so CI can exercise parsing,
identity mapping, coordinates, clocks, quarantine and reconciliation with no
network access and no licensed data in the repository.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import openpyxl

#: The Women's workbook header exactly as discovered in the verified J01 file.
WOMENS_HEADER = ("local_time", "latitude", "longitude", "speed(km/h)", "hr(bpm)")

SPORTEC_FPS = 25
FRAME_STEP = timedelta(seconds=1.0 / SPORTEC_FPS)


@dataclass(frozen=True, slots=True)
class WomensSheet:
    """One synthetic sheet: rows are ``(local_time, lat, lon, speed, hr)``."""

    name: str
    rows: tuple[tuple[str | None, float | None, float | None, float | None, None], ...]


def womens_rows(
    *,
    start: datetime,
    count: int,
    latitude: float = 43.3551,
    longitude: float = -5.9224,
    speed_kmh: float = 7.2,
    step_s: float = 0.1,
) -> tuple[tuple[str, float, float, float, None], ...]:
    rows = []
    for index in range(count):
        stamp = start + timedelta(seconds=index * step_s)
        rows.append(
            (
                stamp.strftime("%Y-%m-%d %H:%M:%S.") + f"{stamp.microsecond // 1000:03d}",
                latitude + index * 1e-6,
                longitude + index * 1e-6,
                speed_kmh,
                None,
            )
        )
    return tuple(rows)


def write_womens_workbook(path: Path, sheets: tuple[WomensSheet, ...]) -> Path:
    """Write a synthetic workbook with the discovered sheet structure."""
    workbook = openpyxl.Workbook()
    first_sheet = workbook.active
    if first_sheet is not None:
        workbook.remove(first_sheet)
    for sheet in sheets:
        worksheet = workbook.create_sheet(title=sheet.name)
        worksheet.append(list(WOMENS_HEADER))
        for row in sheet.rows:
            worksheet.append(list(row))
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    return path


def default_womens_workbook(path: Path) -> Path:
    """Four sheets: one valid, plus one row for each quarantine rule."""
    start = datetime(2023, 9, 10, 17, 22, 32, 800000)
    valid = womens_rows(start=start, count=5)
    mixed = (
        valid[0],
        ("not-a-timestamp", 43.35, -5.92, 5.0, None),
        (
            (start - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S.000"),
            43.35,
            -5.92,
            4.0,
            None,
        ),
        (valid[2][0], None, -5.92, 3.0, None),
        (valid[3][0], 91.5, -5.92, 2.0, None),
        valid[4],
    )
    return write_womens_workbook(
        path,
        (
            WomensSheet(name="p01", rows=valid),
            WomensSheet(name="p02", rows=mixed),
        ),
    )


# ---------------------------------------------------------------------------
# DFL/Sportec XML
# ---------------------------------------------------------------------------


def _put_data_request() -> ET.Element:
    return ET.Element(
        "PutDataRequest",
        {
            "RequestId": "00000000-0000-4000-8000-000000000000",
            "MessageTime": "2022-10-15T23:07:57.602+00:00",
            "TransmissionComplete": "true",
            "TransmissionSuspended": "false",
        },
    )


def write_match_information(
    path: Path,
    *,
    kickoff_utc: datetime,
    home: tuple[str, str] = ("DFL-CLU-00000H", "Home FC"),
    away: tuple[str, str] = ("DFL-CLU-00000A", "Away FC"),
) -> Path:
    """Minimal but structurally faithful matchinformation document."""
    root = _put_data_request()
    information = ET.SubElement(root, "MatchInformation")
    ET.SubElement(
        information,
        "General",
        {
            "TypeOfSport": "Fußball",
            "CompetitionName": "Synthetic League",
            "CompetitionId": "DFL-COM-000000",
            "Host": "Synthetic Host",
            "Type": "Ligabetrieb",
            "MatchDay": "1",
            "Season": "2022/2023",
            "SeasonId": "DFL-SEA-000000",
            "PlannedKickoffTime": kickoff_utc.isoformat(),
            "KickoffTime": kickoff_utc.isoformat(),
            "MatchId": "DFL-MAT-SYNTH1",
            "DlProviderId": "000000",
            "MatchTitle": f"{home[1]}:{away[1]}",
            "HomeTeamName": home[1],
            "HomeTeamId": home[0],
            "GuestTeamName": away[1],
            "GuestTeamId": away[0],
            "Result": "1:0",
        },
    )
    ET.SubElement(
        information,
        "Environment",
        {
            "Country": "Deutschland",
            "StadiumId": "DFL-STA-000000",
            "StadiumName": "Synthetic Arena",
            "NeutralVenue": "false",
            "Roof": "open",
            "Floodlight": "on",
            "Temperature": "16",
            "PitchErosion": "none",
            "NumberOfSpectators": "1000",
            "StadiumCapacity": "2000",
            "Precipitation": "none",
            "SoldOut": "false",
            "PitchX": "105.00",
            "PitchY": "68.00",
        },
    )
    teams = ET.SubElement(information, "Teams")
    for team_id, name, role, players in (
        (home[0], home[1], "home", (("DFL-OBJ-H001", "10"), ("DFL-OBJ-H002", "7"))),
        (away[0], away[1], "guest", (("DFL-OBJ-A001", "1"), ("DFL-OBJ-A002", "9"))),
    ):
        team = ET.SubElement(
            teams,
            "Team",
            {"TeamId": team_id, "TeamName": name, "Role": role, "LineUp": "4-4-2"},
        )
        roster = ET.SubElement(team, "Players")
        for person_id, shirt in players:
            ET.SubElement(
                roster,
                "Player",
                {
                    "PersonId": person_id,
                    "ShirtNumber": shirt,
                    "FirstName": "Synthetic",
                    "LastName": person_id,
                    "Shortname": person_id,
                    "Starting": "true",
                    "PlayingPosition": "TW" if person_id.endswith("A001") else "ST",
                    "TeamLeader": "false",
                },
            )
        staff = ET.SubElement(team, "TrainerStaff")
        ET.SubElement(
            staff,
            "Trainer",
            {
                "PersonId": "DFL-OBJ-T001",
                "Role": "headcoach",
                "FirstName": "Synthetic",
                "LastName": "Coach",
                "Shortname": "S. Coach",
            },
        )
    referees = ET.SubElement(information, "Referees")
    ET.SubElement(
        referees,
        "Referee",
        {
            "PersonId": "DFL-OBJ-R001",
            "Role": "referee",
            "FirstName": "Synthetic",
            "LastName": "Referee",
            "Shortname": "S. Referee",
        },
    )
    ET.SubElement(
        information,
        "OtherGameInformation",
        {
            "TotalTimeFirstHalf": "2400000",
            "TotalTimeSecondHalf": "2400000",
        },
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(str(path), encoding="UTF-8", xml_declaration=True)
    return path


def write_events(
    path: Path,
    *,
    kickoff_utc: datetime,
    half_end_utc: datetime,
    second_half_start_utc: datetime,
    match_end_utc: datetime,
) -> Path:
    """Structurally faithful event document, deliberately out of order."""
    root = _put_data_request()
    local = timezone(timedelta(hours=2))

    def event(
        event_id: str,
        when: datetime,
        x: float | None,
        y: float | None,
    ) -> ET.Element:
        attributes = {
            "EventId": event_id,
            "EventTime": when.astimezone(local).isoformat(),
            "MatchId": "DFL-MAT-SYNTH1",
        }
        if x is not None and y is not None:
            attributes.update(
                {
                    "X-Position": f"{x:.2f}",
                    "Y-Position": f"{y:.2f}",
                    "X-Source-Position": f"{x:.2f}",
                    "Y-Source-Position": f"{y:.2f}",
                }
            )
        return ET.Element("Event", attributes)

    # Deliberately non-chronological source order: the adapter must sort.
    first_kickoff = event(
        "SYN-EV-0001",
        kickoff_utc,
        None,
        None,
    )
    kickoff_payload = ET.SubElement(
        first_kickoff,
        "KickOff",
        {"TeamLeft": "DFL-CLU-00000H", "TeamRight": "DFL-CLU-00000A", "GameSection": "firstHalf"},
    )
    play = ET.SubElement(
        kickoff_payload,
        "Play",
        {
            "Team": "DFL-CLU-00000H",
            "Player": "DFL-OBJ-H002",
            "Recipient": "DFL-OBJ-H001",
            "Evaluation": "successfullyCompleted",
            "Height": "flat",
        },
    )
    ET.SubElement(play, "Pass", {"FreeKickLayup": "false"})

    shot = event("SYN-EV-0003", kickoff_utc + timedelta(seconds=30), 70.0, 20.0)
    shot_payload = ET.SubElement(
        shot,
        "ShotAtGoal",
        {
            "Team": "DFL-CLU-00000H",
            "Player": "DFL-OBJ-H001",
            "TypeOfShot": "rightLeg",
            "XG": "0.31",
        },
    )
    ET.SubElement(shot_payload, "SavedShot", {"GoalKeeper": "DFL-OBJ-A001"})

    deleted = event("SYN-EV-0004", kickoff_utc + timedelta(seconds=31), 71.0, 21.0)
    ET.SubElement(deleted, "Delete")

    half_end = event("SYN-EV-0005", half_end_utc, None, None)
    ET.SubElement(half_end, "FinalWhistle", {"GameSection": "firstHalf"})

    second_kickoff = event("SYN-EV-0006", second_half_start_utc, None, None)
    ET.SubElement(
        second_kickoff,
        "KickOff",
        {"TeamLeft": "DFL-CLU-00000A", "TeamRight": "DFL-CLU-00000H", "GameSection": "secondHalf"},
    )

    foul = event("SYN-EV-0002", kickoff_utc + timedelta(seconds=10), 40.0, 34.0)
    ET.SubElement(
        foul,
        "Foul",
        {
            "TeamFouler": "DFL-CLU-00000A",
            "TeamFouled": "DFL-CLU-00000H",
            "Fouler": "DFL-OBJ-A002",
            "Fouled": "DFL-OBJ-H001",
            "FoulType": "foul",
        },
    )

    match_end = event("SYN-EV-0007", match_end_utc, None, None)
    ET.SubElement(match_end, "FinalWhistle", {"GameSection": "secondHalf"})

    for element in (
        second_kickoff,
        deleted,
        match_end,
        foul,
        half_end,
        shot,
        first_kickoff,
    ):
        root.append(element)

    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(str(path), encoding="UTF-8", xml_declaration=True)
    return path


@dataclass(frozen=True, slots=True)
class SyntheticFrame:
    n: int
    t: datetime
    x: float
    y: float
    d: float = 0.0
    s: float = 1.0
    a: float = 0.0
    m: str = "1"
    z: float | None = None
    ball_possession: str | None = None
    ball_status: str | None = None
    omit_x: bool = False


def write_positions(
    path: Path,
    *,
    first_half_start: datetime,
    second_half_start: datetime,
    first_half_frames: int = 20,
    second_half_frames: int = 10,
) -> Path:
    """Structurally faithful positions document with deliberate defects.

    Defects (one each): a time/frame mismatch, a duplicate frame number and a
    missing coordinate -- so the quarantine rules are exercised.
    """
    root = _put_data_request()
    positions = ET.SubElement(root, "Positions", {"EventTime": first_half_start.isoformat()})
    metadata = ET.SubElement(
        positions, "MetaData", {"MatchId": "DFL-MAT-SYNTH1", "Type": "pitch-size"}
    )
    ET.SubElement(metadata, "PitchSize", {"X": "105.00", "Y": "68.00"})

    def frame_set(section: str, team_id: str, person_id: str, frames: list[SyntheticFrame]) -> None:
        element = ET.SubElement(
            positions,
            "FrameSet",
            {
                "GameSection": section,
                "MatchId": "DFL-MAT-SYNTH1",
                "TeamId": team_id,
                "PersonId": person_id,
            },
        )
        for frame in frames:
            attributes = {
                "N": str(frame.n),
                "T": (
                    frame.t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{frame.t.microsecond // 1000:03d}Z"
                ),
                "Y": f"{frame.y:.2f}",
                "D": f"{frame.d:.2f}",
                "S": f"{frame.s:.2f}",
                "A": f"{frame.a:.2f}",
                "M": frame.m,
            }
            if not frame.omit_x:
                attributes["X"] = f"{frame.x:.2f}"
            if frame.z is not None:
                attributes["Z"] = f"{frame.z:.2f}"
            if frame.ball_possession is not None:
                attributes["BallPossession"] = frame.ball_possession
            if frame.ball_status is not None:
                attributes["BallStatus"] = frame.ball_status
            ET.SubElement(element, "Frame", attributes)

    # First half: two players and the ball. The ball carries the defects.
    for index, (team_id, person_id) in enumerate(
        (("DFL-CLU-00000H", "DFL-OBJ-H001"), ("DFL-CLU-00000A", "DFL-OBJ-A002"))
    ):
        frames = [
            SyntheticFrame(
                n=10_000 + offset,
                t=first_half_start + FRAME_STEP * offset,
                x=float(index) + offset * 0.1,
                y=1.0,
                s=2.0,
            )
            for offset in range(first_half_frames)
        ]
        frame_set("firstHalf", team_id, person_id, frames)

    ball_frames: list[SyntheticFrame] = []
    for offset in range(first_half_frames):
        frame = SyntheticFrame(
            n=10_000 + offset,
            t=first_half_start + FRAME_STEP * offset,
            x=0.0,
            y=0.0,
            s=5.0,
            z=0.1 + offset * 0.01,
            ball_possession="1" if offset % 2 else "2",
            ball_status="1",
        )
        if offset == 4:
            frame = SyntheticFrame(
                n=10_004,
                t=first_half_start + FRAME_STEP * 4 + timedelta(milliseconds=300),
                x=0.0,
                y=0.0,
                s=5.0,
                z=0.2,
                ball_possession="1",
                ball_status="1",
            )
        elif offset == 6:
            frame = SyntheticFrame(
                n=10_005,  # duplicate frame number inside the entity stream
                t=first_half_start + FRAME_STEP * 5,
                x=0.0,
                y=0.0,
                s=5.0,
                z=0.2,
                ball_possession="2",
                ball_status="1",
            )
        elif offset == 8:
            frame = SyntheticFrame(
                n=10_008,
                t=first_half_start + FRAME_STEP * 8,
                x=0.0,
                y=0.0,
                s=5.0,
                z=0.3,
                ball_possession="1",
                ball_status="1",
                omit_x=True,
            )
        ball_frames.append(frame)
    frame_set("firstHalf", "BALL", "DFL-OBJ-B001", ball_frames)

    # A substitute joins late in the first half.
    substitute = [
        SyntheticFrame(
            n=10_000 + offset,
            t=first_half_start + FRAME_STEP * offset,
            x=-5.0,
            y=-5.0,
            s=3.0,
        )
        for offset in range(10, first_half_frames)
    ]
    frame_set("firstHalf", "DFL-CLU-00000H", "DFL-OBJ-H003", substitute)

    # Second half: two players and the ball, clean.
    for index, (team_id, person_id) in enumerate(
        (("DFL-CLU-00000H", "DFL-OBJ-H001"), ("DFL-CLU-00000A", "DFL-OBJ-A002"))
    ):
        frames = [
            SyntheticFrame(
                n=100_000 + offset,
                t=second_half_start + FRAME_STEP * offset,
                x=float(index) - offset * 0.05,
                y=-2.0,
                s=1.5,
            )
            for offset in range(second_half_frames)
        ]
        frame_set("secondHalf", team_id, person_id, frames)
    frame_set(
        "secondHalf",
        "BALL",
        "DFL-OBJ-B001",
        [
            SyntheticFrame(
                n=100_000 + offset,
                t=second_half_start + FRAME_STEP * offset,
                x=1.0,
                y=1.0,
                s=4.0,
                z=0.0,
                ball_possession="1",
                ball_status="0" if offset % 3 == 0 else "1",
            )
            for offset in range(second_half_frames)
        ],
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(str(path), encoding="UTF-8", xml_declaration=True)
    return path
