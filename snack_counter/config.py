"""All tunable numbers in one place. Changing a timeout is configuration, not code."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class Settings:
    # Choosing who buys
    offer_window: timedelta = timedelta(hours=2)        # time to answer a direct offer
    max_direct_offers: int = 3                          # then broadcast to everyone eligible
    fairness_window: timedelta = timedelta(days=90)     # "fewest refills in the last 90 days"

    # Buying
    commit_window: timedelta = timedelta(hours=24)      # time to buy after accepting
    reminder_after: timedelta = timedelta(hours=12)     # reminder halfway

    # Office hours (local time of each office): offers are only sent while open
    office_opens: int = 9
    office_closes: int = 17
    working_days: frozenset[int] = frozenset({0, 1, 2, 3, 4})  # Monday to Friday

    # HR claims
    hr_poll_interval: timedelta = timedelta(hours=24)
    stale_claim_after: timedelta = timedelta(days=10)   # HR says 1-10 days; after that, chase

    # Reporting
    reporting_currency: str = "NOK"
    report_timezone: str = "Europe/Oslo"
    management_ids: tuple[str, ...] = ()
