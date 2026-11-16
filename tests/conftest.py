"""Shared test setup: a fresh app on Monday 2 November 2026, 09:00 in Oslo."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from snack_counter.actions import Action
from snack_counter.app import App, create_app
from snack_counter.fakes import FakeChat, FakeClock, FakeHR, FixedFx
from snack_counter.models import Purchase, Refill, RefillState
from snack_counter.money import Money
from snack_counter.sample_data import TEST_FX_RATES, sample_offices, sample_people, sample_settings

OSLO_TZ = ZoneInfo("Europe/Oslo")
BLR_TZ = ZoneInfo("Asia/Kolkata")


def oslo(month: int, day: int, hour: int = 9, minute: int = 0, year: int = 2026) -> datetime:
    """A moment given in Oslo local time (stored as UTC, like everything else)."""
    return datetime(year, month, day, hour, minute, tzinfo=OSLO_TZ).astimezone(timezone.utc)


def blr(month: int, day: int, hour: int = 10, minute: int = 0, year: int = 2026) -> datetime:
    """A moment given in Bengaluru local time."""
    return datetime(year, month, day, hour, minute, tzinfo=BLR_TZ).astimezone(timezone.utc)


@pytest.fixture
def app() -> App:
    clock = FakeClock(oslo(11, 2, 9, 0))  # Monday, office open
    return create_app(clock, FakeChat(clock), FakeHR(), FixedFx(TEST_FX_RATES),
                      sample_settings(), sample_offices(), sample_people())


# --- helpers ---------------------------------------------------------------

def report(app: App, person_id: str, office_id: str) -> Refill:
    return app.bot.press(person_id, Action.REPORT_EMPTY, office=office_id).refill


def accept(app: App, person_id: str, refill: Refill):
    return app.bot.press(person_id, Action.ACCEPT, refill.id)


def done(app: App, person_id: str, refill: Refill, amount: str, items=("Fruit",), **extra):
    return app.bot.press(person_id, Action.MARK_DONE, refill.id, amount=amount,
                         receipt="receipt.jpg", items=list(items), **extra)


def refill_now(app: App, office_id: str, amount: str, reporter: str) -> Refill:
    """Report, accept by whoever is asked, and complete a refill in one go."""
    refill = report(app, reporter, office_id)
    buyer = refill.offer_to
    assert accept(app, buyer, refill).ok
    assert done(app, buyer, refill, amount).ok
    return refill


def add_past_purchase(app: App, buyer_id: str, office_id: str, when: datetime, amount: int,
                      state: RefillState = RefillState.REIMBURSED, rate: str = "0.12",
                      items=("Fruit",), ran_out=(), left_over=()) -> Refill:
    """Put a finished refill straight into the store (history for fairness, budget and reports)."""
    office = app.store.offices[office_id]
    refill = Refill(id=app.store.new_refill_id(), office_id=office_id, opened_at=when, state=state)
    refill.committed_by = buyer_id
    refill.purchase = Purchase(
        buyer_id=buyer_id, amount=Money(amount, office.currency), items=list(items),
        ran_out=list(ran_out), left_over=list(left_over), receipt="old.jpg", purchased_at=when,
        fx_rate_to_reporting=Decimal(1) if office.currency == "NOK" else Decimal(rate),
    )
    app.store.refills[refill.id] = refill
    return refill
