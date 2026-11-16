"""Budget check.

remaining = monthly budget (+ any extra the admin allowed)
            - purchases already made this month
            - spending limit of a refill someone has accepted but not finished

All amounts are in the office's own currency; the month is the office's local month.
"""

from __future__ import annotations

from datetime import datetime

from .models import MONEY_SPENT, Office, Refill, RefillState
from .money import Money, total
from .store import InMemoryStore


def purchases_in_month(store: InMemoryStore, office: Office, year: int, month: int) -> list[Refill]:
    """Refills bought in this office's local month that count as company spend."""
    return [
        r for r in store.refills_at(office.id)
        if r.purchase and r.state in MONEY_SPENT
        and office.month_of(r.purchase.purchased_at) == (year, month)
    ]


def budget_for(store: InMemoryStore, office: Office, year: int, month: int) -> Money:
    extra = store.extra_budget.get((office.id, year, month), Money.zero(office.currency))
    return office.monthly_budget + extra


def spent_in(store: InMemoryStore, office: Office, year: int, month: int) -> Money:
    return total((r.purchase.amount for r in purchases_in_month(store, office, year, month)), office.currency)


def reserved(store: InMemoryStore, office: Office) -> Money:
    """Budget set aside for a refill that someone has accepted but not finished."""
    return total(
        (r.spending_limit for r in store.refills_at(office.id)
         if r.state == RefillState.COMMITTED and r.spending_limit is not None),
        office.currency,
    )


def remaining(store: InMemoryStore, office: Office, now: datetime) -> Money:
    year, month = office.month_of(now)
    return budget_for(store, office, year, month) - spent_in(store, office, year, month) - reserved(store, office)


def can_start_refill(store: InMemoryStore, office: Office, now: datetime) -> bool:
    return remaining(store, office, now) >= office.min_purchase


def spending_limit(store: InMemoryStore, office: Office, now: datetime) -> Money:
    """What the next buyer may spend: the top of the typical range, or less if the budget is tight."""
    left = remaining(store, office, now)
    return left if left < office.max_purchase else office.max_purchase
