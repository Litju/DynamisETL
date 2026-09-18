"""Narrow typed boundary over :mod:`pyarrow.compute`.

``pyarrow.compute`` builds its function namespace dynamically at import time and
ships no type stubs, so Pyright cannot see the individual kernels. Rather than
sprinkling suppression comments through the scientific checks, this module
declares the exact kernels DynamisData uses together with their result types.

It is deliberately tiny: six documented functions, one untyped boundary, and the
rest of the codebase stays fully typed.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

import pyarrow as pa
import pyarrow.compute as _pc

type Column = pa.Array | pa.ChunkedArray

_kernels: Any = _pc


def count_distinct(column: Column) -> int:
    """Number of distinct non-null values (NULLs are excluded by Arrow)."""
    return int(_kernels.count_distinct(column).as_py())


def any_non_null(columns: Sequence[Column]) -> pa.Array:
    """Boolean array: True where at least one of ``columns`` is non-null."""
    if not columns:
        raise ValueError("any_non_null requires at least one column")
    result = _kernels.is_valid(columns[0])
    for column in columns[1:]:
        result = _kernels.or_(result, _kernels.is_valid(column))
    return cast(pa.Array, result)


def and_(left: Column, right: Column) -> pa.Array:
    return cast(pa.Array, _kernels.and_(left, right))


def or_(left: Column, right: Column) -> pa.Array:
    return cast(pa.Array, _kernels.or_(left, right))


def count_true(column: Column) -> int:
    """Number of True values in a boolean column."""
    if len(column) == 0:
        return 0
    return int(_kernels.sum(_kernels.cast(column, pa.int64())).as_py() or 0)


def distinct_values(column: Column) -> list[Any]:
    """Distinct non-null values, sorted by their string form for determinism."""
    return sorted(
        (value for value in _kernels.unique(column).to_pylist() if value is not None),
        key=str,
    )


def differences(column: Column) -> pa.Array:
    """Element-wise ``column[i+1] - column[i]``."""
    return cast(pa.Array, _kernels.subtract(column.slice(1), column.slice(0, len(column) - 1)))


def is_strictly_increasing(column: Column) -> bool:
    return bool(_kernels.all(_kernels.greater(differences(column), 0)).as_py())


def is_non_decreasing(column: Column) -> bool:
    return bool(_kernels.all(_kernels.greater_equal(differences(column), 0)).as_py())


def values_are_unique(column: Column) -> bool:
    """True when every value in the column is distinct."""
    return count_distinct(column) == len(column)
