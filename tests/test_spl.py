"""SPL free-throw adapter: registry, feet conversion, session-specific landmarks.

All tests are synthetic: the structurally synthetic trials mirror the documented
provider structure, and no real SPL source is downloaded. Real SPL acquisition
remains gated on the explicit operator acknowledgement flag and is never
exercised by CI.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest

import synthetic_spl
from dynamis.adapters.spl.adapter import SplFreethrowAdapter, SplTrialSource
from dynamis.adapters.spl.authorities import (
    FEET_TO_METRE_SCALE,
    SPL_KEYPOINTS,
    SPL_SESSION_RATES_HZ,
)
from dynamis.adapters.spl.trial import SplTrialError, identity_from_key, sampling_rate_for
from dynamis.contracts import MeasurementClass, Modality, SkeletonTopology
from dynamis.pipeline.ingest import ingest_spl_trials
from dynamis.quality.checks import validate
from dynamis.registry import SPL_DATASET_ID, source_by_id, validate_registry


@pytest.fixture(scope="module")
def bundle(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    return synthetic_spl.write_bundle(tmp_path_factory.mktemp("spl"))


def _sources(bundle: dict[str, Path]) -> tuple[SplTrialSource, ...]:
    return (
        SplTrialSource(key=synthetic_spl.KEY_2024, path=bundle["trial_2024"]),
        SplTrialSource(key=synthetic_spl.KEY_2025, path=bundle["trial_2025"]),
    )


def test_discovery_absence_counts_agree_with_canonicalization(tmp_path: Path) -> None:
    import json

    from dynamis.adapters.spl.discovery import discover_spl
    from dynamis.adapters.spl.trial import SplTrialCanonicalizer, identity_from_key

    frames = [
        {"data": {"player": {"NOSE": [1.0, 1.0, 1.0], "LEFT_KNEE": [1.0, 1.0, 0.5]}, "ball": None}},
        # MID_HIP appears only from this frame onward; a growing-seen count would
        # miss its absence in frame 0.
        {"data": {"player": {"NOSE": None, "MID_HIP": [1.0, 1.0, 1.0]}, "ball": None}},
    ]
    path = tmp_path / "BB_FT_P0001_T0001.json"
    path.write_text(json.dumps({"tracking": frames}), encoding="utf-8")
    source = SplTrialSource(key=synthetic_spl.KEY_2024, path=path)

    discovery = discover_spl((source,)).to_dict()["trials"][0]
    assert discovery["observed_keypoints"] == 3
    assert discovery["missing_keypoint_observations"] == {
        "LEFT_KNEE": 1,
        "MID_HIP": 1,
    }
    canonicalizer = SplTrialCanonicalizer(path, identity_from_key(source.key))
    stream = canonicalizer.stream()
    list(stream.batches)
    summary = canonicalizer.summary()
    assert summary.absent_keypoint_observations == 2
    assert summary.unavailable_keypoints == 3  # 2 absent + 1 explicit null
    assert summary.source_records == summary.canonical_rows


def test_registry_declares_the_two_locked_trials_exactly() -> None:
    registry = validate_registry()
    source = source_by_id(registry, SPL_DATASET_ID)
    version = source.versions[0]
    assert version.version == "a3f9cffbde917b1e1747cedd6ec25dfab18c6051"
    files = {item.key: item for item in version.retrieval.files}
    assert set(files) == {synthetic_spl.KEY_2024, synthetic_spl.KEY_2025}
    assert files[synthetic_spl.KEY_2024].size_bytes == 1716672
    assert files[synthetic_spl.KEY_2024].sha1 == "6e74a8a1defaed0979ef0065089ca0d6a572103c"
    assert files[synthetic_spl.KEY_2025].size_bytes == 2385805
    assert files[synthetic_spl.KEY_2025].sha1 == "7ca18fac37806137fd3cd559f5c0ecd8339db5aa"
    assert all(item.upstream_provider == "github" for item in files.values())
    assert all(item.upstream_revision is None for item in files.values())


def test_identity_and_rate_are_derived_from_the_locked_key() -> None:
    identity = identity_from_key(synthetic_spl.KEY_2024)
    assert identity.session_date == "2024-08-28"
    assert identity.participant_id == "P0001"
    assert identity.trial_id == "T0001"
    assert sampling_rate_for("2024-08-28") == 30.0
    assert sampling_rate_for("2025-12-18") == 60.0
    assert SPL_SESSION_RATES_HZ == {"2024-08-28": 30.0, "2025-12-18": 60.0}
    with pytest.raises(SplTrialError, match="documented sampling rate"):
        sampling_rate_for("2030-01-01")
    with pytest.raises(SplTrialError, match="trial key"):
        identity_from_key("basketball/freethrow/data/2024-08-28/P0001/other.json")


def test_adapter_keeps_one_participant_across_sessions(bundle: dict[str, Path]) -> None:
    adapter = SplFreethrowAdapter(trials=_sources(bundle), version="synthetic")
    domain = adapter.domain()
    assert {subject.subject_id for subject in domain.subjects} == {"P0001"}
    assert {session.session_id for session in domain.all_sessions} == {
        "2024-08-28",
        "2025-12-18",
    }
    assert {participant.session_id for participant in domain.participants} == {
        "2024-08-28",
        "2025-12-18",
    }
    assert {trial.trial_id for trial in domain.trials} == {"T0001"}
    assert all(trial.subject_id == "P0001" for trial in domain.trials)
    pose_streams = [stream for stream in domain.streams if stream.modality is Modality.POSE]
    assert len(pose_streams) == 2
    assert all(
        stream.data_grain is not None
        and stream.data_grain.axes == ("subject", "trial", "sample_index", "joint")
        for stream in pose_streams
    )
    assert all(
        stream.measurement_class is MeasurementClass.MODEL_ESTIMATED for stream in pose_streams
    )
    skeletons = {skeleton.skeleton_id: skeleton for skeleton in domain.authorities.skeletons}
    assert len(skeletons) == 2
    for skeleton in skeletons.values():
        assert skeleton.topology is SkeletonTopology.LANDMARK_SET
        assert all(joint.parent_joint_id is None for joint in skeleton.joints)
    assert len(domain.authorities.clocks) == 2
    assert len(domain.authorities.alignments) == 0  # sessions are never synchronized


def test_synthetic_spl_ingest_converts_feet_exactly_and_preserves_availability(
    tmp_settings, bundle: dict[str, Path]
) -> None:
    result = ingest_spl_trials(
        tmp_settings,
        trials=_sources(bundle),
        version="synthetic",
    )
    assert result.reconciliation.all_balanced
    streams = {item.stream_id: item for item in result.streams}
    assert set(streams) == {
        "pose-2024-08-28-T0001",
        "pose-2025-12-18-T0001",
    }
    rate_2024 = streams["pose-2024-08-28-T0001"].row_count
    # 3 frames x 6 keypoints, all canonical (2 explicitly unavailable rows).
    assert rate_2024 == 18
    # 4 frames x 14 keypoints (12 documented session names + RIGHT_WRIST null
    # observation + 1 undocumented name).
    assert streams["pose-2025-12-18-T0001"].row_count == 56

    table = pq.read_table(streams["pose-2024-08-28-T0001"].absolute_path)
    assert validate(table, table.schema) == ()
    assert set(table.column("measurement_class").to_pylist()) == {"MODEL_ESTIMATED"}
    rows = table.to_pylist()
    nose = next(row for row in rows if row["joint_name"] == "NOSE")
    assert nose["x_m"] == 1.0 * FEET_TO_METRE_SCALE
    assert nose["y_m"] == 2.0 * FEET_TO_METRE_SCALE
    assert nose["z_m"] == 3.0 * FEET_TO_METRE_SCALE
    assert nose["parent_joint_id"] is None
    unavailable = [row for row in rows if not row["is_available"]]
    assert len(unavailable) == 2
    names = {row["joint_name"] for row in unavailable}
    assert names == {"LEFT_ANKLE", "NECK"}
    for row in unavailable:
        assert row["x_m"] is None and row["y_m"] is None and row["z_m"] is None
    order = [row["joint_name"] for row in rows[:6]]
    assert order == list(synthetic_spl.KEYPOINTS_2024)
    assert [row["t_rel_ns"] for row in rows[:6]] == [0] * 6
    assert rows[6]["t_rel_ns"] == round(1_000_000_000 / 30.0)

    trial_2025 = next(
        item
        for item in result.reconciliation.domain["trials"]
        if item["session_date"] == "2025-12-18"
    )
    assert trial_2025["undocumented_keypoints"] == [synthetic_spl.UNDOCUMENTED_2025]
    assert trial_2025["keypoint_count"] == 14
    assert trial_2025["unavailable_keypoints"] == 5  # 1 explicit null + 4 absent
    assert trial_2025["absent_keypoint_observations"] == 4
    assert trial_2025["observed_keypoints"] == 51
    assert trial_2025["sampling_rate_hz"] == 60.0
    assert trial_2025["conversion"].startswith("value_m = value_ft * 0.3048")
    assert trial_2025["topology"].startswith("landmark_set")
    documented = [name for name in SPL_KEYPOINTS if name in set(trial_2025["keypoints"])]
    assert trial_2025["keypoints"][: len(documented)] == documented


def test_spl_receipt_reports_participant_identity_and_rates(
    tmp_settings, bundle: dict[str, Path]
) -> None:
    result = ingest_spl_trials(tmp_settings, trials=_sources(bundle), version="synthetic")
    domain = result.reconciliation.domain
    assert domain["participant_ids"] == ["P0001"]
    assert domain["participant_identity_consistent_across_sessions"] is True
    assert domain["sessions"] == ["2024-08-28", "2025-12-18"]
    assert domain["rates_hz"] == {"2024-08-28": 30.0, "2025-12-18": 60.0}
    assert domain["cross_session_synchronization"] is False
    assert domain["feet_to_metre_scale"] == 0.3048
    assert len(domain["skeletons"]) == 2
