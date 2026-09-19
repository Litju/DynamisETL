"""Deterministic Gold serving: control-plane export -> dbt-duckdb -> PostgreSQL.

Gold is relational serving only. No scientific behavior (filtering, derivatives,
integration, event segmentation, biomechanics) is defined in dbt SQL: marts
select, join, pivot and aggregate values that versioned processors already
produced, and every row keeps its dataset/session/subject/trial identity and its
processing-run provenance.
"""

from dynamis.gold.build import MART_NAMES, GoldBuild, build_gold, gold_duckdb_path
from dynamis.gold.export import SERVING_TABLES, ServingExport, export_serving, serving_root
from dynamis.gold.publish import GOLD_SCHEMA, publish_gold, resolve_gold_schema

__all__ = [
    "GOLD_SCHEMA",
    "MART_NAMES",
    "SERVING_TABLES",
    "GoldBuild",
    "ServingExport",
    "build_gold",
    "export_serving",
    "gold_duckdb_path",
    "publish_gold",
    "resolve_gold_schema",
    "serving_root",
]
