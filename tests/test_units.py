"""Unit authority: canonical SI, explicit conversion, recoverable provenance."""

from __future__ import annotations

import pytest

from dynamis.contracts.units import (
    SI_UNITS,
    UnitError,
    UnitProvenance,
    assert_compatible,
    assert_si_unit,
    convert,
    is_si_unit,
    linear_scale,
    normalize_unit,
    parse_unit,
    si_unit_bases,
)


@pytest.mark.parametrize("text", SI_UNITS)
def test_every_declared_unit_is_canonical_si(text: str) -> None:
    assert is_si_unit(text)
    assert normalize_unit(text)
    assert si_unit_bases(text)


@pytest.mark.parametrize("text", ["yard", "furlong", "stone", "kph", "", "   "])
def test_non_si_units_are_rejected(text: str) -> None:
    assert not is_si_unit(text)
    with pytest.raises(UnitError):
        assert_si_unit(text, field_name="test_field")


def test_unknown_unit_text_raises() -> None:
    with pytest.raises(UnitError):
        parse_unit("not_a_unit_at_all")


def test_conversion_is_explicit_and_dimension_checked() -> None:
    assert convert(1000.0, "mm", "m") == pytest.approx(1.0)
    assert convert(1.0, "s", "ns") == pytest.approx(1_000_000_000.0)
    assert convert(1.0, "deg", "rad") == pytest.approx(0.017453292519943295)
    with pytest.raises(UnitError):
        convert(1.0, "m", "s")
    with pytest.raises(UnitError):
        assert_compatible("m", "kg")


def test_linear_scale_refuses_offset_units() -> None:
    assert linear_scale("mm", "m") == pytest.approx(0.001)
    assert linear_scale("N", "N") == pytest.approx(1.0)
    with pytest.raises(UnitError):
        linear_scale("degC", "K")


def test_offset_unit_conversion_uses_full_quantity() -> None:
    assert convert(0.0, "degC", "K") == pytest.approx(273.15)
    assert convert(100.0, "degC", "K") == pytest.approx(373.15)


def test_unit_provenance_keeps_source_units_recoverable() -> None:
    provenance = UnitProvenance.build("speed_m_s", "m/s", source_unit="kph")
    assert provenance.source_to_si_scale == pytest.approx(1000.0 / 3600.0)

    plain = UnitProvenance(field_name="force_n", si_unit="N")
    assert plain.source_unit is None

    with pytest.raises(UnitError):
        UnitProvenance(field_name="bad", si_unit="furlong")
    with pytest.raises(UnitError):
        UnitProvenance(field_name="bad", si_unit="N", source_unit="m")
    with pytest.raises(UnitError):
        UnitProvenance(field_name="bad", si_unit="N", source_to_si_scale=0.5)
