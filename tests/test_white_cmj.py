"""White CMJ provider: NPZ security, discovery, canonicalization and quarantine.

All fixtures are structurally synthetic; no real source bytes enter CI.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import synthetic_lab_providers as providers
from dynamis.adapters.white_cmj.adapter import WhiteCmjAdapter, force_stream_id, imu_stream_id
from dynamis.adapters.white_cmj.authorities import (
    SENSOR_FRAME_ID,
    WHITE_DATASET_ID,
    WHITE_NPZ_KEY,
)
from dynamis.adapters.white_cmj.discovery import (
    WhiteSourceError,
    discover_white_cmj,
    load_white_cmj_bundle,
)
from dynamis.adapters.white_cmj.npz_safety import (
    NpzSecurityError,
    inspect_npz,
    load_object_member_numeric,
)
from dynamis.config import Settings
from dynamis.contracts import FORCE_SCHEMA, IMU_SCHEMA
from dynamis.pipeline.ingest import ingest_white_cmj
from dynamis.quality.checks import validate
from dynamis.storage.parquet import read_parquet_table
from dynamis.storage.paths import silver_parquet_path


@pytest.fixture
def white_npz(tmp_path: Path) -> Path:
    return providers.write_white_npz(tmp_path / "cmj_dataset_synthetic.npz")


def test_npz_headers_are_reported_before_any_value_is_read(white_npz: Path) -> None:
    headers = {header.name: header for header in inspect_npz(white_npz)}
    assert "acc_signals.npy" in headers
    acc = headers["acc_signals.npy"]
    assert acc.object_dtype is True
    assert acc.shape == (6,)
    assert headers["acc_sampling_rate.npy"].dtype == "<i4"
    assert headers["jump_height.npy"].dtype == "<f4"


def test_restricted_unpickler_rejects_a_dangerous_global(tmp_path: Path) -> None:
    path = providers.write_white_npz_with_unsafe_object(tmp_path / "unsafe.npz")
    with pytest.raises(NpzSecurityError, match="forbidden pickle global"):
        load_object_member_numeric_safe(path)


def test_object_member_with_non_array_elements_is_rejected(tmp_path: Path) -> None:
    path = providers.write_white_npz_with_string_object(tmp_path / "stringy.npz")
    with pytest.raises(NpzSecurityError):
        load_object_member_numeric_safe(path)


def load_object_member_numeric_safe(path: Path):
    import zipfile

    with zipfile.ZipFile(path) as archive:
        return load_object_member_numeric(archive, "acc_signals.npy", expected_ndim=2)


def test_npz_member_decompression_is_bounded(tmp_path: Path) -> None:
    import zipfile

    path = tmp_path / "bomb.npz"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("acc_signals.npy", b"\x00" * (65 << 20))
    with pytest.raises(NpzSecurityError, match="member bound"):
        inspect_npz(path)


def test_npz_expansion_ratio_is_bounded(tmp_path: Path) -> None:
    import zipfile

    path = tmp_path / "ratio.npz"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("acc_signals.npy", b"\x00" * (2 << 20))
    with pytest.raises(NpzSecurityError, match="expansion ratio"):
        inspect_npz(path)


def test_numeric_member_rejects_a_string_dtype(tmp_path: Path) -> None:
    import zipfile

    path = tmp_path / "strings.npz"
    np.savez(path, jump_height=np.array(["a", "bb"]), allow_pickle=False)
    with zipfile.ZipFile(path) as archive:
        with pytest.raises(NpzSecurityError, match="forbidden dtype"):
            from dynamis.adapters.white_cmj.npz_safety import load_numeric_member

            load_numeric_member(archive, "jump_height.npy")


def test_numeric_member_preserves_fortran_order(tmp_path: Path) -> None:
    import zipfile

    path = tmp_path / "fortran.npz"
    values = np.asfortranarray(np.arange(12, dtype=np.float64).reshape(3, 4))
    np.savez(path, matrix=values, allow_pickle=False)
    with zipfile.ZipFile(path) as archive:
        from dynamis.adapters.white_cmj.npz_safety import load_numeric_member

        header = inspect_npz(path)
        assert header[0].shape == (3, 4)
        loaded = load_numeric_member(archive, "matrix.npy")
    assert np.array_equal(loaded, values)


def test_bundle_loader_requires_the_verified_member_set(white_npz: Path) -> None:
    bundle = load_white_cmj_bundle(white_npz)
    assert bundle.trial_count == 6
    assert bundle.acc_sampling_rate_hz == 250
    assert bundle.grf_sampling_rate_hz == 1000
    assert bundle.acc_signals[0].dtype == np.float32
    assert bundle.grf_signals[0].dtype == np.float32

    truncated = Path(white_npz).with_name("truncated.npz")
    payload = dict(np.load(white_npz, allow_pickle=True))
    payload.pop("peak_power")
    np.savez(truncated, **payload)
    with pytest.raises(WhiteSourceError, match="missing members"):
        load_white_cmj_bundle(truncated)


def test_discovery_reports_shapes_counts_and_timing(white_npz: Path) -> None:
    discovery = discover_white_cmj(load_white_cmj_bundle(white_npz)).to_dict()
    structure = discovery["structure"]
    assert structure["trial_dimension"] == 6
    assert structure["subject_count_present"] == 3
    assert structure["condition_counts"] == {"1": 3, "2": 3}
    assert structure["acc_sampling_rate_hz"] == 250
    assert structure["grf_sampling_rate_hz"] == 1000
    assert structure["acc_sample_count_per_trial"]["per_trial"] == [300, 250, 260, 260, 240, 245]
    assert structure["grf_sample_count_per_trial"]["per_trial"] == [200, 150, 170, 0, 160, 165]
    assert structure["acc_non_finite_values"] == 1
    assert structure["grf_non_finite_values"] == 0
    timing = discovery["timing"]
    assert timing["acc_takeoff"]["within_trial_bounds"] == 6
    assert timing["grf_takeoff"]["within_distributed_trial_bounds"] == 0
    assert discovery["safety"]["allow_pickle"] is False


def test_quarantine_invalid_trials_are_never_published(
    tmp_settings: Settings, white_npz: Path
) -> None:
    result = ingest_white_cmj(tmp_settings, npz_path=white_npz, version="v1")
    reconciliation = result.reconciliation
    assert reconciliation.all_balanced
    assert len(reconciliation.streams) == 12  # 6 trials x 2 modalities
    assert result.domain["valid_trials"] == 3
    assert result.domain["quarantined_trials"] == 3
    rules = {record.rule for record in result.quarantine_records}
    assert rules == {"shape_mismatch", "missing_pairing", "non_finite_value"}
    assert len(result.streams) == 6
    assert len(result.quarantine_artifacts) == 3
    # Bad trials produced no artifacts at all.
    for session_id, stream_id in (
        ("white-s001", "imu-white-s001-noarms-t00"),
        ("white-s001", "force-white-s001-arms-t00"),
        ("white-s002", "imu-white-s002-noarms-t00"),
    ):
        assert not silver_parquet_path(
            tmp_settings,
            dataset_id=WHITE_DATASET_ID,
            modality="imu" if stream_id.startswith("imu") else "force",
            session_id=session_id,
            stream_id=stream_id,
        ).exists()


def test_canonical_units_timing_and_force_representation(
    tmp_settings: Settings, white_npz: Path
) -> None:
    result = ingest_white_cmj(tmp_settings, npz_path=white_npz, version="v1")
    bundle = load_white_cmj_bundle(white_npz)
    first = result.provider_domain.trials[0]
    imu_target = silver_parquet_path(
        tmp_settings,
        dataset_id=WHITE_DATASET_ID,
        modality="imu",
        session_id=first.session_id,
        stream_id=imu_stream_id(first.trial_id),
    )
    force_target = silver_parquet_path(
        tmp_settings,
        dataset_id=WHITE_DATASET_ID,
        modality="force",
        session_id=first.session_id,
        stream_id=force_stream_id(first.trial_id),
    )
    assert imu_target.is_file() and force_target.is_file()
    imu_table = read_parquet_table(imu_target)
    force_table = read_parquet_table(force_target)
    assert validate(imu_table, IMU_SCHEMA) == ()
    assert validate(force_table, FORCE_SCHEMA) == ()

    imu_rows = imu_table.to_pylist()
    force_rows = force_table.to_pylist()
    assert len(imu_rows) == bundle.acc_signals[0].shape[0]
    assert len(force_rows) == bundle.grf_signals[0].shape[0]

    # g -> m/s**2 exact conversion, sensor frame with unspecified axes.
    raw = bundle.acc_signals[0]
    for row, sample_index in ((imu_rows[0], 0), (imu_rows[5], 5)):
        expected = float(raw[sample_index, 0]) * 9.80665
        assert row["accel_x_m_s2"] == pytest.approx(expected, rel=1e-12)
    assert imu_rows[0]["coordinate_frame_id"] == SENSOR_FRAME_ID
    assert imu_rows[0]["measurement_class"] == "SOURCE_DERIVED"
    assert all(row["gyro_x_rad_s"] is None for row in imu_rows)

    # Takeoff-relative timing: accelerometer t=0 at its takeoff index.
    takeoff = int(bundle.acc_takeoff[0])
    assert imu_rows[takeoff]["t_rel_ns"] == 0
    assert imu_rows[0]["t_rel_ns"] == -takeoff * 4_000_000
    assert all(row["t_rel_ns"] < 0 for row in imu_rows[:takeoff])

    # vGRF: the distributed curve ends at takeoff; ratio in [0, 1] dimensionless.
    assert force_rows[-1]["t_rel_ns"] == 0
    assert force_rows[0]["t_rel_ns"] == -(len(force_rows) - 1) * 1_000_000
    assert force_rows[0]["force_z_body_weight_ratio"] == pytest.approx(2.0)
    assert all(row["force_z_n"] is None for row in force_rows)
    assert all(row["measurement_class"] == "SOURCE_DERIVED" for row in force_rows)

    # Per-contract schema revisions survive materialization.
    assert result.streams[0].schema_version in {"2"}
    assert result.streams[-1].schema_version in {"2"}


def test_ingest_stream_results_carry_the_stream_session(
    tmp_settings: Settings, white_npz: Path
) -> None:
    result = ingest_white_cmj(tmp_settings, npz_path=white_npz, version="v1")
    assert result.streams
    for stream in result.streams:
        matching = next(
            trial for trial in result.provider_domain.trials if trial.trial_id == stream.trial_id
        )
        assert stream.session_id == matching.session_id
        assert stream.session_id.startswith("white-s")


def test_source_metrics_are_imported_not_recomputed(
    tmp_settings: Settings, white_npz: Path
) -> None:
    result = ingest_white_cmj(tmp_settings, npz_path=white_npz, version="v1")
    assert len(result.source_metrics) == 6  # 3 valid trials x 2 source scalars
    by_metric = {(item.metric_id, item.trial_id) for item in result.source_metrics}
    assert ("source_jump_height", "white-s000-noarms-t00") in by_metric
    assert ("source_peak_power_relative", "white-s000-noarms-t00") in by_metric
    sample = next(item for item in result.source_metrics if item.metric_id == "source_jump_height")
    assert sample.si_unit == "m"
    assert sample.value == pytest.approx(0.30)
    assert sample.origin_provenance["origin"] == "source-provided"
    assert sample.origin_provenance["imported_by"] == "dynamis"
    assert sample.origin_provenance["recomputed_by_dynamis"] is False


def test_white_ingest_is_byte_deterministic(tmp_settings: Settings, white_npz: Path) -> None:
    first = ingest_white_cmj(tmp_settings, npz_path=white_npz, version="v1")
    second = ingest_white_cmj(tmp_settings, npz_path=white_npz, version="v1")
    assert [item.checksum_sha256 for item in first.streams] == [
        item.checksum_sha256 for item in second.streams
    ]
    assert [item.derived_metric_id for item in first.source_metrics] == [
        item.derived_metric_id for item in second.source_metrics
    ]


def test_adapter_alignments_declare_shared_takeoff_axis(white_npz: Path) -> None:
    adapter = WhiteCmjAdapter(load_white_cmj_bundle(white_npz))
    authorities = adapter.source_authorities()
    valid_trial_ids = {trial.trial_id for trial in adapter.trials if adapter.trial_is_valid(trial)}
    # One alignment per accepted trial only: quarantined trials materialize no
    # streams, so they can carry no persisted alignment either.
    assert len(authorities.alignments) == len(valid_trial_ids) == 3
    assert {
        alignment.target_stream_id.removeprefix("imu-") for alignment in authorities.alignments
    } == valid_trial_ids
    alignment = authorities.alignments[0]
    assert alignment.scale == 1.0
    assert alignment.offset_ns == 0
    assert alignment.source_stream_id.startswith("force-")
    assert alignment.target_stream_id.startswith("imu-")
    frame = next(item for item in authorities.frames if item.frame_id == SENSOR_FRAME_ID)
    assert frame.handedness.value == "unspecified"
    assert frame.x_direction.value == "unspecified"
    clock = authorities.clocks[0]
    assert clock.frequency_hz is None
    sync = authorities.synchronizations[0]
    assert sync.method.value == "source_provided"
    assert sync.uncertainty_ms is None
    assert sync.residual_max_abs_ms is None


def test_importing_definitions_never_downloads() -> None:
    import dynamis.orchestration.definitions as definitions

    assert definitions.definitions is not None
    assert WHITE_NPZ_KEY == "cmj_dataset_both.npz"


def test_ingest_cli_resolves_the_white_slice_from_verified_bronze(
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

    assert (
        cli.main(["white-cmj-acc-grf", "--version", "v1", "--key", WHITE_NPZ_KEY, "--no-persist"])
        == 2
    )

    source = source_by_id(validate_registry(), WHITE_DATASET_ID)
    version = source.version("v1")
    target = bronze_native_path(
        resolved, dataset_id=WHITE_DATASET_ID, version="v1", key=WHITE_NPZ_KEY
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    providers.write_white_npz(target, trials=providers.DEFAULT_WHITE_TRIALS[:2])
    manifest = record_retrieval(
        resolved,
        manifest_from_registry(source, version),
        retrieved_at=datetime(2026, 9, 18, tzinfo=UTC),
        only_keys=(WHITE_NPZ_KEY,),
    )
    manifest_path = write_bronze_manifest(resolved, manifest)
    assert manifest_path.is_file()
    layout_settings = Settings.from_environ({key: str(value) for key, value in env.items()})
    assert manifest_path == (
        layout_settings.dataset_root / "bronze" / "_manifests" / WHITE_DATASET_ID / "v1.json"
    )

    assert (
        cli.main(
            [
                "white-cmj-acc-grf",
                "--version",
                "v1",
                "--key",
                WHITE_NPZ_KEY,
                "--no-persist",
                "--discovery",
                "--json",
            ]
        )
        == 0
    )
    discovery_receipt = receipt_path(
        resolved, dataset_id=WHITE_DATASET_ID, kind="discovery", name="white-cmj-release-npz"
    )
    assert discovery_receipt.is_file()
    assert "acc_signals.npy" in discovery_receipt.read_text(encoding="utf-8")
