"""Money: an exact amount in a single currency.

Two rules prevent the classic money bugs:
* amounts are Decimal, never float (0.1 + 0.2 must be exactly 0.3);
* NOK and INR can never be added, subtracted or compared by accident.
  Converting is always explicit, with a rate.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

_CENT = Decimal("0.01")


class CurrencyMismatch(ValueError):
    """Raised when two currencies are mixed without converting first."""


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if isinstance(self.amount, float):
            raise TypeError("Money needs a Decimal, int or str amount, never a float")
        object.__setattr__(self, "amount", Decimal(self.amount))
        object.__setattr__(self, "currency", self.currency.upper())

    @classmethod
    def zero(cls, currency: str) -> Money:
        return cls(Decimal(0), currency)

    # --- arithmetic and comparison: same currency only -------------------
    def __add__(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def __lt__(self, other: Money) -> bool:
        self._require_same_currency(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._require_same_currency(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._require_same_currency(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._require_same_currency(other)
        return self.amount >= other.amount

    def is_positive(self) -> bool:
        return self.amount > 0

    def convert(self, rate: Decimal, to_currency: str) -> Money:
        """Convert explicitly: 1 unit of this currency = `rate` units of `to_currency`.

        The result is rounded to whole cents/øre/paise.
        """
        if to_currency.upper() == self.currency:
            return self
        converted = (self.amount * Decimal(rate)).quantize(_CENT, rounding=ROUND_HALF_UP)
        return Money(converted, to_currency)

    def _require_same_currency(self, other: object) -> None:
        if not isinstance(other, Money):
            raise TypeError(f"Expected Money, got {type(other).__name__}")
        if other.currency != self.currency:
            raise CurrencyMismatch(
                f"Cannot combine {self.currency} and {other.currency} without converting first"
            )

    def __str__(self) -> str:
        value = self.amount.quantize(_CENT, rounding=ROUND_HALF_UP)
        if value == value.to_integral_value():
            text = f"{value:,.0f}"
        else:
            text = f"{value:,.2f}"
        return f"{text.replace(',', ' ')} {self.currency}"


def total(amounts: Iterable[Money], currency: str) -> Money:
    """Add up amounts that must all be in `currency` (raises CurrencyMismatch otherwise)."""
    result = Money.zero(currency)
    for amount in amounts:
        result = result + amount
    return result
