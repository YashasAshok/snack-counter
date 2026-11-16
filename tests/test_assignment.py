"""Choosing who buys: fair, and never someone who can't or shouldn't."""

from conftest import add_past_purchase, oslo, report

from snack_counter import assignment
from snack_counter.models import DateRange, RefillState
from snack_counter.sample_data import BENGALURU, INGRID, KARI, LARS, MARTE, OLA, OSLO, PRIYA


def _next(app):
    office = app.store.offices[OSLO]
    person = assignment.next_candidate(app.store, office, app.clock.now(), app.settings, app.fx)
    return person.id if person else None


def _eligible(app, office_id=OSLO):
    office = app.store.offices[office_id]
    return {p.id for p in assignment.eligible_volunteers(app.store, office, app.clock.now(), app.fx)}


def test_picks_the_person_with_the_fewest_recent_refills(app):
    add_past_purchase(app, LARS, OSLO, oslo(10, 1), 800)
    add_past_purchase(app, LARS, OSLO, oslo(10, 15), 800)
    add_past_purchase(app, INGRID, OSLO, oslo(10, 20), 800)
    add_past_purchase(app, PRIYA, OSLO, oslo(10, 25), 800)

    assert _next(app) == OLA  # the only one with none


def test_tie_goes_to_whoever_refilled_longest_ago(app):
    add_past_purchase(app, LARS, OSLO, oslo(10, 20), 800)
    add_past_purchase(app, INGRID, OSLO, oslo(10, 5), 800)
    add_past_purchase(app, OLA, OSLO, oslo(10, 15), 800)
    add_past_purchase(app, PRIYA, OSLO, oslo(10, 25), 800)

    assert _next(app) == INGRID


def test_refills_older_than_90_days_dont_count(app):
    for day in (1, 2, 3):
        add_past_purchase(app, LARS, OSLO, oslo(7, day), 800)       # over 90 days ago
    for person_id in (INGRID, OLA, PRIYA):
        add_past_purchase(app, person_id, OSLO, oslo(10, 1), 800)   # recent

    assert _next(app) == LARS


def test_non_volunteers_and_admins_are_never_asked(app):
    assert _eligible(app) == {LARS, INGRID, OLA, PRIYA}
    assert KARI not in _eligible(app) and MARTE not in _eligible(app)


def test_people_who_are_away_are_skipped(app):
    app.store.people[LARS].away.append(DateRange(oslo(11, 1).date(), oslo(11, 6).date()))
    assert LARS not in _eligible(app)
    assert _next(app) == INGRID


def test_someone_already_holding_a_refill_is_skipped(app):
    other = add_past_purchase(app, LARS, BENGALURU, oslo(11, 2), 0, state=RefillState.COMMITTED)
    other.purchase = None
    assert LARS not in _eligible(app)


def test_people_owed_more_than_the_cap_are_skipped(app):
    add_past_purchase(app, LARS, OSLO, oslo(10, 20), 1200, state=RefillState.CLAIM_SUBMITTED)
    add_past_purchase(app, LARS, OSLO, oslo(10, 28), 900, state=RefillState.APPROVED)   # owed 2 100 NOK
    add_past_purchase(app, INGRID, OSLO, oslo(10, 20), 2000, state=RefillState.CLAIM_SUBMITTED)  # exactly the cap

    assert LARS not in _eligible(app)
    assert INGRID in _eligible(app)


def test_money_owed_in_both_currencies_is_converted_before_comparing_to_the_cap(app):
    add_past_purchase(app, PRIYA, OSLO, oslo(10, 20), 1000, state=RefillState.CLAIM_SUBMITTED)
    add_past_purchase(app, PRIYA, BENGALURU, oslo(10, 22), 9000, state=RefillState.CLAIM_SUBMITTED)
    # 1 000 NOK + 9 000 INR × 0.12 = 2 080 NOK > 2 000 NOK cap
    assert PRIYA not in _eligible(app)


def test_paid_back_money_doesnt_count_as_owed(app):
    add_past_purchase(app, LARS, OSLO, oslo(10, 20), 3000, state=RefillState.REIMBURSED)
    assert LARS in _eligible(app)


def test_the_reason_someone_isnt_eligible_is_explainable(app):
    office = app.store.offices[OSLO]
    kari = app.store.people[KARI]
    assert assignment.why_not_eligible(app.store, kari, office, app.clock.now(), app.fx) == "not on the volunteer list"


def test_offers_rotate_fairly_over_several_refills(app):
    from conftest import refill_now
    buyers = [refill_now(app, OSLO, "500", reporter=KARI).purchase.buyer_id for _ in range(4)]
    assert buyers == [LARS, INGRID, OLA, PRIYA]
