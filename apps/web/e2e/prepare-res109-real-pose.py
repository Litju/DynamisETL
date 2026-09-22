"""Extract a bounded, external fixture for the local RES-109 Pose receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from dynamis.config import settings
from dynamis.serving.dense import canonical_timespan, entity_ids, entity_observations
from dynamis.serving.models import ArtifactRefView

SUBJECTS = ("11897", "50999")
MAX_FIXTURE_NS = 60_000_000_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_fixture(output: Path) -> None:
    config = settings()
    relative = Path(
        "silver/dataset_id=skillcorner-opendata/modality=pose/"
        "session_id=1925299/pose-period-1.parquet"
    )
    path = config.dataset_root / relative
    checksum = sha256_file(path)
    metadata = pq.ParquetFile(path).metadata
    artifact_id = f"pose-period-1-{checksum[:12]}"
    ref = ArtifactRefView(
        artifact_id=artifact_id,
        dataset_id="skillcorner-opendata",
        stream_id="pose-period-1",
        layer="silver",
        relative_path=relative.as_posix(),
        format="parquet",
        compression="zstd",
        checksum_sha256=checksum,
        row_count=metadata.num_rows,
        byte_size=path.stat().st_size,
        artifact_kind="sample",
        modality="pose",
        measurement_class="MODEL_ESTIMATED",
        si_units=["m"],
        coordinate_frame_id="skillcorner-pose-hybrid-m",
        synchronization_spec_id="skillcorner-source-provided-match-clock",
    )
    minimum, maximum = canonical_timespan(config, ref)
    identities = entity_ids(config, ref) or []
    observations = entity_observations(config, ref) or []
    columns = [
        "t_rel_ns",
        "subject_id",
        "joint_name",
        "is_available",
        "x_m",
        "y_m",
        "z_m",
        "error_m",
    ]
    connection = duckdb.connect()
    try:
        table = connection.execute(
            "SELECT t_rel_ns, CAST(subject_id AS VARCHAR) AS subject_id, joint_name, "
            "is_available, x_m, y_m, z_m, error_m FROM read_parquet(?) "
            "WHERE CAST(subject_id AS VARCHAR) IN (?, ?) AND t_rel_ns >= 0 AND t_rel_ns <= ? "
            "ORDER BY t_rel_ns, subject_id, joint_name",
            [path.as_posix(), *SUBJECTS, MAX_FIXTURE_NS],
        ).to_arrow_table()
    finally:
        connection.close()
    artifact = {
        **ref.model_dump(mode="json"),
        "canonical_time_min_ns": minimum,
        "canonical_time_max_ns": maximum,
        "entity_column": "subject_id",
        "entity_count": len(identities),
        "entity_ids": identities,
        "entity_observations": [item.model_dump(mode="json") for item in observations],
    }
    fixture = {
        "schema_version": "res109-local-pose-fixture-1",
        "source_path": relative.as_posix(),
        "source_sha256": checksum,
        "artifact": artifact,
        "columns": columns,
        "rows": table.to_pylist(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(fixture, separators=(",", ":")), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "artifact_id": artifact_id,
                "source_sha256": checksum,
                "entity_count": len(identities),
                "subject_rows": table.num_rows,
                "subject_ids": list(SUBJECTS),
            }
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    build_fixture(args.output)


if __name__ == "__main__":
    main()
