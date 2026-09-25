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
    "womens_j01_bronze",
    "womens_j01_silver_gnss",
    "dfl_j03wpy_bronze",
    "dfl_j03wpy_metadata",
    "dfl_j03wpy_silver_tracking",
    "dfl_j03wpy_silver_events",
    "white_cmj_bronze",
    "white_cmj_discovery",
    "white_cmj_silver",
    "white_cmj_reconciliation",
    "gymaware_landmine_bronze",
    "gymaware_landmine_discovery",
    "gymaware_landmine_canonical",
    "gymaware_landmine_reconciliation",
    "synthetic_lpt_known_answer",
    "white_cmj_force_processing",
    "white_cmj_imu_processing",
    "white_cmj_cross_sensor_processing",
    "womens_gnss_processing",
    "dfl_tracking_processing",
    "skillcorner_tracking_processing",
    "skillcorner_pose_processing",
    "skillcorner_pose_quality_processing",
    "skillcorner_pose_bilateral_processing",
    "dfl_tactical_geometry_processing",
    "dfl_tactical_territory_processing",
    "dfl_tactical_influence_processing",
    "dfl_tactical_event_processing",
    "skillcorner_tactical_geometry_processing",
    "skillcorner_tactical_territory_processing",
    "skillcorner_tactical_influence_processing",
    "gold_serving_export",
    "gold_marts",
    "gold_publish",
}

EXPECTED_ASSET_CHECKS = {
    "synthetic_artifacts_are_zstd",
    "synthetic_roundtrip_reconciles",
    "registry_covers_all_modalities",
    "womens_gnss_reconciliation_balances",
    "dfl_tracking_reconciliation_balances",
    "white_cmj_reconciliation_balances",
    "gymaware_landmine_reconciliation_balances",
    "synthetic_lpt_known_answer_holds",
    "white_force_processing_complete",
    "gold_marts_reconcile",
}


def test_registry_summary_validates_and_reports_rights() -> None:
    summary = registry_summary()
    assert summary["source_count"] == 8
    assert summary["local_only"] == ["tackle-workload"]
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

    gnss = graph.get(AssetKey("womens_j01_silver_gnss"))
    assert {key.path[-1] for key in gnss.parent_keys} == {"womens_j01_bronze"}

    tracking = graph.get(AssetKey("dfl_j03wpy_silver_tracking"))
    assert {key.path[-1] for key in tracking.parent_keys} == {
        "dfl_j03wpy_bronze",
        "dfl_j03wpy_metadata",
    }

    events = graph.get(AssetKey("dfl_j03wpy_silver_events"))
    # The events asset is a projection of the single tracking/events ingest run,
    # so the artifact has exactly one writer.
    assert {key.path[-1] for key in events.parent_keys} == {
        "dfl_j03wpy_silver_tracking",
        "dfl_j03wpy_metadata",
    }

    white_silver = graph.get(AssetKey("white_cmj_silver"))
    assert {key.path[-1] for key in white_silver.parent_keys} == {
        "white_cmj_bronze",
        "white_cmj_discovery",
    }
    white_reconciliation = graph.get(AssetKey("white_cmj_reconciliation"))
    assert {key.path[-1] for key in white_reconciliation.parent_keys} == {"white_cmj_silver"}

    gymaware_canonical = graph.get(AssetKey("gymaware_landmine_canonical"))
    assert {key.path[-1] for key in gymaware_canonical.parent_keys} == {
        "gymaware_landmine_bronze",
        "gymaware_landmine_discovery",
    }
    gymaware_reconciliation = graph.get(AssetKey("gymaware_landmine_reconciliation"))
    assert {key.path[-1] for key in gymaware_reconciliation.parent_keys} == {
        "gymaware_landmine_canonical"
    }

    # Processor assets read canonical Silver through the control-plane registry
    # and never depend on an acquisition/bronze asset (no downloads on import).
    force = graph.get(AssetKey("white_cmj_force_processing"))
    assert not force.parent_keys
    lpt = graph.get(AssetKey("synthetic_lpt_known_answer"))
    assert not lpt.parent_keys

    # Gold lineage: every processing family feeds the serving export, which feeds
    # the dbt marts, which feed the PostgreSQL publication.
    export = graph.get(AssetKey("gold_serving_export"))
    assert {key.path[-1] for key in export.parent_keys} == {
        "white_cmj_force_processing",
        "white_cmj_imu_processing",
        "white_cmj_cross_sensor_processing",
        "womens_gnss_processing",
        "dfl_tracking_processing",
        "skillcorner_tracking_processing",
        "skillcorner_pose_processing",
        "skillcorner_pose_quality_processing",
        "skillcorner_pose_bilateral_processing",
    }
    marts = graph.get(AssetKey("gold_marts"))
    assert {key.path[-1] for key in marts.parent_keys} == {"gold_serving_export"}
    publish = graph.get(AssetKey("gold_publish"))
    assert {key.path[-1] for key in publish.parent_keys} == {"gold_marts"}
