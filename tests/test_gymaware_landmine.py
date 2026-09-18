"""GymAware landmine provider: ZIP security, discovery, source-metric import.

All fixtures are structurally synthetic; no real archive bytes enter CI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import synthetic_lab_providers as providers
from dynamis.adapters.gymaware_landmine.adapter import GymAwareAdapter
from dynamis.adapters.gymaware_landmine.authorities import (
    GYMAWARE_DATASET_ID,
    GYMAWARE_EFFECTIVE_RADIUS_M,
    VISION_EFFECTIVE_RADIUS_M,
    VISION_WORKBOOK_KEY,
)
from dynamis.adapters.gymaware_landmine.discovery import (
    GymAwareSourceError,
    discover_gymaware_landmine,
    parse_gymaware_csv,
)
from dynamis.adapters.gymaware_landmine.zip_safety import (
    ZipSecurityError,
    inspect_zip,
    read_member_bytes,
    sha256_member,
    structured_members,
)
from dynamis.config import Settings
from dynamis.pipeline.ingest import ingest_gymaware_landmine
from dynamis.storage.paths import receipt_path


@pytest.fixture
def gymaware_zip(tmp_path: Path) -> Path:
    return providers.write_gymaware_zip(tmp_path / "LP_data_synthetic.zip")


def test_central_directory_is_inspected_without_extraction(gymaware_zip: Path) -> None:
    inspection = inspect_zip(gymaware_zip)
    assert inspection.archive_name == "LP_data_synthetic.zip"
    assert inspection.extension_counts[".csv"] == 4
    assert inspection.extension_counts[".xlsx"] == 1
    assert inspection.extension_counts[".mp4"] == 1
    assert inspection.root_entries == ("LP_data",)
    members = structured_members(inspection)
    assert {member.normalized_name for member in members} == {
        "LP_data/GymAware_rawdata/001.csv",
        "LP_data/GymAware_rawdata/002.csv",
        "LP_data/GymAware_rawdata/003.csv",
        "LP_data/GymAware_rawdata/004.csv",
        VISION_WORKBOOK_KEY,
    }
    first_hash = sha256_member(gymaware_zip, "LP_data/GymAware_rawdata/001.csv")
    assert first_hash == sha256_member(gymaware_zip, "LP_data/GymAware_rawdata/001.csv")
    assert len(first_hash) == 64


@pytest.mark.parametrize(
    "writer",
    [
        providers.write_traversal_zip,
        providers.write_absolute_zip,
        providers.write_drive_qualified_zip,
        providers.write_duplicate_member_zip,
        providers.write_symlink_zip,
        providers.write_expansion_bomb_zip,
    ],
)
def test_unsafe_archives_are_rejected(tmp_path: Path, writer) -> None:
    path = writer(tmp_path / "unsafe.zip")
    with pytest.raises(ZipSecurityError):
        inspect_zip(path)


def test_selected_member_read_is_bounded(gymaware_zip: Path) -> None:
    with pytest.raises(ZipSecurityError, match="exceeds"):
        read_member_bytes(gymaware_zip, "LP_data/GymAware_rawdata/001.csv", max_bytes=10)


def test_csv_parsing_handles_column_order_and_encoding(tmp_path: Path) -> None:
    peak_first = parse_gymaware_csv(
        "LP_data/GymAware_rawdata/002.csv",
        providers.gymaware_csv(
            set_id=1,
            reps=((1.0, 1.5, 300.0, 150.0, 400.0, 200.0),),
            peak_first=True,
        ),
    )
    assert peak_first.reps[0].values["mean_velocity"] == 1.0
    assert peak_first.reps[0].values["peak_velocity"] == 1.5

    encoded = providers.gymaware_csv(
        set_id=2,
        reps=((1.0, 1.5, 300.0, 150.0, 400.0, 200.0),),
    ).replace(b"Synthetic", "合成".encode("gb18030"))
    gb18030 = parse_gymaware_csv("LP_data/GymAware_rawdata/001.csv", encoded)
    assert gb18030.reps[0].values["peak_power"] == 300.0


def test_discovery_reports_summary_only_granularity(gymaware_zip: Path) -> None:
    discovery = discover_gymaware_landmine(gymaware_zip)
    report = discovery.to_dict()
    assert report["gymaware"]["set_count"] == 4
    assert report["gymaware"]["rep_rows"] == 5
    assert report["gymaware"]["sample_level_trajectory_present"] is False
    assert report["vision"]["populated_value_count"] == 36
    assert report["vision"]["populated_row_count"] == 2
    assert report["vision"]["subject_count"] == 3
    assert report["vision"]["inclusion_numbers"] == [1, 2, 3, 4, 5]
    assert discovery.gymaware_rep_rows == 5
    assert len(discovery.structured_member_hashes) == 5


def test_adapter_imports_metrics_and_fabricates_no_dense_lpt(gymaware_zip: Path) -> None:
    discovery = discover_gymaware_landmine(gymaware_zip)
    adapter = GymAwareAdapter(discovery)
    assert len(adapter.trials) == 5
    assert adapter.excluded_sets == {
        5: (
            "vision workbook row present, but no GymAware set export and no numeric "
            "value distributed for any metric"
        )
    }
    observations = adapter.observations()
    gymaware = [item for item in observations if item.metric_id.startswith("gymaware_")]
    vision = [item for item in observations if item.metric_id.startswith("vision_")]
    assert len(gymaware) == 30  # 5 reps x 6 metrics
    assert len(vision) == 30  # 30 distributed vision cells; six lack a paired rep
    assert all(item.si_unit in {"m/s", "W", "N"} for item in observations)
    assert all(item.measurement_class.value == "SOURCE_DERIVED" for item in observations)
    rules = {record.rule for record in adapter.counters.quarantined}
    assert rules == {"schema_failure", "missing_pairing"}
    domain = adapter.domain()
    assert domain.streams == ()
    assert domain.session_metadata["dense_lpt_stream_present"] is False
    assert domain.session_metadata["method_metadata"]["vision_effective_radius_m"] == (
        VISION_EFFECTIVE_RADIUS_M
    )
    assert domain.session_metadata["method_metadata"]["gymaware_effective_radius_m"] == (
        GYMAWARE_EFFECTIVE_RADIUS_M
    )
    assert domain.session_metadata["method_metadata"]["correction_applied"] is False


def test_paired_trial_identity_is_shared_by_both_methods(gymaware_zip: Path) -> None:
    adapter = GymAwareAdapter(discover_gymaware_landmine(gymaware_zip))
    paired = [item for item in adapter.observations() if item.trial_id == "ga-t001-r01"]
    methods = {item.provenance["method"] for item in paired}
    assert methods == {"gymaware-rs", "vision-tracking"}
    assert {item.metric_id for item in paired} == {
        "gymaware_mean_velocity",
        "gymaware_peak_velocity",
        "gymaware_peak_power",
        "gymaware_mean_power",
        "gymaware_peak_force",
        "gymaware_mean_force",
        "vision_mean_velocity",
        "vision_peak_velocity",
        "vision_peak_power",
        "vision_mean_power",
        "vision_peak_force",
        "vision_mean_force",
    }


def test_ingest_reconciles_sets_reps_and_metric_values(
    tmp_settings: Settings, gymaware_zip: Path
) -> None:
    result = ingest_gymaware_landmine(tmp_settings, zip_path=gymaware_zip, version="v1")
    receipt = result.reconciliation
    assert receipt.all_balanced
    balances = {stream.stream_id: stream for stream in receipt.streams}
    assert balances["gymaware-sets"].source_records == 5
    assert balances["gymaware-sets"].canonical_rows == 4
    assert balances["gymaware-sets"].ignored_records == 1
    assert balances["gymaware-rep-rows"].source_records == 6
    assert balances["gymaware-rep-rows"].canonical_rows == 5
    assert balances["gymaware-rep-rows"].quarantined_rows == 1
    assert balances["gymaware-metric-values"].source_records == 30
    assert balances["gymaware-metric-values"].canonical_rows == 30
    assert balances["vision-metric-values"].source_records == 36
    assert balances["vision-metric-values"].canonical_rows == 30
    assert balances["vision-metric-values"].quarantined_rows == 6
    assert len(result.source_metrics) == 60
    assert result.streams == ()
    assert len(result.quarantine_artifacts) == 2


def test_receipt_and_metrics_never_persist_source_display_names(
    tmp_settings: Settings, gymaware_zip: Path
) -> None:
    result = ingest_gymaware_landmine(tmp_settings, zip_path=gymaware_zip, version="v1")
    serialized = json.dumps(result.to_dict(), sort_keys=True)
    assert "Synthetic Alpha" not in serialized
    assert "Synthetic Beta" not in serialized
    assert "Synthetic Gamma" not in serialized
    receipt = receipt_path(
        tmp_settings,
        dataset_id=GYMAWARE_DATASET_ID,
        kind="reconciliation",
        name="gymaware-landmine-release",
    )
    assert receipt.is_file()
    assert str(tmp_settings.dataset_root) not in receipt.read_text(encoding="utf-8")
    for observation in result.source_metrics:
        assert "Synthetic" not in json.dumps(observation.origin_provenance)


def test_metric_import_is_idempotent_by_identity(
    tmp_settings: Settings, gymaware_zip: Path
) -> None:
    first = ingest_gymaware_landmine(tmp_settings, zip_path=gymaware_zip, version="v1")
    second = ingest_gymaware_landmine(tmp_settings, zip_path=gymaware_zip, version="v1")
    identity = [
        (item.metric_id, item.trial_id, item.value, item.si_unit) for item in first.source_metrics
    ]
    assert identity == [
        (item.metric_id, item.trial_id, item.value, item.si_unit) for item in second.source_metrics
    ]
    assert [item.derived_metric_id for item in first.source_metrics] == [
        item.derived_metric_id for item in second.source_metrics
    ]


def test_partially_malformed_set_keeps_valid_reps_and_quarantines_the_bad_one(
    tmp_path: Path,
) -> None:
    archive = providers.write_gymaware_zip(
        tmp_path / "LP_partial.zip",
        sets=(
            providers.GymAwareFixtureSpec(
                set_number=1,
                display_name="Synthetic Alpha",
                activity="站姿",
                load_raw="20kg",
                reps=(
                    (1.0, 1.5, 300.0, 150.0, 400.0, 200.0),
                    (1.1, 1.6, 320.0, 160.0, 410.0, 205.0),
                ),
                malformed_row="Rep,not-a-number,1.0,1.0,1.0,1.0,1.0,1.0",
                vision_rep_values=(1.0, 1.5, 300.0),
            ),
        ),
    )
    adapter = GymAwareAdapter(discover_gymaware_landmine(archive))
    assert adapter.counters.source_rep_rows == 3
    assert adapter.counters.canonical_trials == 2
    assert adapter.counters.quarantined_rep_rows == 1
    rules = {record.rule for record in adapter.counters.quarantined}
    assert rules == {"schema_failure"}


def test_non_finite_metric_value_is_quarantined(tmp_path: Path) -> None:
    nan = float("nan")
    archive = providers.write_gymaware_zip(
        tmp_path / "LP_nan.zip",
        sets=(
            providers.GymAwareFixtureSpec(
                set_number=1,
                display_name="Synthetic Alpha",
                activity="站姿",
                load_raw="20kg",
                reps=((1.0, 1.5, nan, 150.0, 400.0, 200.0),),
                vision_rep_values=(1.0, 1.5, 300.0),
            ),
        ),
    )
    adapter = GymAwareAdapter(discover_gymaware_landmine(archive))
    gymaware = [item for item in adapter.observations() if item.metric_id.startswith("gymaware_")]
    assert "gymaware_peak_power" not in {item.metric_id for item in gymaware}
    rules = {record.rule for record in adapter.counters.quarantined}
    assert "non_finite_value" in rules


def test_missing_accepted_member_is_reported(tmp_path: Path) -> None:
    import zipfile

    path = tmp_path / "missing.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("LP_data/GymAware_rawdata/001.csv", b"Row Type,Rep Number\n")
    with pytest.raises(GymAwareSourceError):
        discover_gymaware_landmine(path)


def test_ingest_cli_resolves_the_gymaware_slice_from_verified_bronze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    from dynamis.config import ENV_DATABASE_ROOT, ENV_DATASET_ROOT, ENV_DUCKDB_PATH, Settings
    from dynamis.pipeline import cli
    from dynamis.registry import source_by_id, validate_registry
    from dynamis.storage.manifest import (
        manifest_from_registry,
        record_retrieval,
        write_bronze_manifest,
    )
    from dynamis.storage.paths import bronze_native_path, receipt_path

    dataset_root = tmp_path / "datasets"
    database_root = tmp_path / "databases"
    env = {
        ENV_DATASET_ROOT: str(dataset_root),
        ENV_DATABASE_ROOT: str(database_root),
        ENV_DUCKDB_PATH: str(database_root / "duckdb" / "dynamis.duckdb"),
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    resolved = Settings.from_environ(env)

    source = source_by_id(validate_registry(), GYMAWARE_DATASET_ID)
    version = source.version("v1")
    target = bronze_native_path(
        resolved, dataset_id=GYMAWARE_DATASET_ID, version="v1", key="LP_data.zip"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    providers.write_gymaware_zip(target)
    manifest = record_retrieval(
        resolved,
        manifest_from_registry(source, version),
        retrieved_at=datetime(2026, 9, 18, tzinfo=UTC),
        only_keys=("LP_data.zip",),
    )
    write_bronze_manifest(resolved, manifest)

    assert (
        cli.main(
            [
                "gymaware-landmine-vision",
                "--version",
                "v1",
                "--key",
                "LP_data.zip",
                "--no-persist",
                "--discovery",
                "--json",
            ]
        )
        == 0
    )
    discovery_receipt = receipt_path(
        resolved,
        dataset_id=GYMAWARE_DATASET_ID,
        kind="discovery",
        name="gymaware-landmine-release-zip",
    )
    assert discovery_receipt.is_file()
    assert '"sample_level_trajectory_present": false' in discovery_receipt.read_text(
        encoding="utf-8"
    )
