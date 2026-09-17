"""Dagster foundation: operational functions, asset wiring and asset checks."""

from __future__ import annotations

import pytest

from dynamis.config import ENV_DATABASE_ROOT, ENV_DATASET_ROOT, ENV_DUCKDB_PATH
from dynamis.contracts import Modality
from dynamis.orchestration.operations import (
    canonicalize_synthetic,
    materialize_synthetic,
    registry_summary,
    validate_materialized,
)

EXPECTED_ASSETS = {
    "dataset_registry",
    "synthetic_canonical_streams",
    "synthetic_parquet_artifacts",
    "synthetic_validation",
}

EXPECTED_ASSET_CHECKS = {
    "synthetic_artifacts_are_zstd",
    "synthetic_roundtrip_reconciles",
    "registry_covers_all_modalities",
}


def test_registry_summary_validates_and_reports_rights() -> None:
    summary = registry_summary()
    assert summary["source_count"] == 8
    assert "white-cmj-acc-grf" in summary["local_only"]
    assert "openbiomechanics" in summary["optional"]
    assert "modality coverage: complete" in summary["summary"]


def test_synthetic_canonicalization_covers_every_modality_without_violations() -> None:
    descriptors = canonicalize_synthetic()
    assert {item["modality"] for item in descriptors} == {member.value for member in Modality}
    assert all(item["contract_violations"] == 0 for item in descriptors)
    assert all(len(item["content_fingerprint"]) == 64 for item in descriptors)
    assert {item["contract"] for item in descriptors} == {
        "gnss_sample",
        "imu_sample",
        "force_sample",
        "lpt_sample",
        "tracking_sample",
        "event_record",
        "pose_joint_sample",
    }


def test_materialization_and_validation_reconcile_every_stream(tmp_path) -> None:
    artifacts = materialize_synthetic(tmp_path)
    assert len(artifacts) == 8
    assert all(item["compression"] == "zstd" for item in artifacts)
    assert all(item["byte_size"] > 0 for item in artifacts)

    report = validate_materialized(artifacts)
    assert report["all_reconciled"] is True
    assert report["modalities"] == report["expected_modalities"]
    assert len(report["streams"]) == 8
    for stream in report["streams"]:
        assert stream["row_count_matches"]
        assert stream["zstd"]
        assert stream["checksum_matches"]
        assert stream["validation_violations"] == 0
        assert stream["schema_metadata_keys"] >= 14


def test_validation_detects_a_tampered_artifact(tmp_path) -> None:
    import pyarrow as pa

    from dynamis.storage.parquet import write_parquet_atomic

    artifacts = materialize_synthetic(tmp_path)
    target = next(item for item in artifacts if item["name"] == "gnss_constant_velocity")
    # Replace the artifact with a valid but different Parquet file: it stays
    # readable, so the mismatch must be caught by checksum and row-count checks.
    write_parquet_atomic(pa.table({"x": [1, 2, 3]}), target["path"])

    report = validate_materialized(artifacts)
    assert report["all_reconciled"] is False
    tampered = next(item for item in report["streams"] if item["name"] == "gnss_constant_velocity")
    assert tampered["checksum_matches"] is False
    assert tampered["row_count_matches"] is False


def test_synthetic_output_dir_uses_configured_roots(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_DATASET_ROOT, str(tmp_path / "datasets"))
    monkeypatch.setenv(ENV_DATABASE_ROOT, str(tmp_path / "databases"))
    monkeypatch.setenv(ENV_DUCKDB_PATH, str(tmp_path / "databases" / "duckdb" / "d.duckdb"))

    from dynamis.orchestration.assets import synthetic_output_dir

    target = synthetic_output_dir()
    assert target.name == "synthetic"
    assert target.parent.name == "tmp"
    assert str(target).startswith(str(tmp_path / "datasets"))


def test_dagster_definitions_expose_the_foundation_assets_and_checks() -> None:
    from dynamis.orchestration.definitions import definitions

    asset_keys = {key.path[-1] for key in definitions.resolve_asset_graph().get_all_asset_keys()}
    assert asset_keys == EXPECTED_ASSETS

    check_names: set[str] = set()
    for group in definitions.asset_checks or []:
        check_names.update(key.name for key in group.check_keys)
    assert check_names == EXPECTED_ASSET_CHECKS


def test_dagster_definitions_expose_lineage_edges() -> None:
    from dagster import AssetKey

    from dynamis.orchestration.definitions import definitions

    graph = definitions.resolve_asset_graph()
    artifacts = graph.get(AssetKey("synthetic_parquet_artifacts"))
    assert {key.path[-1] for key in artifacts.parent_keys} == {"synthetic_canonical_streams"}

    validation = graph.get(AssetKey("synthetic_validation"))
    assert {key.path[-1] for key in validation.parent_keys} == {"synthetic_parquet_artifacts"}

    registry = graph.get(AssetKey("dataset_registry"))
    assert not registry.parent_keys
