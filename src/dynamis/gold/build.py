"""Programmatic dbt-duckdb build for the Gold marts.

The project is invoked with an explicit ``serving_root`` variable and an
explicit DuckDB path, so a build can never silently read a stale serving export
or write into an unrelated database. Builds are deterministic for the same
serving export: dbt materializes the marts as tables in the Gold DuckDB file and
the runner fingerprints every mart afterwards.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

from dynamis.config import Settings, repository_root
from dynamis.storage.parquet import content_fingerprint

MART_NAMES: tuple[str, ...] = (
    "gold_trial_metrics",
    "gold_session_player_load",
    "gold_cmj_metrics",
    "gold_pose_kinematics_summary",
    "gold_processing_provenance",
)

ENV_GOLD_DUCKDB = "DYNAMIS_GOLD_DUCKDB_PATH"


@dataclass(frozen=True, slots=True)
class GoldBuild:
    duckdb_path: Path
    serving_root: Path
    marts: dict[str, dict[str, Any]]
    success: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "duckdb_path": str(self.duckdb_path),
            "serving_root": str(self.serving_root),
            "success": self.success,
            "marts": self.marts,
        }


def gold_duckdb_path(settings: Settings) -> Path:
    return settings.duckdb_path.with_name("dynamis_gold.duckdb")


def _mart_fingerprint(path: Path, name: str) -> dict[str, Any]:
    # dbt-duckdb may still hold a read-write connection in this process, and
    # DuckDB refuses a differently configured second connection; a read-write
    # connection performs no write here.
    connection = duckdb.connect(str(path))
    try:
        table: pa.Table = connection.execute(f'SELECT * FROM "{name}"').to_arrow_table()
    finally:
        connection.close()
    return {
        "row_count": table.num_rows,
        "column_names": list(table.column_names),
        "content_fingerprint": content_fingerprint(table),
    }


def build_gold(
    settings: Settings,
    *,
    project_dir: Path | None = None,
    serving_root: Path | None = None,
) -> GoldBuild:
    """Run ``dbt build`` (models + tests) and fingerprint every mart."""
    resolved_project = project_dir or (repository_root() / "analytics")
    resolved_serving = serving_root or (settings.dataset_root / "gold" / "serving")
    if not (resolved_project / "dbt_project.yml").is_file():
        raise FileNotFoundError(f"dbt project is missing at {resolved_project}")
    duckdb_path = gold_duckdb_path(settings)
    duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ[ENV_GOLD_DUCKDB] = str(duckdb_path)

    from dbt.cli.main import dbtRunner

    runner = dbtRunner()
    result = runner.invoke(
        [
            "build",
            "--project-dir",
            str(resolved_project),
            "--profiles-dir",
            str(resolved_project),
            "--vars",
            json.dumps({"serving_root": resolved_serving.as_posix()}),
            "--no-partial-parse",
            "--quiet",
        ]
    )
    if not result.success:
        raise RuntimeError("dbt build failed; see the dbt output above")
    marts = {name: _mart_fingerprint(duckdb_path, name) for name in MART_NAMES}
    return GoldBuild(
        duckdb_path=duckdb_path,
        serving_root=resolved_serving,
        marts=marts,
        success=True,
    )


__all__ = [
    "ENV_GOLD_DUCKDB",
    "MART_NAMES",
    "GoldBuild",
    "build_gold",
    "gold_duckdb_path",
]
