"""RES-99 scientific boundaries: no production kinematics, no reinterpretation.

The pose adapters canonicalize provider landmarks exactly: units are converted
and availability is preserved, but no joint angle, angular velocity, ROM,
inverse-dynamics result, smoothing or interpolation is computed, provider values
are never rescaled or shifted beyond the documented unit conversion, and
SkillCorner Z is never presented as an absolute player height.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import synthetic_skillcorner
import synthetic_spl
from dynamis.adapters.skillcorner.authorities import pitch_frame, pose_hybrid_frame
from dynamis.adapters.spl.adapter import SplTrialSource
from dynamis.adapters.spl.authorities import FEET_TO_METRE_SCALE
from dynamis.config import repository_root
from dynamis.contracts import AxisDirection
from dynamis.pipeline.ingest import ingest_skillcorner_match, ingest_spl_trials

FORBIDDEN_PROCESSOR_TOKENS = (
    "joint_angle",
    "jointangle",
    "angular_velocity",
    "inverse_dynamics",
    "range_of_motion",
    "rom_degrees",
    "savgol",
    "butterworth",
    "lowess",
)


@pytest.fixture(scope="module")
def skillcorner_bundle(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    return synthetic_skillcorner.write_skillcorner_bundle(
        tmp_path_factory.mktemp("skillcorner-boundaries")
    )


@pytest.fixture(scope="module")
def spl_bundle(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    return synthetic_spl.write_bundle(tmp_path_factory.mktemp("spl-boundaries"))


def test_pose_adapters_contain_no_production_kinematics_processors() -> None:
    root = repository_root() / "src" / "dynamis" / "adapters"
    offenders: list[str] = []
    for package in ("skillcorner", "spl"):
        for path in sorted((root / package).rglob("*.py")):
            text = path.read_text(encoding="utf-8").lower()
            for token in FORBIDDEN_PROCESSOR_TOKENS:
                if token in text:
                    offenders.append(f"{path.name}: {token}")
    assert offenders == [], f"RES-100 processors leaked into RES-99 adapters: {offenders}"


def test_skillcorner_pose_frame_declares_hybrid_z_not_pitch_registered() -> None:
    frame = pose_hybrid_frame()
    assert frame.z_direction is AxisDirection.UNSPECIFIED
    assert frame.handedness.value == "unspecified"
    description = frame.description or ""
    assert "centroid" in description
    assert "No hidden correction" in description
    # The tracking frame never asserts a global Z registration either.
    tracking = pitch_frame(105.0, 68.0)
    assert tracking.z_direction is AxisDirection.UNSPECIFIED


def test_skillcorner_pose_coordinates_pass_through_unchanged(
    tmp_settings, skillcorner_bundle: dict[str, Path]
) -> None:
    import pyarrow.parquet as pq

    result = ingest_skillcorner_match(
        tmp_settings,
        match_json_path=skillcorner_bundle["match_json"],
        tracking_path=skillcorner_bundle["tracking"],
        pose_zip_path=skillcorner_bundle["pose_zip"],
        version="synthetic",
    )
    streams = {item.stream_id: item for item in result.streams}
    table = pq.read_table(streams["pose-period-1"].absolute_path)
    source = synthetic_skillcorner.joints_for(player_id=101, frame=0)["nose"]["xyz"]
    row = next(
        item
        for item in table.to_pylist()
        if item["joint_name"] == "nose" and item["subject_id"] == "101"
    )
    assert (row["x_m"], row["y_m"], row["z_m"]) == (source[0], source[1], source[2])
    # The provider p90 radius is preserved in metres, not reinterpreted.
    assert row["error_m"] == pytest.approx(1.0 * 0.01)
    assert row["confidence"] is None


def test_spl_conversion_is_scale_only_with_no_offset_or_flip(
    tmp_settings, spl_bundle: dict[str, Path]
) -> None:
    import pyarrow.parquet as pq

    result = ingest_spl_trials(
        tmp_settings,
        trials=(
            SplTrialSource(key=synthetic_spl.KEY_2024, path=spl_bundle["trial_2024"]),
            SplTrialSource(key=synthetic_spl.KEY_2025, path=spl_bundle["trial_2025"]),
        ),
        version="synthetic",
    )
    streams = {item.stream_id: item for item in result.streams}
    table = pq.read_table(streams["pose-2024-08-28-T0001"].absolute_path)
    row = next(item for item in table.to_pylist() if item["joint_name"] == "NOSE")
    assert row["x_m"] == 1.0 * FEET_TO_METRE_SCALE
    assert row["y_m"] == 2.0 * FEET_TO_METRE_SCALE
    assert row["z_m"] == 3.0 * FEET_TO_METRE_SCALE
    # The only transformation is the exact scale: no offset was added.
    assert row["x_m"] != 1.0
