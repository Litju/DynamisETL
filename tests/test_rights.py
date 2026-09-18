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
    for dataset_id in ("white-cmj-acc-grf", "gymaware-landmine-vision"):
        source = source_by_id(validate_registry(), dataset_id)
        assert source.license.local_only is True
        assert source.license.identifier is None
        assert source.license.redistribution.value == "prohibited"


@pytest.mark.parametrize("dataset_id", ["white-cmj-acc-grf", "gymaware-landmine-vision"])
def test_export_of_local_only_records_is_refused(dataset_id: str) -> None:
    source = source_by_id(validate_registry(), dataset_id)
    with pytest.raises(RightsError, match="prohibited"):
        assert_export_allowed(source, Path("exports/out.parquet"))


def test_repository_root_is_never_a_valid_dataset_root_for_local_only_sources() -> None:
    source = source_by_id(validate_registry(), "white-cmj-acc-grf")
    with pytest.raises(RightsError, match="inside the repository"):
        assert_dataset_root_outside_repository(source, repository_root() / "data")
    assert_dataset_root_outside_repository(source, Path("E:/scientific-data"))


def test_ingest_refuses_to_materialize_local_only_sources_in_the_repository(
    tmp_path: Path,
) -> None:
    import synthetic_lab_providers as providers
    from dynamis.pipeline.ingest import ingest_white_cmj

    npz = providers.write_white_npz(tmp_path / "white.npz")
    inside_repo = repository_root() / "res98-should-not-exist"
    settings = Settings(
        dataset_root=inside_repo,
        database_root=tmp_path / "db",
        duckdb_path=tmp_path / "db" / "d.duckdb",
        db_schema="guard_test",
    )
    with pytest.raises(RightsError, match="inside the repository"):
        ingest_white_cmj(settings, npz_path=npz, version="v1")
    assert not inside_repo.exists()


def test_redistributable_sources_are_not_blocked(tmp_path: Path) -> None:
    source = source_by_id(validate_registry(), "dfl-sportec-idsse")
    assert_dataset_root_outside_repository(source, repository_root() / "data")
    assert_export_allowed(source, tmp_path / "out.parquet")
