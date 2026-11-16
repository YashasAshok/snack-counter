"""The refill lifecycle, from "the box is empty" to "the volunteer is paid back"."""

from datetime import timedelta

from conftest import accept, done, oslo, refill_now, report

from snack_counter.models import RefillState as S
from snack_counter.sample_data import INGRID, KARI, LARS, OLA, OSLO


def test_empty_box_opens_a_refill_and_offers_it_to_one_person(app):
    refill = report(app, KARI, OSLO)

    assert refill.state == S.OFFERED
    assert refill.offer_to == LARS  # nobody has refilled yet, so lowest employee ID
    offer = app.chat.last(LARS)
    assert "Can you refill the Oslo box" in offer.text
    assert [b.label for b in offer.buttons] == ["I'll do it", "Can't today"]
    # nobody else was asked
    assert app.chat.inbox(INGRID) == [] and app.chat.inbox(OLA) == []


def test_second_empty_report_joins_the_open_refill(app):
    first = report(app, KARI, OSLO)
    second = report(app, OLA, OSLO)

    assert second is first
    assert len(app.store.refills) == 1
    assert first.reported_by == [KARI, OLA]
    assert "already being handled" in app.chat.last(OLA).text


def test_full_journey_from_empty_to_reimbursed(app):
    refill = report(app, KARI, OSLO)
    assert accept(app, LARS, refill).ok
    assert refill.state == S.COMMITTED

    assert done(app, LARS, refill, "845").ok
    assert refill.state == S.CLAIM_SUBMITTED
    claim_id = refill.claim.hr_claim_id

    app.hr.approve(claim_id)
    app.run_until(oslo(11, 3, 10))  # daily check of HR
    assert refill.state == S.APPROVED
    assert "approved" in app.chat.last(LARS).text

    app.hr.pay(claim_id)
    app.run_until(oslo(11, 4, 10))
    assert refill.state == S.REIMBURSED
    assert "paid back" in app.chat.last(LARS).text


def test_after_a_refill_is_done_a_new_empty_report_opens_a_new_refill(app):
    first = refill_now(app, OSLO, "845", reporter=KARI)
    second = report(app, KARI, OSLO)

    assert second is not first
    assert second.state == S.OFFERED


def test_report_outside_office_hours_waits_until_the_office_opens(app):
    app.run_until(oslo(11, 2, 18, 0))
    refill = report(app, KARI, OSLO)

    assert refill.state == S.OPEN
    assert "when the office opens" in app.chat.last(KARI).text
    assert app.chat.inbox(LARS) == []

    app.run_until(oslo(11, 3, 9, 0))
    assert refill.state == S.OFFERED
    assert refill.offer_to == LARS


def test_every_step_is_kept_in_the_refill_history(app):
    refill = refill_now(app, OSLO, "845", reporter=KARI)
    events = [event for _, event in refill.history]

    assert events[0] == "reported empty by Kari"
    assert "offered to Lars" in events
    assert any(e.startswith("taken by Lars") for e in events)
    assert any("filed with HR" in e for e in events)
