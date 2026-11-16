"""The data the system keeps: offices, people, refills, purchases and claims."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from zoneinfo import ZoneInfo

from .money import Money


class RefillState(str, Enum):
    # The box is empty
    OPEN = "OPEN"                         # needs a buyer; nobody is being asked right now
    BLOCKED_BUDGET = "BLOCKED_BUDGET"     # monthly budget used up
    OFFERED = "OFFERED"                   # offered to one named person
    BROADCAST = "BROADCAST"               # offered to all eligible volunteers; first tap wins
    COMMITTED = "COMMITTED"               # someone took it and is buying
    # The box has been refilled
    NEEDS_APPROVAL = "NEEDS_APPROVAL"     # spent more than the limit; admin decides
    SUBMIT_PENDING = "SUBMIT_PENDING"     # HR not reachable yet; we keep retrying
    CLAIM_SUBMITTED = "CLAIM_SUBMITTED"   # claim is with HR
    APPROVED = "APPROVED"                 # HR approved, payment on the way
    REIMBURSED = "REIMBURSED"             # HR paid the volunteer
    # Ended without payment
    REJECTED = "REJECTED"                 # by the office admin (over limit) or by HR
    CANCELLED = "CANCELLED"               # by the office admin (e.g. box wasn't empty)


S = RefillState
BOX_EMPTY = frozenset({S.OPEN, S.BLOCKED_BUDGET, S.OFFERED, S.BROADCAST, S.COMMITTED})
WAITING_FOR_BUYER = frozenset({S.OPEN, S.OFFERED, S.BROADCAST})
MONEY_SPENT = frozenset({S.NEEDS_APPROVAL, S.SUBMIT_PENDING, S.CLAIM_SUBMITTED, S.APPROVED, S.REIMBURSED})
MONEY_OWED = MONEY_SPENT - {S.REIMBURSED}


@dataclass
class Office:
    id: str
    name: str
    currency: str
    monthly_budget: Money
    min_purchase: Money       # bottom of the typical purchase range
    max_purchase: Money       # top of the typical range = normal spending limit
    owed_cap: Money           # skip volunteers who are owed more than this
    timezone: str
    admin_id: str

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def local(self, moment: datetime) -> datetime:
        return moment.astimezone(self.tz)

    def today(self, now: datetime) -> date:
        return self.local(now).date()

    def month_of(self, moment: datetime) -> tuple[int, int]:
        """Budget month of a moment, in this office's local time."""
        local = self.local(moment)
        return local.year, local.month


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("The end date is before the start date")

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


@dataclass(frozen=True)
class Visit:
    office_id: str
    dates: DateRange


@dataclass
class Person:
    id: str                    # employee ID: the same ID the company login and HR use
    name: str
    home_office: str
    is_volunteer: bool = False
    away: list[DateRange] = field(default_factory=list)
    visits: list[Visit] = field(default_factory=list)

    def office_on(self, day: date) -> str:
        """Where this person works on `day`: a visited office, or their home office."""
        for visit in self.visits:
            if visit.dates.contains(day):
                return visit.office_id
        return self.home_office

    def is_away_on(self, day: date) -> bool:
        return any(period.contains(day) for period in self.away)


@dataclass
class Purchase:
    buyer_id: str
    amount: Money                    # in the office's currency
    items: list[str]
    ran_out: list[str]               # what had run out first (feeds shopping hints)
    left_over: list[str]             # what was left over
    receipt: str                     # reference to the uploaded receipt photo
    purchased_at: datetime
    fx_rate_to_reporting: Decimal    # stored so reports never change afterwards


@dataclass
class Claim:
    reference: str                   # our refill ID: makes submitting idempotent
    hr_claim_id: str | None = None
    submitted_at: datetime | None = None
    last_checked: datetime | None = None
    approved_at: datetime | None = None
    reimbursed_at: datetime | None = None
    rejection_reason: str | None = None
    escalated: bool = False          # admin told that HR is taking too long
    followed_up: bool = False


@dataclass
class Refill:
    id: str
    office_id: str
    opened_at: datetime
    state: RefillState = RefillState.OPEN
    reported_by: list[str] = field(default_factory=list)

    # Finding a buyer
    offer_to: str | None = None
    offer_until: datetime | None = None
    direct_offers: int = 0
    broadcast_to: list[str] = field(default_factory=list)
    skip_for_direct_offer: set[str] = field(default_factory=set)  # declined, didn't reply, or handed back
    skip_for_broadcast: set[str] = field(default_factory=set)     # said no explicitly, or handed back
    escalated_on: date | None = None                             # admin told "no buyer" on this day

    # Buying
    committed_by: str | None = None
    committed_at: datetime | None = None
    deadline: datetime | None = None
    reminder_sent: bool = False
    spending_limit: Money | None = None
    purchase: Purchase | None = None
    claim: Claim | None = None

    # Audit trail of everything that happened to this refill
    history: list[tuple[datetime, str]] = field(default_factory=list)

    @property
    def box_empty(self) -> bool:
        return self.state in BOX_EMPTY

    def log(self, when: datetime, event: str) -> None:
        self.history.append((when, event))
