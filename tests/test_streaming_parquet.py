"""Streaming Parquet writer: bounded Arrow batches, exact table-writer parity.

The streaming writer exists so a 372 MB XML tracking match (millions of rows) is
never materialized in RAM. These tests pin the guarantees that make it a
drop-in replacement for :func:`write_parquet_atomic` when the stream is a
canonical modality schema.
"""

from __future__ import annotations

from collections.abc import Iterator

import pyarrow as pa
import pytest

from dynamis.config import Settings
from dynamis.contracts import get_schema
from dynamis.fixtures import gnss_constant_velocity
from dynamis.storage.atomic import sha256_file
from dynamis.storage.parquet import (
    compression_codecs,
    file_row_count,
    read_parquet_schema,
    read_parquet_table,
    write_parquet_atomic,
    write_parquet_streaming_atomic,
)

ROW_GROUP = 64


def _canonical_table() -> pa.Table:
    return gnss_constant_velocity(rate_hz=10.0, sample_count=250).table


def _batches(table: pa.Table, chunk: int) -> Iterator[pa.RecordBatch]:
    yield from table.to_batches(max_chunksize=chunk)


def test_streaming_matches_table_writer_byte_for_byte(tmp_settings: Settings) -> None:
    table = _canonical_table()
    reference = tmp_settings.dataset_root / "reference.parquet"
    write_parquet_atomic(table, reference, row_group_size=ROW_GROUP)

    for chunk in (1, 3, 64, 100, 250, 1000):
        streamed = tmp_settings.dataset_root / f"streamed-{chunk}.parquet"
        written = write_parquet_streaming_atomic(
            _batches(table, chunk),
            streamed,
            schema=table.schema,
            row_group_size=ROW_GROUP,
            relative_to=tmp_settings.dataset_root,
        )
        assert written.checksum_sha256 == sha256_file(reference), f"chunk={chunk}"
        assert written.byte_size == reference.stat().st_size
        assert written.row_count == table.num_rows
        assert written.relative_path == f"streamed-{chunk}.parquet"


def test_streaming_preserves_schema_provenance_and_compression(tmp_settings: Settings) -> None:
    table = _canonical_table()
    streamed = tmp_settings.dataset_root / "gnss.parquet"
    written = write_parquet_streaming_atomic(
        _batches(table, 32), streamed, schema=table.schema, row_group_size=ROW_GROUP
    )
    assert written.compression == "zstd"
    assert compression_codecs(streamed) == ("ZSTD",)
    assert file_row_count(streamed) == table.num_rows

    read_back = read_parquet_schema(streamed)
    assert read_back == table.schema
    assert read_back.metadata[b"dynamis.contract"] == b"gnss_sample"
    assert read_back.metadata[b"dynamis.units"] == b"SI"
    assert read_parquet_table(streamed).equals(table)


def test_record_batch_reader_input_is_supported(tmp_settings: Settings) -> None:
    table = _canonical_table()
    reader = pa.RecordBatchReader.from_batches(table.schema, _batches(table, 17))
    streamed = tmp_settings.dataset_root / "reader.parquet"
    written = write_parquet_streaming_atomic(
        reader, streamed, schema=table.schema, row_group_size=ROW_GROUP
    )
    assert written.row_count == table.num_rows
    assert read_parquet_table(streamed).equals(table)


def test_streaming_merges_incoming_batches_into_exact_row_groups(tmp_settings: Settings) -> None:
    table = _canonical_table()
    streamed = tmp_settings.dataset_root / "row-groups.parquet"
    write_parquet_streaming_atomic(
        _batches(table, 10), streamed, schema=table.schema, row_group_size=ROW_GROUP
    )
    metadata = read_parquet_schema(streamed)
    assert metadata == table.schema

    from dynamis.storage.parquet import file_row_count

    assert file_row_count(streamed) == 250


def test_empty_stream_writes_a_valid_empty_parquet(tmp_settings: Settings) -> None:
    schema = get_schema("gnss")
    empty = pa.Table.from_pylist([], schema=schema)
    reference = tmp_settings.dataset_root / "empty-table.parquet"
    streamed = tmp_settings.dataset_root / "empty-stream.parquet"
    write_parquet_atomic(empty, reference, row_group_size=ROW_GROUP)
    written = write_parquet_streaming_atomic([], streamed, schema=schema, row_group_size=ROW_GROUP)
    assert written.row_count == 0
    assert written.checksum_sha256 == sha256_file(reference)
    assert read_parquet_schema(streamed) == schema


def test_schema_drift_aborts_and_leaves_no_artifact(tmp_settings: Settings) -> None:
    table = _canonical_table()
    wrong = pa.schema([pa.field("sample_index", pa.int64())])
    target = tmp_settings.dataset_root / "drift.parquet"
    with pytest.raises(ValueError, match="does not match the declared canonical schema"):
        write_parquet_streaming_atomic(
            _batches(table, 32), target, schema=wrong, row_group_size=ROW_GROUP
        )
    assert not target.exists()
    assert not list(target.parent.glob(".*tmp*"))


def test_same_names_type_drift_aborts_the_streaming_write(tmp_settings: Settings) -> None:
    """The writer's exact-schema check is independent defense, not name equality."""
    table = _canonical_table()
    batches = list(_batches(table, 32))
    drifted = batches[0].set_column(
        batches[0].schema.get_field_index("t_rel_ns"),
        pa.field("t_rel_ns", pa.string()),
        pa.array(["not-a-timestamp"] * batches[0].num_rows, type=pa.string()),
    )
    assert drifted.schema.names == table.schema.names
    target = tmp_settings.dataset_root / "type-drift.parquet"
    with pytest.raises(ValueError, match="does not match the declared canonical schema"):
        write_parquet_streaming_atomic(
            [drifted], target, schema=table.schema, row_group_size=ROW_GROUP
        )
    assert not target.exists()
    assert not list(target.parent.glob(".*tmp*"))


def test_midstream_failure_leaves_no_artifact(tmp_settings: Settings) -> None:
    table = _canonical_table()
    target = tmp_settings.dataset_root / "failure.parquet"

    def exploding() -> Iterator[pa.RecordBatch]:
        yield from _batches(table, 32)
        raise RuntimeError("provider stream failed")

    with pytest.raises(RuntimeError, match="provider stream failed"):
        write_parquet_streaming_atomic(
            exploding(), target, schema=table.schema, row_group_size=ROW_GROUP
        )
    assert not target.exists()
    assert not list(target.parent.glob(".*tmp*"))


def test_nonpositive_row_group_size_is_rejected(tmp_settings: Settings) -> None:
    table = _canonical_table()
    with pytest.raises(ValueError, match="row_group_size must be positive"):
        write_parquet_streaming_atomic(
            _batches(table, 32),
            tmp_settings.dataset_root / "bad.parquet",
            schema=table.schema,
            row_group_size=0,
        )
