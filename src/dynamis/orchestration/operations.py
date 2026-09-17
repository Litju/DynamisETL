"""Plain operational functions behind the Dagster assets.

The logic lives here so it can be unit-tested without a Dagster runtime; the
assets in :mod:`dynamis.orchestration.assets` are thin, lineage-bearing wrappers.
RES-96 scope: registry validation, synthetic canonicalization, synthetic Parquet
materialization and synthetic validation. No provider adapter is implemented.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from dynamis.contracts import Modality
from dynamis.fixtures.synthetic import ModalityFixture, all_fixtures
from dynamis.quality.checks import validate
from dynamis.registry import describe_registry, validate_registry
from dynamis.storage.atomic import sha256_file
from dynamis.storage.duckdb import connect, observe_parquet
from dynamis.storage.parquet import content_fingerprint, write_parquet_atomic

SYNTHETIC_NAMESPACE = "synthetic"


def registry_summary() -> dict[str, Any]:
    """Validate the dataset registry and return an auditable summary."""
    registry = validate_registry()
    return {
        "schema_version": registry.schema_version,
        "source_count": len(registry.sources),
        "dataset_ids": [source.dataset_id for source in registry.sources],
        "local_only": [
            source.dataset_id for source in registry.sources if source.license.local_only
        ],
        "optional": [
            source.dataset_id
            for source in registry.sources
            if any(version.optional for version in source.versions)
        ],
        "summary": describe_registry(registry),
    }


def canonicalize_synthetic() -> list[dict[str, Any]]:
    """Build every synthetic canonical stream and describe it.

    Returns descriptors (not Arrow payloads) so the orchestration layer needs no
    custom IO manager; materialization re-derives the identical tables from the
    same deterministic fixture functions.
    """
    descriptors: list[dict[str, Any]] = []
    for fixture in all_fixtures():
        violations = validate(fixture.table, fixture.schema)
        descriptors.append(
            {
                "name": fixture.name,
                "modality": fixture.modality.value,
                "contract": str(fixture.schema.metadata[b"dynamis.contract"], "utf-8"),
                "row_count": fixture.table.num_rows,
                "column_count": fixture.table.num_columns,
                "content_fingerprint": content_fingerprint(fixture.table),
                "contract_violations": len(violations),
            }
        )
    return descriptors


def materialize_synthetic(output_dir: Path) -> list[dict[str, Any]]:
    """Write every synthetic canonical stream as Parquet+Zstd."""
    artifacts: list[dict[str, Any]] = []
    for fixture in all_fixtures():
        written = write_parquet_atomic(
            fixture.table,
            Path(output_dir) / f"{fixture.name}.parquet",
            relative_to=output_dir,
        )
        artifacts.append(
            {
                "name": fixture.name,
                "modality": fixture.modality.value,
                "path": str(written.path),
                "relative_path": written.relative_path,
                "checksum_sha256": written.checksum_sha256,
                "byte_size": written.byte_size,
                "row_count": written.row_count,
                "compression": written.compression,
                "schema_fingerprint": written.schema_fingerprint,
            }
        )
    return artifacts


def validate_materialized(artifacts: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Reconcile materialized Parquet through DuckDB against the Arrow contract."""
    fixtures = {fixture.name: fixture for fixture in all_fixtures()}
    connection = connect()
    try:
        observations: list[dict[str, Any]] = []
        for artifact in artifacts:
            fixture: ModalityFixture = fixtures[str(artifact["name"])]
            observed = observe_parquet(connection, Path(str(artifact["path"])))
            observations.append(
                {
                    "name": fixture.name,
                    "modality": fixture.modality.value,
                    "row_count": observed.row_count,
                    "row_count_matches": observed.row_count == fixture.table.num_rows,
                    "codecs": list(observed.codecs),
                    "zstd": observed.codecs == ("ZSTD",),
                    "column_count": len(observed.columns),
                    "schema_metadata_keys": len(observed.metadata),
                    "checksum_matches": sha256_file(Path(str(artifact["path"])))
                    == artifact["checksum_sha256"],
                    "validation_violations": len(validate(fixture.table, fixture.schema)),
                }
            )
    finally:
        connection.close()
    return {
        "streams": observations,
        "all_reconciled": all(
            item["row_count_matches"]
            and item["zstd"]
            and item["checksum_matches"]
            and item["validation_violations"] == 0
            for item in observations
        ),
        "modalities": sorted({item["modality"] for item in observations}),
        "expected_modalities": sorted(member.value for member in Modality),
    }
