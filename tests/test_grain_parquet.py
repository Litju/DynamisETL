import pyarrow as pa
import pytest

from dynamis.contracts.sports import DataGrain, DataGrainKind
from dynamis.storage.parquet import (
    read_parquet_schema,
    write_parquet_atomic,
    write_parquet_streaming_atomic,
)


def _frame_table(entity_ids: list[str]) -> pa.Table:
    return pa.table(
        {
            "session_id": ["session-1"] * len(entity_ids),
            "trial_id": ["period-1"] * len(entity_ids),
            "t_rel_ns": [0] * len(entity_ids),
            "object_id": entity_ids,
        }
    )


def test_grain_metadata_and_duplicate_gate_on_atomic_writer(tmp_path) -> None:
    grain = DataGrain(kind=DataGrainKind.FRAME_SERIES)
    valid_path = tmp_path / "frames.parquet"
    write_parquet_atomic(_frame_table(["p1", "p2"]), valid_path, grain=grain)
    metadata = read_parquet_schema(valid_path).metadata or {}
    assert metadata[b"dynamis.data_grain_kind"] == b"FRAME_SERIES"
    assert metadata[b"dynamis.data_grain_axes"] == (
        b'["contest","period","canonical_time","entity"]'
    )

    duplicate_path = tmp_path / "duplicate.parquet"
    with pytest.raises(ValueError, match="duplicate grain keys"):
        write_parquet_atomic(_frame_table(["p1", "p1"]), duplicate_path, grain=grain)
    assert not duplicate_path.exists()


def test_grain_keys_come_from_parquet_not_hive_partition(tmp_path) -> None:
    table = pa.table(
        {
            "session_id": ["session-1", "session-2"],
            "trial_id": ["period-1", "period-1"],
            "t_rel_ns": [0, 0],
            "object_id": ["p1", "p1"],
        }
    )
    path = tmp_path / "session_id=9000001" / "frames.parquet"
    artifact = write_parquet_atomic(
        table,
        path,
        grain=DataGrain(kind=DataGrainKind.FRAME_SERIES),
    )
    assert artifact.row_count == 2


def test_streaming_writer_rejects_null_grain_axis_before_publish(tmp_path) -> None:
    table = pa.table(
        {
            "subject_id": ["p1", "p1"],
            "trial_id": ["trial-1", "trial-1"],
            "sample_index": [0, 1],
        }
    )
    path = tmp_path / "trial.parquet"
    artifact = write_parquet_streaming_atomic(
        table.to_batches(),
        path,
        schema=table.schema,
        row_group_size=1,
        grain=DataGrain(kind=DataGrainKind.TRIAL_SERIES),
    )
    assert artifact.row_count == 2

    null_table = pa.table(
        {
            "subject_id": ["p1", None],
            "trial_id": ["trial-1", "trial-1"],
            "sample_index": [0, 1],
        }
    )
    invalid_path = tmp_path / "null-trial.parquet"
    with pytest.raises(ValueError, match="null grain axis"):
        write_parquet_streaming_atomic(
            null_table.to_batches(),
            invalid_path,
            schema=null_table.schema,
            row_group_size=1,
            grain=DataGrain(kind=DataGrainKind.TRIAL_SERIES),
        )
    assert not invalid_path.exists()
