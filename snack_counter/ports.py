"""Interfaces to the outside world.

The core logic only talks to the chat tool, the HR system, the clock and the
exchange-rate source through these. Real adapters would implement them in
production; fakes.py implements them for tests and the demo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, Sequence

from .actions import Action


@dataclass(frozen=True)
class Button:
    """An interactive button in a chat message. Tapping it triggers `action`."""

    label: str
    action: Action
    refill_id: str | None = None


class Clock(Protocol):
    def now(self) -> datetime: ...


class ChatPort(Protocol):
    def send(self, to: str, text: str, buttons: Sequence[Button] = ()) -> None: ...


class HRUnavailable(Exception):
    """The HR system did not answer (down, or the request timed out)."""


@dataclass(frozen=True)
class HRClaimStatus:
    status: str                 # "PENDING", "APPROVED", "REJECTED" or "PAID"
    reason: str | None = None   # set when rejected


class HRPort(Protocol):
    def create_claim(
        self, *, employee_id: str, amount: Decimal, currency: str,
        description: str, receipt: str, reference: str,
    ) -> str: ...

    def find_claim(self, reference: str) -> str | None: ...

    def get_status(self, claim_id: str) -> HRClaimStatus: ...


class FxRates(Protocol):
    def rate(self, from_currency: str, to_currency: str, on: date) -> Decimal: ...
