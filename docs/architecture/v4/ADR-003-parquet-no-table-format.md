# ADR-003: retain Parquet; defer Iceberg and Delta

Status: accepted for V4.

Use immutable, release-derived Parquet artifacts in object storage with DuckDB/PyArrow predicate pushdown, row-group statistics and projection. PostgreSQL already owns artifact/run version and provenance identity; a table format adds no current required behavior.

Reconsider Iceberg or Delta when a real requirement appears: concurrent multi-writer mutation; large mutable tables requiring MERGE/UPDATE; partition evolution without republishing; table-level time travel independent of artifact/run identity; or measured manifest/planning bottlenecks at very high file counts. No table-format dependency is introduced before one of those triggers is demonstrated.
