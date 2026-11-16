"""Two people cannot both commit to the same refill."""

import threading

import pytest
from conftest import accept, oslo, report

from snack_counter.actions import Action
from snack_counter.models import RefillState as S
from snack_counter.sample_data import INGRID, KARI, LARS, OLA, OSLO, PRIYA


def _broadcast_refill(app):
    """Nobody answers three direct offers, so the refill is offered to everyone at once."""
    refill = report(app, KARI, OSLO)
    app.run_until(oslo(11, 2, 15, 0))  # three 2-hour offers expire
    assert refill.state == S.BROADCAST
    assert set(refill.broadcast_to) == {LARS, INGRID, OLA, PRIYA}
    return refill


@pytest.mark.parametrize("attempt", range(20))
def test_two_people_cannot_commit_to_the_same_refill(app, attempt):
    refill = _broadcast_refill(app)
    start = threading.Barrier(2)
    results = {}

    def tap(person_id):
        start.wait()  # both tap at the same instant
        results[person_id] = app.bot.press(person_id, Action.ACCEPT, refill.id)

    threads = [threading.Thread(target=tap, args=(p,)) for p in (LARS, OLA)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    winners = [p for p, r in results.items() if r.ok]
    assert len(winners) == 1
    assert refill.committed_by == winners[0]
    loser = (set(results) - set(winners)).pop()
    assert "already been taken" in results[loser].message


def test_everyone_else_is_told_who_took_the_broadcast(app):
    refill = _broadcast_refill(app)
    assert accept(app, INGRID, refill).ok

    for other in (LARS, OLA, PRIYA):
        assert "Ingrid is refilling the Oslo box" in app.chat.last(other).text


def test_only_one_refill_per_office_even_when_reported_at_the_same_instant(app):
    start = threading.Barrier(5)
    people = [KARI, LARS, INGRID, OLA, PRIYA]

    def tap(person_id):
        start.wait()
        app.bot.press(person_id, Action.REPORT_EMPTY, office=OSLO)

    threads = [threading.Thread(target=tap, args=(p,)) for p in people]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(app.store.refills) == 1
    assert sorted(next(iter(app.store.refills.values())).reported_by) == sorted(people)
