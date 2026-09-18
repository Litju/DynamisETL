"""Storage conventions: paths, atomic Parquet+Zstd writes, manifests, DuckDB."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pyarrow as pa
import pytest

from dynamis.config import Settings
from dynamis.contracts import ArtifactLayer, Modality
from dynamis.fixtures import force_bodyweight_static
from dynamis.registry import source_by_id, validate_registry
from dynamis.storage.atomic import sha256_bytes, sha256_file
from dynamis.storage.duckdb import connect, null_counts, observe_parquet, query
from dynamis.storage.manifest import (
    manifest_from_registry,
    read_bronze_manifest,
    record_retrieval,
    verify_manifest,
    write_bronze_manifest,
)
from dynamis.storage.parquet import (
    compression_codecs,
    content_fingerprint,
    file_row_count,
    read_parquet_schema,
    read_parquet_table,
    write_parquet_atomic,
)
from dynamis.storage.paths import (
    PathConventionError,
    bronze_manifest_path,
    bronze_native_path,
    cache_dir,
    ensure_database_layout,
    ensure_dataset_layout,
    gold_parquet_path,
    layer_dir,
    partition_values,
    quarantine_parquet_path,
    relative_posix,
    safe_upstream_key,
    sanitize_component,
    silver_parquet_path,
    tmp_run_dir,
)


def test_dataset_layout_creates_every_layer(tmp_settings: Settings) -> None:
    created = ensure_dataset_layout(tmp_settings)
    assert len(created) == len(ArtifactLayer) + 1
    for layer in ArtifactLayer:
        assert layer_dir(tmp_settings, layer).is_dir()
    assert (layer_dir(tmp_settings, ArtifactLayer.BRONZE) / "_manifests").is_dir()


def test_database_layout_creates_postgres_and_duckdb_roots(tmp_settings: Settings) -> None:
    created = ensure_database_layout(tmp_settings)
    assert (tmp_settings.database_root / "postgres").is_dir()
    assert tmp_settings.duckdb_path.parent.is_dir()
    assert set(created) == {
        tmp_settings.database_root / "postgres",
        tmp_settings.duckdb_path.parent,
    }


def test_directory_layout_is_idempotent(tmp_settings: Settings) -> None:
    first = ensure_dataset_layout(tmp_settings)
    second = ensure_dataset_layout(tmp_settings)
    assert first == second


def test_silver_path_convention_is_hive_partitioned(tmp_settings: Settings) -> None:
    path = silver_parquet_path(
        tmp_settings,
        dataset_id="skillcorner-opendata",
        modality=Modality.TRACKING,
        session_id="1925299",
        stream_id="tracking-00000001",
    ).as_posix()
    assert "/silver/" in path
    assert "dataset_id=skillcorner-opendata" in path
    assert "modality=tracking" in path
    assert "session_id=1925299" in path
    assert path.endswith("tracking-00000001.parquet")
    assert partition_values("d", modality=Modality.EVENT, session_id="s") == {
        "dataset_id": "d",
        "modality": "event",
        "session_id": "s",
    }


def test_gold_quarantine_cache_and_tmp_paths(tmp_settings: Settings) -> None:
    gold = gold_parquet_path(
        tmp_settings, dataset_id="dfl-sportec-idsse", mart="match_summary", name="match-1"
    )
    assert gold.as_posix().endswith("gold/dfl-sportec-idsse/match_summary/match-1.parquet")

    quarantine = quarantine_parquet_path(
        tmp_settings, dataset_id="white-cmj-acc-grf", rule="time.monotonic", name="cmj-1"
    )
    assert "quarantine/dataset_id=white-cmj-acc-grf/rule=time.monotonic" in quarantine.as_posix()

    assert cache_dir(tmp_settings, "registry").as_posix().endswith("cache/registry")
    assert tmp_run_dir(tmp_settings, "run-abc").as_posix().endswith("tmp/run-abc")


@pytest.mark.parametrize(
    "value",
    ["..", ".", "a/b", "a\\b", "C:/data", "", "   "],
)
def test_unsafe_path_components_are_rejected(value: str) -> None:
    with pytest.raises(PathConventionError):
        sanitize_component(value, field="dataset_id")


def test_safe_components_are_normalized_deterministically() -> None:
    assert sanitize_component("syn session 1") == "syn_session_1"
    assert sanitize_component("already-safe_1.0") == "already-safe_1.0"


@pytest.mark.parametrize("key", ["../escape", "/absolute", "C:/windows", "a//b", ""])
def test_upstream_keys_cannot_traverse(key: str) -> None:
    with pytest.raises(PathConventionError):
        safe_upstream_key(key)


def test_bronze_paths_preserve_upstream_keys(tmp_settings: Settings) -> None:
    path = bronze_native_path(
        tmp_settings,
        dataset_id="openbiomechanics",
        version="dataset-v1",
        key="high_performance/data/hp_obp.csv",
    )
    assert path.as_posix().endswith(
        "bronze/openbiomechanics/dataset-v1/high_performance/data/hp_obp.csv"
    )
    manifest = bronze_manifest_path(
        tmp_settings, dataset_id="openbiomechanics", version="dataset-v1"
    )
    assert manifest.as_posix().endswith("bronze/_manifests/openbiomechanics/dataset-v1.json")
    assert relative_posix(tmp_settings.dataset_root, path).startswith("bronze/")
    with pytest.raises(PathConventionError):
        relative_posix(tmp_settings.dataset_root / "elsewhere", path)


def test_parquet_write_is_atomic_and_records_provenance(tmp_settings: Settings) -> None:
    fixture = force_bodyweight_static(rate_hz=1000.0, duration_s=0.01)
    path = silver_parquet_path(
        tmp_settings,
        dataset_id=fixture.dataset_id,
        modality=fixture.modality,
        session_id=fixture.session_id,
        stream_id=fixture.stream_id,
    )
    written = write_parquet_atomic(fixture.table, path, relative_to=tmp_settings.dataset_root)

    assert written.path == path
    assert written.row_count == fixture.table.num_rows
    assert written.checksum_sha256 == sha256_file(path)
    assert written.byte_size == path.stat().st_size
    assert written.relative_path == relative_posix(tmp_settings.dataset_root, path)
    assert not list(path.parent.glob(".*tmp*"))


def test_parquet_write_is_byte_deterministic(tmp_settings: Settings) -> None:
    fixture = force_bodyweight_static(rate_hz=1000.0, duration_s=0.025)
    target = tmp_settings.dataset_root / "determinism.parquet"
    first = write_parquet_atomic(fixture.table, target)
    second = write_parquet_atomic(fixture.table, target)
    assert first.checksum_sha256 == second.checksum_sha256
    assert content_fingerprint(fixture.table) == content_fingerprint(fixture.table)


def test_parquet_readers_agree_on_schema_and_rows(tmp_settings: Settings) -> None:
    fixture = force_bodyweight_static(rate_hz=1000.0, duration_s=0.04)
    target = tmp_settings.dataset_root / "force.parquet"
    write_parquet_atomic(fixture.table, target)

    assert file_row_count(target) == 40
    assert compression_codecs(target) == ("ZSTD",)
    read_back = read_parquet_schema(target)
    assert read_back.names == fixture.schema.names
    assert read_parquet_table(target).num_rows == 40


def test_duckdb_observation_reports_contract_metadata(tmp_settings: Settings) -> None:
    fixture = force_bodyweight_static(rate_hz=1000.0, duration_s=0.03)
    target = tmp_settings.dataset_root / "force.parquet"
    write_parquet_atomic(fixture.table, target)

    connection = connect()
    try:
        observed = observe_parquet(connection, target)
        assert observed.row_count == 30
        assert observed.codecs == ("ZSTD",)
        assert observed.row_groups >= 1
        assert observed.metadata["dynamis.contract"] == "force_sample"
        assert observed.metadata["dynamis.modality"] == "force"
        assert observed.metadata["dynamis.units"] == "SI"
        assert observed.metadata["dynamis.nominal_sampling_rate_hz"] == "1000.0"
        assert set(observed.columns) == set(fixture.schema.names)

        table = query(connection, f"SELECT * FROM read_parquet('{target.as_posix()}')")
        assert table.num_rows == 30
        counts = null_counts(connection, target, ["force_z_n", "moment_z_n_m"])
        assert counts["force_z_n"] == 0
        assert counts["moment_z_n_m"] == 30
    finally:
        connection.close()


def test_bronze_manifest_roundtrip_and_verification(tmp_settings: Settings) -> None:
    registry = validate_registry()
    source = source_by_id(registry, "tackle-workload")
    version = source.versions[0]
    manifest = manifest_from_registry(source, version)
    assert manifest.retrieved_at is None
    assert manifest.files

    path = write_bronze_manifest(tmp_settings, manifest)
    assert path == bronze_manifest_path(
        tmp_settings, dataset_id=source.dataset_id, version=version.version
    )
    reloaded = read_bronze_manifest(
        tmp_settings, dataset_id=source.dataset_id, version=version.version
    )
    assert reloaded == manifest

    # Nothing retrieved yet: strict verification passes because no local checksum
    # is claimed and the declared sizes only apply to files that exist.
    assert verify_manifest(tmp_settings, manifest).ok

    first = manifest.files[0]
    assert first.size_bytes is not None
    target = bronze_native_path(
        tmp_settings,
        dataset_id=source.dataset_id,
        version=version.version,
        key=first.key,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = b"b" * first.size_bytes
    target.write_bytes(payload)

    stamped = record_retrieval(
        tmp_settings, manifest, retrieved_at=datetime(2026, 9, 17, tzinfo=UTC)
    )
    assert stamped.files[0].local_sha256 == sha256_bytes(payload)
    assert stamped.retrieved_at is not None
    assert stamped.verified_at == datetime(2026, 9, 17, tzinfo=UTC)
    assert stamped.files[0].retrieved_at == datetime(2026, 9, 17, tzinfo=UTC)
    assert stamped.files[0].verified_at == datetime(2026, 9, 17, tzinfo=UTC)
    assert verify_manifest(tmp_settings, stamped).ok

    # A later verification advances verified_at and never moves retrieved_at.
    later = datetime(2026, 10, 1, 9, 30, tzinfo=UTC)
    reverified = record_retrieval(tmp_settings, stamped, retrieved_at=later, verified_at=later)
    assert reverified.files[0].local_sha256 == sha256_bytes(payload)
    assert reverified.files[0].retrieved_at == datetime(2026, 9, 17, tzinfo=UTC)
    assert reverified.files[0].verified_at == later
    assert reverified.retrieved_at == datetime(2026, 9, 17, tzinfo=UTC)
    assert reverified.verified_at == later
    assert verify_manifest(tmp_settings, reverified).ok

    # A file whose bytes or size disagree with the manifest is reported, never
    # silently accepted.
    target.write_bytes(payload + b"corrupted")
    verification = verify_manifest(tmp_settings, reverified)
    assert not verification.ok
    assert first.key in verification.mismatched
    assert first.key in verification.size_mismatched

    # A manifest that claims a local checksum for a missing file is also rejected.
    target.unlink()
    missing = verify_manifest(tmp_settings, reverified)
    assert not missing.ok
    assert first.key in missing.missing


def test_record_retrieval_requires_an_aware_timestamp(tmp_settings: Settings) -> None:
    registry = validate_registry()
    source = source_by_id(registry, "tackle-workload")
    manifest = manifest_from_registry(source, source.versions[0])
    with pytest.raises(ValueError, match="timezone-aware"):
        record_retrieval(tmp_settings, manifest, retrieved_at=datetime(2026, 9, 17))


def test_record_retrieval_requires_an_aware_verification_timestamp(tmp_settings: Settings) -> None:
    registry = validate_registry()
    source = source_by_id(registry, "tackle-workload")
    manifest = manifest_from_registry(source, source.versions[0])
    with pytest.raises(ValueError, match="verified_at must be timezone-aware"):
        record_retrieval(
            tmp_settings,
            manifest,
            retrieved_at=datetime(2026, 9, 17, tzinfo=UTC),
            verified_at=datetime(2026, 9, 17),
        )


def test_v1_manifest_document_loads_without_verification_field(tmp_settings: Settings) -> None:
    """Schema-1 documents (RES-97) load deterministically with nothing invented."""
    registry = validate_registry()
    source = source_by_id(registry, "womens-soccer-positioning")
    version = source.version("1.0")
    path = bronze_manifest_path(tmp_settings, dataset_id=source.dataset_id, version="1.0")
    path.parent.mkdir(parents=True, exist_ok=True)
    first = version.retrieval.files[0]
    path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "dataset_id": source.dataset_id,
                "version": "1.0",
                "upstream_url": str(version.upstream_url),
                "retrieved_at": "2026-09-17T21:29:24.058121Z",
                "files": [
                    {
                        "key": first.key,
                        "size_bytes": first.size_bytes,
                        "upstream_md5": None if first.md5 == "unknown" else first.md5,
                        "upstream_sha1": None,
                        "upstream_sha256": None,
                        "local_sha256": "ab" * 32,
                        "retrieved_at": "2026-09-17T21:29:24.058121Z",
                        "upstream_url": None,
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    loaded = read_bronze_manifest(tmp_settings, dataset_id=source.dataset_id, version="1.0")
    assert loaded.schema_version == "1"
    assert loaded.retrieved_at == datetime(2026, 9, 17, 21, 29, 24, 58121, tzinfo=UTC)
    assert loaded.files[0].retrieved_at == datetime(2026, 9, 17, 21, 29, 24, 58121, tzinfo=UTC)
    assert loaded.files[0].verified_at is None


def test_parquet_write_accepts_plain_tables(tmp_settings: Settings) -> None:
    table = pa.table({"a": [1, 2, 3]})
    target = tmp_settings.dataset_root / "plain.parquet"
    written = write_parquet_atomic(table, target)
    assert written.row_count == 3
    assert compression_codecs(target) == ("ZSTD",)
