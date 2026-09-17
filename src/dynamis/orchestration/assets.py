"""Dagster assets for the RES-96 orchestration foundation.

Four assets represent the foundation lineage only:

``dataset_registry``
    validates the machine-readable dataset registry (no download);
``synthetic_canonical_streams``
    builds every V1 modality's canonical Arrow stream from deterministic fixtures;
``synthetic_parquet_artifacts``
    materializes those streams as partitioned Parquet+Zstd;
``synthetic_validation``
    reconciles the materialized files through DuckDB against their contracts.

Assets exchange JSON-serializable descriptors instead of Arrow payloads so the
foundation needs no custom IO manager. RES-97+ provider adapters, real
canonicalization and gold metrics are explicitly out of scope here.
"""

from __future__ import annotations

from pathlib import Path

from dagster import (
    AssetCheckResult,
    AssetCheckSeverity,
    AssetKey,
    asset,
    asset_check,
)

from dynamis.config import settings
from dynamis.contracts import ArtifactLayer
from dynamis.orchestration.operations import (
    canonicalize_synthetic,
    materialize_synthetic,
    registry_summary,
    validate_materialized,
)
from dynamis.storage.paths import layer_dir


def synthetic_output_dir() -> Path:
    """Configured synthetic materialization directory (never inside the repo)."""
    resolved = settings()
    return layer_dir(resolved, ArtifactLayer.TMP) / "synthetic"


@asset(group_name="registry", compute_kind="python")
def dataset_registry() -> dict:
    """Validated dataset/source registry with rights and retrieval state."""
    return registry_summary()


@asset(group_name="synthetic", compute_kind="python")
def synthetic_canonical_streams() -> list[dict]:
    """Canonical in-memory Arrow streams for every V1 modality."""
    descriptors = canonicalize_synthetic()
    for descriptor in descriptors:
        if descriptor["contract_violations"]:
            raise ValueError(
                f"{descriptor['name']} violates its canonical contract with "
                f"{descriptor['contract_violations']} violation(s)"
            )
    return descriptors


@asset(group_name="synthetic", compute_kind="python")
def synthetic_parquet_artifacts(synthetic_canonical_streams: list[dict]) -> list[dict]:
    """Parquet+Zstd materialization of the canonical synthetic streams."""
    artifacts = materialize_synthetic(synthetic_output_dir())
    expected = {item["name"] for item in synthetic_canonical_streams}
    produced = {item["name"] for item in artifacts}
    if produced != expected:
        raise ValueError(
            f"materialization mismatch: missing={sorted(expected - produced)} "
            f"unexpected={sorted(produced - expected)}"
        )
    return artifacts


@asset(group_name="synthetic", compute_kind="duckdb")
def synthetic_validation(synthetic_parquet_artifacts: list[dict]) -> dict:
    """DuckDB reconciliation of every materialized synthetic artifact."""
    return validate_materialized(synthetic_parquet_artifacts)


@asset_check(
    asset=AssetKey("synthetic_parquet_artifacts"),
    description="Every synthetic artifact uses Zstd compression (Parquet-first rule).",
)
def synthetic_artifacts_are_zstd(
    synthetic_parquet_artifacts: list[dict],
) -> AssetCheckResult:
    offenders = [
        item["name"]
        for item in synthetic_parquet_artifacts
        if str(item["compression"]).lower() != "zstd"
    ]
    return AssetCheckResult(
        passed=not offenders,
        severity=AssetCheckSeverity.ERROR,
        metadata={"offenders": offenders, "streams": len(synthetic_parquet_artifacts)},
    )


@asset_check(
    asset=AssetKey("synthetic_validation"),
    description=(
        "Row counts, Zstd codecs, checksums and contract checks reconcile for every "
        "canonical synthetic stream."
    ),
)
def synthetic_roundtrip_reconciles(synthetic_validation: dict) -> AssetCheckResult:
    return AssetCheckResult(
        passed=bool(synthetic_validation.get("all_reconciled")),
        severity=AssetCheckSeverity.ERROR,
        metadata={
            "streams": len(synthetic_validation.get("streams", [])),
            "modalities": synthetic_validation.get("modalities", []),
        },
    )


@asset_check(
    asset=AssetKey("dataset_registry"),
    description="The registry audit passes and every V1 modality is covered.",
)
def registry_covers_all_modalities(dataset_registry: dict) -> AssetCheckResult:
    summary = str(dataset_registry.get("summary", ""))
    return AssetCheckResult(
        passed="modality coverage: complete" in summary,
        severity=AssetCheckSeverity.WARN,
        metadata={
            "source_count": dataset_registry.get("source_count"),
            "local_only": dataset_registry.get("local_only", []),
        },
    )
