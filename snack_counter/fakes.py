"""Simulated stand-ins for the clock, the chat tool, the HR system and exchange rates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Callable, Sequence

from .ports import Button, HRClaimStatus, HRUnavailable


class FakeClock:
    """A clock that only moves when told to, so timeouts can be tested without waiting."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("Use timezone-aware datetimes")
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta

    def set(self, moment: datetime) -> None:
        self._now = moment


@dataclass(frozen=True)
class SentMessage:
    to: str
    text: str
    buttons: tuple[Button, ...]
    sent_at: datetime


class FakeChat:
    """Records every message the bot sends, with its buttons, so tests can 'tap' them."""

    def __init__(self, clock: FakeClock, on_send: Callable[[SentMessage], None] | None = None) -> None:
        self.clock = clock
        self.on_send = on_send
        self.messages: list[SentMessage] = []

    def send(self, to: str, text: str, buttons: Sequence[Button] = ()) -> None:
        message = SentMessage(to, text, tuple(buttons), self.clock.now())
        self.messages.append(message)
        if self.on_send:
            self.on_send(message)

    def inbox(self, person_id: str) -> list[SentMessage]:
        return [m for m in self.messages if m.to == person_id]

    def last(self, person_id: str) -> SentMessage:
        return self.inbox(person_id)[-1]

    def button(self, person_id: str, label: str) -> Button:
        """The most recent button with this label that was sent to this person."""
        for message in reversed(self.inbox(person_id)):
            for button in message.buttons:
                if button.label == label:
                    return button
        raise LookupError(f"No [{label}] button was sent to {person_id}")


class FakeHR:
    """Stand-in for the external HR system. Tests and the demo play the HR side."""

    def __init__(self) -> None:
        self.claims: dict[str, dict] = {}
        self.down = False                  # simulate an outage
        self.lose_next_response = False    # claim is created, but our request times out
        self._counter = 0

    # --- the API our system calls -----------------------------------------
    def create_claim(self, *, employee_id: str, amount: Decimal, currency: str,
                     description: str, receipt: str, reference: str) -> str:
        if self.down:
            raise HRUnavailable("HR system is down")
        self._counter += 1
        claim_id = f"HR-{self._counter:04d}"
        self.claims[claim_id] = {
            "id": claim_id, "employee_id": employee_id, "amount": amount, "currency": currency,
            "description": description, "receipt": receipt, "reference": reference,
            "status": "PENDING", "reason": None,
        }
        if self.lose_next_response:
            self.lose_next_response = False
            raise HRUnavailable("Timed out waiting for HR (but the claim was created)")
        return claim_id

    def find_claim(self, reference: str) -> str | None:
        if self.down:
            raise HRUnavailable("HR system is down")
        for claim in self.claims.values():
            if claim["reference"] == reference:
                return claim["id"]
        return None

    def get_status(self, claim_id: str) -> HRClaimStatus:
        if self.down:
            raise HRUnavailable("HR system is down")
        claim = self.claims[claim_id]
        return HRClaimStatus(claim["status"], claim["reason"])

    # --- what HR staff do in their own system (driven by tests/demo) -------
    def approve(self, claim_id: str) -> None:
        self.claims[claim_id]["status"] = "APPROVED"

    def reject(self, claim_id: str, reason: str) -> None:
        self.claims[claim_id]["status"] = "REJECTED"
        self.claims[claim_id]["reason"] = reason

    def pay(self, claim_id: str) -> None:
        self.claims[claim_id]["status"] = "PAID"

    def claims_for(self, reference: str) -> list[dict]:
        return [c for c in self.claims.values() if c["reference"] == reference]


class FixedFx:
    """Exchange rates from a fixed table (test values, not real market rates)."""

    def __init__(self, rates: dict[tuple[str, str], Decimal]) -> None:
        self.rates = dict(rates)

    def rate(self, from_currency: str, to_currency: str, on: date) -> Decimal:
        if from_currency == to_currency:
            return Decimal(1)
        if (from_currency, to_currency) in self.rates:
            return self.rates[(from_currency, to_currency)]
        if (to_currency, from_currency) in self.rates:
            return Decimal(1) / self.rates[(to_currency, from_currency)]
        raise KeyError(f"No exchange rate for {from_currency} -> {to_currency}")
