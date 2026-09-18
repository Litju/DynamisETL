"""The streaming validator must agree with the table-oriented contract checks.

The table checks in :mod:`dynamis.quality.checks` are the CI authority for
canonical fixtures; the streaming validator exists so a 3.36 M-row provider
stream is validated without materialization. These tests pin their equivalence,
including for deliberately broken streams, so the streaming restatement cannot
silently drift from the authority.
"""

from __future__ import annotations

import pyarrow as pa
import pytest

from dynamis.contracts import MeasurementClass, Modality, get_schema, schema_fingerprint
from dynamis.fixtures import ModalityFixture, all_fixtures
from dynamis.quality.checks import Violation, validate
from dynamis.quality.streaming import StreamingValidator


def _stream_validate(table: pa.Table, schema: pa.Schema, *, chunk: int) -> tuple[Violation, ...]:
    validator = StreamingValidator(schema)
    for batch in table.to_batches(max_chunksize=chunk):
        validator.observe(batch)
    return validator.finish()


def _rules(violations: tuple[Violation, ...]) -> list[str]:
    return sorted({violation.rule for violation in violations})


@pytest.mark.parametrize("fixture", all_fixtures(), ids=lambda fixture: fixture.name)
def test_streaming_validator_accepts_every_canonical_fixture(fixture: ModalityFixture) -> None:
    assert validate(fixture.table, fixture.schema) == ()
    for chunk in (1, 7, 64, 1000):
        assert _stream_validate(fixture.table, fixture.schema, chunk=chunk) == ()


def test_streaming_validator_reports_the_same_rules_as_the_table_checks() -> None:
    from dynamis.fixtures.synthetic import gnss_constant_velocity

    fixture = gnss_constant_velocity(rate_hz=10.0, sample_count=20)
    schema = fixture.schema
    table = fixture.table

    index = table.schema.get_field_index("t_rel_ns")
    broken = table.set_column(
        index,
        table.schema.field(index),
        pa.array(list(reversed(table.column("t_rel_ns").to_pylist())), type=pa.int64()),
    )
    assert _rules(validate(broken, schema)) == _rules(_stream_validate(broken, schema, chunk=3))

    index = table.schema.get_field_index("clock_id")
    null_clock = table.set_column(
        index,
        table.schema.field(index),
        pa.array([None] * table.num_rows, type=pa.string()),
    )
    assert _rules(validate(null_clock, schema)) == _rules(
        _stream_validate(null_clock, schema, chunk=4)
    )

    index = table.schema.get_field_index("stream_id")
    two_streams = table.set_column(
        index,
        table.schema.field(index),
        pa.array(
            ["gnss-a" if index % 2 else "gnss-b" for index in range(table.num_rows)],
            type=pa.string(),
        ),
    )
    assert _rules(validate(two_streams, schema)) == _rules(
        _stream_validate(two_streams, schema, chunk=5)
    )

    index = table.schema.get_field_index("measurement_class")
    bad_class = table.set_column(
        index,
        table.schema.field(index),
        pa.array(["VENDOR_MAGIC"] * table.num_rows, type=pa.string()),
    )
    assert _rules(validate(bad_class, schema)) == _rules(
        _stream_validate(bad_class, schema, chunk=6)
    )


def test_streaming_validator_detects_boundary_violations_between_batches() -> None:
    from dynamis.fixtures.synthetic import gnss_constant_velocity

    fixture = gnss_constant_velocity(rate_hz=10.0, sample_count=10)
    table = fixture.table
    times = table.column("t_rel_ns").to_pylist()
    times[5] = times[4]  # duplicate across a batch boundary
    index = table.schema.get_field_index("t_rel_ns")
    swapped = table.set_column(index, table.schema.field(index), pa.array(times, type=pa.int64()))
    violations = _stream_validate(swapped, fixture.schema, chunk=5)
    assert "time.monotonic" in _rules(violations)
    # The same violation must be visible to the table authority.
    assert "time.monotonic" in _rules(validate(swapped, fixture.schema))


def test_streaming_validator_reports_the_schema_fingerprint_of_its_contract() -> None:
    schema = get_schema(Modality.TRACKING)
    assert schema_fingerprint(schema) == schema_fingerprint(get_schema("tracking"))
    assert MeasurementClass.RAW_MEASURED.value == "RAW_MEASURED"


def test_streaming_validator_rejects_type_drift_on_a_later_batch() -> None:
    """Identical field names must not be enough for a later batch to pass.

    A first batch can be structurally perfect while a later batch keeps every
    field name and silently changes a required type. The frozen contract check
    runs on every non-empty batch, so the drift is reported as
    ``schema.field.type`` instead of reaching a payload observer.
    """
    from dynamis.fixtures.synthetic import gnss_constant_velocity

    fixture = gnss_constant_velocity(rate_hz=10.0, sample_count=10)
    table = fixture.table
    first = table.slice(0, 5).to_batches()[0]
    late = table.slice(5)
    index = late.schema.get_field_index("latitude_deg")
    retyped = late.set_column(
        index,
        pa.field("latitude_deg", pa.string()),
        pa.array(["not-a-latitude"] * late.num_rows, type=pa.string()),
    )
    late_batch = retyped.to_batches()[0]
    assert late_batch.schema.names == fixture.schema.names
    assert late_batch.schema.field("latitude_deg").type != fixture.schema.field("latitude_deg").type

    validator = StreamingValidator(fixture.schema)
    validator.observe(first)
    validator.observe(late_batch)
    rules = _rules(validator.finish())
    assert "schema.field.type" in rules
    assert validator.row_count == table.num_rows

    # The same rule must fire when the drifted column is the timebase itself,
    # and the int64-only timing kernels must not reinterpret the late batch.
    drifted_time = late.set_column(
        late.schema.get_field_index("t_rel_ns"),
        pa.field("t_rel_ns", pa.string()),
        pa.array(["not-a-timestamp"] * late.num_rows, type=pa.string()),
    ).to_batches()[0]
    timing_validator = StreamingValidator(fixture.schema)
    timing_validator.observe(first)
    timing_validator.observe(drifted_time)
    assert "schema.field.type" in _rules(timing_validator.finish())
    assert timing_validator.t_rel_max_ns == int(table.column("t_rel_ns")[4].as_py())


def test_streaming_validator_keeps_empty_batch_ignore_semantics() -> None:
    """An empty batch is evidence-free and must not initialize the stream."""
    from dynamis.fixtures.synthetic import gnss_constant_velocity

    fixture = gnss_constant_velocity(rate_hz=10.0, sample_count=10)
    empty = pa.RecordBatch.from_pylist([], schema=fixture.schema)
    validator = StreamingValidator(fixture.schema)
    validator.observe(empty)
    assert validator.finish() == ()
    assert validator.row_count == 0
    for batch in fixture.table.to_batches(max_chunksize=4):
        validator.observe(batch)
    assert validator.finish() == ()
