"""The whole demo month, checked: what the walkthrough shows is what the tests prove."""

from demo import Demo

from snack_counter.models import RefillState as S
from snack_counter.money import Money
from snack_counter.reporting import monthly_report
from snack_counter.sample_data import OSLO, PRIYA, SOFIE


def test_a_month_in_both_offices():
    app = Demo(out=lambda *_: None).run()

    report = monthly_report(app.store, 2026, 11, "NOK")
    by_office = {o.office_name: o for o in report.offices}
    assert by_office["Oslo"].spent == Money(5945, "NOK")
    assert by_office["Bengaluru"].spent == Money(14900, "INR")
    assert report.total == Money(7733, "NOK")  # 5 945 + 14 900 × 0.12

    # One claim per bought refill, never two
    bought = [r for r in app.store.refills.values() if r.purchase]
    assert len(app.hr.claims) == len(bought) == 12
    assert all(len(app.hr.claims_for(r.id)) == 1 for r in bought)

    # Work was shared: nobody in Oslo did more than 2 of the 6 refills
    assert max(by_office["Oslo"].refills_by_person.values()) == 2

    # Management got the report, and the blocked Oslo refill restarted in December
    assert "November 2026" in app.chat.last(SOFIE).text
    blocked = app.store.active_refill(OSLO)
    assert blocked.state == S.OFFERED and blocked.offer_to == PRIYA
