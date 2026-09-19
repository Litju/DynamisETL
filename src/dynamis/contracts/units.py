"""Unit authority.

Canonical numerical units are SI. Source units stay recoverable through explicit
provenance, and conversions are always requested explicitly: nothing in
DynamisData silently rescales a value.

Pint is the unit algebra authority here; the SI whitelist below is the closed
set of unit strings that Arrow schema metadata may declare.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Final

import pint
import pint.errors

# Canonical SI unit strings used across contracts and Arrow field metadata.
# ``ns`` is included because relative-time columns are declared in nanoseconds.
SI_UNITS: Final[tuple[str, ...]] = (
    "m",
    "s",
    "ns",
    "ms",
    "m/s",
    "m/s**2",
    #: Jerk: the first derivative of acceleration, used by IMU derivative features.
    "m/s**3",
    "rad",
    "rad/s",
    "N",
    "N*m",
    "W",
    "W/kg",
    "kg",
    "Hz",
    "deg",
    "uT",
    "degC",
    "K",
    "1",
)

DIMENSIONLESS: Final = "1"


class UnitError(ValueError):
    """Raised for unknown, non-SI or dimensionally incompatible units."""


@lru_cache(maxsize=1)
def unit_registry() -> pint.UnitRegistry:
    """Process-wide Pint registry (single instantiation, cached)."""
    return pint.UnitRegistry()


@lru_cache(maxsize=1)
def _canonical_si_names() -> frozenset[str]:
    registry = unit_registry()
    return frozenset(str(registry.Unit(text)) for text in SI_UNITS)


@lru_cache(maxsize=1)
def _non_multiplicative_units() -> frozenset[str]:
    """Units with an offset, e.g. degree Celsius.

    Detected rather than hard-coded: a purely multiplicative unit maps 0 to 0,
    while an offset unit such as ``degC`` maps 0 to 273.15 K.
    """
    registry = unit_registry()
    detected: set[str] = set()
    for text in SI_UNITS:
        unit = registry.Unit(text)
        base = registry.get_base_units(text)[1]
        if float(registry.Quantity(0.0, unit).to(base).magnitude) != 0.0:
            detected.add(str(unit))
    return frozenset(detected)


def parse_unit(text: str) -> pint.Unit:
    if not text or not text.strip():
        raise UnitError("unit text must be non-empty")
    try:
        return unit_registry().Unit(text)
    except pint.errors.PintError as exc:
        raise UnitError(f"unknown unit {text!r}: {exc}") from exc


def normalize_unit(text: str) -> str:
    return str(parse_unit(text))


def is_si_unit(text: str) -> bool:
    """True when ``text`` normalizes to one of the declared canonical SI units."""
    try:
        return normalize_unit(text) in _canonical_si_names()
    except UnitError:
        return False


def si_unit_bases(text: str) -> str:
    """Base-unit expansion of ``text``, e.g. ``m/s`` -> ``meter / second``."""
    return str(unit_registry().get_base_units(parse_unit(text)))


def assert_si_unit(text: str, *, field_name: str) -> None:
    if not is_si_unit(text):
        raise UnitError(
            f"{field_name}: {text!r} is not a canonical SI unit; "
            f"allowed units are {', '.join(SI_UNITS)}"
        )


def assert_compatible(source_unit: str, si_unit: str) -> None:
    registry = unit_registry()
    if not registry.Unit(parse_unit(source_unit)).is_compatible_with(parse_unit(si_unit)):
        raise UnitError(
            f"source unit {source_unit!r} is not dimensionally compatible with SI unit {si_unit!r}"
        )


def linear_scale(source_unit: str, si_unit: str) -> float:
    """Multiplicative factor converting ``source_unit`` to ``si_unit``.

    Raises for offset units such as ``degC`` where a bare scale would be wrong;
    those require :func:`convert` with a full quantity.
    """
    if (
        normalize_unit(source_unit) in _non_multiplicative_units()
        or normalize_unit(si_unit) in _non_multiplicative_units()
    ):
        raise UnitError(
            f"offset unit pair {source_unit!r} -> {si_unit!r} has no linear scale; use convert()"
        )
    assert_compatible(source_unit, si_unit)
    registry = unit_registry()
    ratio = registry.Quantity(1.0, parse_unit(source_unit)).to(parse_unit(si_unit))
    return float(ratio.magnitude)


def convert(value: float, source_unit: str, si_unit: str) -> float:
    """Explicit, auditable conversion of one source value into SI."""
    assert_compatible(source_unit, si_unit)
    registry = unit_registry()
    quantity = registry.Quantity(float(value), parse_unit(source_unit))
    return float(quantity.to(parse_unit(si_unit)).magnitude)


@dataclass(frozen=True, slots=True)
class UnitProvenance:
    """Recoverability record for a column: SI truth plus original source units."""

    field_name: str
    si_unit: str
    source_unit: str | None = None
    source_to_si_scale: float | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        assert_si_unit(self.si_unit, field_name=f"{self.field_name}.si_unit")
        if self.source_unit is not None:
            assert_compatible(self.source_unit, self.si_unit)
        if self.source_to_si_scale is not None and self.source_unit is None:
            raise UnitError(
                f"{self.field_name}: source_to_si_scale requires an explicit source_unit"
            )

    @classmethod
    def build(
        cls,
        field_name: str,
        si_unit: str,
        *,
        source_unit: str | None = None,
        notes: str | None = None,
    ) -> UnitProvenance:
        scale = linear_scale(source_unit, si_unit) if source_unit is not None else None
        return cls(
            field_name=field_name,
            si_unit=si_unit,
            source_unit=source_unit,
            source_to_si_scale=scale,
            notes=notes,
        )
