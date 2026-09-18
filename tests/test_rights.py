"""Rights gate: local-only sources never reach the repository or an export surface."""

from __future__ import annotations

from pathlib import Path

import pytest

from dynamis.config import Settings, repository_root
from dynamis.registry import source_by_id, validate_registry
from dynamis.rights import (
    RightsError,
    assert_dataset_root_outside_repository,
    assert_export_allowed,
)


def test_unclear_rights_sources_are_local_only_in_the_registry() -> None:
    source = source_by_id(validate_registry(), "tackle-workload")
    assert source.license.local_only is True
    assert source.license.identifier is None
    assert source.license.redistribution.value == "prohibited"


def test_export_of_local_only_records_is_refused() -> None:
    source = source_by_id(validate_registry(), "tackle-workload")
    with pytest.raises(RightsError, match="prohibited"):
        assert_export_allowed(source, Path("exports/out.parquet"))


def test_repository_root_is_never_a_valid_dataset_root_for_local_only_sources(
    tmp_path: Path,
) -> None:
    source = source_by_id(validate_registry(), "tackle-workload")
    with pytest.raises(RightsError, match="inside the repository"):
        assert_dataset_root_outside_repository(source, repository_root() / "data")
    assert_dataset_root_outside_repository(source, tmp_path / "scientific-data")


def test_ingest_refuses_to_materialize_local_only_sources_in_the_repository(
    tmp_path: Path,
) -> None:
    from dynamis.pipeline.ingest import assert_local_only_boundary

    inside_repo = repository_root() / "res104-should-not-exist"
    settings = Settings(
        dataset_root=inside_repo,
        database_root=tmp_path / "db",
        duckdb_path=tmp_path / "db" / "d.duckdb",
        db_schema="guard_test",
    )
    with pytest.raises(RightsError, match="inside the repository"):
        assert_local_only_boundary(settings, "tackle-workload")
    assert not inside_repo.exists()


def test_declared_cc_by_sources_are_not_blocked_by_the_local_only_gate(tmp_path: Path) -> None:
    """RES-104 promoted White/GymAware to declared CC-BY-4.0."""
    for dataset_id in ("white-cmj-acc-grf", "gymaware-landmine-vision"):
        source = source_by_id(validate_registry(), dataset_id)
        assert source.license.local_only is False
        assert_dataset_root_outside_repository(source, repository_root() / "data")
        assert_export_allowed(source, tmp_path / f"{dataset_id}.parquet")


def test_redistributable_sources_are_not_blocked(tmp_path: Path) -> None:
    source = source_by_id(validate_registry(), "dfl-sportec-idsse")
    assert_dataset_root_outside_repository(source, repository_root() / "data")
    assert_export_allowed(source, tmp_path / "out.parquet")


def test_acquisition_refuses_a_local_only_source_inside_the_repository(
    tmp_path: Path,
) -> None:
    from dynamis.acquisition.plan import AcquisitionPlan, PlannedFile
    from dynamis.acquisition.runner import acquire

    settings = Settings(
        dataset_root=repository_root() / "res104-fetch-should-not-exist",
        database_root=tmp_path / "db",
        duckdb_path=tmp_path / "db" / "d.duckdb",
        db_schema="guard_test",
    )
    plan = AcquisitionPlan(
        dataset_id="tackle-workload",
        version="unknown",
        provider="Zenodo",
        resolver="zenodo",
        license_identifier=None,
        license_local_only=True,
        attribution_required=True,
        citation=None,
        upstream_url="https://zenodo.org/records/16962280",
        selection="keys",
        files=(
            PlannedFile(
                key="Dataset.xlsx",
                url="https://zenodo.org/api/records/16962280/files/Dataset.xlsx/content",
                size_bytes=1,
                upstream_md5=None,
                upstream_sha1=None,
                upstream_sha256=None,
                git_blob_sha1=None,
            ),
        ),
    )
    with pytest.raises(RightsError, match="inside the repository"):
        acquire(settings, plan, registry=validate_registry())
    assert not (repository_root() / "res104-fetch-should-not-exist").exists()
