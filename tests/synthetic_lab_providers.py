"""Structurally synthetic laboratory-provider fixtures for CI.

Nothing here is copied from the real sources: the fixtures mirror the *structure*
that was discovered in the verified White CMJ ``.npz`` release and the GymAware
``LP_data.zip`` archive, with invented values. They exist so the NPZ/ZIP safety
gates, the strict discovery contracts, the adapters and the reconciliation
arithmetic are exercised without any real dataset entering CI.
"""

from __future__ import annotations

import io
import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import openpyxl

# ---------------------------------------------------------------------------
# White CMJ NPZ fixtures
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WhiteTrialSpec:
    subject_index: int
    original_participant_id: int
    condition_label: int
    acc_samples: int
    grf_samples: int
    acc_takeoff: int
    acc_columns: int = 3
    accel_scale: float = 1.0
    nan_at: int | None = None
    jump_height: float = 0.30
    peak_power: float = 40.0


DEFAULT_WHITE_TRIALS: tuple[WhiteTrialSpec, ...] = (
    WhiteTrialSpec(0, 11, 1, 300, 200, 100),
    WhiteTrialSpec(0, 11, 2, 250, 150, 80, accel_scale=1.2),
    WhiteTrialSpec(1, 12, 1, 260, 170, 90, acc_columns=2),
    WhiteTrialSpec(1, 12, 2, 260, 0, 90),
    WhiteTrialSpec(2, 13, 1, 240, 160, 70, nan_at=10),
    WhiteTrialSpec(2, 13, 2, 245, 165, 75),
)


def _synthetic_acc(spec: WhiteTrialSpec) -> np.ndarray:
    steps = np.arange(spec.acc_samples, dtype=np.float64)
    columns = np.empty((spec.acc_samples, spec.acc_columns), dtype=np.float32)
    for axis in range(spec.acc_columns):
        columns[:, axis] = spec.accel_scale * np.sin(steps / (17.0 + axis))
    if spec.nan_at is not None:
        columns[spec.nan_at, 0] = np.nan
    return columns


def _synthetic_grf(spec: WhiteTrialSpec) -> np.ndarray:
    if spec.grf_samples == 0:
        return np.empty(0, dtype=np.float32)
    steps = np.linspace(1.0, 0.0, spec.grf_samples)
    return (steps * 2.0).astype(np.float32)


def write_white_npz(
    path: Path,
    trials: tuple[WhiteTrialSpec, ...] = DEFAULT_WHITE_TRIALS,
    *,
    declared_n_subjects: int | None = None,
) -> Path:
    """Write a structurally faithful synthetic White-style ``.npz`` release."""
    count = len(trials)
    acc_signals = np.empty(count, dtype=object)
    grf_signals = np.empty(count, dtype=object)
    for index, spec in enumerate(trials):
        acc_signals[index] = _synthetic_acc(spec)
        grf_signals[index] = _synthetic_grf(spec)
    unique_subjects = sorted({spec.subject_index for spec in trials})
    np.savez(
        path,
        acc_signals=acc_signals,
        acc_takeoff=np.array([spec.acc_takeoff for spec in trials], dtype=np.int32),
        grf_signals=grf_signals,
        # Mirrors the real release: an original-source index, not an offset into
        # the distributed pre-takeoff vGRF array.
        grf_takeoff=np.array(
            [spec.grf_samples + 500 + spec.acc_takeoff for spec in trials], dtype=np.int32
        ),
        subject_ids=np.array([spec.subject_index for spec in trials], dtype=np.int32),
        original_participant_ids=np.array(
            [spec.original_participant_id for spec in trials], dtype=np.int32
        ),
        jump_height=np.array([spec.jump_height for spec in trials], dtype=np.float32),
        peak_power=np.array([spec.peak_power for spec in trials], dtype=np.float32),
        condition_labels=np.array([spec.condition_label for spec in trials], dtype=np.int32),
        acc_sampling_rate=np.int32(250),
        grf_sampling_rate=np.int32(1000),
        n_subjects=np.int32(
            declared_n_subjects if declared_n_subjects is not None else len(unique_subjects)
        ),
        allow_pickle=True,
    )
    return path


def write_white_npz_with_unsafe_object(path: Path) -> Path:
    """An NPZ whose object member carries a non-array, pickle-only payload."""

    class UnsafePayload:
        def __reduce__(self):
            return (os.system, ("echo unsafe",))

    acc_signals = np.empty(1, dtype=object)
    acc_signals[0] = UnsafePayload()
    grf_signals = np.empty(1, dtype=object)
    grf_signals[0] = np.zeros(10, dtype=np.float32)
    np.savez(
        path,
        acc_signals=acc_signals,
        acc_takeoff=np.array([5], dtype=np.int32),
        grf_signals=grf_signals,
        grf_takeoff=np.array([510], dtype=np.int32),
        subject_ids=np.array([0], dtype=np.int32),
        original_participant_ids=np.array([1], dtype=np.int32),
        jump_height=np.array([0.3], dtype=np.float32),
        peak_power=np.array([40.0], dtype=np.float32),
        condition_labels=np.array([1], dtype=np.int32),
        acc_sampling_rate=np.int32(250),
        grf_sampling_rate=np.int32(1000),
        n_subjects=np.int32(1),
        allow_pickle=True,
    )
    return path


def write_white_npz_with_string_object(path: Path) -> Path:
    """An object member holding strings (numeric-contract violation, still pickle)."""
    acc_signals = np.empty(1, dtype=object)
    acc_signals[0] = "not-an-array"
    grf_signals = np.empty(1, dtype=object)
    grf_signals[0] = np.zeros(10, dtype=np.float32)
    np.savez(
        path,
        acc_signals=acc_signals,
        acc_takeoff=np.array([5], dtype=np.int32),
        grf_signals=grf_signals,
        grf_takeoff=np.array([510], dtype=np.int32),
        subject_ids=np.array([0], dtype=np.int32),
        original_participant_ids=np.array([1], dtype=np.int32),
        jump_height=np.array([0.3], dtype=np.float32),
        peak_power=np.array([40.0], dtype=np.float32),
        condition_labels=np.array([1], dtype=np.int32),
        acc_sampling_rate=np.int32(250),
        grf_sampling_rate=np.int32(1000),
        n_subjects=np.int32(1),
        allow_pickle=True,
    )
    return path


# ---------------------------------------------------------------------------
# GymAware ZIP fixtures
# ---------------------------------------------------------------------------

GYMAWARE_CSV_HEADER_MEAN_FIRST = (
    "Row Type,Rep Number,Conc Mean Velocity,Conc Peak Velocity (m/s),"
    "Conc Peak Power (W),Conc Mean Power (W),Conc Peak Force (N),Conc Mean Force (N)"
)
GYMAWARE_CSV_HEADER_PEAK_FIRST = (
    "Row Type,Rep Number,Conc Peak Velocity (m/s),Conc Mean Velocity,"
    "Conc Peak Power (W),Conc Mean Power (W),Conc Peak Force (N),Conc Mean Force (N)"
)

VISION_SHEETS: tuple[tuple[str, str], ...] = (
    ("平均速度", "mean_velocity"),
    ("峰值速度", "peak_velocity"),
    ("峰值功率", "peak_power"),
    ("平均功率", "mean_power"),
    ("峰值力", "peak_force"),
    ("平均力", "mean_force"),
)


def gymaware_csv(
    *,
    set_id: int,
    reps: tuple[tuple[float, float, float, float, float, float], ...],
    load_kg: float | None = 20.0,
    activity: str = "Landmine Throw (Right)",
    peak_first: bool = False,
    malformed_row: str | None = None,
    include_row_type_header: bool = True,
) -> bytes:
    lines = [
        "first name: Synthetic,last name: Fixture,date: 2026-01-01,time: 09:00,"
        f"exercise: {activity},set id: {set_id},body weight (kg): 0.0,body weight %: 0,"
        f"bar weight (kg): {load_kg},total weight (kg): {load_kg},notes: ,"
        "sensor: g.test,hardware: 20"
    ]
    if include_row_type_header:
        lines.append(
            GYMAWARE_CSV_HEADER_PEAK_FIRST if peak_first else GYMAWARE_CSV_HEADER_MEAN_FIRST
        )
    for number, values in enumerate(reps, start=1):
        mean, peak, peak_power, mean_power, peak_force, mean_force = values
        cells = (
            (mean, peak, peak_power, mean_power, peak_force, mean_force)
            if not peak_first
            else (peak, mean, peak_power, mean_power, peak_force, mean_force)
        )
        lines.append(f"Rep,{number}," + ",".join(f"{value:g}" for value in cells))
    if malformed_row is not None:
        lines.append(malformed_row)
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_vision_workbook(
    path: Path,
    *,
    rows: tuple[
        tuple[int, str, str, object, int, tuple[float | None, float | None, float | None]], ...
    ],
) -> Path:
    """Write a synthetic vision workbook mirroring the discovered layout."""
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.worksheets[0])
    for sheet_name, _metric in VISION_SHEETS:
        sheet = workbook.create_sheet(title=sheet_name)
        sheet.append(("纳入编号", "姓名", "测试动作", "负重", "测试次数", "REP1", "RPE2", "REP3"))
        for inclusion, name, activity, load, rep_count, values in rows:
            sheet.append((inclusion, name, activity, load, rep_count, *values))
    workbook.save(path)
    workbook.close()
    return path


@dataclass(frozen=True, slots=True)
class GymAwareFixtureSpec:
    """One synthetic set export plus its vision-workbook row."""

    set_number: int
    display_name: str
    activity: str
    load_raw: str
    reps: tuple[tuple[float, float, float, float, float, float], ...]
    vision_rep_values: tuple[float | None, float | None, float | None] | None = None
    peak_first: bool = False
    malformed_row: str | None = None
    has_export: bool = True
    extra_members: tuple[tuple[str, bytes], ...] = field(default_factory=tuple)


DEFAULT_GYMAWARE_SETS: tuple[GymAwareFixtureSpec, ...] = (
    GymAwareFixtureSpec(
        set_number=1,
        display_name="Synthetic Alpha",
        activity="站姿",
        load_raw="20kg",
        reps=(
            (1.0, 1.5, 300.0, 150.0, 400.0, 200.0),
            (1.1, 1.6, 320.0, 160.0, 410.0, 205.0),
            (1.2, 1.7, 340.0, 170.0, 420.0, 210.0),
        ),
        vision_rep_values=(1.05, 1.55, 330.0),
    ),
    GymAwareFixtureSpec(
        set_number=2,
        display_name="Synthetic Alpha",
        activity="站姿",
        load_raw="25kg",
        reps=((0.9, 1.4, 280.0, 140.0, 380.0, 190.0), (0.95, 1.45, 290.0, 145.0, 390.0, 195.0)),
        vision_rep_values=(0.92, 1.42, 285.0),
        peak_first=True,
    ),
    GymAwareFixtureSpec(
        set_number=3,
        display_name="Synthetic Beta",
        activity="跪姿",
        load_raw="30",
        reps=(),
        malformed_row="Rep,not-a-number,1.0,1.0,1.0,1.0,1.0,1.0",
        vision_rep_values=(None, None, None),
    ),
    GymAwareFixtureSpec(
        set_number=4,
        display_name="Synthetic Beta",
        activity="跪姿",
        load_raw="35kg",
        reps=(),
        vision_rep_values=(None, None, None),
    ),
    GymAwareFixtureSpec(
        set_number=5,
        display_name="Synthetic Gamma",
        activity="释放",
        load_raw="20",
        reps=(),
        vision_rep_values=(None, None, None),
        has_export=False,
    ),
)


def write_gymaware_zip(
    path: Path,
    *,
    sets: tuple[GymAwareFixtureSpec, ...] = DEFAULT_GYMAWARE_SETS,
    workbook_path: Path | None = None,
    unsafe_members: bool = False,
) -> Path:
    """Write a synthetic GymAware-style archive with the discovered structure."""
    temp_workbook = workbook_path or path.with_suffix(".tmp.xlsx")
    rows = tuple(
        (
            spec.set_number,
            spec.display_name,
            spec.activity,
            spec.load_raw,
            len(spec.reps),
            spec.vision_rep_values or (None, None, None),
        )
        for spec in sets
    )
    write_vision_workbook(temp_workbook, rows=rows)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("LP_data/", b"")
        for spec in sets:
            if not spec.has_export:
                continue
            archive.writestr(
                f"LP_data/GymAware_rawdata/{spec.set_number:03d}.csv",
                gymaware_csv(
                    set_id=1000 + spec.set_number,
                    reps=spec.reps,
                    load_kg=float(spec.load_raw.rstrip("kg")) if spec.load_raw else None,
                    peak_first=spec.peak_first,
                    malformed_row=spec.malformed_row,
                    include_row_type_header=bool(spec.reps) or spec.malformed_row is None,
                ),
            )
        archive.writestr(
            "LP_data/GA_vision_data.xlsx",
            temp_workbook.read_bytes(),
        )
        archive.writestr("LP_data/LP_yolo_python/demo/001.MP4", b"\x00\x00\x00\x18ftypmp42")
        archive.writestr("LP_data/LP_yolo_python/runs/detect/best.pt", b"\x00" * 64)
        if unsafe_members:
            archive.writestr("../escape.csv", b"a,b\n1,2\n")
    if workbook_path is None:
        temp_workbook.unlink(missing_ok=True)
    return path


def write_gymaware_zip_with_crlf(path: Path) -> Path:
    """A GymAware-style archive whose set CSV uses CP1252-style metadata bytes."""
    content = gymaware_csv(set_id=2000, reps=((1.0, 1.0, 100.0, 50.0, 200.0, 100.0),))
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("LP_data/GymAware_rawdata/001.csv", content)
        workbook = path.with_suffix(".tmp.xlsx")
        write_vision_workbook(
            workbook,
            rows=((1, "Synthetic Alpha", "站姿", "20kg", 1, (1.0, 1.0, 100.0)),),
        )
        archive.writestr("LP_data/GA_vision_data.xlsx", workbook.read_bytes())
    workbook.unlink(missing_ok=True)
    return path


def write_traversal_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("LP_data/GymAware_rawdata/001.csv", b"x")
        archive.writestr("LP_data/GA_vision_data.xlsx", b"x")
        archive.writestr("../outside.csv", b"x")
    return path


def write_absolute_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        info = zipfile.ZipInfo("/LP_data/GA_vision_data.xlsx")
        archive.writestr(info, b"x")
    return path


def write_drive_qualified_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        info = zipfile.ZipInfo("C:/LP_data/GA_vision_data.xlsx")
        archive.writestr(info, b"x")
    return path


def write_duplicate_member_zip(path: Path) -> Path:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("LP_data/GA_vision_data.xlsx", b"first")
            archive.writestr("LP_data/GA_vision_data.xlsx", b"second")
    return path


def write_symlink_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        info = zipfile.ZipInfo("LP_data/link.csv")
        info.external_attr = (0o120777 << 16) | 0o777
        archive.writestr(info, b"target")
    return path


def write_expansion_bomb_zip(path: Path) -> Path:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as inner:
        inner.writestr("LP_data/GymAware_rawdata/001.csv", b"\x00" * (2 << 20))
    path.write_bytes(payload.getvalue())
    return path
