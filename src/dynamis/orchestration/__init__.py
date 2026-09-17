"""Dagster orchestration foundation for DynamisData (RES-96).

Asset lineage and materialization metadata only: registry validation, synthetic
canonicalization, synthetic Parquet materialization and synthetic validation.
"""

from dynamis.orchestration import assets, operations

__all__ = ["assets", "operations"]
