"""The monthly report: correct per office, and correct in total across both currencies."""

from decimal import Decimal

from conftest import add_past_purchase, oslo

from snack_counter.models import RefillState as S
from snack_counter.money import Money
from snack_counter.reporting import format_report, monthly_report
from snack_counter.sample_data import ARJUN, BENGALURU, INGRID, LARS, OSLO, SOFIE


def _report(app, month=11):
    return monthly_report(app.store, 2026, month, "NOK")


def test_each_office_is_totalled_in_its_own_currency(app):
    add_past_purchase(app, LARS, OSLO, oslo(11, 3), 845)
    add_past_purchase(app, INGRID, OSLO, oslo(11, 10), 1100)
    add_past_purchase(app, ARJUN, BENGALURU, oslo(11, 4), 2400)

    report = _report(app)
    by_office = {o.office_name: o for o in report.offices}
    assert by_office["Oslo"].spent == Money(1945, "NOK")
    assert by_office["Bengaluru"].spent == Money(2400, "INR")
    assert by_office["Oslo"].refills == 2


def test_combined_total_converts_each_purchase_at_its_own_rate(app):
    add_past_purchase(app, LARS, OSLO, oslo(11, 3), 845)
    add_past_purchase(app, ARJUN, BENGALURU, oslo(11, 4), 1000, rate="0.12")
    add_past_purchase(app, ARJUN, BENGALURU, oslo(11, 20), 1000, rate="0.13")

    report = _report(app)
    # 845 + 1 000 × 0.12 + 1 000 × 0.13 = 1 095 NOK
    assert report.total == Money(1095, "NOK")


def test_report_does_not_change_when_exchange_rates_change_later(app):
    add_past_purchase(app, ARJUN, BENGALURU, oslo(11, 4), 2400)
    before = _report(app).total

    app.fx.rates[("INR", "NOK")] = Decimal("0.20")  # the market moves afterwards
    assert _report(app).total == before == Money("288", "NOK")


def test_only_real_spend_is_counted(app):
    add_past_purchase(app, LARS, OSLO, oslo(11, 3), 845, state=S.REIMBURSED)
    add_past_purchase(app, LARS, OSLO, oslo(11, 4), 500, state=S.CLAIM_SUBMITTED)
    add_past_purchase(app, LARS, OSLO, oslo(11, 5), 900, state=S.REJECTED)

    oslo_month = next(o for o in _report(app).offices if o.office_name == "Oslo")
    assert oslo_month.spent == Money(1345, "NOK")
    assert oslo_month.reimbursed == Money(845, "NOK")


def test_report_shows_who_refilled_and_what_was_bought(app):
    add_past_purchase(app, LARS, OSLO, oslo(11, 3), 845, items=("Fruit", "Chips"))
    add_past_purchase(app, INGRID, OSLO, oslo(11, 9), 900, items=("Fruit",))

    oslo_month = next(o for o in _report(app).offices if o.office_name == "Oslo")
    assert oslo_month.refills_by_person == {"Lars": 1, "Ingrid": 1}
    assert oslo_month.top_items[0] == ("Fruit", 2)
    assert "Total, both offices" in format_report(_report(app))


def test_monthly_report_is_sent_to_management_automatically(app):
    add_past_purchase(app, LARS, OSLO, oslo(11, 3), 845)
    app.run_until(oslo(11, 30, 23, 55))
    assert app.chat.inbox(SOFIE) == []

    app.run_until(oslo(12, 1, 0, 5))
    message = app.chat.last(SOFIE)
    assert message.text.startswith("Snack spending report · November 2026")
    assert "845 NOK of 6 000 NOK" in message.text
