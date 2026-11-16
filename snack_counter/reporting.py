"""Monthly report for management: each office in its own currency, plus one combined total.

The combined total converts each purchase with the exchange rate stored on it
(the rate on the purchase date), so re-running an old report gives the same number.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from statistics import mean

from .budget import budget_for, purchases_in_month
from .models import RefillState
from .money import Money, total
from .store import InMemoryStore


@dataclass
class OfficeMonth:
    office_name: str
    budget: Money
    spent: Money
    reimbursed: Money
    spent_in_reporting_currency: Money
    refills: int
    avg_hours_to_refill: float | None
    avg_days_to_reimburse: float | None
    refills_by_person: dict[str, int]
    top_items: list[tuple[str, int]]

    @property
    def budget_used_percent(self) -> int:
        if not self.budget.is_positive():
            return 0
        return round(self.spent.amount / self.budget.amount * 100)


@dataclass
class MonthlyReport:
    year: int
    month: int
    reporting_currency: str
    offices: list[OfficeMonth]
    total: Money


def monthly_report(store: InMemoryStore, year: int, month: int, reporting_currency: str) -> MonthlyReport:
    offices = []
    for office in store.offices.values():
        refills = purchases_in_month(store, office, year, month)
        purchases = [r.purchase for r in refills]
        hours = [(r.purchase.purchased_at - r.opened_at).total_seconds() / 3600 for r in refills]
        days = [
            (r.claim.reimbursed_at - r.purchase.purchased_at).total_seconds() / 86400
            for r in refills if r.claim and r.claim.reimbursed_at
        ]
        offices.append(OfficeMonth(
            office_name=office.name,
            budget=budget_for(store, office, year, month),
            spent=total((p.amount for p in purchases), office.currency),
            reimbursed=total((r.purchase.amount for r in refills if r.state == RefillState.REIMBURSED), office.currency),
            spent_in_reporting_currency=total(
                (p.amount.convert(p.fx_rate_to_reporting, reporting_currency) for p in purchases),
                reporting_currency,
            ),
            refills=len(refills),
            avg_hours_to_refill=round(mean(hours), 1) if hours else None,
            avg_days_to_reimburse=round(mean(days), 1) if days else None,
            refills_by_person=dict(Counter(store.name(p.buyer_id) for p in purchases)),
            top_items=Counter(item for p in purchases for item in p.items).most_common(5),
        ))
    grand_total = total((o.spent_in_reporting_currency for o in offices), reporting_currency)
    return MonthlyReport(year, month, reporting_currency, offices, grand_total)


def format_report(report: MonthlyReport) -> str:
    title = date(report.year, report.month, 1).strftime("%B %Y")
    lines = [f"Snack spending report · {title}"]
    for o in report.offices:
        lines.append("")
        lines.append(f"{o.office_name}: {o.spent} of {o.budget} ({o.budget_used_percent}% of budget)")
        lines.append(f"  ≈ {o.spent_in_reporting_currency} · reimbursed so far {o.reimbursed}")
        speed = f"avg {o.avg_hours_to_refill} h from empty to refilled" if o.avg_hours_to_refill is not None else "no refills"
        lines.append(f"  {o.refills} refills · {speed}"
                     + (f" · avg {o.avg_days_to_reimburse} days to reimburse" if o.avg_days_to_reimburse is not None else ""))
        if o.refills_by_person:
            lines.append("  Refilled by: " + ", ".join(f"{name} {n}" for name, n in sorted(o.refills_by_person.items())))
        if o.top_items:
            lines.append("  Most bought: " + ", ".join(f"{item} {n}" for item, n in o.top_items))
    lines.append("")
    lines.append(f"Total, both offices: {report.total} (each purchase converted at its purchase-date rate)")
    return "\n".join(lines)
