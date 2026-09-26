# Grain-aware Parquet storage

PostgreSQL stores semantic/control/catalog/Gold metadata only. Dense observations remain immutable Parquet/Arrow artifacts in private object storage, read with the existing DuckDB/PyArrow plane.

| Grain family | Natural artifact boundary |
| --- | --- |
| FRAME_SERIES / JOINT_FRAME_SERIES | contest × period × modality |
| EVENT_SERIES / PLAY_BY_PLAY | season/release-scale files with contest, period and sequence columns |
| PLAYER_SEASON / TEAM_SEASON | competition edition × aggregate family |
| trial and sensor series | accepted stream/trial artifact boundary |

Use sport, provider/source family, competition edition and grain/family as logical partitions only when they materially prune I/O. Avoid player/event directory partitions and one-file-per-play layouts. Preserve row-group statistics and projection/predicate pushdown. Typical files should contain analytical batches rather than tiny per-entity fragments.

V4 keeps Parquet as the initial format. Adoption triggers for Iceberg or Delta are recorded in [ADR-003](ADR-003-parquet-no-table-format.md); no dependency or table-format migration is introduced here.
