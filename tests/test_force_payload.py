"""Force contract: newton components or the explicit body-weight ratio.

``1 BW`` is never ``1 N``. The payload-completeness invariant must accept either
representation and reject a row that carries neither, in both the table and the
streaming validator.
"""

from __future__ import annotations

import pyarrow as pa
import pytest

from dynamis.contracts import FORCE_SCHEMA
from dynamis.quality.checks import QualityError, assert_valid, validate
from dynamis.quality.streaming import StreamingValidator

BASE_ROW: dict[str, object] = {
    "dataset_id": "ds",
    "session_id": "s",
    "trial_id": "t",
    "subject_id": "sub",
    "device_id": "dev",
    "stream_id": "force-1",
    "sample_index": 0,
    "t_rel_ns": 0,
    "timestamp_utc_ns": None,
    "nominal_sampling_rate_hz": 1000.0,
    "measurement_class": "SOURCE_DERIVED",
    "clock_id": "clock",
    "synchronization_spec_id": "sync",
    "coordinate_frame_id": "frame",
    "plate_id": None,
    "force_x_n": None,
    "force_y_n": None,
    "force_z_n": None,
    "force_z_body_weight_ratio": None,
    "moment_x_n_m": None,
    "moment_y_n_m": None,
    "moment_z_n_m": None,
    "cop_x_m": None,
    "cop_y_m": None,
    "cop_z_m": None,
    "trigger_flag": None,
    "quality_flag": None,
}


def _table(*rows: dict[str, object]) -> pa.Table:
    return pa.Table.from_pylist(list(rows), schema=FORCE_SCHEMA)


def _row(index: int, **payload: object) -> dict[str, object]:
    row = dict(BASE_ROW)
    row["sample_index"] = index
    row["t_rel_ns"] = index * 1_000_000
    row.update(payload)
    return row


def test_newton_component_satisfies_the_contract() -> None:
    table = _table(_row(0, force_z_n=1000.0))
    assert validate(table, FORCE_SCHEMA) == ()


def test_body_weight_ratio_satisfies_the_contract() -> None:
    table = _table(_row(0, force_z_body_weight_ratio=1.4))
    assert validate(table, FORCE_SCHEMA) == ()


def test_row_with_neither_representation_is_rejected() -> None:
    table = _table(_row(0), _row(1, force_z_body_weight_ratio=0.5))
    violations = validate(table, FORCE_SCHEMA)
    assert [(item.rule, item.evidence["rows_without_payload"]) for item in violations] == [
        ("force.payload.missing", 1)
    ]
    assert violations[0].severity.value == "ERROR"


def test_streaming_validator_agrees_with_the_table_authority() -> None:
    good = pa.RecordBatch.from_pylist([_row(0, force_z_body_weight_ratio=1.0)], schema=FORCE_SCHEMA)
    bad = pa.RecordBatch.from_pylist([_row(1)], schema=FORCE_SCHEMA)
    validator = StreamingValidator(FORCE_SCHEMA)
    validator.observe(good)
    assert validator.finish() == ()
    validator.observe(bad)
    rules = {violation.rule for violation in validator.finish()}
    assert "force.payload.missing" in rules


def test_ratio_and_newton_are_never_aliased() -> None:
    ratio = FORCE_SCHEMA.field("force_z_body_weight_ratio")
    newton = FORCE_SCHEMA.field("force_z_n")
    assert ratio.name != newton.name
    assert ratio.metadata[b"dynamis.si_unit"] == b"1"
    assert newton.metadata[b"dynamis.si_unit"] == b"N"
    with pytest.raises(QualityError):
        assert_valid(_table(_row(0)), FORCE_SCHEMA)
