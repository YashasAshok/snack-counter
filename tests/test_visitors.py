"""Employees visiting the other office for a week or two."""

from datetime import date

from conftest import accept, blr, done, oslo, report

from snack_counter import assignment, budget
from snack_counter.actions import Action
from snack_counter.money import Money
from snack_counter.sample_data import BENGALURU, OSLO, PRIYA, SNEHA


def _visit_bengaluru(app):
    result = app.bot.press(PRIYA, Action.SET_VISIT, office=BENGALURU,
                           start=date(2026, 11, 9), end=date(2026, 11, 20))
    assert result.ok


def test_visitor_can_refill_the_office_they_are_visiting(app):
    _visit_bengaluru(app)
    app.run_until(blr(11, 10, 10, 0))

    refill = report(app, SNEHA, BENGALURU)
    assert refill.offer_to == PRIYA  # no refills yet, lowest ID among people in Bengaluru today


def test_visitor_is_not_asked_for_their_home_office_while_away(app):
    _visit_bengaluru(app)
    app.run_until(oslo(11, 10, 10, 0))
    office = app.store.offices[OSLO]

    eligible = assignment.eligible_volunteers(app.store, office, app.clock.now(), app.fx)
    assert PRIYA not in {p.id for p in eligible}


def test_visitor_cost_lands_on_the_host_office_budget_in_host_currency(app):
    _visit_bengaluru(app)
    app.run_until(blr(11, 10, 10, 0))
    refill = report(app, SNEHA, BENGALURU)
    accept(app, PRIYA, refill)
    done(app, PRIYA, refill, "2400")

    blr_office, oslo_office = app.store.offices[BENGALURU], app.store.offices[OSLO]
    assert budget.spent_in(app.store, blr_office, 2026, 11) == Money(2400, "INR")
    assert budget.spent_in(app.store, oslo_office, 2026, 11) == Money(0, "NOK")

    claim = app.hr.claims[refill.claim.hr_claim_id]
    assert claim["currency"] == "INR"        # what was spent; HR pays out in her payroll currency
    assert claim["employee_id"] == PRIYA


def test_report_empty_defaults_to_the_office_you_are_in_today(app):
    _visit_bengaluru(app)
    app.run_until(blr(11, 10, 10, 0))

    refill = app.bot.press(PRIYA, Action.REPORT_EMPTY).refill  # no office given (e.g. from the menu)
    assert refill.office_id == BENGALURU


def test_visit_dates_must_make_sense(app):
    result = app.bot.press(PRIYA, Action.SET_VISIT, office=BENGALURU,
                           start=date(2026, 11, 20), end=date(2026, 11, 9))
    assert not result.ok
    assert app.store.people[PRIYA].visits == []
