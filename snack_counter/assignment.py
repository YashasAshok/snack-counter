"""Choosing who buys.

Plain functions with no side effects, so the rules are easy to test and to
explain ("why was I picked?").

Eligible: a volunteer who is at this office today, not away, not already
holding a refill, and not owed more than the office's cap.
Ranking: fewest refills in the fairness window, then whoever refilled longest
ago (never = first), then employee ID as a fixed tiebreak.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from .config import Settings
from .models import MONEY_OWED, MONEY_SPENT, Office, Person, Purchase, RefillState
from .money import Money
from .ports import FxRates
from .store import InMemoryStore


def purchases_by(store: InMemoryStore, person_id: str) -> list[Purchase]:
    """Every refill this person bought (in any office), whether paid back yet or not."""
    return [
        r.purchase for r in store.refills.values()
        if r.purchase and r.purchase.buyer_id == person_id
        and (r.state in MONEY_SPENT or r.state == RefillState.REJECTED)
    ]


def owed_to(store: InMemoryStore, person_id: str, currency: str, fx: FxRates, on) -> Money:
    """Money this person has spent and not yet got back, converted into `currency`."""
    owed = Money.zero(currency)
    for refill in store.refills.values():
        purchase = refill.purchase
        if purchase and purchase.buyer_id == person_id and refill.state in MONEY_OWED:
            rate = fx.rate(purchase.amount.currency, currency, on)
            owed = owed + purchase.amount.convert(rate, currency)
    return owed


def holds_a_refill(store: InMemoryStore, person_id: str) -> bool:
    return any(
        r.state == RefillState.COMMITTED and r.committed_by == person_id
        for r in store.refills.values()
    )


def why_not_eligible(store: InMemoryStore, person: Person, office: Office,
                     now: datetime, fx: FxRates) -> str | None:
    """None if this person can be asked to refill this office's box now; otherwise the reason."""
    today = office.today(now)
    if not person.is_volunteer:
        return "not on the volunteer list"
    if person.office_on(today) != office.id:
        return f"not at the {office.name} office today"
    if person.is_away_on(today):
        return "marked as away today"
    if holds_a_refill(store, person.id):
        return "already has a refill in progress"
    if owed_to(store, person.id, office.currency, fx, today) > office.owed_cap:
        return "still owed money for earlier refills (let's get that paid first)"
    return None


def eligible_volunteers(store: InMemoryStore, office: Office, now: datetime, fx: FxRates,
                        exclude: Iterable[str] = ()) -> list[Person]:
    excluded = set(exclude)
    return [
        person for person in store.people.values()
        if person.id not in excluded and why_not_eligible(store, person, office, now, fx) is None
    ]


def rank(store: InMemoryStore, people: Iterable[Person], now: datetime, settings: Settings) -> list[Person]:
    """Fairest first."""
    since = now - settings.fairness_window

    def fairness_key(person: Person):
        bought_at = [p.purchased_at for p in purchases_by(store, person.id)]
        recent = sum(1 for moment in bought_at if moment >= since)
        last = max(bought_at) if bought_at else None
        return (recent, last.timestamp() if last else float("-inf"), person.id)

    return sorted(people, key=fairness_key)


def next_candidate(store: InMemoryStore, office: Office, now: datetime, settings: Settings,
                   fx: FxRates, exclude: Iterable[str] = ()) -> Person | None:
    ranked = rank(store, eligible_volunteers(store, office, now, fx, exclude), now, settings)
    return ranked[0] if ranked else None
