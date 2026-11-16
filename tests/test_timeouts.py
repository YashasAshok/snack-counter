"""A refill nobody completes is handed to someone else."""

from conftest import accept, oslo, report

from snack_counter.actions import Action
from snack_counter.models import RefillState as S
from snack_counter.sample_data import INGRID, KARI, LARS, MARTE, OLA, OSLO, PRIYA


def test_unanswered_offer_moves_to_the_next_person_after_2_hours(app):
    refill = report(app, KARI, OSLO)
    assert refill.offer_to == LARS

    app.run_until(oslo(11, 2, 10, 55))
    assert refill.offer_to == LARS  # still Lars's turn

    app.run_until(oslo(11, 2, 11, 0))
    assert refill.offer_to == INGRID
    assert "passed the Oslo refill on" in app.chat.inbox(LARS)[-1].text


def test_declining_moves_to_the_next_person_immediately(app):
    refill = report(app, KARI, OSLO)
    assert app.bot.press(LARS, Action.DECLINE, refill.id, reason="WFH").ok
    assert refill.offer_to == INGRID


def test_after_three_failed_direct_offers_it_is_broadcast(app):
    refill = report(app, KARI, OSLO)
    app.bot.press(LARS, Action.DECLINE, refill.id)       # said no
    app.run_until(oslo(11, 2, 13, 0))                      # Ingrid didn't reply
    app.run_until(oslo(11, 2, 15, 0))                      # Ola didn't reply

    assert refill.state == S.BROADCAST
    # People who said no are not asked again; people who just didn't reply are
    assert set(refill.broadcast_to) == {INGRID, OLA, PRIYA}


def test_unfinished_refill_is_handed_to_someone_else(app):
    refill = report(app, KARI, OSLO)
    accept(app, LARS, refill)

    app.run_until(oslo(11, 3, 9, 5))  # 24 hours later, not done

    assert refill.state == S.OFFERED
    assert refill.offer_to == INGRID
    assert refill.committed_by is None
    assert "Time's up" in app.chat.inbox(LARS)[-1].text


def test_reminder_is_sent_halfway_through(app):
    refill = report(app, KARI, OSLO)
    accept(app, LARS, refill)

    app.run_until(oslo(11, 2, 21, 0))  # 12 hours after accepting

    reminder = app.chat.last(LARS)
    assert reminder.text.startswith("Reminder")
    assert [b.label for b in reminder.buttons] == ["Mark as done", "Can't make it after all"]


def test_handing_back_reassigns_immediately_and_starts_fresh_offers(app):
    refill = report(app, KARI, OSLO)
    accept(app, LARS, refill)

    assert app.bot.press(LARS, Action.RELEASE, refill.id).ok
    assert refill.state == S.OFFERED
    assert refill.offer_to == INGRID
    assert refill.direct_offers == 1


def test_admin_is_told_when_nobody_has_taken_it_by_the_end_of_the_day(app):
    refill = report(app, KARI, OSLO)
    app.run_until(oslo(11, 2, 16, 55))
    assert app.chat.inbox(MARTE) == []

    app.run_until(oslo(11, 2, 17, 0))
    message = app.chat.last(MARTE)
    assert "still has no buyer" in message.text
    assert "Assign to…" in [b.label for b in message.buttons]

    # Only once per day
    app.run_until(oslo(11, 2, 20, 0))
    assert len(app.chat.inbox(MARTE)) == 1


def test_admin_assign_sends_a_direct_offer(app):
    refill = report(app, KARI, OSLO)
    result = app.bot.press(MARTE, Action.ASSIGN, refill.id, person=OLA)

    assert result.ok
    assert refill.offer_to == OLA
    assert "still need to accept" in result.message
    assert "passed to someone else" in app.chat.last(LARS).text


def test_admin_is_told_straight_away_when_nobody_is_available(app):
    for person_id in (LARS, INGRID, OLA, PRIYA):
        app.store.people[person_id].is_volunteer = False

    refill = report(app, KARI, OSLO)

    assert refill.state == S.OPEN
    assert "Nobody is available" in app.chat.last(MARTE).text
    assert "told the office admin" in app.chat.last(KARI).text
