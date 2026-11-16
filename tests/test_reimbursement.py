"""Claims are filed automatically, never twice, and tracked until paid."""

from datetime import timedelta

from conftest import accept, done, oslo, report

from snack_counter import budget
from snack_counter.actions import Action
from snack_counter.models import RefillState as S
from snack_counter.money import Money
from snack_counter.sample_data import KARI, LARS, MARTE, OSLO


def _bought(app, amount="845"):
    refill = report(app, KARI, OSLO)
    accept(app, LARS, refill)
    done(app, LARS, refill, amount, items=["Chips", "Fruit"])
    return refill


def test_claim_is_filed_on_completion_with_everything_hr_needs(app):
    refill = _bought(app)

    claim = app.hr.claims[refill.claim.hr_claim_id]
    assert claim["employee_id"] == LARS
    assert claim["amount"] == 845 and claim["currency"] == "NOK"
    assert claim["receipt"] == "receipt.jpg"
    assert claim["reference"] == refill.id
    assert "Oslo" in claim["description"] and "Chips, Fruit" in claim["description"]


def test_hr_outage_is_retried_without_the_volunteer_doing_anything(app):
    app.hr.down = True
    refill = _bought(app)
    assert refill.state == S.SUBMIT_PENDING
    assert "keep trying" in app.chat.last(LARS).text

    app.hr.down = False
    app.run_until(app.clock.now() + timedelta(minutes=5))
    assert refill.state == S.CLAIM_SUBMITTED
    assert "filed with HR" in app.chat.last(LARS).text


def test_a_lost_response_does_not_create_a_duplicate_claim(app):
    app.hr.lose_next_response = True  # HR creates the claim, but our request times out
    refill = _bought(app)
    assert refill.state == S.SUBMIT_PENDING

    app.run_until(app.clock.now() + timedelta(minutes=30))  # several retries
    assert refill.state == S.CLAIM_SUBMITTED
    assert len(app.hr.claims_for(refill.id)) == 1


def test_rejected_claim_tells_volunteer_and_admin_and_is_not_spend(app):
    refill = _bought(app)
    app.hr.reject(refill.claim.hr_claim_id, "Receipt unreadable")
    app.run_until(oslo(11, 3, 10))

    assert refill.state == S.REJECTED
    assert "Receipt unreadable" in app.chat.last(LARS).text
    assert "Receipt unreadable" in app.chat.last(MARTE).text
    assert budget.spent_in(app.store, app.store.offices[OSLO], 2026, 11) == Money(0, "NOK")


def test_claim_still_pending_after_10_days_is_chased(app):
    refill = _bought(app)  # filed Mon 2 Nov 09:00
    app.run_until(oslo(11, 12, 8, 55))
    assert app.chat.inbox(MARTE) == []

    app.run_until(oslo(11, 12, 9, 0))
    message = app.chat.last(MARTE)
    assert "pending with HR for 10 days" in message.text
    assert [b.label for b in message.buttons] == ["Mark claim followed up"]

    assert app.bot.press(MARTE, Action.MARK_FOLLOWED_UP, refill.id).ok
    assert refill.claim.followed_up
    app.run_until(oslo(11, 15, 10, 0))
    assert len(app.chat.inbox(MARTE)) == 2  # the alert and the reply; no repeat alert


def test_volunteers_can_see_what_they_are_owed(app):
    _bought(app)
    result = app.bot.press(LARS, Action.MY_STATUS)
    assert result.message.startswith("You're owed 845 NOK.")
    assert "with HR for approval" in result.message


def test_paid_back_claims_are_no_longer_owed(app):
    refill = _bought(app)
    app.hr.pay(refill.claim.hr_claim_id)
    app.run_until(oslo(11, 3, 10))

    assert refill.state == S.REIMBURSED
    assert "not owed anything" in app.bot.press(LARS, Action.MY_STATUS).message
