"""The side states: BLOCKED_BUDGET, NEEDS_APPROVAL, SUBMIT_PENDING, REJECTED and CANCELLED.

The main path is tested elsewhere; these tests cover how a refill gets into each
side state, what people are told, and how it gets out again (or doesn't).
"""

from datetime import timedelta

from conftest import accept, add_past_purchase, done, oslo, refill_now, report

from snack_counter import assignment, budget
from snack_counter.actions import Action
from snack_counter.models import RefillState as S
from snack_counter.money import Money
from snack_counter.sample_data import INGRID, KARI, LARS, MARTE, OLA, OSLO, PRIYA, RAVI


def _refill_buttons(app, person_id, refill):
    return {b.action for b in app.bot.available_actions(person_id) if b.refill_id == refill.id}


def _blocked(app):
    add_past_purchase(app, OLA, OSLO, oslo(11, 2, 8), 5800)  # 200 NOK left, below the 300 minimum
    refill = report(app, KARI, OSLO)
    assert refill.state == S.BLOCKED_BUDGET
    return refill


def _over_limit(app, amount="1300"):
    refill = report(app, KARI, OSLO)
    accept(app, LARS, refill)
    done(app, LARS, refill, amount)
    return refill


# =============================================================================
# BLOCKED_BUDGET
# =============================================================================

def test_budget_running_out_between_offer_and_accept_blocks_the_refill(app):
    refill = report(app, KARI, OSLO)  # offered to Lars while there's plenty left
    add_past_purchase(app, OLA, OSLO, oslo(11, 2, 8), 5800)  # e.g. a late purchase is approved meanwhile

    result = accept(app, LARS, refill)

    assert not result.ok and "budget has just run out" in result.message
    assert refill.state == S.BLOCKED_BUDGET and refill.committed_by is None
    assert "only 200 NOK" in app.chat.last(MARTE).text


def test_admin_sees_the_budget_buttons_and_keep_blocked_keeps_it_blocked(app):
    refill = _blocked(app)
    assert _refill_buttons(app, MARTE, refill) == {
        Action.ALLOW_EXTRA_BUDGET, Action.KEEP_BLOCKED, Action.CANCEL_REFILL}

    assert app.bot.press(MARTE, Action.KEEP_BLOCKED, refill.id).ok
    app.run_until(oslo(11, 3, 12))
    assert refill.state == S.BLOCKED_BUDGET
    assert all(app.chat.inbox(p) == [] for p in (LARS, INGRID, OLA, PRIYA))  # nobody asked to buy


def test_extra_budget_must_be_a_positive_number(app):
    refill = _blocked(app)
    assert not app.bot.press(MARTE, Action.ALLOW_EXTRA_BUDGET, refill.id, amount="lots").ok
    assert not app.bot.press(MARTE, Action.ALLOW_EXTRA_BUDGET, refill.id, amount="0").ok
    assert refill.state == S.BLOCKED_BUDGET
    assert app.store.extra_budget == {}


def test_a_blocked_refill_is_not_also_reported_as_having_no_buyer(app):
    _blocked(app)
    app.run_until(oslo(11, 2, 17, 30))
    assert len(app.chat.inbox(MARTE)) == 1  # just the budget message, no end-of-day alert


# =============================================================================
# NEEDS_APPROVAL
# =============================================================================

def test_spending_exactly_the_limit_needs_no_approval(app):
    refill = report(app, KARI, OSLO)
    accept(app, LARS, refill)
    done(app, LARS, refill, "1200")
    assert refill.state == S.CLAIM_SUBMITTED


def test_while_waiting_for_approval_it_counts_as_spent_and_owed(app):
    refill = _over_limit(app)
    assert refill.state == S.NEEDS_APPROVAL

    assert budget.spent_in(app.store, app.store.offices[OSLO], 2026, 11) == Money(1300, "NOK")
    status = app.bot.press(LARS, Action.MY_STATUS).message
    assert status.startswith("You're owed 1 300 NOK.")
    assert "waiting for the office admin's approval" in status


def test_approving_twice_files_only_one_claim(app):
    refill = _over_limit(app)
    assert app.bot.press(MARTE, Action.APPROVE_PURCHASE, refill.id).ok
    second = app.bot.press(MARTE, Action.APPROVE_PURCHASE, refill.id)

    assert not second.ok and "doesn't need approval any more" in second.message
    assert len(app.hr.claims_for(refill.id)) == 1


# =============================================================================
# SUBMIT_PENDING
# =============================================================================

def test_while_hr_stays_down_the_claim_waits_and_the_volunteer_is_told_once(app):
    app.hr.down = True
    refill = report(app, KARI, OSLO)
    accept(app, LARS, refill)
    done(app, LARS, refill, "845")
    messages_before = len(app.chat.inbox(LARS))

    app.run_until(app.clock.now() + timedelta(hours=3))  # dozens of retries
    assert refill.state == S.SUBMIT_PENDING
    assert len(app.chat.inbox(LARS)) == messages_before  # no repeated messages
    assert app.hr.claims == {}

    app.hr.down = False
    app.run_until(app.clock.now() + timedelta(minutes=5))
    assert refill.state == S.CLAIM_SUBMITTED
    assert len(app.hr.claims_for(refill.id)) == 1
    assert len(app.chat.inbox(LARS)) == messages_before + 1  # one "claim filed" message


def test_an_approved_over_limit_purchase_waits_if_hr_is_down(app):
    refill = _over_limit(app)
    app.hr.down = True
    assert app.bot.press(MARTE, Action.APPROVE_PURCHASE, refill.id).ok
    assert refill.state == S.SUBMIT_PENDING

    app.hr.down = False
    app.run_until(app.clock.now() + timedelta(minutes=5))
    assert refill.state == S.CLAIM_SUBMITTED


# =============================================================================
# REJECTED
# =============================================================================

def test_a_rejected_purchase_is_no_longer_shown_as_owed(app):
    refill = _over_limit(app)
    app.bot.press(MARTE, Action.REJECT_PURCHASE, refill.id)
    assert refill.state == S.REJECTED
    assert "not owed anything" in app.bot.press(LARS, Action.MY_STATUS).message


def test_a_rejected_purchase_still_counts_as_that_persons_turn(app):
    """Lars still did the refill, so the next one goes to someone else."""
    refill = _over_limit(app)
    app.bot.press(MARTE, Action.REJECT_PURCHASE, refill.id)

    office = app.store.offices[OSLO]
    nxt = assignment.next_candidate(app.store, office, app.clock.now(), app.settings, app.fx)
    assert nxt.id == INGRID


def test_after_a_rejection_the_next_empty_report_works_normally(app):
    first = _over_limit(app)
    app.bot.press(MARTE, Action.REJECT_PURCHASE, first.id)

    second = report(app, KARI, OSLO)
    assert second is not first and second.state == S.OFFERED


# =============================================================================
# CANCELLED
# =============================================================================

def test_admin_can_cancel_an_open_refill_and_the_person_asked_is_told(app):
    refill = report(app, KARI, OSLO)
    result = app.bot.press(MARTE, Action.CANCEL_REFILL, refill.id, reason="box wasn't empty")

    assert result.ok
    assert refill.state == S.CANCELLED and refill.offer_to is None
    assert "cancelled" in app.chat.last(LARS).text and "box wasn't empty" in app.chat.last(LARS).text


def test_cancelling_a_taken_refill_tells_the_buyer_and_frees_the_budget(app):
    refill = report(app, KARI, OSLO)
    accept(app, LARS, refill)
    office = app.store.offices[OSLO]
    assert budget.remaining(app.store, office, app.clock.now()) == Money(4800, "NOK")

    app.bot.press(MARTE, Action.CANCEL_REFILL, refill.id)

    assert refill.state == S.CANCELLED
    assert "Please don't buy anything" in app.chat.last(LARS).text
    assert budget.remaining(app.store, office, app.clock.now()) == Money(6000, "NOK")
    assert not assignment.holds_a_refill(app.store, LARS)


def test_a_cancelled_refill_is_never_offered_again(app):
    refill = report(app, KARI, OSLO)
    old_button = app.chat.button(LARS, "I'll do it")
    app.bot.press(MARTE, Action.CANCEL_REFILL, refill.id)
    messages = len(app.chat.messages)

    app.run_until(oslo(11, 3, 18))  # timers run for a day and a half
    assert len(app.chat.messages) == messages  # no offers, reminders or alerts

    assert not app.bot.tap(LARS, old_button).ok
    assert refill.state == S.CANCELLED


def test_after_cancelling_a_new_empty_report_opens_a_new_refill(app):
    first = report(app, KARI, OSLO)
    app.bot.press(MARTE, Action.CANCEL_REFILL, first.id)

    second = report(app, KARI, OSLO)
    assert second is not first and second.state == S.OFFERED


def test_a_bought_refill_cannot_be_cancelled(app):
    refill = refill_now(app, OSLO, "845", reporter=KARI)
    result = app.bot.press(MARTE, Action.CANCEL_REFILL, refill.id)

    assert not result.ok and "hasn't been bought yet" in result.message
    assert refill.state == S.CLAIM_SUBMITTED


def test_only_the_office_admin_can_cancel(app):
    refill = report(app, KARI, OSLO)
    assert not app.bot.press(LARS, Action.CANCEL_REFILL, refill.id).ok   # a volunteer
    assert not app.bot.press(RAVI, Action.CANCEL_REFILL, refill.id).ok   # the other office's admin
    assert refill.state == S.OFFERED


def test_cancelled_refills_are_left_out_of_spend_and_the_report(app):
    refill = report(app, KARI, OSLO)
    app.bot.press(MARTE, Action.CANCEL_REFILL, refill.id)

    from snack_counter.reporting import monthly_report
    oslo_month = next(o for o in monthly_report(app.store, 2026, 11, "NOK").offices if o.office_name == "Oslo")
    assert oslo_month.refills == 0 and oslo_month.spent == Money(0, "NOK")
