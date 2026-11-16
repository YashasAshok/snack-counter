from decimal import Decimal

import pytest

from snack_counter.money import CurrencyMismatch, Money, total


def test_cannot_add_nok_and_inr_without_converting():
    with pytest.raises(CurrencyMismatch):
        Money(100, "NOK") + Money(100, "INR")


def test_cannot_compare_nok_and_inr():
    with pytest.raises(CurrencyMismatch):
        Money(100, "NOK") < Money(1000, "INR")


def test_total_refuses_mixed_currencies():
    with pytest.raises(CurrencyMismatch):
        total([Money(1, "NOK"), Money(1, "INR")], "NOK")


def test_floats_are_refused():
    with pytest.raises(TypeError):
        Money(0.1, "NOK")


def test_decimal_arithmetic_is_exact():
    assert Money("0.10", "NOK") + Money("0.20", "NOK") == Money("0.30", "NOK")


def test_conversion_is_explicit_and_rounded_to_cents():
    assert Money("1000", "INR").convert(Decimal("0.1234"), "NOK") == Money("123.40", "NOK")
    assert Money("1", "INR").convert(Decimal("0.125"), "NOK") == Money("0.13", "NOK")  # half rounds up


def test_display_uses_space_as_thousands_separator():
    assert str(Money(1200, "NOK")) == "1 200 NOK"
    assert str(Money("845.5", "NOK")) == "845.50 NOK"
