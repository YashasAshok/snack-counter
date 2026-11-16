"""Budget check: per office, in its own currency, for its own local month."""

from datetime import datetime, timezone

from conftest import accept, add_past_purchase, done, oslo, report

from snack_counter import budget
from snack_counter.actions import Action
from snack_counter.models import RefillState as S
from snack_counter.money import Money
from snack_counter.sample_data import BENGALURU, KARI, LARS, MARTE, OSLO, RAVI


def _oslo(app):
    return app.store.offices[OSLO]


def test_spending_limit_is_the_top_of_the_typical_range_when_budget_is_plentiful(app):
    refill = report(app, KARI, OSLO)
    assert "Spend up to 1 200 NOK" in app.chat.last(LARS).text
    accept(app, LARS, refill)
    assert refill.spending_limit == Money(1200, "NOK")


def test_spending_limit_shrinks_to_what_is_left(app):
    add_past_purchase(app, LARS, OSLO, oslo(11, 2, 8), 5500)
    refill = report(app, KARI, OSLO)
    accept(app, refill.offer_to, refill)
    assert refill.spending_limit == Money(500, "NOK")


def test_an_accepted_refill_reserves_its_limit(app):
    refill = report(app, KARI, OSLO)
    assert budget.remaining(app.store, _oslo(app), app.clock.now()) == Money(6000, "NOK")

    accept(app, LARS, refill)
    assert budget.remaining(app.store, _oslo(app), app.clock.now()) == Money(4800, "NOK")

    done(app, LARS, refill, "845")
    assert budget.remaining(app.store, _oslo(app), app.clock.now()) == Money(5155, "NOK")


def test_refill_is_blocked_when_the_budget_is_used_up_and_admin_is_told(app):
    add_past_purchase(app, LARS, OSLO, oslo(11, 2, 8), 5800)  # 200 NOK left, below the 300 minimum
    refill = report(app, KARI, OSLO)

    assert refill.state == S.BLOCKED_BUDGET
    assert app.chat.inbox(LARS) == []
    admin_message = app.chat.last(MARTE)
    assert "only 200 NOK" in admin_message.text
    assert [b.label for b in admin_message.buttons] == ["Allow extra budget", "Keep blocked"]
    assert "budget is used up" in app.chat.last(KARI).text


def test_admin_can_allow_extra_budget(app):
    add_past_purchase(app, LARS, OSLO, oslo(11, 2, 8), 5800)
    refill = report(app, KARI, OSLO)

    result = app.bot.press(MARTE, Action.ALLOW_EXTRA_BUDGET, refill.id, amount="1000")
    assert result.ok
    assert refill.state == S.OFFERED
    assert budget.budget_for(app.store, _oslo(app), 2026, 11) == Money(7000, "NOK")


def test_blocked_refill_unblocks_when_the_new_month_starts(app):
    add_past_purchase(app, LARS, OSLO, oslo(11, 2, 8), 5800)
    app.run_until(oslo(11, 30, 10))
    refill = report(app, KARI, OSLO)
    assert refill.state == S.BLOCKED_BUDGET

    app.run_until(oslo(12, 1, 9, 0))
    assert refill.state == S.OFFERED


def test_purchase_over_the_limit_needs_admin_approval(app):
    refill = report(app, KARI, OSLO)
    accept(app, LARS, refill)
    result = done(app, LARS, refill, "1300")

    assert result.ok
    assert refill.state == S.NEEDS_APPROVAL
    assert app.hr.claims == {}  # nothing sent to HR yet
    assert "above the 1 200 NOK limit" in app.chat.last(MARTE).text

    assert app.bot.press(MARTE, Action.APPROVE_PURCHASE, refill.id).ok
    assert refill.state == S.CLAIM_SUBMITTED
    assert app.hr.claims[refill.claim.hr_claim_id]["amount"] == 1300
    assert "approved your 1 300 NOK purchase" in app.chat.last(LARS).text


def test_rejected_over_limit_purchase_is_not_counted_as_spend(app):
    refill = report(app, KARI, OSLO)
    accept(app, LARS, refill)
    done(app, LARS, refill, "1300")

    assert app.bot.press(MARTE, Action.REJECT_PURCHASE, refill.id, reason="Please stay within the limit").ok
    assert refill.state == S.REJECTED
    assert budget.spent_in(app.store, _oslo(app), 2026, 11) == Money(0, "NOK")
    assert "stay within the limit" in app.chat.last(LARS).text


def test_the_budget_month_follows_the_office_local_time(app):
    # 30 Nov 23:30 UTC is already 1 December in Oslo (UTC+1)
    oslo_refill_time = datetime(2026, 11, 30, 23, 30, tzinfo=timezone.utc)
    add_past_purchase(app, LARS, OSLO, oslo_refill_time, 700)
    # 30 Nov 21:00 UTC is already 1 December in Bengaluru (UTC+5:30)
    blr_refill_time = datetime(2026, 11, 30, 21, 0, tzinfo=timezone.utc)
    add_past_purchase(app, RAVI, BENGALURU, blr_refill_time, 2000)

    oslo_office, blr_office = app.store.offices[OSLO], app.store.offices[BENGALURU]
    assert budget.spent_in(app.store, oslo_office, 2026, 11) == Money(0, "NOK")
    assert budget.spent_in(app.store, oslo_office, 2026, 12) == Money(700, "NOK")
    assert budget.spent_in(app.store, blr_office, 2026, 11) == Money(0, "INR")
    assert budget.spent_in(app.store, blr_office, 2026, 12) == Money(2000, "INR")


def test_each_office_budget_is_in_its_own_currency(app):
    assert budget.remaining(app.store, app.store.offices[OSLO], app.clock.now()) == Money(6000, "NOK")
    assert budget.remaining(app.store, app.store.offices[BENGALURU], app.clock.now()) == Money(15000, "INR")
